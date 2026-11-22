"""Part-timers stay in the EMPLOYED life state but use the seasonality / noise pooled over part_time profiles."""
from dataclasses import replace

import numpy as np
import pytest

from twin.calibration import calibrate
from twin.config import (EMPLOYED, GROUP_NAMES, PART_TIME, STATE_NAMES, Assumptions, Macro, Market, Strategy,
                         param_group)
from twin.engine import simulate
from twin.scenarios import JobChange, describe

CALIB = calibrate()
PT = next(p for p in CALIB.persons.values() if p.status == "part_time")
FLAT = Market(equity_mu=0.0, equity_sigma=0.0, jump_lambda=0.0, jump_mean=0.0, jump_sd=0.0,
              bond_mu=0.0, bond_sigma=0.0, cash_rate=0.0)
CASH_ONLY = Assumptions(market=FLAT, macro=Macro(inflation=0.0), strategy=Strategy(invest_rate=0.0))


def test_part_time_group_is_calibrated_separately():
    pt, emp = CALIB.states[PART_TIME], CALIB.states[EMPLOYED]
    assert pt.seasonal.sum() == pytest.approx(0, abs=1e-6)
    assert pt.seasonal[11] < emp.seasonal[11] / 5            # no big December bonus for part-timers
    assert pt.sigma_mult[11] < emp.sigma_mult[11]
    assert GROUP_NAMES[PART_TIME] == "part_time" and PART_TIME not in STATE_NAMES


def test_part_timer_lives_in_the_employed_state():
    assert PT.state == EMPLOYED and PT.group == PART_TIME
    assert param_group("employed", EMPLOYED) == EMPLOYED
    assert param_group("part_time", 2) == 2                    # a part-timer who lost the job: unemployed group
    res = simulate(PT, [JobChange(24, 0.1)], 5, calib=CALIB, n_paths=200)
    assert set(np.unique(res.plan.state)) == {EMPLOYED}
    assert describe(res.plan) and "employed" in describe(res.plan)[0]


def test_engine_uses_the_part_time_december():
    full = replace(PT, status="employed")
    dec = {}
    for p in (PT, full):
        cash = simulate(p, [], 2, CASH_ONLY, calib=CALIB, stochastic=False).path0["cash"]
        dec[p.status] = cash[12] - cash[11]                    # month index 11 = December
    assert dec["employed"] - dec["part_time"] == pytest.approx(
        CALIB.states[EMPLOYED].seasonal[11] - CALIB.states[PART_TIME].seasonal[11], abs=1e-6)


def test_game_hud_and_job_cards_for_a_part_timer():
    from twin.session import GameSession
    s = GameSession()
    s.start(pid=PT.profile_id, seed=1)
    p = s.payload()
    assert p["play"]["hud"]["state"] == "employed"
    cards = {c["key"]: c for c in p["play"]["cards"]}
    assert cards["switch"]["locked"] is None and cards["parttime"]["locked"] is None
    assert s.choose("parttime") and s.payload()["play"]["hud"]["state"] == "employed"
