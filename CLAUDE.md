# Notes for Claude Code

This file tells Claude Code how to work in this repository.

## About the project

A small Python data pipeline and Streamlit dashboard for armed-conflict deaths by country. See README.md for the full picture.

## About the author

I am learning. When you change something, explain what you changed and why in plain English, and tell me which lines to read. Prefer simple, readable code over clever code. Do not add a dependency or a new file unless it is clearly needed.

## Commands

- Build the database: `python run_pipeline.py`
- Build from the fictional sample (no internet): `python run_pipeline.py --source tests/fixtures/sample_conflict_deaths.csv --type-source tests/fixtures/sample_conflict_deaths_by_type.csv`
- Run the tests: `pytest`
- Start the dashboard: `streamlit run app.py`

## Rules

- Run `pytest` after every change. All tests must pass before a commit.
- New behaviour needs a test. Tests must not use the internet; use the sample file in `tests/fixtures/`.
- Settings (paths, URLs, thresholds) belong in `conflict_monitor/config.py`.
- SQL questions belong in `conflict_monitor/analysis.py`. `app.py` is layout only.
- Never commit `data/`, `.env`, or any password or API key. Read keys from environment variables.
- Preliminary years (after `LAST_FULL_YEAR`) must stay out of comparisons and be labelled wherever they are shown.
- Any text generated for a reader must come only from figures in the database, name its source, and say it needs analyst review.

## Git

- Work on a branch, one change per branch. Open a pull request into `main`.
- Write commit messages that say what changed and why, in one line.
