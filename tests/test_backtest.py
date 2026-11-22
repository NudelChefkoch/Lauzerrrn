"""Out-of-sample backtest: fit on months 1..18, predict the real cash balance at month 24."""
import time

import numpy as np
import pytest

from twin import backtest as bt
from twin.backtest import backtest
from twin.backtest_view import backtest_card_html
from twin.calibration import calibrate


def test_default_calibration_unchanged_by_cutoff_option():
    full, cut = calibrate(), calibrate(months=18)
    assert full is calibrate() and full is not cut
    assert full.persons["P00001"].mu == pytest.approx(-1030.88, abs=0.01)
    assert cut.persons["P00001"].mu != pytest.approx(full.persons["P00001"].mu)
    with pytest.raises(ValueError):
        calibrate(months=6)


def test_coverage_with_parameter_uncertainty_is_calibrated():
    r = backtest()
    assert r["n_profiles"] > 1000
    assert 0.80 <= r["coverage_90"] <= 0.97
    assert 0.35 <= r["coverage_50"] <= 0.65
    assert sum(v["n"] for v in r["by_status"].values()) == r["n_profiles"]
    assert all(0.0 <= v["coverage_90"] <= 1.0 for v in r["by_status"].values())
    assert r["median_abs_error_chf"] > 0 and 0 < r["median_abs_error_pct"] < 0.2


def test_uncertainty_widens_the_band():
    on, off = backtest(), backtest(param_uncertainty=False)
    assert on["coverage_90"] > off["coverage_90"] and on["coverage_50"] > off["coverage_50"]
    assert on["median_abs_error_chf"] == pytest.approx(off["median_abs_error_chf"], rel=0.05)   # same centre


def test_only_aggregates_and_reproducible():
    r = backtest()
    assert set(r) == {"n_profiles", "split", "horizon", "n_paths", "param_uncertainty", "coverage_90",
                      "coverage_50", "by_status", "median_abs_error_chf", "median_abs_error_pct", "method"}
    r["coverage_90"] = -1                                        # callers get a copy of the cached result
    assert backtest()["coverage_90"] > 0
    assert backtest(calibrate(months=18)) == backtest()


def test_runtime_bound():
    bt._cached.cache_clear()
    t = time.perf_counter()
    backtest(split=12, seed=5)
    assert time.perf_counter() - t < 20


def test_card_html():
    html = backtest_card_html(backtest())
    assert "TWIN VS. REALITY" in html and "The 90 % band caught" in html and "real outcomes" in html
    assert "Part-time" in html and "Employed" in html and "\n" not in html.split("</style>")[-1]
    assert "<script" not in backtest_card_html({"n_profiles": 1, "coverage_90": 0.5,
                                                "by_status": {"<script>": {"n": 1, "coverage_90": 0.5}}})
