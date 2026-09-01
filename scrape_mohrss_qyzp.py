#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中国公共招聘网 · 中央企业招聘应届高校毕业生信息公开 抓取器
=============================================================
数据源：http://job.mohrss.gov.cn/qyzp/index.jhtml
说明：纯静态列表页，每条为「央企名 + 招聘标题 + 日期」，链接指向微信公众号文章。
粒度：招聘公告（非具体岗位），适合作为"央企招聘公告"索引。
输出：data/jobs_qyzp.js（对齐 JOBS 格式）
"""
import urllib.request
import re
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
BASE_URL = "http://job.mohrss.gov.cn/qyzp/index.jhtml"
PAGES = 3  # 抓前 3 页（index + index_2 + index_3）

# 公司名提取：标题开头的央企名（集团/公司/中心/研究院/大学/院 等结尾）
COMPANY_RE = re.compile(r'^([\u4e00-\u9fa5]{2,15}?(?:集团|公司|中心|研究院|大学|学院|总院|所))')


def fetch_page(page: int) -> str:
    url = BASE_URL if page == 1 else f"http://job.mohrss.gov.cn/qyzp/index_{page}.jhtml"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    return urllib.request.urlopen(req, timeout=20).read().decode('utf-8', 'ignore')


def parse_items(html: str):
    """解析 <li><a href="微信链接">标题</a><span>日期</span></li>"""
    items = []
    pattern = re.compile(
        r'<li><a href="([^"]+)"[^>]*>([^<]+)</a>\s*<span[^>]*>([\d\-]+)</span>',
        re.S
    )
    for m in pattern.finditer(html):
        link, title, date = m.group(1), m.group(2).strip(), m.group(3).strip()
        if 'mp.weixin.qq.com' not in link:
            continue
        items.append({'title': title, 'date': date, 'link': link})
    return items


def classify(title: str):
    """从标题提取公司名、招聘类型、目标届次"""
    company = ''
    m = COMPANY_RE.match(title)
    if m:
        company = m.group(1)
    else:
        company = title[:8]

    recruit_type = '校招'
    if '社招' in title or '社会招聘' in title or '公开招聘' in title:
        recruit_type = '社招'
    elif '校招' in title or '校园招聘' in title or '校园' in title:
        recruit_type = '校招'

    years = ''
    y = re.findall(r'(20\d\d)届', title)
    if y:
        years = ','.join(sorted(set(y)))

    return company, recruit_type, years


def main():
    all_items = []
    failed = False
    for page in range(1, PAGES + 1):
        try:
            html = fetch_page(page)
            items = parse_items(html)
            if not items and page == 1:
                print("[error] 首页可达但未识别央企招聘列表，保留上次成功数据")
                failed = True
                break
            if not items:
                break
            all_items.extend(items)
        except Exception as e:
            print(f"[warn] 第 {page} 页抓取失败: {e}")
            failed = True
            break

    if failed:
        raise SystemExit(1)

    # 去重（按链接）
    seen = set()
    unique = []
    for it in all_items:
        if it['link'] not in seen:
            seen.add(it['link'])
            unique.append(it)

    jobs = []
    for i, it in enumerate(unique, 1):
        company, recruit_type, years = classify(it['title'])
        jobs.append({
            'id': str(i),
            'companyName': company,
            'companyType': '央国企',
            'industry': '综合',
            'recruitType': recruit_type,
            'targetYears': years,
            'location': '全国',
            'positions': it['title'],
            'status': '未投递',
            'updateTime': it['date'],
            'deadline': '',
            'applyLink': it['link'],
            # 人社部央企招聘栏目是官方发现证据，公众号文章保留为申请/详情入口。
            'noticeLink': BASE_URL,
            'examInfo': '',
        })

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    header = (
        "// 中国公共招聘网 — 中央企业招聘公告\n"
        f"// {now}\n"
        f"// {len(jobs)} 条\n\n"
        "const JOBS_QYZP = "
    )
    body = json.dumps(jobs, ensure_ascii=False, indent=2)
    out = header + body + ";\n"
    (DATA_DIR / "jobs_qyzp.js").write_text(out, encoding='utf-8')
    print(f"✅ 央企公告抓取完成: {len(jobs)} 条 → data/jobs_qyzp.js")


if __name__ == "__main__":
    main()
