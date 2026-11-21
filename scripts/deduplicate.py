"""多层去重、事件预聚合与精选。"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from utils import settings

logger = logging.getLogger(__name__)

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "fbclid", "gclid", "gbraid", "wbraid", "ref", "ref_src", "source", "spm", "from",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by", "from",
    "is", "are", "was", "were", "be", "new", "its", "it", "as", "that", "this", "after", "over",
    "says", "say", "how", "why", "what", "more", "into", "up", "about", "via", "zh", "en",
}


def normalize_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
        host = parts.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        path = parts.path.rstrip("/") or "/"
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")]
        query.sort()
        return urlunsplit(("", host, path, urlencode(query), ""))
    except Exception:
        return url.strip().lower()


def title_tokens(title: str) -> set:
    words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", (title or "").lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def similarity(a: str, b: str) -> float:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()
    jaccard = len(ta & tb) / len(ta | tb)
    sequence = SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()
    return max(jaccard, sequence)


def deduplicate(items: list) -> list:
    result = []
    url_map, titles = {}, []
    for item in items:
        norm = normalize_url(item["source_url"])
        candidate_title = normalize_title(item["original_title"])
        if norm in url_map:
            existing = url_map[norm]
            if item.get("heuristic_importance", 0) > existing.get("heuristic_importance", 0):
                result[result.index(existing)] = item
                url_map[norm] = item
            continue
        duplicate = None
        for idx, (_title, norm_title) in enumerate(titles):
            if similarity(norm_title, candidate_title) >= 0.86:
                duplicate = result[idx]
                break
        if duplicate is not None:
            if item.get("heuristic_importance", 0) > duplicate.get("heuristic_importance", 0):
                result[result.index(duplicate)] = item
            continue
        result.append(item)
        url_map[norm] = item
        titles.append((item["original_title"], candidate_title))
    logger.info("URL + 标题去重后剩余 %d / %d 条", len(result), len(items))
    return result


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\u4e00-\u9fff\s]", " ", (title or "").lower())).strip()


def group_events(items: list) -> list:
    """基于标题关键词重叠做事件预聚合，AI 阶段可进一步修正 event_group。"""
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    tokens = [title_tokens(i["original_title"]) for i in items]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            shared = tokens[i] & tokens[j]
            if len(shared) >= 2 and len(shared) / max(1, min(len(tokens[i]), len(tokens[j]))) >= 0.5:
                union(i, j)

    groups = {}
    for idx, item in enumerate(items):
        root = find(idx)
        groups.setdefault(root, []).append(item)
    for number, group in enumerate(sorted(groups.values(), key=lambda g: -len(g)), 1):
        event_key = "event-%02d" % number
        for item in group:
            item["event_key"] = event_key
            item["event_size"] = len(group)
    return items


def select_items(items: list, config: dict) -> list:
    cfg = settings(config)
    limit = int(cfg.get("max_articles", 25))

    def rank(item):
        signal = item.get("signal") or {}
        return (
            item.get("heuristic_importance", 2),
            int(signal.get("hn_points") or 0) / 200.0,
            int(signal.get("github_stars") or 0) / 2000.0,
            item.get("published_at", ""),
        )

    sorted_items = sorted(items, key=rank, reverse=True)
    selected, source_count, category_count = [], {}, {}
    source_cap = max(6, limit // 3)
    category_cap = max(10, limit // 2)
    for item in sorted_items:
        source = item.get("source", "unknown")
        category = item.get("heuristic_category", "internet")
        if source_count.get(source, 0) >= source_cap or category_count.get(category, 0) >= category_cap:
            continue
        selected.append(item)
        source_count[source] = source_count.get(source, 0) + 1
        category_count[category] = category_count.get(category, 0) + 1
        if len(selected) >= limit:
            break
    logger.info("精选 %d 条（上限 %d）", len(selected), limit)
    return selected


def process_dedup(items: list, config: dict) -> list:
    return select_items(group_events(deduplicate(items)), config)
