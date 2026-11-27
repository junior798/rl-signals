# rl-signals

Every Monday morning GitHub runs this job for free. It downloads public government and city data, finds companies showing signs they need financing, and saves the new ones in this repo:

- `data/new_signals.csv`: federal contracts, CanadaBuys awards, federal grants and LMIA hiring approvals.
- `data/new_direct.csv`: Calgary and Vancouver building permits, Vancouver and Edmonton business licences, Nova Scotia and Toronto contract awards, Vancouver bid awards, Toronto DineSafe, the Ontario child care file, Ontario Access Environment, the Ontario Environmental Registry, AER well licences and spuds, the Transport Canada aircraft register and Job Bank postings.

At 9am Toronto time the n8n workflow "RL Signals - Weekly GitHub signals into Supabase" loads both files into Supabase (functions `ingest_signals` and `ingest_direct`). Each signal gets the same name, campaign and duplicate key as the first big load on Nov 25, 2026, and anything already in Supabase is skipped. Alex gets an email with the counts and the name of any source that failed.

Nothing runs on anyone's computer and no keys are stored here. The job only writes to this repo.

The rules for each source (which permits count, which job titles count, which grant programs map to which signal) are in `rl_signals/direct.py` and `rl_signals/sources/`. They copy the rules used for the Nov 25 load.

## Files

| File | What it holds |
|---|---|
| data/signals.csv | Every signal the job has ever found. Used to tell new from old. |
| data/new_signals.csv | Only what was new in the latest run. n8n reads this one. |
| data/new_direct.csv | What the other 15 sources found in the last 14 days. n8n reads this one too. |
| data/direct_runs.csv | One line per source for the latest run: ok or FAILED, with the error. |
| data/last_run.txt | When the job last ran. n8n warns if it is more than 8 days old. |

## Running it by hand

Actions tab, then Weekly signals, then Run workflow. "days" is the look-back for the federal files and "direct days" for the rest. To rerun one source, put its name in "direct sources" (for example `jobbank`).

## When something breaks

Open the **Runs** tab or the red run in GitHub Actions. Each source runs on its own, so one broken government file never stops the others. The error message lists the columns the file actually has, which makes a renamed column a one-line fix.

## Changing the rules

Everything you might tune is in `config.yaml`: points per signal, the minimum award size, which provinces get a bonus, the hot-list size, the occupations and categories to keep, and the names to exclude. Edit it on GitHub and the next run uses the new values.

## Running it on a computer (optional)

```
pip install -r requirements.txt
python -m rl_signals run --dry-run --days 30     # writes CSV files to output/ instead of the sheet
python -m pytest                                  # checks the parsing and scoring logic
```
