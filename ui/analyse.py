"""Analysis mode: dashboard with all the controls (English GUI)."""
from __future__ import annotations

import html
import re
from dataclasses import asdict, replace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from twin.analysis import tornado
from twin.analysis_chat import ChatCtx, answer, avatar_from_cfg, greeting, status, suggestions
from twin.avatar import avatar_svg
from twin.calibration import calibrate
from twin.config import (MARKET_PRESETS, STATE_NAMES, STRATEGY_PRESETS, Assumptions, Macro,
                         Shocks, Shortfall)
from twin.engine import PCTS, simulate
from twin.lifechart import chart_data, life_chart
from twin.tipps import STYLES, tipps
from twin.scenarios import (PRESET_LABELS, PRESETS, ExpenseChange, HouseBuy, Job, JobChange, MarketCrash, OneOff,
                            SelfEmployment, Study, Unemployment, describe, preset)


# chart colours (validated categorical slots 1/2 + blue sequential steps for the bands)
BLUE, ORANGE = "#2a78d6", "#eb6834"
CRISIS_PREFIX = "Crisis: "
CHAT_PATHS = 1000          # paths per simulation the twin chat runs (fast enough to answer within a second)

EVENT_TYPES = {
    "Study": Study, "Job": Job, "Job change": JobChange, "Unemployment": Unemployment,
    "Self-employment": SelfEmployment, "House purchase": HouseBuy, "One-off expense/income": OneOff,
    "Change expenses": ExpenseChange, "Market crash": MarketCrash,
}
MARKET_LABELS = {"pessimistisch": "pessimistic", "standard": "standard", "optimistisch": "optimistic", "ohne_crash": "no crash"}
STRATEGY_LABELS = {"konservativ": "cautious", "ausgewogen": "balanced", "risky": "bold"}


@st.cache_resource
def get_calib():
    return calibrate()


# keyed by the (frozen) Person, so the player's own data works exactly like the challenge profiles.
# cache_resource (no pickling): results are read-only here, and pickling breaks after a dev hot-reload of twin/*
@st.cache_resource(show_spinner=False, max_entries=64)
def run(person, events: tuple, years: int, a: Assumptions, n_paths: int, seed: int):
    return simulate(person, list(events), years, a, n_paths, seed, calib=get_calib())


@st.cache_resource(show_spinner=False, max_entries=16)
def run_tornado(person, events: tuple, years: int, a: Assumptions, n_paths: int, seed: int):
    return tornado(person, list(events), years, a, get_calib(), n_paths, seed)


@st.cache_resource(show_spinner=False, max_entries=32)
def run_tips(person, years: int, a: Assumptions, seed: int):
    return tipps(person, get_calib(), a, years, 800, seed)


def chf(x: float) -> str:
    return f"{x:,.0f} CHF".replace(",", "'")


st.page_link("ui/spiel.py", label="🎮 Back to the game")

calib = get_calib()
if "events" not in st.session_state:
    st.session_state.events = []          # start without events: your data as it is (templates below)

# ================================================================ sidebar
with st.sidebar:
    st.header("👤 Profile")
    # the player's own status quo (updated by the film ride, if any) comes first
    game = st.session_state.get("game_session")
    me = getattr(game, "analysis_person", None) if game is not None else None
    ids = (["__me__"] if me is not None else []) + sorted(calib.persons)
    pid = st.selectbox(
        "Person", ids, index=0 if me is not None else ids.index("P00004"),
        format_func=lambda i: (f"🙋 Your data · {me.name}, {me.age}" if i == "__me__" else
                               f"{i} · {calib.persons[i].name}, {calib.persons[i].age}, {calib.persons[i].status}"))
    person = me if pid == "__me__" else calib.persons[pid]
    years = st.slider("Planning horizon (years)", 1, 25, 10)

    st.header("📈 Market")
    market_name = st.segmented_control("Market assumption", list(MARKET_PRESETS), default="standard",
                                       format_func=lambda k: MARKET_LABELS.get(k, k), key="market") or "standard"
    st.header("🧭 Strategy")
    strat_name = st.segmented_control("Investment strategy", list(STRATEGY_PRESETS), default="ausgewogen",
                                      format_func=lambda k: STRATEGY_LABELS.get(k, k), key="strategy") or "ausgewogen"
    market, strategy = MARKET_PRESETS[market_name], STRATEGY_PRESETS[strat_name]

    with st.expander("Fine-tuning (all assumptions)"):
        st.caption("Market")
        market = replace(market,
                         equity_mu=st.slider("Equity return p.a. (%)", 0.0, 12.0, market.equity_mu * 100, 0.5) / 100,
                         equity_sigma=st.slider("Equity volatility p.a. (%)", 5.0, 35.0, market.equity_sigma * 100, 1.0) / 100,
                         jump_lambda=st.slider("Crashes per 10 years", 0.0, 3.0, market.jump_lambda * 10, 0.1) / 10)
        st.caption("Strategy")
        strategy = replace(strategy,
                           equity_share=st.slider("Equity share (%)", 0, 100, int(strategy.equity_share * 100), 5) / 100,
                           buffer_months=st.slider("Emergency fund (months of expenses)", 0.0, 12.0, strategy.buffer_months, 0.5))
        st.caption("Macro")
        macro = Macro(inflation=st.slider("Inflation p.a. (%)", 0.0, 5.0, 1.0, 0.25) / 100,
                      career_growth=st.slider("Salary growth in a job p.a. (%)", 0.0, 6.0, 2.0, 0.5) / 100)
        st.caption("When cash runs out: sell → cut spending → credit")
        shortfall = Shortfall(spending_cut=st.slider("Spending cut (%)", 0, 40, 15, 5) / 100,
                              credit_rate=st.slider("Credit interest p.a. (%)", 2.0, 15.0, 8.0, 0.5) / 100)
        st.caption("Random shocks")
        job_loss = st.toggle("Random job loss", value=False)
        shocks = Shocks(job_loss_per_year=(st.slider("Risk per year (%)", 0.5, 10.0, 2.5, 0.5) / 100) if job_loss else 0.0,
                        reemployment_months=st.slider("Average job search (months)", 1.0, 12.0, 4.0, 0.5))
        n_paths = st.select_slider("Simulation paths", [500, 1000, 2000, 5000, 10000], value=2000)
        seed = st.number_input("Random seed", 0, 10_000, 0)

a = Assumptions(market=market, strategy=strategy, macro=macro, shortfall=shortfall, shocks=shocks)

# ================================================================ header
st.title("🛰️ AI Financial Twin")
st.caption("Don't predict the future – make it explorable. Synthetic data, not investment advice.")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Person", f"{person.name}, {person.age}")
c2.metric("Status", person.status)
c3.metric("Cash today", chf(person.cash))
c4.metric("Portfolio / debt", f"{chf(person.portfolio)} / {chf(person.debt)}")
c5.metric("Typical month (data)", chf(person.mu), help=f"± {chf(person.mu_se)} standard error, "
          f"fluctuation {chf(person.sigma)} per month; expenses ~ {chf(person.expenses)}")

# ================================================================ scenario builder
left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("🗺️ Life plan")
    pc1, pc2 = st.columns([3, 1])
    tpl = pc1.selectbox("Template", PRESETS, index=PRESETS.index("basis"), label_visibility="collapsed", key="tpl",
                        format_func=lambda k: PRESET_LABELS.get(k, k))
    if pc2.button("Load template", width="stretch"):
        st.session_state.events = list(preset(tpl, person))
        st.rerun()

    for i, ev in enumerate(st.session_state.events):
        e1, e2 = st.columns([6, 1])
        d = {k: v for k, v in asdict(ev).items() if k not in ("start", "label") and v is not None}
        details = ", ".join(f"{k}={v:,.0f}" if isinstance(v, (int, float)) and abs(v) >= 10 else f"{k}={v}"
                            for k, v in d.items())
        e1.markdown(f"**Year {ev.start / 12:.1f}** · {ev.label}  \n<small>{details}</small>",
                    unsafe_allow_html=True)
        if e2.button("✕", key=f"del{i}", help="Remove event"):
            st.session_state.events.pop(i)
            st.rerun()
    if not st.session_state.events:
        st.info("No events – the person carries on as in their data.")

    with st.expander("➕ Add an event"):
        kind = st.selectbox("Type", list(EVENT_TYPES))
        start = int(round(st.number_input("Start (years from today)", 0.0, float(years), 0.0, 0.5) * 12))
        if kind == "Study":
            months = st.number_input("Duration (months)", 1, 96, 24)
            tuition = st.number_input("Tuition per year (CHF)", 0, 50_000, 8000, 500)
            side = st.number_input("Side job while studying (CHF/month)", 0, 5000, int(person.income) if person.state == 0 else 1000, 100)
            sal = st.number_input("Salary afterwards (CHF net/month)", 0, 20_000, 5500, 100)
            exp_after = st.number_input("Extra expenses afterwards (CHF/month)", -2000, 5000, 1000, 100)
            new = Study(start, months, tuition, side, sal, exp_after)
        elif kind == "Job":
            sal = st.number_input("Salary (CHF net/month)", 0, 20_000, 5000, 100)
            exp = st.number_input("Extra expenses (CHF/month)", -2000, 5000, 800, 100)
            new = Job(start, sal, exp)
        elif kind == "Job change":
            new = JobChange(start, st.number_input("Pay rise (%)", -50, 100, 10) / 100,
                            st.number_input("Gap without income (months)", 0, 12, 1))
        elif kind == "Unemployment":
            new = Unemployment(start, st.number_input("Duration (months)", 1, 36, 6))
        elif kind == "Self-employment":
            new = SelfEmployment(start, st.number_input("Income (CHF net/month)", 0, 30_000, 5000, 100),
                                 st.number_input("Start-up costs (CHF)", 0, 200_000, 15_000, 1000))
        elif kind == "House purchase":
            new = HouseBuy(start, st.number_input("Purchase price (CHF)", 100_000, 3_000_000, 750_000, 25_000))
        elif kind == "One-off expense/income":
            new = OneOff(start, st.number_input("Amount (CHF, + = expense, − = income)", -500_000, 500_000, 10_000, 500),
                         st.text_input("Label", "One-off"))
        elif kind == "Change expenses":
            new = ExpenseChange(start, st.number_input("Change (CHF/month)", -5000, 5000, 300, 50),
                                st.text_input("Label", "Expenses"))
        else:
            new = MarketCrash(start, st.slider("Crash (%)", -60, -5, -30) / 100)
        if st.button("Add", type="primary"):
            st.session_state.events.append(new)
            st.rerun()

with right:
    st.subheader("🚨 Apollo 13 mode")
    st.caption("Throw in a crisis and see how the plan copes.")
    crisis_year = st.slider("Crisis in year", 0.0, float(max(years - 1, 0)), min(5.0, float(max(years - 1, 0))), 0.5)
    tc = int(round(crisis_year * 12))
    k1, k2 = st.columns(2)
    crises = {
        "💥 Market crash −35 %": MarketCrash(tc, -0.35, CRISIS_PREFIX + "Market crash"),
        "📉 Job loss 6 months": Unemployment(tc, 6, CRISIS_PREFIX + "Job loss"),
        "🧾 Bill CHF 10'000": OneOff(tc, 10_000, CRISIS_PREFIX + "Bill"),
        "🏠 Rent +400 CHF/month": ExpenseChange(tc, 400, CRISIS_PREFIX + "Rent increase"),
    }
    for j, (lbl, ev) in enumerate(crises.items()):
        if (k1 if j % 2 == 0 else k2).button(lbl, width="stretch"):
            st.session_state.events.append(ev)
            st.rerun()
    has_crisis = any(e.label.startswith(CRISIS_PREFIX) for e in st.session_state.events)
    if has_crisis and st.button("Remove crises", width="stretch"):
        st.session_state.events = [e for e in st.session_state.events if not e.label.startswith(CRISIS_PREFIX)]
        st.rerun()
    compare = st.radio("Compare with",
                       ["Plan without crises", "No events (carry on as before)", "No comparison"],
                       index=0 if has_crisis else 1)

# ================================================================ simulate
events = tuple(st.session_state.events)
with st.spinner("Simulating …"):
    res = run(person, events, years, a, n_paths, seed)
    ref_events = None
    if compare == "Plan without crises":
        ref_events = tuple(e for e in events if not e.label.startswith(CRISIS_PREFIX))
    elif compare.startswith("No events"):
        ref_events = ()
    ref = run(person, ref_events, years, a, n_paths, seed) if ref_events is not None and ref_events != events else None

# ================================================================ KPIs
m, rm = res.metrics, (ref.metrics if ref else None)
k = st.columns(5)
k[0].metric(f"Net worth in {years} y (median)", chf(m["median_net_worth_end"]),
            delta=chf(m["median_net_worth_end"] - rm["median_net_worth_end"]) if rm else None)
k[1].metric("90 % range", f"{chf(m['p5_net_worth_end'])} – {chf(m['p95_net_worth_end'])}")
k[2].metric("Needs credit", f"{m['p_ever_credit']:.0%}",
            delta=f"{(m['p_ever_credit'] - rm['p_ever_credit']) * 100:+.0f} pp" if rm else None, delta_color="inverse")
k[3].metric("Lowest liquidity (P5)", chf(m["p5_lowest_liquid"]))
k[4].metric("Months of austerity (avg)", f"{m['avg_austerity_months']:.1f}",
            delta=f"{m['avg_austerity_months'] - rm['avg_austerity_months']:+.1f}" if rm else None, delta_color="inverse")

warnings = []
if m["p_ever_credit"] > 0.5:
    warnings.append(f"In **{m['p_ever_credit']:.0%}** of the simulations the money does not last without credit.")
if m.get("p_house_failed", 0) > 0:
    warnings.append(f"The house purchase fails for lack of a down payment in **{m['p_house_failed']:.0%}** of the cases.")
if m.get("p_house_unaffordable", 0) > 0:
    warnings.append(f"Affordability (≤ 1/3 of gross income) is violated in **{m['p_house_unaffordable']:.0%}** of the cases – "
                    "a bank would probably not grant this mortgage.")
if m["p_alv_exhausted"] > 0:
    warnings.append(f"Unemployment benefits run out in **{m['p_alv_exhausted']:.0%}** of the cases.")
for w in warnings:
    st.warning(w, icon="⚠️")

# ================================================================ your twin: avatar + chat
def played_decisions(sess) -> list[dict]:
    """Decisions of the game session (without "drive on"), with the age at which they were taken."""
    out = []
    try:
        for h in getattr(sess, "history", None) or []:
            if h.get("key") != "stay":
                out.append({"age": sess.age_at(h["turn"]), "emoji": h.get("emoji", ""), "title": h.get("title", "")})
    except Exception:
        return []
    return out


def bubble_text(msg: dict) -> str:
    text = msg.get("bubble") or msg.get("content", "")
    text = re.sub(r"\*\*|“|”", "", text).replace(" Not investment advice.", "")
    return text if len(text) <= 190 else text[:187].rsplit(" ", 1)[0] + " …"


st.markdown("""<style>
.twin-av { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.twin-bubble { position: relative; width: 100%; padding: 10px 13px; border-radius: 16px; font-size: .9rem;
  line-height: 1.4; background: rgba(42,120,214,.10); border: 1px solid rgba(42,120,214,.35); }
.twin-bubble::after { content: ""; position: absolute; left: 50%; bottom: -9px; width: 16px; height: 16px;
  transform: translateX(-50%) rotate(45deg); background: inherit; border-right: inherit; border-bottom: inherit;
  backdrop-filter: inherit; }
.twin-av svg { max-width: 150px; height: auto; }
</style>""", unsafe_allow_html=True)

is_me = pid == "__me__" and game is not None
cfg = dict(getattr(game, "avatar", None) or {}) if is_me else {"name": person.name}
ride = getattr(game, "ride_data", None) if is_me else None
chat_ctx = ChatCtx(
    person=person, years=years, a=a, events=events, calib=calib, n_paths=CHAT_PATHS, seed=seed,
    name=cfg.get("name") if is_me else person.name, decisions=played_decisions(game) if is_me else [],
    ride=ride if isinstance(ride, dict) else None,
    sim=lambda ev, yrs, a_: run(person, tuple(ev), yrs, a_, CHAT_PATHS, seed),
    tips_fn=lambda: run_tips(person, years, a, seed),
    drivers_fn=lambda: run_tornado(person, events, years, a, 400, seed))
chat_key = (pid, person)
if st.session_state.get("twin_chat_key") != chat_key:
    g = greeting(chat_ctx)
    st.session_state.twin_chat = [{"role": "assistant", "content": g["text"], "bubble": g["bubble"], "mode": "offline"}]
    st.session_state.twin_chat_key = chat_key
    st.session_state.twin_pick_n = st.session_state.get("twin_pick_n", 0) + 1


def ask(question: str) -> None:
    st.session_state.twin_chat.append({"role": "user", "content": question})
    with st.spinner("Your twin is calculating …"):
        out = answer(chat_ctx, question)
    st.session_state.twin_chat.append({"role": "assistant", "content": out["text"], "mode": out["mode"],
                                       "tool": out["tool"]})
    st.session_state.twin_chat = st.session_state.twin_chat[-40:]


st.subheader("🙋 Your twin")
with st.container(border=True):
    av_col, chat_col = st.columns([1, 2.6], gap="large")
    with chat_col:
        box = st.container(height=330)
        pick = st.pills("Try asking", suggestions(chat_ctx), key=f"twin_pick_{st.session_state.twin_pick_n}",
                        label_visibility="collapsed")
        question = st.chat_input("Ask your twin – e.g. “Is pillar 3a worth it?”", key="twin_q")
        if pick:
            ask(pick)
            st.session_state.twin_pick_n += 1
            st.rerun()
        if question:
            ask(question)
        with box:
            for msg in st.session_state.twin_chat:
                with st.chat_message(msg["role"], avatar="🙋" if msg["role"] == "assistant" else None):
                    st.markdown(msg["content"])
    with av_col:
        last = next((m for m in reversed(st.session_state.twin_chat) if m["role"] == "assistant"), None)
        av = avatar_from_cfg(cfg, person.name)
        st.markdown(f'<div class="twin-av"><div class="twin-bubble">{html.escape(bubble_text(last or {}))}</div>'
                    f'{avatar_svg(av, size=150, uid="twin")}</div>', unsafe_allow_html=True)
        llm = status()
        st.caption(f"🧠 Local model {llm['model']} picks the calculation; the numbers come from the simulation."
                   if llm["available"] else
                   "⚙️ Offline mode: rule-based routing. Start Ollama for the local model – the numbers "
                   "come from the simulation either way.")

# ================================================================ charts
x = np.arange(years * 12 + 1) / 12


def base_layout(fig, title, h=420):
    fig.update_layout(title=dict(text=title, x=0, font=dict(size=15)), height=h, hovermode="x unified",
                      margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.15),
                      xaxis=dict(title="Years from today", showgrid=False),
                      yaxis=dict(title="CHF", tickformat=",.0f", gridcolor="rgba(128,128,128,0.15)",
                                 zeroline=True, zerolinecolor="rgba(128,128,128,0.5)"))
    return fig


tab0, tab1, tab2, tab3, tab4 = st.tabs(["💡 Tips & investing", "📊 Net worth", "🌪️ What matters most?",
                                         "📋 Plan & goals", "🔍 Assumptions"])

with tab0:
    st.markdown(f"**What {person.name} could do better** – from the data and {years} simulated years "
                "(rules of thumb, not investment advice).")
    with st.spinner("Looking for tips …"):
        tp = run_tips(person, years, a, seed)
    box = {"warn": st.warning, "do": st.info, "good": st.success}
    for t in tp["tips"]:
        box[t["kind"]](f"**{t['title']}** – {t['text']}", icon=t["icon"])
    st.subheader("📈 How could you invest?")
    st.caption("Same person, same random numbers – only the investment style changes. Choose your style in the "
               "sidebar (🧭 Strategy) and fine-tune it there.")
    so = tp["styles"]
    f = go.Figure()
    f.add_trace(go.Bar(x=[s_["label"] for s_ in so], y=[s_["median"] for s_ in so], marker=dict(color=BLUE, cornerradius=6),
                       error_y=dict(type="data", symmetric=False, array=[s_["p95"] - s_["median"] for s_ in so],
                                    arrayminus=[s_["median"] - s_["p5"] for s_ in so], color="rgba(128,128,128,.6)"),
                       hovertemplate="%{x}: median %{y:,.0f} CHF<extra></extra>", name="median"))
    base_layout(f, f"Net worth after {years} years by investment style (median, p5–p95)", 360)
    f.update_layout(hovermode="closest", xaxis=dict(title=None), showlegend=False)
    st.plotly_chart(f, width="stretch", theme="streamlit")
    st.dataframe(pd.DataFrame([{"Style": s_["label"], "Stocks": f"{s_['equity']:.0%}" if s_["invests"] else "–",
                                "Emergency fund": f"{s_['buffer']:g} months", "Median": chf(s_["median"]),
                                "Range p5–p95": f"{chf(s_['p5'])} – {chf(s_['p95'])}",
                                "Chance of credit": f"{s_['p_credit']:.0%}"} for s_ in so]),
                 hide_index=True, width="stretch")

with tab1:
    st.markdown("**Net worth over your life** – hover (or use the arrow keys) for the numbers at every age, and "
                "switch between two life paths above the chart.")
    comps = []
    if ref is not None:
        comps.append(("ref", "Without crises" if compare == "Plan without crises" else "Without life events", ref))
    if events and ref_events != ():
        comps.append(("none", "Without life events", run(person, (), years, a, n_paths, seed)))
    other_key = "konservativ" if strat_name == "risky" else "risky"
    for key_, label_, strat_ in STYLES:
        if key_ in ("cash", other_key):
            comps.append((f"style_{key_}", "Keep everything in cash" if key_ == "cash" else
                          f"{label_.split(' ', 1)[1]} investing",
                          run(person, events, years, a.with_(strategy=strat_), n_paths, seed)))
    life_chart(chart_data(res, comps, start_age=person.age, plan_label="Your plan",
                          default_comp="ref" if ref is not None else None, hide_label_prefix=CRISIS_PREFIX),
               key="lifechart")
    st.caption("Band: 90 % of the simulated lives (p5–p95). Thin grey line: one simulated life. Dashed: the second "
               "life path – same random numbers, only the plan or the investment style differs. Net worth = "
               "cash + portfolio + house − mortgage − loans.")

    cols = st.columns(3)
    for col, (key, title) in zip(cols, [("cash", "Cash (median)"), ("portfolio", "Portfolio (median)"),
                                        ("debt", "Debt incl. mortgage (median)")]):
        f = go.Figure()
        f.add_trace(go.Scatter(x=x, y=res.percentiles[key][2], line=dict(width=2, color=BLUE), name="Scenario",
                               hovertemplate="%{y:,.0f} CHF"))
        if ref:
            f.add_trace(go.Scatter(x=x, y=ref.percentiles[key][2], line=dict(width=2, color=ORANGE, dash="dash"),
                                   name="Comparison", hovertemplate="%{y:,.0f} CHF"))
        col.plotly_chart(base_layout(f, title, 280), width="stretch", theme="streamlit")

    with st.expander("Table (end of year)"):
        rows = range(0, years * 12 + 1, 12)
        tbl = pd.DataFrame({"Year": [t // 12 for t in rows]})
        for i, q in enumerate(PCTS):
            tbl[f"Net worth P{q}"] = [res.percentiles["net_worth"][i, t] for t in rows]
        tbl["Cash (median)"] = [res.percentiles["cash"][2, t] for t in rows]
        tbl["Debt (median)"] = [res.percentiles["debt"][2, t] for t in rows]
        st.dataframe(tbl.style.format("{:,.0f}", subset=tbl.columns[1:]), hide_index=True, width="stretch")

with tab2:
    st.markdown("Which assumption changes the result the most? Each assumption is set to a low and a high "
                "value on its own, everything else stays the same (same random numbers).")
    if st.button("Compute sensitivity", type="primary"):
        st.session_state.tornado = run_tornado(person, events, years, a, 1000, seed)
    if "tornado" in st.session_state:
        base, rows = st.session_state.tornado
        f = go.Figure()
        names = [r["parameter"] for r in rows]
        f.add_trace(go.Bar(y=names, x=[r["low"] for r in rows], orientation="h", name="low value",
                           marker=dict(color=BLUE, cornerradius=4), text=[r["low_label"] for r in rows],
                           textposition="outside", hovertemplate="%{text}: %{x:+,.0f} CHF<extra></extra>"))
        f.add_trace(go.Bar(y=names, x=[r["high"] for r in rows], orientation="h", name="high value",
                           marker=dict(color=ORANGE, cornerradius=4), text=[r["high_label"] for r in rows],
                           textposition="outside", hovertemplate="%{text}: %{x:+,.0f} CHF<extra></extra>"))
        f.update_layout(barmode="overlay", bargap=0.35)
        base_layout(f, f"Change of the median net worth after {years} y (base {chf(base)})",
                    60 + 45 * len(rows))
        f.update_layout(hovermode="closest", xaxis=dict(title="CHF change", tickformat="+,.0f"), yaxis=dict(title=None))
        st.plotly_chart(f, width="stretch", theme="streamlit")
        st.caption("The rows at the top have the biggest impact. If you don't know these values exactly, "
                   "they are the assumptions to check first.")

with tab3:
    st.markdown("**Plan timeline**")
    for line in describe(res.plan) or ["No events."]:
        st.markdown(f"- {line}")
    if res.goals:
        st.markdown("**The person's goals** (from the data; reached when cash + portfolio − credit ≥ goal)")
        st.dataframe(pd.DataFrame([{"Goal": g["goal"], "Amount": chf(g["target"]), "When": f"year {g['month'] / 12:.1f}",
                                    "Probability": f"{g['p_reached']:.0%}",
                                    "Median available": chf(g["median_liquid"])} for g in res.goals]),
                     hide_index=True, width="stretch")
    else:
        st.caption("No goals within the chosen horizon.")
    st.markdown(f"**Accounting check:** change in net worth = sum of all booked flows on every path, "
                f"max. deviation {res.identity_error:.1e} CHF ✅")

with tab4:
    st.markdown("All numbers that drive the result. **Calibrated** = estimated from the person's 24 months or their "
                "group; **assumption** = set by us, adjustable in the menu on the left.")
    sp = calib.states[person.state]
    rows = [
        ("Typical month (net flow)", chf(person.mu), "calibrated", f"± {chf(person.mu_se)} standard error"),
        ("Fluctuation per month", chf(person.sigma), "calibrated", "normal months; Dec/Feb/Aug wider"),
        ("Expenses per month", chf(person.expenses), "calibrated", "income − typical month"),
        ("Seasonal pattern", ", ".join(f"{v:+.0f}" for v in sp.seasonal), "calibrated", f"group {STATE_NAMES[person.state]}, Jan–Dec"),
        ("Equity return / volatility", f"{market.equity_mu:.1%} / {market.equity_sigma:.0%}", "assumption", MARKET_LABELS.get(market_name, market_name)),
        ("Crash", f"{market.jump_lambda * 10:.1f} per 10 y, avg {np.expm1(market.jump_mean):.0%}", "assumption", "Merton jumps"),
        ("Equity share / emergency fund", f"{strategy.equity_share:.0%} / {strategy.buffer_months:g} months", "assumption", STRATEGY_LABELS.get(strat_name, strat_name)),
        ("Inflation / salary growth", f"{macro.inflation:.2%} / {macro.career_growth:.1%}", "assumption", "from month 1"),
        ("Spending cut / credit interest", f"{shortfall.spending_cut:.0%} / {shortfall.credit_rate:.1%}", "assumption", "when cash < 0"),
        ("Random job loss", f"{shocks.job_loss_per_year:.1%} p.a., search avg {shocks.reemployment_months:g} mo.", "assumption", "off" if not job_loss else "on"),
        ("Unemployment benefits", f"{a.social.alv_rate:.0%}, max. {a.social.alv_max_months} months", "simplified", "under 25, no children"),
        ("Mortgage", f"{a.social.min_equity:.0%} down payment, {a.social.mortgage_rate:.0%} interest, affordability at {a.social.affordability_rate:.0%}", "simplified", "Swiss bank practice"),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["Item", "Value", "Source", "Note"]), hide_index=True,
                 width="stretch")
    st.info("Limits: the data is synthetic and covers only 24 months. Links between groups "
            "(e.g. student → employed) are comparisons between people, not causes. Results show "
            "ranges of possible paths – not a forecast and not investment advice.", icon="ℹ️")
