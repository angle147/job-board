#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
山东港口集团 人才需求 抓取器
=============================================================
数据源：https://www.sd-port.com/talentDemandPage/index.html
说明：官网「人才需求」栏目，静态 HTML 列表。公告详情页格式 /talentDemandPage/日期/id.html。
注意：服务器对连续请求会断连，需重试 + 间隔。
输出：data/jobs_sdport.js（对齐 JOBS 格式）
"""
import urllib.request
import json
import re
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LIST_URL = "https://www.sd-port.com/talentDemandPage/index.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def fetch(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            return urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'ignore')
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 + i * 2)  # 退避重试
    return ''


def main():
    html = fetch(LIST_URL)
    # 条目：<a href="https://.../talentDemandPage/日期/id.html">标题</a>
    pattern = re.compile(
        r'<a[^>]*href="(https://www\.sd-port\.com/talentDemandPage/(\d{4}-\d{2}-\d{2})/[^"]+\.html)"[^>]*>([\s\S]*?)</a>',
        re.S
    )
    seen = set()
    jobs = []
    for m in pattern.finditer(html):
        link, date, title = m.group(1), m.group(2), re.sub(r'\s+', ' ', m.group(3)).strip()
        if not title or title in ('人力资源', '人才需求'):
            continue
        if link in seen:
            continue
        seen.add(link)
        years = ''
        y = re.findall(r'(20\d\d)年', title)
        if y:
            years = y[0] + '届'
        rtype = '校招' if ('校' in title or '应届' in title) else ('社招' if '社' in title else '招聘')
        jobs.append({
            'id': str(len(jobs) + 1),
            'companyName': '山东省港口集团',
            'companyType': '国企',
            'industry': '港口/物流',
            'recruitType': rtype,
            'targetYears': years,
            'location': '青岛/日照/烟台/潍坊',
            'positions': title,
            'status': '未投递',
            'updateTime': date,
            'deadline': '',
            'applyLink': link,
            'noticeLink': LIST_URL,
            'examInfo': '',
        })

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    header = (
        "// 山东港口集团 — 人才需求公告\n"
        f"// {now}\n"
        f"// {len(jobs)} 条\n\n"
        "const JOBS_SDPORT = "
    )
    (DATA_DIR / "jobs_sdport.js").write_text(header + json.dumps(jobs, ensure_ascii=False, indent=2) + ";\n", encoding='utf-8')
    print(f"✅ 山东港口公告抓取完成: {len(jobs)} 条 → data/jobs_sdport.js")


if __name__ == "__main__":
    main()
