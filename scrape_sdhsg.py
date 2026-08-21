#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
山东高速招聘平台 抓取器
=============================================================
数据源：https://www.sdhsg.com/zpapi/hr/announcement/weblist
说明：山东高速官网「招才引智」专栏的招聘公告接口（SSR 页面 + 公开 JSON 接口，无需登录）。
分类 recruitType：3=校园招聘（当前主要数据）；社招/内部/实习生的 recruitType 值随公告发布出现。
输出：data/jobs_sdhsg.js（对齐 JOBS 格式）
"""
import urllib.request
import json
import re
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
API = "https://www.sdhsg.com/zpapi/hr/announcement/weblist"
DETAIL_API = "https://www.sdhsg.com/zpapi/hr/announcement/queryIntro"
NOTICE_PAGE = "https://www.sdhsg.com/article/category/rlzyZcyz"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# recruitType -> 招聘类型
RTYPE = {1: '社招', 2: '社招', 3: '校招', 4: '内部招聘', 5: '实习生', 6: '社招'}


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': 'https://www.sdhsg.com/'})
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode('utf-8', 'ignore'))


def company_from(title):
    m = re.search(r'([\u4e00-\u9fa5]{2,20}?(?:集团有限公司|有限公司|公司))', title)
    return m.group(1) if m else '山东高速集团'


def main():
    jobs = []
    for rt, rtype in RTYPE.items():
        try:
            url = f"{API}?recruitType={rt}&page=1&limit=50&sidx=release_time&order=desc"
            data = fetch(url)
            if data.get('code') != 0:
                continue
            for it in data.get('page', {}).get('list') or []:
                title = it.get('title', '').strip()
                release = it.get('releaseTime', '')[:10]
                years = ''
                y = re.findall(r'(20\d\d)年', title)
                if y:
                    years = y[0] + '届'
                jobs.append({
                    'id': str(it.get('id')),
                    'companyName': company_from(title),
                    'companyType': '国企',
                    'industry': '交通',
                    'recruitType': rtype,
                    'targetYears': years,
                    'location': '',
                    'positions': title,
                    'status': '未投递',
                    'updateTime': release,
                    'deadline': '',
                    'applyLink': 'https://zhaopin.sdhsg.com/',
                    'noticeLink': NOTICE_PAGE,
                    'examInfo': '',
                })
        except Exception as e:
            print(f"[warn] recruitType={rt} 抓取失败: {e}")

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    header = (
        "// 山东高速招聘平台 — 招聘公告\n"
        f"// {now}\n"
        f"// {len(jobs)} 条\n\n"
        "const JOBS_SDHSG = "
    )
    body = json.dumps(jobs, ensure_ascii=False, indent=2)
    (DATA_DIR / "jobs_sdhsg.js").write_text(header + body + ";\n", encoding='utf-8')
    print(f"✅ 山东高速公告抓取完成: {len(jobs)} 条 → data/jobs_sdhsg.js")


if __name__ == "__main__":
    main()
