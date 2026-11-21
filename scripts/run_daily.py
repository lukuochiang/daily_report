#!/usr/bin/env python3
"""日报生成入口：采集 → 清洗 → 去重 → AI 处理 → 校验 → 生成静态站点。"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_process import process_with_ai
from clean_news import clean_all
from deduplicate import process_dedup
from fetch_news import demo_stats, fetch_all, fetch_demo_items
from generate_site import generate_site
from utils import (DATA_DIR, beijing_today, is_valid_date, load_config,
                   read_json, setup_logging, utc_now_iso, write_json)
from validate_data import validate_daily

logger = logging.getLogger("run_daily")


def update_source_history(stats: list) -> None:
    """累计各数据源的成功/失败次数，并记录历史成功率。"""
    path = os.path.join(DATA_DIR, "source_history.json")
    try:
        history = read_json(path)
    except Exception:
        history = {}
    for stat in stats:
        record = history.setdefault(stat["name"], {"ok": 0, "failed": 0, "skipped": 0})
        status = stat.get("status", "failed")
        if status in record:
            record[status] += 1
        runs = record["ok"] + record["failed"]
        stat["success_rate"] = round(record["ok"] / runs, 3) if runs else 0.0
        stat["total_runs"] = runs
    history["_updated_at"] = utc_now_iso()
    write_json(path, history)


def write_status(status: str, date: str, stats: list, error: str = "", count: int = 0,
                 ai_status: str = "") -> None:
    write_json(os.path.join(DATA_DIR, "generation_status.json"), {
        "last_run_at": utc_now_iso(),
        "date": date,
        "status": status,
        "article_count": count,
        "ai_status": ai_status,
        "sources": stats,
        "error": error[:600],
    })


def run(config_path: str | None, run_date: str | None, demo: bool, skip_ai: bool) -> dict:
    config = load_config(config_path)
    run_date = run_date or beijing_today()
    if not is_valid_date(run_date):
        raise ValueError("日期格式应为 YYYY-MM-DD: %s" % run_date)

    if demo:
        logger.info("演示模式：使用模拟数据，不访问网络也不调用 AI")
        raw_items, stats = fetch_demo_items(run_date), demo_stats()
    else:
        raw_items, stats = fetch_all(config, run_date)
        try:
            update_source_history(stats)
        except Exception as exc:
            logger.warning("更新数据源成功率统计失败: %s", exc)

    cleaned = clean_all(raw_items)
    if not cleaned:
        raise RuntimeError("没有有效新闻，本次不写入任何数据，保留上一期日报")
    selected = process_dedup(cleaned, config)
    if not selected:
        raise RuntimeError("去重与精选后没有可用新闻，本次不写入任何数据")

    articles, highlights, trends, meta = process_with_ai(
        selected, config, run_date, force_disabled=(demo or skip_ai))
    data = {
        "date": run_date,
        "generated_at": utc_now_iso(),
        "article_count": len(articles),
        "is_demo": bool(demo),
        "ai": meta,
        "highlights": highlights,
        "trends": trends,
        "articles": articles,
        "source_stats": stats,
    }
    validate_daily(data)
    logger.info("数据校验通过：%s，%d 条，AI 状态 %s", run_date, len(articles), meta["ai_status"])

    generate_site(data)
    write_status("success", run_date, stats, count=len(articles), ai_status=meta["ai_status"])
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="生成科技互联网每日一报")
    parser.add_argument("--date", help="指定日报日期 YYYY-MM-DD（默认北京时间今天）")
    parser.add_argument("--config", help="数据源配置路径")
    parser.add_argument("--demo", action="store_true", help="使用模拟数据联调，不访问网络/AI")
    parser.add_argument("--skip-ai", action="store_true", help="跳过 AI 处理，使用原文标题与摘要")
    args = parser.parse_args()

    setup_logging()
    run_date = args.date or beijing_today()
    try:
        data = run(args.config, args.date, args.demo, args.skip_ai)
    except Exception as exc:
        logger.exception("日报生成失败：%s", exc)
        try:
            write_status("failed", run_date, [], error=str(exc))
        except Exception:
            logger.exception("写入失败状态失败")
        return 1
    logger.info("完成：%s，共 %d 条新闻", data["date"], data["article_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
