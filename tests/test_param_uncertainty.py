"""Parameter uncertainty: every Monte Carlo path draws its own mean flow mu_path ~ N(mu, mu_se)."""
from dataclasses import replace

import numpy as np

from twin.calibration import calibrate
from twin.config import Assumptions, Macro
from twin.engine import simulate
from twin.scenarios import Job

CALIB = calibrate()
PERSON = CALIB.persons["P00004"]
ON = Assumptions()
OFF = Assumptions(macro=Macro(param_uncertainty=False))


def run(a, **kw):
    kw = {"years": 10, "n_paths": 600, "seed": 3, "n_samples": 600, **kw}
    return simulate(PERSON, kw.pop("events", []), a=a, calib=CALIB, **kw)


def test_default_is_on_and_mu_se_is_positive():
    assert Assumptions().macro.param_uncertainty is True
    assert PERSON.mu_se > 0


def test_same_seed_is_reproducible():
    r1, r2 = run(ON), run(ON)
    np.testing.assert_array_equal(r1.samples, r2.samples)
    assert r1.metrics == r2.metrics


def test_played_life_path0_unchanged():
    on, off = run(ON, fixed_until=36), run(OFF, fixed_until=36)
    for s in ("cash", "portfolio", "net_worth"):
        np.testing.assert_array_equal(on.path0[s], off.path0[s])


def test_shared_past_stays_identical():
    k = 48
    res = run(ON, fixed_until=k)
    past = res.samples[:, :k + 1]
    np.testing.assert_array_equal(past, np.broadcast_to(res.path0["net_worth"][:k + 1], past.shape))
    assert np.ptp(res.samples[:, -1]) > 0                       # the future fans out again


def test_band_is_wider_than_without():
    on, off = run(ON), run(OFF)
    for s in ("net_worth", "liquid"):
        w_on = on.percentiles[s][4, -1] - on.percentiles[s][0, -1]
        w_off = off.percentiles[s][4, -1] - off.percentiles[s][0, -1]
        assert w_on > w_off
    assert on.identity_error < 1e-6


def test_common_random_numbers_with_and_without_an_event():
    """The mu draws come from their own stream: an event changes the plan, not the random numbers."""
    base, job = run(ON), run(ON, events=[Job(start=12, salary=PERSON.income + 500)])
    np.testing.assert_array_equal(base.path0["net_worth"][:13], job.path0["net_worth"][:13])
    assert job.metrics["median_net_worth_end"] > base.metrics["median_net_worth_end"]


def test_off_without_mu_se_is_the_point_estimate():
    no_se = replace(PERSON, mu_se=0.0)
    a = simulate(no_se, [], 5, ON, 300, 1, calib=CALIB)
    b = simulate(PERSON, [], 5, OFF, 300, 1, calib=CALIB)
    assert a.metrics == b.metrics


def test_shared_past_identical_in_every_account_series():
    """Under fixed_until, every account series (not only net worth) is the same on all paths up to month k, even with
    parameter uncertainty, an event in the past, random job loss and a part-timer's own seasonality group."""
    k = 60
    pt = next(p for p in CALIB.persons.values() if p.status == "part_time")
    for person in (PERSON, pt):
        res = simulate(person, [Job(start=24, salary=person.income + 400)], 10, ON, 500, 11, calib=CALIB,
                       fixed_until=k, n_samples=500)
        for s in ("cash", "portfolio", "debt", "liquid", "net_worth"):
            band = res.percentiles[s][:, :k + 1]                  # p5..p95 per month
            np.testing.assert_array_equal(band, np.broadcast_to(res.path0[s][:k + 1], band.shape))
            np.testing.assert_allclose(res.mean[s][:k + 1], res.path0[s][:k + 1], rtol=1e-12, atol=1e-6)
        assert res.percentiles["net_worth"][4, -1] > res.percentiles["net_worth"][0, -1]   # fans out afterwards
