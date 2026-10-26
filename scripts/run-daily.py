#!/usr/bin/env python3
"""Collect every roster school in resumable batches; publish one history snapshot."""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("school_monitor", ROOT / "scripts/school-monitor.py")
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def rotate_schools(schools, last_school_id=None):
    ids = [s["id"] for s in schools]
    start = ids.index(last_school_id) + 1 if last_school_id in ids else 0
    return schools[start:] + schools[:start]


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def collect(roster, previous, state, *, max_seconds=4500, batch_size=50,
            workers=4, timeout=8, mode="daily", runner=None, checkpoint=None):
    """No result gets a new checked_at until at least one source was attempted."""
    runner = runner or monitor.monitor_school
    state = copy.deepcopy(state)
    began = utc_now()
    deadline = time.monotonic() + max_seconds
    schools = roster["schools"]
    old = {s["id"]: s for s in previous.get("schools", [])}
    rows = {s["id"]: copy.deepcopy(old.get(s["id"], {
        "id": s["id"], "checked_at": None, "status": "not_checked", "sources": [], "notices": []})) for s in schools}
    eligible = []
    for school in rotate_schools(schools, state.get("last_school_id")):
        if monitor.safe_url(school.get("website") or ""):
            eligible.append(school)
        else:
            rows[school["id"]]["status"] = "missing_website"
    completed = {}
    fetcher = monitor.PoliteFetcher(timeout)

    def payload():
        attempts = [row for row in completed.values() if row.get("attempted_sources", 0)]
        sources = [source for row in attempts for source in row.get("sources", [])]
        source_attempts = [s for s in sources if s["status"] != "not_checked_budget"]
        summary = {"schools_total": len(schools), "schools_checked": len(attempts),
                   "schools_failed": sum(row["status"] == "failed" for row in attempts),
                   "schools_deferred": len(eligible) - len(attempts),
                   "schools_missing_website": len(schools) - len(eligible),
                   "sources_checked": len(source_attempts),
                   "sources_ok": sum(s["status"] == "ok" for s in source_attempts),
                   "sources_failed": sum(s["status"] != "ok" for s in source_attempts),
                   "sources_deferred": sum(s["status"] == "not_checked_budget" for s in sources),
                   "sources_changed": sum(s.get("changed") is True for s in source_attempts),
                   "review_required_notices": sum(len(row.get("notices", [])) for row in rows.values())}
        status = "deferred" if not attempts else "failed" if not summary["sources_ok"] else "partial" if (
            summary["sources_failed"] or summary["sources_deferred"] or summary["schools_deferred"] or summary["schools_missing_website"]) else "ok"
        return {"schema_version": "1.1", "checked_at": began, "completed_at": utc_now(),
                "run_status": status, "scope": "all_schools", "scan_mode": mode, "summary": summary,
                "policy": {"verification": "Discovery only. All candidates require human review; no dates, fees or bands are automatically verified.",
                           "pilot_modified": False, "max_pages_per_school": 12 if mode == "deep" else 4,
                           "max_run_seconds": max_seconds, "batch_size": batch_size, "workers": workers,
                           "history_runs_retained": 30, "historical_candidates_retained": True},
                "schools": [rows[s["id"]] for s in schools]}

    def run(school):
        return runner(school, old.get(school["id"], {}), utc_now(), fetcher=fetcher,
                      max_pages=12 if mode == "deep" else 4, deadline=deadline, scan_mode=mode)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for offset in range(0, len(eligible), batch_size):
            if time.monotonic() >= deadline:
                break
            batch = eligible[offset:offset + batch_size]
            for school, result in zip(batch, executor.map(run, batch)):
                if result.get("attempted_sources", 0):
                    rows[school["id"]] = result
                    completed[school["id"]] = result
                    state["last_school_id"] = school["id"]
            state["updated_at"] = utc_now()
            current = payload()
            print(json.dumps({"batch": offset // batch_size + 1, "mode": mode, **current["summary"]}), flush=True)
            if checkpoint:
                checkpoint(current, state)
    return payload(), state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "docs/data/pilot.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/data/monitor.json")
    parser.add_argument("--state", type=Path, default=ROOT / "docs/data/monitor-state.json")
    parser.add_argument("--mode", choices=("daily", "deep"), default="daily")
    parser.add_argument("--max-seconds", type=int, default=4500)
    parser.add_argument("--batch-size", type=int, choices=range(1, 51), default=50)
    parser.add_argument("--workers", type=int, choices=range(1, 7), default=4)
    parser.add_argument("--timeout", type=int, choices=range(2, 11), default=8)
    args = parser.parse_args(argv)
    if not 1 <= args.max_seconds <= 5400:
        parser.error("--max-seconds must be 1–5400")
    read = lambda path: json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    roster, previous, all_state = read(args.input), read(args.output), read(args.state)
    if not roster.get("schools"):
        parser.error("Input roster has no schools; existing output was not changed")
    def checkpoint(payload, state):
        atomic_json(args.output, payload)
        all_state[args.mode] = state
        atomic_json(args.state, all_state)
    payload, state = collect(roster, previous, all_state.get(args.mode, {}), max_seconds=args.max_seconds,
                             batch_size=args.batch_size, workers=args.workers, timeout=args.timeout,
                             mode=args.mode, checkpoint=checkpoint)
    checkpoint(payload, state)
    monitor.save_monitor(payload, args.output)
    print(json.dumps({"run_status": payload["run_status"], **payload["summary"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
