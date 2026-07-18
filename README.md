# WCA Organizer Tools

Streamlit app with tools for **WCA organizers and delegates**:
analyze upcoming/in-progress competitions (newcomers, milestones, 3x3 goals),
summarize completed ones (podiums, medals, PRs), and generate name badges with
QR codes. Data comes live from the WCA API and WCIF; logged-in organizers can
load the **private WCIF** of competitions that are not yet published. The UI is
in English.

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/) (Python pinned to
3.13 via `.python-version`):

```bash
uv sync        # install dependencies from pyproject.toml + uv.lock
```

Configure WCA OAuth by copying the secrets template and filling in real values:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml
```

## Running

```bash
uv run streamlit run main.py   # serves on http://localhost:8501
```

Each tool supports deep links: `/<page>?comp=<competitionId>` opens that
competition directly (e.g. `/competition_analysis?comp=UnicentroPereira2023`).

## Project layout

```
main.py                 # entry point: st.navigation + OAuth redirect
pages/                  # one file per tool (registered explicitly in main.py)
  home.py
  competition_analysis.py
  competition_summary.py
  name_badges.py
wca_tools/              # shared library (WCA client, analysis, formatting, ...)
.streamlit/             # config.toml + secrets.toml.example
```

## Pages

| Page | Purpose |
|------|---------|
| `home.py` | Landing page |
| `competition_analysis.py` | Analyze upcoming/in-progress competitions |
| `competition_summary.py` | Summarize completed competitions |
| `name_badges.py` | Name-badge TSV + person QR codes for a competition |
