"""3D frontend (three.js, bundled locally) as a bidirectional Streamlit component."""
from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_component = components.declare_component("twin3d", path=str(Path(__file__).parent / "frontend3d"))


def creator(config: dict, height: int = 560, key: str = "creator3d") -> dict | None:
    """3D character creator. Returns the chosen config dict once the player changes something."""
    return _component(mode="creator", config=config, height=height, key=key, default=None)


def world(*, avatar: dict, turn: int, prev_turn: int, start_age: int, K: int, badges: dict, life: dict,
          anims: list[dict], finale: bool = False, height: int = 600, key: str = "world3d") -> None:
    """3D island: car drives to station ``turn`` and plays the queued life-event animations."""
    _component(mode="scene", avatar=avatar, turn=turn, prev_turn=prev_turn, start_age=start_age, K=K,
               badges={str(k): v for k, v in badges.items()}, life=life, anims=anims, finale=finale,
               height=height, key=key, default=None)


def game(payload: dict, key: str = "game") -> dict | None:
    """The whole game (title, creator, island, results) as one full-viewport component.

    ``payload`` is the contract object from ``GameSession.payload()``; returns the last action the client sent
    (``{"action": ..., "nonce": ...}``) or None.
    """
    return _component(mode="game", payload=payload, key=key, default=None)
