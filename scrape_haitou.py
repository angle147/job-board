#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
海投网/牛企直聘 校招爬虫 — 交通/物流/仓储行业
==============================================
用法：
    python scrape_haitou.py                    # 抓全部交通类
    python scrape_haitou.py --max-pages 5      # 限制翻页

输出：data/jobs_haitou.js
"""

import re
import json
import time
import random
import hashlib
import argparse
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_FILE = DATA_DIR / "jobs_haitou.js"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
]
REQUEST_TIMEOUT = 10
REQUEST_DELAY = 0.5

# 海投网行业分类页
HAITOU_URL = "https://campus.niuqizp.com/schedulenew-transportationlogisticswarehousing-all-{page}/"

_session = None


def get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
    return _session


def safe_get(url: str) -> str | None:
    session = get_session()
    for attempt in range(3):
        try:
            session.headers["User-Agent"] = random.choice(USER_AGENTS)
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.encoding = resp.apparent_encoding or "utf-8"
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 404:
                return None
        except Exception:
            time.sleep(1 + attempt)
    return None


def polite_wait():
    time.sleep(REQUEST_DELAY + random.random() * 0.3)


# ============================================================
# 解析
# ============================================================
def guess_industry(text: str) -> str:
    patterns = [
        (["港口", "港务", "港航", "海运", "航运", "船舶", "引航", "水运"], "港口/航运"),
        (["高速", "路桥", "公路", "交投", "交通"], "公路/高速"),
        (["铁路", "铁道", "轨道交通", "地铁", "机车", "中车", "轨交"], "铁路/轨交"),
        (["机场", "航空", "民航", "空管", "航发"], "航空"),
        (["邮政", "物流", "快递", "仓储", "供应链"], "邮政/物流"),
        (["水务", "水利", "水处理", "给排水"], "水务/水利"),
        (["公交", "客运", "交运"], "公交/客运"),
        (["汽车", "客车", "车辆"], "汽车/车辆"),
    ]
    for keywords, industry in patterns:
        for kw in keywords:
            if kw in text:
                return industry
    return "综合"


def scrape_haitou(max_pages: int = 10) -> list[dict]:
    print(f"🔍 海投网 — 交通/物流/仓储行业")

    jobs = []
    for page in range(1, max_pages + 1):
        url = HAITOU_URL.format(page=page)
        print(f"  📄 第{page}页: {url}")

        html = safe_get(url)
        if not html:
            print(f"    ⚠ 404或无数据，停止翻页")
            break

        soup = BeautifulSoup(html, "lxml")
        page_count = 0

        # 每个岗位块：h3标题 + 信息行
        # 结构: <h3><a>公司名/类型</a></h3> ... <span>日期~截止</span> ... <span>城市</span>
        for h3 in soup.select("h3"):
            a_tag = h3.find("a")
            if not a_tag:
                continue
            title = a_tag.get_text(strip=True)
            href = a_tag.get("href", "")

            if not title or len(title) < 4:
                continue

            # 公司名：从标题中提取
            # 格式: "中国航发南方 日常实习" 或 "公司名 26届春招"
            company = title
            position = ""
            for suffix in ["日常实习", "春招", "秋招", "补录", "提前批", "暑期", "招聘"]:
                idx = title.find(suffix)
                if idx > 0:
                    company = title[:idx].strip()
                    position = title[idx:].strip()
                    break

            # 从 h3 父容器中找其他信息
            parent = h3.find_parent("div") or h3.parent
            if not parent:
                parent = soup

            full_url = "https://campus.niuqizp.com" + href if href.startswith("/") else href

            # 找日期
            date_str = ""
            deadline = "招满为止"
            date_spans = parent.select("span")
            for span in date_spans:
                text = span.get_text(strip=True)
                # 匹配 "2026-05-29 ~ 2026-06-12" 或 "2026-05-29"
                dm = re.search(r"(\d{4}-\d{2}-\d{2})\s*[~～]\s*(\d{4}-\d{2}-\d{2})", text)
                if dm:
                    date_str = dm.group(1)
                    deadline = dm.group(2)
                    break
                dm2 = re.search(r"(\d{4}-\d{2}-\d{2})", text)
                if dm2:
                    date_str = dm2.group(1)
                    break

            if not date_str:
                date_str = datetime.now().strftime("%Y-%m-%d")

            # 找城市
            location = ""
            for span in date_spans:
                text = span.get_text(strip=True)
                # 排除日期格式的文本
                if re.search(r"\d{4}-\d{2}-\d{2}", text):
                    continue
                if any(c in text for c in ["北京", "上海", "广州", "深圳", "山东", "济南", "青岛",
                                             "天津", "南京", "武汉", "成都", "重庆", "杭州",
                                             "西安", "郑州", "全国", "其他"]):
                    location = text
                    break

            # 找描述（可能是下一个 p 或 div 的文本）
            desc = ""
            next_elem = h3.find_next_sibling()
            if next_elem:
                desc = next_elem.get_text(strip=True)[:150]

            recruit_type = "春招"
            if "实习" in title:
                recruit_type = "实习"
            elif "秋招" in title:
                recruit_type = "秋招"
            elif "提前批" in title:
                recruit_type = "秋招提前批"

            job = {
                "id": 0,
                "companyName": company,
                "companyType": "企业",
                "industry": guess_industry(company + " " + desc),
                "recruitType": recruit_type,
                "targetYears": "2026届",
                "location": location or "全国",
                "positions": position or title,
                "status": "未投递",
                "updateTime": date_str,
                "deadline": deadline,
                "applyLink": full_url,
                "noticeLink": full_url,
                "examInfo": "",
                "companyScale": "",
                "notes": f"来源: 海投网 [{date_str}] | {desc[:80]}",
            }
            jobs.append(job)
            page_count += 1

        print(f"    ✅ {page_count} 条")
        if page_count == 0:
            break
        polite_wait()

    return jobs


# ============================================================
# 输出
# ============================================================
def output_js(jobs: list[dict], filepath: Path):
    # 去重
    seen = set()
    unique = []
    for j in jobs:
        key = hashlib.md5(f"{j['companyName']}|{j['positions'][:30]}".encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            unique.append(j)

    unique.sort(key=lambda j: j.get("updateTime", ""), reverse=True)
    for i, j in enumerate(unique, 1):
        j["id"] = i

    lines = [
        "// 海投网 — 交通/物流/仓储行业校招",
        f"// {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"// {len(unique)} 条",
        "",
        "const JOBS_HAITOU = [",
    ]
    for i, j in enumerate(unique):
        lines.append("  {")
        for key in ["id", "companyName", "companyType", "industry", "recruitType",
                     "targetYears", "location", "positions", "status",
                     "updateTime", "deadline", "applyLink", "noticeLink",
                     "examInfo", "companyScale", "notes"]:
            val = str(j.get(key, "")).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'    {key}: "{val}",')
        lines[-1] = lines[-1].rstrip(",")
        lines.append("  }," if i < len(unique) - 1 else "  }")
    lines.append("];\n")
    filepath.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅ {filepath} ({len(unique)} 条)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=10)
    args = parser.parse_args()

    jobs = scrape_haitou(args.max_pages)
    if jobs:
        output_js(jobs, OUTPUT_FILE)


if __name__ == "__main__":
    main()
