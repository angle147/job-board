#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集济南市及区县地方国企官方招聘栏目。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent
SOURCE_FILE = BASE_DIR / "local_soe_sources.json"
OUTPUT_FILE = BASE_DIR / "data" / "jobs_local_soe.js"
HEALTH_FILE = BASE_DIR / ".local_soe_source_health.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
JOB_WORDS = re.compile(r"招聘|招录|校园招聘|校招|人才引进")
SOE_CONTEXT_WORDS = re.compile(r"国有企业|国企|区属企业|控股集团|人才集团|历下控股")
DATE_RE = re.compile(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?")


def sessions():
    proxy = requests.Session()
    proxy.headers["User-Agent"] = UA
    proxy.proxies.update({"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"})
    direct = requests.Session()
    direct.trust_env = False
    direct.headers["User-Agent"] = UA
    return (("mihomo:7890", proxy), ("direct", direct))


def get(url: str, *, params=None, json_response=False):
    errors = []
    for channel, session in sessions():
        try:
            response = session.get(url, params=params, timeout=20)
            response.raise_for_status()
            if json_response:
                return response.json(), channel
            response.encoding = response.apparent_encoding or "utf-8"
            return response.text, channel
        except Exception as exc:
            errors.append(f"{channel}:{type(exc).__name__}")
    raise RuntimeError("; ".join(errors))


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_existing():
    if not OUTPUT_FILE.exists():
        return []
    text = OUTPUT_FILE.read_text(encoding="utf-8")
    try:
        return json.loads(text[text.index("["):text.rindex("]") + 1])
    except Exception:
        return []


def first_date(text: str) -> str:
    match = DATE_RE.search(text or "")
    if not match:
        return ""
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def deadline(text: str) -> str:
    for pattern in (
        r"(?:报名|申请)?截止(?:时间|日期)?[：:\s]*([^。；\n]{0,30})",
        r"报名时间[^。；\n]{0,80}?至[：:\s]*([^。；\n]{0,30})",
    ):
        match = re.search(pattern, text)
        if match:
            parsed = first_date(match.group(1))
            if parsed:
                return parsed
    return "待核验"


def company_from_title(title: str) -> str:
    match = re.search(r"(.{2,40}?(?:集团有限公司|有限责任公司|有限公司|集团))", title)
    return match.group(1).strip("“”《》 ") if match else title.split("招聘", 1)[0].strip("“”《》 ")


def to_job(source: dict, title: str, url: str, detail: str, published: str, index: int):
    years = sorted(set(re.findall(r"20\d{2}(?=届|年)", title + " " + detail)))
    employment = "直接用工"
    if "劳务派遣" in detail:
        employment = "劳务派遣"
    elif "劳务外包" in detail or "外包用工" in detail:
        employment = "劳务外包"
    elif "政府购买服务" in detail:
        employment = "政府购买服务"
    identifier = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return {
        "id": f"local_soe_{identifier}", "companyName": company_from_title(title),
        "companyType": "地方国企线索", "industry": "综合", "recruitType": "公开招聘",
        "targetYears": ",".join(f"{year}届" for year in years), "location": source["region"],
        "positions": title, "status": "未投递", "updateTime": published,
        "deadline": deadline(detail), "applyLink": url, "noticeLink": url,
        "examInfo": "以公告为准", "companyScale": "", "notes": f"来源: {source['name']}",
        "actualEmployer": company_from_title(title), "contractEmployer": "待核验",
        "employmentType": employment, "ownershipRelation": "控制关系待核验",
        "ownershipEvidenceUrl": source["url"], "sourceKey": source["key"],
    }


def scrape_jpaas(source: dict, max_details: int):
    payload, channel = get(source["apiUrl"], params=source["apiParams"], json_response=True)
    html = payload.get("data", {}).get("html", "") if isinstance(payload, dict) else ""
    if not html:
        raise RuntimeError("JPaas 列表结构异常")
    soup = BeautifulSoup(html, "lxml")
    anchors = []
    for anchor in soup.select("a[href]"):
        title = (anchor.get("title") or anchor.get_text(" ", strip=True)).strip()
        if title and JOB_WORDS.search(title):
            anchors.append((title, urljoin(source["url"], anchor["href"]), anchor.parent.get_text(" ", strip=True)))
    if not anchors:
        raise RuntimeError("页面可达但未识别招聘列表")
    jobs = []
    for index, (title, url, row_text) in enumerate(anchors[:max_details], 1):
        detail_html, _ = get(url)
        detail_text = BeautifulSoup(detail_html, "lxml").get_text("\n", strip=True)
        published = first_date(row_text) or first_date(detail_text) or date.today().isoformat()
        jobs.append(to_job(source, title, url, detail_text, published, index))
    return jobs, channel


def scrape_jsearch(source: dict, max_details: int):
    """采集 JPaas 站内检索；先验证分类与结果结构，再筛选真实招聘标题。"""
    errors = []
    for channel, session in sessions():
        try:
            base = source["searchBaseUrl"].rstrip("/")
            service_id = source["serviceId"]
            landing = session.get(f"{base}/search", params={"serviceId": service_id, "q": "招聘"}, timeout=20)
            landing.raise_for_status()
            categories = session.get(
                f"{base}/interface/structure/list-category",
                params={"serviceId": service_id}, timeout=20,
                headers={"Referer": landing.url},
            ).json()
            category_list = categories.get("data", {}).get("categories", [])
            if not categories.get("success") or not category_list:
                raise RuntimeError("JSearch 分类结构异常")
            category_id = next((x["iid"] for x in category_list if x.get("categoryName") == "全部"), category_list[0]["iid"])
            candidates = {}
            valid_queries = 0
            for query in source.get("queries", []):
                payload = session.get(
                    f"{base}/interface/search/info",
                    params={"websiteid": "", "q": query, "pg": 50, "p": 1,
                            "serviceId": service_id, "cateid": category_id},
                    timeout=20, headers={"Referer": landing.url},
                ).json()
                result = payload.get("data", {}).get("searchResult")
                if payload.get("success") and isinstance(result, dict) and isinstance(result.get("result"), list):
                    valid_queries += 1
                    for fragment in result["result"]:
                        soup = BeautifulSoup(fragment, "lxml")
                        anchor = soup.select_one("a.textTitle[href], a[data-title][href]")
                        if not anchor:
                            continue
                        title = (anchor.get("data-title") or anchor.get_text(" ", strip=True)).strip()
                        url = urljoin(source["url"], anchor["href"])
                        text = soup.get_text(" ", strip=True)
                        if JOB_WORDS.search(title) and SOE_CONTEXT_WORDS.search(title + " " + text):
                            candidates[url] = (title, first_date(text))
            if valid_queries != len(source.get("queries", [])):
                raise RuntimeError(f"JSearch 查询结构不完整 {valid_queries}/{len(source.get('queries', []))}")
            jobs = []
            for index, (url, (title, published)) in enumerate(list(candidates.items())[:max_details], 1):
                detail_html = session.get(url, timeout=20).text
                detail_text = BeautifulSoup(detail_html, "lxml").get_text("\n", strip=True)
                jobs.append(to_job(source, title, url, detail_text, published or first_date(detail_text) or date.today().isoformat(), index))
            return jobs, channel
        except Exception as exc:
            errors.append(f"{channel}:{type(exc).__name__}:{exc}")
    raise RuntimeError("; ".join(errors))


def write_output(jobs):
    header = ("// 济南地方国企官方招聘 — 自动采集\n"
              f"// 更新时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
              f"// 共 {len(jobs)} 条\n\nconst JOBS_LOCAL_SOE = ")
    OUTPUT_FILE.write_text(header + json.dumps(jobs, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source")
    parser.add_argument("--max-details", type=int, default=30)
    args = parser.parse_args()
    sources = load_json(SOURCE_FILE, [])
    active = [s for s in sources if s.get("status") == "active" and (not args.source or s["key"] == args.source)]
    existing = load_existing()
    merged = {job.get("sourceKey", ""): [] for job in existing}
    for job in existing:
        merged.setdefault(job.get("sourceKey", ""), []).append(job)
    health = load_json(HEALTH_FILE, {})
    for source in active:
        try:
            if source["platform"] == "jpaas":
                jobs, channel = scrape_jpaas(source, args.max_details)
            elif source["platform"] == "jsearch":
                jobs, channel = scrape_jsearch(source, args.max_details)
            else:
                raise RuntimeError(f"尚未适配平台族 {source['platform']}")
            merged[source["key"]] = jobs
            health[source["key"]] = {"name": source["name"], "lastSuccessAt": datetime.now().isoformat(timespec="seconds"),
                                     "lastError": "", "consecutiveFailures": 0, "activeCount": len(jobs)}
            print(f"[ok] {source['name']}: {len(jobs)} 条（{channel}）")
        except Exception as exc:
            state = health.get(source["key"], {})
            state.update({"name": source["name"], "lastError": str(exc),
                          "consecutiveFailures": int(state.get("consecutiveFailures", 0)) + 1,
                          "activeCount": len(merged.get(source["key"], []))})
            health[source["key"]] = state
            print(f"[fail] {source['name']}: {exc}，保留旧数据")
    jobs = [job for records in merged.values() for job in records]
    write_output(jobs)
    HEALTH_FILE.write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"地方国企来源完成: {len(jobs)} 条，{len(active)} 个有效来源")


if __name__ == "__main__":
    main()
