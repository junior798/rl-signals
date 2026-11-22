# rl-signals

Every Monday this job downloads free government files, finds companies showing signs they will need equipment financing, scores them, and writes the results to a Google Sheet.

The sources are Quebec public contract awards (SEAO), federal contract awards (CanadaBuys), federal grants, employers approved to hire foreign workers (LMIA), and Job Bank postings.

Nothing runs on your computer. GitHub runs it for free, and if a run fails, GitHub emails you.

## What ends up in the sheet

| Tab | What it holds |
|---|---|
| Signals | Every signal ever found, one row each. Never deleted. |
| Companies | One row per company with its score, tier (hot, sequence, hold) and the event that triggered it. Rebuilt every run. |
| Hot list | The top 30 companies with a score of 60 or more. |
| Runs | One line per source per run: how many signals it found, how many were new, and any error. |

## One-time setup (about 20 minutes)

1. **GitHub.** Create an account at github.com, then a **private** repository named `rl-signals`. Upload every file in this folder, including the hidden `.github` folder.
2. **Google Sheet.** Create a blank Google Sheet. Its ID is the long part of the URL between `/d/` and `/edit`.
3. **Google service account** (this is how the job writes to the sheet):
   - Go to console.cloud.google.com and create a project.
   - Enable the **Google Sheets API**.
   - Go to IAM and Admin, then Service Accounts, and create one. Open it, go to Keys, then Add key, then JSON. A file downloads.
   - Share the Google Sheet with the service account's email address (it ends in `iam.gserviceaccount.com`) as an **Editor**.
4. **Secrets.** In the GitHub repo, go to Settings, then Secrets and variables, then Actions, and add two secrets:
   - `GOOGLE_SERVICE_ACCOUNT_JSON`: paste the whole content of the JSON file.
   - `SHEET_ID`: the sheet ID from step 2.
5. **First run.** In the repo, go to Actions, then Weekly signals, then Run workflow. Set **days = 180** so it loads six months, then run it. Later Monday runs load the last 21 days on their own.

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
