#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集国家大学生就业服务平台的国有企业招聘专题。"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT = DATA_DIR / "jobs_ncss_soe.js"
TARGET_YEARS = (2027, 2026)
URL_TEMPLATE = "https://www.ncss.cn/ncss/zt/gqzp{year}.shtml"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"


def fetch(year: int) -> str | None:
    """专题未发布时返回 None；其他网络或结构异常交给主流程处理。"""
    request = urllib.request.Request(URL_TEMPLATE.format(year=year), headers={"User-Agent": UA})
    try:
        raw = urllib.request.urlopen(request, timeout=30).read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    # 页面声明 UTF-8，但实际响应长期使用 GBK/GB18030。
    return raw.decode("gb18030", "replace")


def parse_embedded_list(html: str) -> list[dict]:
    marker = re.search(r"var\s+comsList\s*=", html)
    if not marker:
        raise ValueError("未找到 comsList 数据标记")
    start = html.find("[", marker.end())
    if start < 0:
        raise ValueError("comsList 缺少数组内容")
    records, _ = json.JSONDecoder().raw_decode(html[start:])
    if not isinstance(records, list) or not records:
        raise ValueError("comsList 为空或类型异常")
    required = {"company", "title", "link"}
    if not all(isinstance(item, dict) and required.issubset(item) for item in records):
        raise ValueError("comsList 记录字段结构异常")
    return records


def iso_date(value: object) -> str:
    match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", str(value or ""))
    if not match:
        return ""
    try:
        return datetime(*map(int, match.groups())).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def target_years(title: str, page_year: int) -> str:
    years = sorted(set(re.findall(r"(20\d{2})届", title)))
    return ",".join(years) if years else f"{page_year}届"


def convert(item: dict, page_year: int, ordinal: int) -> dict:
    title = str(item.get("title") or "").strip()
    source_url = URL_TEMPLATE.format(year=page_year)
    recruit_type = "实习" if "实习" in title else "校招"
    return {
        "id": f"ncss-{page_year}-{item.get('xh') or ordinal}",
        "companyName": str(item.get("company") or "").strip(),
        "companyType": "央国企",
        "industry": "综合",
        "recruitType": recruit_type,
        "targetYears": target_years(title, page_year),
        "location": "全国",
        "positions": title,
        "majorReq": "",
        "educationReq": "高校毕业生",
        "recruitmentCount": str(item.get("yjtggws") or ""),
        "status": "未投递",
        "updateTime": iso_date(item.get("startDate")),
        "deadline": iso_date(item.get("endDate")),
        "applyLink": str(item.get("link") or "").strip(),
        "noticeLink": source_url,
        "examInfo": "",
        "notes": "教育部国家大学生就业服务平台国有企业招聘专题收录；专业和具体岗位以报名页为准",
    }


def main() -> None:
    jobs: list[dict] = []
    available_pages = 0
    for year in TARGET_YEARS:
        html = fetch(year)
        if html is None:
            print(f"[info] {year}届专题尚未发布，继续监控")
            continue
        records = parse_embedded_list(html)
        available_pages += 1
        jobs.extend(convert(item, year, index) for index, item in enumerate(records, 1))
        print(f"[ok] {year}届专题结构有效: {len(records)} 条")

    if not available_pages:
        print("[error] 所有目标专题均不可用，保留上次成功数据")
        raise SystemExit(1)

    unique = {job["id"]: job for job in jobs}
    records = list(unique.values())
    header = (
        "// 国家大学生就业服务平台 — 国有企业招聘专题\n"
        f"// 更新时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"// 共 {len(records)} 条\n\nconst JOBS_NCSS_SOE = "
    )
    OUTPUT.write_text(header + json.dumps(records, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    print(f"[ok] 国企专题采集完成: {len(records)} 条 -> {OUTPUT.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
