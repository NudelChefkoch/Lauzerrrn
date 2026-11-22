"""AI Financial Twin – entry point.   Run:  uv run streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="YOUR LIFE · YOUR CHOICE", page_icon="🎮", layout="wide")

# every button and chip fully rounded (theme sets buttonRadius = "full"; this covers the rest)
st.markdown("""<style>
button, [data-testid^="stBaseButton"], [data-baseweb="tag"] { border-radius: 999px !important; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 20px !important; }
</style>""", unsafe_allow_html=True)

# the game page is the whole app; the analysis page is reached from inside the game (and links back)
pg = st.navigation([
    st.Page("ui/spiel.py", title="Game", icon="🎮", default=True),
    st.Page("ui/analyse.py", title="Analysis", icon="📊"),
], position="hidden")
pg.run()
