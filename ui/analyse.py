"""Analyse-Modus: Dashboard mit allen Reglern."""
from __future__ import annotations

from dataclasses import asdict, replace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from twin.analysis import tornado
from twin.calibration import calibrate
from twin.config import (MARKET_PRESETS, STATE_NAMES, STRATEGY_PRESETS, Assumptions, Macro,
                         Shocks, Shortfall)
from twin.engine import PCTS, simulate
from twin.scenarios import (PRESETS, ExpenseChange, HouseBuy, Job, JobChange, MarketCrash, OneOff,
                            SelfEmployment, Study, Unemployment, describe, preset)


# chart colours (validated categorical slots 1/2 + blue sequential steps for the bands)
BLUE, ORANGE = "#2a78d6", "#eb6834"
BAND_OUTER, BAND_INNER = "rgba(42,120,214,0.14)", "rgba(42,120,214,0.30)"
CRISIS_PREFIX = "Krise: "

EVENT_TYPES = {
    "Studium": Study, "Job": Job, "Jobwechsel": JobChange, "Arbeitslosigkeit": Unemployment,
    "Selbststaendig": SelfEmployment, "Hauskauf": HouseBuy, "Einmalige Ausgabe/Einnahme": OneOff,
    "Ausgaben aendern": ExpenseChange, "Boersencrash": MarketCrash,
}


@st.cache_resource
def get_calib():
    return calibrate()


@st.cache_data(show_spinner=False, max_entries=64)
def run(pid: str, events: tuple, years: int, a: Assumptions, n_paths: int, seed: int):
    return simulate(get_calib().persons[pid], list(events), years, a, n_paths, seed, calib=get_calib())


@st.cache_data(show_spinner=False, max_entries=16)
def run_tornado(pid: str, events: tuple, years: int, a: Assumptions, n_paths: int, seed: int):
    c = get_calib()
    return tornado(c.persons[pid], list(events), years, a, c, n_paths, seed)


def chf(x: float) -> str:
    return f"{x:,.0f} CHF".replace(",", "'")


st.page_link("ui/spiel.py", label="🎮 Zurück zum Spiel")

calib = get_calib()
if "events" not in st.session_state:
    st.session_state.events = list(preset("master", calib.persons["P00001"]))

# ================================================================ sidebar
with st.sidebar:
    st.header("👤 Profil")
    ids = sorted(calib.persons)
    pid = st.selectbox(
        "Person", ids, index=ids.index("P00001"),
        format_func=lambda i: f"{i} · {calib.persons[i].name}, {calib.persons[i].age} J., {calib.persons[i].status}")
    person = calib.persons[pid]
    years = st.slider("Planungshorizont (Jahre)", 1, 25, 10)

    st.header("📈 Markt")
    market_name = st.segmented_control("Marktannahme", list(MARKET_PRESETS), default="standard",
                                       key="market") or "standard"
    st.header("🧭 Strategie")
    strat_name = st.segmented_control("Anlagestrategie", list(STRATEGY_PRESETS), default="ausgewogen",
                                      key="strategy") or "ausgewogen"
    market, strategy = MARKET_PRESETS[market_name], STRATEGY_PRESETS[strat_name]

    with st.expander("Feineinstellungen (alles Annahmen)"):
        st.caption("Markt")
        market = replace(market,
                         equity_mu=st.slider("Aktienrendite p.a. (%)", 0.0, 12.0, market.equity_mu * 100, 0.5) / 100,
                         equity_sigma=st.slider("Aktienvolatilitaet p.a. (%)", 5.0, 35.0, market.equity_sigma * 100, 1.0) / 100,
                         jump_lambda=st.slider("Crashs pro 10 Jahre", 0.0, 3.0, market.jump_lambda * 10, 0.1) / 10)
        st.caption("Strategie")
        strategy = replace(strategy,
                           equity_share=st.slider("Aktienanteil (%)", 0, 100, int(strategy.equity_share * 100), 5) / 100,
                           buffer_months=st.slider("Notgroschen (Monatsausgaben)", 0.0, 12.0, strategy.buffer_months, 0.5))
        st.caption("Makro")
        macro = Macro(inflation=st.slider("Inflation p.a. (%)", 0.0, 5.0, 1.0, 0.25) / 100,
                      career_growth=st.slider("Gehaltswachstum im Job p.a. (%)", 0.0, 6.0, 2.0, 0.5) / 100)
        st.caption("Wenn das Cash nicht reicht: verkaufen → Ausgaben kuerzen → Kredit")
        shortfall = Shortfall(spending_cut=st.slider("Ausgabenkuerzung (%)", 0, 40, 15, 5) / 100,
                              credit_rate=st.slider("Kreditzins p.a. (%)", 2.0, 15.0, 8.0, 0.5) / 100)
        st.caption("Zufaellige Schocks")
        job_loss = st.toggle("Zufaelliger Jobverlust", value=False)
        shocks = Shocks(job_loss_per_year=(st.slider("Risiko pro Jahr (%)", 0.5, 10.0, 2.5, 0.5) / 100) if job_loss else 0.0,
                        reemployment_months=st.slider("Jobsuche im Schnitt (Monate)", 1.0, 12.0, 4.0, 0.5))
        n_paths = st.select_slider("Simulationspfade", [500, 1000, 2000, 5000, 10000], value=2000)
        seed = st.number_input("Zufalls-Seed", 0, 10_000, 0)

a = Assumptions(market=market, strategy=strategy, macro=macro, shortfall=shortfall, shocks=shocks)

# ================================================================ header
st.title("🛰️ AI Financial Twin")
st.caption("Don't predict the future – make it explorable. Synthetische Daten, keine Anlageberatung.")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Person", f"{person.name}, {person.age}")
c2.metric("Status", person.status)
c3.metric("Cash heute", chf(person.cash))
c4.metric("Portfolio / Schulden", f"{chf(person.portfolio)} / {chf(person.debt)}")
c5.metric("Typischer Monat (Daten)", chf(person.mu), help=f"± {chf(person.mu_se)} Standardfehler, "
          f"Schwankung {chf(person.sigma)} pro Monat; Ausgaben ~ {chf(person.expenses)}")

# ================================================================ scenario builder
left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("🗺️ Lebensplan")
    pc1, pc2 = st.columns([3, 1])
    tpl = pc1.selectbox("Vorlage", PRESETS, index=PRESETS.index("master"), label_visibility="collapsed", key="tpl")
    if pc2.button("Vorlage laden", width="stretch"):
        st.session_state.events = list(preset(tpl, person))
        st.rerun()

    for i, ev in enumerate(st.session_state.events):
        e1, e2 = st.columns([6, 1])
        d = {k: v for k, v in asdict(ev).items() if k not in ("start", "label") and v is not None}
        details = ", ".join(f"{k}={v:,.0f}" if isinstance(v, (int, float)) and abs(v) >= 10 else f"{k}={v}"
                            for k, v in d.items())
        e1.markdown(f"**Jahr {ev.start / 12:.1f}** · {ev.label}  \n<small>{details}</small>",
                    unsafe_allow_html=True)
        if e2.button("✕", key=f"del{i}", help="Ereignis entfernen"):
            st.session_state.events.pop(i)
            st.rerun()
    if not st.session_state.events:
        st.info("Keine Ereignisse – die Person lebt weiter wie in ihren Daten.")

    with st.expander("➕ Ereignis hinzufuegen"):
        kind = st.selectbox("Art", list(EVENT_TYPES))
        start = int(round(st.number_input("Start (Jahr ab heute)", 0.0, float(years), 0.0, 0.5) * 12))
        if kind == "Studium":
            months = st.number_input("Dauer (Monate)", 1, 96, 24)
            tuition = st.number_input("Studiengebuehren pro Jahr (CHF)", 0, 50_000, 8000, 500)
            side = st.number_input("Nebenjob waehrend Studium (CHF/Monat)", 0, 5000, int(person.income) if person.state == 0 else 1000, 100)
            sal = st.number_input("Gehalt danach (CHF netto/Monat)", 0, 20_000, 5500, 100)
            exp_after = st.number_input("Mehrausgaben danach (CHF/Monat)", -2000, 5000, 1000, 100)
            new = Study(start, months, tuition, side, sal, exp_after)
        elif kind == "Job":
            sal = st.number_input("Gehalt (CHF netto/Monat)", 0, 20_000, 5000, 100)
            exp = st.number_input("Mehrausgaben (CHF/Monat)", -2000, 5000, 800, 100)
            new = Job(start, sal, exp)
        elif kind == "Jobwechsel":
            new = JobChange(start, st.number_input("Lohnerhoehung (%)", -50, 100, 10) / 100,
                            st.number_input("Luecke ohne Einkommen (Monate)", 0, 12, 1))
        elif kind == "Arbeitslosigkeit":
            new = Unemployment(start, st.number_input("Dauer (Monate)", 1, 36, 6))
        elif kind == "Selbststaendig":
            new = SelfEmployment(start, st.number_input("Einkommen (CHF netto/Monat)", 0, 30_000, 5000, 100),
                                 st.number_input("Startkosten (CHF)", 0, 200_000, 15_000, 1000))
        elif kind == "Hauskauf":
            new = HouseBuy(start, st.number_input("Kaufpreis (CHF)", 100_000, 3_000_000, 750_000, 25_000))
        elif kind == "Einmalige Ausgabe/Einnahme":
            new = OneOff(start, st.number_input("Betrag (CHF, + = Ausgabe, − = Einnahme)", -500_000, 500_000, 10_000, 500),
                         st.text_input("Bezeichnung", "Einmalig"))
        elif kind == "Ausgaben aendern":
            new = ExpenseChange(start, st.number_input("Aenderung (CHF/Monat)", -5000, 5000, 300, 50),
                                st.text_input("Bezeichnung", "Ausgaben"))
        else:
            new = MarketCrash(start, st.slider("Crash (%)", -60, -5, -30) / 100)
        if st.button("Hinzufuegen", type="primary"):
            st.session_state.events.append(new)
            st.rerun()

with right:
    st.subheader("🚨 Apollo-13-Modus")
    st.caption("Krise einspielen und sehen, wie der Plan reagiert.")
    crisis_year = st.slider("Krise in Jahr", 0.0, float(max(years - 1, 0)), min(5.0, float(max(years - 1, 0))), 0.5)
    tc = int(round(crisis_year * 12))
    k1, k2 = st.columns(2)
    crises = {
        "💥 Boersencrash −35 %": MarketCrash(tc, -0.35, CRISIS_PREFIX + "Boersencrash"),
        "📉 Jobverlust 6 Monate": Unemployment(tc, 6, CRISIS_PREFIX + "Jobverlust"),
        "🧾 Rechnung 10'000 CHF": OneOff(tc, 10_000, CRISIS_PREFIX + "Rechnung"),
        "🏠 Miete +400 CHF/Monat": ExpenseChange(tc, 400, CRISIS_PREFIX + "Mieterhoehung"),
    }
    for j, (lbl, ev) in enumerate(crises.items()):
        if (k1 if j % 2 == 0 else k2).button(lbl, width="stretch"):
            st.session_state.events.append(ev)
            st.rerun()
    has_crisis = any(e.label.startswith(CRISIS_PREFIX) for e in st.session_state.events)
    if has_crisis and st.button("Krisen entfernen", width="stretch"):
        st.session_state.events = [e for e in st.session_state.events if not e.label.startswith(CRISIS_PREFIX)]
        st.rerun()
    compare = st.radio("Vergleichen mit",
                       ["Plan ohne Krisen", "Ohne Ereignisse (weiter wie bisher)", "Kein Vergleich"],
                       index=0 if has_crisis else 1)

# ================================================================ simulate
events = tuple(st.session_state.events)
with st.spinner("Simuliere …"):
    res = run(pid, events, years, a, n_paths, seed)
    ref_events = None
    if compare == "Plan ohne Krisen":
        ref_events = tuple(e for e in events if not e.label.startswith(CRISIS_PREFIX))
    elif compare.startswith("Ohne Ereignisse"):
        ref_events = ()
    ref = run(pid, ref_events, years, a, n_paths, seed) if ref_events is not None and ref_events != events else None

# ================================================================ KPIs
m, rm = res.metrics, (ref.metrics if ref else None)
k = st.columns(5)
k[0].metric(f"Nettovermoegen in {years} J. (Median)", chf(m["median_net_worth_end"]),
            delta=chf(m["median_net_worth_end"] - rm["median_net_worth_end"]) if rm else None)
k[1].metric("90 %-Spanne", f"{chf(m['p5_net_worth_end'])} – {chf(m['p95_net_worth_end'])}")
k[2].metric("Braucht Kredit", f"{m['p_ever_credit']:.0%}",
            delta=f"{(m['p_ever_credit'] - rm['p_ever_credit']) * 100:+.0f} Pp." if rm else None, delta_color="inverse")
k[3].metric("Tiefster Liquiditaetsstand (P5)", chf(m["p5_lowest_liquid"]))
k[4].metric("Monate mit Sparprogramm (Ø)", f"{m['avg_austerity_months']:.1f}",
            delta=f"{m['avg_austerity_months'] - rm['avg_austerity_months']:+.1f}" if rm else None, delta_color="inverse")

warnings = []
if m["p_ever_credit"] > 0.5:
    warnings.append(f"In **{m['p_ever_credit']:.0%}** der Simulationen reicht das Geld nicht ohne Kredit.")
if m.get("p_house_failed", 0) > 0:
    warnings.append(f"Hauskauf scheitert am Eigenkapital in **{m['p_house_failed']:.0%}** der Faelle.")
if m.get("p_house_unaffordable", 0) > 0:
    warnings.append(f"Tragbarkeit (≤ 1/3 des Bruttoeinkommens) verletzt in **{m['p_house_unaffordable']:.0%}** der Faelle – "
                    "eine Bank wuerde die Hypothek so wahrscheinlich nicht geben.")
if m["p_alv_exhausted"] > 0:
    warnings.append(f"Arbeitslosengeld laeuft aus in **{m['p_alv_exhausted']:.0%}** der Faelle.")
for w in warnings:
    st.warning(w, icon="⚠️")

# ================================================================ charts
x = np.arange(years * 12 + 1) / 12


def event_lines(fig):
    for t, label in res.plan.labels:
        fig.add_vline(x=t / 12, line_width=1, line_dash="dot", line_color="rgba(128,128,128,0.6)")
        fig.add_annotation(x=t / 12, y=1, yref="paper", text=label, showarrow=False, textangle=-90,
                           xanchor="right", yanchor="top", font=dict(size=10, color="gray"))


def base_layout(fig, title, h=420):
    fig.update_layout(title=dict(text=title, x=0, font=dict(size=15)), height=h, hovermode="x unified",
                      margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.15),
                      xaxis=dict(title="Jahre ab heute", showgrid=False),
                      yaxis=dict(title="CHF", tickformat=",.0f", gridcolor="rgba(128,128,128,0.15)",
                                 zeroline=True, zerolinecolor="rgba(128,128,128,0.5)"))
    return fig


tab1, tab2, tab3, tab4 = st.tabs(["📊 Vermoegen", "🌪️ Was zaehlt am meisten?", "📋 Plan & Ziele", "🔍 Annahmen"])

with tab1:
    p = res.percentiles["net_worth"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=p[4], line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=p[0], fill="tonexty", fillcolor=BAND_OUTER, line=dict(width=0),
                             name="90 % der Faelle", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=p[3], line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=p[1], fill="tonexty", fillcolor=BAND_INNER, line=dict(width=0),
                             name="50 % der Faelle", hoverinfo="skip"))
    for s in res.samples[:8]:
        fig.add_trace(go.Scatter(x=x, y=s, line=dict(width=0.6, color="rgba(42,120,214,0.35)"),
                                 showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=p[2], line=dict(width=2.5, color=BLUE), name="Szenario (Median)",
                             hovertemplate="%{y:,.0f} CHF"))
    if ref:
        fig.add_trace(go.Scatter(x=x, y=ref.percentiles["net_worth"][2], line=dict(width=2, color=ORANGE, dash="dash"),
                                 name=f"Vergleich: {compare} (Median)", hovertemplate="%{y:,.0f} CHF"))
    event_lines(fig)
    st.plotly_chart(base_layout(fig, "Nettovermoegen: Median und Unsicherheit"), width="stretch",
                    theme="streamlit")
    st.caption("Duenne Linien: einzelne simulierte Lebenslaeufe. Baender: Spanne, in der 50 % bzw. 90 % der "
               "Simulationen liegen. Nettovermoegen = Cash + Portfolio + Haus − Hypothek − Kredite.")

    cols = st.columns(3)
    for col, (key, title) in zip(cols, [("cash", "Cash (Median)"), ("portfolio", "Portfolio (Median)"),
                                        ("debt", "Schulden inkl. Hypothek (Median)")]):
        f = go.Figure()
        f.add_trace(go.Scatter(x=x, y=res.percentiles[key][2], line=dict(width=2, color=BLUE), name="Szenario",
                               hovertemplate="%{y:,.0f} CHF"))
        if ref:
            f.add_trace(go.Scatter(x=x, y=ref.percentiles[key][2], line=dict(width=2, color=ORANGE, dash="dash"),
                                   name="Vergleich", hovertemplate="%{y:,.0f} CHF"))
        col.plotly_chart(base_layout(f, title, 280), width="stretch", theme="streamlit")

    with st.expander("Tabelle (Jahresende)"):
        rows = range(0, years * 12 + 1, 12)
        tbl = pd.DataFrame({"Jahr": [t // 12 for t in rows]})
        for i, q in enumerate(PCTS):
            tbl[f"Nettovermoegen P{q}"] = [res.percentiles["net_worth"][i, t] for t in rows]
        tbl["Cash (Median)"] = [res.percentiles["cash"][2, t] for t in rows]
        tbl["Schulden (Median)"] = [res.percentiles["debt"][2, t] for t in rows]
        st.dataframe(tbl.style.format("{:,.0f}", subset=tbl.columns[1:]), hide_index=True, width="stretch")

with tab2:
    st.markdown("Welche Annahme veraendert das Ergebnis am staerksten? Jede Annahme wird einzeln auf einen "
                "tiefen und einen hohen Wert gesetzt, alles andere bleibt gleich (gleiche Zufallszahlen).")
    if st.button("Sensitivitaet berechnen", type="primary"):
        st.session_state.tornado = run_tornado(pid, events, years, a, 1000, seed)
    if "tornado" in st.session_state:
        base, rows = st.session_state.tornado
        f = go.Figure()
        names = [r["parameter"] for r in rows]
        f.add_trace(go.Bar(y=names, x=[r["low"] for r in rows], orientation="h", name="tiefer Wert",
                           marker=dict(color=BLUE, cornerradius=4), text=[r["low_label"] for r in rows],
                           textposition="outside", hovertemplate="%{text}: %{x:+,.0f} CHF<extra></extra>"))
        f.add_trace(go.Bar(y=names, x=[r["high"] for r in rows], orientation="h", name="hoher Wert",
                           marker=dict(color=ORANGE, cornerradius=4), text=[r["high_label"] for r in rows],
                           textposition="outside", hovertemplate="%{text}: %{x:+,.0f} CHF<extra></extra>"))
        f.update_layout(barmode="overlay", bargap=0.35)
        base_layout(f, f"Aenderung des Median-Nettovermoegens nach {years} J. (Basis {chf(base)})",
                    60 + 45 * len(rows))
        f.update_layout(hovermode="closest", xaxis=dict(title="CHF Aenderung", tickformat="+,.0f"), yaxis=dict(title=None))
        st.plotly_chart(f, width="stretch", theme="streamlit")
        st.caption("Die Zeilen oben haben den groessten Einfluss. Wenn ihr die Werte nicht genau kennt, "
                   "sind das die Annahmen, die man zuerst pruefen sollte.")

with tab3:
    st.markdown("**Ablauf des Plans**")
    for line in describe(res.plan) or ["Keine Ereignisse."]:
        st.markdown(f"- {line}")
    if res.goals:
        st.markdown("**Ziele der Person** (aus den Daten; erreicht, wenn Cash + Portfolio − Kredit ≥ Ziel)")
        st.dataframe(pd.DataFrame([{"Ziel": g["goal"], "Betrag": chf(g["target"]), "Zeitpunkt": f"Jahr {g['month'] / 12:.1f}",
                                    "Wahrscheinlichkeit": f"{g['p_reached']:.0%}",
                                    "Median verfuegbar": chf(g["median_liquid"])} for g in res.goals]),
                     hide_index=True, width="stretch")
    else:
        st.caption("Keine Ziele im gewaehlten Horizont.")
    st.markdown(f"**Buchhaltungs-Check:** Nettovermoegen-Aenderung = Summe aller gebuchten Fluesse auf jedem Pfad, "
                f"max. Abweichung {res.identity_error:.1e} CHF ✅")

with tab4:
    st.markdown("Alle Zahlen, die das Ergebnis bestimmen. **Kalibriert** = aus den 24 Monaten der Person bzw. ihrer "
                "Gruppe geschaetzt; **Annahme** = gesetzt, im Menue links aenderbar.")
    sp = calib.states[person.state]
    rows = [
        ("Typischer Monat (Nettofluss)", chf(person.mu), "kalibriert", f"± {chf(person.mu_se)} Standardfehler"),
        ("Schwankung pro Monat", chf(person.sigma), "kalibriert", "normale Monate; Dez/Feb/Aug breiter"),
        ("Ausgaben pro Monat", chf(person.expenses), "kalibriert", "Einkommen − typischer Monat"),
        ("Saisonmuster", ", ".join(f"{v:+.0f}" for v in sp.seasonal), "kalibriert", f"Gruppe {STATE_NAMES[person.state]}, Jan–Dez"),
        ("Aktienrendite / Volatilitaet", f"{market.equity_mu:.1%} / {market.equity_sigma:.0%}", "Annahme", market_name),
        ("Crash", f"{market.jump_lambda * 10:.1f} pro 10 J., Ø {np.expm1(market.jump_mean):.0%}", "Annahme", "Merton-Spruenge"),
        ("Aktienanteil / Notgroschen", f"{strategy.equity_share:.0%} / {strategy.buffer_months:g} Monate", "Annahme", strat_name),
        ("Inflation / Gehaltswachstum", f"{macro.inflation:.2%} / {macro.career_growth:.1%}", "Annahme", "ab Monat 1"),
        ("Ausgabenkuerzung / Kreditzins", f"{shortfall.spending_cut:.0%} / {shortfall.credit_rate:.1%}", "Annahme", "wenn Cash < 0"),
        ("Zufaelliger Jobverlust", f"{shocks.job_loss_per_year:.1%} p.a., Suche Ø {shocks.reemployment_months:g} Mt.", "Annahme", "aus" if not job_loss else "an"),
        ("Arbeitslosengeld", f"{a.social.alv_rate:.0%}, max. {a.social.alv_max_months} Monate", "vereinfacht", "unter 25, ohne Kinder"),
        ("Hypothek", f"{a.social.min_equity:.0%} EK, {a.social.mortgage_rate:.0%} Zins, Tragbarkeit mit {a.social.affordability_rate:.0%}", "vereinfacht", "Schweizer Bankpraxis"),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["Groesse", "Wert", "Quelle", "Bemerkung"]), hide_index=True,
                 width="stretch")
    st.info("Grenzen: Die Daten sind synthetisch und umfassen nur 24 Monate. Zusammenhaenge zwischen Gruppen "
            "(z. B. Student → Angestellt) sind Vergleiche zwischen Personen, keine Ursachen. Ergebnisse zeigen "
            "Spannen moeglicher Verlaeufe, keine Prognose und keine Anlageberatung.", icon="ℹ️")
