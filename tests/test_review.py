"""Life review after the game: effects = direct simulate calls with / without the decision, items, speed."""
import time

import pytest

from twin import game
from twin import review as rv
from twin.calibration import calibrate
from twin.engine import simulate
from twin.session import GameSession

IST = {"age": 27, "status": "employed", "income": 6000, "expenses": 4700, "rent": 1600, "cash": 12000,
       "portfolio": 8000, "debt": 0}
AVATAR = {"name": "Testi", "gender": "mann", "skin": "oliv", "hair": "iro", "hairColor": "blond", "hat": "cap",
          "outfit": "tshirt", "color": "gruen", "car": "rot"}


def played(keys=("switch", "wedding", "stay", "child", "costs"), finish=True, seed=1) -> GameSession:
    s = GameSession()
    s.start(IST, AVATAR, seed=seed)
    for k in keys:
        assert s.choose(k), k
    while finish and s.phase == "play":
        s.skip(10)
    return s


@pytest.fixture(scope="module")
def sess():
    return played()


def direct_median(s, events) -> float:
    events = list(events)
    res = simulate(s.person, events + game.forced_retirement(s.person, events), s.total, s.assumptions, game.N_PATHS,
                   s.seed, calib=calibrate(), fixed_until=0, pct_series=())
    return res.metrics["median_net_worth_end"]


def test_no_game_no_review():
    assert rv.review(None) is None
    assert rv.review(GameSession()) is None                  # boot: nothing played
    s = GameSession()
    s.start(IST, AVATAR, seed=1)
    assert rv.review(s) is None                              # started, but no decision yet


def test_deltas_equal_direct_simulate(sess):
    r = rv.review(sess)
    decisions = [h for h in sess.history if h["key"] != "stay"]
    assert [t["title"] for t in r["timeline"]] == [h["title"] for h in decisions]
    assert [t["age"] for t in r["timeline"]] == [sess.age_at(h["turn"]) for h in decisions]
    full = direct_median(sess, sess.events)
    assert r["facts"]["median_net_worth_end"] == pytest.approx(full)
    assert r["facts"]["median_without_choices"] == pytest.approx(direct_median(sess, []))
    for h, item in zip(decisions, r["timeline"]):
        month = sess.month_at(h["turn"])
        without = [e for e in sess.events if e.start != month]
        assert len(without) < len(sess.events)
        assert item["effect"] == pytest.approx(full - direct_median(sess, without)), h["key"]
        # arrow + amount = what the card showed in the game (no contradiction between cards and timeline)
        assert item["delta"] == pytest.approx(h["delta"]) and item["impact"] == game.impact(h["delta"], h["base"])
        assert item["impact"] in ("up", "down", "flat")
        assert item["cat"] in ("education", "career", "housing", "family", "timeoff")


def test_timeline_arrows_match_the_cards_after_a_degree():
    """After a degree "drive on" means taking the degree job (game.assume_degree_jobs): the job card is grey and the
    gap year red – the timeline must say the same, not "the job paid off millions"."""
    s = GameSession()
    s.start({"age": 20, "status": "student", "income": 0, "expenses": 1800, "rent": 0, "cash": 60000,
             "portfolio": 0, "debt": 0}, AVATAR, seed=7)
    for k in ["bachelor", "stay", "stay", "gap_year", "grad_job"]:
        assert s.choose(k), k
    r = rv.review(s)
    shown = [game.impact(h["delta"], h["base"]) for h in s.history if h["key"] != "stay"]
    assert [t["impact"] for t in r["timeline"]] == shown
    assert dict(zip([t["key"] for t in r["timeline"]], shown))["grad_job"] == "flat"
    assert not any("Job after your degree" in p["title"] for p in r["positives"])


def test_items_and_verdict(sess):
    r = rv.review(sess)
    v = r["verdict"]
    assert v["grade"] in "ABCDE" and len(v["grade"]) == 1 and v["level"] in ("great", "good", "mixed", "risky")
    assert v["title"] and v["text"] and 0 <= v["score"] <= 100
    assert r["positives"] and r["negatives"]
    for p in r["positives"]:
        assert set(p) == {"icon", "title", "text"}
    for n in r["negatives"]:
        assert set(n) == {"icon", "title", "text", "better"} and n["better"]
    # the child costs money in every life: it shows up as a negative with advice
    assert any("child" in n["title"].lower() for n in r["negatives"])
    f = r["facts"]
    assert f["decisions"] == 4 and f["finished"] and f["end_age"] == 85 and f["kids"] == 1
    # months on credit = the played life (path 0) as on the facts screen
    end = sess.payload()["end"]["facts"]
    assert f["months_on_credit"] == end["months_with_credit"]
    assert f["final_net_worth"] == pytest.approx(end["net_worth"])
    # english, no German leftovers
    text = " ".join([v["title"], v["text"]] + [x["title"] + x["text"] for x in r["positives"] + r["negatives"]])
    assert not any(w in text for w in (" und ", " nicht ", "Vermögen", "Jahre"))


def test_credit_life_is_graded_down():
    s = GameSession()
    s.start({"age": 22, "status": "student", "income": 1200, "expenses": 1800, "rent": 800, "cash": 9000,
             "portfolio": 0, "debt": 0}, AVATAR, seed=3)
    for k in ["bachelor", "stay", "stay", "grad_job", "child", "gap_year", "parttime", "flat"]:
        assert s.choose(k), k
    while s.phase == "play":
        s.skip(10)
    r = rv.review(s)
    assert r["facts"]["months_on_credit"] > 0
    assert r["verdict"]["grade"] in ("D", "E")
    assert r["negatives"][0]["icon"] == "💳"
    # never praised for a healthy buffer while living on credit for over a year (no contradictory cards)
    if r["facts"]["months_on_credit"] > 12:
        assert "Healthy buffer" not in [x["title"] for x in r["positives"]]


def test_review_from_dict_and_mid_game():
    s = played(("switch", "wedding"), finish=False)
    assert s.phase == "play"
    r = rv.review(s)
    assert [t["title"] for t in r["timeline"]] == ["Job change", "Get married"] and not r["facts"]["finished"]
    d = {"person": s.person, "events": s.events, "history": s.history, "seed": s.seed, "assumptions": s.assumptions,
         "total": s.total, "avatar": s.avatar}
    assert rv.review(d)["timeline"] == r["timeline"]
    assert rv.review({"person": s.person, "history": []}) is None


def test_fast_enough_for_15_decisions():
    s = GameSession()
    s.start({"age": 22, "status": "student", "income": 1200, "expenses": 1800, "rent": 800, "cash": 30000,
             "portfolio": 0, "debt": 0}, AVATAR, seed=7)
    keys = ["bachelor", "stay", "stay", "grad_job", "wedding", "switch", "costs", "child", "switch", "costs",
            "gap_year", "switch", "costs", "child", "switch", "costs", "flat"]
    for k in keys:
        s.choose(k)
    while s.phase == "play":
        s.skip(10)
    assert len([h for h in s.history if h["key"] != "stay"]) >= 12
    rv._review.cache_clear()
    rv._sim.cache_clear()
    t = time.perf_counter()
    r = rv.review(s)
    assert time.perf_counter() - t < 5.0
    assert len(r["timeline"]) >= 12
    t = time.perf_counter()
    rv.review(s)                                    # cached
    assert time.perf_counter() - t < 0.2


def test_money_format():
    assert rv.money(1_234_567) == "CHF 1.23 M"
    assert rv.money(-85_400) == "−CHF 85'000"
    assert rv.money(1_260) == "CHF 1'300"
    assert rv.money_delta(12_000) == "+CHF 12'000"


# ---------------------------------------------------------------- game-style HTML of the analysis page
def test_review_html_blocks(sess):
    import re

    from twin.lifechart import review_view as view
    r = rv.review(sess)
    f = r["facts"]
    css = view.style_block()
    assert css.count("@font-face") == 3 and "Lilita One" in css and "base64," in css and "\n" not in css
    tl = view.timeline_html(r["timeline"], f["start_age"], f["end_age"])
    assert tl.count('class="lr-mark') == len(r["timeline"]) and "\n" not in tl
    for item in r["timeline"]:
        assert f"lr-mark lr-{item['impact']}" in tl and item["title"] in tl
    assert "▲" in tl and "▼" in tl and "Better for your money" in tl and "Costs you money" in tl
    assert "CHF" not in re.sub(r'title="[^"]*"', "", tl)        # numbers only in the tooltip, the chips show arrows
    asp = view.aspects_html(r["positives"], r["negatives"])
    assert asp.count('class="lr-item"') == len(r["positives"]) + len(r["negatives"])
    assert asp.count("<span>BETTER</span>") == len(r["negatives"])
    hero = view.hero_html("YOUR LIFE REVIEW", "sub", r["verdict"])
    assert f">{r['verdict']['grade']}</div>" in hero and r["verdict"]["text"] in hero


def test_timeline_escapes_and_fits_crowded_years():
    from twin.lifechart import review_view as view
    items = [{"age": 25 + i, "emoji": "🎓", "title": f"<b>x{i}</b>", "impact": "up"} for i in range(15)]
    tl = view.timeline_html(items, 25, 85)
    assert "<b>x" not in tl and "&lt;b&gt;x0" in tl
    lanes = [int(x) for x in __import__("re").findall(r"--lane:(\d+)", tl)]
    assert len(lanes) == 15 and max(lanes) < view.MAX_LANES and "min-width:980px" not in tl
    assert view.lanes([0, 0.05, 0.3, 0.31], 0.2) == [0, 1, 0, 1]
    empty = view.timeline_html([], 30, 40, empty="Nothing yet")
    assert "Nothing yet" in empty and "lr-mark" not in empty and "lr-legend" not in empty
