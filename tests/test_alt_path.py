"""Alternative life path: moving / removing / adding decisions, the net-worth paths and the twin's suggestions."""
import json
import time

import pytest

from twin import alt_path as ap
from twin import game
from twin.calibration import calibrate
from twin.scenarios import Job, Study
from twin.session import GameSession

IST = {"age": 27, "status": "employed", "income": 6000, "expenses": 4700, "rent": 1600, "cash": 12000,
       "portfolio": 8000, "debt": 0}
STUDENT = {"age": 20, "status": "student", "income": 0, "expenses": 1800, "rent": 0, "cash": 60000,
           "portfolio": 0, "debt": 0}
AVATAR = {"name": "Testi", "gender": "mann", "skin": "oliv", "hair": "iro", "hairColor": "blond", "hat": "cap",
          "outfit": "tshirt", "color": "gruen", "car": "rot"}


def played(ist=IST, keys=("switch", "wedding", "stay", "child", "costs"), seed=1) -> GameSession:
    s = GameSession()
    s.start(ist, AVATAR, seed=seed)
    for k in keys:
        assert s.choose(k), k
    while s.phase == "play":
        s.skip(10)
    return s


@pytest.fixture(scope="module")
def sess():
    return played()


@pytest.fixture(scope="module")
def student():
    return played(STUDENT, ("bachelor", "stay", "stay", "gap_year", "grad_job", "stay", "switch", "stay", "wedding",
                            "child"), seed=7)


def direct_end(s, events) -> float:
    return game.play(s.person, list(events), s.assumptions, calibrate(), s.seed, 0, s.total,
                     pct_series=()).metrics["median_net_worth_end"]


def by_id(items):
    return {it["id"]: it for it in items}


# ---------------------------------------------------------------- alt state
def test_apply_edit_merges_and_stays_json_safe():
    a = ap.apply_edit(None, {"moves": {"d1": 30.4}})
    assert a == {"moves": {"d1": 30}, "removed": [], "added": []}
    a = ap.apply_edit(a, {"removed": ["d2"], "added": [{"key": "buy_house", "age": 40, "params": {"price": 612_345}}]})
    assert a["removed"] == ["d2"] and a["added"][0]["id"] == "a1" and a["added"][0]["params"] == {"price": 600_000}
    a2 = ap.apply_edit(a, {"added": [{"id": "a1", "key": "child", "age": 33}]})       # fresh id, no clash
    assert [x["id"] for x in a2["added"]] == ["a1", "a2"]
    assert ap.apply_edit(a2, {"moves": {"a2": 35}})["added"][1]["age"] == 35          # moving an added option
    assert [x["id"] for x in ap.apply_edit(a2, {"removed": ["a1"]})["added"]] == ["a2"]
    assert ap.apply_edit(a2, {"restore": ["d2"]})["removed"] == []
    assert ap.apply_edit(a2, {"reset": True}) == ap.EMPTY
    assert a2["moves"] == {"d1": 30}                     # inputs not mutated by later edits
    json.dumps(a2)
    assert ap.normalize({"moves": {"d1": "x"}, "added": [{"key": "nope", "age": 3}], "removed": "d1"}) == ap.EMPTY
    assert ap.is_empty(None) and not ap.is_empty(a)


def test_apply_action_maps_component_actions():
    a = ap.apply_action(None, {"action": "move", "id": "d1", "age": 31, "nonce": 1})
    a = ap.apply_action(a, {"action": "remove", "id": "d2"})
    a = ap.apply_action(a, {"action": "add", "key": "gap_year", "age": 40, "params": {}})
    assert a["moves"] == {"d1": 31} and a["removed"] == ["d2"] and a["added"][0]["key"] == "gap_year"
    assert ap.apply_action(a, {"action": "restore", "id": "d2"})["removed"] == []
    assert ap.apply_action(a, {"action": "reset"}) == ap.EMPTY
    assert ap.apply_action(a, {"action": "???"}) == a


# ---------------------------------------------------------------- timeline
def test_timeline_has_all_decisions_and_follow_up_events(sess):
    items = ap.timeline_items(sess)
    decisions = [h for h in sess.history if h["key"] != "stay"]
    dec = [it for it in items if it["kind"] == "decision"]
    assert [d["title"] for d in dec] == [h["title"] for h in decisions]
    assert [d["age"] for d in dec] == [sess.age_at(h["turn"]) for h in decisions]
    assert all(d["impact"] in ("up", "down", "flat") and d["movable"] for d in dec)
    events = {it["title"]: it for it in items if it["kind"] == "event"}
    child = next(d for d in dec if d["key"] == "child")
    assert events["Your child moves out"]["follows"] == child["id"]
    assert events["Your child moves out"]["age"] == child["age"] + game.CHILD_MONTHS / 12
    assert events["Retirement"]["age"] == game.FORCED_RETIRE_AGE and events["Retirement"]["follows"] is None
    assert all(it["alt_age"] is None and not it["removed"] for it in items)
    assert max(it["age"] for it in items) <= sess.person.age + sess.total
    json.dumps(items)


def test_moving_a_decision_shifts_its_follow_up_events(sess):
    items = by_id(ap.timeline_items(sess))
    child = next(it for it in items.values() if it.get("key") == "child")
    out = next(it for it in items.values() if it["follows"] == child["id"])
    alt = ap.apply_edit(None, {"moves": {child["id"]: child["age"] + 4}})
    moved = by_id(ap.timeline_items(sess, alt))
    assert moved[child["id"]]["alt_age"] == child["age"] + 4
    assert moved[out["id"]]["alt_age"] == out["age"] + 4
    evs = ap.alt_events(sess, alt)
    m0 = 12 * (child["age"] - sess.person.age)
    assert sorted(e.start for e in evs if e.label in ("Child", "Child costs")) == [m0 + 48, m0 + 48]
    assert len(evs) == len(sess.events)


def test_removing_a_decision_drops_its_events(sess):
    items = ap.timeline_items(sess)
    child = next(it for it in items if it.get("key") == "child")
    alt = ap.apply_edit(None, {"removed": [child["id"]]})
    after = by_id(ap.timeline_items(sess, alt))
    assert after[child["id"]]["removed"]
    assert all(it["removed"] for it in after.values() if it["follows"] == child["id"])
    assert not [e for e in ap.alt_events(sess, alt) if e.label in ("Child", "Child costs")]


def test_added_option_events_at_the_chosen_age(sess):
    alt = ap.apply_edit(None, {"added": [{"key": "buy_house", "age": 40, "params": {"price": 700_000}}]})
    new = [e for e in ap.alt_events(sess, alt) if e not in sess.events]
    assert len(new) == 1 and new[0].start == 12 * (40 - sess.person.age) and new[0].price == 700_000
    added = [it for it in ap.timeline_items(sess, alt) if it["kind"] == "added"]
    assert added and added[0]["age"] == 40 and added[0]["id"] == "a1" and added[0]["key"] == "buy_house"
    # an added child brings its "moves out" event, attached to the added chip
    alt = ap.apply_edit(alt, {"added": [{"key": "child", "age": 35}]})
    items = ap.timeline_items(sess, alt)
    out = [it for it in items if it["follows"] == "a2"]
    assert out and out[0]["age"] == 35 + 18 and out[0]["alt_only"]


def test_added_retirement_replaces_the_forced_one(sess):
    alt = ap.apply_edit(None, {"added": [{"key": "retire", "age": 50}]})       # clamped to 60
    evs = ap.alt_events(sess, alt)
    assert [e.start for e in evs if e.label == "Retired"] == [12 * (game.RETIRE_FROM - sess.person.age)]
    assert game.forced_retirement(sess.person, evs) == []
    forced = next(it for it in ap.timeline_items(sess, alt) if it["title"] == "Retirement")
    assert forced["removed"]


def test_degree_chain_moves_together(student):
    items = by_id(ap.timeline_items(student))
    bach = next(it for it in items.values() if it.get("key") == "bachelor")
    followers = [it for it in items.values() if it["follows"] == bach["id"]]
    assert {it.get("key") for it in followers} >= {"gap_year", "grad_job", None}     # None = degree finished
    alt = ap.apply_edit(None, {"moves": {bach["id"]: bach["age"] + 2}})
    moved = by_id(ap.timeline_items(student, alt))
    for it in followers:
        assert moved[it["id"]]["alt_age"] == it["age"] + 2, it["title"]
    # the degree job can't start before the degree is finished
    job = next(it for it in followers if it.get("key") == "grad_job")
    alt = ap.apply_edit(None, {"moves": {job["id"]: student.person.age}})
    end = next(it for it in followers if it["kind"] == "event")["age"]
    assert by_id(ap.timeline_items(student, alt))[job["id"]]["alt_age"] in (None, end)
    assert min(e.start for e in ap.alt_events(student, alt) if isinstance(e, Job)) >= 12 * (end - student.person.age)


def test_added_degree_brings_the_degree_job(sess):
    alt = ap.apply_edit(None, {"added": [{"key": "master", "age": 40}]})
    evs = ap.alt_events(sess, alt)
    st = next(e for e in evs if isinstance(e, Study))
    job = next(e for e in evs if isinstance(e, Job) and e.label == "First job")
    assert job.start == st.start + st.months and job.salary == game.GRAD_JOBS["master"][0]


def test_addable_options_and_bounds(sess):
    add = {a["key"]: a for a in ap.addable(sess)}
    assert "stay" not in add and "lehre" not in add                     # apprenticeship only up to 25
    assert add["retire"]["min_age"] == game.RETIRE_FROM
    assert (add["child"]["min_age"], add["child"]["max_age"]) == (27, 50)
    assert add["buy_house"]["params"]["price"]["default"] == 850_000
    assert all(a["min_age"] >= sess.person.age and a["max_age"] < sess.person.age + sess.total for a in add.values())
    json.dumps(list(add.values()))


# ---------------------------------------------------------------- paths
def test_simulate_paths_matches_direct_play(sess):
    items = ap.timeline_items(sess)
    child = next(it for it in items if it.get("key") == "child")
    alt = ap.apply_edit(None, {"moves": {child["id"]: child["age"] + 5},
                               "added": [{"key": "gap_year", "age": 45}]})
    p = ap.simulate_paths(sess, alt)
    assert p["ages"][0] == sess.person.age and p["ages"][-1] == sess.person.age + sess.total == 85
    assert len(p["played"]["p50"]) == len(p["ages"]) == len(p["alt"]["p5"])
    played_end, alt_end = direct_end(sess, sess.events), direct_end(sess, ap.alt_events(sess, alt))
    m = p["metrics"]
    assert m["played_end"] == pytest.approx(played_end) and m["alt_end"] == pytest.approx(alt_end)
    assert m["delta_end"] == pytest.approx(alt_end - played_end)
    assert p["played"]["p50"][-1] == pytest.approx(played_end)
    assert all(lo <= mid <= hi for lo, mid, hi in zip(p["played"]["p5"], p["played"]["p50"], p["played"]["p95"]))
    assert "Have a child 5 years later" in p["label"] and "+ Gap year at 45" in p["label"]
    json.dumps(p)


def test_no_alt_or_no_change_means_no_alt_series(sess):
    p = ap.simulate_paths(sess, None)
    assert p["alt"] is None and p["label"] is None and p["metrics"]["delta_end"] is None
    d1 = ap.timeline_items(sess)[0]
    same = ap.apply_edit(None, {"moves": {d1["id"]: d1["age"]}})
    assert ap.simulate_paths(sess, same)["alt"] is None


def test_no_game():
    assert ap.timeline_items(None) == [] and ap.addable(GameSession()) == []
    assert ap.simulate_paths(GameSession(), None) is None and ap.suggestions(None) == []
    assert ap.alt_events(None, None) == []


# ---------------------------------------------------------------- suggestions
def test_suggestions_are_a_mix_and_correct(sess):
    t = time.perf_counter()
    sg = ap.suggestions(sess)
    assert time.perf_counter() - t < 6
    assert 2 <= len(sg) <= 6
    imps = [s["impact"] for s in sg]
    assert "up" in imps and imps.count("down") >= 2
    assert len({s["id"] for s in sg}) == len(sg)
    base = direct_end(sess, sess.events)
    for s in sg[:2] + sg[-1:]:
        evs = ap.alt_events(sess, ap.apply_edit(None, s["edit"]))
        assert s["delta"] == pytest.approx(direct_end(sess, evs) - base), s["title"]
        assert (s["delta"] > 0) == (s["impact"] == "up") or s["impact"] == "flat"
        assert s["title"] and s["text"] and s["emoji"]
    json.dumps(sg)


def test_suggestions_relative_to_the_alt_path(sess):
    child = next(it for it in ap.timeline_items(sess) if it.get("key") == "child")
    alt = ap.apply_edit(None, {"moves": {child["id"]: child["age"] + 3}})
    sg = ap.suggestions(sess, alt, n=4)
    assert 1 <= len(sg) <= 4
    base = direct_end(sess, ap.alt_events(sess, alt))
    s = sg[0]
    evs = ap.alt_events(sess, ap.apply_edit(alt, s["edit"]))
    assert s["delta"] == pytest.approx(direct_end(sess, evs) - base)
    assert "your new path" in s["text"]


def test_suggestions_fast_for_a_long_game(student):
    assert student.total >= 60
    t = time.perf_counter()
    sg = ap.suggestions(student)
    assert time.perf_counter() - t < 6
    assert sg and [s["impact"] for s in sg].count("down") >= 2
    t = time.perf_counter()
    ap.suggestions(student)                              # cached
    ap.simulate_paths(student, None)
    assert time.perf_counter() - t < 0.5
