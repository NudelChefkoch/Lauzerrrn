"""Next round: graduation without a job (grad_job / gap year), skip, retire option, life to 85,
adjustable cards (child costs end at 18, house price, monthly costs), card_params action."""
import json
import time

import numpy as np
import pytest

from twin.config import EMPLOYED, RETIRED, UNEMPLOYED
from twin.engine import simulate
from twin.game import OPTION_BY_KEY, life_span
from twin.session import GameSession

STUDENT_IST = {"age": 20, "status": "student", "income": 1200, "expenses": 1800, "rent": 700, "cash": 8000,
               "portfolio": 0, "debt": 0}
WORKER_IST = {"age": 30, "status": "employed", "income": 6000, "expenses": 4000, "rent": 1500, "cash": 30000,
              "portfolio": 0, "debt": 0}


def pay(s: GameSession) -> dict:
    p = s.payload()
    json.loads(json.dumps(p, allow_nan=False))          # plain, JSON-serialisable, no NaN
    return p


def card(p: dict, key: str) -> dict:
    return next(c for c in p["play"]["cards"] if c["key"] == key)


def kinds(p: dict, block: str = "play") -> list[str]:
    return [a["type"] for a in p[block]["world"]["anims"]]


def graduate(seed: int = 1) -> GameSession:
    """Bachelor from 20: the degree is finished at the 3rd station (age 23)."""
    s = GameSession()
    s.start(STUDENT_IST, None, seed=seed)
    assert card(pay(s), "grad_job")["locked"] == "Finish a degree first"
    assert s.choose("bachelor")
    assert card(pay(s), "grad_job")["locked"] == "You are studying right now"
    assert s.choose("stay") and s.choose("stay")
    return s


# ---------------------------------------------------------------- 1. graduation, then job or gap year
def test_degree_only_graduates_then_player_picks_the_job():
    s = graduate()
    p = pay(s)
    assert kinds(p) == ["graduation"]                                    # no automatic "job" anim any more
    hud = p["play"]["hud"]
    assert hud["state"] == "graduated · looking" and hud["income"] == 0
    gj = card(p, "grad_job")
    assert gj["locked"] is None and gj["emoji"] == "💼" and gj["cat"] == "career"
    assert gj["title"] == "Job after your degree" and "5'200" in gj["text"]
    assert card(p, "gap_year")["locked"] is None
    assert s.choose("grad_job")
    p = pay(s)
    assert p["play"]["world"]["anims"] == [{"id": p["play"]["world"]["anims"][0]["id"], "type": "job",
                                           "label": "First job!"}]
    assert p["play"]["hud"]["state"] == "employed" and p["play"]["hud"]["income"] > 5000
    assert card(p, "grad_job")["locked"] == "You already have a job"


def test_gap_year_after_the_degree_keeps_looking():
    s = graduate()
    pay(s)
    m0 = s.month_at(s.turn)
    assert s.choose("gap_year")
    p = pay(s)
    assert [(a["type"], a["label"]) for a in p["play"]["world"]["anims"]] == [("gapyear", "Gap year")]
    plan = s._res().plan
    assert np.all(plan.income[m0:m0 + 24] == 0) and np.all(plan.state[m0:m0 + 24] == UNEMPLOYED)
    assert not plan.alv_applies[m0:m0 + 24].any()                        # no unemployment benefits
    assert card(p, "grad_job")["locked"] is None                         # still looking: job still available
    assert s.choose("grad_job")
    assert kinds(pay(s)) == ["job"]


def test_master_degree_job_pays_more():
    s = graduate()
    assert s.choose("master")
    assert s.choose("stay")
    p = pay(s)
    assert kinds(p) == ["graduation"] and "6'300" in card(p, "grad_job")["text"]


def test_master_after_a_bachelor_job_still_gets_the_master_job():
    s = graduate()
    assert s.choose("grad_job") and s.choose("master")
    assert s.choose("stay")
    p = pay(s)
    assert p["play"]["hud"]["state"] == "graduated · looking"
    assert card(p, "grad_job")["locked"] is None and "6'300" in card(p, "grad_job")["text"]
    assert s.choose("grad_job") and pay(s)["play"]["hud"]["income"] > 6300


def test_house_lock_matches_the_engine_purchase():
    """An unlocked "Buy a home" card is a purchase that really happens in the played life (price level + fees)."""
    for seed in (0, 2):
        s = GameSession()
        s.start(WORKER_IST, None, seed=seed)
        s.set_params("buy_house", {"price": 2_000_000})
        for _ in range(40):
            if card(pay(s), "buy_house")["locked"] is None:
                break
            assert s.skip(1)
        assert card(pay(s), "buy_house")["locked"] is None
        assert s.choose("buy_house")
        m = s.month_at(s.turn)
        assert s._res(m).path0["house_equity"][m] > 0


def test_gap_year_when_employed_keeps_the_job():
    s = GameSession()
    s.start(WORKER_IST, None, seed=2)
    assert s.choose("gap_year")
    p = pay(s)
    assert kinds(p) == ["gapyear"]
    plan = s._res().plan
    assert np.all(plan.income[:12] == 0) and plan.income[12] == pytest.approx(6000)
    assert plan.state[12] == EMPLOYED and p["play"]["hud"]["state"] == "employed"


def test_time_off_offers_only_the_gap_year():
    s = GameSession()
    s.start(WORKER_IST, None, seed=2)
    keys = {c["key"] for c in pay(s)["play"]["cards"]}
    assert not keys & {"travel", "sabbatical3", "sabbatical12"}
    gy = card(pay(s), "gap_year")
    assert (gy["cat"], gy["emoji"], gy["title"], gy["text"]) == ("timeoff", "🎒", "Gap year", "12 months off without pay")


# ---------------------------------------------------------------- 2. skip
def test_skip_years_equals_driving_on_station_by_station():
    a, b = GameSession(), GameSession()
    a.start(WORKER_IST, None, seed=4)
    b.start(WORKER_IST, None, seed=4)
    seq = pay(a)["seq"]
    a.handle({"action": "skip", "years": 5, "nonce": 1})
    a.handle({"action": "skip", "years": 5, "nonce": 1})                 # duplicate nonce: ignored
    for _ in range(5):
        assert b.choose("stay")
    pa, pb = pay(a), pay(b)
    assert pa["seq"] == seq + 1
    w = pa["play"]["world"]
    assert (w["turn"], w["prev_turn"], w["skipped"]) == (5, 0, 5) and pa["play"]["turn"] == 5
    assert pb["play"]["world"]["skipped"] == 0
    since = ("net_worth_prev", "prev_age")             # "Where you stand": change since the last stop
    ha, hb = pa["play"]["hud"], pb["play"]["hud"]
    assert {k: v for k, v in ha.items() if k not in since} == {k: v for k, v in hb.items() if k not in since}
    assert ha["prev_age"] == 30 and hb["prev_age"] == 34 and len(pa["play"]["history"]) == 5
    assert ha["net_worth_prev"] == 30000                 # the skip started at the status quo
    assert pa["play"]["fan"] == pb["play"]["fan"]


def test_skip_until_next_event_stops_at_the_degree():
    s = GameSession()
    s.start(STUDENT_IST, None, seed=1)
    assert s.choose("bachelor")
    s.handle({"action": "skip", "until": "event", "nonce": 1})
    p = pay(s)
    w = p["play"]["world"]
    assert (w["prev_turn"], w["turn"], w["skipped"]) == (1, 3, 2)
    assert [(a["type"], a.get("brief")) for a in w["anims"]] == [("graduation", True)]
    # nothing planned: stops after 10 years
    s.handle({"action": "skip", "until": "event", "nonce": 2})
    assert pay(s)["play"]["world"]["skipped"] == 10


def test_skip_stops_at_the_end_of_life_and_menu_shrinks():
    s = GameSession()
    s.start({**WORKER_IST, "age": 70}, None, seed=3)                     # oldest start age: 15 stations
    p = pay(s)
    assert p["play"]["K"] == 15 and len(p["play"]["skip"]) == 3
    s.handle({"action": "skip", "years": 8, "nonce": 1})
    p = pay(s)
    assert p["play"]["skip"] == [{"years": 5, "label": "+5 years"}, {"until": "event", "label": "Next event"}]
    s.handle({"action": "skip", "years": 10, "nonce": 2})                # clipped to the remaining 7 years
    p = pay(s)
    assert p["phase"] == "end" and s.turn == 15 and p["end"]["summary"]["age_end"] == 85
    assert p["end"]["world"]["skipped"] == 7
    seq = p["seq"]
    s.handle({"action": "skip", "years": 5, "nonce": 3})                 # game over: rejected, seq still bumps
    assert pay(s)["seq"] == seq + 1 and s.turn == 15
    s2 = GameSession()
    s2.start(WORKER_IST, None, seed=3)
    s2.handle({"action": "skip", "years": 0, "nonce": 1})
    assert s2.turn == 0


# ---------------------------------------------------------------- 3. retire as an option, life to 85
def test_retire_option_from_60_then_play_on_to_85():
    s = GameSession()
    s.start({**WORKER_IST, "age": 55}, None, seed=5)
    p = pay(s)
    r = card(p, "retire")
    assert (r["cat"], r["emoji"], r["title"], r["locked"]) == ("career", "🪑", "Retire", "From age 60")
    s.handle({"action": "skip", "years": 5, "nonce": 1})
    p = pay(s)
    assert p["play"]["age"] == 60 and card(p, "retire")["locked"] is None
    m0 = s.month_at(s.turn)
    last = float(s._res().plan.income[m0 - 1])
    assert s.choose("retire")
    p = pay(s)
    assert p["phase"] == "play"                                          # the game continues
    assert [(a["type"], a["label"]) for a in p["play"]["world"]["anims"]] == [("retirement", "Retired!")]
    plan = s._res().plan
    assert plan.income[m0] == pytest.approx(0.6 * last) and np.all(plan.state[m0:] == RETIRED)
    assert p["play"]["hud"]["state"] == "retired"
    assert card(p, "retire")["locked"] == "Already retired"
    assert card(p, "switch")["locked"] and card(p, "job_start")["locked"] == "You are retired"
    labels = [l for _, l in plan.labels]
    assert "Retirement" not in labels                                    # no forced retirement any more
    while s.phase == "play":
        s.skip(10)
    p = pay(s)
    assert p["end"]["summary"]["age_end"] == 85 and p["end"]["world"]["finale"] is True


def test_forced_retirement_at_70():
    s = GameSession()
    s.start({**WORKER_IST, "age": 62}, None, seed=6)
    s.handle({"action": "skip", "until": "event", "nonce": 1})
    p = pay(s)
    assert p["play"]["age"] == 70
    assert [(a["type"], a["label"]) for a in p["play"]["world"]["anims"]] == [("retirement", "Retirement")]
    assert p["play"]["hud"]["state"] == "retired" and card(p, "retire")["locked"] == "Already retired"


def test_engine_horizon_70_years():
    assert life_span(15) == (1, 70, 70) and life_span(84) == (1, 1, 1)
    with pytest.raises(ValueError):
        simulate("P00001", [], 71, n_paths=5)


# ---------------------------------------------------------------- 4. child costs end at 18
def test_child_costs_adjustable_and_end_after_216_months():
    s = GameSession()
    s.start(WORKER_IST, None, seed=7)
    c = card(pay(s), "child")
    assert c["params"]["cost"] == {"label": "Cost per month", "min": 300, "max": 3000, "step": 100,
                                   "default": 1100, "unit": "CHF", "value": 1100}
    s.handle({"action": "choose", "key": "child", "params": {"cost": 1500}, "nonce": 1})
    assert s.turn == 1 and kinds(pay(s)) == ["child"]
    plan = s._res().plan
    assert np.all(plan.extra_expenses[:216] == 1500) and np.all(plan.extra_expenses[216:] == 0)
    assert card(pay(s), "child")["params"]["cost"]["value"] == 1500      # remembered for the next child
    s.handle({"action": "skip", "years": 10, "nonce": 2})
    assert "child_leaves" not in kinds(pay(s))
    s.handle({"action": "skip", "until": "event", "nonce": 3})
    p = pay(s)
    assert p["play"]["turn"] == 18
    assert [(a["type"], a["label"]) for a in p["play"]["world"]["anims"]] == \
        [("child_leaves", "Your child moves out")]


# ---------------------------------------------------------------- 5. house price
def test_house_price_changes_lock_preview_and_text():
    s = GameSession()
    s.start({**WORKER_IST, "cash": 150_000}, None, seed=8)
    h = card(pay(s), "buy_house")
    assert h["params"]["price"]["value"] == 850_000 and h["locked"].startswith("Down payment missing")
    seq = pay(s)["seq"]
    s.handle({"action": "card_params", "key": "buy_house", "params": {"price": 600_000}, "nonce": 1})
    p = pay(s)
    h = card(p, "buy_house")
    assert p["seq"] == seq + 1 and h["locked"] is None and isinstance(h["median"], float)
    assert "600'000" in h["text"] and h["params"]["price"]["value"] == 600_000
    s.handle({"action": "card_params", "key": "buy_house", "params": {"price": 1_000_000}, "nonce": 2})
    h2 = card(pay(s), "buy_house")
    assert h2["locked"] is not None and h2["median"] is None
    # clamped / snapped to min, max and step
    s.handle({"action": "card_params", "key": "buy_house", "params": {"price": 777_777}, "nonce": 3})
    assert card(pay(s), "buy_house")["params"]["price"]["value"] == 800_000
    s.handle({"action": "card_params", "key": "buy_house", "params": {"price": 5}, "nonce": 4})
    assert card(pay(s), "buy_house")["params"]["price"]["value"] == 400_000
    # choose with explicit params: the price is used
    s.handle({"action": "choose", "key": "buy_house", "params": {"price": 550_000}, "nonce": 5})
    assert [h.price for h in s._res().plan.houses] == [550_000]


def test_card_params_bumps_seq_and_is_deduped_by_nonce():
    s = GameSession()
    s.start(WORKER_IST, None, seed=9)
    seq = pay(s)["seq"]
    msg = {"action": "card_params", "key": "costs", "params": {"delta": -500}, "nonce": 11}
    s.handle(msg)
    s.handle(msg)
    assert pay(s)["seq"] == seq + 1
    s.handle({"action": "card_params", "key": "nope", "params": {"x": 1}, "nonce": 12})   # unknown: seq still bumps
    assert pay(s)["seq"] == seq + 2 and s.turn == 0


# ---------------------------------------------------------------- 6. monthly costs
def test_costs_card_changes_expenses_from_now_on():
    s = GameSession()
    s.start(WORKER_IST, None, seed=10)
    c = card(pay(s), "costs")
    assert (c["cat"], c["emoji"], c["title"]) == ("housing", "🧾", "Adjust monthly costs")
    assert c["params"]["delta"]["default"] == -300 and c["params"]["delta"]["value"] == -300
    assert s.choose("stay")
    m0 = s.month_at(s.turn)
    s.handle({"action": "card_params", "key": "costs", "params": {"delta": -500}, "nonce": 1})
    assert "−CHF 500" in card(pay(s), "costs")["text"]
    s.handle({"action": "choose", "key": "costs", "nonce": 2})          # stored value is used
    plan = s._res().plan
    assert np.all(plan.extra_expenses[:m0] == 0) and np.all(plan.extra_expenses[m0:] == -500)
    assert card(pay(s), "costs")["locked"] is None                        # can be adjusted again (once=False)
    s.handle({"action": "card_params", "key": "costs", "params": {"delta": -2000}, "nonce": 3})
    s.handle({"action": "card_params", "key": "costs", "params": {"delta": -2000}, "nonce": 4})
    s2 = GameSession()
    s2.start({**WORKER_IST, "expenses": 2000, "rent": 900}, None, seed=10)
    s2.set_params("costs", {"delta": -1600})
    assert card(pay(s2), "costs")["locked"].startswith("Costs can't go below")


# ---------------------------------------------------------------- runtime
def test_a_full_life_stays_responsive():
    s = GameSession()
    s.start(STUDENT_IST, None, seed=11)
    pay(s)
    worst = 0.0
    for key in ["bachelor", "stay", "stay", "grad_job", "stay", "child", "stay"]:
        t = time.perf_counter()
        assert s.choose(key)
        pay(s)
        worst = max(worst, time.perf_counter() - t)
    t = time.perf_counter()
    s.skip(10)
    pay(s)
    worst = max(worst, time.perf_counter() - t)
    assert worst < 2.5, worst                                            # ~0.5 s on a laptop; generous for CI


def test_option_values_fallbacks():
    house = OPTION_BY_KEY["buy_house"]
    assert house.values() == {"price": 850_000}
    assert house.values({"price": "abc"}) == {"price": 850_000}
    assert house.values({"price": float("nan")}) == {"price": 850_000}
    assert OPTION_BY_KEY["costs"].values({"delta": 99_999}) == {"delta": 2000}


# ---------------------------------------------------------------- integration: world.life + anim turn + snapping
def test_world_life_kids_home_retired_and_skip_anim_turn():
    s = GameSession()
    s.start({**WORKER_IST, "age": 44}, None, seed=8)
    assert s.choose("child")
    life = pay(s)["play"]["world"]["life"]
    assert (life["kids"], life["kids_home"], life["retired"]) == (1, 1, False)
    s.handle({"action": "skip", "years": 18, "nonce": 1})          # the child moves out at station 18 (age 62)
    w = pay(s)["play"]["world"]
    leave = [a for a in w["anims"] if a["type"] == "child_leaves"]
    assert len(leave) == 1 and leave[0]["turn"] == 18 and leave[0]["brief"] is True
    assert all(w["prev_turn"] < a["turn"] <= w["turn"] for a in w["anims"])
    assert (w["life"]["kids"], w["life"]["kids_home"]) == (1, 0)
    assert s.choose("retire")
    assert pay(s)["play"]["world"]["life"]["retired"] is True


def test_param_snapping_rounds_half_up_like_the_client():
    spec = OPTION_BY_KEY["child"].params["cost"]
    assert spec.snap(1750) == 1800 and spec.snap(1749) == 1700 and spec.snap(10_000) == 3000
    assert OPTION_BY_KEY["costs"].params["delta"].snap(-450) == -400


# ---------------------------------------------------------------- browser findings (preview sanity)
def test_degree_previews_assume_the_degree_job():
    """Without a job after the degree the preview would price in 'never work again' (−38 M at 85)."""
    from twin.session import GameSession
    s = GameSession()
    s.start(pid="P00004", seed=1)
    cards = {c["key"]: c for c in s.payload()["play"]["cards"]}
    assert cards["bachelor"]["median"] > 0 and cards["lehre"]["median"] > 0
    s.choose("bachelor")
    s.skip(until="event")
    cards = {c["key"]: c for c in s.payload()["play"]["cards"]}
    assert cards["grad_job"]["locked"] is None and abs(cards["grad_job"]["delta"]) < 1e-6   # stay assumes the job too
    assert cards["gap_year"]["delta"] < 0                                                    # a year without pay costs


def test_employed_start_has_career_growth_like_a_new_job():
    """An employed starter must not lose salary growth by staying (a gap year used to look like +8.7 M)."""
    from twin.session import GameSession
    s = GameSession()
    s.start(pid="P00004", seed=1)
    cards = {c["key"]: c for c in s.payload()["play"]["cards"]}
    assert cards["gap_year"]["delta"] < 0 and cards["switch"]["delta"] > 0
