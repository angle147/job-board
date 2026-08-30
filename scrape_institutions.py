#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集人社部中国公共招聘网中与交通物流相关的事业单位公告。"""

import argparse
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent
OUTPUT_FILE = BASE_DIR / "data" / "jobs_institutions.js"
LIST_URL = "http://job.mohrss.gov.cn/cjobs/institution/listInstitution"
KEYWORDS = ("交通", "运输", "物流", "仓储", "铁路", "轨道", "港口", "海事", "航运",
            "民航", "航空", "邮政", "快递", "公路", "水利", "水运", "自然资源")


def fetch(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def extract_date(url: str, text: str) -> str:
    match = re.search(r"/(20\d{2})(\d{2})/t(20\d{6})_", url)
    if match:
        token = match.group(3)
        return f"{token[:4]}-{token[4:6]}-{token[6:8]}"
    match = re.search(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})", text)
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}" if match else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age", type=int, default=180)
    args = parser.parse_args()
    html = fetch(LIST_URL)
    soup = BeautifulSoup(html, "lxml")
    cutoff = datetime.now().date() - timedelta(days=max(1, args.max_age))
    jobs = []
    seen = set()
    for anchor in soup.select("a[href]"):
        title = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(LIST_URL, anchor.get("href", ""))
        if len(title) < 8 or not href.startswith("http") or not any(k in title for k in KEYWORDS):
            continue
        if href in seen:
            continue
        published = extract_date(href, title)
        if published:
            try:
                if datetime.strptime(published, "%Y-%m-%d").date() < cutoff:
                    continue
            except ValueError:
                pass
        seen.add(href)
        company = re.split(r"20\d{2}|公开招聘|招聘", title, maxsplit=1)[0].strip(" —-（）()") or "中央事业单位"
        years = sorted(set(re.findall(r"20\d{2}(?=年|届)", title)))
        jobs.append({
            "id": f"institution_{len(jobs)+1}", "companyName": company,
            "companyType": "事业单位", "industry": "交通/公共服务",
            "recruitType": "事业单位招聘", "targetYears": ",".join(f"{year}届" for year in years),
            "location": "全国", "positions": title, "status": "未投递",
            "updateTime": published or datetime.now().strftime("%Y-%m-%d"),
            "deadline": "以公告为准", "applyLink": href, "noticeLink": href,
            "examInfo": "以公告为准", "companyScale": "",
            "notes": "来源: 中国公共招聘网事业单位公开招聘 | 交通物流关键词筛选",
        })
    time.sleep(2.0)
    header = ("// 中国公共招聘网事业单位公开招聘 — 自动采集\n"
              f"// 更新时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
              f"// 共 {len(jobs)} 条\n\nconst JOBS_INSTITUTIONS = ")
    OUTPUT_FILE.write_text(header + json.dumps(jobs, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    print(f"中国公共招聘网事业单位完成: {len(jobs)} 条")


if __name__ == "__main__":
    main()
