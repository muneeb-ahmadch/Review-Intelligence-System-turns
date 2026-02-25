# Review Intelligence LLM + NLP MVP

Local MVP scaffold for ingesting app review CSVs into DuckDB, running a staged pipeline, and serving a Gradio dashboard.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Data

Current review CSV files are available in `data/`:

- `data/converted_reviews_good.csv`
- `data/converted_reviews_average.csv`
- `data/converted_reviews_bad.csv`

Detected headers:
`reviewId,userName,content,score,thumbsUpCount,reviewCreatedVersion,at,appVersion,category`

## Run Pipeline (placeholder)

```bash
bash scripts/run_pipeline.sh
```

Current pipeline scripts are scaffolds for steps `00` to `09` and will be implemented incrementally.

## Run Gradio App (placeholder)

```bash
bash scripts/run_app.sh
```

The Gradio app now uses a dashboard-style UI with:

- Sidebar navigation for Overview, Trends, Issues, Release Diff, Executive Brief, and Sprint Planner
- Calendar date pickers with quick presets (`7D`, `30D`, `90D`, `YTD`)
- Upgraded matplotlib chart styling for dashboard readability
- Sprint backlog ticket board rendering plus raw JSON toggle and CSV export

No backend run-command changes were introduced. Keep using `bash scripts/run_app.sh`.
