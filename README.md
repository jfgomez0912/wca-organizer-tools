# WCA Organizer Tools

Streamlit app with tools for **WCA organizers and delegates**:
analyze upcoming/in-progress competitions (rookies, milestones, 3x3 goals) and
summarize completed ones (podiums, medals, PRs). Data comes live from the WCA
API and WCIF; logged-in organizers can load the **private WCIF** of competitions
that are not yet published. UI strings are in Spanish.

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/) (Python >= 3.13):

```bash
uv lock        # generate uv.lock the first time
uv sync        # install dependencies
```

Configure WCA OAuth by copying the secrets template and filling in real values:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml
```

## Running

```bash
streamlit run main.py          # serves on http://localhost:8501
```

## Pages

| File | Purpose |
|------|---------|
| `pages/1_home.py` | Landing page |
| `pages/2_competition_analysis.py` | Analyze upcoming/in-progress competitions |
| `pages/3_competition_summary.py` | Summarize completed competitions; export summary |

## Scripts

- `scripts/generate_chinchina_person_qr.py` — generate per-person QR PNGs for a
  competition (CompetitionGroups) and update the registration CSV.
