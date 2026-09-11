# コード解説 — arena/ とパイロットの中身

リポジトリの各ファイルが何をしているかの技術解説です。
前提知識からの説明は [GUIDE_ja.md](GUIDE_ja.md)、結果サマリは [README.md](README.md) へ。

---

## arena/ — 評価ハーネス

「変更を1件入れるごとに400戦回し、信頼区間が分離したときだけ採用する」を実現する装置。
外部ライブラリ依存なし（標準ライブラリのみ）。

### battle.py — 1戦を回す

`play_one(deck0, deck1, policy0, policy1)` が1戦を最後まで実行し、勝者(0/1)を返す。

エンジン（`cg`）は**プロセスグローバルな状態**を持つため、1プロセスで同時に扱えるバトルは1つだけ。
これが次の match.py の設計を決めている。

### match.py — 並列対戦と統計判定（このリポジトリの心臓部）

```python
def wilson_interval(wins, n, z=1.96):
    """二項比率の Wilson スコア信頼区間"""
    p = wins / n
    denom  = 1 + z*z/n
    centre = p + z*z/(2*n)
    spread = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return ((centre - spread)/denom, (centre + spread)/denom)

def is_better(result):
    """信頼区間の下限が 0.5 を超えていれば「有意に勝ち越し」"""
    return result.ci_low > 0.5
```

設計上のポイント:

- **先攻後攻をペアで回す**。`pairs=200` は「同じ組み合わせを先攻・後攻で1回ずつ×200」= 400戦。
  先攻有利のバイアスが差し引きで消える
- **並列化はスレッドではなくプロセス**（エンジンがグローバル状態を持つため）。
  ワーカープロセスは方策とデッキを初回だけ読み込みキャッシュする
- 通常の正規近似ではなく **Wilson 区間**を使う。試合数が少ない・勝率が偏っている場合でも
  区間が破綻しない

### tournament.py — プール総当たり

`evaluate_deck()` が1つのデッキを相手プール全体に当て、平均勝率・最悪勝率・最悪の相手を返す。
「平均は良いが特定の型に極端に弱い」を検出するために最悪勝率を持っている
（実際、Crustle 相手の勝率 .08 はこれで把握していた）。

### policy.py / deck.py — 任意のエージェントの読み込み

Kaggle 提出形式の `main.py` / `deck.csv` をそのまま方策として読み込む。
`main.py` は自分のディレクトリの `deck.csv` を相対パスで読む実装が多いため、
読み込みと推論の間だけ `chdir` する処理が入っている。
これにより**他人の公開エージェントも無改造で対戦相手にできる**。

---

## policies/ — パイロットの中身

### 基本構造：点数表 + 理由文字列

エンジンから渡される「選べる行動リスト」の全要素に `score_option()` が点数をつけ、上位を選ぶ。
**すべての点数に理由の文字列が付く**のがこの実装の要点。

```python
return 90000, "Teal Dance"                    # 特性: エネ+1ドロー+1。毎ターン全個体で使う
return 21500, "Boss: bypass Crustle wall"     # 壁は無視してベンチを引きずり出す
return 16000, "Hero's Cape: break 270"        # HP+100 で Mega Brave 270 を耐える
return max(50, dmg), "Myriad Leaf Shower"     # 攻撃 = 打点そのまま → 常に最後に回る
```

攻撃の点数を打点そのもの（最大でも360程度）にすることで、
**セットアップ系の行動（1,000〜90,000点）をすべて消化してから殴る**挙動が点数表だけで実現される。
打点が場のエネルギー数に比例するデッキでは、これが常に正しい手順になる。

理由文字列は後の**敗因解剖**を可能にした。負けた480戦の各ターンについて
「そのときエージェントが何を考えてその手を選んだか」がログから全部読める。

### detect_threat() — 脅威検知6モード

相手の場のカードIDから相手アーキタイプを毎ターン判定し、戦い方を切り替える。

| モード | 相手 | 対応 |
|---|---|---|
| metal | Archaludon | Metal Defender 220 の確殺ライン対策。HP カード優先 |
| fighting | Mega Lucario | Mega Brave 270 は連発不可 → 相手の前ターンの技を記憶し、撃った直後だけ強気に出る |
| alakazam | Alakazam | 打点 = 相手の手札×20 → Judge で手札4枚に戻すと上限80 に抑まる |
| mill | Crustle / Great Tusk | 山札切れ狙い → 自分のドローを絞り、攻撃レースに切り替え |
| dark | Grimmsnarl | 弱点2倍の一撃圏 → エネ破壊カードを使わない（相手のエネは自分の燃料） |
| generic | その他 | 標準の点数表 |

### バージョン間の差分

| 版 | 差分 | 結果 |
|---|---|---|
| `ogerpon`(v1) | 初期実装 | LB 652。600-799帯の「堀」で沈没 |
| `ogerpon2c` | **デッキ4枠入れ替え**（Grow 2→4 / Lively 2→4 / 草エネ−2 / Harlequin, Briar カット）+ Judge 格上げ | LB 853.8。全列改善 |
| `ogerpon2f` | **+16行**: Crustle への攻撃を0点化 / Boss で壁迂回 / 先攻選択 | LB 872.7 → **最終 942.6** ★ |
| `ogerpon2g` | ミラー対策のベンチ・エネ貯金 | **未提出**。400戦で .487 → 棄却。「もっともらしいが劣化」の実例として同梱 |
| `ogerpon2h` | −Hammer +Briar（相手残りサイド2でテラを倒すと+1枚 = レースで1ターン盗む） | 最終 878.9。もう1つのアクティブ枠 |

2c → 2f の差分は `diff policies/ogerpon2c/main.py policies/ogerpon2f/main.py` で実際に16行だけなのが確認できる。

---

## 実行手順（ローカル）

```bash
# 1. エンジンを取得（コンペ規約により同梱していない）
kaggle competitions download -c pokemon-tcg-ai-battle \
  -f "sample_submission/sample_submission/cg/__init__.py" ...
# cg/{__init__,api,game,sim,utils}.py と libcg.* をリポジトリ直下 cg/ に配置

# 2. A/B テスト
PYTHONPATH=. python3 -c "
from arena.match import PolicySpec, run_match, is_better
a = PolicySpec('2f', 'policies/ogerpon2f/main.py', 'policies/ogerpon2f/deck.csv')
b = PolicySpec('2g', 'policies/ogerpon2g/main.py', 'policies/ogerpon2g/deck.csv')
r = run_match(a, b, pairs=200, workers=8)
print(r.winrate, (r.ci_low, r.ci_high), 'SHIP' if is_better(r) else 'REJECT')
"
```

Apple Silicon なら `libcg-arm64.so`、x86 Linux なら `libcg.so`、Windows なら `cg.dll` が使われる。
400戦は 8 ワーカーで数秒〜十数秒。

Kaggle 上での再現は公開データセット
[ogerpon-tcg-agent-ab-harness](https://www.kaggle.com/datasets/kiyomiyak/ogerpon-tcg-agent-ab-harness) を参照。
