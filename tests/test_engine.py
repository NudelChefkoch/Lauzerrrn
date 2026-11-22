"""Validation checks for the judges' question "how did you verify the calculations?"."""
from dataclasses import replace

import numpy as np
import pytest

from twin.calibration import calibrate
from twin.config import Assumptions, Macro, Market, Shocks, Strategy
from twin.engine import simulate
from twin.scenarios import HouseBuy, Job, OneOff, Study, Unemployment, preset

CALIB = calibrate()
ALEXIA = CALIB.persons["P00001"]
NO_MACRO = Macro(inflation=0.0, career_growth=0.0)
FLAT = Market(equity_mu=0.0, equity_sigma=0.0, jump_lambda=0.0, jump_mean=0.0, jump_sd=0.0,
              bond_mu=0.0, bond_sigma=0.0, cash_rate=0.0)


def run(person=ALEXIA, events=(), years=5, a=None, **kw):
    return simulate(person, list(events), years, a or Assumptions(), calib=CALIB, **kw)


# ---------------------------------------------------------------- calibration
def test_calibration_alexia_matches_data_analysis():
    assert ALEXIA.mu == pytest.approx(-1030.88, abs=0.01)
    assert ALEXIA.expenses == pytest.approx(ALEXIA.income - ALEXIA.mu)
    for s in CALIB.states.values():
        assert s.seasonal.sum() == pytest.approx(0, abs=1e-6)


# ---------------------------------------------------------------- accounting
@pytest.mark.parametrize("name", ["basis", "master", "jobverlust", "startup", "hauskauf"])
def test_net_worth_identity_every_path(name):
    a = Assumptions(shocks=Shocks(job_loss_per_year=0.05))
    res = run(events=preset(name, ALEXIA), years=10, a=a, n_paths=500)
    assert res.identity_error < 1e-6


def test_deterministic_cash_only_closed_form():
    """No noise, no inflation, no market: cash path is linear in the mean flow."""
    a = Assumptions(market=FLAT, macro=NO_MACRO, strategy=Strategy(invest_rate=0.0))
    rich = replace(ALEXIA, cash=1e6)              # never hits the shortfall rule
    res = run(rich, years=2, a=a, stochastic=False)
    cash = res.percentiles["cash"][2]
    seas = CALIB.states[ALEXIA.state].seasonal
    expected = 1e6 + np.concatenate([[0], np.cumsum([ALEXIA.mu + seas[t % 12] for t in range(24)])])
    np.testing.assert_allclose(cash, expected, atol=1e-6)


def test_seed_reproducible_and_seed_sensitive():
    r1, r2, r3 = (run(n_paths=200, seed=s) for s in (1, 1, 2))
    np.testing.assert_array_equal(r1.percentiles["net_worth"], r2.percentiles["net_worth"])
    assert not np.array_equal(r1.percentiles["net_worth"], r3.percentiles["net_worth"])


def test_investing_does_not_change_net_worth_without_returns():
    a0 = Assumptions(market=FLAT, macro=NO_MACRO, strategy=Strategy(invest_rate=0.0))
    a1 = a0.with_(strategy=Strategy(invest_rate=1.0))
    rich = replace(ALEXIA, cash=200_000, expenses=500)
    n0 = run(rich, a=a0, stochastic=False).percentiles["net_worth"][2]
    r1 = run(rich, a=a1, stochastic=False)
    np.testing.assert_allclose(r1.percentiles["net_worth"][2], n0, atol=1e-6)
    assert r1.percentiles["portfolio"][2, -1] > 0


# ---------------------------------------------------------------- policies
def test_shortfall_order_sell_before_credit():
    a = Assumptions(market=FLAT, macro=NO_MACRO)
    p = replace(ALEXIA, cash=0, portfolio=5000)
    res = run(p, years=1, a=a, stochastic=False)
    port, debt = res.percentiles["portfolio"][2], res.percentiles["debt"][2]
    first_credit = np.argmax(debt > 0)
    assert port[first_credit] == pytest.approx(0, abs=1e-6)   # portfolio gone before any credit
    assert port[1] < 5000                                     # sold in month 1


def test_spending_cut_reduces_burn():
    a_cut = Assumptions(market=FLAT, macro=NO_MACRO)
    a_no = a_cut.with_(shortfall=replace(a_cut.shortfall, spending_cut=0.0))
    p = replace(ALEXIA, cash=0)
    d_cut = run(p, years=2, a=a_cut, stochastic=False).percentiles["debt"][2, -1]
    d_no = run(p, years=2, a=a_no, stochastic=False).percentiles["debt"][2, -1]
    assert d_cut < d_no


def test_alv_runs_out_after_max_months():
    a = Assumptions(market=FLAT, macro=NO_MACRO)
    ev = [Job(start=0, salary=5000), Unemployment(start=1, months=15)]
    res = run(events=ev, years=2, a=a, stochastic=False)
    assert res.metrics["p_alv_exhausted"] == 1.0


def test_house_purchase_fails_without_equity():
    ev = [HouseBuy(start=1, price=1_000_000)]
    res = run(events=ev, years=1, n_paths=100)
    assert res.metrics["p_house_failed"] == 1.0
    assert res.percentiles["house_equity"].max() == 0


def test_house_purchase_affordability_flag():
    rich = replace(ALEXIA, cash=400_000)
    ok = run(rich, [Job(0, salary=15_000), HouseBuy(1, 600_000)], years=2, n_paths=50)
    bad = run(rich, [Job(0, salary=4_000), HouseBuy(1, 600_000)], years=2, n_paths=50)
    assert ok.metrics["p_house_failed"] == 0 and ok.metrics["p_house_unaffordable"] == 0
    assert bad.metrics["p_house_unaffordable"] == 1.0


def test_one_off_cost_lowers_net_worth_by_its_amount():
    a = Assumptions(market=FLAT, macro=NO_MACRO, strategy=Strategy(invest_rate=0.0))
    rich = replace(ALEXIA, cash=1e6)
    base = run(rich, years=1, a=a, stochastic=False).percentiles["net_worth"][2, -1]
    hit = run(rich, [OneOff(3, 7000)], years=1, a=a, stochastic=False).percentiles["net_worth"][2, -1]
    assert base - hit == pytest.approx(7000, abs=1e-6)


def test_study_then_job_switches_state_and_tuition():
    ev = [Study(start=0, months=12, tuition_per_year=12_000, salary_after=6000)]
    res = run(events=ev, years=2, n_paths=10)
    assert res.plan.extra_cost[:12].sum() == pytest.approx(12_000)
    assert res.plan.income[12] == pytest.approx(6000)


def test_random_job_loss_hurts_on_average():
    ev = [Job(start=0, salary=5000)]
    safe = run(events=ev, years=10, n_paths=2000).metrics["median_net_worth_end"]
    risky = run(events=ev, years=10, n_paths=2000,
                a=Assumptions(shocks=Shocks(job_loss_per_year=0.10))).metrics["median_net_worth_end"]
    assert risky < safe


def test_horizon_limits():
    with pytest.raises(ValueError):
        run(years=51)
    run(years=1, n_paths=10)
    run(years=45, n_paths=10)          # a 20-year-old's road to retirement at 65


def test_market_mean_matches_expected_return():
    """Monte Carlo mean growth of an all-equity portfolio ~ (1+mu)^T (Merton drift compensation)."""
    from twin.engine import _market_draws
    rng = np.random.default_rng(0)
    eq, _ = _market_draws(rng, Assumptions(), (120, 200_000), True)
    growth = np.exp(eq.sum(axis=0)).mean()
    assert growth == pytest.approx(1.06 ** 10, rel=0.02)


def test_conditional_future_shares_realised_past():
    """fixed_until: all paths equal path 0 up to that month; path 0 is unchanged by later decisions."""
    from twin.scenarios import JobChange
    ev = [Job(start=0, salary=5000)]
    full = run(events=ev, years=3, n_paths=300, seed=3)
    cond = run(events=ev, years=3, n_paths=300, seed=3, fixed_until=12)
    p = cond.percentiles["net_worth"]
    np.testing.assert_allclose(p[0, :13], p[4, :13])                         # no spread in the past
    np.testing.assert_allclose(cond.path0["net_worth"], full.path0["net_worth"])
    later = run(events=ev + [JobChange(18, 0.5)], years=3, n_paths=300, seed=3, fixed_until=12)
    np.testing.assert_allclose(later.path0["net_worth"][:19], full.path0["net_worth"][:19])
    assert p[4, -1] > p[0, -1]                                               # spread in the future


def test_game_locks_and_animations():
    from twin.game import Ctx, Snapshot, animations, available, finished_degrees, preview
    from twin.scenarios import build_plan
    snap = Snapshot(0, 0, 1200, 8000, 0, 0, 8000, 8000)
    opts = dict((o.key, r) for o, r in available(Ctx(snap, frozenset(), 20, 0, frozenset())))
    assert opts["bachelor"] is None and opts["master"] == "Finish a bachelor first"
    assert opts["buy_house"] is not None and opts["child"] == "From age 22"
    plan = build_plan(ALEXIA, [Study(0, 36, 1500, None, 5200, 800, "Bachelor", "Bachelor's degree")], 60, CALIB, Assumptions())
    assert finished_degrees(plan, 35) == frozenset() and finished_degrees(plan, 36) == {"bachelor"}
    played = set()
    kinds = [a["type"] for a in animations(plan, 24, 36, 3, played)]   # graduation lands on the arrival month
    assert kinds == ["graduation", "job"]
    assert animations(plan, 36, 48, 4, played) == []                     # ...and is not played twice
