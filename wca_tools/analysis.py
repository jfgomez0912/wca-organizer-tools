"""Shared helpers for the Competition Analysis page."""

import altair as alt
import pandas as pd
import requests
import streamlit as st

from .config import WCA_LIVE_API
from .formatting import fmt_goal, fmt_seconds
from .results import ROUND_TYPE_LABEL
from .cards import render_milestone_cards
from .wca import wca_get

GOALS_333 = [4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.0, 15.0, 20.0, 30.0, 60.0]
# Milestones: competitions whose count ends in 0 or 1 (1st, 10th, 20th, 21st, …)
MILESTONE_THRESHOLD = 1
TOP_N = 10


def is_milestone(n: int) -> bool:
    return n >= MILESTONE_THRESHOLD and n % 10 <= MILESTONE_THRESHOLD


def closest_goal(avg: float) -> tuple[float, float]:
    achievable = [g for g in GOALS_333 if g < avg]
    goal = max(achievable) if achievable else min(GOALS_333)
    return goal, avg - goal


def ranked_df(data: list[dict], sort_by: str, **sort_kwargs) -> pd.DataFrame:
    df = pd.DataFrame(data).sort_values(sort_by, na_position="last", **sort_kwargs)
    df.insert(0, "#", range(1, len(df) + 1))
    return df


def _round_label(round_num: int, num_rounds: int) -> str:
    return "Final" if round_num == num_rounds else f"R{round_num}"


def extract_comp_333_avgs(wcif: dict) -> dict[int, tuple[float, str]]:
    """Returns dict[registrant_id -> (best_avg_seconds, round_label)]."""
    event_333 = next(
        (e for e in wcif.get("events", []) if e["id"] == "333"), None
    )
    if not event_333:
        return {}
    rounds = event_333.get("rounds", [])
    num_rounds = len(rounds)
    avgs: dict[int, tuple[float, str]] = {}
    for idx, rnd in enumerate(rounds):
        label = _round_label(idx + 1, num_rounds)
        for result in rnd.get("results", []):
            avg = result.get("average", 0)
            if avg <= 0:
                continue
            pid = result["personId"]
            avg_seconds = avg / 100
            existing = avgs.get(pid)
            if existing is None or avg_seconds < existing[0]:
                avgs[pid] = (avg_seconds, label)
    return avgs


def fetch_comp_333_avgs_from_api(
    wcif: dict,
) -> tuple[dict[int, tuple[float, str]], int]:
    """Fallback for when WCIF has no results (e.g. competitions using WCA Live).

    Returns (avgs, participant_count) where participant_count is the number of
    unique competitors who appeared in any event result.
    """
    comp_id = wcif.get("id", "")
    wca_id_to_reg = {
        p["wcaId"]: p["registrantId"] for p in wcif.get("persons", []) if p.get("wcaId")
    }
    name_to_reg = {
        p["name"]: p["registrantId"]
        for p in wcif.get("persons", [])
        if not p.get("wcaId")
    }
    avgs: dict[int, tuple[float, str]] = {}
    participants: set[str] = set()
    try:
        results = wca_get(f"competitions/{comp_id}/results", auth=False)
        for r in results:
            name = r.get("name", "")
            if name:
                participants.add(name)
            if r.get("event_id") != "333":
                continue
            avg = r.get("average", 0)
            if avg <= 0:
                continue
            wca_id = r.get("wca_id")
            reg_id = (
                wca_id_to_reg.get(wca_id)
                if wca_id
                else name_to_reg.get(name)
            )
            if not reg_id:
                continue
            avg_seconds = avg / 100
            rt = r.get("round_type_id", "")
            label = ROUND_TYPE_LABEL.get(rt, rt or "-")
            existing = avgs.get(reg_id)
            if existing is None or avg_seconds < existing[0]:
                avgs[reg_id] = (avg_seconds, label)
    except requests.HTTPError:
        pass
    return avgs, len(participants)


_LIVE_SEARCH_QUERY = """
query($filter: String!) {
  competitions(filter: $filter, limit: 5) {
    id
    wcaId
  }
}
"""

_LIVE_RESULTS_QUERY = """
query($id: ID!) {
  competition(id: $id) {
    competitionEvents {
      event { id }
      rounds {
        number
        results {
          person { registrantId }
          average
        }
      }
    }
  }
}
"""


def _live_post(query: str, variables: dict) -> dict | None:
    """Post a GraphQL query to WCA Live and return parsed JSON, or None on error."""
    try:
        resp = requests.post(
            WCA_LIVE_API,
            json={"query": query, "variables": variables},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    if "errors" in data:
        return None
    return data


def fetch_live_333_avgs(
    comp_id: str, comp_name: str
) -> dict[int, tuple[float, str]]:
    """Fetch 3x3 averages from WCA Live (for ongoing competitions)."""
    # Step 1: find database ID by competition name
    data = _live_post(_LIVE_SEARCH_QUERY, {"filter": comp_name})
    if not data:
        return {}

    comps = (data.get("data") or {}).get("competitions", [])
    match = next((c for c in comps if c.get("wcaId") == comp_id), None)
    if not match:
        return {}

    # Step 2: fetch results using database ID
    data = _live_post(_LIVE_RESULTS_QUERY, {"id": match["id"]})
    if not data:
        return {}

    comp = (data.get("data") or {}).get("competition")
    if not comp:
        return {}

    avgs: dict[int, tuple[float, str]] = {}
    for ce in comp.get("competitionEvents", []):
        if ce.get("event", {}).get("id") != "333":
            continue
        rounds = ce.get("rounds", [])
        num_rounds = len(rounds)
        for rnd in rounds:
            label = _round_label(rnd.get("number", 0), num_rounds)
            for r in rnd.get("results", []):
                avg = r.get("average", 0)
                if not avg or avg <= 0:
                    continue
                pid = r.get("person", {}).get("registrantId")
                if pid is None:
                    continue
                avg_seconds = avg / 100
                existing = avgs.get(pid)
                if existing is None or avg_seconds < existing[0]:
                    avgs[pid] = (avg_seconds, label)
    return avgs


def display_newcomers_and_women(
    newcomers: list[dict], women: list[dict], *, show_newcomers: bool = True
) -> None:
    cols = st.columns(2) if show_newcomers else [st.container()]
    if show_newcomers:
        with cols[0]:
            st.markdown(f"**Newcomers** ({len(newcomers)})")
            if newcomers:
                st.dataframe(
                    ranked_df(newcomers, "Comp AVG").style.format(
                        {"Comp AVG": fmt_seconds}, na_rep="-"
                    ),
                    hide_index=True,
                )
            else:
                st.info("No newcomers.")
    with cols[-1]:
        st.markdown(f"**Women** ({len(women)})")
        if women:
            st.dataframe(
                ranked_df(women, "Comp AVG").style.format(
                    {"Comp AVG": fmt_seconds}, na_rep="-"
                ),
                hide_index=True,
            )
        else:
            st.info("No women competitors.")


def display_milestones(milestones: list[dict]) -> None:
    st.markdown(f"**Competition milestones** ({len(milestones)})")
    if not milestones:
        st.info("No competitors at a milestone.")
        return

    render_milestone_cards(milestones)


def display_333_goals(goals: list[dict], *, has_results: bool = False) -> None:
    st.markdown(f"**3x3x3 PR average & nearest goals** ({len(goals)})")
    st.caption(
        "Each goal is a **sub-X** target: e.g. *sub-10.00* means averaging under "
        "10 seconds (9.99 or faster)."
    )
    if has_results:
        st.caption(
            "⚠️ The PR averages are each competitor's current ones, not those at the "
            "time of the competition. The nearest goals may not reflect their actual goal back then."
        )
    if not goals:
        st.info("No 3x3x3 average data.")
        return

    df = pd.DataFrame(goals).sort_values("PR AVG")

    # Distribution of competitors by goal bucket
    goal_dist = df.groupby("Goal").size().reset_index(name="Competitors")
    goal_dist = goal_dist.sort_values("Goal")
    goal_dist["label"] = goal_dist["Goal"].apply(fmt_goal)
    st.altair_chart(
        alt.Chart(goal_dist)
        .mark_bar()
        .encode(
            x=alt.X("label:N", sort=list(goal_dist["label"]), title="Goal"),
            y=alt.Y("Competitors:Q"),
            tooltip=["label", "Competitors"],
        ),
        width="stretch",
    )
    if has_results:
        # Past competition: show Comp AVG, omit Achieved
        st.dataframe(
            df[["Name", "PR AVG", "Goal", "Difference", "Comp AVG"]].style.format(
                {
                    "PR AVG": fmt_seconds,
                    "Goal": fmt_goal,
                    "Difference": fmt_seconds,
                    "Comp AVG": fmt_seconds,
                },
                na_rep="-",
            ),
            hide_index=True,
        )
        return

    # Upcoming / in-progress: show Comp AVG (may be empty) + Achieved with highlight
    total_with_results = df["Comp AVG"].notna().sum()
    if total_with_results:
        achieved_count = int(df["Achieved"].sum())
        st.caption(f"Goal reached: {achieved_count} / {total_with_results} competitors")

    df["Achieved"] = df["Achieved"].astype("boolean")

    def highlight(row):
        if row["Achieved"] is True:
            return ["background-color: #d4edda"] * len(row)
        if row["Achieved"] is False:
            return [""] * len(row)
        return ["color: #999"] * len(row)

    st.dataframe(
        df.style.apply(highlight, axis=1).format(
            {
                "PR AVG": fmt_seconds,
                "Goal": fmt_goal,
                "Difference": fmt_seconds,
                "Comp AVG": fmt_seconds,
            },
            na_rep="-",
        ),
        hide_index=True,
        column_config={"Achieved": st.column_config.CheckboxColumn(disabled=True)},
    )
