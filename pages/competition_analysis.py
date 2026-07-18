from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

from wca_tools.analysis import (
    TOP_N,
    closest_goal,
    display_333_goals,
    display_milestones,
    display_newcomers_and_women,
    extract_comp_333_avgs,
    fetch_comp_333_avgs_from_api,
    fetch_live_333_avgs,
    is_milestone,
)
from wca_tools.cards import render_birthday_cards
from wca_tools.config import PERSON_CACHE_TTL, PERSON_FETCH_WORKERS, PERSON_REQUEST_TIMEOUT
from wca_tools.wca import accepted_persons, tool_page, wca_get

BIRTHDAY_THRESHOLD_DAYS = 7


@st.cache_data(ttl=3600)
def _results_posted(comp_id: str) -> bool:
    """Return True only if the WCA has officially posted results for *comp_id*.

    Uses the ``results_posted_at`` field from the competition API endpoint,
    which is ``null`` until results are officially published.  Falls back to
    checking the WCA results endpoint for at least one official result (covers
    older competitions where ``results_posted_at`` may not be populated).
    """
    try:
        comp_info = wca_get(f"competitions/{comp_id}", auth=False)
        if isinstance(comp_info, dict) and comp_info.get("results_posted_at") is not None:
            return True
    except requests.RequestException:
        pass
    # Fallback: check official WCA results (not WCIF) for at least one entry.
    try:
        results = wca_get(f"competitions/{comp_id}/results", auth=False)
        return isinstance(results, list) and len(results) > 0
    except requests.RequestException:
        return False


def _count_actual_participants(wcif: dict) -> int:
    """Count unique competitors who have at least one result in the WCIF."""
    return len({
        result["personId"]
        for event in wcif.get("events", [])
        for rnd in event.get("rounds", [])
        for result in rnd.get("results", [])
    })


@st.cache_data(ttl=PERSON_CACHE_TTL)
def _fetch_person(wca_id: str) -> dict | None:
    """Fetch public person data from WCA API, cached for 1 h."""
    try:
        return wca_get(f"persons/{wca_id}", timeout=PERSON_REQUEST_TIMEOUT, auth=False)
    except requests.RequestException:
        return None


# --- Helpers ---
def fmt_birthday(days: int) -> str:
    if days == 0:
        return "On competition day!"
    d = abs(days)
    label = "day" if d == 1 else "days"
    return f"{d} {label} after" if days > 0 else f"{d} {label} before"


def birthday_delta(birth_date: str, comp_date: datetime) -> int:
    birth_dt = datetime.strptime(birth_date, "%Y-%m-%d")
    try:
        bd = birth_dt.replace(year=comp_date.year)
    except ValueError:
        # Handle Feb 29 birthdays on non-leap years.
        bd = birth_dt.replace(year=comp_date.year, day=28)
    return (bd - comp_date).days


# --- Display functions ---
def display_ages(persons: list[dict], comp_date: datetime) -> None:
    persons_with_bd = [p for p in persons if p.get("birthdate")]
    if not persons_with_bd:
        return

    ages_df = pd.DataFrame(
        [
            {
                "Name": p["name"],
                "Birthdate": p["birthdate"],
                "Age": (comp_date - datetime.strptime(p["birthdate"], "%Y-%m-%d")).days
                // 365,
            }
            for p in persons_with_bd
        ]
    )
    ages_df["_bd"] = pd.to_datetime(ages_df["Birthdate"])

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Youngest (Top {TOP_N})**")
        df = (
            ages_df.nsmallest(TOP_N, "Age")
            .sort_values("_bd", ascending=False)
            .reset_index(drop=True)
        )
        df.index = df.index + 1
        df.index.name = "#"
        st.dataframe(df[["Name", "Birthdate", "Age"]])
    with col2:
        st.markdown(f"**Oldest (Top {TOP_N})**")
        df = (
            ages_df.nlargest(TOP_N, "Age")
            .sort_values("_bd", ascending=True)
            .reset_index(drop=True)
        )
        df.index = df.index + 1
        df.index.name = "#"
        st.dataframe(df[["Name", "Birthdate", "Age"]])


def display_birthdays(birthdays: list[dict]) -> None:
    st.markdown(f"**Birthdays** (within {BIRTHDAY_THRESHOLD_DAYS} days)")
    if not birthdays:
        st.info("No birthdays near the competition.")
        return

    render_birthday_cards(birthdays, fmt_birthday)


# --- Analysis ---
@dataclass
class _AnalysisData:
    newcomers: list[dict] = field(default_factory=list)
    women: list[dict] = field(default_factory=list)
    birthdays: list[dict] = field(default_factory=list)
    milestones: list[dict] = field(default_factory=list)
    goals: list[dict] = field(default_factory=list)


def _comp_333_avgs(wcif: dict) -> dict[int, tuple[float, str]]:
    """3x3 averages from the WCIF, the results API, or WCA Live — first source with data."""
    avgs = extract_comp_333_avgs(wcif)
    if not avgs:
        avgs, _ = fetch_comp_333_avgs_from_api(wcif)
    if not avgs:
        avgs = fetch_live_333_avgs(wcif.get("id", ""), wcif.get("name", ""))
    return avgs


def _fetch_person_infos(wca_ids: list[str]) -> dict[str, dict]:
    """Fetch public person data for many WCA IDs in parallel, with a progress bar."""
    if not wca_ids:
        return {}
    infos: dict[str, dict] = {}
    progress = st.progress(0, text="Loading competitor data...")
    with ThreadPoolExecutor(max_workers=PERSON_FETCH_WORKERS) as ex:
        futures = {ex.submit(_fetch_person, wid): wid for wid in wca_ids}
        for done, future in enumerate(as_completed(futures), 1):
            if result := future.result():
                infos[futures[future]] = result
            progress.progress(done / len(wca_ids), text=f"Loading... {done}/{len(wca_ids)}")
    progress.empty()
    return infos


def _collect_analysis(
    persons: list[dict],
    person_infos: dict[str, dict],
    comp_avgs: dict[int, tuple[float, str]],
    comp_date: datetime,
    has_results: bool,
) -> _AnalysisData:
    """Bucket competitors into newcomers, women, birthdays, milestones and 3x3 goals."""
    data = _AnalysisData()
    for p in persons:
        wca_id = p.get("wcaId")
        reg_id = p.get("registrantId")
        comp_entry = comp_avgs.get(reg_id) if reg_id is not None else None
        comp_avg = comp_entry[0] if comp_entry else None
        comp_round = comp_entry[1] if comp_entry else None
        fmt_avg = round(comp_avg, 2) if comp_avg else None

        birthdate = p.get("birthdate")
        if birthdate:
            days = birthday_delta(birthdate, comp_date)
            if abs(days) <= BIRTHDAY_THRESHOLD_DAYS:
                data.birthdays.append({"Name": p["name"], "Birthday": birthdate, "Days": days})

        if not wca_id:
            if not has_results:
                data.newcomers.append(
                    {"Name": p["name"], "Comp AVG": fmt_avg, "Round": comp_round}
                )
            continue

        if p.get("gender") == "f":
            data.women.append(
                {"Name": p["name"], "WCA ID": wca_id, "Comp AVG": fmt_avg, "Round": comp_round}
            )

        info = person_infos.get(wca_id)
        if info is None:
            continue

        if not has_results:
            num_comps = info.get("competition_count", 0) + 1
            if is_milestone(num_comps):
                data.milestones.append(
                    {"Name": p["name"], "WCA ID": wca_id, "Competitions": num_comps}
                )

        pr = info.get("personal_records", {}).get("333", {}).get("average", {})
        pr_avg = pr.get("best", 0) / 100 if pr.get("best", 0) > 0 else None
        if pr_avg:
            goal, gap = closest_goal(pr_avg)
            data.goals.append(
                {
                    "Name": p["name"],
                    "PR AVG": pr_avg,
                    "Goal": goal,
                    "Difference": round(gap, 2),
                    "Comp AVG": fmt_avg,
                    "Achieved": (comp_avg <= goal) if comp_avg else None,
                }
            )
    return data


def analyze_wcif(wcif: dict) -> None:
    comp_date = datetime.strptime(wcif["schedule"]["startDate"], "%Y-%m-%d")
    persons = accepted_persons(wcif)
    if not persons:
        st.warning("No accepted registrations found.")
        return

    st.subheader(f"Analysis of {wcif['name']}")
    st.caption(comp_date.strftime("%B %d, %Y"))

    has_results = _results_posted(wcif.get("id", ""))
    comp_avgs = _comp_333_avgs(wcif)
    competitor_count = (
        (_count_actual_participants(wcif) or len(persons)) if has_results else len(persons)
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("Competitors", competitor_count)
    col2.metric("Events", len(wcif.get("events", [])))
    col3.metric("Rounds", sum(len(e.get("rounds", [])) for e in wcif.get("events", [])))

    person_infos = _fetch_person_infos([p["wcaId"] for p in persons if p.get("wcaId")])
    data = _collect_analysis(persons, person_infos, comp_avgs, comp_date, has_results)

    has_birthdates = any(p.get("birthdate") for p in persons)
    if has_birthdates:
        display_ages(persons, comp_date)
        st.divider()
    display_newcomers_and_women(data.newcomers, data.women, show_newcomers=not has_results)
    if not has_results:
        st.divider()
        display_milestones(data.milestones)
    if has_birthdates:
        st.divider()
        display_birthdays(data.birthdays)
    st.divider()
    display_333_goals(data.goals, has_results=has_results)


# --- Page ---
st.set_page_config(page_title="Competition Analysis", page_icon="🔍", layout="wide")
st.title("Competition Analysis")

wcif = tool_page("analysis", "wcif_analysis", upcoming=True)
if wcif:
    if not st.session_state.get("wcif_analysis_private"):
        st.caption("Using public WCIF")
    analyze_wcif(wcif)
