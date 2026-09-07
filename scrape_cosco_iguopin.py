#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集中远海运、招商局集团国聘官方企业站的校园招聘岗位。"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
OUTPUT = BASE_DIR / "data" / "jobs_cosco.js"
API_HOST = "https://gp-api.iguopin.com"
PORTAL = "https://coscoshipping.iguopin.com"
CMHK_PORTAL = "https://cmhk.iguopin.com"
CONFIG_URL = f"{API_HOST}/api/activity/exclusive/v1/info?domain=coscoshipping"
CMHK_CONFIG_URL = f"{API_HOST}/api/activity/exclusive/v1/info?domain=cmhk"
JOBS_URL = f"{API_HOST}/api/jobs/v1/project-job"
COMPANY_JOBS_URL = f"{API_HOST}/api/jobs/v1/list"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"


def request_json(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA,
        "Origin": PORTAL,
        "Referer": f"{PORTAL}/job",
        "Device": "pc",
        "Version": "5.0.0",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("code") != 200:
        raise ValueError(f"公开接口返回异常: code={result.get('code')} msg={result.get('msg')}")
    return result


def parse_campus_config(result: dict) -> tuple[str, list[str], str]:
    data = result.get("data") or {}
    content = json.loads(data.get("content") or "{}")
    nav = (content.get("params") or {}).get("nav") or []
    campus = next((item for item in nav if item.get("route") == "/job" and item.get("type") == "job"), None)
    if not campus:
        raise ValueError("企业配置可达但未找到校园招聘栏目")
    props = campus.get("props") or {}
    project_id = str(props.get("projectId") or "").strip()
    if not project_id:
        raise ValueError("校园招聘栏目缺少 projectId")
    nature = [part for part in str(props.get("nature") or "").split(",") if part]
    company_id = str(data.get("company_id") or "").strip()
    return project_id, nature, company_id


def campus_config() -> tuple[str, list[str], str]:
    return parse_campus_config(request_json(CONFIG_URL))


def parse_company_campus_config(result: dict) -> tuple[list[str], str]:
    data = result.get("data") or {}
    content = json.loads(data.get("content") or "{}")
    nav = (content.get("params") or {}).get("nav") or []
    campus = next((item for item in nav if item.get("type") == "job" and (item.get("props") or {}).get("type") == "campus"), None)
    if not campus:
        raise ValueError("企业配置可达但未找到校园招聘栏目")
    props = campus.get("props") or {}
    nature = [part for part in str(props.get("nature") or "").split(",") if part]
    company_id = str(data.get("company_id") or "").strip()
    if not company_id:
        raise ValueError("校园招聘栏目缺少 company_id")
    return nature, company_id


def target_years(item: dict) -> str:
    text = " | ".join(str(item.get(key) or "") for key in ("job_name", "contents", "notes"))
    years = sorted(set(re.findall(r"(20\d{2})\s*(?:届|年应届)", text)))
    return ",".join(f"{year}届" for year in years)


def convert(item: dict, portal: str = PORTAL, source_key: str = "cosco") -> dict:
    districts = item.get("district_list") or []
    location = "、".join(dict.fromkeys(str(row.get("area_cn") or "").strip() for row in districts if row.get("area_cn")))
    majors = item.get("major_cn") or []
    company = item.get("company_info") or {}
    job_id = str(item.get("job_id") or "").strip()
    return {
        "id": f"{source_key}-{job_id}",
        "companyName": str(item.get("company_name") or company.get("show_name") or "中远海运集团").strip(),
        "companyType": "央国企",
        "industry": str(company.get("industry_cn") or "交通运输").strip(),
        "recruitType": str(item.get("recruitment_type_cn") or "校园招聘").strip(),
        "targetYears": target_years(item),
        "location": location,
        "positions": str(item.get("job_name") or "").strip(),
        "majorReq": "、".join(str(value).strip() for value in majors if str(value).strip()),
        "educationReq": str(item.get("education_cn") or "").strip(),
        "recruitmentCount": str(item.get("amount") or ""),
        "status": "未投递",
        "updateTime": str(item.get("update_time") or item.get("start_time") or "")[:10],
        "deadline": str(item.get("end_time") or "")[:10],
        "applyLink": f"{portal}/job/detail?id={job_id}",
        "noticeLink": f"{portal}/job",
        "examInfo": "",
        "companyScale": str(company.get("scale_cn") or "").strip(),
        "notes": str(item.get("contents") or "").strip(),
        "actualEmployer": str(item.get("company_name") or company.get("show_name") or "").strip(),
        "contractEmployer": "待核验",
        "employmentType": "直接招聘",
        "ownershipRelation": "国聘官方企业人才招聘平台；企业页面标注国企",
        "ownershipEvidenceUrl": portal,
    }


def fetch_pages(url: str, base_payload: dict, args: argparse.Namespace, portal: str, source_key: str) -> tuple[list[dict], int]:
    jobs: list[dict] = []
    total = 0
    for page in range(1, args.max_pages + 1):
        if page > 1:
            time.sleep(2.1)
        payload = {**base_payload, "page": page, "page_size": args.page_size, "source": "s_job_list", "sort_scene": 1}
        data = request_json(url, payload).get("data") or {}
        rows = data.get("list") or []
        if page == 1 and not isinstance(rows, list):
            raise ValueError("岗位接口结构异常：list 不是数组")
        total = int(data.get("total") or 0)
        jobs.extend(convert(row, portal=portal, source_key=source_key) for row in rows if row.get("job_id") and row.get("job_name"))
        if not rows or len(jobs) >= total:
            break
    if total > 0 and not jobs:
        raise ValueError("岗位接口有总数但未取得真实岗位")
    return jobs, total


def main() -> None:
    parser = argparse.ArgumentParser(description="采集中远海运集团校园招聘岗位")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=5)
    args = parser.parse_args()

    project_id, nature, company_id = campus_config()
    time.sleep(2.1)
    cosco_jobs, cosco_total = fetch_pages(JOBS_URL, {
        "project_id": [project_id], "nature": nature, "company_id_with_sub": company_id,
    }, args, PORTAL, "cosco")

    time.sleep(2.1)
    cmhk_config = request_json(CMHK_CONFIG_URL)
    cmhk_nature, cmhk_company_id = parse_company_campus_config(cmhk_config)
    time.sleep(2.1)
    cmhk_jobs, cmhk_total = fetch_pages(COMPANY_JOBS_URL, {
        "nature": cmhk_nature, "company_id_with_sub": cmhk_company_id,
    }, args, CMHK_PORTAL, "cmhk")

    jobs = cosco_jobs + cmhk_jobs
    if not jobs:
        raise ValueError("两个企业站均未取得真实岗位，保留上次成功数据")
    unique = list({job["id"]: job for job in jobs}.values())
    header = (
        "// 中远海运集团、招商局集团官方人才招聘平台 — 校园招聘岗位\n"
        f"// 更新时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"// 共 {len(unique)} 条\n\nconst JOBS_COSCO = "
    )
    OUTPUT.write_text(header + json.dumps(unique, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    print(f"[ok] 交通物流央企校园招聘岗位: {len(unique)} 条（中远海运 {cosco_total}，招商局 {cmhk_total}） -> {OUTPUT.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
