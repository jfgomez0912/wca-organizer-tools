# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Streamlit multi-page web app with tools for **WCA (World Cube Association)
organizers and delegates**: analyzing upcoming/in-progress
competitions and summarizing completed ones. Data is fetched live from the WCA
API and WCIF. UI strings and code are in English.

This project was split out from the Coffee Cubers community app; the community
app keeps the static regional rankings/records pages, while this project keeps
the live, auth-backed organizer tooling.

## Running the App

```bash
streamlit run main.py          # serves on http://localhost:8501
```

Dependencies are managed with **uv** (Python pinned to 3.13 via
`.python-version`):

```bash
uv sync                        # install dependencies from pyproject.toml + uv.lock
uv run streamlit run main.py   # run inside the managed environment
```

The project is a uv application (no `[build-system]`, no `requirements.txt`):
`pyproject.toml` + `uv.lock` are the source of truth for dependencies.

WCA OAuth is configured in `.streamlit/secrets.toml` (gitignored). Copy
`.streamlit/secrets.toml.example` and fill in real values.

There is no test suite, linter, or build step configured.

## Architecture

### Entry Point & Navigation

`main.py` registers pages via `st.Page()` / `st.navigation()` and patches
Authlib's `IDToken.validate_nonce` to work around WCA's OIDC implementation
(which omits the nonce claim). It also redirects after OAuth login/logout using
a JS cookie (`wca_next`).

### Pages (`pages/`)

Pages are registered explicitly in `main.py` via `st.navigation`, so filenames
carry no numeric ordering prefix.

| File | Purpose |
|------|---------|
| `home.py` | Landing page |
| `competition_analysis.py` | Analyze upcoming/in-progress competitions (newcomers, women, milestones, 3x3 goals) |
| `competition_summary.py` | Summarize completed competitions (podiums, medals, PRs) |
| `name_badges.py` | Generate a name-badge TSV + person QR codes (CompetitionGroups) for a competition |

### Shared library (`wca_tools/`)

All non-page logic lives in the `wca_tools` package; pages import from it, e.g.
`from wca_tools.wca import tool_page`.

- **`wca.py`** — WCA API client (`wca_get()`), auth/session-expiry helpers (`authenticated()`, `session_expired()`), OAuth header/login UI (`render_header()`), WCIF fetching with private-then-public fallback, competition selector with tabs (My/Country/ID), `?comp=` deep-link loading, and the `tool_page()` scaffold shared by every tool page.
- **`analysis.py`** — Helpers for the analysis page: 3x3 average extraction from WCIF or API fallback, milestone detection, goal tracking, display functions (`display_newcomers_and_women`, `display_milestones`, `display_333_goals`).
- **`results.py`** — Result parsing for the summary page (from WCIF or API).
- **`badges.py`** — Name-badge table + person QR PNG generation (pure, no Streamlit).
- **`cards.py`** — HTML card rendering helpers.
- **`events.py`** — `EVENT_MAPPING` (WCA event IDs to names) and `BASE_SVG_URL` for cubing icons.
- **`formatting.py`** — result-time formatters: `fmt_result` (centiseconds int) and `fmt_seconds` (seconds float).
- **`config.py`** — API URLs, timeouts, cache TTLs, pagination/worker constants.

### Data Flow

1. **Live competition data**: Fetched from `https://www.worldcubeassociation.org/api/v0` in real-time. WCIF (competition data format) is cached in `st.session_state`.
2. **Auth**: WCA OAuth via Streamlit's built-in `st.login()`/`st.logout()` with Authlib. Post-login redirect uses a JS cookie (`wca_next`). An expired token (past `expires_at` or a 401) is treated as signed-out via `authenticated()`/`session_expired()`, so public tools stay usable.
3. **Private WCIF first**: `_fetch_wcif()` in `wca_tools/wca.py` attempts the authenticated WCIF endpoint (works for organizers/delegates, including unpublished competitions) and falls back to the public WCIF.

### Key Patterns

- `tool_page()` renders the shared header + competition selector and returns the loaded WCIF (or `None`); pages only render from it.
- Deep links: `/<page>?comp=<id>` auto-loads that competition (`load_competition_from_query`), reusing the private-then-public fetch.
- `st.session_state` persists WCIF data and fetched competition lists across page reruns.
- `wca_get()` attaches the OAuth bearer token only while `authenticated()`; a 401 flags the session expired and reruns, so the signed-out UI and public tools keep working instead of blocking.
- `ThreadPoolExecutor` is used for parallel WCA API person-data fetches in the analysis page.
- WCA API result values (averages, singles) are in centiseconds — divide by 100 for seconds.

## Conventions

**Language:** UI strings, comments, and identifiers are all in English.

**Caching:** Use `@st.cache_data(ttl=seconds)` for API calls. Countries are
cached 24h, individual persons 1h.

**Page layout pattern:** every tool page is

```python
st.set_page_config(page_title="...", page_icon="...", layout="wide")
st.title("...")
wcif = tool_page("<name>", "wcif_<key>", upcoming=True)  # header + selector; WCIF or None
if wcif:
    ...  # render the tool from the WCIF
```

**WCIF schema:** Competition data uses WCA Competition Information Format — a
JSON object with `persons[]`, `events[]`, `rounds[]`, and `results[]` arrays.
Result values are integers in centiseconds for time events.

### Constants

- `GOALS_333`: Target 3x3 average times in seconds `[4, 5, 6, ..., 60]`
- `MILESTONE_THRESHOLD = 1`: Competition counts ending in 0 or 1 are milestones
- `TOP_N = 10`: Default limit for top-N displays
- `wca_tools.config.PER_PAGE`, `wca_tools.config.LOOKBACK_DAYS`: API pagination and date range defaults
