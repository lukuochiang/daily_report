"""静态站点生成：JSON 数据、每日 HTML、归档、分类页与 SEO 文件。"""
from __future__ import annotations

import glob
import os
import re

from jinja2 import Environment, FileSystemLoader, select_autoescape

from utils import (CATEGORY_NAMES, ROOT, beijing_time, read_json, utc_now_iso,
                   write_if_changed, write_json)

TEMPLATES_DIR = os.path.join(ROOT, "templates")
PUBLIC_DIR = os.path.join(ROOT, "public")
DATA_DIR = os.path.join(PUBLIC_DIR, "data")
SITE_URL = os.environ.get("SITE_URL", "https://daily.fs.kg").rstrip("/")
DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")

env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)
env.globals["cat_name"] = lambda slug, lang="zh": CATEGORY_NAMES.get(
    slug, ("其他", "Other"))[0 if lang == "zh" else 1]
env.globals["site_url"] = SITE_URL


def prepare_article(article: dict) -> dict:
    item = dict(article)
    item["time_bj"] = beijing_time(article.get("published_at", ""))
    item["date_bj"] = beijing_time(article.get("published_at", ""), "%Y-%m-%d")
    item["cat_zh"], item["cat_en"] = CATEGORY_NAMES.get(
        article.get("category", "internet"), ("其他", "Other"))
    level = article.get("importance", 2)
    item["stars"] = "★" * level + "☆" * (5 - level)
    return item


def load_days() -> list:
    days = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
        match = DATE_FILE_RE.match(os.path.basename(path))
        if not match:
            continue
        try:
            data = read_json(path)
            if data.get("date") == match.group(1) and isinstance(data.get("articles"), list):
                days.append((match.group(1), data))
        except Exception:
            continue
    days.sort(key=lambda pair: pair[0], reverse=True)
    return days


def base_context(**kwargs) -> dict:
    context = {
        "site_url": SITE_URL,
        "generated_at": utc_now_iso(),
        "lang": "zh",
    }
    context.update(kwargs)
    return context


def render(template_name: str, output_path: str, context: dict) -> None:
    content = env.get_template(template_name).render(**context)
    write_if_changed(output_path, content)


def app_data(articles: list) -> list:
    return [{
        "id": a.get("id"), "category": a.get("category"), "importance": a.get("importance"),
        "published_at": a.get("published_at"), "time_bj": a.get("time_bj"),
        "source": a.get("source"),
        "search": " ".join(str(a.get(k) or "") for k in
                           ("title_zh", "title_en", "summary_zh", "summary_en", "source", "original_title"))
                  .lower() + " " + " ".join(a.get("tags") or []).lower(),
    } for a in articles]


def generate_archives_json(days: list) -> dict:
    return {
        "dates": [date for date, _ in days],
        "counts": {date: len(data.get("articles", [])) for date, data in days},
        "total_days": len(days),
        "total_articles": sum(len(data.get("articles", [])) for _, data in days),
        "updated_at": max([data.get("generated_at", "") for _, data in days] or [""]),
    }


def generate_robots() -> str:
    return ("User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % SITE_URL)


def generate_sitemap(days: list) -> str:
    urls = [("/", None), ("/archives/", None), ("/about/", None)]
    urls += [("/categories/%s/" % slug, None) for slug in CATEGORY_NAMES]
    urls += [("/daily/%s/" % date, date) for date, _ in days]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, date in urls:
        lines.append("  <url><loc>%s%s</loc>%s</url>" % (
            SITE_URL, path,
            "<lastmod>%s</lastmod>" % date if date else ""))
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def generate_site(current_data: dict) -> dict:
    """写入全部静态文件；返回归档信息。"""
    date = current_data["date"]
    write_json(os.path.join(DATA_DIR, "%s.json" % date), current_data)
    write_json(os.path.join(DATA_DIR, "latest.json"),
               dict(current_data, latest_date=date))

    days = load_days()
    if not any(d == date for d, _ in days):
        days.insert(0, (date, current_data))
        days.sort(key=lambda pair: pair[0], reverse=True)
    archives = generate_archives_json(days)
    write_json(os.path.join(DATA_DIR, "archives.json"), archives)

    latest_date, latest_data = days[0]
    latest_articles = [prepare_article(a) for a in latest_data["articles"]]
    highlights = [prepare_article(a) for a in latest_articles if a["id"] in latest_data.get("highlights", [])]
    if not highlights:
        highlights = sorted(latest_articles, key=lambda a: -a["importance"])[:5]

    global_ctx = {
        "latest_date": latest_date,
        "latest_count": len(latest_articles),
        "total_days": archives["total_days"],
        "total_articles": archives["total_articles"],
        "ai_status": latest_data.get("ai", {}).get("ai_status", "disabled"),
        "is_demo": bool(latest_data.get("is_demo")),
    }

    render("index.html", os.path.join(PUBLIC_DIR, "index.html"), base_context(
        page_title="科技互联网每日一报 · Tech Internet Daily",
        page_description="每日精选全球科技、互联网、人工智能与开发者生态资讯，提供中英双语摘要。",
        canonical=SITE_URL + "/",
        current_date=latest_date, articles=latest_articles, highlights=highlights,
        trends=latest_data.get("trends", []), app_data=app_data(latest_articles),
        prev_day=None, next_day=None, **global_ctx,
    ))

    for index, (day, data) in enumerate(days):
        articles = [prepare_article(a) for a in data["articles"]]
        day_highlights = [a for a in articles if a["id"] in data.get("highlights", [])]
        if not day_highlights:
            day_highlights = sorted(articles, key=lambda a: -a["importance"])[:5]
        prev_day = days[index + 1][0] if index + 1 < len(days) else None
        next_day = days[index - 1][0] if index > 0 else None
        day_context = base_context(
            page_title="%s 科技互联网日报 · Tech Daily" % day,
            page_description="%s 每日科技互联网资讯精选，含中英双语标题与 AI 整理摘要。" % day,
            canonical="%s/daily/%s/" % (SITE_URL, day),
            current_date=day, articles=articles, highlights=day_highlights,
            trends=data.get("trends", []), app_data=app_data(articles),
            prev_day=prev_day, next_day=next_day,
            day_article_count=len(articles), **global_ctx,
        )
        day_context["ai_status"] = data.get("ai", {}).get("ai_status", "disabled")
        day_context["is_demo"] = bool(data.get("is_demo"))
        render("daily.html", os.path.join(PUBLIC_DIR, "daily", day, "index.html"), day_context)

    months = {}
    for day, data in days:
        month = day[:7]
        months.setdefault(month, []).append({
            "date": day, "count": len(data.get("articles", [])),
            "url": "%s/daily/%s/" % (SITE_URL, day),
            "label": "%s 年 %d 月" % (month[:4], int(month[5:])),
        })
    month_list = [{"key": key, "dates": values, "label": values[0]["label"]}
                  for key, values in sorted(months.items(), reverse=True)]

    render("archives.html", os.path.join(PUBLIC_DIR, "archives", "index.html"), base_context(
        page_title="历史日报归档 · Archives | 科技互联网每日一报",
        page_description="按日期浏览科技互联网每日一报的全部历史日报。",
        canonical=SITE_URL + "/archives/",
        months=month_list, **global_ctx,
    ))

    for slug in CATEGORY_NAMES:
        category_articles = []
        for day, data in days:
            for article in data["articles"]:
                if article.get("category") == slug:
                    item = prepare_article(article)
                    item["day"] = day
                    item["day_url"] = "%s/daily/%s/" % (SITE_URL, day)
                    category_articles.append(item)
        category_articles.sort(key=lambda a: a.get("published_at", ""), reverse=True)
        category_articles = category_articles[:80]
        zh, en = CATEGORY_NAMES[slug]
        render("category.html", os.path.join(PUBLIC_DIR, "categories", slug, "index.html"), base_context(
            page_title="%s · 科技互联网每日一报" % zh,
            page_description="浏览“%s”分类下的科技互联网新闻与中英双语摘要。" % zh,
            canonical="%s/categories/%s/" % (SITE_URL, slug),
            category_slug=slug, category_zh=zh, category_en=en,
            articles=category_articles, app_data=app_data(category_articles), **global_ctx,
        ))

    render("about.html", os.path.join(PUBLIC_DIR, "about", "index.html"), base_context(
        page_title="关于我们 · About | 科技互联网每日一报",
        page_description="了解科技互联网每日一报的数据来源、AI 整理方式、更新频率与版权声明。",
        canonical=SITE_URL + "/about/", **global_ctx,
    ))
    render("404.html", os.path.join(PUBLIC_DIR, "404.html"), base_context(
        page_title="页面未找到 · 404 | 科技互联网每日一报",
        page_description="您访问的页面不存在。",
        canonical=SITE_URL + "/404.html", **global_ctx,
    ))

    write_if_changed(os.path.join(PUBLIC_DIR, "robots.txt"), generate_robots())
    write_if_changed(os.path.join(PUBLIC_DIR, "sitemap.xml"), generate_sitemap(days))
    return archives
