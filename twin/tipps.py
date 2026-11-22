"""Tips: what the person could do better – for the analysis page (own data, example data or any profile).

``tipps(person, ...)`` returns
* ``tips``: a ranked list of {icon, title, text, kind} (kind: "warn" | "do" | "good"), plain English for the GUI;
* ``styles``: the investment options side by side (keep cash / cautious / balanced / bold), each simulated with the
  same random numbers so the differences come from the strategy only.

All rules are simple and explainable; amounts come from the person's data and the simulation, not from advice.
"""
from __future__ import annotations

from .calibration import Calibration, Person, calibrate
from .config import STRATEGY_PRESETS, Assumptions, Strategy
from .engine import simulate

GOAL_LABEL = {"Emergency savings": "Emergency fund", "Career transition": "Career-change cushion",
              "Education flexibility": "Education reserve", "Housing deposit": "Home down payment",
              "Long-term financial resilience": "Long-term reserve", "Retirement reserve": "Retirement reserve"}
STYLES = [("cash", "💵 Keep it in cash", Strategy(equity_share=0.6, buffer_months=3.0, invest_rate=0.0)),
          ("konservativ", "🛡️ Cautious", STRATEGY_PRESETS["konservativ"]),
          ("ausgewogen", "⚖️ Balanced", STRATEGY_PRESETS["ausgewogen"]),
          ("risky", "🚀 Bold", STRATEGY_PRESETS["risky"])]


def _chf(v: float) -> str:
    return ("CHF −" if v < -0.5 else "CHF ") + f"{abs(v):,.0f}".replace(",", "'")


def anlage_optionen(person: Person, calib: Calibration, a: Assumptions, years: int, n_paths: int = 800,
                    seed: int = 0) -> list[dict]:
    """The investment options compared: median / p5 / p95 net worth at the horizon and the chance of credit."""
    out = []
    for key, label, strat in STYLES:
        r = simulate(person, [], years, a.with_(strategy=strat), n_paths, seed, calib=calib)
        m = r.metrics
        out.append({"key": key, "label": label, "equity": strat.equity_share, "buffer": strat.buffer_months,
                    "invests": strat.invest_rate > 0, "median": m["median_net_worth_end"],
                    "p5": m["p5_net_worth_end"], "p95": m["p95_net_worth_end"], "p_credit": m["p_ever_credit"]})
    return out


def tipps(person: Person, calib: Calibration | None = None, a: Assumptions | None = None, years: int = 15,
          n_paths: int = 800, seed: int = 0) -> dict:
    calib = calib or calibrate()
    a = a or Assumptions()
    res = simulate(person, [], years, a, n_paths, seed, calib=calib)
    m = res.metrics
    styles = anlage_optionen(person, calib, a, years, n_paths, seed)
    tips: list[dict] = []
    add = lambda kind, icon, title, text, prio: tips.append({"kind": kind, "icon": icon, "title": title,
                                                             "text": text, "prio": prio})
    inc, exp, mu = person.income, person.expenses, person.mu
    buffer = person.cash / exp if exp > 0 else 99.0

    # 1. spending vs income
    if mu < 0:
        add("warn", "🔥", "You spend more than you earn",
            f"Your typical month is {_chf(mu)}. Without changes your savings run out after about "
            f"{max(person.cash, 0) / max(-mu, 1):.0f} months. Look at the biggest fixed costs first.", 0)
    elif inc > 0 and mu / inc < 0.10:
        add("do", "✂️", "Raise your savings rate",
            f"You keep {mu / inc:.0%} of your income ({_chf(mu)} a month). 10–20 % gives you room for goals and "
            f"surprises: {_chf(0.15 * inc - mu)} more per month would reach 15 %.", 2)
    elif inc > 0 and mu / inc >= 0.2:
        add("good", "💪", "Strong savings rate", f"You keep {mu / inc:.0%} of your income – keep it up.", 9)
    # 2. rent
    if inc > 0 and person.rent / inc > 1 / 3:
        add("do", "🏠", "Rent is a big block",
            f"Rent is {person.rent / inc:.0%} of your income. A rule of thumb is at most a third "
            f"({_chf(inc / 3)}); a cheaper flat would free {_chf(person.rent - inc / 3)} a month.", 3)
    # 3. debt
    if person.debt > 0:
        add("warn", "🧾", "Pay off expensive debt first",
            f"You owe {_chf(person.debt)} at {person.debt_rate:.1%}, about {_chf(person.debt * person.debt_rate)} "
            "interest a year. Paying it off is a guaranteed return – usually before investing.", 1)
    # 4. emergency fund
    if buffer < 3:
        add("warn", "🐷", "Build an emergency fund",
            f"Your cash covers {buffer:.1f} months of expenses. Aim for 3–6 months ({_chf(3 * exp)}–{_chf(6 * exp)}); "
            f"you are {_chf(3 * exp - person.cash)} short of 3 months.", 1)
    elif buffer > 9:
        add("do", "💤", "A lot of idle cash",
            f"Your cash covers {buffer:.0f} months of expenses. Everything above a 3–6 month buffer could be invested "
            "– see the investment options below.", 4)
    else:
        add("good", "🛟", "Emergency fund in place", f"Your cash covers {buffer:.1f} months of expenses.", 8)
    # 5. volatility
    if inc > 0 and person.sigma > 0.25 * inc:
        add("do", "🎢", "Your months swing a lot",
            f"Your monthly result varies by about ±{_chf(person.sigma)}. A bigger buffer (6 months) keeps you away "
            "from credit in bad months.", 4)
    # 6. credit risk in the simulation
    if m["p_ever_credit"] > 0.2:
        add("warn", "💳", "Credit risk",
            f"In {m['p_ever_credit']:.0%} of the simulated futures you would need credit at some point. "
            "A bigger buffer or lower fixed costs reduce this.", 1)
    # 7. investing: best option vs keeping cash
    cash, best = styles[0], max(styles[1:], key=lambda s: s["median"])
    gain = best["median"] - cash["median"]
    if gain > 1000 and mu > 0:
        add("do", "📈", "Let your savings work",
            f"Investing above a 3-month buffer ({best['label'].split(' ', 1)[1].lower()}) instead of keeping everything "
            f"in cash ends at a median of {_chf(best['median'])} instead of {_chf(cash['median'])} after {years} years "
            f"(+{_chf(gain)}, but with ups and downs: p5 {_chf(best['p5'])}).", 3)
    # 8. goals
    for g in res.goals:
        if g["p_reached"] < 0.5:
            gap = max(g["target"] - g["median_liquid"], 0)
            add("do", "🎯", f"Goal at risk: {GOAL_LABEL.get(g['goal'], g['goal'])}",
                f"Reached in only {g['p_reached']:.0%} of the futures. About {_chf(gap / max(g['month'], 1))} more "
                f"saved per month would close the gap of {_chf(gap)}.", 2)
    # 9. general Swiss tip (not modelled)
    if person.state == 1 and mu > 0:
        add("do", "🏦", "Pillar 3a",
            "Paying into pillar 3a lowers your taxes and builds your pension at the same time "
            "(simplified – not part of this simulation).", 6)
    tips.sort(key=lambda t: t["prio"])
    return {"tips": tips, "styles": styles, "metrics": m, "years": years}
