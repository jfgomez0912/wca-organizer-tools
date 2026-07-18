from __future__ import annotations

import pandas as pd
import requests


ROUND_ORDER = {"1": 1, "2": 2, "3": 3, "b": 10, "c": 10, "d": 10, "e": 10, "f": 10}
ROUND_TYPE_LABEL = {
    "1": "R1",
    "2": "R2",
    "3": "R3",
    "c": "R1",
    "d": "R2",
    "e": "R3",
    "b": "SF",
    "f": "Final",
    "g": "Final",
}


def parse_results_from_wcif(wcif: dict, accepted_people: list[dict]) -> pd.DataFrame:
    """Parse all results from WCIF into a flat DataFrame."""
    reg_to_name = {p["registrantId"]: p["name"] for p in accepted_people}
    records = []
    for event in wcif.get("events", []):
        event_id = event["id"]
        for rnd in event.get("rounds", []):
            round_id = rnd["id"]
            for result in rnd.get("results", []):
                if result.get("ranking", 0) <= 0:
                    continue
                records.append(
                    {
                        "registrant_id": result["personId"],
                        "name": reg_to_name.get(result["personId"], ""),
                        "event_id": event_id,
                        "round_id": round_id,
                        "single": result.get("best", 0),
                        "average": result.get("average", 0),
                        "ranking": result["ranking"],
                    }
                )
    return pd.DataFrame(records) if records else pd.DataFrame()


def fetch_results_from_api(
    wcif: dict,
    wca_get_fn,
) -> pd.DataFrame:
    """Fallback for competitions where results are not embedded in the WCIF."""
    comp_id = wcif.get("id", "")
    wca_id_to_reg = {
        p["wcaId"]: p["registrantId"] for p in wcif.get("persons", []) if p.get("wcaId")
    }
    name_to_reg = {
        p["name"]: p["registrantId"] for p in wcif.get("persons", []) if not p.get("wcaId")
    }
    try:
        results = wca_get_fn(f"competitions/{comp_id}/results", auth=False)
    except requests.HTTPError:
        return pd.DataFrame()

    records = []
    for r in results:
        wca_id = r.get("wca_id") or ""
        name = r.get("name", "")
        reg_id = wca_id_to_reg.get(wca_id) or name_to_reg.get(name)
        if reg_id is None:
            continue
        round_num = ROUND_ORDER.get(r.get("round_type_id", "1"), 1)
        event_id = r.get("event_id", "")
        records.append(
            {
                "registrant_id": reg_id,
                "name": name,
                "event_id": event_id,
                "round_id": f"{event_id}-r{round_num:02d}",
                "single": r.get("best") or 0,
                "average": r.get("average") or 0,
                "ranking": r.get("pos") or 0,
            }
        )
    return pd.DataFrame(records) if records else pd.DataFrame()
