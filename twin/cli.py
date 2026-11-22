"""Quick terminal run:  python -m twin.cli P00001 master --years 10 --market standard --strategy ausgewogen"""
from __future__ import annotations

import argparse

from .calibration import calibrate
from .config import MARKET_PRESETS, STRATEGY_PRESETS, Assumptions, Shocks
from .engine import simulate
from .scenarios import PRESETS, describe, preset


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile", nargs="?", default="P00001")
    ap.add_argument("scenario", nargs="?", default="master", choices=PRESETS)
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--market", default="standard", choices=list(MARKET_PRESETS))
    ap.add_argument("--strategy", default="ausgewogen", choices=list(STRATEGY_PRESETS))
    ap.add_argument("--job-loss", type=float, default=0.0, help="random job loss per year, e.g. 0.025")
    ap.add_argument("--paths", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    calib = calibrate()
    person = calib.persons[args.profile]
    a = Assumptions(market=MARKET_PRESETS[args.market], strategy=STRATEGY_PRESETS[args.strategy],
                    shocks=Shocks(job_loss_per_year=args.job_loss))
    res = simulate(person, preset(args.scenario, person), args.years, a, args.paths, args.seed, calib=calib)

    print(f"{person.name} ({person.profile_id}), {person.age} y, {person.status}; "
          f"Cash {person.cash:,.0f}, Portfolio {person.portfolio:,.0f}, debt {person.debt:,.0f}")
    print(f"Scenario '{args.scenario}', {args.years} years, market '{args.market}', strategy '{args.strategy}'")
    for line in describe(res.plan):
        print("  " + line)
    print("\nNet worth (CHF) at year end:  P5 / P50 / P95")
    nw = res.percentiles["net_worth"]
    for y in range(1, args.years + 1):
        t = 12 * y
        print(f"  Year {y:2d}: {nw[0, t]:>12,.0f} {nw[2, t]:>12,.0f} {nw[4, t]:>12,.0f}")
    print("\nMetrics:")
    for k, v in res.metrics.items():
        print(f"  {k:28s} {v:>14,.3f}")
    for g in res.goals:
        print(f"  Goal '{g['goal']}' ({g['target']:,.0f} CHF, month {g['month']}): "
              f"P = {g['p_reached']:.0%}, median liquid {g['median_liquid']:,.0f}")
    print(f"\nAccounting check (max. deviation): {res.identity_error:.2e} CHF")


if __name__ == "__main__":
    main()
