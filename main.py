import streamlit as st

# WCA's id_token omits the 'nonce' claim, which Authlib's OIDC validation requires.
# Patch nonce validation to make st.login() work with WCA's OAuth provider.
from authlib.oidc.core.claims import IDToken

_original_validate_nonce = IDToken.validate_nonce


def _lenient_validate_nonce(self):
    try:
        _original_validate_nonce(self)
    except Exception as exc:
        # WCA omits nonce in id_token; only ignore that known case.
        if "nonce" not in str(exc).lower():
            raise


IDToken.validate_nonce = _lenient_validate_nonce

# Define the pages
home = st.Page("pages/home.py", title="Home", icon="🏠")
analysis = st.Page(
    "pages/competition_analysis.py", title="Competition Analysis", icon="🔍"
)
summary = st.Page(
    "pages/competition_summary.py", title="Competition Summary", icon="📋"
)
name_badges = st.Page("pages/name_badges.py", title="Name Badges", icon="🏷️")

# Set up navigation
pg = st.navigation([home, analysis, summary, name_badges])

# After OAuth/logout, Streamlit starts a fresh session and lands on the default
# (home) page. Redirect to the page the user was on (stored in a JS cookie) on the
# first script run of the new session. Only redirect while on the default page, so
# direct deep links like /competition_analysis?comp=... are not hijacked (a
# switch_page would drop their query params).
if not st.session_state.get("_navigated"):
    st.session_state["_navigated"] = True
    if pg.url_path == "":  # on the default/home page
        target = st.context.cookies.get("wca_next")
        if target == "summary":
            st.switch_page(summary)
        elif target == "analysis":
            st.switch_page(analysis)
        elif target == "name_badges":
            st.switch_page(name_badges)

pg.run()
