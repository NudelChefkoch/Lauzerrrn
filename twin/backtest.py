"""Out-of-sample backtest: does the twin's uncertainty band catch what really happened?

For every profile of the challenge data:

1. re-calibrate the model on months 1..``split`` only (``calibrate(months=split)``: mu, mu_se, sigma per person,
   seasonality a_{s,m} and noise multipliers k_{s,m} per group – nothing from the later months);
2. start from the REAL closing cash of month ``split`` and simulate months ``split+1..horizon`` with the engine's
   cash-flow model for the person's own state (step 3 of ``twin.engine.simulate``):
       X = mu + d_mu + a_{s,m} + sigma * k_{s,m} * eps,   d_mu ~ N(0, mu_se) once per path (parameter uncertainty)
   with path 0 at the point estimate, exactly like the engine;
3. compare the simulated distribution of the closing cash at month ``horizon`` with the real one.

Why not the full ``simulate``: over a few months without events the engine's market, investing and credit steps only
move money between accounts or add interest, but they would distort the comparison with the bank data – the engine
invests cash above the emergency buffer and turns a negative balance into 8 % consumer credit, while the real
accounts may simply go below zero (about 3 % of the months do). The cash-flow step is the part the data can test,
so it is re-implemented here vectorised over all profiles (one array of profiles x paths x months, < 1 s).

Only aggregated numbers are returned (coverage rates, counts, medians); no per-profile rows leave this module.
"""
from __future__ import annotations

import copy
from functools import lru_cache

import numpy as np

from .calibration import Calibration, _read, calibrate

METHOD = ("Fitted on months 1–{split} only, then {n_paths} simulated futures per person for months "
          "{a}–{horizon}, compared with the real cash balance at month {horizon}.")


def backtest(calib_or_none: Calibration | None = None, split: int = 18, horizon: int = 24, n_paths: int = 400,
             seed: int = 0, param_uncertainty: bool = True) -> dict:
    """Aggregated backtest results (see module doc).

    ``calib_or_none``: a calibration fitted on months 1..split (default: ``calibrate(months=split)``; only that
    default is cached).

    Returns ``{"n_profiles", "split", "horizon", "n_paths", "param_uncertainty", "coverage_90", "coverage_50",
    "by_status": {status: {"n", "coverage_90", "coverage_50"}}, "median_abs_error_chf", "median_abs_error_pct",
    "method"}``. ``coverage_90`` = share of profiles whose real balance lies in the simulated p5–p95 band
    (``coverage_50``: p25–p75); ``median_abs_error_chf`` = median |real − simulated median|; ``median_abs_error_pct``
    = that error relative to the median |real end balance|."""
    if calib_or_none is None:
        return copy.deepcopy(_cached(split, horizon, n_paths, seed, param_uncertainty))
    return _run(calib_or_none, split, horizon, n_paths, seed, param_uncertainty)


@lru_cache(maxsize=16)
def _cached(split: int, horizon: int, n_paths: int, seed: int, param_uncertainty: bool) -> dict:
    return _run(calibrate(months=split), split, horizon, n_paths, seed, param_uncertainty)


@lru_cache(maxsize=1)
def _balances() -> tuple[tuple[str, ...], np.ndarray, tuple[str, ...]]:
    """(profile ids, closing cash per profile x month in calendar order, the months)."""
    cb = _read("synthetic-cash-balances.csv")
    wide = cb.pivot_table(index="profile_id", columns="month", values="closing_cash_chf", aggfunc="sum")
    wide = wide.sort_index(axis=1)
    return tuple(wide.index), wide.to_numpy(dtype=float), tuple(wide.columns)


def _run(calib: Calibration, split: int, horizon: int, n_paths: int, seed: int, param_uncertainty: bool) -> dict:
    pids, closing, months = _balances()
    if not 1 <= split < horizon <= len(months):
        raise ValueError(f"need 1 <= split < horizon <= {len(months)}")
    if n_paths < 20:
        raise ValueError("n_paths must be at least 20")
    # usable profiles: calibrated, finite noise, real balances at both ends
    rows, people = [], []
    for i, pid in enumerate(pids):
        p = calib.persons.get(pid)
        if p is None or not np.isfinite(p.sigma) or not np.isfinite(closing[i, [split - 1, horizon - 1]]).all():
            continue
        rows.append(i)
        people.append(p)
    if not people:
        raise ValueError("no profiles to backtest")
    J, H = len(people), horizon - split
    cal_m = np.array([int(m[5:7]) - 1 for m in months[split:horizon]])        # calendar month index of each step
    seas = np.empty((J, H))
    mult = np.empty((J, H))
    for j, p in enumerate(people):
        sp = calib.states.get(p.group, calib.states[p.state])
        seas[j] = sp.seasonal[cal_m]
        mult[j] = sp.sigma_mult[cal_m]
    mu = np.array([p.mu for p in people])
    se = np.array([p.mu_se if np.isfinite(p.mu_se) and p.mu_se > 0 else 0.0 for p in people])
    sigma = np.array([p.sigma for p in people])
    start = closing[rows, split - 1]
    real = closing[rows, horizon - 1]

    rng = np.random.default_rng(seed)
    eps = rng.standard_normal((J, n_paths, H))
    z_mu = np.random.default_rng((int(seed), 0x6D75)).standard_normal((J, n_paths)) if param_uncertainty \
        else np.zeros((J, n_paths))
    z_mu[:, 0] = 0.0                                                             # path 0 = point estimate (engine)
    noise = np.einsum("jph,jh->jp", eps, sigma[:, None] * mult)                  # sum_h sigma * k_h * eps_h
    end = start[:, None] + H * (mu[:, None] + se[:, None] * z_mu) + seas.sum(axis=1)[:, None] + noise

    q5, q25, q50, q75, q95 = np.percentile(end, (5, 25, 50, 75, 95), axis=1)
    in90 = (real >= q5) & (real <= q95)
    in50 = (real >= q25) & (real <= q75)
    err = np.abs(real - q50)
    status = np.array([p.status for p in people])
    by_status = {str(s): {"n": int((status == s).sum()), "coverage_90": float(in90[status == s].mean()),
                     "coverage_50": float(in50[status == s].mean())}
                 for s in sorted(set(status), key=lambda s: (-(status == s).sum(), s))}
    mae = float(np.median(err))
    return {"n_profiles": J, "split": split, "horizon": horizon, "n_paths": n_paths,
            "param_uncertainty": bool(param_uncertainty),
            "coverage_90": float(in90.mean()), "coverage_50": float(in50.mean()), "by_status": by_status,
            "median_abs_error_chf": mae, "median_abs_error_pct": mae / max(float(np.median(np.abs(real))), 1.0),
            "method": METHOD.format(split=split, n_paths=n_paths, a=split + 1, horizon=horizon)}
