"""デッキの読み書きと構築ルール検証。"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path

BASIC_ENERGY = 5  # cg.api.CardType.BASIC_ENERGY
DECK_SIZE = 60
MAX_COPIES = 4
MAX_ACE_SPEC = 1


class DeckError(Exception):
    """デッキが構築ルールに違反している。"""


@lru_cache(maxsize=1)
def card_table() -> dict:
    """カードIDから CardData への辞書。エンジンから取得する。"""
    from cg import api

    return {c.cardId: c for c in api.all_card_data()}


def load_deck(path: str | Path) -> list[int]:
    text = Path(path).read_text()
    return [int(line) for line in text.split("\n") if line.strip()]


def save_deck(deck: list[int], path: str | Path) -> None:
    Path(path).write_text("\n".join(str(c) for c in deck) + "\n")


def validate_deck(deck: list[int], cards: dict | None = None) -> None:
    """違反があれば DeckError を送出する。何も返さない。"""
    if cards is None:
        cards = card_table()

    if len(deck) != DECK_SIZE:
        raise DeckError(f"デッキは60枚ちょうどでなければならない: {len(deck)}枚")

    unknown = sorted({cid for cid in deck if cid not in cards})
    if unknown:
        raise DeckError(f"存在しないカードID: {unknown}")

    # 同名4枚制限。基本エネルギーは例外。
    counts: Counter[str] = Counter()
    for cid in deck:
        card = cards[cid]
        if card.cardType == BASIC_ENERGY:
            continue
        counts[card.name] += 1
    over = {name: n for name, n in counts.items() if n > MAX_COPIES}
    if over:
        raise DeckError(f"同名カードは4枚まで: {over}")

    if not any(cards[cid].basic for cid in deck):
        raise DeckError("たねポケモンが1枚も入っていない")

    ace = sum(1 for cid in deck if cards[cid].aceSpec)
    if ace > MAX_ACE_SPEC:
        raise DeckError(f"ACE SPEC は1枚まで: {ace}枚")
