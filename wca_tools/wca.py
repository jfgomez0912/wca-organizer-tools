import math
from datetime import datetime, timedelta

import requests
import streamlit as st

from .config import (
    ANALYSIS_LOOKBACK_DAYS,
    COUNTRIES_CACHE_TTL,
    COUNTRIES_REQUEST_TIMEOUT,
    DEFAULT_REQUEST_TIMEOUT,
    LOOKBACK_DAYS,
    PER_PAGE,
    WCA_API,
)

_DEFAULT_AVATAR = (
    "https://assets.worldcubeassociation.org/assets/e874e91/assets/"
    "missing_avatar_thumb-d77f478a307a91a9d4a083ad197012a391d5410f6dd26cb0b0e3118a5de71438.png"
)
_SESSION_EXPIRED_KEY = "_session_expired"


def session_expired() -> bool:
    """Whether the logged-in WCA session's access token has expired.

    Flagged on a 401 from an authenticated request, or when the token's
    ``expires_at`` has passed. False when not logged in (no session to expire).
    """
    if not st.user.is_logged_in:
        return False
    if st.session_state.get(_SESSION_EXPIRED_KEY):
        return True
    expires_at = st.user.tokens.get("expires_at")
    if expires_at and datetime.now().timestamp() >= expires_at:
        st.session_state[_SESSION_EXPIRED_KEY] = True
        return True
    return False


def authenticated() -> bool:
    """Logged in with a still-valid token — gate for authenticated requests and UI."""
    return st.user.is_logged_in and not session_expired()


def wca_get(
    path: str,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
    auth: bool = True,
    raw_response: bool = False,
) -> requests.Response | dict | list:
    use_auth = auth and authenticated()
    headers = (
        {"Authorization": f"Bearer {st.user.tokens['access']}"} if use_auth else {}
    )
    resp = requests.get(f"{WCA_API}/{path}", headers=headers, timeout=timeout)
    if use_auth and resp.status_code == 401:
        # Token rejected — flag the session expired and rerun so the header shows the
        # signed-out state (public tools keep working) instead of blocking the page.
        st.session_state[_SESSION_EXPIRED_KEY] = True
        st.rerun()
    resp.raise_for_status()
    if raw_response:
        return resp
    return resp.json()


@st.cache_data(ttl=COUNTRIES_CACHE_TTL)
def fetch_countries() -> dict[str, str]:
    """Returns {country_name: iso2} sorted by name, cached for 24 h."""
    try:
        resp = requests.get(f"{WCA_API}/countries", timeout=COUNTRIES_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return {
            c["name"]: c["iso2"]
            for c in sorted(resp.json(), key=lambda x: x["name"])
            if c.get("iso2")
        }
    except requests.RequestException:
        return {}


def accepted_persons(wcif: dict) -> list[dict]:
    """Return only accepted registrants from a WCIF dict."""
    return [
        p
        for p in wcif.get("persons", [])
        if (p.get("registration") or {}).get("status") == "accepted"
    ]


def _fetch_wcif(comp_id: str) -> tuple[dict | None, bool]:
    """Try private WCIF (if logged in), fall back to public. Returns (wcif, is_private)."""
    if authenticated():
        try:
            return wca_get(f"competitions/{comp_id}/wcif", timeout=60), True
        except requests.HTTPError:
            pass
    try:
        return (
            wca_get(f"competitions/{comp_id}/wcif/public", timeout=60, auth=False),
            False,
        )
    except requests.HTTPError as e:
        st.error(f"Competition not found: {e}")
        return None, False


def _store_wcif(comp_id: str, wcif_key: str) -> None:
    """Fetch a WCIF by ID and store it (plus privacy flag) in session state."""
    with st.spinner("Loading WCIF..."):
        wcif, wcif_private = _fetch_wcif(comp_id)
        if wcif is not None:
            st.session_state[wcif_key] = wcif
            st.session_state[f"{wcif_key}_private"] = wcif_private
            # Reflect the loaded competition in the URL for shareable deep links
            # (e.g. ?comp=UnicentroArmeniaV2026). Only write when it changed to
            # avoid an extra rerun.
            if st.query_params.get("comp") != comp_id:
                st.query_params["comp"] = comp_id


def load_competition_from_query(wcif_key: str) -> None:
    """Load the WCIF named by the ``?comp=<id>`` query param, if any.

    Enables shareable deep links like ``/name_badges?comp=UnicentroArmeniaV2026``.
    Runs once per competition: it no-ops when that WCIF is already loaded, so it
    won't refetch on every rerun. Organizer vs. public access is handled by
    ``_fetch_wcif`` (authenticated WCIF first, public WCIF as fallback).
    """
    comp_id = st.query_params.get("comp")
    if not comp_id:
        return
    current = st.session_state.get(wcif_key)
    if isinstance(current, dict) and current.get("id") == comp_id:
        return  # already loaded — nothing to do
    # Only attempt each id once per session so a broken link doesn't refetch on
    # every rerun. A fresh session (e.g. after login) resets this and retries.
    tried_key = f"{wcif_key}_query_comp"
    if st.session_state.get(tried_key) == comp_id:
        return
    st.session_state[tried_key] = comp_id
    _store_wcif(comp_id, wcif_key)


def tool_page(page: str, wcif_key: str, *, upcoming: bool) -> dict | None:
    """Render the shared tool-page scaffold (header + competition selector).

    Loads a competition from the ``?comp=`` deep link or the selector and returns
    its WCIF, or None if none is selected yet.
    """
    render_header(page=page)
    st.divider()
    load_competition_from_query(wcif_key)
    render_competition_selector(wcif_key, upcoming=upcoming)
    return st.session_state.get(wcif_key)


def render_header(page: str = "analysis") -> None:
    """Render the profile bar (logged in) or login prompt (not logged in)."""
    # Set a persistent cookie so main.py can redirect to the correct page after OAuth.
    # st.context.cookies reads from the initial WebSocket request, so this cookie
    # set here (via JS) will be visible in the NEW session that starts after OAuth.
    st.html(
        f"<script>"
        f"var s=location.protocol==='https:'?';Secure':'';"
        f"document.cookie='wca_next={page};path=/;max-age=3600;SameSite=Lax'+s;"
        f"</script>",
        unsafe_allow_javascript=True,
    )
    if authenticated():
        avatar = st.user.get("picture") or _DEFAULT_AVATAR
        col1, col2 = st.columns([0.92, 0.08])
        with col1:
            st.markdown(
                f"""
                <div style="display:flex; align-items:center; gap:12px; padding:8px 16px;
                            background:#f0f2f6; border-radius:10px;">
                    <img src="{avatar}" style="width:48px; height:48px; border-radius:50%;
                         object-fit:cover; border:2px solid #ddd;" />
                    <div>
                        <div style="font-size:15px; font-weight:600;">{st.user.name}</div>
                        <div style="font-size:13px; color:#666;">{st.user.email}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
            st.button("Sign out", on_click=st.logout, type="primary")
    else:
        if session_expired():
            st.warning("Your session has expired. Please sign in again.")
        else:
            st.info(
                "Sign in with your WCA account to access your managed competitions "
                "and the full analysis. Search by country and by ID is available without signing in."
            )
        st.button("Sign in with WCA", on_click=st.login, args=["wca"])


def _search_country_competitions(country_code: str, upcoming: bool) -> list[dict]:
    """Competitions for a country: an upcoming window, or the most recent PER_PAGE past ones."""
    if upcoming:
        start = (datetime.today() - timedelta(days=ANALYSIS_LOOKBACK_DAYS)).strftime(
            "%Y-%m-%d"
        )
        base = f"competitions?country_iso2={country_code}&start={start}&sort=start_date"
        return wca_get(f"{base}&per_page={PER_PAGE}", auth=False)

    one_year_ago = (datetime.today() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    base = (
        f"competitions?country_iso2={country_code}"
        f"&start={one_year_ago}&end={yesterday}&sort=start_date"
    )
    # Results are paginated ascending, so walk back from the last page to collect the
    # most recent PER_PAGE competitions.
    probe = wca_get(f"{base}&per_page=1", auth=False, raw_response=True)
    probe.raise_for_status()
    total = int(probe.headers.get("total", 0))
    if total == 0:
        return []
    comps: list[dict] = []
    page = math.ceil(total / PER_PAGE)
    while len(comps) < PER_PAGE and page >= 1:
        comps = wca_get(f"{base}&per_page={PER_PAGE}&page={page}", auth=False) + comps
        page -= 1
    return sorted(comps, key=lambda c: c["start_date"], reverse=True)


def render_competition_selector(wcif_key: str, upcoming: bool = True) -> None:
    """Render competition selection tabs and populate st.session_state[wcif_key].

    Args:
        wcif_key: Session state key to store the loaded WCIF (e.g. 'wcif_analysis').
        upcoming: True to show upcoming competitions, False to show past ones.
    """
    today = datetime.today().strftime("%Y-%m-%d")
    country_key = f"{wcif_key}_country_comps"

    competitions = []
    if authenticated():
        try:
            data = wca_get("competitions/mine")
            competitions = (
                [c for v in data.values() if isinstance(v, list) for c in v]
                if isinstance(data, dict)
                else data
            )
            if upcoming:
                lookback = (
                    datetime.today() - timedelta(days=ANALYSIS_LOOKBACK_DAYS)
                ).strftime("%Y-%m-%d")
                competitions = [c for c in competitions if c["start_date"] >= lookback]
                competitions.sort(key=lambda c: c["start_date"])
            else:
                competitions = [c for c in competitions if c["start_date"] < today]
                competitions.sort(key=lambda c: c["start_date"], reverse=True)
        except requests.HTTPError:
            competitions = []

    st.subheader("Competitions")

    if authenticated():
        tab_mine, tab_country, tab_search = st.tabs(
            ["My competitions", "Search by country", "Search by ID"]
        )
    else:
        tab_country, tab_search = st.tabs(["Search by country", "Search by ID"])

    if authenticated():
        with tab_mine:
            if competitions:
                options = {
                    f"{c.get('name', c['id'])} ({c['start_date']})": c["id"]
                    for c in competitions
                }
                with st.form("form_mine"):
                    selected = st.selectbox("Select competition", options.keys())
                    if st.form_submit_button("Analyze"):
                        _store_wcif(options[selected], wcif_key)
            else:
                st.info(
                    "No managed competitions found. "
                    "Use **Search by country** or **Search by ID**."
                )

    with tab_country:
        countries = fetch_countries()
        default_idx = (
            list(countries.keys()).index("Colombia") if "Colombia" in countries else 0
        )
        with st.form("form_country"):
            country_name = st.selectbox(
                "Country", list(countries.keys()), index=default_idx
            )
            if st.form_submit_button("Search competitions"):
                with st.spinner("Searching competitions..."):
                    try:
                        st.session_state[country_key] = _search_country_competitions(
                            countries[country_name], upcoming
                        )
                    except requests.HTTPError as e:
                        st.error(f"Error searching competitions: {e}")
                        st.session_state.pop(country_key, None)

        if st.session_state.get(country_key):
            country_options = {
                f"{c.get('name', c['id'])} ({c['start_date']})": c["id"]
                for c in st.session_state[country_key]
            }
            with st.form("form_country_analyze"):
                selected_cc = st.selectbox(
                    "Select competition", country_options.keys()
                )
                if st.form_submit_button("Analyze"):
                    _store_wcif(country_options[selected_cc], wcif_key)
        elif country_key in st.session_state:
            st.info("No competitions found for this country.")

    with tab_search:
        with st.form("form_search"):
            comp_id_input = st.text_input(
                "Competition ID", placeholder="e.g. UnicentroPereira2023"
            )
            if st.form_submit_button("Analyze") and comp_id_input:
                _store_wcif(comp_id_input, wcif_key)
