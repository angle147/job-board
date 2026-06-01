#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书浏览器爬虫 — Playwright + Stealth
========================================
通过真实浏览器访问小红书搜索页，绕过签名验证。
首次运行需要扫码登录（登录态自动保存）。

用法：
    python scrape_xiaohongshu_v2.py                     # 全部关键词
    python scrape_xiaohongshu_v2.py --keyword 济南校招    # 单个关键词
    python scrape_xiaohongshu_v2.py --headless           # 无头模式（需已有登录态）

输出：data/xiaohongshu_events.js
"""

import re
import json
import time
import random
import argparse
from datetime import datetime, timedelta, date
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_JS = DATA_DIR / "xiaohongshu_events.js"
USER_DATA_DIR = BASE_DIR.parent / "playwright_profile"

CAMPUS_KEYWORDS = [
    "济南 校园招聘会",
    "济南大学 双选会",
    "山东大学 校招 宣讲会",
    "山东交通学院 招聘会",
    "济南 高校 招聘会 2026",
    "山东 交通运输 校招",
]

SCROLL_TIMES = 5
SCROLL_DELAY = 1.5


def extract_event(title: str, desc: str, url: str, author: str, likes: str) -> dict | None:
    """从笔记提取招聘会信息"""
    full_text = f"{title} {desc}"
    if not any(kw in full_text for kw in ["招聘会", "双选会", "宣讲会", "校招", "春招", "秋招"]):
        return None

    # 日期
    date_str = ""
    for pat in [r"(\d{4}年\d{1,2}月\d{1,2}日)", r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", r"(\d{1,2}月\d{1,2}日)"]:
        m = re.search(pat, full_text)
        if m:
            date_str = m.group(1)
            break

    # 地点
    location = ""
    for pat in [r"(?:地点|地址|位置)[：:]\s*(.+?)(?:[\n，。,]|$)",
                r"(济南|青岛|山东)[\u4e00-\u9fa5]*(?:大学|学院|校区|体育馆|广场|中心|楼)[\u4e00-\u9fa5]*"]:
        m = re.search(pat, full_text)
        if m:
            location = m.group(0)[:50]
            break

    return {
        "title": title[:120],
        "description": desc[:500],
        "date": date_str,
        "location": location,
        "source": "小红书",
        "source_url": url,
        "author": author,
        "likes": str(likes or 0),
    }


def scrape_keyword(page, keyword: str, max_scroll: int = 5) -> list[dict]:
    """搜索一个关键词，滚动加载并提取笔记"""
    url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_search_result_notes"
    print(f"  🔍 {keyword}")
    page.goto(url, timeout=15000, wait_until="domcontentloaded")
    time.sleep(3)

    events = []
    seen_ids = set()

    for i in range(max_scroll):
        # 提取当前页笔记
        notes = page.query_selector_all("section.note-item, div.note-item, a[href*='/explore/']")
        for note in notes:
            try:
                href = note.get_attribute("href") or ""
                if "/explore/" not in href:
                    continue
                note_id = href.split("/explore/")[-1].split("?")[0]
                if note_id in seen_ids:
                    continue
                seen_ids.add(note_id)

                title_el = note.query_selector(".title, .note-title, span.title")
                desc_el = note.query_selector(".desc, .note-desc")
                author_el = note.query_selector(".author .name, .nickname")
                likes_el = note.query_selector(".like-count, .count")

                title = title_el.inner_text() if title_el else ""
                desc = desc_el.inner_text() if desc_el else ""
                author = author_el.inner_text() if author_el else ""
                likes = likes_el.inner_text() if likes_el else ""

                event = extract_event(
                    title or desc[:50],
                    desc or title,
                    f"https://www.xiaohongshu.com{href}" if href.startswith("/") else href,
                    author,
                    likes
                )
                if event:
                    events.append(event)
            except Exception:
                continue

        # 滚动
        page.evaluate("window.scrollBy(0, 800)")
        time.sleep(SCROLL_DELAY + random.random())

    return events


def _parse_date(date_str: str):
    if not date_str:
        return None
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", date_str)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{1,2})月(\d{1,2})日", date_str)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        now = datetime.now()
        year = now.year if month <= now.month else now.year - 1
        return date(year, month, day)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", type=str)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    keywords = [args.keyword] if args.keyword else CAMPUS_KEYWORDS
    headless = args.headless
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"{'='*60}")
    print(f"🔍 小红书浏览器爬虫 ({len(keywords)} 个关键词)")
    print(f"{'='*60}\n")

    with sync_playwright() as p:
        # 启动浏览器（持久化用户目录保存登录态）
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
        )

        page = browser.new_page()
        stealth_obj = Stealth()
        stealth_obj.apply_stealth_sync(page)

        if not headless:
            print("📱 浏览器已打开，请在浏览器中扫码登录小红书")
            print("   等待登录中（检测到登录后自动继续，最多等 60 秒）...")
            # 等待登录完成：检测页面是否出现用户头像或已登录状态
            page.goto("https://www.xiaohongshu.com", timeout=15000, wait_until="domcontentloaded")
            time.sleep(2)
            logged_in = False
            for _ in range(30):
                try:
                    # 检测登录状态：看是否有登录用户标识
                    has_avatar = page.query_selector(".user-avatar, .avatar, [class*='side-bar'] a[href*='profile']")
                    # 或者 URL 不再跳转到登录页
                    current_url = page.url
                    if has_avatar or "login" not in current_url:
                        logged_in = True
                        print("  ✅ 检测到登录状态，继续...")
                        break
                except:
                    pass
                time.sleep(2)
            if not logged_in:
                print("  ⚠ 未检测到登录，使用当前状态继续...")

        all_events = []
        for kw in keywords:
            events = scrape_keyword(page, kw, SCROLL_TIMES)
            all_events.extend(events)
            time.sleep(2 + random.random())

        browser.close()

    if not all_events:
        print("\n⚠ 未抓取任何招聘会信息")
        return

    # 去重 + 过期过滤
    now = datetime.now()
    cutoff = (now - timedelta(days=14)).date()
    seen_ids = set()
    unique = []

    for e in all_events:
        eid = e["source_url"][-40:]
        if eid in seen_ids:
            continue
        d = _parse_date(e.get("date", ""))
        if d and d < cutoff:
            continue
        seen_ids.add(eid)
        unique.append(e)

    unique.sort(key=lambda e: str(e.get("date", "")), reverse=True)

    # 输出 JS
    lines = [
        "// 小红书校园招聘会 — Playwright浏览器爬取",
        f"// {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"// {len(unique)} 条",
        "",
        "const XHS_EVENTS = [",
    ]
    for e in unique:
        lines.append("  {")
        for key in ["title", "description", "date", "location", "source", "source_url", "author", "likes"]:
            val = str(e.get(key, "")).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
            lines.append(f'    {key}: "{val}",')
        lines[-1] = lines[-1].rstrip(",")
        lines.append("  },")
    lines.append("];\n")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JS.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"📊 完成: {len(unique)} 条招聘会信息")
    print(f"📁 {OUTPUT_JS}")


if __name__ == "__main__":
    main()
