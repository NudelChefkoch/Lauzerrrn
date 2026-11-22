"""GameSession: payload contract (CONTRACT.md) over a full playthrough."""
import json
import re

from twin.session import GameSession

CARD_KEYS = {"key", "cat", "emoji", "title", "text", "locked", "delta", "median", "p5", "p95", "credit"}
PREVIEW_KEYS = ("delta", "median", "p5", "p95", "credit")
HUD_KEYS = {"name", "age", "net_worth", "cash", "portfolio", "debt", "income", "state"}
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
    assert {s["key"] for s in boot["statuses"]} >= {"student", "employed"}
    assert not re.search(r"\"(xp|level|rarity|joy|joy_emoji|achievements|new_achievements)\"|_de\"", json.dumps(p))
    assert p["height"] > 0 and isinstance(p["seq"], int) and isinstance(p["avatar"], dict)
    if p["phase"] == "play":
        pl = p["play"]
        assert HUD_KEYS <= set(pl["hud"]) and pl["end_age"] == 65 and pl["step"] == 1
        assert pl["age"] == min(pl["start_age"] + pl["turn"] * pl["step"], 65)
        assert len(pl["categories"]) == 5
        cat_keys = {c["key"] for c in pl["categories"]}
        assert cat_keys == {"education", "career", "housing", "family", "timeoff"}    # money: analysis only
        for card in pl["cards"]:
            assert CARD_KEYS <= set(card) and card["cat"] in cat_keys
            if card["locked"] is not None:
                assert all(card[k] is None for k in PREVIEW_KEYS), card
            else:
                assert all(isinstance(card[k], float) for k in PREVIEW_KEYS), card
        for c in pl["categories"]:
            assert c["open"] == sum(1 for x in pl["cards"] if x["cat"] == c["key"] and x["locked"] is None)
        assert pl["stay"]["key"] == "stay"
        fan = pl["fan"]
        assert fan["ages"] == pl["world"]["labels"] and len(fan["ages"]) == pl["K"] + 1 and fan["ages"][-1] == 65
        assert fan["now_index"] == pl["turn"]
        assert fan["past"][pl["turn"]] is not None and fan["p50"][pl["turn"]] is not None
        assert all(v is None for v in fan["past"][pl["turn"] + 1:])
        assert all(v is None for v in fan["p50"][:pl["turn"]])
        assert pl["quests"][-1]["name"] == "Stay debt-free"
        assert set(pl["world"]) >= {"avatar", "turn", "prev_turn", "start_age", "K", "badges", "life", "anims",
                                    "finale", "intro"}
    if p["phase"] == "end":
        e = p["end"]
        assert e["world"]["finale"] is True
        assert SUMMARY_KEYS <= set(e["summary"]) and FACT_KEYS <= set(e["facts"])
        assert 0 <= e["facts"]["percentile"] <= 100
        assert 1 <= e["summary"]["stars"] <= 5
        assert e["summary"]["age_end"] == 65 and len(e["facts"]["fan"]["lazy"]) == len(e["facts"]["fan"]["ages"])
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
    for turn in range(K):
        assert p["phase"] == "play" and p["play"]["turn"] == turn
        open_cards = [c for c in p["play"]["cards"] if c["locked"] is None]
        key = open_cards[0]["key"] if open_cards else "stay"
        nonce += 1
        s.handle({"action": "choose", "nonce": nonce, "key": key})
        s.handle({"action": "choose", "nonce": nonce, "key": key})     # replayed value: ignored
        p = check(s.payload())
        assert p["seq"] > seqs[-1]
        seqs.append(p["seq"])
        phases.append(p["phase"])
        if p["phase"] == "play":
            assert p["play"]["turn"] == turn + 1
            assert p["play"]["history"][-1]["title"]

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
    assert p3["play"]["step"] == 1 and p3["play"]["K"] == 38                 # 27 → 65, one station per year
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


def test_housing_offers_buying_and_a_luxury_flat():
    s = GameSession()
    s.start(IST, AVATAR, seed=2)
    assert [c["key"] for c in s.payload()["play"]["cards"] if c["cat"] == "housing"] == ["buy_house", "flat"]


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


def test_life_span_runs_to_retirement():
    from twin.game import life_span
    assert life_span(20) == (1, 45, 45) and life_span(24) == (1, 41, 41) and life_span(62) == (1, 5, 5)
    s = GameSession()
    s.start({**IST, "age": 58}, AVATAR, seed=8)
    pl = s.payload()["play"]
    assert pl["step"] == 1 and pl["world"]["labels"] == list(range(58, 66))


def test_career_offers_only_entry_job_job_change_part_time():
    s = GameSession()
    s.start(IST, AVATAR, seed=9)
    assert [c["key"] for c in s.payload()["play"]["cards"] if c["cat"] == "career"] == ["job_start", "switch", "parttime"]


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
