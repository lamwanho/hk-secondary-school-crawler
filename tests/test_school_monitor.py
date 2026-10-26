"""Contract tests for the bounded school notice monitor (stdlib unittest)."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "school-monitor.py"


def load_monitor():
    if not SCRIPT.exists():
        return None
    spec = importlib.util.spec_from_file_location("school_monitor", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.m = load_monitor()
        self.assertIsNotNone(self.m, "school monitor has not been implemented")
        self.now = "2026-10-26T00:15:00Z"
        self.school = {"id": "sample", "website": "https://school.edu.hk/", "events": [], "sources": []}

    def page(self, url, html):
        return {"url": url, "text": html, "content_type": "text/html", "http_status": 200}

    def test_selects_school_and_confirmed_general_social_without_chsc_gate(self):
        self.school["events"] = [{"source_urls": ["https://school.edu.hk/admissions", "https://www.chsc.hk/day"]}]
        self.school["official_social_accounts"] = [
            {"url": "https://www.facebook.com/school", "role": "general", "official_evidence_url": "https://school.edu.hk/contact"},
            {"url": "https://www.instagram.com/sports", "role": "sports", "official_evidence_url": "https://school.edu.hk/"},
            {"url": "https://www.facebook.com/unconfirmed", "role": "general", "official_evidence_url": None},
        ]
        urls = [s["url"] for s in self.m.select_sources(self.school)]
        self.assertEqual(urls, ["https://school.edu.hk/", "https://school.edu.hk/admissions", "https://www.facebook.com/school"])

    def test_relevant_2027_notice_excludes_sports_prizes_and_infers_no_date(self):
        html = '<title>School news</title><a href="/prize">2027 Sports Prize</a><a href="/s1">2027 S1 Admissions briefing — 12 November 2026</a><p>Open day registration details coming soon.</p>'
        notices, links = self.m.extract_notices("https://school.edu.hk/", html)
        self.assertTrue(any("2027 S1" in n["title"] for n in notices))
        self.assertFalse(any("Sports" in n["title"] for n in notices))
        dated = next(n for n in notices if "2027 S1" in n["title"])
        self.assertIn("12 November 2026", dated["date_mentions"])
        self.assertEqual(dated["status"], "review_required")
        self.assertNotIn("start_date", dated)
        undated = next(n for n in notices if "coming soon" in n["snippet"])
        self.assertEqual(undated["date_mentions"], [])

    def test_unrelated_sports_history_labels_are_not_admissions_notices_from_path_alone(self):
        html = '<a href="/admission/sports-prize">2027 Sports Prize</a><a href="/admission/History_Web.pdf">School History</a><a href="/admission/briefing">S1 admissions briefing</a>'
        notices, links = self.m.extract_notices(self.school["website"], html)
        self.assertFalse(any("Sports Prize" in n["title"] or "School History" in n["title"] for n in notices))
        self.assertNotIn("https://school.edu.hk/admission/History_Web.pdf", links)
        self.assertIn("https://school.edu.hk/admission/briefing", links)

    def test_discovery_is_same_host_and_ignores_search_and_logout(self):
        html = '<a href="/news">News</a><a href="https://evil.test/admissions">Admissions</a><a href="/apply?year=2027">2027 Admissions</a><a href="/logout">Admission logout</a><a href="javascript:void(0)">Open Day</a>'
        _, links = self.m.extract_notices("https://school.edu.hk/", html)
        self.assertIn("https://school.edu.hk/apply?year=2027", links)
        self.assertIn("https://school.edu.hk/news", links)
        self.assertNotIn("https://evil.test/admissions", links)
        self.assertFalse(any("logout" in u for u in links))

    def test_failed_source_retains_last_good_and_notices(self):
        old = {"id": "sample", "sources": [{"url": self.school["website"], "status": "ok", "last_success_at": "2026-10-25T00:15:00Z", "content_hash": "oldhash"}], "notices": [{"url": self.school["website"], "source_url": self.school["website"], "title": "Open day", "snippet": "Open day", "date_mentions": [], "first_seen_at": "2026-10-25T00:15:00Z", "last_seen_at": "2026-10-25T00:15:00Z", "status": "review_required"}]}
        def failed(url, previous=None):
            raise self.m.FetchError("http_error", "HTTP 403", 403)
        result = self.m.monitor_school(self.school, old, self.now, fetcher=failed, max_pages=2)
        self.assertEqual(result["sources"][0]["content_hash"], "oldhash")
        self.assertEqual(result["sources"][0]["last_success_at"], "2026-10-25T00:15:00Z")
        self.assertEqual(result["sources"][0]["status"], "http_error")
        self.assertEqual(result["notices"], old["notices"])
        self.assertNotEqual(result["status"], "ok")

    def test_success_hash_change_is_fetch_evidence_only_and_pilot_unchanged(self):
        before = copy.deepcopy(self.school)
        def fetched(url, previous=None):
            return self.page(url, '<title>S1 Admissions 2027</title><p>Apply by 2026年11月12日</p>')
        first = self.m.monitor_school(self.school, {}, self.now, fetcher=fetched, max_pages=1)
        again = self.m.monitor_school(self.school, first, "2026-10-27T00:15:00Z", fetcher=fetched, max_pages=1)
        self.assertIsNone(first["sources"][0]["changed"])
        self.assertFalse(again["sources"][0]["changed"])
        self.assertEqual(again["notices"][0]["first_seen_at"], self.now)
        self.assertEqual(again["notices"][0]["last_seen_at"], "2026-10-27T00:15:00Z")
        self.assertEqual(before, self.school)
        self.assertTrue(all(n["status"] == "review_required" for n in again["notices"]))

    def test_social_login_shell_is_not_success(self):
        self.school["official_social_accounts"] = [{"url": "https://www.facebook.com/school", "role": "general", "official_evidence_url": self.school["website"]}]
        def fetched(url, previous=None):
            return self.page(url, '<title>Log in to Facebook</title><p>Log in or sign up</p>') if "facebook" in url else self.page(url, '<title>School</title><p>Welcome to our school.</p>')
        result = self.m.monitor_school(self.school, {}, self.now, fetcher=fetched, max_pages=2)
        source = next(s for s in result["sources"] if "facebook" in s["url"])
        self.assertEqual(source["status"], "social_unavailable")
        self.assertNotIn("last_success_at", source)

    def test_social_hidden_post_url_cannot_make_login_shell_successful(self):
        self.school["official_social_accounts"] = [{"url": "https://www.facebook.com/school", "role": "general", "official_evidence_url": self.school["website"]}]
        def fetched(url, previous=None):
            return self.page(url, '<title>Log in to Facebook</title><p>Admissions</p><script>const teaser="https://facebook.com/school/posts/123";</script>') if "facebook" in url else self.page(url, '<title>School</title><p>Welcome to our school.</p>')
        result = self.m.monitor_school(self.school, {}, self.now, fetcher=fetched, max_pages=2)
        source = next(s for s in result["sources"] if "facebook" in s["url"])
        self.assertEqual(source["status"], "social_unavailable")
        self.assertNotIn("last_success_at", source)

    def test_visible_relevant_social_post_link_is_required(self):
        self.school["official_social_accounts"] = [{"url": "https://www.facebook.com/school", "role": "general", "official_evidence_url": self.school["website"]}]
        def fetched(url, previous=None):
            return self.page(url, '<title>School | Facebook</title><a href="https://www.facebook.com/school/posts/123">S1 Admissions briefing 2027 — 12 November 2026</a>') if "facebook" in url else self.page(url, '<title>School</title><p>Welcome to our school.</p>')
        result = self.m.monitor_school(self.school, {}, self.now, fetcher=fetched, max_pages=2)
        source = next(s for s in result["sources"] if "facebook" in s["url"])
        self.assertEqual(source["status"], "ok")
        self.assertTrue(any("/posts/123" in n["url"] for n in result["notices"]))

    def test_unchanged_304_keeps_existing_candidates(self):
        old = {"sources": [{"url": self.school["website"], "content_hash": "old", "etag": '"test"', "last_success_at": "2026-10-25T00:15:00Z"}], "notices": [{"url": self.school["website"], "source_url": self.school["website"], "title": "Open Day", "status": "review_required", "first_seen_at": "2026-10-25T00:15:00Z", "last_seen_at": "2026-10-25T00:15:00Z"}]}
        old["sources"][0]["current_notice_keys"] = [[self.school["website"], "Open Day"]]
        result = self.m.monitor_school(self.school, old, self.now, fetcher=lambda u, p=None: {"url": u, "http_status": 304}, max_pages=1)
        self.assertFalse(result["sources"][0]["changed"])
        self.assertEqual(result["notices"][0]["last_seen_at"], self.now)

    def test_source_budget_preserves_unchecked_last_good_sources(self):
        old = {"sources": [{"url": "https://school.edu.hk/old-admissions", "content_hash": "old", "last_success_at": "yesterday"}], "notices": []}
        result = self.m.monitor_school(self.school, old, self.now, fetcher=lambda u,p=None: self.page(u, '<title>School</title><p>Welcome to our school.</p>'), max_pages=1)
        unchecked = next(s for s in result["sources"] if "old-admissions" in s["url"])
        self.assertEqual(unchecked["status"], "not_checked_budget")
        self.assertEqual(unchecked["content_hash"], "old")

    def test_confirmed_social_is_not_starved_by_historical_sources(self):
        self.school["events"] = [{"source_urls": [f"https://school.edu.hk/open-day/{year}" for year in range(2010, 2027)]}]
        self.school["official_social_accounts"] = [{"url": "https://www.facebook.com/school", "role": "general", "official_evidence_url": self.school["website"]}]
        result = self.m.monitor_school(self.school, {}, self.now, fetcher=lambda u,p=None: self.page(u, '<title>School</title><p>Welcome to our school.</p>'), max_pages=2)
        social = next(s for s in result["sources"] if "facebook" in s["url"])
        self.assertEqual(social["status"], "social_unavailable")

    def test_live_numeric_notice_precedes_many_historical_sources(self):
        self.school["events"] = [{"source_urls": [f"https://school.edu.hk/open-day/{year}" for year in range(2010, 2027)]}]
        fetched_urls = []
        def fetched(url, previous=None):
            fetched_urls.append(url)
            html = '<a href="/node/123">S1 Admissions briefing 2027</a><a href="/node/456">News</a>' if url == self.school["website"] else '<title>Open Day 2027</title><p>Welcome to our school.</p>'
            return self.page(url, html)
        self.m.monitor_school(self.school, {}, self.now, fetcher=fetched)
        self.assertIn("https://school.edu.hk/node/123", fetched_urls)
        self.assertIn("https://school.edu.hk/node/456", fetched_urls)

    def test_equal_ranked_notice_links_preserve_document_order(self):
        html = '<a href="/notice?id=999">S1 Admissions 2027 latest notice</a>' + ''.join(f'<a href="/notice?id={i:03d}">S1 Admissions 2027 earlier notice</a>' for i in range(25))
        _, links = self.m.extract_notices(self.school["website"], html)
        self.assertEqual(links[0], "https://school.edu.hk/notice?id=999")

    def test_2027_label_gives_numeric_notice_priority_over_older_labels(self):
        html = ''.join(f'<a href="/notice?id={i:03d}">S1 Admissions 2026 notice</a>' for i in range(25)) + '<a href="/notice?id=999">S1 Admissions 2027</a>'
        _, links = self.m.extract_notices(self.school["website"], html)
        self.assertEqual(links[0], "https://school.edu.hk/notice?id=999")

    def test_prior_discovered_numeric_notice_precedes_historical_seeds(self):
        self.school["events"] = [{"source_urls": [f"https://school.edu.hk/open-day/{year}" for year in range(2010, 2027)]}]
        old = {"sources": [{"url": "https://school.edu.hk/node/123", "kind": "discovered_school_page", "checked_at": "2026-10-25T00:15:00Z"}], "notices": []}
        fetched_urls = []
        def fetched(url, previous=None):
            fetched_urls.append(url)
            return self.page(url, '<title>School</title><p>Welcome to our school.</p>')
        self.m.monitor_school(self.school, old, self.now, fetcher=fetched)
        self.assertIn("https://school.edu.hk/node/123", fetched_urls)

    def test_discovered_budget_rotates_when_root_returns_304(self):
        old = {"sources": [{"url": self.school["website"], "content_hash": "root", "checked_at": "2026-10-25T00:15:00Z"}] + [
            {"url": f"https://school.edu.hk/node/{i}", "kind": "discovered_school_page", "status": "not_checked_budget"} for i in range(5)
        ], "notices": []}
        def fetched(url, previous=None):
            return {"url": url, "http_status": 304} if url == self.school["website"] else self.page(url, '<title>School</title><p>Welcome to our school.</p>')
        first = self.m.monitor_school(self.school, old, self.now, fetcher=fetched, max_pages=3)
        second = self.m.monitor_school(self.school, first, "2026-10-27T00:15:00Z", fetcher=fetched, max_pages=3)
        before = {s["url"] for s in first["sources"] if s["status"] == "ok"} - {self.school["website"]}
        after = {s["url"] for s in second["sources"] if s["status"] == "ok"} - {self.school["website"]}
        self.assertTrue(before.isdisjoint(after))
        self.assertEqual(len(after), 2)

    def test_stable_admissions_seed_precedes_dated_historical_seed(self):
        self.school["events"] = [{"source_urls": [f"https://school.edu.hk/2026/open-day/{i}" for i in range(15)]}]
        self.school["sources"] = [{"url": "https://school.edu.hk/admissions", "type": "school_website"}]
        urls = []
        def fetched(url, previous=None):
            urls.append(url)
            return self.page(url, '<title>School</title><p>Welcome to our school.</p>')
        self.m.monitor_school(self.school, {}, self.now, fetcher=fetched)
        self.assertIn("https://school.edu.hk/admissions", urls)

    def test_stable_admissions_seed_is_not_starved_by_retained_discoveries(self):
        self.school["sources"] = [{"url": "https://school.edu.hk/admissions", "type": "school_website"}]
        old = {"sources": [{"url": f"https://school.edu.hk/node/{i}", "kind": "discovered_school_page"} for i in range(39)], "notices": []}
        urls = []
        def fetched(url, previous=None):
            urls.append(url)
            return self.page(url, '<title>School</title><p>Welcome to our school.</p>')
        self.m.monitor_school(self.school, old, self.now, fetcher=fetched)
        self.assertIn("https://school.edu.hk/admissions", urls)

    def test_new_notice_still_discovered_after_source_history_reaches_cap(self):
        old = {"sources": [{"url": f"https://school.edu.hk/node/{i}", "kind": "discovered_school_page"} for i in range(40)], "notices": []}
        fetched_urls = []
        def fetched(url, previous=None):
            fetched_urls.append(url)
            return self.page(url, '<a href="/node/new">S1 Admissions 2027</a>' if url == self.school["website"] else '<title>School</title><p>Welcome to our school.</p>')
        result = self.m.monitor_school(self.school, old, self.now, fetcher=fetched)
        self.assertIn("https://school.edu.hk/node/new", fetched_urls)
        self.assertLessEqual(len(result["sources"]), 40)

    def test_run_deadline_defers_work_and_preserves_last_good_evidence(self):
        old = {"sources": [{"url": self.school["website"], "content_hash": "good", "checked_at": "yesterday"}], "notices": []}
        def forbidden(url, previous=None):
            self.fail("expired run must not start another fetch")
        result = self.m.monitor_school(self.school, old, self.now, fetcher=forbidden, deadline=0)
        self.assertEqual(result["sources"][0]["status"], "not_checked_budget")
        self.assertEqual(result["sources"][0]["content_hash"], "good")
        self.assertEqual(result["sources"][0]["checked_at"], "yesterday")
        self.assertIsNone(result.get("checked_at"))
        self.assertEqual(result.get("attempted_sources"), 0)

    def test_removed_historical_notice_is_retained_after_successful_empty_page(self):
        notice = {"url": self.school["website"], "source_url": self.school["website"], "title": "Open Day 2024", "status": "review_required", "last_seen_at": "2024-11-01"}
        result = self.m.monitor_school(self.school, {"notices": [notice]}, self.now,
            fetcher=lambda u, p=None: self.page(u, "<title>School</title><p>Welcome to our school.</p>"), max_pages=1)
        self.assertEqual(result["notices"], [notice])

    def test_html_with_no_visible_body_text_preserves_last_good_evidence(self):
        notice = {"url": self.school["website"], "title": "Open Day 2024", "status": "review_required", "last_seen_at": "yesterday"}
        old = {"sources": [{"url": self.school["website"], "content_hash": "good", "last_success_at": "yesterday"}], "notices": [notice]}
        for html in ('<!doctype html><html><head><script>app()</script></head><body><div id="root"></div></body></html>',
                     '<html><head><title>School</title><style>body { color: red; }</style></head><body> </body></html>',
                     '<html><body><!-- no readable content --></body></html>'):
            with self.subTest(html=html):
                result = self.m.monitor_school(self.school, old, self.now,
                    fetcher=lambda u, p=None: self.page(u, html), max_pages=1)
                source = result["sources"][0]
                self.assertEqual(source["status"], "no_extractable_text")
                self.assertEqual(source["content_hash"], "good")
                self.assertEqual(source["last_success_at"], "yesterday")
                self.assertEqual(result["notices"], [notice])

    def test_visible_school_body_without_admissions_notice_is_still_successful(self):
        result = self.m.monitor_school(self.school, {}, self.now,
            fetcher=lambda u, p=None: self.page(u, '<title>School</title><body><p>Welcome to our school.</p></body>'), max_pages=1)
        self.assertEqual(result["sources"][0]["status"], "ok")
        self.assertEqual(result["notices"], [])

    def test_304_does_not_refresh_archived_notice_removed_from_latest_body(self):
        first = self.m.monitor_school(self.school, {}, "2026-10-24T00:00:00Z",
            fetcher=lambda u, p=None: self.page(u, '<p>S1 Open Day A 2027</p>'), max_pages=1)
        second = self.m.monitor_school(self.school, first, "2026-10-25T00:00:00Z",
            fetcher=lambda u, p=None: self.page(u, '<p>Welcome to our school.</p>'), max_pages=1)
        third = self.m.monitor_school(self.school, second, "2026-10-26T00:00:00Z",
            fetcher=lambda u, p=None: {"url": u, "http_status": 304}, max_pages=1)
        self.assertEqual(third["sources"][0]["status"], "ok")
        self.assertEqual(third["notices"][0]["last_seen_at"], "2026-10-24T00:00:00Z")

    def test_notice_history_survives_more_than_thirty_candidates(self):
        notices = [{"url": f"https://school.edu.hk/{i}", "title": f"Open Day 2024 {i}", "status": "review_required"} for i in range(35)]
        result = self.m.monitor_school(self.school, {"notices": notices}, self.now,
            fetcher=lambda u, p=None: self.page(u, "<title>School</title><p>Welcome to our school.</p>"), max_pages=1)
        self.assertEqual(len(result["notices"]), 35)

    def test_deeper_scan_gives_historical_endpoints_a_rotating_slot(self):
        self.school["events"] = [{"source_urls": ["https://school.edu.hk/open-day/2024", "https://school.edu.hk/open-day/2025"]}]
        old = {"sources": [{"url": f"https://school.edu.hk/node/{i}", "kind": "discovered_school_page"} for i in range(10)]}
        urls = []
        def fetched(url, previous=None):
            urls.append(url)
            return self.page(url, "<title>School</title><p>Welcome to our school.</p>")
        self.m.monitor_school(self.school, old, self.now, fetcher=fetched, max_pages=3, scan_mode="deep")
        self.assertIn("https://school.edu.hk/open-day/2024", urls)

    def test_daily_does_not_spend_key_page_budget_on_old_dated_seeds(self):
        self.school["events"] = [{"source_urls": [f"https://school.edu.hk/open-day/{year}" for year in (2024, 2025)]}]
        urls = []
        def fetched(url, previous=None):
            urls.append(url)
            return self.page(url, "<title>School</title><p>Welcome to our school.</p>")
        result = self.m.monitor_school(self.school, {}, self.now, fetcher=fetched, max_pages=4)
        self.assertEqual(urls, [self.school["website"]])
        self.assertEqual(result["attempted_sources"], 1)
        self.assertEqual(len([s for s in result["sources"] if s["status"] == "not_checked_budget"]), 2)

    def test_non_descriptive_discovered_url_survives_homepage_failure(self):
        old = {"sources": [{"url": "https://school.edu.hk/node/123", "kind": "discovered_school_page", "content_hash": "good", "last_success_at": "yesterday"}], "notices": []}
        def failed(url, previous=None):
            raise self.m.FetchError("network_error", "timeout")
        result = self.m.monitor_school(self.school, old, self.now, fetcher=failed, max_pages=1)
        retained = next((s for s in result["sources"] if s["url"].endswith("/node/123")), None)
        self.assertIsNotNone(retained)
        self.assertEqual(retained["content_hash"], "good")

    def test_deferred_sources_make_coverage_partial(self):
        self.school["events"] = [{"source_urls": ["https://school.edu.hk/admissions"]}]
        result = self.m.monitor_school(self.school, {}, self.now, fetcher=lambda u,p=None: self.page(u, '<title>School</title><p>Welcome to our school.</p>'), max_pages=1)
        self.assertEqual(result["status"], "partial")

    def test_http_refusal_stops_further_requests_to_host(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(404 if self.path == "/robots.txt" else 403)
                self.end_headers()
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            fetcher = self.m.PoliteFetcher(timeout=2)
            root = f"http://127.0.0.1:{server.server_port}"
            with self.assertRaises(self.m.FetchError):
                fetcher(root + "/")
            with self.assertRaises(self.m.FetchError):
                fetcher(root + "/admissions")
            self.assertEqual(requests, ["/robots.txt", "/"])
        finally:
            server.shutdown()
            server.server_close()

    def test_history_contains_bounded_evidence_and_retention(self):
        payload = {"checked_at": self.now, "run_status": "ok", "summary": {}, "schools": [{"id": "sample", "sources": [], "notices": [{"title": "Open Day", "snippet": "x"*2000, "url": "https://school.edu.hk/a", "status": "review_required"}]}]}
        with tempfile.TemporaryDirectory(dir=SCRIPT.parent.parent / "tests") as tmp:
            root = Path(tmp)
            self.m.save_monitor(payload, root / "monitor.json", history_limit=2)
            for day in (27, 28):
                payload["checked_at"] = f"2026-10-{day}T00:15:00Z"
                self.m.save_monitor(payload, root / "monitor.json", history_limit=2)
            files = list((root / "monitor-history").glob("*.json"))
            self.assertEqual(len(files), 2)
            history = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertLessEqual(len(history["schools"][0]["notices"][0]["snippet"]), 280)

    def test_fetches_real_http_and_sends_conditional_headers(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(dict(self.headers))
                self.send_response(304 if self.headers.get("If-None-Match") else 200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("ETag", '"fixture"')
                self.end_headers()
                if not self.headers.get("If-None-Match"):
                    html = '<html><head><script>app()</script></head><body><div id="root"></div></body></html>' if self.path == "/empty" else '<title>Open day 2027</title><p>Welcome to our school.</p>'
                    self.wfile.write(html.encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/"
            result = self.m.fetch_url(url)
            self.assertIn("Open day", result["text"])
            second = self.m.fetch_url(url, {"etag": result["etag"]})
            self.assertEqual(second["http_status"], 304)
            self.assertIn("hk-secondary-school-crawler", requests[0]["User-Agent"])
            self.assertEqual(requests[1]["If-None-Match"], '"fixture"')
            with self.assertRaises(self.m.FetchError) as caught:
                self.m.fetch_url(url + "empty")
            self.assertEqual(caught.exception.status, "no_extractable_text")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
