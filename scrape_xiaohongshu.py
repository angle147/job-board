#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书校园招聘会爬虫
=====================
基于 Spider_XHS，搜索济南高校校园招聘会信息。
首次使用需要先在 Spider_XHS-master/.env 中填入小红书 Cookie。

用法：
    python scrape_xiaohongshu.py                     # 全部关键词
    python scrape_xiaohongshu.py --keyword 济南校招    # 单个关键词

输出：data/xiaohongshu_events.json
"""

import re
import sys
import os
import json
import time
import random
import hashlib
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# 切换到 Spider_XHS 目录（否则 JS 文件路径不对）
SPIDER_XHS_PATH = Path(__file__).parent.parent / "Spider_XHS-master"
os.chdir(str(SPIDER_XHS_PATH))
sys.path.insert(0, str(SPIDER_XHS_PATH))

from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.common_util import init

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_FILE = DATA_DIR / "xiaohongshu_events.json"

# 校园招聘会搜索关键词
CAMPUS_KEYWORDS = [
    "济南 校园招聘会",
    "济南大学 双选会",
    "山东大学 校招",
    "山东交通学院 招聘会",
    "济南 高校宣讲会",
    "青岛 校园招聘会",
    "山东 交通运输 校招",
    "济南 春招 双选会",
]

REQUEST_DELAY = 2.0


def search_notes(xhs_api, query: str, count: int, cookies: str) -> list[dict]:
    """搜索小红书笔记"""
    print(f"  🔍 搜索: {query}")
    try:
        success, msg, notes = xhs_api.search_some_note(
            query=query,
            require_num=count,
            cookies_str=cookies,
            sort_type_choice=1,  # 最新
            note_type=0,          # 不限
            note_time=3,          # 半年内
        )
        if success:
            return notes
        else:
            print(f"    ⚠ 搜索失败: {msg}")
            return []
    except Exception as e:
        print(f"    ⚠ 异常: {e}")
        return []


def extract_event_from_note(note: dict, detail_html: str = "") -> dict | None:
    """
    从笔记数据提取招聘会信息
    小红书笔记结构: {id, model_type, note_card: {display_title, desc, user, interact_info, ...}}
    """
    try:
        note_card = note.get("note_card") or note
        title = note_card.get("display_title", "")
        desc = note_card.get("desc", "") or ""

        # 合并标题和描述
        full_text = f"{title} {desc}"

        # 必须有招聘相关关键词
        if not any(kw in full_text for kw in ["招聘", "校招", "双选会", "宣讲会", "春招", "秋招", "实习"]):
            return None

        # 提取时间
        date_str = ""
        time_patterns = [
            r"(\d{4}年\d{1,2}月\d{1,2}日)",
            r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
            r"(\d{1,2}月\d{1,2}日)[\s\-～]*(\d{1,2}:\d{2})?",
        ]
        for pat in time_patterns:
            m = re.search(pat, full_text)
            if m:
                date_str = m.group(1)
                break

        if not date_str:
            # 用发布时间
            ts = note_card.get("time") or note.get("time") or 0
            if ts:
                date_str = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")

        # 提取地点
        location = ""
        loc_patterns = [
            r"(?:地点|地址|位置)[：:]\s*(.+?)(?:[\n，。,]|$)",
            r"(?:济南|青岛|山东)(?:市|大学|学院)?[\u4e00-\u9fa5]*(?:校区|体育馆|报告厅|广场|中心)[\u4e00-\u9fa5]*",
        ]
        for pat in loc_patterns:
            m = re.search(pat, full_text)
            if m:
                location = m.group(0).strip()
                break

        # 提取参会企业
        companies = []
        # 常见企业名模式
        company_matches = re.findall(
            r'[\u4e00-\u9fa5]{2,20}(?:集团|有限公司|公司|银行|证券|保险|航空|港口|物流|水务|高速)',
            full_text
        )
        companies = list(set(company_matches))[:10]

        # 获取笔记链接
        note_id = note.get("id", "")
        xsec = note.get("xsec_token", "")
        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if xsec:
            note_url += f"?xsec_token={xsec}"

        # 互动数据
        interact = note_card.get("interact_info", {})
        likes = interact.get("liked_count", "0")

        # 作者
        user = note_card.get("user", {})
        author = user.get("nickname", user.get("nick_name", ""))

        event = {
            "id": hashlib.md5(note_id.encode()).hexdigest()[:12],
            "title": title[:100] or desc[:100],
            "description": desc[:300],
            "date": date_str,
            "location": location,
            "companies": companies,
            "source": "小红书",
            "source_url": note_url,
            "author": author,
            "likes": str(likes),
            "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        return event

    except Exception as e:
        return None


def main():
    parser = argparse.ArgumentParser(description="小红书校园招聘会爬虫")
    parser.add_argument("--keyword", type=str, help="单个关键词")
    parser.add_argument("--count", type=int, default=15, help="每个关键词搜索结果数")
    args = parser.parse_args()

    # 初始化
    cookies_str, _ = init()
    if not cookies_str or cookies_str == '在此填入你的小红书Cookie':
        print("❌ 请先在 Spider_XHS-master/.env 中填入你的小红书 Cookie")
        print("   获取方法: 浏览器登录 xiaohongshu.com → F12 → 网络 → 任意请求 → 复制 Cookie")
        return

    xhs_api = XHS_Apis()

    keywords = [args.keyword] if args.keyword else CAMPUS_KEYWORDS

    print(f"{'='*60}")
    print(f"🔍 小红书 — 校园招聘会 ({len(keywords)} 个关键词)")
    print(f"{'='*60}\n")

    all_events = []
    for kw in keywords:
        notes = search_notes(xhs_api, kw, args.count, cookies_str)
        for note in notes:
            event = extract_event_from_note(note)
            if event:
                # 尝试获取完整笔记详情
                note_url = f"https://www.xiaohongshu.com/explore/{note.get('id','')}"
                success, msg, detail = xhs_api.get_note_info(note_url, cookies_str)
                if success and detail:
                    try:
                        items = detail.get("data", {}).get("items", [])
                        if items:
                            full_desc = items[0].get("note_card", {}).get("desc", "")
                            if full_desc:
                                event["description"] = full_desc[:500]
                    except Exception:
                        pass
                    time.sleep(random.random() * 1.5)

                all_events.append(event)
                print(f"  ✅ {event['title'][:60]}")
            time.sleep(0.3)

        time.sleep(REQUEST_DELAY + random.random())

    # 去重
    seen = set()
    unique = []
    for e in all_events:
        key = e["id"]
        if key not in seen:
            seen.add(key)
            unique.append(e)

    # 按日期倒序
    unique.sort(key=lambda e: e.get("date", ""), reverse=True)

    # 保存
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"📊 完成: {len(unique)} 条招聘会信息")
    print(f"📁 输出: {OUTPUT_FILE}")

    # 生成简单的 HTML 摘要
    if unique:
        generate_summary_html(unique)


def generate_summary_html(events: list[dict]):
    """生成一个简单的汇总 HTML"""
    html_path = DATA_DIR / "xiaohongshu_events.html"
    items = ""
    for e in events[:20]:
        companies_str = "、".join(e.get("companies", [])[:5]) or "待确认"
        items += f"""
        <div style="border:1px solid #e2e8f0;border-radius:8px;padding:12px;margin:8px 0;">
            <div style="font-weight:700;font-size:15px;">{e.get('title','无标题')}</div>
            <div style="color:#64748b;font-size:12px;margin:4px 0;">
                📅 {e.get('date','')} | 📍 {e.get('location','未知')} | 👤 {e.get('author','')}
            </div>
            <div style="font-size:13px;margin:6px 0;">{e.get('description','')[:200]}</div>
            <div style="font-size:12px;color:#2563eb;">
                🏢 {companies_str}
            </div>
            <a href="{e.get('source_url','')}" target="_blank" style="font-size:11px;color:#64748b;">查看原文 →</a>
        </div>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>校园招聘会汇总</title>
<style>body{{font-family:PingFang SC,Microsoft YaHei,sans-serif;max-width:800px;margin:0 auto;padding:16px;background:#f8fafc}}</style>
</head><body><h2>🔍 小红书 · 济南校园招聘会 ({len(events)}条)</h2>{items}
<p style="color:#94a3b8;font-size:11px;text-align:center;">自动爬取于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</body></html>"""
    html_path.write_text(html, encoding="utf-8")
    print(f"📄 摘要页: {html_path}")


if __name__ == "__main__":
    main()
