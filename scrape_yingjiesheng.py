#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
应届生求职网爬虫 — 交通类校招岗位
===================================
搜索多个交通关键词，抓取岗位列表和详情

用法：
    python scrape_yingjiesheng.py                     # 全部关键词
    python scrape_yingjiesheng.py --keyword 运输       # 单个关键词
    python scrape_yingjiesheng.py --max-pages 5       # 每个关键词最多翻5页

输出：追加到 data/jobs.js（保留已有手动数据）
"""

import re
import json
import time
import random
import hashlib
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, quote

import requests
from bs4 import BeautifulSoup

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_FILE = DATA_DIR / "jobs_yingjiesheng.js"
MANUAL_FILE = DATA_DIR / "jobs_manual.js"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
]
REQUEST_TIMEOUT = 10
REQUEST_DELAY = 0.6

# 交通类搜索关键词
TRANSPORT_KEYWORDS = [
    "交通运输", "物流管理", "港口", "航运", "铁路", "轨道交通",
    "航空", "机场", "水务", "水利", "高速", "公路", "邮政", "快递",
    "仓储", "供应链", "公交", "地铁", "海事", "船舶",
]

# 行业分类页（移动版不需要，用关键词搜索覆盖）

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


def polite_wait():
    time.sleep(REQUEST_DELAY + random.random() * 0.5)


# ============================================================
# 行业推断（同 scraper.py）
# ============================================================
INDUSTRY_PATTERNS = [
    (["港口", "港务", "港航", "港湾", "海运", "航运", "船舶", "引航", "水运", "滚装"], "港口/航运"),
    (["高速", "路桥", "公路", "交投", "交通", "铁投"], "公路/高速"),
    (["铁路", "铁道", "轨道交通", "地铁", "机车", "中车", "轨交"], "铁路/轨交"),
    (["机场", "航空", "民航", "空管", "航瑞"], "航空"),
    (["邮政", "物流", "快递", "仓储", "供应链"], "邮政/物流"),
    (["水务", "水利", "水发", "水处理", "给排水"], "水务/水利"),
    (["公交", "客运", "交运"], "公交/客运"),
    (["设计院", "勘察", "勘测", "规划院"], "交通设计/规划"),
    (["汽车", "客车", "车辆"], "汽车/车辆"),
    (["能源", "电力", "电网", "矿业", "煤炭", "石油", "石化"], "能源/电力"),
    (["建筑", "建材", "建设", "工程", "施工", "土木"], "建筑/建材"),
]


def guess_industry(name: str, position: str) -> str:
    text = (name + " " + position).lower()
    for keywords, industry in INDUSTRY_PATTERNS:
        for kw in keywords:
            if kw in text:
                return industry
    return "综合"


def classify_company(name: str) -> str:
    if any(k in name for k in ["银行", "证券", "保险"]):
        return "银行/金融"
    if any(k in name for k in ["学院", "学校", "大学", "医院", "设计院", "研究院", "科学院", "规划院", "中心"]):
        return "事业单位"
    if any(k in name for k in ["集团", "有限", "控股", "股份"]):
        return "央国企"
    if any(k in name for k in ["外资", "外企", "中外"]):
        return "外企"
    return "企业"


# ============================================================
# 搜索列表抓取（移动版 m.yingjiesheng.com）
# ============================================================
YJS_MOBILE = "https://m.yingjiesheng.com/h.php"


def scrape_search(keyword: str, max_pages: int = 3) -> list[dict]:
    """搜索关键词，从移动版抓取职位列表"""
    print(f"\n  🔍 关键词: {keyword}")
    jobs = []

    for page in range(max_pages):
        start = page * 20
        url = f"{YJS_MOBILE}?word={quote(keyword)}&start={start}"
        print(f"    📄 第{page+1}页 (start={start})")

        html = safe_get(url)
        if not html:
            break

        soup = BeautifulSoup(html, "lxml")
        page_count = 0

        # 移动版格式（每个 a 中有两个 span）：
        # <a href="..." class="clearfix">
        #   <span>[城市] 公司名 职位名</span><br />
        #   <span>YYYY-MM-DD</span> &nbsp; <span>城市</span>
        # </a>
        for a in soup.select("ul.list a.clearfix, ul.link_visit a.clearfix"):
            href = a.get("href", "")
            if "job-" not in href:
                continue

            spans = a.find_all("span")
            if len(spans) < 2:
                continue

            title_span = spans[0].get_text(strip=True)
            date_span = spans[1].get_text(strip=True)
            # 第三个 span 是城市（备用）
            loc_span = spans[2].get_text(strip=True) if len(spans) > 2 else ""

            # 解析标题: [城市] 公司名 职位名
            m = re.match(r'\[([^\]]+)\]\s*(.+)', title_span)
            if not m:
                continue

            location = m.group(1).strip()
            rest = m.group(2).strip()

            # 日期
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", date_span)
            date_str = date_match.group(1) if date_match else datetime.now().strftime("%Y-%m-%d")

            # 从 rest 中区分公司名和职位名
            company = rest
            position = ""
            company_suffixes = ["有限公司", "集团有限公司", "有限责任公司", "集团", "公司",
                               "中心", "局", "处", "支队", "事务所", "分行", "支行"]
            for suffix in company_suffixes:
                idx = rest.find(suffix)
                if idx > 0 and idx < 30:  # 公司名不会太长
                    company = rest[:idx + len(suffix)]
                    position = rest[idx + len(suffix):].strip()
                    break

            if not position:
                position = rest

            # 跳过太旧的
            if date_str < "2025-09-01":
                continue

            detail_url = urljoin("https://m.yingjiesheng.com/", href)

            job = {
                "id": 0,
                "companyName": company.strip(),
                "companyType": classify_company(company),
                "industry": guess_industry(company, position),
                "recruitType": "春招",
                "targetYears": "2026届",
                "location": location,
                "positions": position.strip()[:100],
                "status": "未投递",
                "updateTime": date_str,
                "deadline": "招满为止",
                "applyLink": detail_url,
                "noticeLink": detail_url,
                "examInfo": "",
                "companyScale": "",
                "notes": f"来源: 应届生求职网 [{date_str}]",
            }
            jobs.append(job)
            page_count += 1

        print(f"    ✅ {page_count} 条")
        if page_count < 18:
            break
        polite_wait()

    return jobs


# ============================================================
# 输出（合并到 jobs.js）
# ============================================================
def load_existing_jobs(filepath: Path) -> list[dict]:
    """从现有 jobs.js 加载已抓取数据（用于去重合并）"""
    if not filepath.exists():
        return []
    content = filepath.read_text(encoding="utf-8")
    m = re.search(r"const JOBS\s*=\s*(\[.*?\]);", content, re.DOTALL)
    if not m:
        return []
    try:
        # JS 对象字面量转 JSON（简单替换）
        js_text = m.group(1)
        # 替换单引号 key
        js_text = re.sub(r'(\w+):', r'"\1":', js_text)
        return json.loads(js_text)
    except Exception:
        return []


def merge_jobs(existing: list[dict], new_jobs: list[dict]) -> list[dict]:
    seen = set()
    merged = []

    for job in existing:
        key = hashlib.md5(
            f"{job.get('companyName','')}|{job.get('positions','')[:30]}|{job.get('applyLink','')[:60]}".encode()
        ).hexdigest()
        seen.add(key)
        merged.append(job)

    added = 0
    for job in new_jobs:
        key = hashlib.md5(
            f"{job.get('companyName','')}|{job.get('positions','')[:30]}|{job.get('applyLink','')[:60]}".encode()
        ).hexdigest()
        if key not in seen:
            seen.add(key)
            merged.append(job)
            added += 1

    # 按日期倒序
    merged.sort(key=lambda j: j.get("updateTime", ""), reverse=True)

    # 重新分配 ID
    for i, job in enumerate(merged, 1):
        job["id"] = i

    return merged, added


def output_jobs_js(jobs: list[dict], filepath: Path):
    lines = [
        "// 应届生求职网 — 自动爬取生成",
        f"// 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"// 共 {len(jobs)} 条",
        "",
        "const JOBS_YINGJIESHENG = [",
    ]
    for i, job in enumerate(jobs):
        lines.append("  {")
        for key in ["id", "companyName", "companyType", "industry", "recruitType",
                     "targetYears", "location", "positions", "status",
                     "updateTime", "deadline", "applyLink", "noticeLink",
                     "examInfo", "companyScale", "notes"]:
            val = job.get(key, "")
            if isinstance(val, str):
                val = val.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'    {key}: "{val}",')
            else:
                lines.append(f'    {key}: {val},')
        lines[-1] = lines[-1].rstrip(",")
        lines.append("  }," if i < len(jobs) - 1 else "  }")
    lines.append("];\n")
    filepath.write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="应届生求职网爬虫")
    parser.add_argument("--keyword", type=str, help="单个关键词（默认全部交通关键词）")
    parser.add_argument("--max-pages", type=int, default=3, help="每个关键词最大翻页数")
    args = parser.parse_args()

    keywords = [args.keyword] if args.keyword else TRANSPORT_KEYWORDS
    all_jobs = []

    print(f"{'='*60}")
    print(f"🔍 应届生求职网 — 交通类校招 ({len(keywords)} 个关键词)")
    print(f"{'='*60}")

    for kw in keywords:
        jobs = scrape_search(kw, args.max_pages)
        all_jobs.extend(jobs)
        polite_wait()

    if not all_jobs:
        print("\n⚠ 未抓取任何数据")
        return

    # 去重
    seen = set()
    unique = []
    for job in all_jobs:
        key = f"{job.get('companyName','')}|{job.get('positions','')[:30]}|{job.get('applyLink','')[:60]}"
        h = hashlib.md5(key.encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(job)

    # 按日期倒序
    unique.sort(key=lambda j: j.get("updateTime", ""), reverse=True)
    for i, job in enumerate(unique, 1):
        job["id"] = i

    output_jobs_js(unique, OUTPUT_FILE)

    industries = {}
    for j in all_jobs:
        ind = j.get("industry", "综合")
        industries[ind] = industries.get(ind, 0) + 1
    print(f"  新增行业分布:")
    for ind, cnt in sorted(industries.items(), key=lambda x: -x[1])[:10]:
        print(f"    {ind}: {cnt}")


if __name__ == "__main__":
    main()
