#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
山东省高校就业平台爬虫 — 线下宣讲会/招聘会
=============================================
覆盖济南多所高校的官方就业服务平台。

用法：
    python scrape_university.py                         # 全部济南高校
    python scrape_university.py --school ujn             # 仅济南大学

输出：data/university_events.js
"""

import re
import json
import time
import random
import hashlib
import argparse
from datetime import datetime, timedelta, date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_JS = DATA_DIR / "university_events.js"

BASE_URL = "https://school.gxjy.sdei.edu.cn"

# 济南高校代码映射（已验证的标记 ✅）
JINAN_SCHOOLS = {
    "ujn": "济南大学",        # ✅ 有宣讲会数据
    "qlu": "齐鲁工业大学",     # ✅ 使用同一平台
    # 以下待验证/不同平台
    "sdu": "山东大学",         # ❌ 使用 jobcareer.sdu.edu.cn
    "sdjzu": "山东建筑大学",    # ❌ 使用 sdjzu.bysjy.com.cn
    "jnvc": "济南职业学院",    # ❌ 使用 jnvc.sdbys.com
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
REQUEST_TIMEOUT = 10


def safe_get(url: str) -> str | None:
    for _ in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.encoding = "utf-8"
            if r.status_code == 200:
                return r.text
        except Exception:
            time.sleep(1)
    return None


def scrape_school(school_code: str, school_name: str) -> list[dict]:
    """抓取一个学校的宣讲会/招聘会"""
    url = f"{BASE_URL}/{school_code}"
    print(f"  🏫 {school_name} ({school_code}): {url}")

    html = safe_get(url)
    if not html:
        print(f"    ⚠ 无法访问")
        return []

    soup = BeautifulSoup(html, "lxml")
    events = []

    # 找所有宣讲会链接
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if "TblCareerFairReviewRecord/detail" not in href:
            continue

        text = a.get_text(strip=True)
        if not text or len(text) < 4:
            continue

        # 解析: "进行中就业工作会议宣讲-就业指导中心402室【主校区】2026-06-02"
        # 或: "已举办面试面试-就业指导中心401-1室【主校区】2026-05-30"
        status = "进行中" if text.startswith("进行中") else "已举办"

        # 提取日期 YYYY-MM-DD
        dm = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        date_str = dm.group(1) if dm else ""

        # 提取标题和地点
        # 去掉状态前缀和日期后缀
        content = re.sub(r"^(进行中|已举办)", "", text)
        content = re.sub(r"\d{4}-\d{2}-\d{2}$", "", content).strip()

        # 分离标题和地点
        title = content
        location = ""
        # 常见地点格式: "宣讲-就业指导中心402室【主校区】" 或 "面试-XXX"
        loc_match = re.search(r"(宣讲|面试|招聘)[\-—](.+)$", content)
        if loc_match:
            title = content[:loc_match.start()].strip()
            location = loc_match.group(0)

        detail_url = urljoin(url, href)

        event = {
            "title": title or content,
            "date": date_str,
            "location": location,
            "school": school_name,
            "status": status,
            "source": "高校就业平台",
            "source_url": detail_url,
            "description": "",
            "type": "宣讲会",
        }

        # 获取详情
        detail_html = safe_get(detail_url)
        if detail_html:
            detail_soup = BeautifulSoup(detail_html, "lxml")
            detail_text = detail_soup.get_text(separator="\n", strip=True)

            # 宣讲时间
            tm = re.search(r"宣讲时间[：:]\s*(.+)", detail_text)
            if tm:
                event["date"] = tm.group(1).strip()[:30]

            # 举办地点
            lm = re.search(r"举办地点[：:]\s*(.+)", detail_text)
            if lm:
                event["location"] = lm.group(1).strip()[:60]

            # 单位名称
            cm = re.search(r"单位名称[：:]\s*(.+)", detail_text)
            if cm:
                event["company"] = cm.group(1).strip()

            # 宣讲类别
            cat = re.search(r"宣讲类别[：:]\s*(.+)", detail_text)
            if cat:
                event["type"] = cat.group(1).strip()

            # 描述
            desc_parts = []
            for line in detail_text.split("\n"):
                line = line.strip()
                if line and len(line) > 3 and line not in ("基本信息", "附件", "下载附件"):
                    desc_parts.append(line)
            event["description"] = " | ".join(desc_parts[:5])[:400]

        events.append(event)

    print(f"    ✅ {len(events)} 场宣讲会/招聘会")
    return events


def _parse_date(date_str: str):
    if not date_str:
        return None
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", date_str)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", date_str)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--school", type=str, help="学校代码（如 ujn）")
    args = parser.parse_args()

    schools = {args.school: JINAN_SCHOOLS.get(args.school, args.school)} if args.school else JINAN_SCHOOLS

    print(f"{'='*60}")
    print(f"🔍 山东省高校就业平台 ({len(schools)} 所高校)")
    print(f"{'='*60}\n")

    all_events = []
    for code, name in schools.items():
        events = scrape_school(code, name)
        all_events.extend(events)
        time.sleep(0.5)

    if not all_events:
        print("\n⚠ 未抓取任何数据")
        return

    # 去重 + 两周过滤
    now = datetime.now()
    cutoff = (now - timedelta(days=14)).date()
    seen_urls = set()
    unique = []

    for e in all_events:
        url = e["source_url"]
        if url in seen_urls:
            continue
        d = _parse_date(e.get("date", ""))
        if d and d < cutoff:
            continue
        seen_urls.add(url)
        e["id"] = hashlib.md5(url.encode()).hexdigest()[:12]
        unique.append(e)

    unique.sort(key=lambda e: str(e.get("date", "")), reverse=True)

    # 输出 JS
    lines = [
        "// 高校就业平台 — 线下宣讲会/招聘会",
        f"// {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"// {len(unique)} 场（近两周）",
        "",
        "const UNIVERSITY_EVENTS = [",
    ]
    for e in unique:
        lines.append("  {")
        for key in ["id", "title", "date", "location", "school", "status",
                     "source", "source_url", "description", "type", "company"]:
            val = str(e.get(key, "")).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
            lines.append(f'    {key}: "{val}",')
        lines[-1] = lines[-1].rstrip(",")
        lines.append("  },")
    lines.append("];\n")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JS.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"📊 完成: {len(unique)} 场宣讲会/招聘会（近两周）")
    school_stats = {}
    for e in unique:
        s = e.get("school", "未知")
        school_stats[s] = school_stats.get(s, 0) + 1
    for s, c in school_stats.items():
        print(f"  {s}: {c} 场")
    print(f"📁 {OUTPUT_JS}")


if __name__ == "__main__":
    main()
