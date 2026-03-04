#!/usr/bin/env python3
"""
Run fixed 24h/72h/7d backtest reports into project directory.

Outputs in `reports/backtests/`:
- strategy_24h.json / strategy_72h.json / strategy_7d.json
- market_maker_fp_24h.json / market_maker_fp_72h.json / market_maker_fp_7d.json
- summary.json / summary.md
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WINDOWS = [
    {"label": "24h", "lookback_hours": 24, "days": 1},
    {"label": "72h", "lookback_hours": 72, "days": 3},
    {"label": "7d", "lookback_hours": 168, "days": 7},
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _strategy_brief(report: dict[str, Any]) -> dict[str, Any]:
    coverage = report.get("coverage") or {}
    rows = list(report.get("strategy_win_rates") or [])
    rows.sort(key=lambda row: float(row.get("win_rate_pct") or 0.0), reverse=True)
    return {
        "selected_items": int(coverage.get("selected_items") or 0),
        "evaluated_points": int(coverage.get("evaluated_points") or 0),
        "signals_counted": int(coverage.get("signals_counted") or 0),
        "top_signals": rows[:3],
    }


def _fp_brief(report: dict[str, Any]) -> dict[str, Any]:
    overall = report.get("overall") or {}
    per_type = list(report.get("per_type") or [])
    washout = next((row for row in per_type if str(row.get("signal_type")) == "washout_phase"), None)
    return {
        "overall": overall,
        "washout_phase": washout,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fixed 24h/72h/7d backtests and write reports.")
    parser.add_argument("--report-dir", default="reports/backtests", help="Output directory under project root.")
    parser.add_argument("--fp-since", default="", help="Only evaluate false-positive alerts at/after this ISO timestamp.")
    parser.add_argument("--sample-items", type=int, default=300)
    parser.add_argument("--lookback-points", type=int, default=2880)
    parser.add_argument("--min-history-points", type=int, default=24)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--horizon-hours", type=int, default=24)
    parser.add_argument("--success-threshold-pct", type=float, default=2.0)
    parser.add_argument("--score-buckets", type=int, default=5)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    report_dir = (project_root / args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    strategy_script = project_root / "backend/scripts/backtest_v2_strategies.py"
    fp_script = project_root / "backend/scripts/evaluate_market_maker_false_positives.py"

    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_dir": str(report_dir),
        "fp_since": str(args.fp_since or ""),
        "windows": {},
    }

    for window in WINDOWS:
        label = str(window["label"])
        lookback_hours = int(window["lookback_hours"])
        days = int(window["days"])

        strategy_report = report_dir / f"strategy_{label}.json"
        fp_report = report_dir / f"market_maker_fp_{label}.json"

        _run(
            [
                sys.executable,
                str(strategy_script),
                "--sample-items",
                str(int(args.sample_items)),
                "--lookback-hours",
                str(lookback_hours),
                "--lookback-points",
                str(int(args.lookback_points)),
                "--min-history-points",
                str(int(args.min_history_points)),
                "--stride",
                str(int(args.stride)),
                "--horizon-hours",
                str(int(args.horizon_hours)),
                "--success-threshold-pct",
                str(float(args.success_threshold_pct)),
                "--score-buckets",
                str(int(args.score_buckets)),
                "--report",
                str(strategy_report),
            ],
            cwd=project_root,
        )

        _run(
            [
                sys.executable,
                str(fp_script),
                "--days",
                str(days),
                *(["--since", str(args.fp_since)] if str(args.fp_since or "").strip() else []),
                "--horizon-hours",
                str(int(args.horizon_hours)),
                "--up-threshold-pct",
                str(float(args.success_threshold_pct)),
                "--down-threshold-pct",
                str(float(args.success_threshold_pct)),
                "--report",
                str(fp_report),
            ],
            cwd=project_root,
        )

        strategy_data = _read_json(strategy_report)
        fp_data = _read_json(fp_report)
        summary["windows"][label] = {
            "lookback_hours": lookback_hours,
            "false_positive_days": days,
            "strategy_report": str(strategy_report),
            "market_maker_fp_report": str(fp_report),
            "strategy": _strategy_brief(strategy_data),
            "market_maker_fp": _fp_brief(fp_data),
        }

    summary_path = report_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = ["# 回测总览", "", f"- 生成时间: {summary['generated_at']}", f"- 报告目录: `{report_dir}`", ""]
    for label in ("24h", "72h", "7d"):
        row = summary["windows"].get(label, {})
        strategy = row.get("strategy", {})
        fp = (row.get("market_maker_fp", {}) or {}).get("washout_phase", {})
        lines.append(f"## {label}")
        lines.append(f"- 样本点: {strategy.get('evaluated_points', 0)}")
        lines.append(f"- 信号计数: {strategy.get('signals_counted', 0)}")
        lines.append(f"- washout 命中率: {fp.get('hit_rate_pct', 'N/A')}%")
        lines.append(f"- washout 误报率: {fp.get('false_positive_rate_pct', 'N/A')}%")
        lines.append("")

    summary_md_path = report_dir / "summary.md"
    summary_md_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "summary_json": str(summary_path), "summary_md": str(summary_md_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
