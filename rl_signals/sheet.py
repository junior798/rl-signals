"""Google Sheet storage. Tabs: Signals (every signal, never deleted), Companies (rebuilt each run),
Hot list (top companies), Runs (one line per run)."""
from __future__ import annotations

import json
import os

SIGNAL_COLS = ["signal_id", "source", "signal_type", "company", "company_key", "city", "province", "date",
               "amount", "points", "detail", "url", "added_on"]
COMPANY_COLS = ["company", "city", "province", "score", "tier", "sources", "signal_count", "top_signal_type",
                "trigger_event", "latest_signal", "company_key"]
RUN_COLS = ["run_at", "source", "status", "signals_found", "new_signals", "note"]


def open_sheet():
    import gspread

    creds = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    client = gspread.service_account_from_dict(creds)
    return client.open_by_key(os.environ["SHEET_ID"])


def tab(sh, name: str, cols: list[str]):
    import gspread

    try:
        ws = sh.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(name, rows=1000, cols=len(cols))
        ws.append_row(cols)
    if ws.row_values(1) != cols:
        ws.update(values=[cols], range_name="A1")
    return ws


def existing_signals(sh) -> list[dict]:
    # keep everything as text so ids like "0123" or "4455" stay exactly as written
    return tab(sh, "Signals", SIGNAL_COLS).get_all_records(numericise_ignore=["all"])


def append_signals(sh, rows: list[dict]):
    if rows:
        tab(sh, "Signals", SIGNAL_COLS).append_rows([[r.get(c, "") for c in SIGNAL_COLS] for r in rows],
                                                    value_input_option="RAW")


def replace_tab(sh, name: str, cols: list[str], rows: list[dict]):
    ws = tab(sh, name, cols)
    ws.clear()
    ws.update(values=[cols] + [[r.get(c, "") for c in cols] for r in rows], range_name="A1")
    ws.freeze(rows=1)


def log_runs(sh, rows: list[dict]):
    tab(sh, "Runs", RUN_COLS).append_rows([[r.get(c, "") for c in RUN_COLS] for r in rows])
