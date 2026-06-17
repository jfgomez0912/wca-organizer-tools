# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Streamlit multi-page web app with tools for **WCA (World Cube Association)
organizers and delegates**: analyzing upcoming/in-progress
competitions and summarizing completed ones. Data is fetched live from the WCA
API and WCIF. UI strings are in Spanish.

This project was split out from the Coffee Cubers community app; the community
app keeps the static regional rankings/records pages, while this project keeps
the live, auth-backed organizer tooling.

## Running the App

```bash
streamlit run main.py          # serves on http://localhost:8501
```

Dependencies are managed with **uv** (Python >= 3.13):

```bash
uv lock                        # first time, to generate uv.lock
uv sync                        # install dependencies
```

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

| File | Purpose |
|------|---------|
| `1_home.py` | Landing page |
| `2_competition_analysis.py` | Analyze upcoming/in-progress competitions (novatos, milestones, 3x3 goals) |
| `3_competition_summary.py` | Summarize completed competitions (podiums, medals, PRs); export summary |

### Core Modules

- **`wca.py`** — WCA API client (`wca_get()`), OAuth header/login UI (`render_header()`), WCIF fetching with private-then-public fallback, competition selector widget with tabs (My/Country/ID).
- **`analysis.py`** — Helpers for the analysis page: time formatting (`fmt_seconds`), 3x3 average extraction from WCIF or API fallback, milestone detection, goal tracking, display functions (`display_novatos_y_mujeres`, `display_hitos`, `display_metas_333`).
- **`services/results.py`** — Result parsing for the summary page (from WCIF or API).
- **`ui/cards.py`** — HTML card rendering helpers.
- **`common.py`** — `EVENT_MAPPING` (WCA event IDs to names) and `BASE_SVG_URL` for cubing icons.
- **`config.py`** — API URLs, timeouts, cache TTLs, pagination/worker constants.

### Data Flow

1. **Live competition data**: Fetched from `https://www.worldcubeassociation.org/api/v0` in real-time. WCIF (competition data format) is cached in `st.session_state`.
2. **Auth**: WCA OAuth via Streamlit's built-in `st.login()`/`st.logout()` with Authlib. Post-login redirect uses a JS cookie (`wca_next`).
3. **Private WCIF first**: `wca._fetch_wcif()` attempts the authenticated WCIF endpoint (works for organizers/delegates, including unpublished competitions) and falls back to the public WCIF.

### Key Patterns

- `st.session_state` persists WCIF data and fetched competition lists across page reruns.
- `wca_get()` automatically attaches OAuth bearer tokens when logged in; clears session on 401.
- `ThreadPoolExecutor` is used for parallel WCA API person-data fetches in the analysis page.
- WCA API result values (averages, singles) are in centiseconds — divide by 100 for seconds.

## Conventions

**Language:** UI labels and many variable/function names use Spanish — e.g.,
`novatos` (rookies), `metas` (goals), `hitos` (milestones), `mujeres` (women).

**Caching:** Use `@st.cache_data(ttl=seconds)` for API calls. Countries are
cached 24h, individual persons 1h.

**Page layout pattern:**

```python
st.set_page_config(page_title="...", page_icon="🛠️", layout="wide")
wca.render_header()   # Auth UI at top of every page
```

**WCIF schema:** Competition data uses WCA Competition Information Format — a
JSON object with `persons[]`, `events[]`, `rounds[]`, and `results[]` arrays.
Result values are integers in centiseconds for time events.

### Constants

- `GOALS_333`: Target 3x3 average times in seconds `[4, 5, 6, ..., 60]`
- `MILESTONE_THRESHOLD = 1`: Competition counts ending in 0 or 1 are milestones
- `TOP_N = 10`: Default limit for top-N displays
- `config.PER_PAGE`, `config.LOOKBACK_DAYS`: API pagination and date range defaults
