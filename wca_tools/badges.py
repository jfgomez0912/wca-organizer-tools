"""Build name-badge data and person QR codes from a WCIF.

Pure helpers (no Streamlit): the page layer supplies the WCIF persons, the
list of competition events and the CompetitionGroups base URL, and gets back a
DataFrame ready to export as TSV plus PNG bytes for each person's QR.
"""

from __future__ import annotations

import io

import pandas as pd
import qrcode
from qrcode.constants import ERROR_CORRECT_M

from .formatting import fmt_result

# Events ranked by single only — no average personal best to show.
NO_AVERAGE_EVENTS = {"333bf", "444bf", "555bf", "333mbf"}

# Lowercase connectors that glue to their neighbours to form a single surname
# unit (e.g. "López de Juan", "Pérez y García", "Van der Berg").
NAME_PARTICLES = {
    "de", "del", "la", "las", "los", "y", "e", "i", "san", "santa",
    "da", "das", "do", "dos", "van", "von", "der", "den", "di", "du",
    "le", "mac", "mc", "della", "dello", "st", "st.",
}


def _split_units(name: str) -> list[str]:
    """Split a full name into tokens, gluing particles forward into one unit.

    A particle starts a surname unit and absorbs the following token(s), so a
    given name that precedes it stays separate:
    "María Fernanda de la Cruz" -> ["María", "Fernanda", "de la Cruz"].
    """
    units: list[str] = []
    attach_next = False
    for tok in name.split():
        is_particle = tok.lower() in NAME_PARTICLES
        if units and attach_next:
            units[-1] = f"{units[-1]} {tok}"
            attach_next = is_particle
        elif is_particle:
            units.append(tok)
            attach_next = True
        else:
            units.append(tok)
            attach_next = False
    return units


def short_name(full_name: str, max_chars: int) -> str:
    """Shorten a full name to fit `max_chars`, degrading gracefully.

    Keeps the full name if it fits; otherwise drops trailing surnames, then
    extra given names (down to one given + one surname), then the surname, and
    only truncates the first given name as a last resort. Surnames and given
    names are split with the hispanic convention (last two units are surnames,
    always leaving at least one given name), with particles kept together.
    """
    name = " ".join(full_name.split())
    if len(name) <= max_chars:
        return name

    units = _split_units(name)
    if len(units) <= 1:
        return name[:max_chars].rstrip()

    n_sur = min(2, len(units) - 1)
    given, sur = units[: len(units) - n_sur], units[len(units) - n_sur :]

    candidates: list[list[str]] = []
    # Drop trailing surnames, keeping every given name + the first surname(s).
    for k in range(len(sur) - 1, 0, -1):
        candidates.append(given + sur[:k])
    candidates.append([given[0], sur[0]])  # one given + one surname
    candidates.append([given[0]])  # first given name only

    for parts in candidates:
        candidate = " ".join(parts)
        if len(candidate) <= max_chars:
            return candidate

    return given[0][:max_chars].rstrip()


def person_qr_url(comp_url: str, registrant_id) -> str:
    """CompetitionGroups person page URL for a registrant."""
    return f"{comp_url.rstrip('/')}/persons/{registrant_id}"


def qr_filename(registrant_id) -> str:
    """Stable PNG filename for a person's QR (matches the ZIP entry name)."""
    return f"person_{registrant_id}.png"


def qr_png_bytes(url: str, module_rgb: tuple[int, int, int] = (0, 0, 0)) -> bytes:
    """Render `url` as a QR PNG with colored modules on a transparent background.

    Transparent background so the code prints cleanly on any badge stock; pick
    black modules for light badges or white modules for dark ones.
    """
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=12, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
    r_, g_, b_ = module_rgb
    img.putdata(
        [
            (r_, g_, b_, 255) if (r, g, b) == (0, 0, 0) else (255, 255, 255, 0)
            for r, g, b, _a in img.getdata()
        ]
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_badge_df(
    persons: list[dict],
    event_ids: list[str],
    comp_url: str,
    country_names: dict[str, str] | None = None,
    short_max: int = 20,
) -> pd.DataFrame:
    """Build the badge table: identity, country, per-event PBs and QR filename.

    Personal bests come from the WCIF `personalBests` array (a snapshot taken
    when the WCIF was generated), filtered to the competition's events. Single
    and average are shown; average is omitted for single-only events. A
    ``short_name`` column holds each name shortened to ``short_max`` characters.
    Columns use short snake_case names; per-event columns are keyed by event id
    (e.g. ``333_single``, ``333_avg``).
    """
    country_names = country_names or {}
    avg_events = [e for e in event_ids if e not in NO_AVERAGE_EVENTS]

    rows = []
    for p in persons:
        rid = p.get("registrantId")
        iso2 = p.get("countryIso2", "")
        name = p.get("name", "")
        pbs = {
            (pb["eventId"], pb["type"]): pb["best"]
            for pb in p.get("personalBests", [])
        }
        row = {
            "registrant_id": rid,
            "wca_id": p.get("wcaId") or "",
            "name": name,
            "short_name": short_name(name, short_max),
            "country": country_names.get(iso2, iso2),
        }
        for ev in event_ids:
            row[f"{ev}_single"] = fmt_result(pbs.get((ev, "single")), ev, blank="")
            if ev in avg_events:
                row[f"{ev}_avg"] = fmt_result(pbs.get((ev, "average")), ev, blank="")
        row["qr_file"] = qr_filename(rid)
        row["_qr_url"] = person_qr_url(comp_url, rid)
        rows.append(row)

    df = pd.DataFrame(rows)
    return df.sort_values("name").reset_index(drop=True) if not df.empty else df
