#!/usr/bin/env python3
"""将通用模拟器的已保存结果转换为数据自包含的离线 HTML 报告。"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

TEMPLATE_PATH = Path(__file__).resolve().with_name("rps_report_template.html")
DATA_MARKER = "__RPS_REPORT_DATA__"
CSV_TABLES = {
    "groups": ("strategy_summary.csv", {"group", "win_rate", "qualification_rate", "total_games", "total_points"}),
    "stage_summary": ("stage_summary.csv", {"scope", "group", "stage", "entries", "advances", "advance_rate"}),
    "players": ("player_summary.csv", {"player_id", "group", "qualification_rate"}),
    "rankings": ("rankings.csv", {"rank", "qualified", "player_id", "group", "stage", "stage_points", "ranking_points", "total_points"}),
    "stage_rankings": ("stage_rankings.csv", {"advanced", "player_id", "group", "stage", "stage_rank", "stage_points", "ranking_points"}),
    "matches": ("matches.csv", {"stage", "round", "player_1", "player_2", "hand_1", "hand_2", "winner", "points_1", "points_2"}),
    "rounds": ("rounds.csv", {"stage", "stage_name", "round", "matches", "rock_count", "scissors_count", "paper_count"}),
}


def reject_constant(value: str) -> None:
    raise ValueError(f"结果 JSON 包含非法数值：{value}")


def read_table(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not required_columns <= set(reader.fieldnames):
            missing = required_columns - set(reader.fieldnames or [])
            raise ValueError(f"{path.name} 缺少报告所需字段：{', '.join(sorted(missing))}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name} 没有结果记录，请先完成一次模拟。")
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"{path.name} 存在不完整或多列的 CSV 记录。")
    return rows


def load_report_data(directory: Path) -> dict[str, Any]:
    directory = Path(directory).resolve()
    with (directory / "summary.json").open(encoding="utf-8-sig") as stream:
        summary = json.load(stream, parse_constant=reject_constant)
    if not isinstance(summary, dict) or not isinstance(summary.get("config"), dict):
        raise ValueError("此目录不是通用 rps_simulator.py 的完整结果目录：summary.json 缺少 config。")
    config = summary["config"]
    required = {"name", "seed", "runs", "stages"}
    if not required <= set(config) or not isinstance(config["stages"], list) or not config["stages"]:
        raise ValueError("summary.json 的配置缺少比赛名称、种子、届数或阶段信息。")
    meta_keys = ("players", "final_qualifiers", "rounds_per_tournament", "matches_per_tournament")
    if any(not isinstance(summary.get(key), int) or isinstance(summary[key], bool) or summary[key] < 1
           for key in meta_keys):
        raise ValueError("summary.json 的人数、轮数或场数信息不完整。")
    data = {"meta": {"title": str(config["name"]), "seed": config["seed"], "runs": config["runs"],
                     **{key: summary[key] for key in meta_keys}}, "config": config}
    for key, (filename, required_columns) in CSV_TABLES.items():
        data[key] = read_table(directory / filename, required_columns)
    return data


def embedded_json(data: dict[str, Any]) -> str:
    """JSON 仍可解析，同时禁止用户名称关闭承载数据的 script 标签。"""
    value = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return (value.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def build_report(directory: Path, output: Path | None = None, *, template_path: Path | None = None) -> Path:
    directory = Path(directory).resolve()
    data = load_report_data(directory)
    template_file = Path(template_path) if template_path is not None else TEMPLATE_PATH
    template = template_file.read_text(encoding="utf-8-sig")
    if template.count(DATA_MARKER) != 1:
        raise ValueError(f"报告模板必须恰好包含一个 {DATA_MARKER} 数据标记。")
    result = template.replace(DATA_MARKER, embedded_json(data))
    output_file = Path(output).resolve() if output is not None else directory / "report.html"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(result, encoding="utf-8")
    return output_file


def main() -> None:
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="通用模拟器生成的结果目录")
    parser.add_argument("--output", type=Path, help="HTML 路径；默认在结果目录生成 report.html")
    args = parser.parse_args()
    try:
        path = build_report(args.directory, args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"可视化报告：{path}")


if __name__ == "__main__":
    main()
