"""複数戦をマルチプロセスで回し、勝率と信頼区間を返す。

エンジンはプロセスグローバルな状態を持つので、並列化はスレッドではなく
プロセスで行う。ワーカープロセスは自分の中で方策を1度だけ読み込む。
"""

from __future__ import annotations

import math
import multiprocessing as mp
import os
from dataclasses import dataclass

from arena.battle import BattleError, play_one
from arena.deck import load_deck
from arena.policy import load_policy


@dataclass(frozen=True)
class PolicySpec:
    """1人分の (方策, デッキ) の組。プロセス間で渡すのでパスだけを持つ。"""

    name: str
    main_py: str
    deck_csv: str


@dataclass(frozen=True)
class MatchResult:
    wins: int
    games: int
    winrate: float
    ci_low: float
    ci_high: float
    errors: int


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """二項比率の Wilson スコア信頼区間。n=0 のときは (0.0, 1.0)。"""
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((centre - spread) / denom, (centre + spread) / denom)


def is_better(result: MatchResult) -> bool:
    """信頼区間の下限が 0.5 を超えていれば「有意に勝ち越し」と判定する。"""
    return result.ci_low > 0.5


_CACHE: dict = {}


def _get(spec: PolicySpec):
    """ワーカープロセス内で方策とデッキを1度だけ読み込む。"""
    key = (spec.main_py, spec.deck_csv)
    if key not in _CACHE:
        _CACHE[key] = (load_policy(spec.main_py), load_deck(spec.deck_csv))
    return _CACHE[key]


def _play(args: tuple[PolicySpec, PolicySpec, bool]) -> int:
    """1戦を実行し、a から見た結果を返す。1=a の勝ち、0=b の勝ち、-1=エラー。"""
    a, b, a_is_first = args
    pol_a, deck_a = _get(a)
    pol_b, deck_b = _get(b)
    try:
        if a_is_first:
            return 1 if play_one(deck_a, deck_b, pol_a, pol_b) == 0 else 0
        return 1 if play_one(deck_b, deck_a, pol_b, pol_a) == 1 else 0
    except BattleError:
        return -1


def run_match(a: PolicySpec, b: PolicySpec, pairs: int, workers: int = 0) -> MatchResult:
    """a と b を pairs ペア（= pairs*2 戦）対戦させ、a 視点の結果を返す。

    1ペアは「a が先攻の1戦」と「b が先攻の1戦」の2戦。先攻有利を打ち消す。
    """
    if workers <= 0:
        workers = max(1, (os.cpu_count() or 2) - 1)

    jobs = []
    for _ in range(pairs):
        jobs.append((a, b, True))
        jobs.append((a, b, False))

    if workers == 1:
        outcomes = [_play(j) for j in jobs]
    else:
        ctx = mp.get_context("spawn")
        with ctx.Pool(workers) as pool:
            outcomes = pool.map(_play, jobs)

    errors = sum(1 for o in outcomes if o == -1)
    wins = sum(1 for o in outcomes if o == 1)
    games = len(outcomes) - errors
    winrate = wins / games if games else 0.0
    lo, hi = wilson_interval(wins, games)
    return MatchResult(wins=wins, games=games, winrate=winrate,
                       ci_low=lo, ci_high=hi, errors=errors)
