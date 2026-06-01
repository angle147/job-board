#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博校园招聘会爬虫
===================
基于 crawl4weibo，搜索济南高校招聘会信息。无需 Cookie。

用法：
    python scrape_weibo.py                         # 全部关键词
    python scrape_weibo.py --keyword 济南校招        # 单个关键词

输出：data/weibo_events.json + data/weibo_events.html
"""

import re
import json
import time
import random
import hashlib
import argparse
from datetime import datetime, timedelta, date
from pathlib import Path

from crawl4weibo import WeiboClient

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_JSON = DATA_DIR / "weibo_events.json"
OUTPUT_HTML = DATA_DIR / "weibo_events.html"
OUTPUT_JS = DATA_DIR / "weibo_events.js"

# 济南校园招聘会关键词（扩充覆盖）
CAMPUS_KEYWORDS = [
    # 综合招聘会
    "济南 校园招聘会",
    "济南 双选会",
    "济南 高校 招聘会 2026",
    "济南 春招 双选会 2026",
    "济南 国企 校招 招聘会",
    "济南 人社局 招聘会",
    "选择济南 共赢未来 招聘会",
    "就选山东 招聘会 济南",
    # 各高校
    "山东大学 校招 宣讲会",
    "山东大学 双选会",
    "济南大学 双选会",
    "济南大学 宣讲会",
    "山东建筑大学 招聘会",
    "山东建筑大学 双选会",
    "齐鲁工业大学 招聘会",
    "齐鲁工业大学 双选会",
    "山东交通学院 招聘会",
    "山东交通学院 双选会",
    "山东财经大学 招聘会",
    "山东财经大学 双选会",
    "济南职业学院 招聘会",
    "山东师范大学 招聘会",
    "山东政法学院 招聘会",
    "青岛大学 校招 双选会",
    # 行业相关
    "山东 交通运输 校园招聘",
    "山东 物流 校招 招聘会",
    "济南 交通 双选会",
]

REQUEST_DELAY = 0.8


def extract_event_from_post(post) -> dict | None:
    """从微博帖子提取招聘会信息"""
    text = post.text or ""
    if len(text) < 10:
        return None

    # 必须有招聘会关键词
    event_kw = ["招聘会", "双选会", "宣讲会", "校招", "春招", "秋招",
                "校园招聘", "供需见面", "人才对接"]
    if not any(kw in text for kw in event_kw):
        return None

    # 提取时间
    date_str = ""
    time_patterns = [
        r"(\d{4}年\d{1,2}月\d{1,2}日)",
        r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
        r"(\d{1,2}月\d{1,2}日)[\s\-～]*(\d{1,2}:\d{2})?",
    ]
    for pat in time_patterns:
        m = re.search(pat, text)
        if m:
            date_str = m.group(1)
            break

    if not date_str:
        date_str = str(post.created_at)[:10] if post.created_at else ""

    # 提取地点
    location = ""
    loc_patterns = [
        r"(?:地点|地址|位置|举办地点)[：:]\s*(.+?)(?:[\n，。,]|$)",
        r"(济南|青岛|山东)[\u4e00-\u9fa5]*(?:大学|学院|校区|体育馆|报告厅|广场|中心|楼)[\u4e00-\u9fa5]*",
    ]
    for pat in loc_patterns:
        m = re.search(pat, text)
        if m:
            location = m.group(0).strip()[:50]
            break

    # 提取参会企业
    companies = list(set(re.findall(
        r'[\u4e00-\u9fa5]{2,20}(?:集团|有限公司|公司|银行|证券|保险|航空|港口|物流|水务|高速|轨道|地铁)',
        text
    )))[:10]

    # 提取链接
    urls = re.findall(r'https?://[^\s]+', text)

    return {
        "id": hashlib.md5((post.id or text[:50]).encode()).hexdigest()[:12],
        "title": text[:100].replace("\n", " "),
        "description": text[:500],
        "date": date_str,
        "location": location,
        "companies": companies,
        "source": "微博",
        "source_url": f"https://m.weibo.cn/detail/{post.id}" if post.id else "",
        "author": str(post.user_id) if post.user_id else "",
        "likes": str(post.attitudes_count or 0),
        "reposts": str(post.reposts_count or 0),
        "urls": urls,
        "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _parse_date(date_str: str):
    """解析中文日期 → date 对象"""
    import re as _re
    if not date_str:
        return None
    m = _re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", date_str)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _re.match(r"(\d{1,2})月(\d{1,2})日", date_str)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        now = datetime.now()
        year = now.year if month <= now.month else now.year - 1
        return date(year, month, day)
    return None


def main():
    parser = argparse.ArgumentParser(description="微博校园招聘会爬虫")
    parser.add_argument("--keyword", type=str, help="单个关键词")
    parser.add_argument("--max-pages", type=int, default=2, help="每个关键词翻页数")
    args = parser.parse_args()

    client = WeiboClient()
    keywords = [args.keyword] if args.keyword else CAMPUS_KEYWORDS

    print(f"{'='*60}")
    print(f"🔍 微博 — 济南校园招聘会 ({len(keywords)} 个关键词)")
    print(f"{'='*60}\n")

    all_events = []
    for kw in keywords:
        print(f"  🔍 {kw}")
        for page in range(1, args.max_pages + 1):
            try:
                posts, pagination = client.search_posts(kw, page=page)
                if not posts:
                    break
                for post in posts:
                    event = extract_event_from_post(post)
                    if event:
                        all_events.append(event)
                print(f"    📄 第{page}页: {len(posts)} 条, 匹配 {sum(1 for p in posts if extract_event_from_post(p))} 条招聘会")
                if not pagination.get("has_more"):
                    break
                time.sleep(REQUEST_DELAY + random.random())
            except Exception as e:
                print(f"    ⚠ 第{page}页失败: {e}")
                break
        time.sleep(1)

    # 去重 + 过期过滤（仅保留近两周）
    now = datetime.now()
    two_weeks_ago = (now - timedelta(days=14)).date()

    seen = set()
    unique = []
    for e in all_events:
        # 解析日期
        d = _parse_date(e.get("date", ""))
        if d and d < two_weeks_ago:
            continue  # 过期，跳过
        key = e["id"]
        if key not in seen:
            seen.add(key)
            unique.append(e)

    unique.sort(key=lambda e: e.get("date", ""), reverse=True)

    # 保存 JSON
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")

    # 生成 HTML
    items_html = ""
    for e in unique[:30]:
        companies_str = "、".join(e.get("companies", [])[:5]) or "待确认"
        urls_str = " ".join(
            f'<a href="{u}" target="_blank">🔗</a>' for u in e.get("urls", [])[:3]
        )
        items_html += f"""
        <div style="border:1px solid #e2e8f0;border-radius:8px;padding:12px;margin:8px 0;background:white;">
            <div style="font-weight:700;font-size:15px;">{e.get('title','无标题')[:120]}</div>
            <div style="color:#64748b;font-size:12px;margin:4px 0;">
                📅 {e.get('date','')} | 📍 {e.get('location','未知')}
                | ❤️ {e.get('likes','0')} | 🔄 {e.get('reposts','0')}
            </div>
            <div style="font-size:12px;color:#2563eb;margin:4px 0;">
                🏢 {companies_str}
            </div>
            <div style="margin-top:4px;">
                <a href="{e.get('source_url','')}" target="_blank" style="font-size:11px;color:#64748b;">查看原文 →</a>
                {urls_str}
            </div>
        </div>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>微博招聘会汇总</title>
<style>body{{font-family:PingFang SC,Microsoft YaHei,sans-serif;max-width:800px;margin:0 auto;padding:16px;background:#f0f2f5}}
h2{{color:#1e293b}}</style></head><body>
<h2>🐦 微博 · 济南校园招聘会 ({len(unique)}条)</h2>
{items_html}
<p style="color:#94a3b8;font-size:11px;text-align:center;margin-top:20px;">
自动爬取于 {datetime.now().strftime('%Y-%m-%d %H:%M')} | 数据来源: 微博搜索
</p></body></html>"""
    OUTPUT_HTML.write_text(html, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"📊 完成: {len(unique)} 条招聘会信息")
    print(f"📁 JSON: {OUTPUT_JSON}")
    print(f"📁 JS: {OUTPUT_JS}")
    print(f"📄 HTML: {OUTPUT_HTML}")

    # 输出 JS 文件供网页加载
    js_lines = [
        "// 微博校园招聘会 — 自动爬取",
        f"// {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"// {len(unique)} 条",
        "",
        "const WEIBO_EVENTS = [",
    ]
    for e in unique:
        js_lines.append("  {")
        for key in ["id", "title", "description", "date", "location",
                     "source", "source_url", "author", "likes"]:
            val = str(e.get(key, "")).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
            js_lines.append(f'    {key}: "{val}",')
        # companies is an array
        companies = e.get("companies", [])
        js_lines.append(f'    companies: {json.dumps(companies, ensure_ascii=False)},')
        js_lines[-1] = js_lines[-1].rstrip(",")
        js_lines.append("  },")
    js_lines.append("];\n")
    OUTPUT_JS.write_text("\n".join(js_lines), encoding="utf-8")


if __name__ == "__main__":
    main()
