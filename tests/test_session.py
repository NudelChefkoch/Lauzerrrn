"""GameSession: payload contract (CONTRACT.md) over a full playthrough."""
import json

from twin.session import GameSession

CARD_KEYS = {"key", "cat", "emoji", "title", "text", "locked", "xp", "joy", "delta", "median", "p5", "p95",
             "credit", "rarity"}
PREVIEW_KEYS = ("delta", "median", "p5", "p95", "credit")
RARITIES = {"COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY"}
HUD_KEYS = {"name", "age", "level", "level_title", "xp_in_level", "xp_per_level", "xp_total", "joy", "joy_emoji",
            "net_worth", "cash", "portfolio", "debt", "income", "state_de", "achievements_got", "achievements_total"}
SUMMARY_KEYS = {"name", "age_end", "score", "stars", "level", "level_title", "joy", "joy_emoji", "xp_total",
                "choices", "achievements"}
FACT_KEYS = {"net_worth", "percentile", "p5", "p95", "lazy_median", "cash", "portfolio", "house_equity", "debt",
             "max_credit", "months_with_credit", "decisions", "best", "fan", "disclaimer"}
AVATAR = {"name": "Testi", "gender": "mann", "skin": "oliv", "hair": "kurz", "hairColor": "blond", "hat": "cap",
          "outfit": "tshirt", "color": "gruen", "car": "rot"}


def check(p: dict) -> dict:
    json.loads(json.dumps(p, allow_nan=False))          # plain, JSON-serialisable, no NaN
    assert p["phase"] in ("boot", "play", "end")
    assert p["boot"]["profiles"][0]["id"] == "P00001" and len(p["boot"]["risks"]) == 3
    assert p["height"] > 0 and isinstance(p["seq"], int) and isinstance(p["avatar"], dict)
    if p["phase"] == "play":
        pl = p["play"]
        assert HUD_KEYS <= set(pl["hud"]) and pl["K"] == 15 and pl["age"] == pl["start_age"] + pl["turn"]
        assert len(pl["categories"]) == 6
        cat_keys = {c["key"] for c in pl["categories"]}
        assert cat_keys == {"bildung", "karriere", "wohnen", "familie", "auszeit", "geld"}
        for card in pl["cards"]:
            assert CARD_KEYS <= set(card) and card["cat"] in cat_keys and card["rarity"] in RARITIES
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
        assert pl["quests"][-1]["name"] == "Stay debt-free"
        assert set(pl["world"]) >= {"avatar", "turn", "prev_turn", "start_age", "K", "badges", "life", "anims",
                                    "finale"}
    if p["phase"] in ("play", "end"):
        blk = p[p["phase"]]
        assert set(blk["chat"]) >= {"available", "model", "mode", "messages", "prompts"}
        assert blk["chat"]["mode"] in ("llm", "offline") and blk["chat"]["messages"]
        assert all(m["role"] in ("twin", "user") and isinstance(m["tools"], list) for m in blk["chat"]["messages"])
        assert "dashboard" in blk
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

    assert s.handle({"action": "start", "nonce": 1, "avatar": AVATAR, "pid": "P00001", "risk": "ausgewogen"}) is None
    p = check(s.payload())
    assert p["phase"] == "play" and p["avatar"]["name"] == "Testi" and p["play"]["hud"]["name"] == "Testi"
    seqs.append(p["seq"])
    phases.append(p["phase"])
    seen_new += [a["title"] for a in p["play"]["new_achievements"]]

    # a duplicate nonce is ignored
    assert s.handle({"action": "start", "nonce": 1, "pid": "P00001", "risk": "risky"}) is None
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

    s.start("P00001", AVATAR, "konservativ", seed=7)
    p3 = check(s.payload())
    assert p3["phase"] == "play" and p3["play"]["turn"] == 0 and p3["play"]["hud"]["xp_total"] >= 0
    assert p3["play"]["history"] == []


def test_deterministic_with_seed():
    a, b = GameSession(), GameSession()
    a.start("P00001", None, "risky", seed=3)
    b.start("P00001", None, "risky", seed=3)
    assert json.dumps(a.payload()["play"]) == json.dumps(b.payload()["play"])


def test_rejected_choose_still_bumps_seq():
    """A locked/unknown choice changes nothing but bumps seq, so the client's waiting overlay clears."""
    s = GameSession()
    s.handle({"action": "start", "nonce": 1, "pid": "P00001", "risk": "ausgewogen"})
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
