"""Behavior checks for conservative, separate calendar-year planning forecasts."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "school-forecasts.py"
if SCRIPT.exists():
    spec = importlib.util.spec_from_file_location("school_forecasts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    generate = module.generate_forecasts
else:
    generate = None


def event(year, month=11, day=20, *, family="Admission briefing", opening=None, **extra):
    value = {"event_id": f"e-{year}-{month}-{day}", "event_year": year,
             "start_date": f"{year}-{month:02}-{day:02}", "end_date": None,
             "admission_year": f"{year + 1}/{str(year + 2)[-2:]}",
             "title": "S1 briefing", "activity_types": [family],
             "talk_registration": {"opens_date": opening},
             "source_urls": [f"https://school.edu.hk/{year}"],
             "verification": {"level": "school_page_verified"}}
    value.update(extra)
    return value


class ForecastTests(unittest.TestCase):
    def forecast(self, events, **kwargs):
        self.assertTrue(callable(generate), "The planning forecast generator must exist")
        payload = {"schools": [{"id": "school", "events": events}]}
        return generate(payload, target_year=2027, generated_at="2026-10-26", **kwargs)["schools"][0]

    def test_single_year_is_low_confidence_month_window(self):
        result = self.forecast([event(2026)])
        window = result["event_window"]
        self.assertEqual((window["start"], window["end"]), ("2027-10-01", "2027-12-31"))
        self.assertEqual((window["confidence"], window["sample_count"]), ("low", 1))
        self.assertNotIn("time", window)

    def test_registration_forecast_requires_observed_booking_date(self):
        result = self.forecast([event(2025), event(2026)])
        self.assertIsNone(result["registration_window"])
        self.assertIn("unknown", result["registration_status"])

    def test_missing_dates_remain_unknown(self):
        result = self.forecast([event(2026, start_date=None)])
        self.assertIsNone(result["event_window"])
        self.assertIsNone(result["watch_from"])

    def test_official_calendar_2027_suppresses_forecasts(self):
        result = self.forecast([event(2026), event(2027)])
        self.assertIsNone(result["event_window"])
        self.assertIsNone(result["registration_window"])
        self.assertEqual(result["status"], "official_dates_available")
        self.assertEqual(result["official_event_ids"], ["e-2027-11-20"])

    def test_admission_year_2027_is_not_calendar_year_2027(self):
        result = self.forecast([event(2026, admission_year="2027/28")])
        self.assertIsNotNone(result["event_window"])
        self.assertEqual(result["history"][0]["admission_year"], "2027/28")

    def test_verified_official_pdf_and_social_dates_supersede_estimates(self):
        for level in ("school_pdf_verified", "official_social_verified"):
            with self.subTest(level=level):
                result = self.forecast([event(2026), event(2027, verification={"level": level})])
                self.assertEqual(result["status"], "official_dates_available")
                self.assertIsNone(result["event_window"])

    def test_verified_official_pdf_counts_as_directly_read_evidence(self):
        result = self.forecast([event(2025, verification={"level": "school_pdf_verified"}), event(2026)])
        self.assertEqual(result["event_window"]["confidence"], "medium")

    def test_fete_does_not_supply_admissions_samples(self):
        fete = event(2024, family="Open day", title="Garden Fete")
        result = self.forecast([fete, event(2026, month=10)])
        self.assertEqual(result["event_window"]["sample_count"], 1)
        self.assertEqual(result["activity_family"], "s1_admissions")
        self.assertNotIn(fete["event_id"], result["source_event_ids"])

    def test_anniversary_day_not_used_as_regular_information_day(self):
        special = event(2025, month=7, title="170th Anniversary Open Day & Cultural Performances")
        result = self.forecast([special, event(2025, month=10)])
        self.assertEqual(result["event_window"]["sample_count"], 1)
        self.assertEqual(result["event_window"]["start"], "2027-09-01")

    def test_only_2024_to_2026_history_used(self):
        result = self.forecast([event(2023), event(2024), event(2028)])
        self.assertEqual(result["event_window"]["sample_years"], [2024])

    def test_two_sessions_same_year_count_one_year_sample(self):
        result = self.forecast([event(2025), event(2025, day=21), event(2026)])
        self.assertEqual(result["event_window"]["sample_count"], 2)

    def test_watch_starts_before_earliest_observed_booking(self):
        result = self.forecast([event(2025, opening="2025-10-03"), event(2026, opening="2026-11-02")])
        self.assertLessEqual(result["watch_from"], "2027-08-04")
        self.assertEqual(result["registration_window"]["sample_count"], 2)
        self.assertEqual(result["registration_window"]["source_urls"], ["https://school.edu.hk/2025", "https://school.edu.hk/2026"])

    def test_future_official_year_can_still_use_unrelated_family(self):
        future_fete = event(2027, family="Open day", title="Garden Fete")
        result = self.forecast([event(2026), future_fete])
        self.assertIsNotNone(result["event_window"])

    def test_generator_does_not_modify_official_evidence(self):
        payload = {"schools": [{"id": "school", "events": [event(2026)]}]}
        before = copy.deepcopy(payload)
        self.assertTrue(callable(generate), "The planning forecast generator must exist")
        generate(payload, target_year=2027, generated_at="2026-10-26")
        self.assertEqual(payload, before)

    def test_pilot_has_all_28_school_rows_and_no_times(self):
        self.assertTrue(callable(generate), "The planning forecast generator must exist")
        pilot = json.loads((ROOT / "seed/verified-schools.json").read_text(encoding="utf-8-sig"))
        result = generate(pilot, target_year=2027, generated_at="2026-10-26")
        self.assertEqual(len(result["schools"]), 28)
        for row in result["schools"]:
            for key in ("event_window", "registration_window"):
                if row[key]:
                    self.assertNotIn(":", row[key]["start"])
                    self.assertTrue(row[key]["source_urls"])


if __name__ == "__main__":
    unittest.main()
