"""GameSession: payload contract (CONTRACT.md) over a full playthrough."""
import json
import re

from twin.session import GameSession

CARD_KEYS = {"key", "cat", "emoji", "title", "text", "locked", "impact", "delta", "median", "p5", "p95", "credit"}
PREVIEW_KEYS = ("delta", "median", "p5", "p95", "credit")
HUD_KEYS = {"name", "age", "net_worth", "cash", "portfolio", "debt", "income", "state",
            "net_worth_prev", "prev_age", "expenses", "health"}
SUMMARY_KEYS = {"name", "age_end", "score", "stars", "percentile", "decisions", "choices"}
IST = {"age": 27, "status": "employed", "income": 6000, "expenses": 4700, "rent": 1600, "cash": 12000,
       "portfolio": 8000, "debt": 0}
FACT_KEYS = {"net_worth", "percentile", "p5", "p95", "lazy_median", "cash", "portfolio", "house_equity", "debt",
             "max_credit", "months_with_credit", "decisions", "best", "fan", "disclaimer"}
AVATAR = {"name": "Testi", "gender": "mann", "skin": "oliv", "hair": "kurz", "hairColor": "blond", "hat": "cap",
          "outfit": "tshirt", "color": "gruen", "car": "rot"}


def check(p: dict) -> dict:
    json.loads(json.dumps(p, allow_nan=False))          # plain, JSON-serialisable, no NaN
    assert p["phase"] in ("boot", "play", "end", "ride")
    boot = p["boot"]
    assert "profiles" not in boot and "risks" not in boot          # own data first, exactly ONE example
    assert boot["example"]["ist"]["basis"] == boot["example"]["id"] and boot["retire_age"] == 65
    assert boot["end_age"] == 85 and boot["retire_from"] == 60 and boot["forced_retire_age"] == 70
    assert {s["key"] for s in boot["statuses"]} >= {"student", "employed"}
    assert not re.search(r"\"(xp|level|rarity|joy|joy_emoji|achievements|new_achievements)\"|_de\"", json.dumps(p))
    assert p["height"] > 0 and isinstance(p["seq"], int) and isinstance(p["avatar"], dict)
    if p["phase"] == "play":
        pl = p["play"]
        assert HUD_KEYS <= set(pl["hud"]) and pl["end_age"] == 85 and pl["step"] == 1
        assert pl["hud"]["health"] in ("ok", "thin", "credit") and pl["hud"]["expenses"] > 0
        assert (pl["hud"]["net_worth_prev"] is None) == (pl["turn"] == 0) == (pl["hud"]["prev_age"] is None)
        assert pl["age"] == min(pl["start_age"] + pl["turn"] * pl["step"], 85)
        assert len(pl["categories"]) == 5
        cat_keys = {c["key"] for c in pl["categories"]}
        assert cat_keys == {"education", "career", "housing", "family", "timeoff"}    # money: analysis only
        for card in pl["cards"]:
            assert CARD_KEYS <= set(card) and card["cat"] in cat_keys
            if card["locked"] is not None:
                assert all(card[k] is None for k in PREVIEW_KEYS) and card["impact"] is None, card
            else:
                assert all(isinstance(card[k], float) for k in PREVIEW_KEYS), card
                # the card shows only an arrow: green ▲ better, red ▼ worse, grey ● about the same
                assert card["impact"] in ("up", "down", "flat"), card
                assert {"up": card["delta"] > 0, "down": card["delta"] < 0,
                        "flat": abs(card["delta"]) < 20_000}[card["impact"]], card
            for name, prm in card.get("params", {}).items():
                assert set(prm) == {"label", "min", "max", "step", "default", "unit", "value"}, (name, prm)
                assert prm["min"] <= prm["value"] <= prm["max"] and (prm["value"] - prm["min"]) % prm["step"] == 0
        left = pl["K"] - pl["turn"]
        assert pl["skip"][-1] == {"until": "event", "label": "Next event"}
        assert all(e["years"] <= left for e in pl["skip"] if "years" in e)
        for c in pl["categories"]:
            assert c["open"] == sum(1 for x in pl["cards"] if x["cat"] == c["key"] and x["locked"] is None)
        assert pl["stay"]["key"] == "stay"
        fan = pl["fan"]
        assert fan["ages"] == pl["world"]["labels"] and len(fan["ages"]) == pl["K"] + 1 and fan["ages"][-1] == 85
        assert fan["now_index"] == pl["turn"]
        assert fan["past"][pl["turn"]] is not None and fan["p50"][pl["turn"]] is not None
        assert all(v is None for v in fan["past"][pl["turn"] + 1:])
        assert all(v is None for v in fan["p50"][:pl["turn"]])
        assert pl["quests"][-1]["name"] == "Stay debt-free"
        assert set(pl["world"]) >= {"avatar", "turn", "prev_turn", "start_age", "K", "badges", "life", "anims",
                                    "finale", "intro", "skipped"}
    if p["phase"] == "end":
        e = p["end"]
        assert e["world"]["finale"] is True
        assert SUMMARY_KEYS <= set(e["summary"]) and FACT_KEYS <= set(e["facts"])
        assert 0 <= e["facts"]["percentile"] <= 100
        assert 1 <= e["summary"]["stars"] <= 5
        assert e["summary"]["age_end"] == 85 and len(e["facts"]["fan"]["lazy"]) == len(e["facts"]["fan"]["ages"])
    return p


def test_full_playthrough_and_restart():
    s = GameSession()
    p = check(s.payload())
    assert p["phase"] == "boot" and "play" not in p
    assert s.payload() is p                                   # cached until the state changes
    seqs, phases = [p["seq"]], ["boot"]

    assert s.handle({"action": "start", "nonce": 1, "avatar": AVATAR, "ist": p["boot"]["example"]["ist"]}) is None
    p = check(s.payload())
    assert p["phase"] == "play" and p["avatar"]["name"] == "Testi" and p["play"]["hud"]["name"] == "Testi"
    seqs.append(p["seq"])
    phases.append(p["phase"])
    K = p["play"]["K"]

    # a duplicate nonce is ignored
    assert s.handle({"action": "start", "nonce": 1, "ist": IST}) is None
    assert s.payload()["seq"] == p["seq"]
    # a locked card cannot be chosen
    locked = next(c["key"] for c in p["play"]["cards"] if c["locked"])
    assert s.choose(locked) is False

    nonce = 1
    turn = 0
    while p["phase"] == "play":
        assert p["play"]["turn"] == turn
        nonce += 1
        if turn < 15:                                                  # station by station, first open card
            open_cards = [c for c in p["play"]["cards"] if c["locked"] is None]
            key = open_cards[0]["key"] if open_cards else "stay"
            action, step = {"action": "choose", "nonce": nonce, "key": key}, 1
        else:                                                          # then skip to the end of life (85)
            step = min(10, K - turn)
            action = {"action": "skip", "nonce": nonce, "years": step}
        s.handle(action)
        s.handle(action)                                               # replayed value: ignored
        p = check(s.payload())
        assert p["seq"] == seqs[-1] + 1
        seqs.append(p["seq"])
        phases.append(p["phase"])
        turn += step
        if p["phase"] == "play":
            assert p["play"]["turn"] == turn
            assert p["play"]["history"][-1]["title"]
    assert turn == K

    assert p["phase"] == "end"
    assert phases[0] == "boot" and phases[-1] == "end" and set(phases[1:-1]) == {"play"}
    facts = p["end"]["facts"]
    assert facts["decisions"] == len(p["end"]["summary"]["choices"]) > 0
    assert facts["best"] is not None and isinstance(facts["best"]["delta"], float)
    assert facts["disclaimer"]
    assert s.choose("stay") is False                                  # game over

    assert s.handle({"action": "analyse", "nonce": nonce + 1}) == "analyse"
    assert s.handle({"action": "analyse", "nonce": nonce + 1}) is None

    s.handle({"action": "restart", "nonce": nonce + 2})
    p2 = check(s.payload())
    assert p2["phase"] == "boot" and p2["seq"] > p["seq"] and "end" not in p2
    assert p2["avatar"]["name"] == "Testi"

    s.start(IST, AVATAR, seed=7)
    p3 = check(s.payload())
    assert p3["phase"] == "play" and p3["play"]["turn"] == 0 and p3["play"]["start_age"] == 27
    assert p3["play"]["step"] == 1 and p3["play"]["K"] == 58                 # 27 → 85, one station per year
    assert p3["play"]["history"] == []


def test_deterministic_with_seed():
    a, b = GameSession(), GameSession()
    a.start(IST, None, seed=3)
    b.start(IST, None, seed=3)
    assert json.dumps(a.payload()["play"]) == json.dumps(b.payload()["play"])


def test_rejected_choose_still_bumps_seq():
    """A locked/unknown choice changes nothing but bumps seq, so the client's waiting overlay clears."""
    s = GameSession()
    s.handle({"action": "start", "nonce": 1})                               # no data: the example
    p = s.payload()
    turn, seq = p["play"]["turn"], p["seq"]
    locked = next(c["key"] for c in p["play"]["cards"] if c["locked"])
    s.handle({"action": "choose", "nonce": 2, "key": locked})
    s.handle({"action": "choose", "nonce": 3, "key": "does-not-exist"})
    p2 = s.payload()
    assert p2["seq"] == seq + 2 and p2["play"]["turn"] == turn and p2["phase"] == "play"
    s.handle({"action": "choose", "nonce": 3, "key": "stay"})            # duplicate nonce: ignored
    assert s.payload()["seq"] == seq + 2


def test_ist_zustand_builds_the_person():
    s = GameSession()
    s.start(IST, AVATAR, seed=1)
    pr = s.person
    assert (pr.profile_id, pr.name, pr.age, pr.income, pr.expenses, pr.rent) == ("IST", "Testi", 27, 6000, 4700, 1600)
    assert pr.mu == 1300 and pr.cash == 12000 and pr.portfolio == 8000 and pr.sigma > 0
    hud = s.payload()["play"]["hud"]
    assert hud["net_worth"] == 20000 and hud["income"] == 6000
    # an unchanged example profile keeps its calibrated parameters
    ex = s.payload()["boot"]["example"]
    s.start(ex["ist"], AVATAR, seed=1)
    assert s.person.profile_id == ex["id"] and s.person.name == "Testi"
    assert s.person.sigma == s.calib.persons[ex["id"]].sigma
    # an edited example becomes an own person
    s.start({**ex["ist"], "cash": 20000}, AVATAR, seed=1)
    assert s.person.profile_id == "IST" and s.person.cash == 20000


def test_no_investment_cards_in_the_game():
    s = GameSession()
    s.start(IST, AVATAR, seed=2)
    pl = s.payload()["play"]
    assert not any(c["key"].startswith("style_") or c["cat"] == "money" for c in pl["cards"])
    assert "focus_cat" not in pl and "style" not in pl["hud"]
    assert s.assumptions.strategy.invest_rate == 1.0 and s.assumptions.strategy.equity_share == 0.6   # balanced default


def test_housing_offers_buying_a_luxury_flat_and_monthly_costs():
    s = GameSession()
    s.start(IST, AVATAR, seed=2)
    assert [c["key"] for c in s.payload()["play"]["cards"] if c["cat"] == "housing"] == ["buy_house", "flat", "costs"]


def test_intro_flag_only_for_a_fresh_game():
    s = GameSession()
    s.start(IST, AVATAR, seed=5)
    assert s.payload()["play"]["world"]["intro"] is True
    assert s.choose("stay")
    assert s.payload()["play"]["world"]["intro"] is False


def test_wedding_plays_its_own_scene_and_partner_stays():
    s = GameSession()
    s.start({**IST, "age": 25}, AVATAR, seed=6)
    w = s.payload()["play"]["world"]
    assert w["life"]["partner"] is False
    assert s.choose("wedding")
    w = s.payload()["play"]["world"]
    assert [a["type"] for a in w["anims"]] == ["wedding"]
    assert w["life"]["partner"] is True
    assert s.choose("stay")
    assert s.payload()["play"]["world"]["life"]["partner"] is True          # stays in the car


def test_life_span_runs_to_85():
    from twin.game import life_span
    assert life_span(20) == (1, 65, 65) and life_span(24) == (1, 61, 61) and life_span(15) == (1, 70, 70)
    assert life_span(70) == (1, 15, 15)
    s = GameSession()
    s.start({**IST, "age": 58}, AVATAR, seed=8)
    pl = s.payload()["play"]
    assert pl["step"] == 1 and pl["world"]["labels"] == list(range(58, 86))


def test_career_cards():
    s = GameSession()
    s.start(IST, AVATAR, seed=9)
    assert [c["key"] for c in s.payload()["play"]["cards"] if c["cat"] == "career"] == \
        ["grad_job", "job_start", "switch", "parttime", "retire"]
    assert [c["key"] for c in s.payload()["play"]["cards"] if c["cat"] == "timeoff"] == ["gap_year"]


def test_film_ride_with_the_example_data_set_and_own_csv():
    s = GameSession()
    s.handle({"action": "ride", "nonce": 1, "example": True, "avatar": AVATAR})
    p = check(s.payload())
    r = p["ride"]
    # the example data set rides through its own 24 recorded months, one station per month
    assert p["phase"] == "ride" and r["months"] == 24 and len(r["stations"]) == 24
    assert r["stations"][0]["label"] == "Jan 2025" and r["stations"][-1]["label"] == "Dec 2026"
    assert r["world"]["ride"] is True and r["world"]["K"] == 24 and len(r["world"]["labels"]) == 25
    assert len(r["world"]["ride_tags"]) == 24 and r["statements"] and r["after"]["alter_ende"] == 65
    assert s.analysis_person is not None and s.analysis_person.age == 26     # 24 + two years of data
    # own CSV, 24 months -> still monthly stations (quarters only beyond 36 months)
    rows = ["month,net_transactions_chf"] + [f"2027-{m:02d},{500 + m}" for m in range(1, 13)] + \
           [f"2028-{m:02d},{-200 + m}" for m in range(1, 13)]
    s.handle({"action": "ride", "nonce": 2, "ist": IST, "csv": "\n".join(rows)})
    r = check(s.payload())["ride"]
    assert r["months"] == 24 and len(r["stations"]) == 24 and r["source"] == "your data"
    # play on with the updated status quo
    s.handle({"action": "ride_play", "nonce": 3})
    assert s.phase == "play" and s.person.cash == IST["cash"] + sum(500 + m for m in range(1, 13)) + sum(-200 + m for m in range(1, 13))


def test_film_ride_rejects_bad_csv():
    s = GameSession()
    s.handle({"action": "ride", "nonce": 1, "ist": IST, "csv": "a,b\n1,2\n"})
    p = s.payload()
    assert p["phase"] == "boot" and "missing columns" in p["error"]
    assert "error" not in GameSession().payload()


def test_where_you_stand_tile_in_the_hud():
    s = GameSession()
    s.start(IST, AVATAR, seed=3)
    hud = s.payload()["play"]["hud"]
    # start: no previous station; CHF 12'000 cash < 3 x CHF 4'700 expenses -> thin buffer
    assert hud["net_worth_prev"] is None and hud["prev_age"] is None
    assert hud["expenses"] == 4700 and hud["health"] == "thin"
    before = hud["net_worth"]
    assert s.choose("stay")
    hud = s.payload()["play"]["hud"]
    assert hud["net_worth_prev"] == before and hud["prev_age"] == 27 and hud["age"] == 28
    # a decision: the previous value is what the tile showed before (same random paths up to that station)
    shown = hud["net_worth"]
    assert s.choose("wedding")
    assert s.payload()["play"]["hud"]["net_worth_prev"] == shown
    # enough cash for 3 months -> buffer OK; an open loan -> on credit (a mortgage does not count)
    s.start({**IST, "cash": 30000}, AVATAR, seed=3)
    assert s.payload()["play"]["hud"]["health"] == "ok"
    s.start({**IST, "cash": 30000, "debt": 5000}, AVATAR, seed=3)
    assert s.payload()["play"]["hud"]["health"] == "credit"


def test_card_impact_rule():
    from twin.game import impact
    assert impact(None) is None and impact(None, 1e6) is None
    assert impact(50_000, 1e6) == "up" and impact(-50_000, 1e6) == "down"
    assert impact(9_000, 1e6) == "flat" and impact(-9_000, 1e6) == "flat"           # < 1 % of the median
    assert impact(25_000, 1e7) == "up"                                              # >= CHF 20'000 always counts
    assert impact(500, 0.0) == "up" and impact(0.0, 1e6) == "flat"
    # the summary keeps the numbers for the end and adds the direction
    s = GameSession()
    s.start(IST, AVATAR, seed=3)
    for _ in range(3):
        key = next(c["key"] for c in s.payload()["play"]["cards"] if c["locked"] is None and c["key"] != "costs")
        assert s.choose(key)
    assert s.skip(70) and s.phase == "end"
    ch = s.payload()["end"]["summary"]["choices"]
    assert len(ch) == 3 and all(c["impact"] in ("up", "down", "flat") and isinstance(c["delta"], float) for c in ch)
