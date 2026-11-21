"""数据清洗：字段规整、时间校验、语言识别、相关性过滤与启发式评分。"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from utils import VALID_CATEGORIES, clean_text, contains_cjk, parse_iso

logger = logging.getLogger(__name__)

CATEGORY_KEYWORDS = {
    "ai": ["ai", "artificial intelligence", "llm", "large language model", "model", "gpt", "gemini",
           "claude", "deepseek", "diffusion", "neural", "machine learning", "inference", "agent",
           "language model", "artificial", "人工智能", "大模型", "模型", "智能体", "推理", "训练"],
    "companies": ["apple", "google", "microsoft", "amazon", "meta", "nvidia", "tesla", "netflix",
                  "samsung", "openai", "anthropic", "company", "companies", "acquisition", "earnings",
                  "company", "公司", "苹果", "谷歌", "微软", "英伟达", "收购", "财报"],
    "developers": ["developer", "open source", "opensource", "github", "api", "sdk", "framework",
                   "library", "repository", "compiler", "runtime", "database", "tooling", "programming",
                   "software", "code", "开发者", "开源", "框架", "工具链", "代码", "数据库"],
    "internet": ["platform", "social", "browser", "search", "mobile", "app", "website", "creator",
                 "internet", "online", "app store", "social media", "平台", "社交", "浏览器", "应用", "互联网"],
    "business": ["startup", "funding", "investment", "venture", "series a", "series b", "valuation",
                 "ipo", "revenue", "business", "subscriber", "公司", "融资", "创业", "投资", "估值", "营收", "上市"],
    "security": ["security", "breach", "vulnerability", "cyber", "attack", "privacy", "policy",
                 "regulation", "regulator", "lawsuit", "compliance", "encrypt", "exposed", "jam",
                 "安全", "漏洞", "隐私", "监管", "政策", "攻击", "泄露"],
}

TECH_KEYWORDS = [
    "ai", "artificial intelligence", "model", "llm", "machine learning", "software", "developer",
    "open source", "github", "programming", "code", "api", "sdk", "database", "cloud", "compute",
    "chip", "semiconductor", "processor", "cpu", "gpu", "hardware", "robot", "robotics", "internet",
    "platform", "browser", "app", "mobile", "startup", "funding", "cyber", "security", "privacy",
    "vulnerability", "data center", "quantum", "encryption", "tech", "technology", "network",
    "web", "server", "algorithm", "arxiv", "release", "repository", "framework", "tool",
    "acquisition", "funding", "merger", "ipo", "valuation", "billion", "robot", "量子", "机器人",
    "芯片", "算法", "开源", "互联网", "平台", "软件", "硬件", "网络", "数据", "模型", "安全", "隐私",
]

PROMO_PATTERNS = [
    "coupon", "promo code", "promo", "discount", "% off", "deal of", "flash sale",
    "giveaway", "subscribe now", "affiliate", "buy now", "clearance", "sale price",
    "deals", "cyber week", "black friday", "best deals", "shop now", "lowest price",
]

HIGH_VALUE_KEYWORDS = [
    "launch", "release", "announce", "unveil", "introduce", "acquire", "acquisition", "merger",
    "funding", "raises", "ipo", "breakthrough", "vulnerability", "breach", "regulation", "ban",
    "lawsuit", "record", "milestone", "open source", "发布", "推出", "收购", "融资", "漏洞", "监管",
]


def keyword_hits(text: str, keywords) -> int:
    """ ASCII 关键词按词边界匹配，避免 'ai' 命中 'said'；中文按子串匹配。 """
    text = (text or "").lower()
    hits = 0
    for word in keywords:
        if re.search(r"[\u4e00-\u9fff]", word):
            if word in text:
                hits += 1
        elif re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(word), text):
            hits += 1
    return hits


def relevance_score(item: dict) -> int:
    title = item.get("original_title", "")
    excerpt = item.get("excerpt", "")
    return keyword_hits(title, TECH_KEYWORDS) * 2 + keyword_hits(excerpt, TECH_KEYWORDS)


def guess_category(item: dict) -> str:
    text = (item.get("original_title") or "") + " " + (item.get("excerpt") or "")
    scores = {cat: keyword_hits(text, words) for cat, words in CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    for category in (item.get("categories") or []):
        if category in VALID_CATEGORIES:
            return category
    return "internet"


def heuristic_importance(item: dict, category: str) -> int:
    text = ((item.get("original_title") or "") + " " + (item.get("excerpt") or "")).lower()
    score = 2
    if any(word in text for word in HIGH_VALUE_KEYWORDS):
        score += 1
    signal = item.get("signal") or {}
    if int(signal.get("hn_points") or 0) >= 150 or int(signal.get("github_stars") or 0) >= 800:
        score += 1
    if category in ("ai", "security"):
        score += 1
    try:
        hours = (datetime.now(timezone.utc) - parse_iso(item["published_at"])).total_seconds() / 3600
        if 0 <= hours <= 36:
            score += 1
    except Exception:
        pass
    return max(1, min(5, score))


def clean_all(raw_items: list) -> list:
    cleaned, seen_ids = [], set()
    now = datetime.now(timezone.utc)

    for item in raw_items:
        title = clean_text(item.get("original_title"), 300)
        url = str(item.get("source_url") or "").strip()
        if len(title) < 8 or not url.startswith(("http://", "https://")):
            logger.debug("丢弃无效新闻: %s", title[:60])
            continue
        if any(pattern in title.lower() for pattern in PROMO_PATTERNS):
            logger.debug("丢弃促销内容: %s", title[:60])
            continue
        if item.get("id") in seen_ids:
            continue
        try:
            published = parse_iso(item["published_at"])
            age_days = (now - published).days
            if age_days > 21 or age_days < -1:
                logger.debug("丢弃时间异常新闻: %s (%s)", title[:60], item["published_at"])
                continue
        except Exception:
            item["published_at"] = item.get("collected_at")

        item["original_title"] = title
        item["source_url"] = url
        item["excerpt"] = clean_text(item.get("excerpt"), 800) or title
        item["original_language"] = "zh" if contains_cjk(title) else (item.get("original_language") or "en")
        item["relevance_score"] = relevance_score(item)
        if item.get("strict_relevance") and item["relevance_score"] < 2:
            logger.debug("丢弃科技相关性不足的条目: %s", title[:60])
            continue
        item["heuristic_category"] = guess_category(item)
        item["heuristic_importance"] = heuristic_importance(item, item["heuristic_category"])
        cleaned.append(item)
        seen_ids.add(item.get("id"))

    logger.info("清洗后剩余 %d / %d 条", len(cleaned), len(raw_items))
    return cleaned
