#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集中国铁路人才招聘网公开招聘公告。"""

import argparse
import base64
import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BASE_DIR = Path(__file__).parent
OUTPUT_FILE = BASE_DIR / "data" / "jobs_railway.js"
API_URL = "https://rczp.china-railway.com.cn/job/chnldocinfo/pageList"
LIST_URL = "https://rczp.china-railway.com.cn/page/recruitment/rec_info.html"
KEY = b"g0UNalNo4nSmGZwS"
REQUEST_DELAY = 2.1


def encrypt(payload: list) -> str:
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(KEY), modes.ECB()).encryptor()
    return base64.b64encode(cipher.update(padded) + cipher.finalize()).decode().replace("/", "#")


def fetch_page(session: requests.Session, page: int, size: int) -> dict:
    if page == 1:
        session.get(LIST_URL, timeout=15)
        time.sleep(REQUEST_DELAY)
    payload = json.dumps({"data": encrypt([1000, 521])}, separators=(",", ":"))
    response = session.post(
        f"{API_URL}?current={page}&size={size}",
        data=payload,
        headers={"Content-Type": "application/json", "Referer": LIST_URL,
                 "Origin": "https://rczp.china-railway.com.cn",
                 "X-Requested-With": "XMLHttpRequest"},
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("success"):
        raise RuntimeError(f"铁路公开接口返回失败: {result.get('msg', '未知原因')}")
    return result["obj"]


def to_job(record: dict, index: int) -> dict:
    published = str(record.get("docpubtime") or "")[:10]
    deadline = str(record.get("invalidtime") or "")[:10] or "招满为止"
    title = str(record.get("doctitle") or "").strip()
    years = sorted(set(re.findall(r"20\d{2}(?=年|届)", title)))
    company = str(record.get("organ") or "中国国家铁路集团所属单位").strip()
    headcount = str(record.get("gwsums") or "").strip()
    notes = f"来源: 中国铁路人才招聘网 | 岗位类别 {record.get('gwcounts') or '未注明'}"
    if headcount:
        notes += f" | 计划招聘 {headcount} 人"
    return {
        "id": f"railway_{record.get('docid', index)}", "companyName": company,
        "companyType": "央国企", "industry": "铁路/轨道交通", "recruitType": "校招",
        "targetYears": ",".join(f"{year}届" for year in years), "location": "全国", "positions": title,
        "status": "未投递", "updateTime": published, "deadline": deadline,
        "applyLink": LIST_URL, "noticeLink": LIST_URL, "examInfo": "以公告为准",
        "companyScale": "", "notes": notes,
    }


def write_output(jobs: list[dict]) -> None:
    header = ("// 中国铁路人才招聘网 — 自动采集\n"
              f"// 更新时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
              f"// 共 {len(jobs)} 条\n\nconst JOBS_RAILWAY = ")
    OUTPUT_FILE.write_text(header + json.dumps(jobs, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--page-size", type=int, default=20)
    args = parser.parse_args()
    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    records = []
    for page in range(1, max(1, args.pages) + 1):
        obj = fetch_page(session, page, min(max(args.page_size, 1), 50))
        page_records = obj.get("records", [])
        print(f"铁路人才招聘网 第 {page} 页: {len(page_records)} 条")
        records.extend(page_records)
        if page < args.pages:
            time.sleep(REQUEST_DELAY)
    seen = set()
    unique = []
    for record in records:
        key = str(record.get("docid") or record.get("doctitle"))
        if key not in seen:
            seen.add(key)
            unique.append(to_job(record, len(unique) + 1))
    write_output(unique)
    print(f"中国铁路人才招聘网完成: {len(unique)} 条")


if __name__ == "__main__":
    main()
