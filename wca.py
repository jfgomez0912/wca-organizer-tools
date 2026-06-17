import math
from datetime import datetime, timedelta

import requests
import streamlit as st

from config import (
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
AUTH_SESSION_KEYS = ("user", "tokens")


def clear_auth_session_state() -> None:
    """Clear only auth-related keys instead of wiping all page state."""
    for key in AUTH_SESSION_KEYS:
        st.session_state.pop(key, None)


def wca_get(
    path: str,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
    auth: bool = True,
    raw_response: bool = False,
) -> requests.Response | dict | list:
    use_auth = auth and st.user.is_logged_in
    headers = (
        {"Authorization": f"Bearer {st.user.tokens['access']}"} if use_auth else {}
    )
    resp = requests.get(f"{WCA_API}/{path}", headers=headers, timeout=timeout)
    if use_auth and resp.status_code == 401:
        clear_auth_session_state()
        st.error("Tu sesión ha expirado. Por favor inicia sesión de nuevo.")
        st.button("Iniciar sesión con WCA", on_click=st.login, args=["wca"])
        st.stop()
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
    if st.user.is_logged_in:
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
        st.error(f"Competencia no encontrada: {e}")
        return None, False


def _store_wcif(comp_id: str, wcif_key: str) -> None:
    """Fetch a WCIF by ID and store it (plus privacy flag) in session state."""
    with st.spinner("Cargando WCIF..."):
        wcif, wcif_private = _fetch_wcif(comp_id)
        if wcif is not None:
            st.session_state[wcif_key] = wcif
            st.session_state[f"{wcif_key}_private"] = wcif_private


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
    if st.user.is_logged_in:
        expires_at = st.user.tokens.get("expires_at")
        if expires_at and datetime.now().timestamp() >= expires_at:
            clear_auth_session_state()
            st.warning("Tu sesión ha expirado. Por favor inicia sesión de nuevo.")
            st.button("Iniciar sesión con WCA", on_click=st.login, args=["wca"])
            st.stop()

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
            st.button("Cerrar sesión", on_click=st.logout, type="primary")
    else:
        st.info(
            "Inicia sesión con tu cuenta WCA para acceder a tus competencias administradas "
            "y el análisis completo. La búsqueda por país y por ID está disponible sin iniciar sesión."
        )
        st.button("Iniciar sesión con WCA", on_click=st.login, args=["wca"])


def render_competition_selector(wcif_key: str, upcoming: bool = True) -> None:
    """Render competition selection tabs and populate st.session_state[wcif_key].

    Args:
        wcif_key: Session state key to store the loaded WCIF (e.g. 'wcif_analysis').
        upcoming: True to show upcoming competitions, False to show past ones.
    """
    today = datetime.today().strftime("%Y-%m-%d")
    country_key = f"{wcif_key}_country_comps"

    competitions = []
    if st.user.is_logged_in:
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

    st.subheader("Competencias")

    if st.user.is_logged_in:
        tab_mine, tab_country, tab_search = st.tabs(
            ["Mis competencias", "Buscar por país", "Buscar por ID"]
        )
    else:
        tab_country, tab_search = st.tabs(["Buscar por país", "Buscar por ID"])

    if st.user.is_logged_in:
        with tab_mine:
            if competitions:
                options = {
                    f"{c.get('name', c['id'])} ({c['start_date']})": c["id"]
                    for c in competitions
                }
                with st.form("form_mine"):
                    selected = st.selectbox("Seleccionar competencia", options.keys())
                    if st.form_submit_button("Analizar"):
                        _store_wcif(options[selected], wcif_key)
            else:
                st.info(
                    "No se encontraron competencias administradas. "
                    "Usa **Buscar por país** o **Buscar por ID**."
                )

    with tab_country:
        countries = fetch_countries()
        default_idx = (
            list(countries.keys()).index("Colombia") if "Colombia" in countries else 0
        )
        with st.form("form_country"):
            country_name = st.selectbox(
                "País", list(countries.keys()), index=default_idx
            )
            if st.form_submit_button("Buscar competencias"):
                country_code = countries[country_name]
                with st.spinner("Buscando competencias..."):
                    try:
                        if upcoming:
                            lookback_date = (
                                datetime.today()
                                - timedelta(days=ANALYSIS_LOOKBACK_DAYS)
                            ).strftime("%Y-%m-%d")
                            params = f"&start={lookback_date}"
                        else:
                            one_year_ago = (
                                datetime.today() - timedelta(days=LOOKBACK_DAYS)
                            ).strftime("%Y-%m-%d")
                            yesterday = (datetime.today() - timedelta(days=1)).strftime(
                                "%Y-%m-%d"
                            )
                            params = f"&start={one_year_ago}&end={yesterday}"
                        base_url = (
                            f"competitions?country_iso2={country_code}{params}"
                            f"&sort=start_date"
                        )
                        if upcoming:
                            st.session_state[country_key] = wca_get(
                                f"{base_url}&per_page={PER_PAGE}", auth=False
                            )
                        else:
                            # Fetch the most recent PER_PAGE competitions by paginating backwards
                            probe = wca_get(
                                f"{base_url}&per_page=1",
                                auth=False,
                                raw_response=True,
                            )
                            probe.raise_for_status()
                            total = int(probe.headers.get("total", 0))
                            if total == 0:
                                st.session_state[country_key] = []
                            else:
                                last_page = math.ceil(total / PER_PAGE)
                                comps: list[dict] = []
                                page = last_page
                                while len(comps) < PER_PAGE and page >= 1:
                                    batch = wca_get(
                                        f"{base_url}&per_page={PER_PAGE}&page={page}",
                                        auth=False,
                                    )
                                    comps = batch + comps
                                    page -= 1
                                st.session_state[country_key] = sorted(
                                    comps,
                                    key=lambda c: c["start_date"],
                                    reverse=True,
                                )
                    except requests.HTTPError as e:
                        st.error(f"Error al buscar competencias: {e}")
                        st.session_state.pop(country_key, None)

        if st.session_state.get(country_key):
            country_options = {
                f"{c.get('name', c['id'])} ({c['start_date']})": c["id"]
                for c in st.session_state[country_key]
            }
            with st.form("form_country_analyze"):
                selected_cc = st.selectbox(
                    "Seleccionar competencia", country_options.keys()
                )
                if st.form_submit_button("Analizar"):
                    _store_wcif(country_options[selected_cc], wcif_key)
        elif country_key in st.session_state:
            st.info("No se encontraron competencias para este país.")

    with tab_search:
        with st.form("form_search"):
            comp_id_input = st.text_input(
                "ID de competencia", placeholder="ej. UnicentroPereira2023"
            )
            if st.form_submit_button("Analizar") and comp_id_input:
                _store_wcif(comp_id_input, wcif_key)
