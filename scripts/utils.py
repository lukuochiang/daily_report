"""通用工具：配置、HTTP、时间、文本与文件写入。"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import time as time_module
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "public", "data")
BEIJING = timezone(timedelta(hours=8))

CATEGORY_NAMES = {
    "ai": ("人工智能", "AI & Artificial Intelligence"),
    "companies": ("科技公司", "Tech Companies"),
    "developers": ("开发者生态", "Developer Ecosystem"),
    "internet": ("互联网动态", "Internet & Platforms"),
    "business": ("创业与商业", "Startups & Business"),
    "security": ("网络安全与政策", "Cybersecurity & Policy"),
}

VALID_CATEGORIES = tuple(CATEGORY_NAMES.keys())

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_config(path: str | None = None) -> dict:
    path = path or os.path.join(ROOT, "config", "sources.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    if not isinstance(config, dict) or "sources" not in config:
        raise ValueError("配置文件格式错误：缺少 sources")
    return config


def settings(config: dict) -> dict:
    return config.get("settings") or {}


def beijing_today() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_source_frequency(frequency: str, run_date: str) -> bool:
    """按采集频率判断是否应在当天采集。"""
    if not frequency or frequency == "daily":
        return True
    if frequency == "weekly":
        return datetime.strptime(run_date, "%Y-%m-%d").weekday() == 0
    if frequency == "weekdays":
        return datetime.strptime(run_date, "%Y-%m-%d").weekday() < 5
    return True


def http_get(url: str, *, timeout: int = 12, retries: int = 2,
             headers: dict | None = None, params: dict | None = None,
             session: requests.Session | None = None) -> requests.Response:
    """带有限重试与超时的 GET；全部失败时抛出最后一次异常。"""
    client = session or requests
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = client.get(url, timeout=timeout, headers=headers, params=params)
            response.raise_for_status()
            return response
        except Exception as exc:  # 网络、HTTP 状态错误统一进入重试
            last_error = exc
            if attempt < retries:
                time_module.sleep(0.6 * (attempt + 1))
    raise last_error


def to_utc_iso(value) -> str:
    """将 feedparser/API/字符串/时间戳统一为 UTC ISO8601 字符串。"""
    if value is None or value == "":
        return utc_now_iso()
    if hasattr(value, "tm_year"):  # time.struct_time（feedparser 为 UTC）
        try:
            dt = datetime(*value[:6], tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return utc_now_iso()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return utc_now_iso()
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, str):
        text = value.strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(text)
            return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass
        if text.isdigit():
            return to_utc_iso(int(text))
    return utc_now_iso()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def beijing_time(iso_value: str, fmt: str = "%Y-%m-%d %H:%M") -> str:
    try:
        return parse_iso(iso_value).astimezone(BEIJING).strftime(fmt)
    except Exception:
        return iso_value


HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def clean_text(value, limit: int | None = None) -> str:
    if not value:
        return ""
    text = html.unescape(str(value))
    text = HTML_TAG_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", text or ""))


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_if_changed(path: str, content: str) -> bool:
    """内容无变化时不写盘，避免 GitHub Actions 产生空提交。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            if fh.read() == content:
                return False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return True


def is_valid_date(value: str) -> bool:
    if not DATE_RE.match(value or ""):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False
