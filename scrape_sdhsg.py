#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""山东高速多渠道招聘探测器。

渠道一：集团官网公开招聘公告及详情；渠道二：集团招聘平台公开在招岗位；
渠道三：本项目独立采集的山东省国资委招聘公告。结构异常时拒绝覆盖旧数据。
"""
from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_FILE = DATA_DIR / "jobs_sdhsg.js"
SASAC_FILE = DATA_DIR / "jobs.js"
API_ROOT = "https://www.sdhsg.com/zpapi"
ANNOUNCEMENT_API = f"{API_ROOT}/hr/announcement/weblist"
DETAIL_API = f"{API_ROOT}/hr/announcement/queryIntro"
JOB_API = f"{API_ROOT}/hr/job/weblist"
ATTACHMENT_API = f"{API_ROOT}/hr/upload/getAnnouncementUploadFile"
NOTICE_PAGE = "https://www.sdhsg.com/article/category/rlzyZcyz"
RECRUIT_SITE = "https://zhaopin.sdhsg.com/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
RTYPE = {1: "社招", 2: "社招", 3: "校招", 4: "内部招聘", 5: "实习生", 6: "社招"}


def fetch_json(url: str, params: dict | None = None) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": RECRUIT_SITE, "Accept": "application/json",
    })
    raw = urllib.request.urlopen(req, timeout=20).read()
    return json.loads(raw.decode("utf-8", "replace"))


def clean_html(value: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", value or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape(text)).strip()


def extract_date(text: str, *, deadline: bool = False) -> str:
    patterns = (
        r"报名截止(?:时间|日期)?[：:\s]*?(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?",
        r"(?:2[.、．]\s*)?截止时间\s*(?:\n|：).*?至\s*(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?",
        r"报名[\s\S]{0,120}?至\s*(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?",
    ) if deadline else (r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?",)
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return ""


def extract_target_years(text: str) -> str:
    years = sorted(set(re.findall(r"(20\d{2})(?=届|年(?:度|应届|毕业))", text)))
    if not years and any(term in text for term in ("校园招聘", "应届毕业生")):
        years = sorted(set(re.findall(r"20\d{2}", text)))
    return ",".join(f"{year}届" for year in years)


def company_from(title: str) -> str:
    match = re.search(r"([\u4e00-\u9fa5]{2,35}?(?:集团有限公司|有限公司|公司))", title)
    return match.group(1) if match else "山东高速集团有限公司"


def announcement_detail_url(announcement_id: object) -> str:
    return f"{RECRUIT_SITE}#/announcementInfo?id={announcement_id}"


def load_js_array(path: Path, variable: str) -> list[dict]:
    if not path.exists():
        return []
    match = re.search(rf"const\s+{re.escape(variable)}\s*=\s*(\[.*\]);", path.read_text(encoding="utf-8"), re.S)
    if not match:
        return []
    payload = re.sub(r'(?m)^(\s*)([A-Za-z_]\w*)\s*:', r'\1"\2":', match.group(1))
    return json.loads(payload)


def normalized_tokens(text: str) -> set[str]:
    text = re.sub(r"\s+|[《》‘’“”()（）]", "", str(text or ""))
    return set(re.findall(r"[\u4e00-\u9fa5]{2,}|20\d{2}", text))


def corroborating_sasac(item: dict, sasac_records: list[dict]) -> list[str]:
    """按公司、年份和标题词匹配省国资委同批公告，宁缺毋滥。"""
    title = str(item.get("title") or "")
    company = company_from(title)
    years = set(re.findall(r"20\d{2}", title))
    title_tokens = normalized_tokens(title)
    links: list[str] = []
    for record in sasac_records:
        other = " | ".join(str(record.get(key) or "") for key in ("companyName", "positions", "notes"))
        if company not in other and not ("山东高速" in company and "山东高速" in other):
            continue
        if years and not years.intersection(re.findall(r"20\d{2}", other)):
            continue
        if len(title_tokens.intersection(normalized_tokens(other))) < 2:
            continue
        link = record.get("noticeLink") or record.get("applyLink")
        if link:
            links.append(str(link))
    return list(dict.fromkeys(links))


def fetch_active_jobs(page_size: int = 100) -> list[dict]:
    """招聘平台空列表是有效状态；字段结构缺失才算失败。"""
    jobs: list[dict] = []
    for recruit_type in range(1, 7):
        payload = fetch_json(JOB_API, {
            "recruitType": recruit_type, "startTime": "", "endTime": "", "areaId": "",
            "orgId": "", "jobType": "", "specialty": "", "page": 1, "limit": page_size,
            "status": 1, "sidx": "", "order": "desc",
        })
        page = payload.get("page")
        if payload.get("code") != 0 or not isinstance(page, dict) or not isinstance(page.get("list"), list):
            raise RuntimeError(f"招聘岗位接口结构异常: recruitType={recruit_type}")
        jobs.extend(page["list"])
        time.sleep(0.2)
    return jobs


def job_matches_announcement(job: dict, announcement: dict) -> bool:
    org_id = announcement.get("orgId")
    if org_id and str(job.get("orgId") or "") == str(org_id):
        return True
    job_text = " | ".join(str(job.get(key) or "") for key in ("orgName", "companyName", "name", "jobName"))
    return company_from(str(announcement.get("title") or "")) in job_text


def convert(
    announcement: dict,
    detail: dict,
    active_jobs: list[dict],
    sasac_records: list[dict],
    attachments: list[dict] | None = None,
) -> dict:
    title = str(detail.get("title") or announcement.get("title") or "").strip()
    content = clean_html(str(detail.get("content") or ""))
    matched_jobs = [job for job in active_jobs if job_matches_announcement(job, announcement)]
    sasac_links = corroborating_sasac({**announcement, "title": title}, sasac_records)
    attachment_links = [str(item.get("url")) for item in (attachments or []) if item.get("url")]
    urls = re.findall(r"https?://[^\s，。；<>]+", content)
    apply_link = next((url.rstrip("/）)") for url in urls if "zhaopin.sdhsg.com" in url), RECRUIT_SITE)
    channels = [
        {"name": "山东高速集团官网公告", "url": NOTICE_PAGE, "matched": True},
        {"name": "山东高速招聘平台岗位", "url": apply_link, "matched": bool(matched_jobs)},
    ]
    if attachment_links:
        channels.append({"name": "山东高速招聘平台岗位计划表", "url": attachment_links[0], "matched": True})
    if sasac_links:
        channels.append({"name": "山东省国资委招聘公告", "url": sasac_links[0], "matched": True})
    matched_count = sum(1 for channel in channels if channel["matched"])
    verification = "cross_verified" if matched_count >= 2 else "single_source"
    notes = f"来源核验：{matched_count}/{len(channels)} 个渠道匹配"
    if verification == "single_source":
        notes += "；招聘平台暂无同单位在招岗位，保留为单源待复核"
    return {
        "id": str(announcement.get("id")), "companyName": company_from(title),
        "companyType": "省属国企", "industry": "交通",
        "recruitType": RTYPE.get(announcement.get("recruitType"), "招聘"),
        "targetYears": extract_target_years(title) or extract_target_years(content), "location": "",
        "positions": title, "status": "未投递",
        "updateTime": str(detail.get("releaseTime") or announcement.get("releaseTime") or "")[:10],
        "deadline": extract_date(content, deadline=True), "applyLink": apply_link,
        "noticeLink": announcement_detail_url(announcement.get("id")), "examInfo": "",
        "ownershipRelation": "山东高速集团所属企业", "ownershipEvidenceUrl": NOTICE_PAGE,
        "verificationStatus": verification, "verificationChannels": channels,
        "corroborationLinks": list(dict.fromkeys([NOTICE_PAGE, *attachment_links, *sasac_links])),
        "attachmentLink": attachment_links[0] if attachment_links else "",
        "sourceChannelCount": matched_count, "notes": notes,
    }


def collect() -> list[dict]:
    active_jobs = fetch_active_jobs()
    sasac_records = load_js_array(SASAC_FILE, "JOBS")
    announcements: list[dict] = []
    for recruit_type in RTYPE:
        payload = fetch_json(ANNOUNCEMENT_API, {
            "recruitType": recruit_type, "page": 1, "limit": 100,
            "sidx": "release_time", "order": "desc",
        })
        page = payload.get("page")
        if payload.get("code") != 0 or not isinstance(page, dict) or not isinstance(page.get("list"), list):
            raise RuntimeError(f"招聘公告接口结构异常: recruitType={recruit_type}")
        announcements.extend(page["list"])
        time.sleep(0.2)
    records: list[dict] = []
    for item in announcements:
        payload = fetch_json(DETAIL_API, {"id": item.get("id")})
        detail = payload.get("announcement")
        if payload.get("code") != 0 or not isinstance(detail, dict) or not detail.get("title"):
            raise RuntimeError(f"公告详情接口结构异常: id={item.get('id')}")
        attachment_payload = fetch_json(ATTACHMENT_API, {"announcement_id": item.get("id")})
        attachments = attachment_payload.get("uploadList")
        if attachment_payload.get("code") != 0 or not isinstance(attachments, list):
            raise RuntimeError(f"公告附件接口结构异常: id={item.get('id')}")
        records.append(convert(item, detail, active_jobs, sasac_records, attachments))
        time.sleep(0.2)
    return records


def write_output(records: list[dict]) -> None:
    verified = sum(record["verificationStatus"] == "cross_verified" for record in records)
    header = (
        "// 山东高速多渠道招聘探测 — 官网公告 / 招聘平台 / 省国资委\n"
        f"// {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"// {len(records)} 条；多源印证 {verified} 条\n\nconst JOBS_SDHSG = "
    )
    OUTPUT_FILE.write_text(header + json.dumps(records, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-only", action="store_true", help="只探测并打印统计，不写输出")
    args = parser.parse_args()
    records = collect()
    verified = sum(record["verificationStatus"] == "cross_verified" for record in records)
    if not args.probe_only:
        write_output(records)
    print(f"山东高速探测完成: {len(records)} 条，至少两渠道印证 {verified} 条，单源待复核 {len(records) - verified} 条")


if __name__ == "__main__":
    main()
