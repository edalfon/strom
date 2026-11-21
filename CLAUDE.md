# CLAUDE.md

Personal data project that tracks household electricity use ("Strom" = normal electricity, meter 1; "Wärmestrom" = heat-pump/heating electricity, meters 2 and 3, low and high tariff). It ingests meter readings, combines them with German weather data from DWD (Deutscher Wetterdienst), fits models of consumption against climate, and publishes a Quarto website to GitHub Pages. The package scaffold (README, CONTRIBUTING, `.readthedocs.yml`) is leftover cookiecutter boilerplate and doesn't describe the project.

## Commands

The project uses `uv`. Python 3.11 is pinned in `.python-version`.

```bash
uv sync                                                              # install deps (incl. quarto-cli)
uv run python -c "from strom import strom_flow; strom_flow.strom_flow()"   # run the full pipeline (what CI runs)
uv run pytest -s tests/ --cov=strom                                  # tests
uv run pytest tests/test_consumption.py::test_get_period             # single test
quarto render quarto --execute-dir . [--metadata freeze:false]       # render site only (output -> results/)
quarto preview quarto --execute-dir .
```

`Makefile` has `render`, `render_all`, `preview` and `test`. These use Windows `start`. The `prefect_*` and `metaflow_*` targets are stale: `prefect_flow.py` and `flow.py` no longer exist.

## Pipeline architecture (`src/strom/strom_flow.py`)

`strom_flow()` is the orchestrator. Steps are cached with **stepit** (`@stepit` decorator). Results are pickled into `.stepit_cache/<function_name>` and reused when the inputs and the source code haven't changed. CI commits `.stepit_cache/` back to the repo, so it is versioned state, not junk. Don't delete it casually.

Flow:
1. `gsheets.ingest_strom_gsheet`: reads one worksheet per meter from the Google Sheet configured in `config.toml` (`[gsheets]` sheet_id + meterid→tab-name map) and writes a DuckDB table `strom`. It needs the `GOOGLE_SHEETS_CREDENTIALS_JSON` env var (service account JSON; `.env` is loaded via python-dotenv). It is deliberately **not** cached: it returns an md5 of the table, and that md5 is the change signal that invalidates downstream steps. The same pattern (returning `duck_md5(...)` instead of data) is used elsewhere so the cache sees changes without passing whole tables around.
2. `meter.make_strom_intervals` → table `strom_intervals` (one row per reading interval, with consumption-per-minute `cm`). The project moved away from minute-level expansion to an interval-overlap approach.
3. `meter.make_strom_per_day|month|hour` → tables `strom_per_day/month/hour`. The columns are `nd` (normal), `wd` (wärme = `nt` + `ht`) and `obs`/`weight`. Only two observation periods are kept: **2020-12-01 – 2021-05-25** and **from 2022-12-01**. These dates are hard-coded in several places (meter.py, strom_flow.py).
4. `dwd.get_climate_data`: scrapes the hourly DWD open-data listings (air temperature, dew point, moisture, precipitation) and aggregates them to daily min/max/mean/median/std.
5. `merge_strom_climate_data`: joins the daily consumption and climate data, then forward-fills NAs.
6. `consumption.*`: average-consumption summaries and `compare_last_days` (run under multiple cache keys via `.update(key=...)`).
7. `modelling.split_data` (train/test cutoff date is hard-coded in the flow).
8. `quarto.render_report`: renders the site. It takes `quarto.detect_changes()` (hashes of `.qmd/.yml/.css`) as an argument, so it only re-renders when the data or templates change. It writes `rendered=true` to `$GITHUB_OUTPUT` so CI can skip the Pages deploy.

Shared SQL: `meter.STROM_WINDOW_SQL` computes `minutes`, `consumption` and `cm` from `(meterid, date, value, first)`. It is used by both the Google Sheets path and the legacy sqlite path (`meter.ingest_strom`, which reads `data/*-ecas-export.db`, the old phone-app exports). `first = 1` marks a meter (re)start, where consumption is NULL.

In `consumption.py`, the `minute_table` arguments (`"normalstrom_minute"`, `"waermestrom_minute"`) are legacy names. They are now only keys that map to meter IDs and prices, and they no longer refer to real tables.

## Data and storage

- `duckdb/strom.duckdb`: the main DB (gitignored, cached in CI via `actions/cache`). Paths are relative to the repo root, so run everything from there.
- `connections.ini`: jupysql DSN sections `duck` (strom.duckdb) and `ducktest` (strom_test.duckdb), used by the notebooks via `%sql --section duck`.
- `data/`: historical sqlite exports plus `pooltemp/` CSVs. `interim/`: parquet intermediates.
- `vetiver/`: pins board for model versioning (`strom.get_board`/`log_vetiver`).

## Quarto site (`quarto/` → `results/`)

- `_quarto.yml` uses `execute-dir: project`, `output-dir: ../results` and `freeze: auto`. Always render with `--execute-dir .` so relative paths resolve from the repo root.
- Pages read data in two ways: from DuckDB tables via jupysql (`%%sql` / `<<` assignment), and from pipeline outputs via `strom.read_result("<stepit key>")` (e.g. `index.qmd`). If you rename a stepit-cached function, update those `read_result` keys.
- `05_model_waermestrom/` holds the modelling notebooks (naive, baseline, polynomial, RF, GBM, SVM, H2O). They use the helper functions in `strom/strom.py`: CV, grid-search plotting, residual diagnostics and vetiver helpers, all re-exported from `strom/__init__.py`.
- `_`-prefixed files are partials or playgrounds and aren't rendered as pages.

## CI (`.github/workflows/`)

- `run_workflow.yml` runs on push to any branch, hourly cron, repository_dispatch or manual trigger. It runs `uv sync`, then the flow, commits `.stepit_cache/` ("Commit changes made by workflow") and deploys `results/` to `gh-pages`. Many commits in the history are these bot commits.
- `fetch_latest_data.yml`: opening an issue triggers rclone to copy `*-ecas-export.db` from OneDrive into `data/`, commit, dispatch the main workflow and close the issue. This is the legacy ingestion route.

## Known issues

- `tests/test_strom.py` calls `meter.ingest_normalstrom.fn`, which no longer exists. `tests/test_consumption.py` also uses `.fn`, a Prefect-era API. Both are probably broken.
- `tests/test_consumption.py` needs a populated `duckdb/strom.duckdb`. `tests/test_gsheets.py` is skipped unless credentials are set.
- `modelling.py` defines `mod_rf` twice; the second definition wins.
- Comments and docstrings still mention Prefect. The orchestration is now plain Python + stepit.
