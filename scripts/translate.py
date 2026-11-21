"""零配置双语回退：使用公开的 Google Translate 接口自动翻译，失败时返回空字符串。"""
from __future__ import annotations

import logging
import os
import time

import requests

from utils import clean_text

logger = logging.getLogger(__name__)

ENDPOINT = "https://translate.googleapis.com/translate_a/single"
_CACHE = {}


def enabled() -> bool:
    return os.environ.get("TRANSLATE_ENABLED", "true").strip().lower() not in ("0", "false", "no")


def translate(text: str, target_lang: str, *, timeout: int = 10) -> str:
    """翻译单段文本；不抛异常，失败返回空字符串。"""
    text = clean_text(text, 1000)
    if not text:
        return ""
    key = (target_lang, text)
    if key in _CACHE:
        return _CACHE[key]

    if not enabled():
        return ""

    for attempt in range(2):
        try:
            response = requests.get(
                ENDPOINT,
                params={"client": "gtx", "sl": "auto", "tl": target_lang, "dt": "t", "q": text},
                headers={"User-Agent": "Mozilla/5.0 (compatible; TechDailyBot/1.0)"},
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            segments = data[0] if isinstance(data, list) and data else []
            result = "".join(str(seg[0]) for seg in segments if isinstance(seg, list) and seg and seg[0])
            result = clean_text(result, 1000)
            _CACHE[key] = result
            time.sleep(0.12)
            return result
        except Exception as exc:
            logger.debug("自动翻译失败（第 %d 次，目标 %s）: %s", attempt + 1, target_lang, str(exc)[:160])
            time.sleep(0.3 * (attempt + 1))
    _CACHE[key] = ""
    return ""
