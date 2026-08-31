#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集济南线下招聘活动，并在单源失败时保留上次成功数据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
SOURCE_FILE = BASE_DIR / "offline_event_sources.json"
OUTPUT_FILE = DATA_DIR / "offline_events.js"
SOURCE_OUTPUT_FILE = DATA_DIR / "offline_sources.js"
HEALTH_FILE = BASE_DIR / ".offline_source_health.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
EVENT_WORDS = re.compile(r"双选会|招聘会|宣讲会|校园宣讲|专场招聘|人才引进|招聘活动")
EXCLUDE_WORDS = re.compile(r"面试|笔试|签约|讲座|培训|考研|留学|就业指导|企业参观|开放日|线上|空中宣讲|空宣")
EMPTY_WORDS = re.compile(r"暂无.{0,8}(宣讲|招聘|活动|数据)|没有相关.{0,8}(宣讲|招聘|活动)")
JINAN_WORDS = re.compile(r"济南|历下|市中区|槐荫|天桥|历城|长清|章丘|济阳|莱芜|钢城|平阴|商河")
DATE_PATTERN = re.compile(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def request_sessions():
    stable = requests.Session()
    stable.headers.update(HEADERS)
    stable.proxies.update({"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"})
    env = requests.Session()
    env.headers.update(HEADERS)
    return [("mihomo:7890", stable), ("环境代理", env)]


def fetch(url: str, timeout: int = 18) -> tuple[str | None, str, str]:
    errors = []
    for channel, session in request_sessions():
        try:
            response = session.get(url, timeout=timeout)
            if response.status_code == 200 and len(response.content) > 200:
                response.encoding = response.apparent_encoding or "utf-8"
                return response.text, response.url, channel
            errors.append(f"{channel}:HTTP {response.status_code}")
        except Exception as exc:
            errors.append(f"{channel}:{type(exc).__name__}")
    return None, url, "; ".join(errors)[:200]


def fetch_json(url: str, params: dict | None = None, timeout: int = 18) -> tuple[dict | None, str]:
    errors = []
    for channel, session in request_sessions():
        try:
            response = session.get(url, params=params, timeout=timeout)
            if response.status_code == 200:
                return response.json(), channel
            errors.append(f"{channel}:HTTP {response.status_code}")
        except Exception as exc:
            errors.append(f"{channel}:{type(exc).__name__}")
    return None, "; ".join(errors)[:200]


def parse_date(text: str) -> date | None:
    match = DATE_PATTERN.search(text or "")
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_time_text(text: str) -> str:
    match = re.search(r"(?:宣讲|举办|活动|招聘)?时间[：:]?\s*(\d{1,2}:\d{2}\s*(?:[-—~至]\s*\d{1,2}:\d{2})?)", text)
    if match:
        return match.group(1)
    match = re.search(r"\d{1,2}:\d{2}\s*(?:[-—~至]\s*\d{1,2}:\d{2})?", text)
    return match.group(0) if match else "时间待公布"


def parse_location(text: str, default: str) -> str:
    match = re.search(r"(?:举办|活动|宣讲|招聘)(?:地点|场地)[：:]\s*([^\n|]{2,80})", text)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip(" ，。;")[:80]
    return default or "校内地点待公布"


def classify_type(title: str) -> str:
    if "双选" in title:
        return "双选会"
    if "宣讲" in title:
        return "企业宣讲会"
    if "人才引进" in title:
        return "人才引进活动"
    if "专场" in title or "组团" in title:
        return "专场招聘会"
    return "综合招聘会"


def find_exhibitor_link(soup: BeautifulSoup, base_url: str) -> tuple[str, str]:
    for anchor in soup.select("a[href]"):
        label = anchor.get_text(" ", strip=True)
        href = anchor.get("href", "")
        if re.search(r"参会单位|参展企业|企业名单|单位名单|展位表|招聘单位", label):
            return "查看企业名单", urljoin(base_url, href)
        if re.search(r"\.(?:pdf|docx?|xlsx?)($|\?)", href, re.I) and re.search(r"名单|展位|参会|参展", label):
            return "下载企业名单", urljoin(base_url, href)
    return "企业名单未公布", ""


def event_id(source_key: str, url: str, title: str, event_date: date) -> str:
    raw = url or f"{source_key}|{title}|{event_date.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def make_event(source: dict, title: str, event_date: date, detail_url: str,
               detail_text: str, detail_soup: BeautifulSoup) -> dict | None:
    if EXCLUDE_WORDS.search(title):
        return None
    location = parse_location(detail_text, source.get("campus", ""))
    if location == source.get("campus", ""):
        title_location = re.search(r"((?:舜耕|燕山|圣井|长清|千佛山|中心|主)校区[^，。]{0,30})", title)
        if title_location:
            location = title_location.group(1).strip()
    if EXCLUDE_WORDS.search(location):
        return None
    combined = f"{location} {source.get('campus', '')}"
    if not JINAN_WORDS.search(combined) and re.search(r"青岛|烟台|潍坊|泰安|淄博|临沂|德州|聊城|菏泽|济宁", location):
        return None
    exhibitor_status, exhibitor_url = find_exhibitor_link(detail_soup, detail_url)
    return {
        "id": event_id(source["key"], detail_url, title, event_date),
        "title": title[:160],
        "eventType": "企业宣讲会" if "宣讲" in location else classify_type(title),
        "organizer": source["name"],
        "school": source["name"] if source["key"] not in {"jnhrss", "jnjob"} else "",
        "startDate": event_date.isoformat(),
        "endDate": event_date.isoformat(),
        "timeText": parse_time_text(detail_text),
        "location": location,
        "city": "济南",
        "sourceKey": source["key"],
        "sourceName": source["name"],
        "sourceUrl": detail_url,
        "evidenceLevel": "官方",
        "exhibitorStatus": exhibitor_status,
        "exhibitorUrl": exhibitor_url,
        "admissionNotes": "未明确拒绝则默认可尝试入场",
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def scrape_sdei(source: dict, max_details: int) -> tuple[bool, list[dict], str]:
    """山东省大学生就业服务平台的宣讲会公开接口。"""
    api = f"{source['url'].rstrip('/')}/front/indexCarieList"
    payload, channel = fetch_json(api, {"pageNum": 1, "pageSize": max(100, max_details)})
    if not payload or not isinstance(payload.get("rows"), list):
        return False, [], channel or "宣讲会接口结构异常"
    today = date.today()
    horizon = today + timedelta(days=370)
    events = []
    for row in payload["rows"]:
        title = str(row.get("fairName") or "").strip()
        fair_type = str(row.get("fairType") or "")
        event_date = parse_date(str(row.get("fairDate") or ""))
        if not title or "线下" not in fair_type or EXCLUDE_WORDS.search(title):
            continue
        if not event_date or event_date < today or event_date > horizon:
            continue
        location = str(row.get("fairAddress") or source.get("campus") or "校内地点待公布")
        if re.search(r"线上|空宣", title + location):
            continue
        detail_url = f"{source['url'].rstrip('/')}/school/TblCareerFairReviewRecord/detail/{row.get('id')}"
        detail_html = str(row.get("fairDetail") or "")
        detail_soup = BeautifulSoup(detail_html, "lxml")
        detail_text = detail_soup.get_text("\n", strip=True)
        exhibitor_status, exhibitor_url = find_exhibitor_link(detail_soup, detail_url)
        events.append({
            "id": event_id(source["key"], detail_url, title, event_date),
            "title": title[:160], "eventType": classify_type(title),
            "organizer": source["name"], "school": source["name"],
            "startDate": event_date.isoformat(), "endDate": event_date.isoformat(),
            "timeText": " - ".join(filter(None, [str(row.get("fairStartTime") or ""), str(row.get("fairEndTime") or "")])) or "时间待公布",
            "location": location, "city": "济南", "sourceKey": source["key"],
            "sourceName": source["name"], "sourceUrl": detail_url,
            "evidenceLevel": "官方", "exhibitorStatus": exhibitor_status,
            "exhibitorUrl": exhibitor_url, "admissionNotes": "未明确拒绝则默认可尝试入场",
            "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    return True, events, channel


def scrape_source(source: dict, max_details: int) -> tuple[bool, list[dict], str]:
    if source.get("platform") == "sdei":
        return scrape_sdei(source, max_details)
    html, final_url, channel = fetch(source["url"])
    if not html:
        return False, [], channel
    soup = BeautifulSoup(html, "lxml")
    candidates = []
    for anchor in soup.select("a[href]"):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or anchor.get("title", "")).strip()
        href = anchor.get("href", "")
        is_platform_detail = bool(re.search(r"/detail/(?:career|jobfair)", href))
        if (not title or not href or len(title) <= 4
                or (not EVENT_WORDS.search(title) and not is_platform_detail)
                or EXCLUDE_WORDS.search(title)):
            continue
        candidates.append((title, urljoin(final_url, href)))

    # 山东省统一平台的首页链接文字有时把日期地点拼接在标题中，仍沿用同一候选处理。
    unique_candidates = []
    seen = set()
    for candidate in candidates:
        if candidate[1] not in seen:
            seen.add(candidate[1])
            unique_candidates.append(candidate)

    if not unique_candidates:
        if EMPTY_WORDS.search(soup.get_text(" ", strip=True)):
            return True, [], channel
        return False, [], "页面可达但未识别活动列表结构"

    today = date.today()
    horizon = today + timedelta(days=370)
    events = []
    for title, detail_url in unique_candidates[:max_details]:
        detail_html, resolved_url, _ = fetch(detail_url)
        if detail_html:
            detail_soup = BeautifulSoup(detail_html, "lxml")
            detail_text = detail_soup.get_text("\n", strip=True)
        else:
            detail_soup = soup
            detail_text = f"{title}\n{source.get('campus', '')}"
            resolved_url = detail_url
        event_date = parse_date(detail_text) or parse_date(title)
        if not event_date or event_date < today or event_date > horizon:
            continue
        event = make_event(source, title, event_date, resolved_url, detail_text, detail_soup)
        if event:
            events.append(event)
        time.sleep(0.25)
    return True, events, channel


def parse_existing() -> list[dict]:
    if not OUTPUT_FILE.exists():
        return []
    text = OUTPUT_FILE.read_text(encoding="utf-8")
    try:
        return json.loads(text[text.index("["):text.rindex("]") + 1])
    except Exception:
        return []


def canonical_key(event: dict) -> str:
    normalized = re.sub(r"\W+", "", f"{event.get('organizer','')}{event.get('title','')}")
    return f"{normalized}|{event.get('startDate','')}|{re.sub(r'\W+', '', event.get('location',''))}"


def write_js(path: Path, const_name: str, records: list[dict], title: str):
    payload = json.dumps(records, ensure_ascii=False, indent=2)
    path.write_text(
        f"// {title} — 由 scrape_offline_events.py 生成\n"
        f"// 更新时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n\n"
        f"const {const_name} = {payload};\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="仅采集指定 source key")
    parser.add_argument("--max-details", type=int, default=30)
    args = parser.parse_args()

    sources = load_json(SOURCE_FILE, [])
    if args.source:
        sources = [source for source in sources if source["key"] == args.source]
    health = load_json(HEALTH_FILE, {})
    existing = parse_existing()
    today = date.today().isoformat()
    merged = {canonical_key(event): event for event in existing if event.get("endDate", event.get("startDate", "")) >= today}

    for source in sources:
        ok, events, message = scrape_source(source, args.max_details)
        state = health.get(source["key"], {})
        state.update({"name": source["name"], "url": source["url"], "platform": source["platform"]})
        if ok:
            # 仅在确认页面结构有效后替换该来源；失败时绝不清空旧数据。
            merged = {key: value for key, value in merged.items() if value.get("sourceKey") != source["key"]}
            new_count = 0
            for event in events:
                key = canonical_key(event)
                if key not in merged:
                    new_count += 1
                merged[key] = {**merged.get(key, {}), **event}
            state.update({
                "lastSuccessAt": datetime.now().isoformat(timespec="seconds"),
                "lastError": "", "consecutiveFailures": 0,
                "lastRunCount": len(events), "lastNewCount": new_count,
            })
            if new_count:
                state["lastNewAt"] = datetime.now().isoformat(timespec="seconds")
            print(f"[ok] {source['name']}: {len(events)} 场，新增 {new_count}（{message}）")
        else:
            state["consecutiveFailures"] = int(state.get("consecutiveFailures", 0)) + 1
            state["lastError"] = message
            print(f"[fail] {source['name']}: {message}，保留旧数据")
        health[source["key"]] = state
        time.sleep(0.4)

    events = sorted(merged.values(), key=lambda item: (item.get("startDate", ""), item.get("timeText", "")))
    for source in sources:
        health[source["key"]]["activeCount"] = sum(1 for event in events if event.get("sourceKey") == source["key"])
    health["_meta"] = {"updatedAt": datetime.now().isoformat(timespec="seconds"), "sourceCount": len(sources)}
    HEALTH_FILE.write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")
    public_health = [{
        "key": source["key"], "name": source["name"], "platform": source["platform"],
        "required": bool(source.get("required")),
        "lastSuccessAt": health[source["key"]].get("lastSuccessAt", ""),
        "lastNewAt": health[source["key"]].get("lastNewAt", ""),
        "activeCount": health[source["key"]].get("activeCount", 0),
        "consecutiveFailures": health[source["key"]].get("consecutiveFailures", 0),
    } for source in sources]
    DATA_DIR.mkdir(exist_ok=True)
    write_js(OUTPUT_FILE, "OFFLINE_EVENTS", events, "济南线下招聘活动")
    write_js(SOURCE_OUTPUT_FILE, "OFFLINE_SOURCES", public_health, "线下活动来源健康")
    failures = sum(1 for source in sources if health[source["key"]].get("consecutiveFailures", 0) >= 3)
    print(f"完成: {len(events)} 场有效活动，{len(sources)} 个来源，{failures} 个连续失败来源")


if __name__ == "__main__":
    main()
