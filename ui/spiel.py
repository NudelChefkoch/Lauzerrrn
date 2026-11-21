"""Spiel-Modus "YOUR LIFE · YOUR CHOICE": das ganze Spiel läuft in EINER Vollbild-Komponente.

Python ist nur das Simulations-Backend (``twin.session.GameSession``): die Komponente schickt Aktionen
(start / choose / restart / analyse, jeweils mit ``nonce``), wir wenden sie an und schicken den neuen Payload.
"""
from __future__ import annotations

import streamlit as st

from twin.session import GameSession
from twin.three_d import game

# hide every piece of Streamlit chrome; the component iframe fills the whole viewport
st.markdown("""<style>
header, [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarNav"], footer, #MainMenu { display: none !important; }
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  overflow: hidden !important; margin: 0 !important; padding: 0 !important; }
.block-container, [data-testid="stMainBlockContainer"], [data-testid="block-container"] {
  padding: 0 !important; margin: 0 !important; max-width: none !important; }
[data-testid="stVerticalBlock"] { gap: 0 !important; }
[data-testid="stElementContainer"]:has(style) { display: none !important; }
iframe[title="twin.three_d.twin3d"], [data-testid="stCustomComponentV1"] {
  position: fixed !important; inset: 0 !important; width: 100% !important; height: 100vh !important;
  border: none !important; display: block; z-index: 10; }
</style>""", unsafe_allow_html=True)

ss = st.session_state
if not isinstance(ss.get("game_session"), GameSession):
    ss.game_session = GameSession()
sess: GameSession = ss.game_session

value = game(sess.payload(), key="game")
if sess.is_new(value):
    if sess.handle(value) == "analyse":
        st.switch_page("ui/analyse.py")
    st.rerun()
