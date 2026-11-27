# rl-signals

Every Monday morning GitHub runs this job for free. It downloads government files (federal contract awards, CanadaBuys awards, federal grants and LMIA hiring approvals), finds companies showing signs they need financing, and saves the new ones in `data/new_signals.csv` in this repo.

At 9am Toronto time the n8n workflow "RL Signals - Weekly GitHub signals into Supabase" picks up that file and loads it into Supabase, where the outreach system takes over. It labels each signal the same way the first big load did, skips anything already in Supabase, and emails Alex a short summary.

Nothing runs on anyone's computer and no keys are stored here. The job only writes to this repo.

## Files

| File | What it holds |
|---|---|
| data/signals.csv | Every signal the job has ever found. Used to tell new from old. |
| data/new_signals.csv | Only what was new in the latest run. n8n reads this one. |
| data/last_run.txt | When the job last ran. n8n warns if it is more than 8 days old. |

## Running it by hand

Actions tab, then Weekly signals, then Run workflow. Set days to 180 to reload six months.

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
