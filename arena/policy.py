"""対戦方策。obs（dict）を受け取り、選択肢インデックスのリストを返す。"""

from __future__ import annotations

import importlib.util
import os
import random
from pathlib import Path
from typing import Callable

Policy = Callable[[dict], list[int]]


def random_policy(obs: dict) -> list[int]:
    """選択肢から maxCount 個をランダムに選ぶ。arena の下限基準線。"""
    sel = obs["select"]
    return random.sample(range(len(sel["option"])), sel["maxCount"])


def load_policy(main_py: str | Path) -> Policy:
    """任意の main.py から agent 関数を読み込む。

    main.py 側は deck.csv をカレントディレクトリから読むことがあるので、
    呼び出しの間だけ main.py のあるディレクトリに chdir する。
    """
    path = Path(main_py).resolve()
    spec = importlib.util.spec_from_file_location(f"policy_{path.parent.name}", path)
    module = importlib.util.module_from_spec(spec)
    cwd = os.getcwd()
    os.chdir(path.parent)
    try:
        spec.loader.exec_module(module)
    finally:
        os.chdir(cwd)

    inner = module.agent
    workdir = str(path.parent)

    def policy(obs: dict) -> list[int]:
        cwd = os.getcwd()
        os.chdir(workdir)
        try:
            return inner(obs)
        finally:
            os.chdir(cwd)

    return policy
