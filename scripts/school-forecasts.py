#!/usr/bin/env python3
"""Build separate, conservative calendar-year planning windows from cited evidence."""
import argparse
import calendar
from datetime import date, timedelta
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
METHOD = "comparable-history-month-windows-v1"
DIRECTLY_VERIFIED_LEVELS = {"school_page_verified", "school_pdf_verified", "official_social_verified"}
SPECIAL_EVENTS = {
    "kings-college-2026-03-13-open-day": "Centennial celebration; a one-off anniversary is not evidence of a regular annual open day.",
    "st-pauls-convent-school-2025-07-04-open-day": "170th anniversary in July is separate from the October S1 Information Day.",
    "kwun-tong-maryknoll-college-2026-3": "February 55th anniversary celebration is separate from the November/December admissions information activity.",
    "wong-shiu-chi-secondary-school-2024-1": "65th anniversary open day does not establish the timing of the S1 briefing and taster lessons.",
    "ho-fung-college-2024-1": "50th anniversary multi-day celebration is separate from the regular S1 information day.",
    "chiu-lut-sau-memorial-secondary-school-2024-1": "May anniversary and history-gallery opening is separate from the December S1 information day.",
}


def parsed(value):
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def family(event):
    title = event.get("title", "")
    if event.get("event_id") in SPECIAL_EVENTS or "170th Anniversary" in title or "Centennial" in title:
        return None
    if re.search(r"garden f[eê]te|fun fair|嘉年華", title, re.I):
        return "fete"
    text = " ".join([title, *event.get("activity_types", [])])
    if re.search(r"admission|parents seminar|中一|升中|入學", text, re.I):
        return "s1_admissions"
    if re.search(r"information day|資訊日", text, re.I):
        return "information_day"
    if re.search(r"experience day|taster|體驗", text, re.I):
        return "school_experience"
    if re.search(r"open day|開放日", text, re.I):
        return "open_day"
    return None


def shift_year(value, years):
    return value.replace(year=value.year + years, day=min(value.day, calendar.monthrange(value.year + years, value.month)[1]))


def month_shift(value, offset):
    index = value.year * 12 + value.month - 1 + offset
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def window(samples, target_year, *, event_window=False):
    if not samples:
        return None
    years = sorted({item["event_year"] for item in samples})
    projected = [shift_year(parsed(item["date"]), target_year - item["event_year"]) for item in samples]
    projected_ends = [shift_year(parsed(item.get("end_date")) or parsed(item["date"]), target_year - item["event_year"]) for item in samples]
    earliest, latest = min(projected), max(projected_ends)
    if len(years) == 1:
        start = month_shift(earliest.replace(day=1), -1)
        end = month_shift(latest.replace(day=1), 2) - timedelta(days=1)
        basis = "One observed year only; rough observed month plus one month either side. Recurrence is unconfirmed."
    else:
        start = (earliest - timedelta(days=14)).replace(day=1)
        padded_end = latest + timedelta(days=14)
        end = month_shift(padded_end.replace(day=1), 1) - timedelta(days=1)
        basis = "Observed month/day range projected to target calendar year, padded 14 days each side, then rounded outward to whole months."
    if event_window:
        start, end = max(start, date(target_year, 1, 1)), min(end, date(target_year, 12, 31))
    stable = (latest - earliest).days <= 62 and not any(item["exceptional"] for item in samples)
    all_verified = all(item["evidence_level"] in DIRECTLY_VERIFIED_LEVELS for item in samples)
    confidence = "medium" if len(years) >= 2 and stable and all_verified else "low"
    return {"start": start.isoformat(), "end": end.isoformat(), "confidence": confidence,
            "sample_count": len(years), "sample_years": years, "record_count": len(samples),
            "source_urls": sorted({url for item in samples for url in item["source_urls"]}),
            "source_event_ids": sorted({item["event_id"] for item in samples}),
            "basis": basis, "uncertainty": "Planning estimate only; no school announcement, guaranteed date, or statistical probability."}


def generate_forecasts(pilot, target_year=2027, generated_at=None):
    rows = []
    for school in pilot["schools"]:
        events = school.get("events", [])
        candidates = [event for event in events if family(event)]
        available_families = {family(event) for event in candidates}
        selected = next((value for value in ("s1_admissions", "information_day", "school_experience", "open_day", "fete") if value in available_families), None)
        history, event_samples, registration_samples, excluded, official_ids = [], [], [], [], []
        for event in sorted(events, key=lambda item: (item.get("start_date") or "9999", item.get("event_id", ""))):
            start = parsed(event.get("start_date"))
            event_year = start.year if start else event.get("event_year")
            same_family = family(event) == selected and selected is not None
            level = event.get("verification", {}).get("level", "unknown")
            urls = list(dict.fromkeys(event.get("source_urls", []) + event.get("chsc_urls", [])))
            official = same_family and start and start.year == target_year and level in DIRECTLY_VERIFIED_LEVELS and bool(urls)
            if official:
                official_ids.append(event["event_id"])
            eligible = same_family and start and 2024 <= start.year <= 2026 and start.year < target_year and bool(urls)
            reason = SPECIAL_EVENTS.get(event.get("event_id"))
            if not reason and not same_family:
                reason = "Different activity family or one-off celebration; not pooled with the selected planning activity."
            if not reason and not start:
                reason = "No confirmed event date; an admission academic-year heading is not an event date."
            if not reason and start and not (2024 <= start.year <= 2026 and start.year < target_year):
                reason = "Outside the 2024–2026 historical calendar-year sample."
            if not reason and not urls:
                reason = "No retained source URL."
            if eligible:
                reason = None
            item = {"event_id": event.get("event_id"), "title": event.get("title"),
                    "start_date": event.get("start_date"), "end_date": event.get("end_date"),
                    "event_year": event_year, "admission_year": event.get("admission_year"),
                    "activity_family": family(event), "evidence_level": level,
                    "source_urls": urls, "included": bool(eligible), "exclusion_reason": reason,
                    "registration_open_dates": [], "notes": event.get("notes", [])}
            exceptional = any(re.search(r"postpon|延期|tentative", note, re.I) for note in item["notes"])
            if eligible:
                event_samples.append({"date": start.isoformat(), "end_date": event.get("end_date"), "event_year": start.year,
                                      "event_id": event["event_id"], "evidence_level": level, "source_urls": urls, "exceptional": exceptional})
                for registration_type in ("talk_registration", "visit_registration"):
                    opening = parsed(event.get(registration_type, {}).get("opens_date"))
                    if opening and 2024 <= opening.year <= 2026 and opening <= start:
                        item["registration_open_dates"].append({"kind": registration_type, "date": opening.isoformat()})
                        registration_samples.append({"date": opening.isoformat(), "event_year": start.year, "event_id": event["event_id"],
                                                     "evidence_level": level, "source_urls": urls, "exceptional": exceptional})
            if reason:
                excluded.append({"event_id": event.get("event_id"), "reason": reason})
            history.append(item)
        estimated_event = None if official_ids else window(event_samples, target_year, event_window=True)
        estimated_registration = None if official_ids else window(registration_samples, target_year)
        watch_candidates = [parsed(value["start"]) for value in (estimated_event, estimated_registration) if value]
        watch_from = (min(watch_candidates) - timedelta(days=60)).isoformat() if watch_candidates else None
        notes = ["Target is calendar year 2027, not the 2027/28 entry academic year." if target_year == 2027 else "Target year denotes the event calendar year.",
                 "Watch date is a planning reminder to check official sources; it does not activate monitoring or guarantee a seat."]
        if not estimated_registration and not official_ids:
            notes.append("Registration opening is unknown; no opening date is inferred from the event date or another school.")
        if len({sample["event_year"] for sample in event_samples}) == 1:
            notes.append("Only one comparable dated year was found; recurrence and future format are unconfirmed.")
        if excluded:
            notes.append("Excluded activities remain in history with reasons; unrelated celebrations are not admissions samples.")
        if any(sample["exceptional"] for sample in event_samples):
            notes.append("History includes a postponement or tentative arrangement; retain the actual dated evidence and lower confidence.")
        if not event_samples and not official_ids:
            notes.append("No comparable dated 2024–2026 sample; timing is unknown. Missing evidence does not establish no event.")
        if official_ids:
            notes.append("Official target-calendar-year dates supersede estimates; use the cited actual event records.")
        rows.append({"id": school["id"], "record_type": "planning_forecast", "target_year": target_year,
                     "activity_family": selected, "status": "official_dates_available" if official_ids else "estimated" if estimated_event else "unknown",
                     "event_window": estimated_event, "registration_window": estimated_registration,
                     "registration_status": "official_event_check_booking_details" if official_ids else "estimated" if estimated_registration else "unknown_no_dated_opening",
                     "watch_from": watch_from, "watch_lead_days": 60,
                     "source_event_ids": sorted({item["event_id"] for item in event_samples}),
                     "official_event_ids": sorted(official_ids), "history": history, "excluded_events": excluded, "notes": notes})
    return {"schema_version": "1.0", "record_type": "planning_forecast_dataset", "target_year": target_year,
            "target_year_kind": "event_calendar_year", "generated_at": generated_at or date.today().isoformat(),
            "method": METHOD, "historical_calendar_years": [2024, 2025, 2026], "timezone": "Asia/Hong_Kong",
            "disclaimer": "Historical planning windows only. These are not official dates or admissions offers; entry academic years are separate historical context.",
            "schools": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "docs/data/pilot.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/data/forecasts.json")
    parser.add_argument("--target-year", type=int, default=2027)
    parser.add_argument("--generated-at", default=None)
    args = parser.parse_args()
    data = generate_forecasts(json.loads(args.input.read_text(encoding="utf-8-sig")), args.target_year, args.generated_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(data['schools'])} separate school planning records to {args.output}")


if __name__ == "__main__":
    main()
