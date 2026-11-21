"""生成前的数据完整性校验；校验失败时不得写入线上数据。"""
from __future__ import annotations

from utils import VALID_CATEGORIES, is_valid_date, parse_iso

REQUIRED_ARTICLE_FIELDS = (
    "id", "title_zh", "title_en", "summary_zh", "summary_en", "source", "source_url",
    "original_title", "original_language", "published_at", "collected_at", "category",
    "tags", "importance", "event_group", "ai_generated",
)


class ValidationError(Exception):
    pass


def validate_daily(data: dict) -> bool:
    errors = []
    if not isinstance(data, dict):
        raise ValidationError("日报数据必须是 JSON 对象")

    if not is_valid_date(data.get("date", "")):
        errors.append("date 缺失或格式错误")
    try:
        parse_iso(data.get("generated_at", ""))
    except Exception:
        errors.append("generated_at 缺失或格式错误")

    articles = data.get("articles")
    if not isinstance(articles, list) or not articles:
        errors.append("articles 必须是非空数组")
        articles = []
    if len(articles) > 40:
        errors.append("单日新闻数超过 40 条，疑似异常")
    if data.get("article_count") != len(articles):
        errors.append("article_count 与实际条数不一致")

    ids = set()
    for index, article in enumerate(articles):
        prefix = "articles[%d]" % index
        if not isinstance(article, dict):
            errors.append("%s 不是对象" % prefix)
            continue
        for field in REQUIRED_ARTICLE_FIELDS:
            if field not in article:
                errors.append("%s 缺少字段 %s" % (prefix, field))
        aid = article.get("id")
        if not isinstance(aid, str) or not aid or aid in ids:
            errors.append("%s id 缺失或重复" % prefix)
        ids.add(aid)
        for text_field in ("title_zh", "title_en", "summary_zh", "summary_en",
                           "source", "original_title", "category"):
            if not isinstance(article.get(text_field), str) or not article[text_field].strip():
                errors.append("%s.%s 必须非空字符串" % (prefix, text_field))
        url = article.get("source_url", "")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            errors.append("%s.source_url 不是有效链接" % prefix)
        if article.get("category") not in VALID_CATEGORIES:
            errors.append("%s.category 不在六大分类内" % prefix)
        importance = article.get("importance")
        if not isinstance(importance, int) or isinstance(importance, bool) or not 1 <= importance <= 5:
            errors.append("%s.importance 必须是 1-5 的整数" % prefix)
        if not isinstance(article.get("tags"), list):
            errors.append("%s.tags 必须是数组" % prefix)
        if not isinstance(article.get("ai_generated"), bool):
            errors.append("%s.ai_generated 必须是布尔值" % prefix)
        for time_field in ("published_at", "collected_at"):
            try:
                parse_iso(article.get(time_field, ""))
            except Exception:
                errors.append("%s.%s 时间格式错误" % (prefix, time_field))

    highlights = data.get("highlights")
    if not isinstance(highlights, list) or any(h not in ids for h in highlights):
        errors.append("highlights 必须是已存在的新闻 id 数组")
    trends = data.get("trends")
    if not isinstance(trends, list) or len(trends) > 6:
        errors.append("trends 必须是数组且不超过 6 条")
    else:
        for trend in trends:
            if not isinstance(trend, dict) or any(
                not isinstance(trend.get(k), str) or not trend[k].strip()
                for k in ("title_zh", "title_en", "summary_zh", "summary_en")
            ):
                errors.append("trends 条目字段不完整")
    if not isinstance(data.get("source_stats"), list):
        errors.append("source_stats 必须是数组")

    if errors:
        raise ValidationError("数据校验失败:\n- " + "\n- ".join(errors))
    return True
