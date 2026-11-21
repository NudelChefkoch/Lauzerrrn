"""GameSession: payload contract (CONTRACT.md) over a full playthrough."""
import json
import re

from twin.session import GameSession

CARD_KEYS = {"key", "cat", "emoji", "title", "text", "locked", "joy", "delta", "median", "p5", "p95", "credit"}
PREVIEW_KEYS = ("delta", "median", "p5", "p95", "credit")
HUD_KEYS = {"name", "age", "style_de", "joy", "joy_emoji", "net_worth", "cash", "portfolio", "debt", "income",
            "state_de", "achievements_got", "achievements_total"}
SUMMARY_KEYS = {"name", "age_end", "score", "stars", "joy", "joy_emoji", "style_de", "choices", "achievements"}
IST = {"age": 27, "status": "employed", "income": 6000, "expenses": 4700, "rent": 1600, "cash": 12000,
       "portfolio": 8000, "debt": 0}
FACT_KEYS = {"net_worth", "percentile", "p5", "p95", "lazy_median", "cash", "portfolio", "house_equity", "debt",
             "max_credit", "months_with_credit", "decisions", "best", "fan", "disclaimer"}
AVATAR = {"name": "Testi", "gender": "mann", "skin": "oliv", "hair": "kurz", "hairColor": "blond", "hat": "cap",
          "outfit": "tshirt", "color": "gruen", "car": "rot"}


def check(p: dict) -> dict:
    json.loads(json.dumps(p, allow_nan=False))          # plain, JSON-serialisable, no NaN
    assert p["phase"] in ("boot", "play", "end")
    boot = p["boot"]
    assert boot["profiles"][0]["id"] == "P00001" and "risks" not in boot       # no risk question at the start
    assert boot["ist"]["basis"] == "P00001" and all("ist" in pr for pr in boot["profiles"])
    assert {s["key"] for s in boot["statuses"]} >= {"student", "employed"}
    assert not re.search(r"\"(xp|level|rarity)", json.dumps(p))                                        # no XP anywhere
    assert p["height"] > 0 and isinstance(p["seq"], int) and isinstance(p["avatar"], dict)
    if p["phase"] == "play":
        pl = p["play"]
        assert HUD_KEYS <= set(pl["hud"]) and pl["K"] == 15 and pl["age"] == pl["start_age"] + pl["turn"]
        assert len(pl["categories"]) == 6
        cat_keys = {c["key"] for c in pl["categories"]}
        assert cat_keys == {"bildung", "karriere", "wohnen", "familie", "auszeit", "geld"}
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
        assert len(fan["ages"]) == 16 and fan["now_index"] == pl["turn"]
        assert fan["past"][pl["turn"]] is not None and fan["p50"][pl["turn"]] is not None
        assert all(v is None for v in fan["past"][pl["turn"] + 1:])
        assert all(v is None for v in fan["p50"][:pl["turn"]])
        assert pl["quests"][-1]["name"] == "Schuldenfrei bleiben"
        assert set(pl["world"]) >= {"avatar", "turn", "prev_turn", "start_age", "K", "badges", "life", "anims",
                                    "finale"}
    if p["phase"] == "end":
        e = p["end"]
        assert e["world"]["finale"] is True
        assert SUMMARY_KEYS <= set(e["summary"]) and FACT_KEYS <= set(e["facts"])
        assert 0 <= e["facts"]["percentile"] <= 100
        assert 1 <= e["summary"]["stars"] <= 5
        assert len(e["facts"]["fan"]["lazy"]) == 16
    return p


def test_full_playthrough_and_restart():
    s = GameSession()
    p = check(s.payload())
    assert p["phase"] == "boot" and "play" not in p
    assert s.payload() is p                                   # cached until the state changes
    seqs, phases, seen_new = [p["seq"]], ["boot"], []

    assert s.handle({"action": "start", "nonce": 1, "avatar": AVATAR, "ist": p["boot"]["ist"]}) is None
    p = check(s.payload())
    assert p["phase"] == "play" and p["avatar"]["name"] == "Testi" and p["play"]["hud"]["name"] == "Testi"
    seqs.append(p["seq"])
    phases.append(p["phase"])
    seen_new += [a["title"] for a in p["play"]["new_achievements"]]

    # a duplicate nonce is ignored
    assert s.handle({"action": "start", "nonce": 1, "ist": IST}) is None
    assert s.payload()["seq"] == p["seq"]
    # a locked card cannot be chosen
    locked = next(c["key"] for c in p["play"]["cards"] if c["locked"])
    assert s.choose(locked) is False

    nonce = 1
    for turn in range(15):
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
            seen_new += [a["title"] for a in p["play"]["new_achievements"]]

    assert p["phase"] == "end"
    assert phases[0] == "boot" and phases[-1] == "end" and set(phases[1:-1]) == {"play"}
    assert seen_new and len(seen_new) == len(set(seen_new))          # each new achievement shown exactly once
    got = sum(a["got"] for a in p["end"]["summary"]["achievements"])
    assert got >= len(seen_new)
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
    assert p3["play"]["history"] == []


def test_deterministic_with_seed():
    a, b = GameSession(), GameSession()
    a.start(IST, None, seed=3)
    b.start(IST, None, seed=3)
    assert json.dumps(a.payload()["play"]) == json.dumps(b.payload()["play"])


def test_rejected_choose_still_bumps_seq():
    """A locked/unknown choice changes nothing but bumps seq, so the client's waiting overlay clears."""
    s = GameSession()
    s.handle({"action": "start", "nonce": 1, "pid": "P00001"})
    p = s.payload()
    turn, seq = p["play"]["turn"], p["seq"]
    locked = next(c["key"] for c in p["play"]["cards"] if c["locked"])
    s.handle({"action": "choose", "nonce": 2, "key": locked})
    s.handle({"action": "choose", "nonce": 3, "key": "does-not-exist"})
    p2 = s.payload()
    assert p2["seq"] == seq + 2 and p2["play"]["turn"] == turn and p2["phase"] == "play"
    assert p2["play"]["new_achievements"] == []
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
    s.start(s.payload()["boot"]["ist"], AVATAR, seed=1)
    assert s.person.profile_id == "P00001" and s.person.name == "Testi"
    assert s.person.sigma == s.calib.persons["P00001"].sigma
    # an edited example becomes an own person
    s.start({**s.payload()["boot"]["ist"], "cash": 20000}, AVATAR, seed=1)
    assert s.person.profile_id == "IST" and s.person.cash == 20000


def test_investment_style_is_asked_later():
    s = GameSession()
    s.start(IST, AVATAR, seed=2)
    pl = s.payload()["play"]
    styles = [c for c in pl["cards"] if c["key"].startswith("style_")]
    assert len(styles) == 3 and all(c["locked"] for c in styles)            # station 1: not yet
    assert pl["focus_cat"] is None and pl["hud"]["style_de"] == "noch offen"
    assert s.choose("style_risky") is False
    assert s.choose("stay")
    pl = s.payload()["play"]
    assert pl["focus_cat"] == "geld" and pl["hint"]                          # station 2: now ask
    assert all(c["locked"] is None for c in pl["cards"] if c["key"].startswith("style_"))
    port_before = pl["hud"]["portfolio"]
    assert s.choose("style_risky")
    pl = s.payload()["play"]
    assert pl["focus_cat"] is None and pl["hud"]["style_de"] == "Mutig anlegen"
    lock = {c["key"]: c["locked"] for c in pl["cards"]}
    assert lock["style_risky"] == "Dein aktueller Anlagestil" and lock["style_konservativ"] is None
    assert s.choose("stay")
    assert s.payload()["play"]["hud"]["portfolio"] > port_before              # now money gets invested
