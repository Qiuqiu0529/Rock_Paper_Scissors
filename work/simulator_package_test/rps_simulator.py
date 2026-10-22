#!/usr/bin/env python3
"""可配置石头剪刀布模拟器，Python 3.10+，仅使用标准库。

python rps_simulator.py --config simulator.original.json --runs 1000
python rps_simulator.py --config simulator.advanced.json --validate-only
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation, localcontext
from functools import wraps
from pathlib import Path
from typing import Any

HANDS = ("rock", "scissors", "paper")
HAND_NAMES = ("石头", "剪刀", "布")
BEATS = (1, 2, 0)
COUNTER = (2, 0, 1)
ZERO = Decimal(0)
TIE_KEYS = {"wins", "draws", "rock_count", "scissors_count", "paper_count", "random"}
DEFAULT_CONFIG = {
    "name": "原始规则两阶段比赛", "seed": 42, "runs": 1,
    "groups": [{"name": "均匀随机", "count": 100,
                "strategy": {"type": "random", "probabilities": {
                    "rock": 1 / 3, "scissors": 1 / 3, "paper": 1 / 3}}}],
    "scoring": {"win": 2, "draw": 1, "loss": 0,
                "hand_bonus": {"rock": 0, "scissors": 0, "paper": 0}},
    "tie_breakers": ["wins", "random"],
    "stages": [{"name": "初赛", "rounds": 5, "advance": 30, "reset_scores": True},
               {"name": "决赛", "rounds": 9, "advance": 10, "reset_scores": True}],
}


def object_keys(value: Any, allowed: set[str], path: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须是对象。")
    extra = set(value) - allowed
    if extra:
        raise ValueError(f"{path} 存在未知字段：{', '.join(sorted(extra))}")
    return value


def integer(value: Any, path: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{path} 必须是大于等于 {minimum} 的整数。")
    return value


def boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} 必须是 true 或 false。")
    return value


def text_name(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} 必须是非空字符串。")
    return value.strip()


def decimal_number(value: Any, path: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise ValueError(f"{path} 必须是有限数值或十进制字符串。")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{path} 不是有效数值。") from exc
    if not number.is_finite():
        raise ValueError(f"{path} 不能是 NaN 或 Infinity。")
    # 限制到可审计的精度；Decimal 默认 28 位，整个计算使用更大的精度。
    if number == 0:
        return ZERO
    if len(number.as_tuple().digits) > 28 or abs(number.adjusted()) > 100:
        raise ValueError(f"{path} 最多支持 28 位有效数字，数量级须在 10^-100 至 10^100 内（0 除外）。")
    return number


def exact_scores(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext() as context:
            context.prec = 256
            return function(*args, **kwargs)
    return wrapped


def hand(value: Any, path: str) -> int:
    if not isinstance(value, str) or value not in HANDS:
        raise ValueError(f"{path} 必须是 rock、scissors 或 paper。")
    return HANDS.index(value)


@dataclass(frozen=True)
class Strategy:
    kind: str
    probabilities: tuple[float, float, float] = (1 / 3, 1 / 3, 1 / 3)
    fixed_hand: int = 0
    sequence: tuple[int, ...] = (0, 1, 2)
    offset: int = 0
    initial: int = 0
    reset_each_stage: bool = True


def parse_strategy(raw: Any, path: str) -> Strategy:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} 必须是策略对象。")
    kind = raw.get("type", "random")
    options = {"random": {"probabilities"}, "fixed": {"hand"},
               "cycle": {"sequence", "offset"}, "copy_last": {"initial"},
               "counter_last": {"initial"}}
    if not isinstance(kind, str) or kind not in options:
        raise ValueError(f"{path}.type 必须是 random/fixed/cycle/copy_last/counter_last。")
    object_keys(raw, {"type", "reset_each_stage"} | options[kind], path)
    reset = boolean(raw.get("reset_each_stage", True), f"{path}.reset_each_stage")
    if kind == "random":
        values = raw.get("probabilities", dict(zip(HANDS, (1 / 3,) * 3)))
        object_keys(values, set(HANDS), f"{path}.probabilities")
        if set(values) != set(HANDS):
            raise ValueError(f"{path}.probabilities 必须包含三种手势。")
        if any(isinstance(values[key], bool) or not isinstance(values[key], (int, float, Decimal))
               for key in HANDS):
            raise ValueError(f"{path}.probabilities 必须是数值。")
        if any((isinstance(value, float) and not math.isfinite(value))
               or (isinstance(value, Decimal) and not value.is_finite())
               or not 0 <= value <= 1 for value in values.values()):
            raise ValueError(f"{path}.probabilities 每项必须在 0 到 1 之间。")
        probabilities = tuple(float(values[key]) for key in HANDS)
        total = sum(probabilities)
        if not math.isclose(total, 1, rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"{path}.probabilities 之和必须为 1，当前为 {total:g}。")
        # 机器精度附近的概率直接保留，避免配置导出再载入时反复归一化产生 1 ulp 漂移。
        if abs(total - 1) > 1e-15:
            probabilities = tuple(value / total for value in probabilities)
        return Strategy(kind, probabilities=probabilities, reset_each_stage=reset)
    if kind == "fixed":
        return Strategy(kind, fixed_hand=hand(raw.get("hand"), f"{path}.hand"), reset_each_stage=reset)
    if kind == "cycle":
        sequence = raw.get("sequence")
        if not isinstance(sequence, list) or not sequence:
            raise ValueError(f"{path}.sequence 必须是非空手势数组。")
        return Strategy(kind, sequence=tuple(hand(value, f"{path}.sequence") for value in sequence),
                        offset=integer(raw.get("offset", 0), f"{path}.offset", 0), reset_each_stage=reset)
    return Strategy(kind, initial=hand(raw.get("initial", "rock"), f"{path}.initial"), reset_each_stage=reset)


@dataclass(frozen=True)
class Scoring:
    win: Decimal = Decimal(2)
    draw: Decimal = Decimal(1)
    loss: Decimal = ZERO
    bonuses: tuple[Decimal, Decimal, Decimal] = (ZERO, ZERO, ZERO)

    def award(self, outcome: str, chosen_hand: int) -> Decimal:
        return getattr(self, outcome) + self.bonuses[chosen_hand]


def parse_scoring(raw: Any, base: Scoring, path: str) -> Scoring:
    object_keys(raw, {"win", "draw", "loss", "hand_bonus"}, path)
    bonuses = raw.get("hand_bonus", {})
    object_keys(bonuses, set(HANDS), f"{path}.hand_bonus")
    return Scoring(
        *(decimal_number(raw.get(key, getattr(base, key)), f"{path}.{key}")
          for key in ("win", "draw", "loss")),
        tuple(decimal_number(bonuses.get(key, base.bonuses[index]), f"{path}.hand_bonus.{key}")
              for index, key in enumerate(HANDS)),
    )


def parse_ties(raw: Any, path: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or any(not isinstance(value, str) or value not in TIE_KEYS for value in raw):
        raise ValueError(f"{path} 仅支持 wins/draws/rock_count/scissors_count/paper_count/random。")
    if len(set(raw)) != len(raw) or ("random" in raw and raw[-1] != "random"):
        raise ValueError(f"{path} 不可重复，random 必须位于最后。")
    return tuple(raw if "random" in raw else raw + ["random"])


@dataclass(frozen=True)
class Group:
    name: str
    count: int
    strategy: Strategy
    stage_strategies: dict[str, Strategy]


@dataclass(frozen=True)
class Player:
    player_id: str
    group: Group

    def strategy_for(self, stage_name: str) -> Strategy:
        return self.group.stage_strategies.get(stage_name, self.group.strategy)


@dataclass(frozen=True)
class Stage:
    name: str
    rounds: int
    advance: int
    reset_scores: bool
    scoring: Scoring
    tie_breakers: tuple[str, ...]
    entrants: int


@dataclass(frozen=True)
class Settings:
    name: str
    seed: int
    runs: int
    groups: list[Group]
    players: list[Player]
    scoring: Scoring
    tie_breakers: tuple[str, ...]
    stages: list[Stage]


def parse_config(raw: Any) -> Settings:
    object_keys(raw, {"name", "seed", "runs", "groups", "scoring", "tie_breakers", "stages"}, "配置")
    seed = raw.get("seed", 42)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed 必须是整数。")
    runs = integer(raw.get("runs", 1), "runs")
    scoring = parse_scoring(raw.get("scoring", {}), Scoring(), "scoring")
    ties = parse_ties(raw.get("tie_breakers", ["wins", "random"]), "tie_breakers")
    raw_groups = raw.get("groups", DEFAULT_CONFIG["groups"])
    if not isinstance(raw_groups, list) or not raw_groups:
        raise ValueError("groups 必须是非空数组。")
    groups, group_names = [], set()
    for index, entry in enumerate(raw_groups, 1):
        path = f"groups[{index}]"
        object_keys(entry, {"name", "count", "strategy", "probabilities", "stage_strategies"}, path)
        name = text_name(entry.get("name"), f"{path}.name")
        if name in group_names:
            raise ValueError(f"策略组名称重复：{name}")
        group_names.add(name)
        if "strategy" in entry and "probabilities" in entry:
            raise ValueError(f"{path} 不能同时设置 strategy 和 probabilities。")
        strategy_raw = entry.get("strategy", {"type": "random", "probabilities": entry.get(
            "probabilities", dict(zip(HANDS, (1 / 3,) * 3)))})
        overrides_raw = entry.get("stage_strategies", {})
        if not isinstance(overrides_raw, dict):
            raise ValueError(f"{path}.stage_strategies 必须是阶段名到策略的对象。")
        overrides = {key: parse_strategy(value, f"{path}.stage_strategies.{key}")
                     for key, value in overrides_raw.items()}
        groups.append(Group(name, integer(entry.get("count"), f"{path}.count"),
                            parse_strategy(strategy_raw, f"{path}.strategy"), overrides))
    count = sum(group.count for group in groups)
    if count < 2 or count % 2:
        raise ValueError("参赛总人数必须是大于等于 2 的偶数，不使用轮空。")
    raw_stages = raw.get("stages", DEFAULT_CONFIG["stages"])
    if not isinstance(raw_stages, list) or not raw_stages:
        raise ValueError("stages 必须是非空数组。")
    stages, stage_names, entrants = [], set(), count
    for index, entry in enumerate(raw_stages, 1):
        path = f"stages[{index}]"
        object_keys(entry, {"name", "rounds", "advance", "reset_scores", "scoring", "tie_breakers"}, path)
        name = text_name(entry.get("name", f"第{index}阶段"), f"{path}.name")
        if name in stage_names:
            raise ValueError(f"阶段名称重复：{name}")
        stage_names.add(name)
        rounds = integer(entry.get("rounds"), f"{path}.rounds")
        advance = integer(entry.get("advance"), f"{path}.advance")
        if entrants % 2 or not 1 <= rounds < entrants:
            raise ValueError(f"{path} 参赛人数须为偶数，每人场次数须在 1 到 {entrants - 1} 之间。")
        if advance > entrants or (index < len(raw_stages) and (advance < 2 or advance % 2)):
            raise ValueError(f"{path}.advance 不可超过 {entrants}；非末阶段须为大于等于 2 的偶数。")
        reset = boolean(entry.get("reset_scores", True), f"{path}.reset_scores")
        stages.append(Stage(name, rounds, advance, reset,
                            parse_scoring(entry.get("scoring", {}), scoring, f"{path}.scoring"),
                            parse_ties(entry.get("tie_breakers", list(ties)), f"{path}.tie_breakers"), entrants))
        entrants = advance
    for group in groups:
        unknown = set(group.stage_strategies) - stage_names
        if unknown:
            raise ValueError(f"组 {group.name} 的 stage_strategies 引用了未知阶段：{', '.join(sorted(unknown))}")
    width = max(3, len(str(count)))
    players = []
    for group in groups:
        for _ in range(group.count):
            players.append(Player(f"P{len(players) + 1:0{width}d}", group))
    return Settings(text_name(raw.get("name", "石头剪刀布模拟"), "name"), seed, runs,
                    groups, players, scoring, ties, stages)


def reject_constant(value: str) -> None:
    raise ValueError(f"JSON 不允许 {value}。")


def load_config(path: Path | None) -> Settings:
    if path is None:
        return parse_config(DEFAULT_CONFIG)
    with path.open(encoding="utf-8-sig") as stream:
        return parse_config(json.load(stream, parse_float=Decimal, parse_constant=reject_constant))


@dataclass
class Tally:
    points: Decimal = ZERO
    wins: int = 0
    draws: int = 0
    losses: int = 0
    hands: list[int] = field(default_factory=lambda: [0, 0, 0])

    @property
    def games(self) -> int:
        return self.wins + self.draws + self.losses

    def record(self, chosen_hand: int, outcome: str, points: Decimal) -> None:
        attribute = {"win": "wins", "draw": "draws", "loss": "losses"}[outcome]
        setattr(self, attribute, getattr(self, attribute) + 1)
        self.hands[chosen_hand] += 1
        self.points += points

    def add(self, other: Tally) -> None:
        self.points += other.points
        self.wins += other.wins
        self.draws += other.draws
        self.losses += other.losses
        self.hands = [left + right for left, right in zip(self.hands, other.hands)]

    def copy(self) -> Tally:
        return Tally(self.points, self.wins, self.draws, self.losses, self.hands.copy())

    def metric(self, key: str) -> int:
        return self.hands[HANDS.index(key[:-6])] if key.endswith("_count") else getattr(self, key)


@dataclass
class History:
    index: int = 0
    own_hand: int | None = None
    opponent_hand: int | None = None


def choose_hand(strategy: Strategy, history: History, rng: random.Random) -> int:
    if strategy.kind == "random":
        value = rng.random()
        if value < strategy.probabilities[0]:
            return 0
        return 1 if value < strategy.probabilities[0] + strategy.probabilities[1] else 2
    if strategy.kind == "fixed":
        return strategy.fixed_hand
    if strategy.kind == "cycle":
        return strategy.sequence[(history.index + strategy.offset) % len(strategy.sequence)]
    if history.opponent_hand is None:
        return strategy.initial
    if strategy.kind == "copy_last":
        return history.opponent_hand
    return COUNTER[history.opponent_hand]


def schedule_rounds(count: int, rounds: int, rng: random.Random) -> list[list[tuple[int, int]]]:
    if count < 2 or count % 2 or not 1 <= rounds < count:
        raise ValueError("赛程须为偶数人数，轮数在 1 到人数减 1 之间。")
    order = list(range(count))
    rng.shuffle(order)
    anchor, tail = order[0], order[1:]
    result = []
    # 抽取完整轮转赛程中的不同轮次，只构造真正需要打的对局。
    for shift in rng.sample(range(count - 1), rounds):
        rotated = [anchor] + (tail[-shift:] + tail[:-shift] if shift else tail)
        result.append([(rotated[index], rotated[-index - 1]) for index in range(count // 2)])
    return result


@dataclass
class Standing:
    player: Player
    stage_index: int
    stage_name: str
    stage: Tally
    ranking: Tally
    total: Tally
    strategy_type: str
    rank: int = 0


@dataclass
class StageResult:
    spec: Stage
    standings: list[Standing]


@dataclass
class Tournament:
    rankings: list[Standing]
    stages: list[StageResult]
    totals: dict[str, Tally]
    winners: set[str]
    matches: list[dict[str, Any]]
    rounds: list[dict[str, Any]]


@exact_scores
def play_tournament(settings: Settings, run_index: int = 0, capture: bool = True) -> Tournament:
    active = settings.players.copy()
    totals = {player.player_id: Tally() for player in active}
    histories = {player.player_id: History() for player in active}
    previous_ranking: dict[str, Tally] = {}
    results, eliminated, matches, round_records = [], [], [], []
    round_offset = 0
    for stage_index, spec in enumerate(settings.stages, 1):
        active.sort(key=lambda player: player.player_id)
        prefix = f"{settings.seed}:{run_index}:{stage_index}"
        schedule_rng, lottery_rng = random.Random(prefix + ":schedule"), random.Random(prefix + ":lottery")
        hand_rngs = {player.player_id: random.Random(prefix + ":hands:" + player.player_id) for player in active}
        strategies = {player.player_id: player.strategy_for(spec.name) for player in active}
        local = {player.player_id: Tally() for player in active}
        carried = {player.player_id: (Tally() if spec.reset_scores or stage_index == 1
                                     else previous_ranking[player.player_id].copy()) for player in active}
        for player in active:
            if strategies[player.player_id].reset_each_stage:
                histories[player.player_id] = History()
        lottery = [player.player_id for player in active]
        lottery_rng.shuffle(lottery)
        lottery_order = {player_id: index for index, player_id in enumerate(lottery)}
        for round_number, pairs in enumerate(schedule_rounds(len(active), spec.rounds, schedule_rng), 1):
            round_hands, draws = [0, 0, 0], 0
            for match_number, (left, right) in enumerate(pairs, 1):
                players = (active[left], active[right])
                # 双方出拳全部确定后，才更新任意一方的历史。
                moves = tuple(choose_hand(strategies[player.player_id], histories[player.player_id],
                                          hand_rngs[player.player_id]) for player in players)
                if moves[0] == moves[1]:
                    outcomes, winner = ("draw", "draw"), "draw"
                    draws += 1
                elif BEATS[moves[0]] == moves[1]:
                    outcomes, winner = ("win", "loss"), players[0].player_id
                else:
                    outcomes, winner = ("loss", "win"), players[1].player_id
                points = tuple(spec.scoring.award(outcome, move) for outcome, move in zip(outcomes, moves))
                for side, player in enumerate(players):
                    player_id, move = player.player_id, moves[side]
                    local[player_id].record(move, outcomes[side], points[side])
                    totals[player_id].record(move, outcomes[side], points[side])
                    histories[player_id].index += 1
                    histories[player_id].own_hand = move
                    histories[player_id].opponent_hand = moves[1 - side]
                    round_hands[move] += 1
                if capture:
                    matches.append({
                        "stage": stage_index, "stage_name": spec.name, "round": round_number,
                        "overall_round": round_offset + round_number, "match": match_number,
                        "player_1": players[0].player_id, "group_1": players[0].group.name,
                        "strategy_1": strategies[players[0].player_id].kind, "hand_1": HANDS[moves[0]],
                        "player_2": players[1].player_id, "group_2": players[1].group.name,
                        "strategy_2": strategies[players[1].player_id].kind, "hand_2": HANDS[moves[1]],
                        "winner": winner, "base_points_1": getattr(spec.scoring, outcomes[0]),
                        "bonus_1": spec.scoring.bonuses[moves[0]], "points_1": points[0],
                        "base_points_2": getattr(spec.scoring, outcomes[1]),
                        "bonus_2": spec.scoring.bonuses[moves[1]], "points_2": points[1],
                    })
            if capture:
                scores = {player.player_id: carried[player.player_id].points + local[player.player_id].points
                          for player in active}
                highest = max(scores.values())
                round_records.append({
                    "stage": stage_index, "stage_name": spec.name, "round": round_number,
                    "overall_round": round_offset + round_number, "matches": len(pairs),
                    "rock_count": round_hands[0], "scissors_count": round_hands[1],
                    "paper_count": round_hands[2], "draw_matches": draws,
                    "highest_ranking_points": highest,
                    "leaders": ";".join(player_id for player_id, score in scores.items() if score == highest),
                })
        standings = []
        for player in active:
            ranking = carried[player.player_id].copy()
            ranking.add(local[player.player_id])
            standings.append(Standing(player, stage_index, spec.name, local[player.player_id].copy(),
                                      ranking, totals[player.player_id].copy(), strategies[player.player_id].kind))
        standings.sort(key=lambda item: (
            -item.ranking.points,
            *(-item.ranking.metric(key) for key in spec.tie_breakers if key != "random"),
            lottery_order[item.player.player_id],
        ))
        for rank, standing in enumerate(standings, 1):
            standing.rank = rank
        results.append(StageResult(spec, standings))
        if stage_index < len(settings.stages):
            eliminated.append(standings[spec.advance:])
        previous_ranking = {item.player.player_id: item.ranking for item in standings}
        active = [item.player for item in standings[:spec.advance]]
        round_offset += spec.rounds
    overall = results[-1].standings + [item for batch in reversed(eliminated) for item in batch]
    return Tournament(overall, results, totals, {player.player_id for player in active}, matches, round_records)


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def mean_score(points: Decimal, entries: int) -> Decimal | None:
    return points / entries if entries else None


def tally_fields(tally: Tally, prefix: str = "") -> dict[str, Any]:
    return {
        prefix + "points": tally.points, prefix + "games": tally.games,
        prefix + "wins": tally.wins, prefix + "draws": tally.draws, prefix + "losses": tally.losses,
        **{prefix + key + "_count": tally.hands[index] for index, key in enumerate(HANDS)},
    }


def rate_fields(tally: Tally) -> dict[str, Any]:
    return {"win_rate": ratio(tally.wins, tally.games), "draw_rate": ratio(tally.draws, tally.games),
            "loss_rate": ratio(tally.losses, tally.games),
            "non_draw_win_rate": ratio(tally.wins, tally.wins + tally.losses),
            **{key + "_rate": ratio(tally.hands[index], tally.games) for index, key in enumerate(HANDS)}}


def standing_fields(standing: Standing) -> dict[str, Any]:
    return {"player_id": standing.player.player_id, "group": standing.player.group.name,
            "stage": standing.stage_index, "stage_name": standing.stage_name,
            "stage_rank": standing.rank, "strategy_type": standing.strategy_type,
            **tally_fields(standing.stage, "stage_"), **tally_fields(standing.ranking, "ranking_"),
            **tally_fields(standing.total, "total_")}


@dataclass
class Aggregate:
    entries: int = 0
    advances: int = 0
    rank_sum: int = 0
    ranking_points: Decimal = ZERO
    tally: Tally = field(default_factory=Tally)

    def add(self, standing: Standing, advanced: bool) -> None:
        self.entries += 1
        self.advances += int(advanced)
        self.rank_sum += standing.rank
        self.ranking_points += standing.ranking.points
        self.tally.add(standing.stage)

    def merge(self, other: Aggregate) -> None:
        self.entries += other.entries
        self.advances += other.advances
        self.rank_sum += other.rank_sum
        self.ranking_points += other.ranking_points
        self.tally.add(other.tally)

    def fields(self, initial_entries: int) -> dict[str, Any]:
        return {"entries": self.entries, "advances": self.advances,
                "reach_rate": ratio(self.entries, initial_entries),
                "advance_rate": ratio(self.advances, self.entries),
                "average_stage_rank": ratio(self.rank_sum, self.entries),
                "average_stage_points": mean_score(self.tally.points, self.entries),
                "average_ranking_points": mean_score(self.ranking_points, self.entries),
                **tally_fields(self.tally, "total_"), **rate_fields(self.tally)}


@exact_scores
def simulate(settings: Settings) -> tuple[Tournament, list[dict], list[dict], list[dict]]:
    overall = {player.player_id: {"rank_sum": 0, "qualifications": 0, "tally": Tally()}
               for player in settings.players}
    per_stage = {(player.player_id, index): Aggregate() for player in settings.players
                 for index in range(1, len(settings.stages) + 1)}
    first = None
    for run_index in range(settings.runs):
        tournament = play_tournament(settings, run_index, capture=(run_index == 0))
        if first is None:
            first = tournament
        for rank, item in enumerate(tournament.rankings, 1):
            stats = overall[item.player.player_id]
            stats["rank_sum"] += rank
            stats["qualifications"] += int(item.player.player_id in tournament.winners)
            stats["tally"].add(tournament.totals[item.player.player_id])
        for index, result in enumerate(tournament.stages, 1):
            for item in result.standings:
                per_stage[item.player.player_id, index].add(item, item.rank <= result.spec.advance)
    assert first is not None
    player_rows = []
    for player in settings.players:
        stats, tally = overall[player.player_id], overall[player.player_id]["tally"]
        row = {"player_id": player.player_id, "group": player.group.name,
               "strategy_type": player.group.strategy.kind, "runs": settings.runs,
               "qualifications": stats["qualifications"],
               "qualification_rate": ratio(stats["qualifications"], settings.runs),
               "average_overall_rank": ratio(stats["rank_sum"], settings.runs),
               "average_total_points": mean_score(tally.points, settings.runs),
               "average_games": ratio(tally.games, settings.runs),
               **tally_fields(tally, "total_"), **rate_fields(tally)}
        for index in range(1, len(settings.stages) + 1):
            fields = per_stage[player.player_id, index].fields(settings.runs)
            row.update({f"stage_{index}_{key}": fields[key] for key in (
                "entries", "advances", "reach_rate", "advance_rate", "average_stage_points", "average_ranking_points")})
        player_rows.append(row)
    group_rows, stage_rows = [], []
    for group in settings.groups:
        members = [player for player in settings.players if player.group.name == group.name]
        tally = Tally()
        for player in members:
            tally.add(overall[player.player_id]["tally"])
        entries = len(members) * settings.runs
        group_rows.append({
            "group": group.name, "strategy_type": group.strategy.kind, "players": len(members),
            "runs": settings.runs, "qualifications": sum(overall[player.player_id]["qualifications"] for player in members),
            "qualification_rate": ratio(sum(overall[player.player_id]["qualifications"] for player in members), entries),
            "average_overall_rank": ratio(sum(overall[player.player_id]["rank_sum"] for player in members), entries),
            "average_total_points": mean_score(tally.points, entries), "average_games": ratio(tally.games, entries),
            **tally_fields(tally, "total_"), **rate_fields(tally),
        })
    for index, spec in enumerate(settings.stages, 1):
        for group in [None, *settings.groups]:
            members = [player for player in settings.players if group is None or player.group.name == group.name]
            aggregate = Aggregate()
            for player in members:
                aggregate.merge(per_stage[player.player_id, index])
            stage_rows.append({"scope": "all" if group is None else "group",
                               "group": "" if group is None else group.name, "stage": index,
                               "stage_name": spec.name, **aggregate.fields(len(members) * settings.runs)})
    return first, player_rows, group_rows, stage_rows


def strategy_config(strategy: Strategy) -> dict:
    result: dict[str, Any] = {"type": strategy.kind, "reset_each_stage": strategy.reset_each_stage}
    if strategy.kind == "random":
        result["probabilities"] = dict(zip(HANDS, strategy.probabilities))
    elif strategy.kind == "fixed":
        result["hand"] = HANDS[strategy.fixed_hand]
    elif strategy.kind == "cycle":
        result.update(sequence=[HANDS[value] for value in strategy.sequence], offset=strategy.offset)
    else:
        result["initial"] = HANDS[strategy.initial]
    return result


def scoring_config(scoring: Scoring) -> dict:
    return {"win": scoring.win, "draw": scoring.draw, "loss": scoring.loss,
            "hand_bonus": dict(zip(HANDS, scoring.bonuses))}


def config_dict(settings: Settings) -> dict:
    return {"name": settings.name, "seed": settings.seed, "runs": settings.runs,
            "groups": [{"name": group.name, "count": group.count,
                        "strategy": strategy_config(group.strategy),
                        "stage_strategies": {key: strategy_config(value) for key, value in group.stage_strategies.items()}}
                       for group in settings.groups],
            "scoring": scoring_config(settings.scoring), "tie_breakers": list(settings.tie_breakers),
            "stages": [{"name": stage.name, "rounds": stage.rounds, "advance": stage.advance,
                        "reset_scores": stage.reset_scores, "scoring": scoring_config(stage.scoring),
                        "tie_breakers": list(stage.tie_breakers)} for stage in settings.stages]}


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def json_decimal(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"无法序列化 {type(value).__name__}")


def export_results(settings: Settings, directory: Path, tournament: Tournament,
                   players: list[dict], groups: list[dict], stages: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    rankings = [{"rank": rank, "qualified": item.player.player_id in tournament.winners,
                 **standing_fields(item)} for rank, item in enumerate(tournament.rankings, 1)]
    stage_rankings = [{"advanced": item.rank <= result.spec.advance, **standing_fields(item)}
                      for result in tournament.stages for item in result.standings]
    for filename, rows in (("rankings.csv", rankings), ("stage_rankings.csv", stage_rankings),
                           ("matches.csv", tournament.matches), ("rounds.csv", tournament.rounds),
                           ("player_summary.csv", players), ("strategy_summary.csv", groups),
                           ("stage_summary.csv", stages)):
        write_csv(directory / filename, rows)
    summary = {
        "config": config_dict(settings), "players": len(settings.players),
        "final_qualifiers": settings.stages[-1].advance,
        "rounds_per_tournament": sum(stage.rounds for stage in settings.stages),
        "matches_per_tournament": sum(stage.entrants * stage.rounds // 2 for stage in settings.stages),
        "first_tournament_winners": rankings[:settings.stages[-1].advance],
        "groups": groups, "stage_summary": stages,
        "record_scope": "rankings, stage_rankings, matches, rounds describe only the first tournament; other summaries cover all runs",
        "score_scope": {"stage_points": "earned in this stage", "ranking_points": "earned since the last score reset",
                        "total_points": "earned in all played stages, including stages cleared from ranking"},
        "decimal_scores": "Decimal values are written as strings to preserve exact decimal values",
    }
    with (directory / "summary.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, default=json_decimal, allow_nan=False)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, help="JSON 配置文件；省略时采用内置原始规则")
    parser.add_argument("--runs", type=int, help="覆盖配置中的重复模拟届数")
    parser.add_argument("--seed", type=int, help="覆盖配置中的随机种子")
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent / "simulator_results")
    parser.add_argument("--show-rounds", action="store_true", help="显示首届各轮过程")
    parser.add_argument("--validate-only", action="store_true", help="检查配置并显示赛程规模，不运行或写结果")
    args = parser.parse_args()
    try:
        settings = load_config(args.config)
        if args.runs is not None:
            settings = replace(settings, runs=integer(args.runs, "--runs"))
        if args.seed is not None:
            settings = replace(settings, seed=args.seed)
    except (OSError, ValueError, InvalidOperation) as exc:
        parser.error(str(exc))
    print(f"{settings.name}：{len(settings.players)} 人，模拟 {settings.runs} 届，种子 {settings.seed}")
    for index, stage in enumerate(settings.stages, 1):
        print(f"阶段 {index} {stage.name}：{stage.entrants} 人各打 {stage.rounds} 场，取 {stage.advance} 人，"
              f"{'积分清零' if stage.reset_scores else '结转上一阶段排名分'}；"
              f"胜/平/负={stage.scoring.win}/{stage.scoring.draw}/{stage.scoring.loss}，"
              f"石头/剪刀/布加分={','.join(map(str, stage.scoring.bonuses))}")
    print(f"每届共 {sum(stage.rounds for stage in settings.stages)} 轮、"
          f"{sum(stage.entrants * stage.rounds // 2 for stage in settings.stages)} 场。")
    if args.validate_only:
        print("配置有效；未运行比赛，未写入结果。")
        return
    tournament, players, groups, stages = simulate(settings)
    export_results(settings, args.out_dir, tournament, players, groups, stages)
    if args.show_rounds:
        for row in tournament.rounds:
            print(f"{row['stage_name']}第{row['round']}轮：石头/剪刀/布="
                  f"{row['rock_count']}/{row['scissors_count']}/{row['paper_count']}，"
                  f"平局{row['draw_matches']}场，最高排名分{row['highest_ranking_points']}")
    print("\n首届最终入选者：")
    for rank, item in enumerate(tournament.rankings[:settings.stages[-1].advance], 1):
        print(f"{rank:>3}. {item.player.player_id} {item.player.group.name}："
              f"本阶段分 {item.stage.points}，排名分 {item.ranking.points}，全届总分 {item.total.points}")
    print("\n全部模拟的策略组统计：")
    for row in groups:
        print(f"{row['group']}：单局胜率 {row['win_rate']:.2%}，"
              f"最终入选率 {row['qualification_rate']:.2%}")
    print(f"\n结果目录：{args.out_dir.resolve()}")
    print("逐局及排名记录仅首届；玩家、策略组和阶段统计涵盖全部届数。")


if __name__ == "__main__":
    main()
