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
home = st.Page("pages/1_home.py", title="Inicio")
analysis = st.Page(
    "pages/2_competition_analysis.py", title="Competition Analysis", icon="🔍"
)
summary = st.Page(
    "pages/3_competition_summary.py", title="Competition Summary", icon="📋"
)

# Set up navigation
pg = st.navigation([home, analysis, summary])

# After OAuth/logout, Streamlit starts a fresh session. Redirect to the page the
# user was on (stored in a JS cookie) on their first script run of the new session.
# Only redirects when the cookie has a valid value — no default — so anonymous
# first-time visitors land on the home page normally.
if not st.session_state.get("_navigated"):
    st.session_state["_navigated"] = True
    target = st.context.cookies.get("wca_next")
    if target == "summary":
        st.switch_page(summary)
    elif target == "analysis":
        st.switch_page(analysis)

pg.run()
