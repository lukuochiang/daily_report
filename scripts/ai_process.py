"""AI 双语处理：分类、评分、摘要、重点与趋势；含降级机制。"""
from __future__ import annotations

import json
import logging
import os
import re

import requests

from utils import VALID_CATEGORIES, clean_text, settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a bilingual technology news editor for a professional daily brief.
You MUST base every statement strictly on the provided source headline and excerpt.
Never invent facts, people, companies, dates, numbers, or quotes.
Do not reproduce full article text. Write concise original summaries (40-90 Chinese characters / 20-45 English words).
Chinese and English versions must express the same facts.
Distinguish official announcements, media reports and rumours; if uncertain, say so explicitly.
Classify each item into exactly one category slug: ai, companies, developers, internet, business, security.
Score importance from 1 (low) to 5 (critical) based on industry impact, not source fame.
Use the provided event_key as event_group when several articles describe the same event.
Return ONLY a single valid JSON object. No markdown, no explanation outside JSON."""

USER_TEMPLATE = """Date (Beijing): {date}
Articles (JSON):
{articles}

Return JSON with exactly this shape:
{{
  "articles": [
    {{"id": "item id", "importance": 1-5, "category": "slug", "tags": ["tag1", "tag2"],
      "title_zh": "中文标题", "title_en": "English title",
      "summary_zh": "中文摘要", "summary_en": "English summary",
      "event_group": "event-01 or short label"}}
  ],
  "highlights": ["id of the most important article", ... up to 5],
  "trends": [
    {{"title_zh": "趋势中文标题", "title_en": "Trend title",
      "summary_zh": "基于今日新闻的趋势说明", "summary_en": "Trend summary based on today's news"}}
  ]
}}
Provide 2-4 trends. Every input id must appear exactly once in articles."""


def ai_config() -> tuple:
    key = os.environ.get("AI_API_KEY", "").strip()
    base = (os.environ.get("AI_BASE_URL") or "https://api.deepseek.com").strip().rstrip("/") \
        or "https://api.deepseek.com"
    model = (os.environ.get("AI_MODEL") or "deepseek-chat").strip() or "deepseek-chat"
    return key, base, model


def ai_is_enabled() -> bool:
    return bool(ai_config()[0])


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI 返回内容中未找到 JSON 对象")
    return json.loads(text[start:end + 1])


def call_ai(prompt: str, key: str, base: str, model: str) -> dict:
    url = base + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": int(os.environ.get("AI_MAX_TOKENS", "4096")),
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": "Bearer %s" % key, "Content-Type": "application/json"}
    timeout = int(os.environ.get("AI_TIMEOUT", "90"))
    last_error = None
    for attempt in range(2):
        try:
            current = dict(payload)
            if attempt == 1:  # 某些兼容接口不支持 response_format
                current.pop("response_format", None)
            response = requests.post(url, json=current, headers=headers, timeout=timeout)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return extract_json(content)
        except Exception as exc:
            last_error = exc
            logger.warning("AI 请求第 %d 次失败: %s", attempt + 1, str(exc)[:300])
    raise last_error


def fallback_article(item: dict) -> dict:
    excerpt = clean_text(item.get("excerpt"), 300) or item["original_title"]
    title = item["original_title"]
    return {
        "id": item["id"],
        "title_zh": title,
        "title_en": title if item.get("original_language") != "zh" else title,
        "summary_zh": "【原文摘要，未经 AI 整理】" + excerpt,
        "summary_en": "Original excerpt (AI summary unavailable): " + excerpt,
        "source": item["source"],
        "source_url": item["source_url"],
        "original_title": item["original_title"],
        "original_language": item.get("original_language", "en"),
        "published_at": item["published_at"],
        "collected_at": item["collected_at"],
        "category": item.get("heuristic_category", "internet"),
        "tags": [],
        "importance": int(item.get("heuristic_importance", 2)),
        "event_group": item.get("event_key", ""),
        "event_size": int(item.get("event_size", 1)),
        "ai_generated": False,
        "source_note": item.get("source_note", ""),
        "discussion_url": item.get("discussion_url", ""),
    }


def build_article(item: dict, ai_item: dict | None) -> dict:
    base = fallback_article(item)
    if not isinstance(ai_item, dict):
        return base

    original = item["original_title"]
    title_zh = clean_text(ai_item.get("title_zh"), 200)
    title_en = clean_text(ai_item.get("title_en"), 200)
    summary_zh = clean_text(ai_item.get("summary_zh"), 600)
    summary_en = clean_text(ai_item.get("summary_en"), 600)
    complete = all([title_zh, title_en, summary_zh, summary_en])
    if complete:
        base.update({
            "title_zh": title_zh, "title_en": title_en,
            "summary_zh": summary_zh, "summary_en": summary_en,
            "ai_generated": True,
        })

    try:
        importance = int(ai_item.get("importance", base["importance"]))
        base["importance"] = max(1, min(5, importance))
    except (TypeError, ValueError):
        pass
    category = str(ai_item.get("category") or "").lower()
    if category in VALID_CATEGORIES:
        base["category"] = category
    tags = ai_item.get("tags")
    if isinstance(tags, list):
        base["tags"] = [clean_text(t, 30) for t in tags if isinstance(t, (str, int))][:5]
    event_group = clean_text(ai_item.get("event_group"), 60)
    if event_group:
        base["event_group"] = event_group
    if base["source_url"] != item["source_url"]:
        base["source_url"] = item["source_url"]
    if not base["original_title"]:
        base["original_title"] = original
    return base


def validate_trends(value) -> list:
    if not isinstance(value, list):
        return []
    trends = []
    for raw in value[:4]:
        if not isinstance(raw, dict):
            continue
        trend = {key: clean_text(raw.get(key), 300) for key in
                 ("title_zh", "title_en", "summary_zh", "summary_en")}
        if all(trend.values()):
            trends.append(trend)
    return trends


def process_with_ai(items: list, config: dict, run_date: str, force_disabled: bool = False) -> tuple:
    """返回 (articles, highlights, trends, meta)。"""
    api_key, base, model = ai_config()
    key = "" if force_disabled else api_key
    cfg = settings(config)
    batch = int(cfg.get("ai_batch_size", 25))
    batch_items = items[:batch]
    meta = {
        "ai_enabled": bool(key),
        "ai_status": "disabled" if not key else "ok",
        "ai_model": model if key else "",
        "ai_error": "",
    }

    ai_data = None
    if key:
        slim = [{
            "id": i["id"], "original_title": i["original_title"],
            "excerpt": i.get("excerpt", ""), "source": i["source"],
            "original_language": i.get("original_language", "en"),
            "event_key": i.get("event_key", ""),
            "hint_category": i.get("heuristic_category", ""),
        } for i in batch_items]
        prompt = USER_TEMPLATE.format(date=run_date, articles=json.dumps(slim, ensure_ascii=False))
        try:
            ai_data = call_ai(prompt, key, base, model)
            logger.info("AI 处理成功：%d 条", len(ai_data.get("articles") or []))
        except Exception as exc:
            meta["ai_status"] = "error"
            meta["ai_error"] = str(exc)[:400]
            logger.exception("AI 处理失败，启用降级: %s", exc)

    ai_map = {}
    if isinstance(ai_data, dict) and isinstance(ai_data.get("articles"), list):
        for entry in ai_data["articles"]:
            if isinstance(entry, dict) and entry.get("id"):
                ai_map[str(entry["id"])] = entry

    articles = [build_article(item, ai_map.get(item["id"])) for item in batch_items]
    if key and len(ai_map) < len(batch_items):
        meta["ai_status"] = "partial" if meta["ai_status"] == "ok" else meta["ai_status"]
        meta["ai_error"] = (meta["ai_error"] + " 部分新闻未获得 AI 结果。").strip()

    valid_ids = {a["id"] for a in articles}
    highlights = []
    if isinstance(ai_data, dict) and isinstance(ai_data.get("highlights"), list):
        for hid in ai_data["highlights"]:
            if str(hid) in valid_ids and str(hid) not in highlights:
                highlights.append(str(hid))
            if len(highlights) >= 5:
                break
    if not highlights:
        highlights = [a["id"] for a in sorted(articles, key=lambda a: -a["importance"])[:5]]

    trends = validate_trends(ai_data.get("trends")) if isinstance(ai_data, dict) else []
    if not trends and key:
        meta["ai_error"] = (meta["ai_error"] + " 趋势分析未返回。").strip()
    return articles, highlights, trends, meta
