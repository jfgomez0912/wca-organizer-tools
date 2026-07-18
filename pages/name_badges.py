import io
import zipfile

import streamlit as st

from wca_tools.badges import build_badge_df, qr_png_bytes
from wca_tools.wca import accepted_persons, fetch_countries, tool_page

COMPETITION_GROUPS_URL = "https://www.competitiongroups.com/competitions"

MODULE_COLORS = {
    "Black (for light badges)": (0, 0, 0),
    "White (for dark badges)": (255, 255, 255),
}

# label -> (delimiter, mime type, file extension)
FILE_FORMATS = {
    "TSV": ("\t", "text/tab-separated-values", "tsv"),
    "CSV": (",", "text/csv", "csv"),
}

# label -> Python codec. utf-16 writes a little-endian BOM (InDesign reads it as
# "Unicode"); utf-8-sig adds a BOM so Excel opens accents correctly.
ENCODINGS = {
    "UTF-16 LE (InDesign)": "utf-16",
    "UTF-8 with BOM (Excel)": "utf-8-sig",
    "UTF-8": "utf-8",
}


def _country_names() -> dict[str, str]:
    """{iso2: country_name} from the cached WCA country list."""
    return {iso2: name for name, iso2 in fetch_countries().items()}


def _build_zip(df, module_rgb) -> bytes:
    """One transparent QR PNG per registrant, packed into an in-memory ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for _, row in df.iterrows():
            png = qr_png_bytes(row["_qr_url"], module_rgb)
            zf.writestr(row["qr_file"], png)
    return buf.getvalue()


def generate_badges(wcif: dict) -> None:
    persons = accepted_persons(wcif)
    if not persons:
        st.warning("No accepted registrations found for this competition.")
        return

    event_ids = [e["id"] for e in wcif.get("events", [])]

    st.subheader(f"Name badges for {wcif.get('name', wcif.get('id', ''))}")
    st.caption(
        "Personal bests (single and average) come from the WCIF, filtered to this "
        "competition's events. They are a snapshot taken when the WCIF was generated, "
        "not necessarily the current PBs."
    )

    comp_url = f"{COMPETITION_GROUPS_URL}/{wcif.get('id', '')}"
    color_label = st.radio(
        "QR module color",
        list(MODULE_COLORS.keys()),
        horizontal=True,
        help="The background is always transparent so it prints on any badge stock.",
    )
    module_rgb = MODULE_COLORS[color_label]

    short_max = st.number_input(
        "Max characters for the short name",
        min_value=1,
        max_value=60,
        value=20,
        step=1,
        help=(
            "If the full name does not fit, surnames and then given names are "
            "trimmed until it fits (keeping at least one given name + one surname)."
        ),
    )

    df = build_badge_df(persons, event_ids, comp_url, _country_names(), int(short_max))

    # Hide the internal URL column from the preview and the exported file.
    display_df = df.drop(columns=["_qr_url"])

    st.markdown(f"**Preview** ({len(display_df)} competitors)")
    st.dataframe(display_df, hide_index=True)

    col_fmt, col_enc = st.columns(2)
    fmt = col_fmt.radio("Format", list(FILE_FORMATS), horizontal=True)
    enc_label = col_enc.selectbox(
        "Encoding",
        list(ENCODINGS),
        help=(
            "UTF-16 LE (BOM) is the most reliable for Adobe InDesign data merge; "
            "UTF-8 with BOM opens accents correctly in Excel; plain UTF-8 otherwise."
        ),
    )
    sep, mime, ext = FILE_FORMATS[fmt]
    text = display_df.to_csv(sep=sep, index=False)
    st.download_button(
        f"⬇️ Download badges {fmt}",
        data=text.encode(ENCODINGS[enc_label]),
        file_name=f"{wcif.get('id', 'competition')}_badges.{ext}",
        mime=mime,
    )

    st.divider()
    st.markdown("**QR codes**")
    if st.button("Generate QR ZIP"):
        with st.spinner("Generating QR codes..."):
            st.session_state["badges_zip"] = _build_zip(df, module_rgb)

    if "badges_zip" in st.session_state:
        st.download_button(
            "⬇️ Download QR ZIP (PNG)",
            data=st.session_state["badges_zip"],
            file_name=f"{wcif.get('id', 'competition')}_qr.zip",
            mime="application/zip",
        )


# --- Page ---
st.set_page_config(page_title="Name Badges", page_icon="🏷️", layout="wide")
st.title("Name Badges & QR Codes")

wcif = tool_page("name_badges", "wcif_name_badges", upcoming=True)
if wcif:
    generate_badges(wcif)
