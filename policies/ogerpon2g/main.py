"""Teal Mask Ogerpon ex — mono-attacker rule-based agent, v2 (threat-aware)

v1 result: LB 652 — died in the 600-799 climb vs Metal/Fighting/Alakazam.
v2 adds detect_threat() modes with mechanically-derived counters:

  metal (Archaludon):  Metal Defender 220 vs base HP210 = OHKO. Grow Grass
      (+20 -> 230) breaks the OHKO; Hammer to 2 energy blocks the attack
      (cost 3); their 3 energy feeds our damage anyway.
  fighting (M. Lucario): Mega Brave 270 cannot repeat. Sacrifice-cycle on
      270 turns (promote empty shell), strike on Aura Jab turns; Cape (310)
      breaks 270; Hammer below 2 blocks Mega Brave.
  alakazam: Powerful Hand = 20 x their hand. Judge caps it at 80.
  mill (Great Tusk/Crustle): stop digging early, race with attacks.
  dark (Grimmsnarl): unchanged v1 burst mode (weakness x2 already 90%).

Deck: the 222-game ladder list (references/ogerpon-deck2.csv), unmodified.
Score system mirrors llcc_stable: setup/play/attach 1000..90000, attack =
damage so it goes last, negative = skip when above minCount.
"""

import os
import random
import sys

try:
    ROOT = __file__
except NameError:
    ROOT = None
CG_PATH = "/kaggle_simulations/agent"
for p in ([os.path.dirname(os.path.abspath(ROOT))] if ROOT else []) + [CG_PATH]:
    if p and p not in sys.path and os.path.isdir(p):
        sys.path.insert(0, p)

from cg.api import (
    AreaType,
    EnergyType,
    LogType,
    OptionType,
    SelectContext,
    all_card_data,
    to_observation_class,
)

# ── Card IDs ──

OGERPON_EX = 96
GRASS_ENERGY = 1
GROW_GRASS = 18

BUG_CATCHING_SET = 1094
ENERGY_RETRIEVAL = 1118
ENERGY_SEARCH = 1119
CRUSHING_HAMMER = 1120
POKEGEAR = 1122
TERA_ORB = 1127
TOOL_SCRAPPER = 1137
JUMBO_ICE_CREAM = 1147
HERO_CAPE = 1159
BOSS = 1182
BRIAR = 1201
JUDGE = 1213
NS_PLAN = 1221
HARLEQUIN = 1223
LILLIE = 1227
LIVELY_STADIUM = 1251

ENERGY_IDS = {GRASS_ENERGY, GROW_GRASS}
DRAW_SUPPORTERS = {LILLIE, JUDGE, HARLEQUIN}

CARD_DB = {c.cardId: c for c in all_card_data()}

MYRIAD_LEAF_SHOWER = 120

# ── Threat lines (opponent board) ──

METAL_LINE = {169, 190}                 # Duraludon / Archaludon ex (Metal Defender 220)
FIGHTING_LINE = {677, 678}              # Riolu? / Mega Lucario ex (Mega Brave 270)
ALAKAZAM_LINE = {65, 66, 741, 742, 743}  # Abra..Alakazam (Powerful Hand = 20 x hand)
MILL_LINE = {58, 344, 345}              # Great Tusk / Dwebble / Crustle (deck-out)
DARK_LINE = {646, 647, 648}             # Marnie's Grimmsnarl line (grass-weak prey)

MEGA_BRAVE = 983                        # attack id (cannot repeat next turn)

# opponent attack cost floor per threat (Hammer blocking target)
_ATTACK_COST = {"metal": 3, "fighting": 2, "mirror": 3}


def detect_threat(obs):
    opp = opp_state(obs)
    ids = {p.id for p in (opp.active + opp.bench) if p}
    if ids & METAL_LINE:
        return "metal"
    if ids & FIGHTING_LINE:
        return "fighting"
    if ids & ALAKAZAM_LINE:
        return "alakazam"
    if ids & MILL_LINE:
        return "mill"
    if ids & DARK_LINE:
        return "dark"
    if OGERPON_EX in ids:
        return "mirror"
    return "generic"


# Track opponent's last-turn attack via logs (llcc_stable mechanism)
_opp_last_attack_id = None
_cur_turn_logs = []


def _update_opp_attack_tracking(obs):
    global _opp_last_attack_id, _cur_turn_logs
    yi = obs.current.yourIndex
    for entry in obs.logs:
        if entry.type == LogType.TURN_END:
            for prev in _cur_turn_logs:
                if prev.type == LogType.ATTACK and getattr(prev, 'playerIndex', yi) != yi:
                    _opp_last_attack_id = prev.attackId
            _cur_turn_logs.clear()
        else:
            _cur_turn_logs.append(entry)


def mega_brave_incoming(obs):
    """True on turns where the opponent CAN use Mega Brave (didn't use it last turn)."""
    return detect_threat(obs) == "fighting" and _opp_last_attack_id != MEGA_BRAVE


# ── Board helpers (llcc conventions) ──

def read_deck_csv():
    fp = "deck.csv"
    if not os.path.exists(fp):
        fp = "/kaggle_simulations/agent/deck.csv"
    with open(fp) as f:
        return [int(line) for line in f.read().strip().split("\n")]


def get_card(obs, area, index, player_index):
    if area is None or index is None:
        return None
    ps = obs.current.players[player_index]
    if area == AreaType.DECK and obs.select and obs.select.deck is not None:
        return obs.select.deck[index] if index < len(obs.select.deck) else None
    if area == AreaType.HAND and ps.hand is not None:
        return ps.hand[index] if index < len(ps.hand) else None
    if area == AreaType.DISCARD:
        return ps.discard[index] if index < len(ps.discard) else None
    if area == AreaType.ACTIVE:
        return ps.active[index] if index < len(ps.active) else None
    if area == AreaType.BENCH:
        return ps.bench[index] if index < len(ps.bench) else None
    if area == AreaType.PRIZE:
        return ps.prize[index] if index < len(ps.prize) else None
    if area == AreaType.STADIUM:
        return obs.current.stadium[index] if index < len(obs.current.stadium) else None
    if area == AreaType.LOOKING and obs.current.looking is not None:
        return obs.current.looking[index] if index < len(obs.current.looking) else None
    return None


def option_card(obs, opt):
    yi = obs.current.yourIndex
    pi = opt.playerIndex if opt.playerIndex is not None else yi
    if opt.type == OptionType.PLAY:
        return get_card(obs, AreaType.HAND, opt.index, pi)
    return get_card(obs, opt.area, opt.index, pi)


def option_target(obs, opt):
    if opt.inPlayArea is None or opt.inPlayIndex is None:
        return None
    return get_card(obs, opt.inPlayArea, opt.inPlayIndex, obs.current.yourIndex)


def my_state(obs):
    return obs.current.players[obs.current.yourIndex]


def opp_state(obs):
    return obs.current.players[1 - obs.current.yourIndex]


def active_pokemon(obs):
    ps = my_state(obs)
    return ps.active[0] if ps.active else None


def opp_active_pokemon(obs):
    ps = opp_state(obs)
    return ps.active[0] if ps.active else None


def opp_bench_pokemon(obs):
    return [p for p in opp_state(obs).bench if p]


def my_bench_pokemon(obs):
    return [p for p in my_state(obs).bench if p]


def all_my_pokemon(obs):
    ps = my_state(obs)
    return [p for p in (ps.active + ps.bench) if p]


def hand_ids(obs):
    hand = my_state(obs).hand
    return [c.id for c in hand if c] if hand else []


def energy_count(pokemon):
    if pokemon is None:
        return 0
    if getattr(pokemon, "energyCards", None) is not None:
        return len(pokemon.energyCards)
    return len(getattr(pokemon, "energies", []) or [])


def has_tool(pokemon):
    return bool(getattr(pokemon, "tools", []) or [])


def damage_on(pokemon):
    if pokemon is None:
        return 0
    return max(0, getattr(pokemon, "maxHp", pokemon.hp) - pokemon.hp)


def prize_value(pokemon):
    data = CARD_DB.get(pokemon.id) if pokemon else None
    if data and getattr(data, "megaEx", False):
        return 3
    if data and getattr(data, "ex", False):
        return 2
    return 1


def is_grass_weak(pokemon):
    if pokemon is None:
        return False
    data = CARD_DB.get(pokemon.id)
    w = getattr(data, "weakness", None) if data else None
    if w is None:
        return False
    return int(getattr(w, "value", w)) == int(EnergyType.GRASS)


# ── Damage math ──

CRUSTLE_WALL = 345  # ability: prevents ALL damage from opponent's Pokemon ex


def shower_damage(obs, my_energy=None, target=None):
    """Myriad Leaf Shower vs `target` assuming it sits in the Active Spot."""
    if my_energy is None:
        my_energy = energy_count(active_pokemon(obs))
    if target is None:
        target = opp_active_pokemon(obs)
    if target is not None and target.id == CRUSTLE_WALL:
        return 0  # we are all ex: Crustle is immune to us
    dmg = 30 + 30 * (my_energy + energy_count(target))
    return dmg * 2 if is_grass_weak(target) else dmg


def can_attack(obs, pokemon=None):
    if pokemon is None:
        pokemon = active_pokemon(obs)
    return pokemon is not None and pokemon.id == OGERPON_EX and energy_count(pokemon) >= 3


def grass_in_hand(obs):
    return sum(1 for c in (my_state(obs).hand or []) if c and c.id == GRASS_ENERGY)


def ogerpon_in_play(obs):
    return sum(1 for p in all_my_pokemon(obs) if p.id == OGERPON_EX)


def best_backup(obs):
    """Benched Ogerpon with the most energy (next attacker)."""
    bench = [p for p in my_bench_pokemon(obs) if p.id == OGERPON_EX]
    return max(bench, key=energy_count) if bench else None


# ── Scoring ──

def score_setup(obs, opt):
    ctx = obs.select.context
    card = option_card(obs, opt)
    cid = card.id if card else None

    if ctx == SelectContext.MULLIGAN:
        return (10000, "no mulligan") if opt.type == OptionType.NO else (0, "mulligan")
    if ctx == SelectContext.IS_FIRST:
        return (10000, "choose first: ramp head start") if opt.type == OptionType.YES else (0, "second")
    if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
        return (100000, "Active: Ogerpon") if cid == OGERPON_EX else (0, "unknown")
    if ctx == SelectContext.SETUP_BENCH_POKEMON:
        # Mono-deck: an empty bench loses to one KO. Bench one spare.
        benched = len([p for p in my_state(obs).bench if p])
        if cid == OGERPON_EX and benched < 1:
            return 5000, "setup bench: 1 spare Ogerpon"
        return -10000, "setup bench: enough"
    return 0, "non-setup"


def score_play(obs, opt):
    card = option_card(obs, opt)
    cid = card.id if card else None
    ids = hand_ids(obs)
    deck_count = my_state(obs).deckCount
    opp_act = opp_active_pokemon(obs)

    # ── Pokemon ──
    if cid == OGERPON_EX:
        benched = len(my_bench_pokemon(obs))
        if benched < 2:
            return 22000, "bench spare Ogerpon"
        if benched < 3 and ids.count(OGERPON_EX) > 1:
            return 3000, "bench 3rd Ogerpon"
        return -500, "bench full enough"

    # ── Stadium ──
    if cid == LIVELY_STADIUM:
        # +30 HP to Basics. We are all Basic; evolution decks profit less.
        stadium = obs.current.stadium[0] if obs.current.stadium else None
        if stadium is not None and getattr(stadium, "id", None) == LIVELY_STADIUM:
            return -500, "stadium already ours"
        if detect_threat(obs) in ("metal", "fighting"):
            return 19500, "Lively Stadium: HP breakpoint vs OHKO threat"
        return 15000, "play Lively Stadium"

    # ── Items ──
    if cid in (BUG_CATCHING_SET, ENERGY_SEARCH, TERA_ORB, POKEGEAR):
        dig_floor = 15 if detect_threat(obs) == "mill" else 6
        if deck_count <= dig_floor:
            return -2000, "deck low: stop digging"
        if cid == ENERGY_SEARCH:
            return 20000, "Energy Search"
        if cid == TERA_ORB:
            total_seen = ogerpon_in_play(obs) + ids.count(OGERPON_EX)
            if total_seen >= 3:
                return -500, "Tera Orb: enough Ogerpon"
            return 20000, "Tera Orb: fetch Ogerpon"
        if cid == POKEGEAR:
            if obs.current.supporterPlayed:
                return 1500, "Pokegear: supporter used, dig for next turn"
            return 19000, "Pokegear"
        return 20000, "Bug Catching Set"

    if cid == CRUSHING_HAMMER:
        # Own damage feeds on opponent energy: don't strip it when we already KO.
        if opp_act and can_attack(obs) and shower_damage(obs) >= opp_act.hp:
            return -500, "Hammer: already lethal, keep their energy"
        threat = detect_threat(obs)
        cost = _ATTACK_COST.get(threat)
        if cost and opp_act and 0 < energy_count(opp_act) <= cost:
            # Coin-flip chance to push them below attack cost = a full blocked turn.
            return 21000, f"Hammer: block {threat} attack (cost {cost})"
        best = opp_act if energy_count(opp_act) > 0 else None
        for p in opp_bench_pokemon(obs):
            if energy_count(p) > energy_count(best) if best else energy_count(p) > 0:
                best = p
        if best is None:
            return -500, "Hammer: no energy to strip"
        return 18000, "Crushing Hammer"

    if cid == JUMBO_ICE_CREAM:
        act = active_pokemon(obs)
        heal_floor = 40 if detect_threat(obs) in ("metal", "fighting", "mirror") else 60
        if act and energy_count(act) >= 3 and damage_on(act) >= heal_floor:
            return 20000, "Ice Cream heal"
        return -500, "Ice Cream: save"

    if cid == TOOL_SCRAPPER:
        opp_tools = any(has_tool(p) for p in ([opp_act] if opp_act else []) + opp_bench_pokemon(obs))
        if opp_tools:
            return 17000, "Tool Scrapper"
        return -500, "Tool Scrapper: no target"

    if cid == ENERGY_RETRIEVAL:
        disc_energy = sum(1 for c in (my_state(obs).discard or []) if c and c.id == GRASS_ENERGY)
        if disc_energy >= 1 and grass_in_hand(obs) == 0:
            return 18000, "Energy Retrieval"
        return -500, "Energy Retrieval: save"

    # ── Supporters ──
    if cid in (BOSS, BRIAR, LILLIE, JUDGE, HARLEQUIN, NS_PLAN):
        if obs.current.supporterPlayed:
            return -1000, "Supporter already used"

    if cid == BOSS:
        act = active_pokemon(obs)
        my_e = energy_count(act) if act else 0
        remaining = len(my_state(obs).prize)
        if not can_attack(obs):
            return -500, "Boss: cannot attack"
        if detect_threat(obs) == "mill" and opp_act and opp_act.id == 345:
            # Wall in front is unkillable for us: Boss out a killable 1-prizer.
            for target in opp_bench_pokemon(obs):
                if shower_damage(obs, my_energy=my_e, target=target) >= target.hp:
                    return 21500, "Boss: bypass Crustle wall"
        # Never Boss away a KO we already have, unless bench target wins the game.
        active_lethal = opp_act and shower_damage(obs) >= opp_act.hp
        best_score = -500
        best_reason = "save Boss"
        for target in opp_bench_pokemon(obs):
            eff = shower_damage(obs, my_energy=my_e, target=target)
            hp_bonus = 30 if _lively_up(obs) else 0
            if eff >= target.hp + hp_bonus:
                pv = prize_value(target)
                if pv >= remaining:
                    return 21000, "LETHAL Boss"
                s = 5000 + pv * 1500 + energy_count(target) * 300
                if s > best_score:
                    best_score = s
                    best_reason = "Boss: pull killable loaded target"
        if active_lethal and best_score < 21000:
            if prize_value(opp_act) >= 2 or best_score < 8000:
                return -500, "Boss: active KO is fine"
        return best_score, best_reason

    if cid == BRIAR:
        if len(opp_state(obs).prize) == 2 and can_attack(obs) and opp_act and shower_damage(obs) >= opp_act.hp:
            return 20500, "Briar: bonus prize on KO"
        return -500, "Briar: condition not met"

    if cid == NS_PLAN:
        # Move 2 bench energy to active: +60 (x2 vs weak) — use when it flips lethal.
        act = active_pokemon(obs)
        backup = best_backup(obs)
        if act and opp_act and backup and energy_count(backup) >= 1:
            move = min(2, energy_count(backup))
            now = shower_damage(obs)
            then = shower_damage(obs, my_energy=energy_count(act) + move)
            if now < opp_act.hp <= then:
                return 20800, "N's Plan: flip to lethal"
            if energy_count(act) < 3 and energy_count(act) + move >= 3:
                return 16000, "N's Plan: enable attack"
        return -500, "N's Plan: save"

    if cid == LILLIE:
        if detect_threat(obs) == "mill":
            # Shuffle-hand-draw-6: net deck change = hand - 6. Only deck-positive uses.
            if len(ids) - 1 >= 7:
                return 16000, "Lillie: refill deck vs mill"
            return -1000, "Lillie: would burn deck vs mill"
        if len(ids) <= 4:
            return 16000, "Lillie: refresh small hand"
        return 2000, "Lillie"

    if cid == JUDGE:
        opp_hand = opp_state(obs).handCount
        if detect_threat(obs) == "alakazam" and opp_hand >= 5:
            # Powerful Hand = 20 x their hand: Judge caps the next hit at 80.
            return 19000, "Judge: cap Powerful Hand"
        if opp_hand >= 6 and len(ids) <= 5:
            return 15000, "Judge: strip big hand"
        if len(ids) <= 3:
            return 9000, "Judge: refresh"
        return -500, "Judge: save"

    if cid == HARLEQUIN:
        if len(ids) <= 2:
            return 8000, "Harlequin: desperate refresh"
        return -500, "Harlequin: save"

    return 1000, "generic play"


def _lively_up(obs):
    st = obs.current.stadium[0] if obs.current.stadium else None
    return st is not None and getattr(st, "id", None) == LIVELY_STADIUM


def score_attach(obs, opt):
    card = option_card(obs, opt)
    target = option_target(obs, opt)
    cid = card.id if card else None
    tid = target.id if target else None

    if cid == HERO_CAPE:
        if tid == OGERPON_EX and target and not has_tool(target):
            area_bonus = 2000 if opt.inPlayArea == AreaType.ACTIVE else 0
            threat = detect_threat(obs)
            if threat == "fighting":
                # 210+100=310 survives Mega Brave 270
                return 16000 + area_bonus, "Hero's Cape: break 270"
            if threat == "mirror":
                # +100 HP is the only asymmetric edge in the mirror race
                return 16000 + area_bonus, "Hero's Cape: mirror edge"
            if threat == "metal":
                return 14000 + area_bonus, "Hero's Cape: break 220"
            return 12000 + area_bonus, "Hero's Cape on Ogerpon"
        return -1000, "save Hero's Cape"

    if cid not in ENERGY_IDS:
        return -500, "skip non-energy attach"
    if obs.current.energyAttached:
        return -1000, "already attached"
    score = attach_target_score(obs, target, opt.inPlayArea)
    # Grow Grass (+20 HP) breaks Metal Defender's OHKO (220 vs 230): spend it
    # on the Active vs OHKO threats, keep plain grass for Teal Dance.
    if cid == GROW_GRASS and target is not None and target.id == OGERPON_EX:
        if detect_threat(obs) in ("metal", "fighting") and opt.inPlayArea == AreaType.ACTIVE:
            score += 5000
    return score, "attach energy"


def attach_target_score(obs, target, area):
    """Manual attach: active first until attack-ready+1, then charge backup."""
    if target is None or target.id != OGERPON_EX:
        return -500
    e = energy_count(target)
    act = active_pokemon(obs)
    is_active = area == AreaType.ACTIVE
    score = 5000
    if is_active:
        if e < 3:
            score += 12000        # reach attack cost first
        elif detect_threat(obs) == "mirror":
            # Mirror: sums are symmetric — bank energy on the bench instead and
            # burst it in with N's Plan on the lethal turn.
            score += 1500
        elif e < 6:
            score += 6000         # damage still scales
        else:
            score += 1000
        # Active about to die: prefer charging the backup instead.
        opp_act = opp_active_pokemon(obs)
        if act and opp_act and act.hp <= 90:
            score -= 8000
    else:
        if e < 3:
            score += 7000         # backup toward attack-ready
        else:
            score += 2000
    return score


def score_retreat(obs, opt):
    act = active_pokemon(obs)
    backup = best_backup(obs)
    if act and backup and energy_count(act) == 0 and energy_count(backup) >= 3:
        return 12000, "retreat shell to charged backup"
    if act and backup and act.hp <= 60 and energy_count(backup) >= 3 and energy_count(act) >= 1:
        return 8000, "retreat dying active"
    return -100, "avoid retreat"


def retreat_cost_of(pokemon):
    data = CARD_DB.get(pokemon.id) if pokemon else None
    return getattr(data, "retreatCost", 1) if data else 1


def score_to_hand(obs, opt):
    """Bug Catching Set picks, Pokegear picks, generic takes."""
    card = option_card(obs, opt)
    cid = card.id if card else opt.cardId
    ids = hand_ids(obs)

    if cid == OGERPON_EX:
        total_seen = ogerpon_in_play(obs) + ids.count(OGERPON_EX)
        return (22000 if total_seen < 3 else 4000), "take Ogerpon"
    if cid == GRASS_ENERGY:
        need = 2 - grass_in_hand(obs)
        return (20000 if need > 0 else 8000), "take energy"
    if cid == GROW_GRASS:
        return 18000, "take Grow Grass"
    if cid == BOSS:
        return 9000, "take Boss"
    if cid in DRAW_SUPPORTERS:
        sup_in_hand = sum(1 for c in ids if c in DRAW_SUPPORTERS or c == BOSS)
        return (12000 if sup_in_hand == 0 else 2000), "take supporter"
    if cid in (BUG_CATCHING_SET, ENERGY_SEARCH, TERA_ORB):
        return 6000, "take search"
    return 1000, "generic take"


def score_discard(obs, opt):
    card = option_card(obs, opt)
    cid = card.id if card else opt.cardId
    ids = hand_ids(obs)
    if cid == HARLEQUIN:
        return 10000, "discard Harlequin"
    if cid == LIVELY_STADIUM and _lively_up(obs):
        return 9000, "discard spare stadium"
    if cid == GRASS_ENERGY and grass_in_hand(obs) > 2:
        return 8000, "discard surplus energy"
    if cid in (POKEGEAR, ENERGY_RETRIEVAL):
        return 7000, "discard utility"
    if cid == OGERPON_EX and (ogerpon_in_play(obs) + ids.count(OGERPON_EX)) > 3:
        return 6000, "discard 4th Ogerpon"
    if cid == OGERPON_EX:
        return -5000, "keep Ogerpon"
    if cid == GRASS_ENERGY:
        return -2000, "keep energy"
    return 1000, "generic discard"


def score_target(obs, opt):
    card = option_card(obs, opt)
    cid = card.id if card else opt.cardId
    ctx = obs.select.context
    yi = obs.current.yourIndex
    pi = getattr(opt, "playerIndex", yi)

    if ctx == SelectContext.ATTACH_TO:
        # N's Plan destination / energy attach target
        return (attach_target_score(obs, card, opt.area), "attach to")

    if ctx == SelectContext.ATTACH_FROM:
        # N's Plan source: bench Ogerpon with most energy
        return (2000 + energy_count(card) * 500, "move from loaded bench")

    if ctx == SelectContext.HEAL:
        return (20000 + damage_on(card), "heal") if card else (0, "heal none")

    if ctx in {SelectContext.SWITCH, SelectContext.TO_ACTIVE}:
        if pi != yi and card:
            # Boss target: killable first, weighted by prize + their energy (feeds damage)
            act = active_pokemon(obs)
            my_e = energy_count(act) if act else 0
            eff = shower_damage(obs, my_energy=my_e, target=card)
            killable = eff >= card.hp
            pv = prize_value(card)
            te = energy_count(card)
            if killable:
                return 20000 + pv * 3000 + te * 300, "Boss: killable"
            return 4000 + te * 500 - card.hp // 10, "Boss: stall loaded"
        # our promotion after KO / retreat: normally most-charged first, but on
        # Mega Brave turns send the cheapest shell to eat the 270.
        if cid == OGERPON_EX:
            return 15000 + energy_count(card) * 1000 + card.hp, "promote charged Ogerpon"
        return 1000, "generic promote"

    if ctx == SelectContext.DAMAGE:
        hp = getattr(card, "hp", 999) if card else 999
        return 10000 - hp, "damage lowest HP"

    if ctx in {SelectContext.TO_FIELD, SelectContext.TO_BENCH}:
        return (16000, "field Ogerpon") if cid == OGERPON_EX else (1000, "generic")

    return 1000, "generic target"


def score_option(obs, opt):
    ctx = obs.select.context

    if ctx in {SelectContext.IS_FIRST, SelectContext.MULLIGAN,
               SelectContext.SETUP_ACTIVE_POKEMON, SelectContext.SETUP_BENCH_POKEMON}:
        return score_setup(obs, opt)

    if opt.type in {OptionType.YES, OptionType.NO}:
        if ctx == SelectContext.ACTIVATE:
            # Teal Dance confirmation: +energy +draw, always take it when it can fire
            if grass_in_hand(obs) > 0:
                return (100000, "Teal Dance yes") if opt.type == OptionType.YES else (0, "no")
            return (1, "yes") if opt.type == OptionType.YES else (0, "no")
        return (1, "yes") if opt.type == OptionType.YES else (0, "no")

    if opt.type == OptionType.NUMBER:
        return (opt.number or 0), "number"

    if ctx == SelectContext.MAIN:
        if opt.type == OptionType.PLAY:
            return score_play(obs, opt)
        if opt.type == OptionType.ATTACH:
            return score_attach(obs, opt)
        if opt.type == OptionType.RETREAT:
            return score_retreat(obs, opt)
        if opt.type == OptionType.ABILITY:
            # Teal Dance: fire on every Ogerpon while grass remains in hand
            if grass_in_hand(obs) > 0:
                if detect_threat(obs) == "mill":
                    act = active_pokemon(obs)
                    if act and energy_count(act) >= 4 and my_state(obs).deckCount <= 30:
                        return -500, "Teal Dance: throttle vs mill (save deck)"
                return 90000, "Teal Dance"
            return -500, "ability: no grass in hand"
        if opt.type == OptionType.ATTACK:
            act = active_pokemon(obs)
            opp_act = opp_active_pokemon(obs)
            dmg = shower_damage(obs)
            # Attacking is free (no discard); always do it once the turn is set up.
            return max(50, dmg), "Myriad Leaf Shower"
        if opt.type == OptionType.EVOLVE:
            return -500, "no evolutions in deck"
        if opt.type == OptionType.END:
            return 0, "end turn"
        return 500, "generic MAIN"

    if ctx == SelectContext.TO_HAND:
        return score_to_hand(obs, opt)
    if ctx in {SelectContext.DISCARD, SelectContext.DISCARD_CARD_OR_ATTACHED_CARD}:
        return score_discard(obs, opt)
    if ctx in {SelectContext.ATTACH_TO, SelectContext.TO_FIELD, SelectContext.TO_BENCH,
               SelectContext.ATTACH_FROM, SelectContext.SWITCH, SelectContext.TO_ACTIVE,
               SelectContext.HEAL, SelectContext.DAMAGE}:
        return score_target(obs, opt)
    if ctx == SelectContext.ATTACK:
        return max(50, shower_damage(obs)), "attack"
    if opt.type == OptionType.CARD:
        return score_to_hand(obs, opt)
    if opt.type == OptionType.ENERGY:
        return 1000, "energy"
    if opt.type == OptionType.END:
        return 0, "end"
    return 100, "fallback"


# ── Choose & Agent (identical mechanics to llcc_stable) ──

def choose_options(obs):
    scored = []
    for i, opt in enumerate(obs.select.option):
        try:
            score, reason = score_option(obs, opt)
        except Exception as e:
            score, reason = -999999, f"error {type(e).__name__}: {e}"
        scored.append((score, i, reason))

    scored.sort(key=lambda x: (x[0], -x[1]), reverse=True)

    selected = []
    for score, i, reason in scored:
        if len(selected) >= obs.select.maxCount:
            break
        if score < 0 and len(selected) >= obs.select.minCount:
            continue
        selected.append(i)

    if len(selected) < obs.select.minCount:
        selected = [i for _, i, _ in scored[:obs.select.minCount]]

    return selected


def agent(obs_dict):
    obs = to_observation_class(obs_dict)
    if obs.select is None:
        global _opp_last_attack_id, _cur_turn_logs
        _opp_last_attack_id = None
        _cur_turn_logs.clear()
        return read_deck_csv()
    _update_opp_attack_tracking(obs)
    if not obs.select.option:
        return []
    try:
        return choose_options(obs)
    except Exception:
        return random.sample(list(range(len(obs.select.option))), obs.select.maxCount)
