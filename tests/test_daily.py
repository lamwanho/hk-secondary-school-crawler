"""Offline scheduler contracts: progress, fair resumption and honest coverage."""
import importlib.util
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run-daily.py"


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), "daily batch coordinator is missing")
        spec = importlib.util.spec_from_file_location("daily", SCRIPT)
        self.d = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.d)
        self.rows = [{"id": str(i), "website": f"https://s{i}.edu.hk/"} for i in range(5)]

    def runner(self, school, old, stamp, **kwargs):
        return {"id": school["id"], "checked_at": stamp, "attempted_sources": 1,
                "status": "ok", "sources": [{"url": school["website"], "status": "ok", "checked_at": stamp}], "notices": []}

    def test_rotating_cursor_starts_after_last_completed_school(self):
        self.assertEqual([s["id"] for s in self.d.rotate_schools(self.rows, "2")], ["3", "4", "0", "1", "2"])

    def test_expired_budget_preserves_school_timestamp_and_does_not_claim_checks(self):
        old = {"schools": [{"id": "0", "checked_at": "yesterday", "status": "ok", "sources": [], "notices": []}]}
        payload, state = self.d.collect({"schools": self.rows}, old, {}, max_seconds=0, runner=self.runner)
        self.assertEqual(payload["summary"]["schools_checked"], 0)
        self.assertEqual(payload["summary"]["schools_deferred"], 5)
        self.assertEqual(payload["schools"][0]["checked_at"], "yesterday")
        self.assertIsNone(payload["schools"][1].get("checked_at"))
        self.assertEqual(payload["run_status"], "deferred")

    def test_all_schools_included_and_missing_websites_reported_separately(self):
        rows = self.rows + [{"id": "missing", "website": None}]
        payload, state = self.d.collect({"schools": rows}, {}, {}, runner=self.runner, batch_size=2)
        self.assertEqual(payload["summary"]["schools_total"], 6)
        self.assertEqual(payload["summary"]["schools_checked"], 5)
        self.assertEqual(payload["summary"]["schools_missing_website"], 1)
        self.assertEqual(payload["summary"]["schools_deferred"], 0)
        self.assertEqual(len(payload["schools"]), 6)
        self.assertEqual(payload["schools"][-1]["status"], "missing_website")

    def test_checkpoint_occurs_after_each_bounded_batch(self):
        checkpoints = []
        payload, state = self.d.collect({"schools": self.rows}, {}, {}, runner=self.runner, batch_size=2,
            checkpoint=lambda p, s: checkpoints.append((p["summary"]["schools_checked"], s["last_school_id"])))
        self.assertEqual(checkpoints, [(2, "1"), (4, "3"), (5, "4")])
        self.assertEqual(state["last_school_id"], "4")

    def test_unattempted_worker_result_does_not_advance_resume_cursor(self):
        def deferred(school, old, stamp, **kwargs):
            return {"id": school["id"], "status": "deferred", "attempted_sources": 0, "sources": [], "notices": []}
        payload, state = self.d.collect({"schools": self.rows}, {}, {"last_school_id": "1"}, runner=deferred)
        self.assertEqual(payload["summary"]["schools_checked"], 0)
        self.assertEqual(state["last_school_id"], "1")

    def test_daily_and_deeper_budgets_are_explicit(self):
        budgets = []
        def run(school, old, stamp, **kwargs):
            budgets.append((kwargs["max_pages"], kwargs["scan_mode"]))
            return self.runner(school, old, stamp, **kwargs)
        self.d.collect({"schools": self.rows[:1]}, {}, {}, runner=run)
        self.d.collect({"schools": self.rows[:1]}, {}, {}, runner=run, mode="deep")
        self.assertEqual(budgets, [(4, "daily"), (12, "deep")])

    def test_diagnostic_cli_counts_only_real_attempts(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
            root = Path(tmp)
            pilot = root / "pilot.json"
            output = root / "monitor.json"
            pilot.write_text(json.dumps({"schools": self.rows[:1]}), encoding="utf-8")
            deferred = {"id": "0", "checked_at": None, "status": "deferred", "attempted_sources": 0, "sources": [], "notices": []}
            with patch.object(self.d.monitor, "monitor_school", return_value=deferred):
                self.d.monitor.main(["--pilot", str(pilot), "--output", str(output), "--max-seconds", "30"])
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["summary"]["schools_checked"], 0)
            self.assertEqual(result["summary"]["schools_deferred"], 1)
            self.assertEqual(result["run_status"], "deferred")


class WorkflowBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github/workflows/school-monitor.yml").read_text(encoding="utf-8")

    def test_only_standard_public_runners_and_official_setup_actions(self):
        runners = re.findall(r"^\s+runs-on:\s*(.+)$", self.workflow, re.M)
        self.assertEqual(runners, ["ubuntu-latest", "ubuntu-latest"])
        actions = re.findall(r"uses:\s*([^\s]+)", self.workflow)
        self.assertEqual(actions, ["actions/checkout@v4", "actions/setup-python@v5"] * 2)

    def test_each_job_requires_exact_public_repository_and_api_recheck(self):
        for job in re.split(r"^  (?:daily|deeper):\s*$", self.workflow, flags=re.M)[1:]:
            self.assertIn("github.repository == 'lamwanho/hk-secondary-school-crawler'", job)
            self.assertIn("github.event.repository.private == false", job)
            self.assertEqual(job.count("--jq '.private'"), 2)
            self.assertEqual(job.count("test \"$GITHUB_REPOSITORY\" = 'lamwanho/hk-secondary-school-crawler'"), 2)

    def test_no_cache_artifacts_paid_services_or_other_secret_surfaces(self):
        self.assertNotRegex(self.workflow, r"(?i)actions/cache|upload-artifact|download-artifact|\bcache:|\bsecrets\.|self-hosted|larger.runner|pages/deploy|deploy-pages")
        permissions = re.search(r"^permissions:\n(.*?)(?=\n\S)", self.workflow, re.S | re.M).group(1)
        self.assertEqual(permissions.strip(), "contents: write")
        self.assertIn("GH_TOKEN: ${{ github.token }}", self.workflow)

    def test_no_pr_external_trigger_and_publication_is_limited_to_monitor_outputs(self):
        self.assertNotRegex(self.workflow, r"pull_request|repository_dispatch|workflow_call|push:")
        self.assertEqual(self.workflow.count("docs/data/monitor.json docs/data/monitor-state.json docs/data/monitor-history"), 2)
        self.assertNotRegex(self.workflow, r"git add (?:\.|-A|--all)|git push.*--force")
        self.assertIn("--max-seconds 4500", self.workflow)
        self.assertIn("--max-seconds 2700", self.workflow)


if __name__ == "__main__":
    unittest.main()
