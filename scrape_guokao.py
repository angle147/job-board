#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国考/省考职位爬虫 v2 — 中公职位库 + 山东省排名页
================================================
自动获取交通类 + 山东全省国考职位

用法：
    python scrape_guokao.py                  # 全量抓取
    python scrape_guokao.py --province-only  # 仅抓山东全省国考
    python scrape_guokao.py --transport-only # 仅抓交通部委
    python scrape_guokao.py --year 2026

输出：data/exams.js
"""

import re
import time
import random
import argparse
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_FILE = DATA_DIR / "exams.js"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
]

REQUEST_TIMEOUT = 10
REQUEST_DELAY_BASE = 0.6

# 中公内部短码 → 部门名（已验证）
TRANSPORT_DEPT_CODES = {
    # 交通运输核心
    "298": "交通运输部",
    # 铁路系统
    "19678": "国家铁路局",
    "19684": "济南铁路公安局",
    "19681": "北京铁路公安局",
    "19685": "上海铁路公安局",
    "19686": "广州铁路公安局",
    "19687": "成都铁路公安局",
    "19682": "沈阳铁路公安局",
    "19688": "武汉铁路公安局",
    "19689": "西安铁路公安局",
    "19690": "兰州铁路公安局",
    "19691": "乌鲁木齐铁路公安局",
    "19692": "南昌铁路公安局",
    "19683": "哈尔滨铁路公安局",
    "19693": "太原铁路公安局",
    "19694": "南宁铁路公安局",
    "19695": "昆明铁路公安局",
    "19696": "青藏铁路公安局",
    "19677": "上海铁路监督管理局",
    "19679": "武汉铁路监督管理局",
    # 海事系统（修正后的短码）
    "1086": "山东海事局",
    "1300": "上海海事局",
    "1301": "天津海事局",
    "1302": "辽宁海事局",
    "1303": "河北海事局",
    "1304": "浙江海事局",
    "1305": "福建海事局",
    "1306": "广东海事局",
    "1307": "广西海事局",
    "1308": "海南海事局",
    "1309": "长江海事局",
    "1310": "江苏海事局",
    "1311": "深圳海事局",
    # 民航
    "169000": "中国民用航空局",
    "169100": "中国民用航空局华东地区管理局",
    # 邮政
    "170000": "国家邮政局",
    # 水利（修正后的短码）
    "19908": "水利部黄河水利委员会",
    "19909": "水利部淮河水利委员会",
    "19910": "水利部海河水利委员会",
    "19911": "水利部珠江水利委员会",
    "19912": "水利部松辽水利委员会",
    "19913": "水利部太湖流域管理局",
}

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
            if resp.status_code in (403, 429):
                time.sleep(2 ** attempt * 2)
        except Exception:
            time.sleep(1 + attempt)
    return None


def clean_text(text: str) -> str:
    """去掉中公页面重复的专业描述"""
    if not text or len(text) < 10:
        return text
    mid = len(text) // 2
    if text[:mid].strip() == text[mid:].strip():
        return text[:mid].strip()
    return text


# ============================================================
# 抓取单个部门（含分页）
# ============================================================
def scrape_dept(code: str, name: str) -> list[dict]:
    """抓取一个部门的所有职位，含分页"""
    all_positions = []
    page = 1

    while True:
        url = (f"https://zhiwei.offcn.com/gj/2026/bmall{code}.html"
               if page == 1
               else f"https://zhiwei.offcn.com/gj/2026/bmall{code}_{page}.html")

        if page == 1:
            print(f"  📄 {name} ({code})")
        else:
            print(f"    📄 第{page}页")

        html = safe_get(url)
        if not html:
            break

        soup = BeautifulSoup(html, "lxml")
        page_count = 0

        for tr in soup.select("tr"):
            tds = tr.select("td")
            if len(tds) < 8:
                continue
            first = tds[0].get_text(strip=True)
            if not first.isdigit() or len(first) < 3:
                continue
            if first in ("部门代码", "用人司局"):
                continue

            try:
                pos = {
                    "department": name,
                    "office": tds[1].get_text(strip=True) if len(tds) > 1 else "",
                    "position": tds[2].get_text(strip=True) if len(tds) > 2 else "",
                    "positionCode": tds[3].get_text(strip=True) if len(tds) > 3 else "",
                    "recruitmentCount": tds[4].get_text(strip=True) if len(tds) > 4 else "0",
                    "applicants": tds[5].get_text(strip=True) if len(tds) > 5 else "0",
                    "majorReq": clean_text(tds[6].get_text(strip=True)) if len(tds) > 6 else "",
                    "educationReq": tds[7].get_text(strip=True) if len(tds) > 7 else "",
                    "location": tds[8].get_text(strip=True) if len(tds) > 8 else "",
                }
                all_positions.append(pos)
                page_count += 1
            except Exception:
                continue

        print(f"    ✅ {page_count} 个职位")
        if page_count == 0:
            break

        page += 1
        time.sleep(REQUEST_DELAY_BASE + random.random() * 0.5)

    return all_positions


# ============================================================
# 抓取山东全省国考（从山东排名页）
# ============================================================
def scrape_shandong_all() -> list[dict]:
    """从山东排名页抓取全省所有国考职位"""
    url = "https://zhiwei.offcn.com/gj/bmph/2026_zkrs_sd.html"
    print(f"\n🔍 山东省国考职位排行: {url}")

    html = safe_get(url)
    if not html:
        print("  ⚠ 无法访问")
        return []

    soup = BeautifulSoup(html, "lxml")
    dept_codes = []

    # 解析排行表获取各部门代码
    for tr in soup.select("tr"):
        tds = tr.select("td")
        if len(tds) >= 2:
            name = tds[0].get_text(strip=True)
            code = tds[1].get_text(strip=True)
            if code.isdigit() and len(code) >= 3:
                dept_codes.append((code, name))
                print(f"  📋 {name} ({code})")

    print(f"\n  共 {len(dept_codes)} 个部门，开始抓取...")

    all_positions = []
    for code, name in dept_codes:
        positions = scrape_dept(code, name)
        all_positions.extend(positions)
        time.sleep(REQUEST_DELAY_BASE + random.random() * 0.5)

    return all_positions


# ============================================================
# 转换为 exams.js 格式
# ============================================================
def convert_to_exams(positions: list[dict], exam_type: str = "国考") -> list[dict]:
    exams = []
    for i, pos in enumerate(positions, 1):
        exams.append({
            "id": i,
            "examType": exam_type,
            "department": pos.get("department", ""),
            "position": f"{pos.get('office', '')} {pos.get('position', '')}".strip(),
            "positionCode": pos.get("positionCode", ""),
            "recruitmentCount": int(pos.get("recruitmentCount", "0") or "0"),
            "location": pos.get("location", ""),
            "majorReq": pos.get("majorReq", ""),
            "educationReq": pos.get("educationReq", ""),
            "politicalStatus": "不限",
            "workExp": "无限制",
            "registrationStart": "2025-10-15",
            "registrationEnd": "2025-10-24",
            "examDate": "2025-11-30",
            "competitionRatio": pos.get("applicants", "待公布"),
            "pastScoreLine": "待公布",
            "notes": f"来源: 中公职位库 | {pos.get('department','')} | 招{pos.get('recruitmentCount','?')}人",
            "applyLink": "http://bm.scs.gov.cn/kl2026",
        })
    return exams


def output_exams_js(exams: list[dict], filepath: Path):
    # 按部门排序
    exams.sort(key=lambda x: (x["department"], x["position"]))

    for i, e in enumerate(exams, 1):
        e["id"] = i

    lines = [
        "// 国考/省考/事业编职位数据 — 自动爬取",
        f"// 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"// 共 {len(exams)} 条",
        "",
        "const EXAMS = [",
    ]

    for i, e in enumerate(exams):
        lines.append("  {")
        for key in ["id", "examType", "department", "position", "positionCode",
                     "recruitmentCount", "location", "majorReq", "educationReq",
                     "politicalStatus", "workExp", "registrationStart", "registrationEnd",
                     "examDate", "competitionRatio", "pastScoreLine", "notes", "applyLink"]:
            val = e.get(key, "")
            if isinstance(val, str):
                val = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
                lines.append(f'    {key}: "{val}",')
            else:
                lines.append(f'    {key}: {val},')
        lines[-1] = lines[-1].rstrip(",")
        lines.append("  }," if i < len(exams) - 1 else "  }")

    lines.append("];\n")
    filepath.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅ 已写入 {filepath} ({len(exams)} 条)")


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="国考职位爬虫 v2")
    parser.add_argument("--province-only", action="store_true", help="仅山东全省国考")
    parser.add_argument("--transport-only", action="store_true", help="仅交通部委")
    parser.add_argument("--year", default="2026")
    args = parser.parse_args()

    all_positions = []

    if args.transport_only or (not args.province_only):
        print(f"\n{'='*60}")
        print(f"🔍 交通部委国考职位 ({len(TRANSPORT_DEPT_CODES)} 个部门)")
        print(f"{'='*60}")
        for code, name in TRANSPORT_DEPT_CODES.items():
            positions = scrape_dept(code, name)
            all_positions.extend(positions)
            time.sleep(REQUEST_DELAY_BASE + random.random() * 0.3)

    if args.province_only or (not args.transport_only):
        all_positions.extend(scrape_shandong_all())

    if not all_positions:
        print("\n⚠ 未抓取任何数据")
        return

    # 去重（同部门+同职位代码）
    seen = set()
    unique = []
    for p in all_positions:
        key = (p.get("department", ""), p.get("positionCode", ""))
        if key not in seen:
            seen.add(key)
            unique.append(p)

    exams = convert_to_exams(unique)
    output_exams_js(exams, OUTPUT_FILE)

    dept_stats = {}
    for e in exams:
        d = e["department"]
        dept_stats[d] = dept_stats.get(d, 0) + 1
    print(f"\n📊 共 {len(exams)} 条, {len(dept_stats)} 个部门")
    for d, cnt in sorted(dept_stats.items(), key=lambda x: -x[1])[:15]:
        print(f"    {d}: {cnt}")


if __name__ == "__main__":
    main()
