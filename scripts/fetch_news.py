"""新闻采集：RSS、Hacker News、GitHub Search API，以及本地演示数据。"""
from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import feedparser
import requests

from utils import (beijing_today, clean_text, http_get, normalize_source_frequency,
                   settings, to_utc_iso, utc_now_iso)

logger = logging.getLogger(__name__)

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def make_id(url: str) -> str:
    return "n" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def base_item(*, source: str, source_url: str, original_title: str,
              published_at, collected_at: str, original_language: str,
              categories, excerpt: str = "", **extra) -> dict:
    item = {
        "id": make_id(source_url),
        "source": source,
        "source_url": source_url,
        "original_title": clean_text(original_title, 300),
        "published_at": to_utc_iso(published_at),
        "collected_at": collected_at,
        "original_language": original_language,
        "categories": list(categories or []),
        "excerpt": clean_text(excerpt, 800),
        "signal": {},
    }
    item.update(extra)
    return item


def _get_with_ua_fallback(url: str, *, timeout: int, retries: int, user_agent: str,
                          params: dict | None = None) -> requests.Response:
    try:
        return http_get(url, timeout=timeout, retries=retries,
                        headers={"User-Agent": user_agent, "Accept": "*/*"}, params=params)
    except Exception as first_error:
        try:
            return http_get(url, timeout=timeout, retries=1,
                            headers={"User-Agent": BROWSER_UA, "Accept": "*/*"}, params=params)
        except Exception:
            raise first_error


def fetch_rss(source: dict, cfg: dict, collected_at: str) -> list:
    url = source["url"]
    response = _get_with_ua_fallback(
        url,
        timeout=int(source.get("timeout") or cfg.get("request_timeout", 12)),
        retries=int(source.get("retries") if source.get("retries") is not None else cfg.get("retry", 2)),
        user_agent=cfg.get("user_agent", "TechDailyBot/1.0"),
    )
    feed = feedparser.parse(response.content)
    entries = getattr(feed, "entries", []) or []
    if not entries and getattr(feed, "bozo", False):
        raise ValueError("RSS 解析失败: %s" % getattr(feed, "bozo_exception", "unknown"))

    items = []
    for entry in entries[:40]:
        link = (entry.get("link") or "").strip()
        title = (entry.get("title") or "").strip()
        if not link or not title or not link.startswith(("http://", "https://")):
            continue
        summary = entry.get("summary") or entry.get("description") or ""
        published = entry.get("published_parsed") or entry.get("updated_parsed") or entry.get("published")
        items.append(base_item(
            source=source["name"], source_url=link, original_title=title,
            published_at=published, collected_at=collected_at,
            original_language=source.get("language", "en"),
            categories=source.get("categories", []), excerpt=summary,
            source_note=source.get("note", ""),
            strict_relevance=bool(source.get("strict_relevance", False)),
        ))
    return items


def fetch_hackernews(source: dict, cfg: dict, collected_at: str) -> list:
    root = source["url"].rstrip("/")
    lists = source.get("lists") or ["topstories"]
    limit = int(cfg.get("hn_item_limit", 40))
    ids = []
    for list_name in lists:
        response = http_get(
            "%s/%s.json" % (root, list_name),
            timeout=int(source.get("timeout") or cfg.get("request_timeout", 12)),
            retries=int(source.get("retries") if source.get("retries") is not None else cfg.get("retry", 2)),
            headers={"User-Agent": cfg.get("user_agent", "TechDailyBot/1.0")},
        )
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Hacker News %s 返回格式异常" % list_name)
        ids.extend(data[:limit])
    ids = list(dict.fromkeys(int(i) for i in ids if str(i).isdigit()))[:limit * 2]

    def get_story(story_id: int):
        try:
            resp = http_get("%s/item/%d.json" % (root, story_id), timeout=8, retries=1)
            return resp.json()
        except Exception as exc:
            logger.debug("HN item %d 获取失败: %s", story_id, exc)
            return None

    raw_stories = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(get_story, sid) for sid in ids]
        for future in as_completed(futures):
            story = future.result()
            if story and story.get("type") == "story" and story.get("title"):
                raw_stories.append(story)

    items = []
    for story in raw_stories:
        score = int(story.get("score") or 0)
        comments = int(story.get("descendants") or 0)
        if score < 10 and comments < 3:
            continue
        link = story.get("url") or "https://news.ycombinator.com/item?id=%d" % story.get("id")
        if not str(link).startswith(("http://", "https://")):
            continue
        excerpt = clean_text(story.get("text") or "", 500)
        if not excerpt:
            excerpt = "Hacker News: %d points, %d comments." % (score, comments)
        items.append(base_item(
            source=source["name"], source_url=link, original_title=story["title"],
            published_at=story.get("time"), collected_at=collected_at,
            original_language="en", categories=source.get("categories", []),
            excerpt=excerpt,
            signal={"hn_points": score, "hn_comments": comments},
            discussion_url="https://news.ycombinator.com/item?id=%s" % story.get("id"),
            strict_relevance=bool(source.get("strict_relevance", False)),
        ))
    return items


def fetch_github(source: dict, cfg: dict, collected_at: str) -> list:
    params = dict(source.get("params") or {})
    since = (datetime.now(timezone.utc) - timedelta(days=int(cfg.get("github_window_days", 30)))).strftime("%Y-%m-%d")
    params["q"] = str(params.get("q", "created:>{date} stars:>200")).replace("{date}", since)
    headers = {
        "User-Agent": cfg.get("user_agent", "TechDailyBot/1.0"),
        "Accept": "application/vnd.github+json",
    }
    token = None
    import os
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer %s" % os.environ["GITHUB_TOKEN"]
        token = True
    response = http_get(
        source["url"],
        timeout=int(source.get("timeout") or cfg.get("request_timeout", 12)),
        retries=int(source.get("retries") if source.get("retries") is not None else cfg.get("retry", 2)),
        headers=headers, params=params,
    )
    data = response.json()
    repos = data.get("items") if isinstance(data, dict) else None
    if not isinstance(repos, list):
        raise ValueError("GitHub Search API 返回格式异常: %s" % str(data)[:160])

    note = "基于 GitHub 搜索 API 的近期高星仓库代理数据，非官方 Trending 排名。"
    items = []
    for repo in repos:
        url = repo.get("html_url")
        if not url:
            continue
        full_name = repo.get("full_name") or url.rsplit("/", 2)[-2] + "/" + url.rsplit("/", 1)[-1]
        stars = int(repo.get("stargazers_count") or 0)
        description = clean_text(repo.get("description") or "", 400)
        excerpt = description or ("Recently created repository with %d GitHub stars." % stars)
        items.append(base_item(
            source=source["name"], source_url=url, original_title=full_name,
            published_at=repo.get("created_at") or collected_at, collected_at=collected_at,
            original_language="en", categories=source.get("categories", []),
            excerpt=excerpt,
            signal={"github_stars": stars, "github_language": repo.get("language") or ""},
            source_note=note,
        ))
    logger.info("GitHub 搜索代理返回 %d 个仓库（认证: %s）", len(items), bool(token))
    return items


FETCHERS = {
    "rss": fetch_rss,
    "hackernews": fetch_hackernews,
    "github_search": fetch_github,
}


def fetch_all(config: dict, run_date: str | None = None) -> tuple:
    """返回 (原始新闻列表, 数据源统计列表)。每个来源独立容错。"""
    cfg = settings(config)
    run_date = run_date or beijing_today()
    collected_at = utc_now_iso()
    all_items, stats = [], []

    for source in config.get("sources", []):
        name = source.get("name", "unnamed")
        if not source.get("enabled", True):
            stats.append({"name": name, "status": "skipped", "count": 0, "error": "已禁用"})
            continue
        if not normalize_source_frequency(source.get("frequency"), run_date):
            stats.append({"name": name, "status": "skipped", "count": 0, "error": "采集频率不匹配"})
            continue
        fetcher = FETCHERS.get(source.get("type"))
        if not fetcher:
            stats.append({"name": name, "status": "failed", "count": 0,
                          "error": "未知数据源类型: %s" % source.get("type")})
            continue
        try:
            items = fetcher(source, cfg, collected_at)
            all_items.extend(items)
            stats.append({"name": name, "status": "ok", "count": len(items), "error": ""})
            logger.info("数据源 %s: 采集 %d 条", name, len(items))
        except Exception as exc:
            logger.exception("数据源 %s 采集失败: %s", name, exc)
            stats.append({"name": name, "status": "failed", "count": 0, "error": str(exc)[:300]})

    logger.info("采集完成：%d 个来源，共 %d 条原始新闻", len(stats), len(all_items))
    return all_items, stats


def fetch_demo_items(run_date: str | None = None) -> list:
    """生成用于页面联调的演示数据；所有链接指向 example.com，不代表真实新闻。"""
    run_date = run_date or beijing_today()
    collected_at = utc_now_iso()
    samples = [
        ("Open-source model release brings smaller, faster inference to edge devices", "ai", "en"),
        ("New developer preview expands local testing tools for cloud functions", "developers", "en"),
        ("Platform announces expanded moderation controls for large online communities", "internet", "en"),
        ("Security researchers describe a widely used patch workflow for exposed services", "security", "en"),
        ("Startup funding round highlights renewed interest in developer infrastructure", "business", "en"),
        ("Major technology company publishes updated API pricing and documentation", "companies", "en"),
        ("AI-assisted coding tools add support for multi-file repository changes", "ai", "en"),
        ("A new open source observability project reaches a major release milestone", "developers", "en"),
        ("Mobile platform update changes default privacy settings for applications", "internet", "en"),
        ("Industry group publishes guidance on responsible model evaluation", "security", "en"),
        ("Earlier-stage company reports growth in self-serve enterprise subscriptions", "business", "en"),
        ("Cloud provider extends regional availability for compute services", "companies", "en"),
        ("Researchers release benchmark for evaluating long-context language models", "ai", "en"),
        ("Community maintainers announce a new long-term support branch", "developers", "en"),
        ("Social platform begins testing a redesigned creator dashboard", "internet", "en"),
        ("Regulators publish draft requirements for incident reporting timelines", "security", "en"),
        ("Venture investors back a new team building data pipeline tooling", "business", "en"),
        ("Hardware maker details next-generation accelerator roadmap", "companies", "en"),
        ("AI product update focuses on retrieval quality and citation transparency", "ai", "en"),
        ("Developer conference agenda highlights practical deployment workflows", "developers", "en"),
    ]
    demos = []
    for idx, (title, category, lang) in enumerate(samples, 1):
        url = "https://example.com/demo/%s/%02d" % (run_date, idx)
        published = "%sT%02d:00:00Z" % (run_date, (idx % 20) + 1)
        demos.append(base_item(
            source="Demo Source · %s" % category, source_url=url, original_title=title,
            published_at=published, collected_at=collected_at, original_language=lang,
            categories=[category],
            excerpt="Demo article %d: headline and summary are generated for layout testing only; no real news event is represented." % idx,
            signal={"demo": True},
            source_note="示例数据（仅用于页面联调）",
        ))
    return demos


def demo_stats() -> list:
    return [{"name": "Demo Source · " + name, "status": "ok", "count": 3, "error": ""}
            for name in ("ai", "companies", "developers", "internet", "business", "security")]
