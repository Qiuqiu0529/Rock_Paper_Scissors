#!/usr/bin/env python3
"""100 人石头剪刀布分阶段积分赛，使用 Python 3.10+ 标准库。

默认初赛：100 人各打 5 场取前 30；决赛：30 人清零后各打 9 场取前 10。

示例：
  python rps_tournament.py
  python rps_tournament.py --probs 0.2 0.6 0.2 --seed 42 --show-rounds
  python rps_tournament.py --config strategies.example.json --runs 100
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PLAYER_COUNT = 100
QUALIFIER_COUNT = 10
ROCK, SCISSORS, PAPER = range(3)
HAND_KEYS = ("rock", "scissors", "paper")
HAND_NAMES = ("石头", "剪刀", "布")
BEATS = (SCISSORS, PAPER, ROCK)


@dataclass(frozen=True)
class Player:
    player_id: str
    strategy: str
    probabilities: tuple[float, float, float]


@dataclass
class Standing:
    player: Player
    wins: int = 0
    draws: int = 0
    losses: int = 0
    hand_counts: list[int] = field(default_factory=lambda: [0, 0, 0])

    def points(self, scissors_bonus: float) -> float:
        return 2 * self.wins + self.draws + scissors_bonus * self.hand_counts[SCISSORS]


@dataclass
class Tournament:
    rankings: list[Standing]
    stages: list[StageResult]
    total_standings: dict[str, Standing]
    match_records: list[dict[str, Any]]
    round_records: list[dict[str, Any]]


@dataclass
class StageResult:
    stage: int
    name: str
    rounds: int
    qualifier_count: int
    rankings: list[Standing]


def validate_probabilities(values: Any) -> tuple[float, float, float]:
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise ValueError("概率必须依次包含石头、剪刀、布三个数。")
    if any(isinstance(value, bool) for value in values):
        raise ValueError("概率必须是数值，不能是布尔值。")
    try:
        probabilities = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ValueError("概率必须是数值。") from exc
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in probabilities):
        raise ValueError("每个概率必须是 0 到 1 之间的有限数值。")
    total = sum(probabilities)
    if not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-8):
        raise ValueError(f"三个概率之和必须为 1，当前为 {total:g}。")
    return tuple(value / total for value in probabilities)


def make_players(
    probabilities: tuple[float, float, float] | None = None,
    config_path: Path | None = None,
) -> list[Player]:
    if config_path is None:
        groups = [{"name": "统一策略", "count": PLAYER_COUNT,
                   "probabilities": dict(zip(HAND_KEYS, probabilities or (1 / 3,) * 3))}]
    else:
        with config_path.open(encoding="utf-8-sig") as stream:
            config = json.load(stream)
        if not isinstance(config, dict) or not isinstance(config.get("groups"), list):
            raise ValueError("配置文件必须包含 groups 数组。")
        groups = config["groups"]

    players: list[Player] = []
    names: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("每个策略组必须是一个 JSON 对象。")
        name = group.get("name")
        count = group.get("count")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("策略组 name 必须是非空且不重复的字符串。")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= PLAYER_COUNT:
            raise ValueError(f"策略组 {name} 的 count 必须是 1 到 100 之间的整数。")
        values = group.get("probabilities")
        if not isinstance(values, dict) or set(values) != set(HAND_KEYS):
            raise ValueError(f"策略组 {name} 的 probabilities 必须恰好包含 rock、scissors、paper。")
        group_probabilities = validate_probabilities([values[key] for key in HAND_KEYS])
        names.add(name)
        for _ in range(count):
            players.append(Player(f"P{len(players) + 1:03d}", name, group_probabilities))
    if len(players) != PLAYER_COUNT:
        raise ValueError(f"所有策略组人数之和必须是 100，当前为 {len(players)}。")
    return players


def round_robin_schedule(player_count: int, rng: random.Random) -> list[list[tuple[int, int]]]:
    """轮转编排：偶数人数，每轮人人参赛，任意两人恰好相遇一次。"""
    if player_count < 2 or player_count % 2:
        raise ValueError("循环赛人数必须是大于等于 2 的偶数。")
    order = list(range(player_count))
    rng.shuffle(order)
    rounds = []
    for _ in range(player_count - 1):
        rounds.append([(order[index], order[-index - 1])
                       for index in range(player_count // 2)])
        order = [order[0], order[-1], *order[1:-1]]
    return rounds


def draw_hand(probabilities: tuple[float, float, float], rng: random.Random) -> int:
    value = rng.random()
    if value < probabilities[ROCK]:
        return ROCK
    if value < probabilities[ROCK] + probabilities[SCISSORS]:
        return SCISSORS
    return PAPER


def validate_format(player_count: int, prelim_rounds: int, finalists: int, final_rounds: int) -> None:
    if player_count < 2 or player_count % 2:
        raise ValueError("参赛人数必须是大于等于 2 的偶数。")
    if not 1 <= prelim_rounds < player_count:
        raise ValueError(f"初赛场次数必须在 1 到 {player_count - 1} 之间。")
    if not QUALIFIER_COUNT < finalists < player_count or finalists % 2:
        raise ValueError(f"决赛人数必须是大于 10、小于 {player_count} 的偶数。")
    if not 1 <= final_rounds < finalists:
        raise ValueError(f"决赛场次数必须在 1 到 {finalists - 1} 之间。")


def partial_schedule(
    player_count: int, rounds: int, rng: random.Random,
) -> list[list[tuple[int, int]]]:
    if not 1 <= rounds < player_count:
        raise ValueError("每人场次数必须在 1 到参赛人数减 1 之间。")
    schedule = round_robin_schedule(player_count, rng)
    rng.shuffle(schedule)
    return schedule[:rounds]


def play_stage(
    players: list[Player], seed: int, run_index: int, stage: int, name: str,
    rounds: int, qualifier_count: int, scissors_bonus: float,
    capture_records: bool, round_offset: int,
) -> tuple[StageResult, list[dict[str, Any]], list[dict[str, Any]]]:
    # 每阶段独立随机流；人数相同时，排名顺序不会影响随机编排。
    players = sorted(players, key=lambda player: player.player_id)
    schedule_rng = random.Random(f"{seed}:schedule:{run_index}:{stage}")
    hand_rng = random.Random(f"{seed}:hands:{run_index}:{stage}")
    lottery_rng = random.Random(f"{seed}:lottery:{run_index}:{stage}")
    standings = [Standing(player) for player in players]
    match_records: list[dict[str, Any]] = []
    round_records: list[dict[str, Any]] = []

    lottery_order = list(range(len(players)))
    lottery_rng.shuffle(lottery_order)
    lottery_priority = {players[index].player_id: position
                        for position, index in enumerate(lottery_order)}

    for round_number, pairs in enumerate(partial_schedule(len(players), rounds, schedule_rng), 1):
        round_hand_counts = [0, 0, 0]
        draw_matches = 0
        for match_number, (left_index, right_index) in enumerate(pairs, 1):
            left, right = standings[left_index], standings[right_index]
            left_hand = draw_hand(left.player.probabilities, hand_rng)
            right_hand = draw_hand(right.player.probabilities, hand_rng)
            left.hand_counts[left_hand] += 1
            right.hand_counts[right_hand] += 1
            round_hand_counts[left_hand] += 1
            round_hand_counts[right_hand] += 1
            if left_hand == right_hand:
                left.draws += 1
                right.draws += 1
                left_base, right_base = 1, 1
                winner = "draw"
                draw_matches += 1
            elif BEATS[left_hand] == right_hand:
                left.wins += 1
                right.losses += 1
                left_base, right_base = 2, 0
                winner = left.player.player_id
            else:
                left.losses += 1
                right.wins += 1
                left_base, right_base = 0, 2
                winner = right.player.player_id
            if capture_records:
                match_records.append({
                    "stage": stage, "stage_name": name,
                    "overall_round": round_offset + round_number,
                    "round": round_number, "match": match_number,
                    "player_1": left.player.player_id, "strategy_1": left.player.strategy,
                    "hand_1": HAND_NAMES[left_hand],
                    "player_2": right.player.player_id, "strategy_2": right.player.strategy,
                    "hand_2": HAND_NAMES[right_hand], "winner": winner,
                    "points_1": left_base + scissors_bonus * (left_hand == SCISSORS),
                    "points_2": right_base + scissors_bonus * (right_hand == SCISSORS),
                })
        if capture_records:
            highest_points = max(item.points(scissors_bonus) for item in standings)
            leaders = [item.player.player_id for item in standings
                       if item.points(scissors_bonus) == highest_points]
            round_records.append({
                "stage": stage, "stage_name": name,
                "overall_round": round_offset + round_number,
                "round": round_number, "matches": len(pairs),
                "rock_count": round_hand_counts[ROCK],
                "scissors_count": round_hand_counts[SCISSORS],
                "paper_count": round_hand_counts[PAPER], "draw_matches": draw_matches,
                "highest_points": highest_points, "leaders": ";".join(leaders),
            })

    rankings = sorted(standings, key=lambda item: (
        -item.points(scissors_bonus), -item.hand_counts[SCISSORS], -item.wins,
        lottery_priority[item.player.player_id],
    ))
    return StageResult(stage, name, rounds, qualifier_count, rankings), match_records, round_records


def play_tournament(
    players: list[Player], seed: int, run_index: int = 0,
    scissors_bonus: float = 1.0, capture_records: bool = True,
    prelim_rounds: int = 5, finalists: int = 30, final_rounds: int = 9,
) -> Tournament:
    validate_format(len(players), prelim_rounds, finalists, final_rounds)
    preliminary, prelim_matches, prelim_records = play_stage(
        players, seed, run_index, 1, "初赛", prelim_rounds, finalists,
        scissors_bonus, capture_records, 0,
    )
    final_players = [item.player for item in preliminary.rankings[:finalists]]
    final, final_matches, final_records = play_stage(
        final_players, seed, run_index, 2, "决赛", final_rounds, QUALIFIER_COUNT,
        scissors_bonus, capture_records, prelim_rounds,
    )
    # 综合名次先按进入的阶段，再按该阶段名次；不跨阶段直接比较积分。
    rankings = final.rankings + preliminary.rankings[finalists:]
    totals = {player.player_id: Standing(player) for player in players}
    for stage_result in (preliminary, final):
        for item in stage_result.rankings:
            total = totals[item.player.player_id]
            total.wins += item.wins
            total.draws += item.draws
            total.losses += item.losses
            for index in range(3):
                total.hand_counts[index] += item.hand_counts[index]
    return Tournament(rankings, [preliminary, final], totals,
                      prelim_matches + final_matches, prelim_records + final_records)


def ranking_rows(tournament: Tournament, scissors_bonus: float) -> list[dict[str, Any]]:
    rows = []
    last_stages = {standing.player.player_id: (stage, stage_rank)
                   for stage in tournament.stages
                   for stage_rank, standing in enumerate(stage.rankings, 1)}
    for rank, standing in enumerate(tournament.rankings, 1):
        stage, stage_rank = last_stages[standing.player.player_id]
        total = tournament.total_standings[standing.player.player_id]
        rows.append({
            "rank": rank, "player_id": standing.player.player_id,
            "strategy": standing.player.strategy, "qualified": rank <= QUALIFIER_COUNT,
            "reached_final": stage.stage == 2, "last_stage": stage.name,
            "stage_rank": stage_rank, "stage_points": standing.points(scissors_bonus),
            "stage_wins": standing.wins, "stage_draws": standing.draws,
            "stage_losses": standing.losses, "stage_games": stage.rounds,
            "stage_scissors_count": standing.hand_counts[SCISSORS],
            "total_points": total.points(scissors_bonus),
            "total_wins": total.wins, "total_draws": total.draws, "total_losses": total.losses,
            "total_games": sum(total.hand_counts),
            "total_rock_count": total.hand_counts[ROCK],
            "total_scissors_count": total.hand_counts[SCISSORS],
            "total_paper_count": total.hand_counts[PAPER],
            "actual_scissors_rate": total.hand_counts[SCISSORS] / sum(total.hand_counts),
            **{f"configured_{key}_probability": standing.player.probabilities[index]
               for index, key in enumerate(HAND_KEYS)},
        })
    return rows


def stage_ranking_rows(tournament: Tournament, scissors_bonus: float) -> list[dict[str, Any]]:
    rows = []
    for stage in tournament.stages:
        for rank, standing in enumerate(stage.rankings, 1):
            rows.append({
                "stage": stage.stage, "stage_name": stage.name, "rank": rank,
                "player_id": standing.player.player_id, "strategy": standing.player.strategy,
                "advanced": rank <= stage.qualifier_count,
                "points": standing.points(scissors_bonus), "games": stage.rounds,
                "wins": standing.wins, "draws": standing.draws, "losses": standing.losses,
                "rock_count": standing.hand_counts[ROCK],
                "scissors_count": standing.hand_counts[SCISSORS],
                "paper_count": standing.hand_counts[PAPER],
            })
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"无法写入空的结果表：{path}")
    # UTF-8 BOM 便于 Excel 正确识别中文。
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def simulate(
    players: list[Player], seed: int, runs: int, scissors_bonus: float,
    prelim_rounds: int = 5, finalists: int = 30, final_rounds: int = 9,
) -> tuple[Tournament, list[dict[str, Any]], list[dict[str, Any]]]:
    if runs < 1:
        raise ValueError("模拟次数必须大于等于 1。")
    totals = {player.player_id: {"qualified": 0, "rank": 0, "points": 0.0,
                                "prelim_qualified": 0, "prelim_points": 0.0,
                                "final_points": 0.0, "wins": 0,
                                "scissors": 0, "games": 0} for player in players}
    first_tournament = None
    for run_index in range(runs):
        tournament = play_tournament(
            players, seed, run_index, scissors_bonus, run_index == 0,
            prelim_rounds, finalists, final_rounds,
        )
        if run_index == 0:
            first_tournament = tournament
        for rank, standing in enumerate(tournament.rankings, 1):
            total = totals[standing.player.player_id]
            all_games = tournament.total_standings[standing.player.player_id]
            total["qualified"] += int(rank <= QUALIFIER_COUNT)
            total["rank"] += rank
            total["points"] += all_games.points(scissors_bonus)
            total["wins"] += all_games.wins
            total["scissors"] += all_games.hand_counts[SCISSORS]
            total["games"] += sum(all_games.hand_counts)
        for standing in tournament.stages[0].rankings:
            totals[standing.player.player_id]["prelim_points"] += standing.points(scissors_bonus)
        for standing in tournament.stages[1].rankings:
            total = totals[standing.player.player_id]
            total["prelim_qualified"] += 1
            total["final_points"] += standing.points(scissors_bonus)

    player_rows = []
    for player in players:
        total = totals[player.player_id]
        player_rows.append({
            "player_id": player.player_id, "strategy": player.strategy, "runs": runs,
            "prelim_qualifications": total["prelim_qualified"],
            "prelim_qualification_rate": total["prelim_qualified"] / runs,
            "qualifications": total["qualified"],
            "qualification_rate": total["qualified"] / runs,
            "conditional_final_qualification_rate": (total["qualified"] / total["prelim_qualified"]
                                                     if total["prelim_qualified"] else None),
            "average_rank": total["rank"] / runs,
            "average_prelim_points": total["prelim_points"] / runs,
            "average_final_points": (total["final_points"] / total["prelim_qualified"]
                                     if total["prelim_qualified"] else None),
            "average_total_points": total["points"] / runs,
            "average_games": total["games"] / runs,
            "average_wins": total["wins"] / runs,
            "actual_scissors_rate": total["scissors"] / total["games"],
            **{f"configured_{key}_probability": player.probabilities[index]
               for index, key in enumerate(HAND_KEYS)},
        })

    strategy_rows = []
    for strategy in dict.fromkeys(player.strategy for player in players):
        members = [row for row in player_rows if row["strategy"] == strategy]
        size = len(members)
        qualifications = sum(row["qualifications"] for row in members)
        member_totals = [totals[row["player_id"]] for row in members]
        prelim_qualifications = sum(total["prelim_qualified"] for total in member_totals)
        strategy_rows.append({
            "strategy": strategy, "players": size, "runs": runs,
            "prelim_qualifications": prelim_qualifications,
            "prelim_qualification_rate": prelim_qualifications / (size * runs),
            "qualifications": qualifications,
            "qualification_rate": qualifications / (size * runs),
            "conditional_final_qualification_rate": (qualifications / prelim_qualifications
                                                     if prelim_qualifications else None),
            "average_rank": sum(row["average_rank"] for row in members) / size,
            "average_prelim_points": sum(total["prelim_points"] for total in member_totals) / (size * runs),
            "average_final_points": (sum(total["final_points"] for total in member_totals) / prelim_qualifications
                                     if prelim_qualifications else None),
            "average_total_points": sum(total["points"] for total in member_totals) / (size * runs),
            "average_games": sum(total["games"] for total in member_totals) / (size * runs),
            "actual_scissors_rate": (sum(total["scissors"] for total in member_totals)
                                     / sum(total["games"] for total in member_totals)),
            **{f"configured_{key}_probability": members[0][f"configured_{key}_probability"]
               for key in HAND_KEYS},
        })
    assert first_tournament is not None
    return first_tournament, player_rows, strategy_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="模拟两阶段石头剪刀布比赛：默认 100 人取 30，清零后取前 10。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--probs", nargs=3, type=float, metavar=("ROCK", "SCISSORS", "PAPER"),
                        help="所有人的石头、剪刀、布概率，三数之和为 1；默认各 1/3")
    source.add_argument("--config", type=Path, help="JSON 策略组配置文件，组人数之和必须为 100")
    parser.add_argument("--seed", type=int, default=42, help="可复现的随机种子")
    parser.add_argument("--runs", type=int, default=1, help="重复模拟的完整比赛次数")
    parser.add_argument("--prelim-rounds", type=int, default=5, help="初赛每人场次数，同阶段对手不重复")
    parser.add_argument("--finalists", type=int, default=30, help="初赛晋级人数，必须是大于 10 的偶数")
    parser.add_argument("--final-rounds", type=int, default=9, help="决赛每人场次数，同阶段对手不重复")
    parser.add_argument("--scissors-bonus", type=float, default=1.0,
                        help="每次出剪刀的额外积分；设为 0 可做无奖励的对照实验")
    parser.add_argument("--out-dir", type=Path,
                        default=Path(__file__).resolve().parent / "simulation_results",
                        help="结果目录；同名结果文件会被覆盖")
    parser.add_argument("--show-rounds", action="store_true", help="在终端显示首届比赛每轮摘要")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs 必须大于等于 1。")
    if not math.isfinite(args.scissors_bonus) or args.scissors_bonus < 0:
        parser.error("--scissors-bonus 必须是非负有限数值。")
    try:
        args.players = make_players(
            validate_probabilities(args.probs) if args.probs is not None else None,
            args.config,
        )
        validate_format(len(args.players), args.prelim_rounds, args.finalists, args.final_rounds)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return args


def main() -> None:
    args = parse_args()
    tournament, player_rows, strategy_rows = simulate(
        args.players, args.seed, args.runs, args.scissors_bonus,
        args.prelim_rounds, args.finalists, args.final_rounds,
    )
    first_rankings = ranking_rows(tournament, args.scissors_bonus)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "rankings.csv", first_rankings)
    write_csv(args.out_dir / "stage_rankings.csv", stage_ranking_rows(tournament, args.scissors_bonus))
    write_csv(args.out_dir / "matches.csv", tournament.match_records)
    write_csv(args.out_dir / "rounds.csv", tournament.round_records)
    write_csv(args.out_dir / "player_summary.csv", player_rows)
    write_csv(args.out_dir / "strategy_summary.csv", strategy_rows)
    summary = {
        "seed": args.seed, "runs": args.runs, "players": len(args.players),
        "qualifiers_per_tournament": QUALIFIER_COUNT,
        "rounds_per_tournament": args.prelim_rounds + args.final_rounds,
        "matches_per_tournament": (len(args.players) * args.prelim_rounds + args.finalists * args.final_rounds) // 2,
        "stages": [{"name": stage.name, "players": len(stage.rankings),
                    "rounds_per_player": stage.rounds, "qualifiers": stage.qualifier_count,
                    "matches": len(stage.rankings) * stage.rounds // 2}
                   for stage in tournament.stages],
        "scores_reset_between_stages": True,
        "overall_ranking": "finalists ordered by final-stage rank, followed by preliminary eliminated players ordered by preliminary rank",
        "scoring": {"win": 2, "draw": 1, "loss": 0, "scissors_bonus": args.scissors_bonus},
        "ranking_order": ["points descending", "scissors count descending", "wins descending", "random lottery"],
        "first_tournament_top_10": first_rankings[:QUALIFIER_COUNT],
        "strategies": strategy_rows,
        "records_scope": "rankings.csv, stage_rankings.csv, matches.csv, rounds.csv describe the first tournament; summary tables cover all runs",
    }
    with (args.out_dir / "summary.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

    print(f"两阶段比赛：每届 {summary['rounds_per_tournament']} 轮、"
          f"{summary['matches_per_tournament']} 局；共模拟 {args.runs} 届。")
    for stage in tournament.stages:
        print(f"{stage.name}：{len(stage.rankings)} 人各打 {stage.rounds} 场，取前 {stage.qualifier_count}。")
    print("决赛积分清零重算；每阶段对手不重复，跨阶段可以再次相遇。")
    print(f"积分：胜 2 / 平 1 / 负 0；出剪刀额外 +{args.scissors_bonus:g}。种子：{args.seed}")
    if args.show_rounds:
        for row in tournament.round_records:
            print(f"{row['stage_name']}第 {row['round']:02d} 轮：石头 {row['rock_count']:3d}，"
                  f"剪刀 {row['scissors_count']:3d}，布 {row['paper_count']:3d}；"
                  f"平局 {row['draw_matches']:2d} 场；本阶段最高分 {row['highest_points']:g}")
    print("\n首届比赛前 10 名：")
    print("名次  玩家    决赛分  决赛胜/平/负  决赛剪刀  策略")
    for row in first_rankings[:QUALIFIER_COUNT]:
        print(f"{row['rank']:>2}    {row['player_id']}  {row['stage_points']:>6g}    "
              f"{row['stage_wins']:02d}/{row['stage_draws']:02d}/{row['stage_losses']:02d}       "
              f"{row['stage_scissors_count']:>2}     {row['strategy']}")
    print("\n策略统计（晋级率 = 该组晋级人次 / 该组参赛人次）：")
    for row in strategy_rows:
        print(f"{row['strategy']}：{row['players']} 人，"
              f"进入决赛 {row['prelim_qualification_rate']:.2%}，"
              f"进入前十 {row['qualification_rate']:.2%}，"
              f"实际剪刀比例 {row['actual_scissors_rate']:.2%}")
    print(f"\n结果已保存到：{args.out_dir.resolve()}")
    print("逐局记录和完整排名对应首届比赛；玩家及策略统计涵盖全部模拟。")


if __name__ == "__main__":
    main()
