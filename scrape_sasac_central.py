#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集国务院国资委人才招聘栏目的央企招聘公告。"""

from __future__ import annotations

import json
import hashlib
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT = DATA_DIR / "jobs_sasac_central.js"
LIST_URL = "http://www.sasac.gov.cn/n2588035/n2588325/n2588350/index.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"


def fetch() -> str:
    request = urllib.request.Request(LIST_URL, headers={"User-Agent": UA})
    return urllib.request.urlopen(request, timeout=30).read().decode("utf-8", "replace")


def parse_items(html: str) -> list[dict]:
    pattern = re.compile(
        r'<li[^>]*>\s*<a\s+href="(?P<link>[^"]+)"[^>]*title="(?P<title>[^"]+)"[^>]*>'
        r'[\s\S]*?</a>\s*<span>\[(?P<date>20\d{2}-\d{2}-\d{2})\]</span>\s*</li>',
        re.IGNORECASE,
    )
    records = []
    for match in pattern.finditer(html):
        title = match.group("title").strip()
        if not any(word in title for word in ("招聘", "招募", "毕业生", "人才")):
            continue
        records.append({
            "title": title,
            "date": match.group("date"),
            "link": urljoin(LIST_URL, match.group("link")),
        })
    if not records:
        raise ValueError("页面可达但未识别到带日期的招聘公告列表")
    return records


def company_name(title: str) -> str:
    named = re.search(
        r"([\u4e00-\u9fa5〇·（）()]{2,30}?(?:集团(?:有限公司)?|公司|研究所|研究院|中心))",
        title,
    )
    if named:
        return named.group(1)
    prefix = re.split(r"(?:20\d{2}\s*届?|校园招聘|秋季招聘|春季招聘|社会招聘|公开招聘|招聘公告|招聘启事|招录)", title, maxsplit=1)[0]
    prefix = prefix.strip(" ：:！!，,·-")
    return prefix if len(prefix) >= 2 else title


def convert(item: dict) -> dict:
    title = item["title"]
    years = sorted(set(re.findall(r"(20\d{2})\s*届?", title)))
    recruit_type = "社招" if any(word in title for word in ("社会招聘", "社招")) else "校招"
    industry = "交通" if any(word in title for word in ("交通", "铁路", "海运", "物流", "港口", "机场", "航空公司")) else "综合"
    record_id = re.search(r"/c(\d+)/content\.html", item["link"])
    fallback_id = hashlib.sha1(item["link"].encode("utf-8")).hexdigest()[:16]
    return {
        "id": f"sasac-central-{record_id.group(1) if record_id else fallback_id}",
        "companyName": company_name(title),
        "companyType": "央国企",
        "industry": industry,
        "recruitType": recruit_type,
        "targetYears": ",".join(f"{year}届" for year in years),
        "location": "全国",
        "positions": title,
        "majorReq": "",
        "educationReq": "",
        "status": "未投递",
        "updateTime": item["date"],
        "deadline": "",
        "applyLink": item["link"],
        "noticeLink": item["link"],
        "examInfo": "",
        "notes": "国务院国资委人才招聘栏目官方公告；具体岗位、专业和截止时间以公告及报名页为准",
    }


def main() -> None:
    records = parse_items(fetch())
    jobs = [convert(item) for item in records]
    header = (
        "// 国务院国资委 — 人才招聘栏目\n"
        f"// 更新时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"// 共 {len(jobs)} 条\n\nconst JOBS_SASAC_CENTRAL = "
    )
    OUTPUT.write_text(header + json.dumps(jobs, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    target_count = sum("2027" in job["targetYears"] for job in jobs)
    print(f"[ok] 国务院国资委招聘公告: {len(jobs)} 条，其中2027届 {target_count} 条 -> {OUTPUT.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
