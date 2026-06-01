#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校招/社招岗位爬虫 v2 — 山东省国资委 + 铁路人才网 + 人社厅
===========================================================
参考 Auto-JobHunter 的反爬策略：指数退避、请求抖动、会话复用。

用法：
    python scraper.py                     # 全部源抓取
    python scraper.py --source sasac      # 只抓国资委
    python scraper.py --max-pages 5       # 限制翻页
    python scraper.py --details 20        # 每页抓取详情条数（默认15）

输出：data/jobs.js（覆盖写入）
"""

import re
import json
import time
import random
import argparse
import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_FILE = DATA_DIR / "jobs.js"

# User-Agent 池（轮换，降低反爬识别）
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]

REQUEST_TIMEOUT = 12
REQUEST_DELAY_BASE = 0.8   # 基础等待（秒）
REQUEST_DELAY_JITTER = 0.5  # 随机抖动幅度
MAX_RETRIES = 3             # 最大重试次数

# 公共 Session（连接复用）
_session = None


def get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })
    return _session


def random_ua():
    return random.choice(USER_AGENTS)


def polite_wait():
    """带抖动的礼貌等待（参考 Auto-JobHunter jitter 策略）"""
    time.sleep(REQUEST_DELAY_BASE + random.random() * REQUEST_DELAY_JITTER)


# ============================================================
# 网络工具
# ============================================================
def safe_get(url: str, encoding: str = "utf-8") -> str | None:
    """
    安全抓取，指数退避重试（参考 Auto-JobHunter retry 策略）
    """
    session = get_session()
    for attempt in range(MAX_RETRIES):
        try:
            session.headers["User-Agent"] = random_ua()
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.encoding = resp.apparent_encoding or encoding
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 429):
                # 被限流，等待更久
                wait = (2 ** attempt) * 2 + random.random() * 3
                print(f"  [WARN] {url} 返回 {resp.status_code}，等待 {wait:.0f}s 后重试")
                time.sleep(wait)
            else:
                print(f"  [WARN] {url} 返回 {resp.status_code}")
        except requests.Timeout:
            print(f"  [WARN] 第 {attempt+1} 次请求超时: {url}")
        except Exception as e:
            print(f"  [WARN] 第 {attempt+1} 次请求失败: {e}")

        if attempt < MAX_RETRIES - 1:
            backoff = (2 ** attempt) + random.random()
            time.sleep(backoff)

    return None


def extract_date(text: str) -> str:
    """从文本中提取标准日期 YYYY-MM-DD"""
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def extract_detail_fields(detail_html: str) -> dict:
    """从详情页 HTML 提取关键字段（一次请求，复用解析）"""
    soup = BeautifulSoup(detail_html, "lxml")
    text = soup.get_text(separator="\n", strip=True)
    result = {"location": "", "deadline": "", "applyLink": "", "positions": "",
              "targetYears": "2026届", "education": ""}

    # 工作地点
    for pat in [r"工作地点[：:]\s*(.+?)(?:\n|。|；)", r"工作地址[：:]\s*(.+?)(?:\n|。|；)",
                r"工作城市[：:]\s*(.+?)(?:\n|。|；)", r"地点[：:]\s*(.+?)(?:\n|。|；)"]:
        m = re.search(pat, text)
        if m:
            result["location"] = m.group(1).strip().rstrip("，。；")
            break

    # 截止时间
    for pat in [r"报名截止[时间日]?[：:]\s*(.+?)(?:\n|。|；)",
                r"截止[时间日]?[：:]\s*(.+?)(?:\n|。|；)",
                r"截止日期[：:]\s*(.+?)(?:\n|。|；)",
                r"(\d{4}年\d{1,2}月\d{1,2}日).*?截止",
                r"自.*?至\s*(\d{4}年\d{1,2}月\d{1,2}日)"]:
        m = re.search(pat, text)
        if m:
            d = extract_date(m.group(1))
            if d:
                result["deadline"] = d
                break

    # 投递链接
    for pat in [r'(https?://[^\s<>"]*(?:zhaopin|recruit|campus|job|hotjob|51job|zhiye|hotjob\.cn)[^\s<>"]*)',
                r"报名网址[：:]\s*(https?://[^\s\n]+)",
                r"报名链接[：:]\s*(https?://[^\s\n]+)",
                r"投递网址[：:]\s*(https?://[^\s\n]+)"]:
        m = re.search(pat, text)
        if m:
            result["applyLink"] = m.group(1).strip().rstrip("。；，")
            break

    # 岗位描述
    for pat in [r"招聘岗位[：:]\s*(.+?)(?:\n|。|；)", r"招聘职位[：:]\s*(.+?)(?:\n|。|；)",
                r"岗位名称[：:]\s*(.+?)(?:\n|。|；)"]:
        m = re.search(pat, text)
        if m:
            result["positions"] = m.group(1).strip().rstrip("，。；")
            break

    # 毕业届数
    years_set = set()
    for pat in [r"(\d{4})届.*?应届", r"(\d{4})年应届", r"(\d{4})年毕业[生]?", r"(\d{4})年.*?毕业生"]:
        for ym in re.finditer(pat, text):
            years_set.add(ym.group(1) + "届")
    if not years_set:
        for yr in ["2024", "2025", "2026", "2027"]:
            if yr in text:
                years_set.add(yr + "届")
    if years_set:
        result["targetYears"] = ",".join(sorted(years_set))

    # 学历
    edu = []
    if "硕士" in text or "研究生" in text:
        edu.append("硕士及以上")
    if "博士" in text:
        edu.append("博士优先")
    if "本科" in text:
        if "硕士" not in text:
            edu.append("本科及以上")
    result["education"] = "、".join(edu)

    return result


# ============================================================
# 标题解析
# ============================================================
def parse_title(title: str) -> dict:
    """
    解析标题 → {companyName, recruitType, isValid}
    """
    result = {"companyName": "", "recruitType": "校招/社招", "isValid": True}

    # 过滤导航链接
    noise = ["首页", "无障碍", "关怀版", "新闻中心", "政务公开", "公众参与",
             "专题专栏", "招聘专栏", "驻委纪检监察组", "当前位置", "信息公开",
             "政策文件", "办事服务", "互动交流", "设为首页", "收藏本站"]
    if any(n in title for n in noise):
        result["isValid"] = False
        return result

    # 去掉引号和年份前缀
    cleaned = re.sub(r'[\u201c\u201d\u300c\u300d][^\u201c\u201d\u300c\u300d]*[\u201c\u201d\u300c\u300d]', '', title)
    cleaned = re.sub(r'^\d{4}年', '', cleaned)
    cleaned = re.sub(r'^才聚齐鲁\s*成就未来\s*', '', cleaned)
    cleaned = re.sub(r'^[\s\u300a\u300b\u201c\u201d\u300c\u300d]+', '', cleaned)

    # 提取招聘类型
    type_map = [
        (r"校园招聘|校招(?!.*社招)|应届.*?招聘", "春招"),
        (r"社会招聘|社招", "社招"),
        (r"实习", "实习"),
        (r"秋招提前批", "秋招提前批"),
        (r"春招补录", "春招补录"),
    ]
    for pat, t in type_map:
        if re.search(pat, cleaned):
            result["recruitType"] = t
            break

    # 提取公司名
    company_pat = r'(.+?(?:有限公司|集团有限公司|集团|公司|银行|中心|设计院|研究院|院|所|学校|学院|大学))'
    m = re.search(company_pat, cleaned)
    if m:
        raw = m.group(1).strip("\u300a\u300b\u300c\u300d\u201c\u201d").strip()
        raw = re.sub(r'^才聚齐鲁\s*成就未来\s*', '', raw).strip()
        result["companyName"] = raw
    else:
        m = re.search(r'(.+?)(?:校园|社会|公开|招聘|公告|简章|启事)', cleaned)
        if m:
            raw = m.group(1).strip("\u300a\u300b\u300c\u300d\u201c\u201d").strip()
            raw = re.sub(r'^才聚齐鲁\s*成就未来\s*', '', raw).strip()
            result["companyName"] = raw

    if not result["companyName"] or len(result["companyName"]) < 3:
        result["isValid"] = False

    return result


# ============================================================
# 行业 + 类型推断
# ============================================================
INDUSTRY_PATTERNS = [
    (["港口", "港务", "港航", "港湾", "海运", "航运", "船舶", "引航", "水运"], "港口/航运"),
    (["高速", "路桥", "公路", "交投", "交通", "铁投"], "公路/高速"),
    (["铁路", "铁道", "轨道交通", "地铁", "机车", "中车", "轨交"], "铁路/轨交"),
    (["机场", "航空", "民航", "空管"], "航空"),
    (["邮政", "物流", "快递", "仓储", "供应链"], "邮政/物流"),
    (["水务", "水利", "水发", "水处理", "给排水", "南水北调", "引水"], "水务/水利"),
    (["公交", "客运", "交运"], "公交/客运"),
    (["设计院", "勘察", "勘测", "规划院"], "交通设计/规划"),
    (["汽车", "客车", "车辆"], "汽车/车辆"),
    (["能源", "电力", "电网", "矿业", "煤炭", "兖矿", "石油"], "能源/电力"),
    (["建筑", "建材", "建设", "工程", "施工", "土木"], "建筑/建材"),
    (["电子", "半导体", "芯片", "集成电路", "微电子"], "电子/半导体"),
    (["软件", "信息", "数据", "数字", "互联网", "人工智能", "云", "科技"], "软件技术"),
    (["银行", "金融", "证券", "保险", "投资", "财金", "产权交易", "期货"], "金融/银行"),
    (["烟草"], "烟草"),
    (["健康", "医疗", "医药", "药业", "生物", "医养"], "医药健康"),
    (["文旅", "旅游", "文化", "传媒", "出版", "展览"], "文旅/传媒"),
    (["农业", "畜牧", "食品", "粮食", "种业", "农发"], "农业/食品"),
    (["钢铁", "冶金", "化工", "新材料", "纺织", "纤维"], "钢铁/化工"),
    (["电器", "家电"], "电器/家电"),
    (["地产", "物业", "置业", "土地发展"], "地产/物业"),
    (["环保", "环境", "生态"], "环保"),
    (["消防", "应急"], "应急/消防"),
]


def guess_industry(name: str) -> str:
    for keywords, industry in INDUSTRY_PATTERNS:
        for kw in keywords:
            if kw in name:
                return industry
    return "综合"


def classify_company(name: str) -> str:
    if any(k in name for k in ["银行", "证券", "保险", "期货"]):
        return "银行/金融"
    if any(k in name for k in ["学院", "学校", "大学", "医院", "设计院", "研究院", "科学院", "规划院"]):
        return "事业单位"
    return "央国企"


# ============================================================
# 数据源 1: 山东省国资委
# ============================================================
SASAC_BASE = "http://gzw.shandong.gov.cn/channels/ch00223/"


def scrape_sasac(max_pages: int = 3, detail_limit: int = 15) -> list[dict]:
    print(f"\n{'='*60}")
    print(f"🔍 山东省国资委招聘专栏 (最多 {max_pages} 页, 详情前 {detail_limit} 条)")
    print(f"{'='*60}")

    jobs = []

    for page in range(1, max_pages + 1):
        url = SASAC_BASE if page == 1 else f"{SASAC_BASE}index_{page}.html"
        print(f"\n  📄 第 {page} 页: {url}")

        html = safe_get(url)
        if not html:
            if page > 1:
                alt = f"{SASAC_BASE}?page={page}"
                html = safe_get(alt)
            if not html:
                print(f"  ⚠ 无法访问，停止翻页")
                break

        soup = BeautifulSoup(html, "lxml")

        # 只取内容区的链接（td width=876 的 a 标签，排除导航）
        entries = []
        for a in soup.select("td[width='876'] a, a[title]"):
            title = a.get("title") or a.get_text(strip=True)
            href = a.get("href", "")
            if not href or not title or len(title) < 10:
                continue
            if not any(kw in title for kw in ["招聘", "招录", "校招", "社招", "实习"]):
                continue
            if any(kw in title for kw in ["首页", "无障碍", "新闻中心", "政务公开",
                                            "专题专栏", "招聘专栏"]):
                continue

            # 从同行 td 找日期
            date_str = ""
            parent_td = a.find_parent("td")
            if parent_td:
                parent_tr = parent_td.find_parent("tr")
                if parent_tr:
                    for td in parent_tr.find_all("td"):
                        dm = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", td.get_text(strip=True))
                        if dm:
                            date_str = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
                            break
            if not date_str:
                date_str = extract_date(title)

            entries.append((title, href, date_str or datetime.now().strftime("%Y-%m-%d")))

        page_count = 0
        for i, (title, href, date_str) in enumerate(entries):
            info = parse_title(title)
            if not info["isValid"]:
                continue

            detail_url = urljoin(url, href)

            job = {
                "id": 0,
                "companyName": info["companyName"],
                "companyType": classify_company(info["companyName"]),
                "industry": guess_industry(info["companyName"]),
                "recruitType": info["recruitType"],
                "targetYears": "2026届",
                "location": "",
                "positions": "",
                "status": "未投递",
                "updateTime": date_str,
                "deadline": "招满为止",
                "applyLink": "",
                "noticeLink": detail_url,
                "examInfo": "",
                "companyScale": "",
                "notes": f"来源: 山东省国资委 [{date_str}]",
            }

            # 详情页（前 N 条）
            if i < detail_limit:
                detail_html = safe_get(detail_url)
                if detail_html:
                    fields = extract_detail_fields(detail_html)
                    if fields["location"]:
                        job["location"] = fields["location"]
                    if fields["deadline"]:
                        job["deadline"] = fields["deadline"]
                    if fields["applyLink"]:
                        job["applyLink"] = fields["applyLink"]
                    if fields["positions"]:
                        job["positions"] = fields["positions"]
                    if fields["targetYears"] != "2026届":
                        job["targetYears"] = fields["targetYears"]
                    if fields["education"]:
                        job["notes"] = fields["education"] + " | " + job["notes"]
                    polite_wait()

            jobs.append(job)
            page_count += 1

        print(f"  ✅ 本页 {page_count} 条 (有效 {len(entries)} 条链接)")
        polite_wait()

        if page_count < 5 and page > 1:
            print(f"  ⚠ 条目较少，停止翻页")
            break

    print(f"\n  🎯 国资委共 {len(jobs)} 条")
    return jobs


# ============================================================
# 数据源 2: 铁路人才网
# ============================================================
RAILWAY_URL = "https://rczp.china-railway.com.cn/page/recruitment/rec_info.html"


def scrape_railway(max_pages: int = 2) -> list[dict]:
    print(f"\n{'='*60}")
    print(f"🔍 中国铁路人才招聘网")
    print(f"{'='*60}")

    jobs = []
    html = safe_get(RAILWAY_URL)
    if not html:
        print("  ⚠ 无法访问")
        return jobs

    soup = BeautifulSoup(html, "lxml")
    count = 0
    for a in soup.select("a[href]"):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or len(title) < 5:
            continue
        if not any(kw in title for kw in ["招聘", "铁路", "局", "公告"]):
            continue

        date_str = extract_date(title) or datetime.now().strftime("%Y-%m-%d")
        info = parse_title(title)

        jobs.append({
            "id": 0,
            "companyName": info.get("companyName") or title,
            "companyType": "央国企",
            "industry": "铁路/轨交",
            "recruitType": info.get("recruitType", "春招"),
            "targetYears": "2026届",
            "location": "",
            "positions": title,
            "status": "未投递",
            "updateTime": date_str,
            "deadline": "招满为止",
            "applyLink": urljoin(RAILWAY_URL, href),
            "noticeLink": urljoin(RAILWAY_URL, href),
            "examInfo": "",
            "companyScale": "大型（万人以上）",
            "notes": "来源: 铁路人才网",
        })
        count += 1

    print(f"  🎯 铁路 {count} 条")
    return jobs


# ============================================================
# 数据源 3: 山东省人社厅 — 事业单位
# ============================================================
RENSHETING_URL = "http://hrss.shandong.gov.cn/channels/ch00372/"


def scrape_rensheting(max_pages: int = 2) -> list[dict]:
    print(f"\n{'='*60}")
    print(f"🔍 山东省人社厅事业单位招聘")
    print(f"{'='*60}")

    jobs = []
    html = safe_get(RENSHETING_URL)
    if not html:
        print("  ⚠ 无法访问")
        return jobs

    soup = BeautifulSoup(html, "lxml")
    count = 0

    # 同国资委：td 布局中找 a 标签 + 相邻日期
    for a in soup.select("a[href]"):
        title = a.get("title") or a.get_text(strip=True)
        href = a.get("href", "")
        if not href or not title or len(title) < 8:
            continue
        if not any(kw in title for kw in ["招聘", "招录", "公开", "事业"]):
            continue

        # 找日期
        date_str = ""
        parent_td = a.find_parent("td")
        if parent_td:
            parent_tr = parent_td.find_parent("tr")
            if parent_tr:
                for td in parent_tr.find_all("td"):
                    dm = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", td.get_text(strip=True))
                    if dm:
                        date_str = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
                        break
        if not date_str:
            date_str = extract_date(title) or datetime.now().strftime("%Y-%m-%d")

        detail_url = urljoin(RENSHETING_URL, href)
        info = parse_title(title)
        unit = info.get("companyName") or title

        job = {
            "id": 0,
            "companyName": unit,
            "companyType": "事业单位",
            "industry": guess_industry(unit),
            "recruitType": "事业编",
            "targetYears": "2025届,2026届",
            "location": "山东",
            "positions": title,
            "status": "未投递",
            "updateTime": date_str,
            "deadline": "招满为止",
            "applyLink": "",
            "noticeLink": detail_url,
            "examInfo": "笔试+面试",
            "companyScale": "",
            "notes": "来源: 山东省人社厅",
        }

        # 详情页
        detail_html = safe_get(detail_url)
        if detail_html:
            fields = extract_detail_fields(detail_html)
            if fields["location"]:
                job["location"] = fields["location"]
            if fields["deadline"]:
                job["deadline"] = fields["deadline"]
            if fields["applyLink"]:
                job["applyLink"] = fields["applyLink"]
            polite_wait()

        jobs.append(job)
        count += 1

    print(f"  🎯 人社厅 {count} 条")
    return jobs


# ============================================================
# 合并去重
# ============================================================
def make_dedup_key(job: dict) -> str:
    """多字段复合去重键（参考 Auto-JobHunter 的 SQLite 去重逻辑）"""
    parts = [
        job.get("companyName", "").strip().lower(),
        job.get("positions", "")[:40].strip().lower(),
        job.get("recruitType", ""),
        # URL 域名部分做粗去重
        re.sub(r'https?://|www\.|/.*', '', job.get("noticeLink", "")),
    ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def merge_and_deduplicate(all_jobs: list[dict], cutoff_date: str = "2025-11-01") -> list[dict]:
    seen = set()
    unique = []

    for job in all_jobs:
        if job.get("updateTime", "") < cutoff_date:
            continue
        key = make_dedup_key(job)
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)

    unique.sort(key=lambda j: j.get("updateTime", ""), reverse=True)
    for i, job in enumerate(unique, 1):
        job["id"] = i

    return unique


def output_jobs_js(jobs: list[dict], filepath: Path):
    lines = [
        "// 校招/社招岗位数据 — 自动爬取生成",
        f"// 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"// 共 {len(jobs)} 条",
        "",
        "const JOBS = [",
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
    print(f"\n✅ 已写入 {filepath} ({len(jobs)} 条)")


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="校招岗位爬虫 v2")
    parser.add_argument("--source", choices=["sasac", "railway", "rensheting", "all"], default="all")
    parser.add_argument("--max-pages", type=int, default=3, help="每源最大翻页数")
    parser.add_argument("--details", type=int, default=15, help="每页抓取详情条数")
    args = parser.parse_args()

    all_jobs = []

    if args.source in ("sasac", "all"):
        all_jobs.extend(scrape_sasac(args.max_pages, args.details))

    if args.source in ("railway", "all"):
        all_jobs.extend(scrape_railway(args.max_pages))

    if args.source in ("rensheting", "all"):
        all_jobs.extend(scrape_rensheting(args.max_pages))

    if not all_jobs:
        print("\n⚠ 未抓取任何数据")
        return

    unique = merge_and_deduplicate(all_jobs)
    output_jobs_js(unique, OUTPUT_FILE)

    print(f"\n{'='*60}")
    print(f"📊 汇总: {len(unique)} 条, {len(set(j['companyName'] for j in unique))} 家企业/单位")
    industries = {}
    for j in unique:
        ind = j.get("industry", "未知")
        industries[ind] = industries.get(ind, 0) + 1
    for ind, cnt in sorted(industries.items(), key=lambda x: -x[1])[:10]:
        print(f"    {ind}: {cnt}")


if __name__ == "__main__":
    main()
