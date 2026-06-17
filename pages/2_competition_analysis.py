from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, cast

import pandas as pd
import requests
import streamlit as st

from analysis import (
    TOP_N,
    closest_goal,
    display_hitos,
    display_metas_333,
    display_novatos_y_mujeres,
    extract_comp_333_avgs,
    fetch_comp_333_avgs_from_api,
    fetch_live_333_avgs,
    is_milestone,
)
from config import PERSON_CACHE_TTL, PERSON_FETCH_WORKERS, PERSON_REQUEST_TIMEOUT, WCA_API
from ui.cards import render_birthday_cards
from wca import accepted_persons, render_competition_selector, render_header, wca_get

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
        if isinstance(comp_info, dict):
            comp_info_dict = cast(dict[str, Any], comp_info)
            if comp_info_dict.get("results_posted_at") is not None:
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
        resp = requests.get(f"{WCA_API}/persons/{wca_id}", timeout=PERSON_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


# --- Helpers ---
def fmt_birthday(days: int) -> str:
    if days == 0:
        return "¡El día de la competencia!"
    d = abs(days)
    label = "día" if d == 1 else "días"
    return f"{d} {label} después" if days > 0 else f"{d} {label} antes"


def birthday_delta(birth_date: str, comp_date: datetime) -> int:
    birth_dt = datetime.strptime(birth_date, "%Y-%m-%d")
    try:
        bd = birth_dt.replace(year=comp_date.year)
    except ValueError:
        # Handle Feb 29 birthdays on non-leap years.
        bd = birth_dt.replace(year=comp_date.year, day=28)
    return (bd - comp_date).days


# --- Display functions ---
def display_edades(persons: list[dict], comp_date: datetime) -> None:
    persons_with_bd = [p for p in persons if p.get("birthdate")]
    if not persons_with_bd:
        return

    ages_df = pd.DataFrame(
        [
            {
                "Nombre": p["name"],
                "Fecha nac.": p["birthdate"],
                "Edad": (comp_date - datetime.strptime(p["birthdate"], "%Y-%m-%d")).days
                // 365,
            }
            for p in persons_with_bd
        ]
    )
    ages_df["_bd"] = pd.to_datetime(ages_df["Fecha nac."])

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Más jóvenes (Top {TOP_N})**")
        df = (
            ages_df.nsmallest(TOP_N, "Edad")
            .sort_values("_bd", ascending=False)
            .reset_index(drop=True)
        )
        df.index = df.index + 1
        df.index.name = "#"
        st.dataframe(df[["Nombre", "Fecha nac.", "Edad"]])
    with col2:
        st.markdown(f"**Mayores (Top {TOP_N})**")
        df = (
            ages_df.nlargest(TOP_N, "Edad")
            .sort_values("_bd", ascending=True)
            .reset_index(drop=True)
        )
        df.index = df.index + 1
        df.index.name = "#"
        st.dataframe(df[["Nombre", "Fecha nac.", "Edad"]])


def display_cumpleanos(birthdays: list[dict]) -> None:
    st.markdown(f"**Cumpleañeros** (en los {BIRTHDAY_THRESHOLD_DAYS} días)")
    if not birthdays:
        st.info("Sin cumpleaños cercanos a la competencia.")
        return

    render_birthday_cards(birthdays, fmt_birthday)


# --- Analysis ---
def analyze_wcif(wcif: dict) -> None:
    comp_date = datetime.strptime(wcif["schedule"]["startDate"], "%Y-%m-%d")
    persons = accepted_persons(wcif)
    if not persons:
        st.warning("No se encontraron inscripciones aceptadas.")
        return

    st.subheader(f"Análisis de {wcif['name']}")
    st.caption(comp_date.strftime("%d de %B de %Y"))

    event_count = len(wcif.get("events", []))
    total_rounds = sum(len(e.get("rounds", [])) for e in wcif.get("events", []))

    has_results = _results_posted(wcif.get("id", ""))
    comp_avgs = extract_comp_333_avgs(wcif)
    if not comp_avgs:
        comp_avgs, _ = fetch_comp_333_avgs_from_api(wcif)
    if not comp_avgs:
        comp_avgs = fetch_live_333_avgs(wcif.get("id", ""), wcif.get("name", ""))
    if has_results:
        competitor_count = _count_actual_participants(wcif) or len(persons)
    else:
        competitor_count = len(persons)

    col1, col2, col3 = st.columns(3)
    col1.metric("Competidores", competitor_count)
    col2.metric("Eventos", event_count)
    col3.metric("Rondas", total_rounds)

    novatos, mujeres, cumpleanos, hitos, metas = [], [], [], [], []

    # Fetch all person records in parallel (sequential would take ~1 s × N competitors)
    wca_ids = [p["wcaId"] for p in persons if p.get("wcaId")]
    person_infos: dict[str, dict] = {}
    if wca_ids:
        progress = st.progress(0, text="Cargando datos de competidores...")
        with ThreadPoolExecutor(max_workers=PERSON_FETCH_WORKERS) as ex:
            futures = {ex.submit(_fetch_person, wid): wid for wid in wca_ids}
            for done, future in enumerate(as_completed(futures), 1):
                wid = futures[future]
                result = future.result()
                if result:
                    person_infos[wid] = result
                progress.progress(done / len(wca_ids), text=f"Cargando... {done}/{len(wca_ids)}")
        progress.empty()

    for p in persons:
        wca_id = p.get("wcaId")
        birthdate = p.get("birthdate")
        gender = p.get("gender", "")
        reg_id = p.get("registrantId")
        comp_entry = comp_avgs.get(reg_id) if reg_id is not None else None
        comp_avg = comp_entry[0] if comp_entry else None
        comp_round = comp_entry[1] if comp_entry else None
        fmt_avg = round(comp_avg, 2) if comp_avg else None

        if birthdate:
            days = birthday_delta(birthdate, comp_date)
            if abs(days) <= BIRTHDAY_THRESHOLD_DAYS:
                cumpleanos.append(
                    {"Nombre": p["name"], "Cumpleaños": birthdate, "Días": days}
                )

        if not wca_id:
            if not has_results:
                novatos.append(
                    {"Nombre": p["name"], "Comp AVG": fmt_avg, "Ronda": comp_round}
                )
            continue

        if gender == "f":
            mujeres.append(
                {
                    "Nombre": p["name"],
                    "WCA ID": wca_id,
                    "Comp AVG": fmt_avg,
                    "Ronda": comp_round,
                }
            )

        info = person_infos.get(wca_id)
        if info is None:
            continue

        if not has_results:
            num_comps = info.get("competition_count", 0) + 1
            if is_milestone(num_comps):
                hitos.append(
                    {"Nombre": p["name"], "WCA ID": wca_id, "Competencias": num_comps}
                )

        pr = info.get("personal_records", {}).get("333", {}).get("average", {})
        pr_avg = pr.get("best", 0) / 100 if pr.get("best", 0) > 0 else None
        if pr_avg:
            goal, gap = closest_goal(pr_avg)
            achieved = comp_avg is not None and comp_avg <= goal
            metas.append(
                {
                    "Nombre": p["name"],
                    "PR AVG": pr_avg,
                    "Meta": goal,
                    "Diferencia": round(gap, 2),
                    "Comp AVG": fmt_avg,
                    "Logrado": achieved if comp_avg else None,
                }
            )

    has_birthdates = any(p.get("birthdate") for p in persons)
    if has_birthdates:
        display_edades(persons, comp_date)
        st.divider()
    display_novatos_y_mujeres(novatos, mujeres, show_novatos=not has_results)
    if not has_results:
        st.divider()
        display_hitos(hitos)
    if has_birthdates:
        st.divider()
        display_cumpleanos(cumpleanos)
    st.divider()
    display_metas_333(metas, has_results=has_results)


# --- Page ---
st.set_page_config(layout="wide")
st.title("Competition Analysis")

render_header(page="analysis")
st.divider()
render_competition_selector("wcif_analysis", upcoming=True)

if "wcif_analysis" in st.session_state:
    if not st.session_state.get("wcif_analysis_private"):
        st.caption("Usando WCIF público")
    analyze_wcif(st.session_state["wcif_analysis"])
