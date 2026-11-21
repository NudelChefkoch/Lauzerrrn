"""Später entstandene Daten einlesen und die Aussagen aktualisieren (twin.daten_update)."""
import numpy as np
import pandas as pd
import pytest

from twin.calibration import calibrate
from twin.daten_update import aktualisiere_aus_daten, lese_neue_daten, nachkalibrieren
from twin.session import GameSession

C = calibrate()
ALEXIA = C.persons["P00001"]


def _months(n: int, flow: float, start_cash: float, noise: float = 0.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    months = pd.period_range("2027-01", periods=n, freq="M").astype(str)
    sp = C.states[ALEXIA.state]
    m = np.array([int(x[5:7]) for x in months]) - 1
    x = flow + sp.seasonal[m] + noise * rng.standard_normal(n)
    return pd.DataFrame({"profile_id": "P00001", "month": months, "net_transactions_chf": x,
                         "closing_cash_chf": start_cash + np.cumsum(x)})


def test_reads_and_validates():
    df = lese_neue_daten(_months(6, -500, 8000), "P00001")
    assert len(df) == 6 and df["month"].is_monotonic_increasing
    with pytest.raises(ValueError):
        lese_neue_daten(pd.DataFrame({"month": ["2027-01"]}))
    two = pd.concat([_months(3, 0, 0), _months(3, 0, 0).assign(profile_id="P00002")])
    with pytest.raises(ValueError):
        lese_neue_daten(two, "IST")


def test_mu_moves_towards_new_data_and_state_is_current():
    df = _months(24, ALEXIA.mu + 600, 9000)
    neu = nachkalibrieren(ALEXIA, lese_neue_daten(df), C)
    assert ALEXIA.mu < neu.mu < ALEXIA.mu + 600 + 1e-6        # posterior between prior and data
    assert neu.mu_se < ALEXIA.mu_se                             # more data -> less uncertainty
    assert neu.cash == pytest.approx(df["closing_cash_chf"].iloc[-1])
    assert neu.age == ALEXIA.age + 2
    assert all(g[2] == old[2] - 24 for g, old in zip(neu.goals, [g for g in ALEXIA.goals if g[2] > 24]))


def test_update_produces_statements_and_better_outlook():
    upd = aktualisiere_aus_daten(ALEXIA, _months(12, ALEXIA.mu + 800, 8000), calib=C, n_paths=300)
    assert upd.monate == 12 and upd.person.mu > ALEXIA.mu
    assert upd.nachher["median_ende"] > upd.vorher["median_ende"] - 1e-6 or upd.nachher["netto_jetzt"] > 0
    assert any(a.startswith("Typischer Monat") and "besser" in a for a in upd.aussagen)
    assert any("Kredit" in a for a in upd.aussagen)


def test_session_hook_restarts_with_updated_person():
    s = GameSession()
    s.start(pid="P00001", seed=4)
    s.choose("stay")
    upd = s.aktualisiere_mit_daten(_months(6, ALEXIA.mu, 8000), n_paths=200)
    assert s.phase == "play" and s.turn == 0 and s.person == upd.person
    assert s.payload()["play"]["hud"]["cash"] == pytest.approx(upd.person.cash)
