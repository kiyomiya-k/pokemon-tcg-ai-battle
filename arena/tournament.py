"""デッキ候補を対戦相手プール全体に対して評価し、順位づけする。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from arena.match import MatchResult, PolicySpec, run_match


@dataclass(frozen=True)
class DeckScore:
    deck: str
    mean_winrate: float
    worst_winrate: float
    worst_opponent: str
    games: int
    per_opponent: dict[str, MatchResult] = field(default_factory=dict)


def load_opponents(root: str | Path) -> list[PolicySpec]:
    """opponents/<name>/{main.py,deck.csv} を PolicySpec のリストとして読む。"""
    root = Path(root)
    specs = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        main_py, deck_csv = d / "main.py", d / "deck.csv"
        if main_py.exists() and deck_csv.exists():
            specs.append(PolicySpec(name=d.name, main_py=str(main_py),
                                    deck_csv=str(deck_csv)))
    return specs


def evaluate_deck(
    deck_csv: str | Path,
    policy_main_py: str | Path,
    opponents: list[PolicySpec],
    pairs: int,
    workers: int = 0,
) -> DeckScore:
    """1つのデッキをプール全体に当てて、平均勝率と最悪勝率を返す。"""
    me = PolicySpec(name=Path(deck_csv).stem, main_py=str(policy_main_py),
                    deck_csv=str(deck_csv))
    per = {opp.name: run_match(me, opp, pairs=pairs, workers=workers)
           for opp in opponents}
    rates = {name: r.winrate for name, r in per.items()}
    worst_opponent = min(rates, key=rates.get)
    return DeckScore(
        deck=me.name,
        mean_winrate=sum(rates.values()) / len(rates),
        worst_winrate=rates[worst_opponent],
        worst_opponent=worst_opponent,
        games=sum(r.games for r in per.values()),
        per_opponent=per,
    )


def rank_decks(scores: list[DeckScore]) -> list[DeckScore]:
    """平均勝率の降順。同点なら最悪勝率の高いほうを上に置く。

    平均だけで選ぶと、特定の1体を完封するだけで他に弱い構築を選んでしまう。
    """
    return sorted(scores, key=lambda s: (s.mean_winrate, s.worst_winrate),
                  reverse=True)
