"""Weekly run.

  python -m rl_signals run                  # all sources, write to the Google Sheet
  python -m rl_signals run --dry-run        # write CSVs to output/ instead of the sheet
  python -m rl_signals run --sources seao,canadabuys --days 30
"""
from __future__ import annotations

import argparse
import csv
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from .score import score_companies
from .sources import canadabuys, grants, jobbank, lmia, seao

SOURCES = {"seao": seao, "canadabuys": canadabuys, "grants": grants, "lmia": lmia, "jobbank": jobbank}


def write_csv(path: Path, rows: list[dict], cols: list[str]):
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def run(args) -> int:
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    excl = cfg["exclude_name_patterns"]
    allowed = set(cfg["provinces_allowed"])
    names = list(SOURCES) if args.sources == "all" else [s.strip() for s in args.sources.split(",")]
    days = args.days or cfg["lookback_days"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sh = None
    known: dict[str, dict] = {}
    state = Path(args.state) if args.state else None
    if state and state.exists():  # repo mode: past signals live in a CSV committed to the repo
        with open(state, encoding="utf-8") as f:
            known = {r["signal_id"]: r for r in csv.DictReader(f)}
    elif not args.dry_run and not state:
        from . import sheet
        sh = sheet.open_sheet()
        known = {r["signal_id"]: r for r in sheet.existing_signals(sh)}

    new_signals, runs, failed = [], [], 0
    for name in names:
        try:
            found = SOURCES[name].fetch(cfg[name], excl, days)
            found = [s for s in found if not s["province"] or s["province"] in allowed]
            fresh = [dict(s, added_on=date.today().isoformat()) for s in found if s["signal_id"] not in known]
            for s in fresh:
                known[s["signal_id"]] = s
            new_signals += fresh
            runs.append({"run_at": now, "source": name, "status": "ok", "signals_found": len(found),
                         "new_signals": len(fresh), "note": ""})
            print(f"[{name}] {len(found)} signals, {len(fresh)} new")
        except Exception as e:  # one broken source never stops the others
            failed += 1
            traceback.print_exc()
            runs.append({"run_at": now, "source": name, "status": "FAILED", "signals_found": 0,
                         "new_signals": 0, "note": str(e)[:400]})

    companies = score_companies(list(known.values()), cfg)
    hot = [c for c in companies if c["tier"] == "hot"][: cfg["scoring"]["hot_list_size"]]

    from .sheet import COMPANY_COLS, RUN_COLS, SIGNAL_COLS
    if state:
        write_csv(state, list(known.values()), SIGNAL_COLS)
    if args.dry_run or state:
        out = Path("output")
        write_csv(out / "signals.csv", list(known.values()), SIGNAL_COLS)
        write_csv(out / "companies.csv", companies, COMPANY_COLS)
        write_csv(out / "hot_list.csv", hot, COMPANY_COLS)
        write_csv(out / "runs.csv", runs, RUN_COLS)
        write_csv(out / "new_signals.csv", new_signals, SIGNAL_COLS)
        print(f"Wrote output/ ({len(new_signals)} new signals, {len(companies)} companies, {len(hot)} hot)")
    else:
        from . import sheet
        sheet.append_signals(sh, new_signals)
        sheet.replace_tab(sh, "Companies", COMPANY_COLS, companies)
        sheet.replace_tab(sh, "Hot list", COMPANY_COLS, hot)
        sheet.log_runs(sh, runs)
        print(f"Sheet updated: {len(new_signals)} new signals, {len(companies)} companies, {len(hot)} hot")

    # a failed source shows red in GitHub (and GitHub emails you); the rest of the run still saved
    return 1 if failed else 0


def main():
    p = argparse.ArgumentParser(prog="rl_signals")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--sources", default="all")
    r.add_argument("--days", type=int, default=0)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--config", default="config.yaml")
    r.add_argument("--state", default="", help="CSV that keeps every signal between runs (repo mode, no Google keys)")
    args = p.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
