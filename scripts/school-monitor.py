#!/usr/bin/env python3
"""Bounded, independent school notice discovery; never verifies event dates.

Only short notice excerpts, hashes and fetch metadata are persisted. The curated
roster is an input, never an output. See docs/OPERATIONS.md for the contract.
"""
import argparse
import copy
import hashlib
from html import unescape
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

USER_AGENT = "hk-secondary-school-crawler/1.0 (+https://github.com/lamwanho/hk-secondary-school-crawler)"
MAX_BYTES = 3 * 1024 * 1024
MAX_NOTICES = 30
MAX_SOURCES = 40
RELEVANCE = re.compile(r"open[\s_-]*days?|information[\s_-]*days?|info[\s_-]*days?|admissions?|form[\s_-]*(?:1|one)|\bs[\s_-]*1\b|briefing|taster[\s_-]*days?|開放日|开放日|資訊日|信息日|升中|中一|招生|入學|入学|小六", re.I)
HUB = re.compile(r"news|notice|events?|calendar|announcement|消息|通告|活動|最新", re.I)
UNRELATED_LABEL = re.compile(r"\bsports?\b|\bathletics?\b|\bprizes?\b|\bawards?\b|\bhistory\b|\balumni\b|運動|體育|獲獎|得獎|校史", re.I)
SKIP = re.compile(r"logout|signout|[?&](?:s|search|keyword)=|\.(?:jpg|jpeg|png|gif|webp|svg|mp4|mp3|zip|docx?|xlsx?)(?:\?|$)", re.I)
DATE_PATTERN = re.compile(r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s*,?\s*20\d{2}\b|\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?\s*,?\s*20\d{2}\b|\b20\d{2}\s*[/–-]\s*(?:20)?\d{2}\b|\b20\d{2}\b", re.I)


class FetchError(Exception):
    def __init__(self, status, message, http_status=None):
        super().__init__(message)
        self.status = status
        self.http_status = http_status


def clean(value):
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def host(url):
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def safe_url(url):
    try:
        parsed = urlsplit(url)
        return bool(parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username and not parsed.password)
    except ValueError:
        return False


def social_url(url):
    return host(url) in ("facebook.com", "m.facebook.com", "instagram.com")


def select_sources(school):
    """School sources run independently of CHSC and unconfirmed social leads."""
    root = school.get("website", "")
    sources = []
    seen = set()
    def add(url, kind="school_website", **metadata):
        if safe_url(url) and url not in seen:
            seen.add(url)
            sources.append({"url": url, "kind": kind, **metadata})
    add(root)
    candidates = []
    for event in school.get("events", []):
        candidates.extend(event.get("source_urls", []))
    for source in school.get("sources", []):
        if source.get("type") == "school_website":
            candidates.append(source.get("url", ""))
    # Historical evidence is checked only when it concerns admissions or events.
    candidates = sorted(set(candidates), key=lambda u: ("2027" not in u, "2026" not in u, u))
    for url in candidates:
        if host(url) == host(root):
            add(url)
    for account in school.get("official_social_accounts", []):
        url = account.get("url") or ""
        if account.get("role") in ("general", "admissions") and account.get("official_evidence_url") and social_url(url):
            add(url, "official_social", role=account["role"], official_evidence_url=account["official_evidence_url"])
    return sources


class NoticeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.blocks = []
        self.block = []
        self.anchor = None
        self.title = []
        self.in_title = False
        self.hidden = 0

    def flush(self):
        text = clean(" ".join(self.block))
        if text:
            self.blocks.append(text)
        self.block = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.hidden += 1
        if self.hidden:
            return
        if tag in ("p", "li", "div", "section", "article", "br", "h1", "h2", "h3", "tr", "a"):
            self.flush()
        if tag == "title":
            self.in_title = True
        if tag == "a":
            attributes = dict(attrs)
            self.anchor = {"href": attributes.get("href", ""), "text": [attributes.get("title", "")]}
        if tag == "img":
            alt = dict(attrs).get("alt", "")
            if self.anchor:
                self.anchor["text"].append(alt)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.hidden:
            self.hidden -= 1
            return
        if self.hidden:
            return
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.anchor:
            self.links.append((self.anchor["href"], clean(" ".join(self.anchor["text"]))))
            self.anchor = None
        if tag in ("p", "li", "div", "section", "article", "h1", "h2", "h3", "tr", "a"):
            self.flush()

    def handle_data(self, data):
        if self.hidden:
            return
        if self.in_title:
            self.title.append(data)
        else:
            self.block.append(data)
        if self.anchor:
            self.anchor["text"].append(data)


def extract_notices(url, text, content_type="text/html"):
    """Return unverified candidates and bounded same-host discovery links."""
    parser = NoticeParser()
    if "html" in content_type:
        parser.feed(text)
        parser.flush()
    else:
        parser.blocks = [clean(line) for line in text.splitlines() if clean(line)]
    title = clean(" ".join(parser.title))
    notices = []
    links = []
    link_priority = {}
    seen = set()
    def candidate(target, heading, snippet):
        heading, snippet = clean(heading)[:160], clean(snippet)[:280]
        key = (target, heading)
        if heading and key not in seen:
            seen.add(key)
            notices.append({"url": target, "source_url": url, "title": heading,
                            "snippet": snippet, "date_mentions": list(dict.fromkeys(DATE_PATTERN.findall(snippet)))[:12],
                            "status": "review_required"})
    for href, label in parser.links:
        target = urldefrag(urljoin(url, href))[0]
        if not href or not safe_url(target) or host(target) != host(url) or SKIP.search(target):
            continue
        if UNRELATED_LABEL.search(label) and not RELEVANCE.search(label):
            continue
        if RELEVANCE.search(label) or RELEVANCE.search(target):
            links.append(target)
            link_priority[target] = 3 if "2027" in label + target else 2
            candidate(target, label or title or "Admissions notice link", label or target)
        elif HUB.search(label) or HUB.search(target):
            links.append(target)
            link_priority.setdefault(target, 1)
    relevant_blocks = [block for block in parser.blocks if RELEVANCE.search(block)]
    if RELEVANCE.search(title):
        snippet = " ".join([title] + relevant_blocks[:2])
        candidate(url, title, snippet)
    for block in relevant_blocks:
        # A long navigation/footer block is not a dated event narrative.
        if len(block) <= 700:
            candidate(url, block[:160], block)
    notices.sort(key=lambda n: ("2027" not in (n["title"] + n["snippet"]), not bool(n["date_mentions"])))
    # Stable sorting retains the publisher's document order among equal ranks.
    links = sorted(dict.fromkeys(links), key=lambda u: -link_priority[u])
    return notices[:MAX_NOTICES], links[:20]


def require_readable_html(text, content_type):
    """A title, markup or script payload alone is not a readable school page."""
    if "html" in content_type:
        parser = NoticeParser()
        parser.feed(text)
        parser.flush()
        if not any(parser.blocks):
            raise FetchError("no_extractable_text", "HTML has no readable body text; JavaScript/image-only page requires review")


def fetch_url(url, previous=None, timeout=8, retries=1):
    """One honest request; one retry only for transport errors or HTTP 5xx.

    403 and 429 are never retried or bypassed. Conditional headers reduce traffic.
    """
    previous = previous or {}
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,text/plain;q=0.8", "Accept-Encoding": "identity"}
    if previous.get("etag"):
        headers["If-None-Match"] = previous["etag"]
    if previous.get("last_modified"):
        headers["If-Modified-Since"] = previous["last_modified"]
    for attempt in range(retries + 1):
        try:
            with urlopen(Request(url, headers=headers), timeout=timeout) as response:
                final_url = response.geturl()
                if host(final_url) != host(url):
                    raise FetchError("redirect_outside_host", "Redirected outside the monitored host")
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise FetchError("too_large", "Response exceeds 3 MiB; no full document retained")
                content_type = response.headers.get_content_type()
                if "pdf" in content_type or data.startswith(b"%PDF-"):
                    try:
                        from pypdf import PdfReader
                    except ImportError as error:
                        raise FetchError("pdf_unavailable", "Optional pypdf dependency is unavailable") from error
                    try:
                        reader = PdfReader(BytesIO(data))
                        text = "\n".join((page.extract_text() or "") for page in reader.pages[:12])[:60000]
                        content_type = "application/pdf"
                    except Exception as error:
                        raise FetchError("parse_error", "PDF text extraction failed") from error
                    if not clean(text):
                        raise FetchError("no_extractable_text", "PDF has no extractable text; image/OCR review required")
                elif content_type in ("text/html", "application/xhtml+xml", "text/plain"):
                    charset = response.headers.get_content_charset() or "utf-8"
                    # Several older school sites declare charset only in HTML.
                    if not response.headers.get_content_charset():
                        declared = re.search(br'charset\s*=\s*["\x27]?([a-zA-Z0-9_-]+)', data[:4096])
                        if declared:
                            charset = declared.group(1).decode("ascii")
                    try:
                        text = data.decode(charset, errors="replace")
                    except LookupError:
                        text = data.decode("utf-8", errors="replace")
                else:
                    raise FetchError("unsupported_content", "Unsupported response content type: " + content_type)
                if not clean(text):
                    raise FetchError("empty_response", "Empty response")
                require_readable_html(text, content_type)
                return {"url": final_url, "text": text, "content_type": content_type,
                        "http_status": response.status, "etag": response.headers.get("ETag"),
                        "last_modified": response.headers.get("Last-Modified")}
        except HTTPError as error:
            if error.code == 304:
                return {"url": url, "http_status": 304}
            if error.code >= 500 and attempt < retries:
                time.sleep(0.5)
                continue
            raise FetchError("http_error", f"HTTP {error.code}; access was not bypassed", error.code) from error
        except (URLError, socket.timeout, TimeoutError, OSError) as error:
            if attempt < retries:
                time.sleep(0.5)
                continue
            raise FetchError("network_error", clean(str(error))[:220]) from error


class PoliteFetcher:
    """Robots check once per host, no login/cookie or browser impersonation."""
    def __init__(self, timeout=8):
        self.timeout = timeout
        self.robots = {}
        self.refused = {}
        self.locks = {}
        self.lock_guard = threading.Lock()

    def __call__(self, url, previous=None):
        with self.lock_guard:
            lock = self.locks.setdefault(host(url), threading.Lock())
        with lock:
            return self.fetch(url, previous)

    def fetch(self, url, previous=None):
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self.refused:
            raise FetchError("host_access_refused", "Further requests stopped after the host refused access", self.refused[origin])
        if origin not in self.robots:
            robots_url = origin + "/robots.txt"
            try:
                result = fetch_url(robots_url, timeout=self.timeout, retries=0)
                robot = RobotFileParser()
                robot.parse(result["text"].splitlines())
                self.robots[origin] = (robot, "read")
            except FetchError as error:
                if error.http_status in (401, 403, 429):
                    self.refused[origin] = error.http_status
                    raise FetchError("robots_access_refused", "robots.txt access refused; host not crawled", error.http_status) from error
                self.robots[origin] = (None, "not_available")
        robot, robots_status = self.robots[origin]
        if robot and not robot.can_fetch(USER_AGENT, url):
            raise FetchError("robots_disallowed", "robots.txt disallows this URL")
        time.sleep(0.25)
        try:
            result = fetch_url(url, previous, timeout=self.timeout)
        except FetchError as error:
            if error.http_status in (401, 403, 429):
                self.refused[origin] = error.http_status
            raise
        result["robots_status"] = robots_status
        return result


def monitor_school(school, previous, checked_at, fetcher=fetch_url, max_pages=8, deadline=None, scan_mode="daily"):
    root = school.get("website", "")
    previous_sources = {s["url"]: s for s in previous.get("sources", [])}
    previous_notices = previous.get("notices", [])
    queue = select_sources(school)
    # Keep checking previously discovered relevant endpoints even if removed from
    # the homepage; cap stored endpoint count so history cannot grow indefinitely.
    known = {s["url"] for s in queue}
    for old in previous.get("sources", []):
        if old["url"] not in known and host(old["url"]) == host(root):
            queue.append({"url": old["url"], "kind": "discovered_school_page"})
            known.add(old["url"])
    mandatory = queue[:1] + [s for s in queue[1:] if s["kind"] == "official_social"]
    pending = [s for s in queue[1:] if s["kind"] != "official_social"]
    # Previously discovered pages remain ahead of historical seed evidence.
    # Oldest/never checked endpoints rotate first within each group.
    def pending_priority(source):
        years = [int(year) for year in re.findall(r"20\d{2}", source["url"])]
        historical = bool(years and max(years) < 2027)
        if source["kind"] == "discovered_school_page":
            group = 0
        elif not historical and (RELEVANCE.search(source["url"]) or HUB.search(source["url"])):
            group = 1
        else:
            group = 3 if historical else 2
        return group, previous_sources.get(source["url"], {}).get("checked_at", "")
    pending.sort(key=pending_priority)
    stable_seeds = [s for s in pending if pending_priority(s)[0] == 1]
    reserved_urls = {stable_seeds[0]["url"]} if stable_seeds else set()
    if scan_mode == "deep":
        historical = [s for s in pending if pending_priority(s)[0] == 3]
        historical.sort(key=lambda s: previous_sources.get(s["url"], {}).get("checked_at", ""))
        if historical:
            reserved_urls.add(historical[0]["url"])
    # Reserve one rotating stable admissions/notice endpoint even when retained
    # discoveries fill every other page slot for many consecutive days.
    queue = mandatory + [s for s in pending if s["url"] in reserved_urls] + [s for s in pending if s["url"] not in reserved_urls]
    sources, notices, attempted, weekly_deferred = [], [], set(), []
    current_year = int(checked_at[:4])
    while queue and len(attempted) < max_pages and (deadline is None or time.monotonic() < deadline):
        source = queue.pop(0)
        url = source["url"]
        years = [int(year) for year in re.findall(r"20\d{2}", url)]
        if scan_mode == "daily" and years and max(years) < current_year:
            weekly_deferred.append({**source, "deferral_reason": "weekly_deep_scan"})
            continue
        if url in attempted:
            continue
        attempted.add(url)
        old = previous_sources.get(url, {})
        state = {**copy.deepcopy(old), **source, "checked_at": checked_at, "changed": None}
        for stale in ("error", "http_status", "deferral_reason"):
            state.pop(stale, None)
        try:
            result = fetcher(url, old)
            state["http_status"] = result["http_status"]
            if result["http_status"] == 304:
                if not old.get("content_hash"):
                    raise FetchError("invalid_not_modified", "304 without last known good content")
                state.update(status="ok", last_success_at=checked_at, changed=False)
                retained = copy.deepcopy([n for n in previous_notices if n.get("source_url", n.get("url")) == url])
                current_keys = {tuple(key) for key in old.get("current_notice_keys", [])}
                for notice in retained:
                    if (notice.get("url"), notice.get("title")) in current_keys:
                        notice["last_seen_at"] = checked_at
                notices.extend(retained)
            else:
                text = result["text"]
                found, links = extract_notices(result.get("url", url), text, result.get("content_type", "text/html"))
                if social_url(url):
                    # A profile or a login shell is not evidence of accessible
                    # posts. Require a relevant concrete post permalink.
                    concrete_post = re.compile(r'^https?://(?:(?:www|m)\.)?(?:facebook\.com/(?:[^/?]+/(?:posts|videos)/[^?]+|permalink\.php\?)|instagram\.com/(?:p|reel)/[^/?]+)', re.I)
                    post_notices = [notice for notice in found if concrete_post.search(notice["url"])]
                    login_shell = re.search(r'<title[^>]*>[^<]*(?:log[ -]?in|sign[ -]?in|sign[ -]?up|登入|登录)|checking your browser|verify you are human|just a moment|access denied', text[:12000], re.I)
                    if login_shell or not post_notices:
                        raise FetchError("social_unavailable", "Public posts not readable; login/profile shell is not successful monitoring")
                    found = post_notices
                elif re.search(r"checking your browser|verify you are human|just a moment|access denied|enable javascript and cookies", text[:12000], re.I):
                    raise FetchError("access_challenge", "Access challenge or denial; no bypass attempted")
                require_readable_html(text, result.get("content_type", "text/html"))
                content_hash = hashlib.sha256(clean(text).encode("utf-8")).hexdigest()
                state.update(status="ok", last_success_at=checked_at, content_hash=content_hash,
                             current_notice_keys=[[notice["url"], notice["title"]] for notice in found],
                             changed=(content_hash != old["content_hash"]) if old.get("content_hash") else None)
                for key in ("etag", "last_modified", "robots_status"):
                    if result.get(key):
                        state[key] = result[key]
                old_index = {(n.get("url"), n.get("title")): n for n in previous_notices}
                for notice in found:
                    notice["source_url"] = url
                    earlier = old_index.get((notice["url"], notice["title"]), {})
                    notice.update(first_seen_at=earlier.get("first_seen_at", checked_at), last_seen_at=checked_at)
                notices.extend(found)
                if not social_url(url):
                    discovered = []
                    for link in links:
                        if link not in known:
                            known.add(link)
                            discovered.append({"url": link, "kind": "discovered_school_page"})
                    # A current announcement may have an opaque numeric URL.
                    # Follow relevant live links before historical pilot evidence,
                    # while preserving the independently checked social accounts.
                    protected = [s for s in queue if s["kind"] == "official_social" or s["url"] in reserved_urls]
                    queue = protected + discovered + [s for s in queue if s["kind"] != "official_social" and s["url"] not in reserved_urls]
        except FetchError as error:
            state.update(status=error.status, error=clean(str(error))[:240])
            if error.http_status:
                state["http_status"] = error.http_status
            notices.extend(copy.deepcopy([n for n in previous_notices if n.get("source_url", n.get("url")) == url]))
        except Exception as error:
            state.update(status="parse_error", error=f"{type(error).__name__}: {clean(str(error))[:180]}")
            notices.extend(copy.deepcopy([n for n in previous_notices if n.get("source_url", n.get("url")) == url]))
        sources.append(state)
    actual_attempts = len(attempted)
    queue.extend(weekly_deferred)
    for source in queue:
        url = source["url"]
        if url not in attempted and len(sources) < MAX_SOURCES:
            attempted.add(url)
            old = previous_sources.get(url, {})
            state = {**copy.deepcopy(old), **source, "status": "not_checked_budget", "changed": None,
                     "deferral_reason": source.get("deferral_reason") or ("run_time_budget" if deadline is not None and time.monotonic() >= deadline else "page_budget")}
            sources.append(state)
            notices.extend(copy.deepcopy([n for n in previous_notices if n.get("source_url", n.get("url")) == url]))
    unique = {}
    # A removed page does not erase historical evidence or imply cancellation.
    for notice in copy.deepcopy(previous_notices) + notices:
        key = (notice["url"], notice["title"])
        if key not in unique or notice.get("last_seen_at", "") > unique[key].get("last_seen_at", ""):
            unique[key] = notice
    notices = sorted(unique.values(), key=lambda n: (n.get("last_seen_at", ""), "2027" in n.get("title", "")), reverse=True)
    successes = sum(s["status"] == "ok" for s in sources)
    errors = sum(s["status"] not in ("ok", "not_checked_budget") for s in sources)
    deferred = any(s["status"] == "not_checked_budget" for s in sources)
    return {"id": school["id"], "checked_at": checked_at if actual_attempts else previous.get("checked_at"),
            "attempted_sources": actual_attempts,
            "status": "deferred" if not actual_attempts else "failed" if not successes else "partial" if errors or deferred else "ok",
            "sources": sources, "notices": notices}


def save_monitor(payload, output_path, history_limit=30):
    """Atomically persist bounded current evidence and the latest 30 run files."""
    payload = copy.deepcopy(payload)
    for school in payload.get("schools", []):
        school["sources"] = school.get("sources", [])[:MAX_SOURCES]
        school["notices"] = school.get("notices", [])
        for notice in school["notices"]:
            notice["snippet"] = notice.get("snippet", "")[:280]
            notice["title"] = notice.get("title", "")[:160]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary = output_path.with_suffix(".json.tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(output_path)
    history = output_path.parent / "monitor-history"
    history.mkdir(exist_ok=True)
    stamp = re.sub(r"[^0-9]", "", payload["checked_at"])
    (history / f"{stamp}.json").write_text(serialized, encoding="utf-8")
    for old in sorted(history.glob("*.json"), reverse=True)[history_limit:]:
        old.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--pilot", type=Path, default=root / "docs/data/pilot.json")
    parser.add_argument("--output", type=Path, default=root / "docs/data/monitor.json")
    parser.add_argument("--school", action="append", help="Limit live checks to these ids; preserve other schools")
    parser.add_argument("--max-pages", type=int, default=8, choices=range(1, 13))
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 7))
    parser.add_argument("--timeout", type=int, default=8, choices=range(2, 11))
    parser.add_argument("--max-seconds", type=int, default=960, help="Stop starting fetches after this run budget (30–1080 seconds)")
    args = parser.parse_args(argv)
    if not 30 <= args.max_seconds <= 1080:
        parser.error("--max-seconds must be between 30 and 1080")
    pilot = json.loads(args.pilot.read_text(encoding="utf-8-sig"))
    previous = json.loads(args.output.read_text(encoding="utf-8-sig")) if args.output.exists() else {}
    old_schools = {s["id"]: s for s in previous.get("schools", [])}
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    deadline = time.monotonic() + args.max_seconds
    selected = [s for s in pilot["schools"] if not args.school or s["id"] in args.school]
    if not selected:
        parser.error("No matching school ids; existing monitor output was not changed")
    fetcher = PoliteFetcher(args.timeout)
    def run(school):
        return monitor_school(school, old_schools.get(school["id"], {}),
                              datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                              fetcher, args.max_pages, deadline=deadline)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        checked = list(executor.map(run, selected))
    checked_ids = {s["id"] for s in checked}
    schools = checked + [s for s in previous.get("schools", []) if s["id"] not in checked_ids]
    attempted_schools = [school for school in checked if school.get("attempted_sources", 0)]
    sources = [source for school in attempted_schools for source in school["sources"]]
    summary = {"schools_checked": len(attempted_schools), "schools_total": len(pilot["schools"]),
               "schools_deferred": len(checked) - len(attempted_schools),
               "schools_failed": sum(s["status"] == "failed" for s in attempted_schools),
               "sources_checked": sum(s["status"] != "not_checked_budget" for s in sources),
               "sources_ok": sum(s["status"] == "ok" for s in sources),
               "sources_failed": sum(s["status"] not in ("ok", "not_checked_budget") for s in sources),
               "sources_deferred": sum(s["status"] == "not_checked_budget" for s in sources),
               "sources_changed": sum(s.get("changed") is True for s in sources),
               "review_required_notices": sum(len(s["notices"]) for s in schools)}
    run_status = "deferred" if not attempted_schools else "failed" if not summary["sources_ok"] else "partial" if summary["sources_failed"] or summary["sources_deferred"] or summary["schools_deferred"] else "ok"
    payload = {"schema_version": "1.0", "checked_at": checked_at, "run_status": run_status,
               "scope": "selected_schools" if args.school else "all_schools", "summary": summary,
               "policy": {"verification": "Discovery only. Every notice and date mention requires human review.",
                          "pilot_modified": False, "max_pages_per_school": args.max_pages,
                          "max_run_seconds": args.max_seconds,
                          "history_runs_retained": 30, "target_admission_year": 2027}, "schools": schools}
    save_monitor(payload, args.output)
    print(json.dumps({"checked_at": checked_at, "run_status": run_status, **summary}, ensure_ascii=False))
    # Failure details are persisted even when sites refuse access. A zero exit
    # means the run completed and wrote results, not that every source succeeded.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
