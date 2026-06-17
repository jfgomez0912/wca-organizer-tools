import streamlit as st

import wca

st.set_page_config(page_title="WCA Organizer Tools", page_icon="🛠️", layout="wide")

wca.render_header()

st.title("🛠️ WCA Organizer Tools")
st.markdown("""
Herramientas para **organizadores y delegados** de competencias WCA: análisis de
inscritos, hitos y metas antes/durante la competencia, y resúmenes de resultados
(podios, medallas, PRs) una vez finalizada.

Los datos se obtienen en tiempo real desde la **API de la WCA** y el **WCIF**. Si
inicias sesión con tu cuenta WCA y eres organizador/delegado del torneo, también
puedes cargar el **WCIF privado** de competencias aún no publicadas.
""")

st.markdown("---")

col1, col2 = st.columns(2)
with col1:
    st.subheader("🔍 Competition Analysis")
    st.markdown(
        "Analiza una competencia próxima o en curso: novatos, mujeres, hitos de "
        "participación y metas de 3x3."
    )
with col2:
    st.subheader("📋 Competition Summary")
    st.markdown(
        "Resume una competencia finalizada: podios, medallas y récords personales. "
        "Exporta el resumen para compartirlo o publicarlo."
    )
