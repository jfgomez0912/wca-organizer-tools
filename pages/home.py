import streamlit as st

from wca_tools import wca

st.set_page_config(page_title="WCA Organizer Tools", page_icon="🛠️", layout="wide")

wca.render_header()

st.title("🛠️ WCA Organizer Tools")
st.markdown("""
Tools for WCA competition **organizers and delegates**: analysis of
registrants, milestones and goals before/during the competition, and results
summaries (podiums, medals, PRs) once it has finished.

Data is fetched live from the **WCA API** and the **WCIF**. If you sign in with
your WCA account and are an organizer/delegate of the competition, you can also
load the **private WCIF** of competitions that haven't been published yet.
""")

st.markdown("---")

col1, col2 = st.columns(2)
with col1:
    st.subheader("🔍 Competition Analysis")
    st.markdown(
        "Analyze an upcoming or ongoing competition: newcomers, women, "
        "participation milestones and 3x3 goals."
    )
with col2:
    st.subheader("📋 Competition Summary")
    st.markdown(
        "Summarize a finished competition: podiums, medals and personal records. "
        "Export the summary to share or publish it."
    )
