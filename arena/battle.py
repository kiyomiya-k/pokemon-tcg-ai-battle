"""1戦を最後まで走らせる。

エンジンはプロセスグローバルな battle_ptr を持つため、1プロセスで同時に
1バトルしか扱えない。並列化は Task 7 でマルチプロセスとして行う。
"""

from __future__ import annotations

from arena.policy import Policy


class BattleError(Exception):
    """対戦が正常に完了しなかった。"""


def play_one(
    deck0: list[int],
    deck1: list[int],
    policy0: Policy,
    policy1: Policy,
    max_steps: int = 5000,
) -> int:
    """deck0/policy0 を先攻側として1戦させ、勝者のインデックス（0 or 1）を返す。"""
    from cg import game

    obs, start = game.battle_start(deck0, deck1)
    if obs is None:
        raise BattleError(
            f"battle_start failed: errorPlayer={start.errorPlayer} "
            f"errorType={start.errorType}"
        )
    policies = (policy0, policy1)
    try:
        for _ in range(max_steps):
            cur = obs["current"]
            if cur["result"] != -1:
                return cur["result"]
            if obs["select"] is None:
                raise BattleError("決着していないのに select が None")
            obs = game.battle_select(policies[cur["yourIndex"]](obs))
        raise BattleError(f"{max_steps}手を超えても決着しなかった")
    finally:
        game.battle_finish()
