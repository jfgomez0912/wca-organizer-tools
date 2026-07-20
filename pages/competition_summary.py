from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

from wca_tools.config import PERSON_CACHE_TTL, PERSON_FETCH_WORKERS, PERSON_REQUEST_TIMEOUT
from wca_tools.events import BASE_SVG_URL, EVENT_MAPPING
from wca_tools.formatting import fmt_result
from wca_tools.results import fetch_results_from_api, parse_results_from_wcif
from wca_tools.wca import accepted_persons, tool_page, wca_get

# Events where ranking is based on single (no average used)
NO_AVERAGE_EVENTS = {"333bf", "444bf", "555bf", "333mbf"}

# Shared tooltip CSS for event icon spans
_TOOLTIP_CSS = (
    ".ev-tip{position:relative;display:inline-block;}"
    ".ev-tip img{width:22px;height:22px;opacity:0.75;}"
    ".ev-tip::after{content:attr(data-tip);position:absolute;bottom:130%;left:50%;"
    "transform:translateX(-50%);background:#333;color:#fff;padding:3px 8px;"
    "border-radius:4px;white-space:nowrap;font-size:11px;pointer-events:none;"
    "opacity:0;transition:opacity 0.15s;}"
    ".ev-tip:hover::after{opacity:1;}"
)


def _event_icon(event_id: str) -> str:
    """Return an HTML span with event icon and tooltip."""
    name = EVENT_MAPPING.get(event_id, event_id)
    return (
        f'<span class="ev-tip" data-tip="{name}">'
        f'<img src="{BASE_SVG_URL.format(event_id)}" '
        f"onerror=\"this.style.display='none'\" alt=\"{event_id}\" /></span>"
    )


def primary_result(single: int, average: int, event_id: str) -> int:
    """Return the primary result (average if valid and applicable, else single)."""
    if event_id not in NO_AVERAGE_EVENTS and average > 0:
        return average
    return single


def _final_round_df(df: pd.DataFrame) -> pd.DataFrame:
    """Filter df to keep only the final round row(s) for each event."""
    final_rounds = df.groupby("event_id")["round_id"].transform("max")
    return df[df["round_id"] == final_rounds]


def display_podiums(df: pd.DataFrame) -> None:
    st.markdown("**Podiums by event**")

    df_final = _final_round_df(df)
    df_podium = df_final[df_final["ranking"] <= 3].copy()

    rows_html = []
    for event_id in df_podium["event_id"].unique():
        event_df = df_podium[df_podium["event_id"] == event_id].sort_values("ranking")
        event_name = EVENT_MAPPING.get(event_id, event_id)
        icon_url = BASE_SVG_URL.format(event_id)

        places: dict[int, str] = {}
        for _, r in event_df.iterrows():
            result = primary_result(r["single"], r["average"], event_id)
            places[r["ranking"]] = f"{r['name']} ({fmt_result(result, event_id)})"

        rows_html.append(
            f"""<tr>
              <td>
                <div class="ev-cell">
                  <img src="{icon_url}" onerror="this.style.display='none'" alt="" />
                  {event_name}
                </div>
              </td>
              <td>{places.get(1, "-")}</td>
              <td>{places.get(2, "-")}</td>
              <td>{places.get(3, "-")}</td>
            </tr>"""
        )

    if rows_html:
        st.html(f"""
        <style>
          .podium-tbl {{width:100%;border-collapse:collapse;font-size:13px;}}
          .podium-tbl th {{text-align:left;padding:6px 10px;border-bottom:2px solid #e0e0e0;font-weight:600;color:#555;}}
          .podium-tbl td {{padding:6px 10px;border-bottom:1px solid #f5f5f5;vertical-align:middle;}}
          .ev-cell {{display:flex;align-items:center;gap:8px;}}
          .ev-cell img {{width:20px;height:20px;opacity:0.75;}}
        </style>
        <table class="podium-tbl">
          <tr><th>Event</th><th>🥇</th><th>🥈</th><th>🥉</th></tr>
          {"".join(rows_html)}
        </table>
        """)
    else:
        st.info("No final results available.")


def display_medal_table(df: pd.DataFrame) -> None:
    st.markdown("**Medal table**")

    df_final = _final_round_df(df)
    medals = df_final[df_final["ranking"].isin([1, 2, 3])]
    if medals.empty:
        st.info("No medal data.")
        return

    counts = (
        medals.assign(medal=medals["ranking"].map({1: "Gold", 2: "Silver", 3: "Bronze"}))
        .groupby(["name", "medal"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=["Gold", "Silver", "Bronze"], fill_value=0)
        .reset_index()
    )
    counts["Total"] = counts["Gold"] + counts["Silver"] + counts["Bronze"]
    medal_df = counts.sort_values(
        ["Total", "Gold", "Silver", "Bronze"], ascending=False
    ).rename(columns={"name": "Name"})[["Name", "Total", "Gold", "Silver", "Bronze"]]

    st.dataframe(medal_df, hide_index=True)


@st.cache_data(ttl=PERSON_CACHE_TTL, show_spinner=False)
def _pre_comp_pbs(wca_id: str, before_date: str) -> dict[tuple[str, str], int]:
    """Best single/average per event from the competitor's results BEFORE a date.

    Uses their real WCA history (results at earlier competitions), so a PR reflects
    the record at competition time — not the current PB, which may have been beaten
    later. Returns {(event_id, type): best}; empty when this is their first
    competition, so first-time-in-event results are excluded from PRs.
    """
    try:
        results = wca_get(
            f"persons/{wca_id}/results", timeout=PERSON_REQUEST_TIMEOUT, auth=False
        )
        comps = wca_get(
            f"persons/{wca_id}/competitions", timeout=PERSON_REQUEST_TIMEOUT, auth=False
        )
    except requests.RequestException:
        return {}
    date_of = {c["id"]: c["start_date"] for c in comps}
    pbs: dict[tuple[str, str], int] = {}
    for r in results:
        d = date_of.get(r["competition_id"])
        if not d or d >= before_date:  # ISO dates compare lexicographically
            continue
        for typ, val in (("single", r["best"]), ("average", r["average"])):
            if val and val > 0:
                key = (r["event_id"], typ)
                pbs[key] = min(pbs.get(key, val), val)
    return pbs


def _competition_prs(wcif: dict, df: pd.DataFrame) -> pd.DataFrame:
    """Rounds that tied or beat each competitor's pre-competition PB (single/average).

    Counts every round from each competitor's pre-competition PB onward — matching
    the per-round PR badges on WCA Live. First-time-in-event results (no prior PB)
    are excluded. Returns columns name/event_id/type.
    """
    comp_date = wcif["schedule"]["startDate"]
    reg_to_wca = {p["registrantId"]: p.get("wcaId") for p in accepted_persons(wcif)}

    # Per-round results, in round order, melted to (competitor, event, type, result).
    rounds = df.melt(
        id_vars=["registrant_id", "name", "event_id", "round_id"],
        value_vars=["single", "average"],
        var_name="type",
        value_name="result",
    )
    rounds = rounds[rounds["result"] > 0].sort_values(
        ["registrant_id", "event_id", "type", "round_id"]
    )

    wca_ids = {reg_to_wca[r] for r in rounds["registrant_id"].unique() if reg_to_wca.get(r)}
    pbs_by_wca: dict[str, dict] = {}
    with st.spinner("Calculating personal records..."):
        with ThreadPoolExecutor(max_workers=PERSON_FETCH_WORKERS) as ex:
            futures = {ex.submit(_pre_comp_pbs, wid, comp_date): wid for wid in wca_ids}
            for fut in as_completed(futures):
                pbs_by_wca[futures[fut]] = fut.result()

    pr_rows = []
    for (rid, event_id, typ), grp in rounds.groupby(
        ["registrant_id", "event_id", "type"], sort=False
    ):
        wid = reg_to_wca.get(rid)
        if not wid:
            continue  # no WCA ID yet → first competition → not a PR
        best = pbs_by_wca.get(wid, {}).get((event_id, typ))
        if best is None:
            continue  # first time in this event/type → not a PR
        for _, r in grp.iterrows():
            if r["result"] <= best:
                pr_rows.append({"name": r["name"], "event_id": event_id, "type": typ})
                best = r["result"]
    return pd.DataFrame(pr_rows)


def display_personal_records(wcif: dict, df: pd.DataFrame) -> None:
    st.markdown("**Personal records at the competition**")

    df_pr = _competition_prs(wcif, df)
    if df_pr.empty:
        st.info("No personal records set at this competition.")
        return

    pr_counts = df_pr.groupby("name").size().reset_index(name="PRs")

    # PRs by event — bar chart with event icons and tooltips
    pr_by_event = (
        df_pr.groupby("event_id")["name"]
        .nunique()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )
    max_n = pr_by_event["n"].max()

    if len(pr_by_event) <= 8:
        bars = "".join(
            f'<div class="ev-bar-col">'
            f'<div class="ev-bar-count">{row["n"]}</div>'
            f'<div class="ev-bar-fill" style="height:{int(row["n"]/max_n*80)}px"></div>'
            f'{_event_icon(row["event_id"])}</div>'
            for _, row in pr_by_event.iterrows()
        )
        chart_html = f"""
        <style>
          .ev-chart{{display:flex;align-items:flex-end;gap:10px;padding:4px 0;}}
          .ev-bar-col{{display:flex;flex-direction:column;align-items:center;gap:4px;}}
          .ev-bar-count{{font-size:12px;font-weight:600;color:#555;}}
          .ev-bar-fill{{width:28px;background:#4c8bf5;border-radius:4px 4px 0 0;min-height:4px;}}
          {_TOOLTIP_CSS}
        </style>
        <div class="ev-chart">{bars}</div>"""
    else:
        rows_h = "".join(
            f'<div class="ev-row">'
            f'{_event_icon(row["event_id"])}'
            f'<div class="ev-bar-h" style="width:{int(row["n"]/max_n*100)}%"></div>'
            f'<div class="ev-count-h">{row["n"]}</div>'
            f'</div>'
            for _, row in pr_by_event.iterrows()
        )
        chart_html = f"""
        <style>
          .ev-chart-h{{display:flex;flex-direction:column;gap:5px;padding:4px 0;}}
          .ev-row{{display:flex;align-items:center;gap:8px;}}
          .ev-bar-h{{height:18px;background:#4c8bf5;border-radius:0 4px 4px 0;min-width:4px;}}
          .ev-count-h{{font-size:12px;font-weight:600;color:#555;}}
          {_TOOLTIP_CSS}
        </style>
        <div class="ev-chart-h">{rows_h}</div>"""

    col1, col2, col3 = st.columns(3)
    col1.metric("Personal records", df_pr.shape[0])
    col2.metric("Competitors with a PR", len(pr_counts))
    with col3:
        st.html(
            '<p style="font-size:14px;color:rgb(49,51,63);'
            'font-weight:400;margin:0 0 4px;">'
            "PRs by event</p>" + chart_html
        )

    # Table grouped by person: PR count + icons per type (single / average)
    def _icons(events: list) -> str:
        return "".join(_event_icon(e) for e in sorted(events))

    pr_totals = df_pr.groupby("name").size().reset_index(name="PRs")
    single_evs = (
        df_pr[df_pr["type"] == "single"]
        .groupby("name")["event_id"]
        .apply(lambda x: sorted(x))
        .reset_index(name="single_events")
    )
    avg_evs = (
        df_pr[df_pr["type"] == "average"]
        .groupby("name")["event_id"]
        .apply(lambda x: sorted(x))
        .reset_index(name="avg_events")
    )
    persons_prs = (
        pr_totals.merge(single_evs, on="name", how="left")
        .merge(avg_evs, on="name", how="left")
        .sort_values("PRs", ascending=False)
    )
    persons_prs["single_events"] = persons_prs["single_events"].apply(
        lambda x: x if isinstance(x, list) else []
    )
    persons_prs["avg_events"] = persons_prs["avg_events"].apply(
        lambda x: x if isinstance(x, list) else []
    )

    rows_html = [
        f"<tr><td>{row['name']}</td>"
        f"<td style='text-align:center'>{row['PRs']}</td>"
        f"<td>{_icons(row['single_events'])}</td>"
        f"<td>{_icons(row['avg_events'])}</td></tr>"
        for _, row in persons_prs.iterrows()
    ]

    st.html(
        f"""
        <style>
          .pr-tbl {{width:100%;border-collapse:collapse;font-size:13px;}}
          .pr-tbl th {{text-align:left;padding:6px 10px;border-bottom:2px solid #e0e0e0;font-weight:600;color:#555;}}
          .pr-tbl th:nth-child(2) {{text-align:center;}}
          .pr-tbl td {{padding:6px 10px;border-bottom:1px solid #f5f5f5;vertical-align:middle;}}
          .pr-tbl img {{width:22px;height:22px;opacity:0.75;margin:0 2px;}}
          {_TOOLTIP_CSS}
        </style>
        <table class="pr-tbl">
          <tr><th>Name</th><th>PRs</th><th>Single</th><th>Average</th></tr>
          {"".join(rows_html)}
        </table>
        """
    )


def summarize_wcif(wcif: dict) -> None:
    comp_date = datetime.strptime(wcif["schedule"]["startDate"], "%Y-%m-%d")
    persons = accepted_persons(wcif)
    if not persons:
        st.warning("No accepted registrations found.")
        return

    st.subheader(f"Summary of {wcif['name']}")
    st.caption(comp_date.strftime("%B %d, %Y"))

    event_count = len(wcif.get("events", []))
    total_rounds = sum(len(e.get("rounds", [])) for e in wcif.get("events", []))
    col1, col2, col3 = st.columns(3)
    col1.metric("Competitors", len(persons))
    col2.metric("Events", event_count)
    col3.metric("Rounds", total_rounds)

    df = parse_results_from_wcif(wcif, persons)
    if df.empty:
        df = fetch_results_from_api(wcif, wca_get)

    if df.empty:
        st.info("No results available for this competition.")
        return

    display_podiums(df)
    st.divider()
    display_medal_table(df)
    st.divider()
    display_personal_records(wcif, df)


# --- Page ---
st.set_page_config(page_title="Competition Summary", page_icon="📋", layout="wide")
st.title("Competition Summary")

wcif = tool_page("summary", "wcif_summary", upcoming=False)
if wcif:
    summarize_wcif(wcif)
