#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据二次校对脚本 — 从详情页补全职位信息
=========================================
1. 遍历 jobs_yingjiesheng.js，逐条抓取详情页
2. 提取：精确届数、详细岗位描述、来源单位
3. 更新 targetYears、positions、notes 字段
4. 输出校对后的数据

用法：
    python enrich.py                        # 校对全部数据
    python enrich.py --source yingjiesheng  # 只校对应届生数据
    python enrich.py --limit 20            # 只处理前 20 条（测试）
"""

import re
import json
import time
import random
import argparse
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

SOURCES = {
    "yingjiesheng": DATA_DIR / "jobs_yingjiesheng.js",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
]
REQUEST_TIMEOUT = 10
REQUEST_DELAY = 0.5

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
    for attempt in range(2):
        try:
            session.headers["User-Agent"] = random.choice(USER_AGENTS)
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.encoding = resp.apparent_encoding or "utf-8"
            if resp.status_code == 200:
                return resp.text
        except Exception:
            time.sleep(1)
    return None


def polite_wait():
    time.sleep(REQUEST_DELAY + random.random() * 0.3)


# ============================================================
# 数据加载
# ============================================================
def load_js_data(filepath: Path, varname: str) -> list[dict]:
    """加载 JS 数据文件"""
    if not filepath.exists():
        return []
    content = filepath.read_text(encoding="utf-8")

    # 提取数组
    start = content.find(f"{varname} = [")
    if start < 0:
        return []
    start = content.find("[", start)
    # 找到匹配的 ]
    depth = 0
    end = start
    for i in range(start, len(content)):
        if content[i] == "[":
            depth += 1
        elif content[i] == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    js = content[start:end]

    # 手动解析JS对象（不用json模块，避免格式问题）
    jobs = []
    # 按 }, { 分割对象
    # 先去掉首尾的 [ ]
    inner = js[1:-1].strip()
    if not inner:
        return []

    # 找到每个 {...} 对象
    obj_starts = []
    depth = 0
    for i, ch in enumerate(inner):
        if ch == "{":
            if depth == 0:
                obj_starts.append(i)
            depth += 1
        elif ch == "}":
            depth -= 1

    for start_idx in obj_starts:
        # 找到对应的 }
        d = 0
        end_idx = start_idx
        for j in range(start_idx, len(inner)):
            if inner[j] == "{":
                d += 1
            elif inner[j] == "}":
                d -= 1
                if d == 0:
                    end_idx = j + 1
                    break
        obj_text = inner[start_idx:end_idx]
        job = parse_js_object(obj_text)
        if job:
            jobs.append(job)

    return jobs


def parse_js_object(text: str) -> dict | None:
    """手动解析 JS 对象字面量"""
    result = {}
    # 匹配 key: value 对
    # key是字母/下划线，value可能是字符串或数字
    pairs = re.findall(
        r'(\w+):\s*("(?:[^"\\]|\\.)*"|\d+|true|false|null)',
        text
    )
    for key, raw_val in pairs:
        if raw_val.startswith('"'):
            val = raw_val[1:-1]
            # 处理转义
            val = val.replace('\\"', '"').replace('\\\\', '\\')
        elif raw_val == "true":
            val = True
        elif raw_val == "false":
            val = False
        elif raw_val == "null":
            val = None
        else:
            try:
                val = int(raw_val)
            except ValueError:
                val = raw_val
        result[key] = val
    return result if result else None


def save_js_data(jobs: list[dict], filepath: Path, varname: str):
    """保存为 JS 数据文件"""
    lines = [
        "// 应届生求职网 — 自动爬取 + 二次校对",
        f"// 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"// 共 {len(jobs)} 条",
        "",
        f"const {varname} = [",
    ]
    for i, job in enumerate(jobs):
        lines.append("  {")
        for key in ["id", "companyName", "companyType", "industry", "recruitType",
                     "targetYears", "location", "positions", "status",
                     "updateTime", "deadline", "applyLink", "noticeLink",
                     "examInfo", "companyScale", "notes"]:
            val = job.get(key, "")
            if isinstance(val, str):
                val = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
                lines.append(f'    {key}: "{val}",')
            else:
                lines.append(f'    {key}: {val},')
        lines[-1] = lines[-1].rstrip(",")
        lines.append("  }," if i < len(jobs) - 1 else "  }")
    lines.append("];\n")
    filepath.write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# 详情页解析
# ============================================================
def enrich_from_detail(job: dict) -> dict:
    """
    从详情页提取补充信息，返回更新后的 job
    """
    detail_url = job.get("applyLink") or job.get("noticeLink", "")
    if "yingjiesheng.com/job-" not in detail_url:
        return job

    html = safe_get(detail_url)
    if not html:
        return job

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n", strip=True)

    changes = []

    # 1. 提取精确届数
    year_map = {
        "2027届": ["2027届", "27届", "2027年毕业", "2027年应届"],
        "2026届": ["2026届", "26届", "2026年毕业", "2026年应届"],
        "2025届": ["2025届", "25届", "2025年毕业", "2025年应届"],
    }
    found_years = set()
    for year_label, patterns in year_map.items():
        for pat in patterns:
            if pat in text:
                found_years.add(year_label)
                break
    if found_years:
        new_target = ",".join(sorted(found_years))
        old_target = job.get("targetYears", "")
        if new_target != old_target:
            changes.append(f"targetYears: {old_target} → {new_target}")
            job["targetYears"] = new_target

    # 2. 提取招聘类型（实习优先，只改一次）
    if "实习生" in text or "实习招聘" in text or "暑期实习" in text:
        if job.get("recruitType", "") != "实习":
            changes.append(f"recruitType: {job.get('recruitType','')} → 实习")
            job["recruitType"] = "实习"
    elif "校园招聘" in text or "校招" in text or "毕业生" in text:
        if job.get("recruitType", "") not in ("实习",):
            changes.append(f"recruitType: {job.get('recruitType','')} → 春招")
            job["recruitType"] = "春招"

    # 3. 提取详细岗位描述（截取职位描述部分）
    pos_desc = ""
    for marker in ["职位描述", "岗位描述", "工作内容", "岗位职责", "任职要求"]:
        idx = text.find(marker)
        if idx > 0:
            desc = text[idx:idx + 500]
            # 截取到下一个段落标记
            cutoff = re.search(r'\n(?:公司|联系|投递|来源|发布)', desc)
            if cutoff:
                desc = desc[:cutoff.start()]
            pos_desc = desc.strip()[:300]
            break

    if pos_desc and len(pos_desc) > 20:
        old_pos = job.get("positions", "")
        # 如果原岗位名太短，用描述补充
        if len(old_pos) < 15 and pos_desc:
            short_desc = pos_desc.split("\n")[0].strip()[:80]
            if short_desc and short_desc not in old_pos:
                changes.append(f"positions enriched from detail")
                job["positions"] = short_desc

    # 4. 提取来源单位
    source_match = re.search(r'信息来源[：:]\s*(.+?)(?:\n|。|$)', text)
    if source_match:
        source = source_match.group(1).strip()
        if source and source not in job.get("notes", ""):
            job["notes"] = job.get("notes", "") + f" | 来源: {source}"

    # 5. 提取邮箱/联系方式（截断的不完整）
    email_match = re.search(r'[\w.]+@[\w.]+', text)
    if email_match:
        email = email_match.group(0)
        if len(email) > 5 and email not in job.get("notes", ""):
            job["notes"] = job.get("notes", "") + f" | 📧 {email}"

    if changes:
        print(f"    📝 {job['companyName'][:20]}: {', '.join(changes)}")

    return job


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="数据二次校对")
    parser.add_argument("--source", choices=["yingjiesheng"], default="yingjiesheng")
    parser.add_argument("--limit", type=int, default=0, help="限制处理条数（0=全部）")
    args = parser.parse_args()

    source_key = args.source
    filepath = SOURCES[source_key]
    varname = "JOBS_YINGJIESHENG"

    print(f"{'='*60}")
    print(f"🔍 二次校对: {source_key} ({filepath.name})")
    print(f"{'='*60}\n")

    jobs = load_js_data(filepath, varname)
    print(f"📂 加载 {len(jobs)} 条数据")

    if len(jobs) == 0:
        print("⚠ 加载 0 条数据，跳过（保留原文件）")
        return

    if args.limit > 0:
        enrich_jobs = jobs[:args.limit]
        print(f"🔢 限制处理前 {args.limit} 条")
    else:
        enrich_jobs = jobs[:]

    enriched = 0
    processed = 0
    for i, job in enumerate(enrich_jobs):
        if "yingjiesheng.com/job-" not in str(job.get("applyLink", "")):
            continue
        processed += 1
        print(f"\n  [{i+1}/{len(enrich_jobs)}] {job['companyName'][:30]}")
        old_data = {k: v for k, v in job.items()}
        enrich_from_detail(job)
        if any(job.get(k) != old_data.get(k) for k in job):
            enriched += 1
        polite_wait()

    save_js_data(jobs, filepath, varname)

    print(f"\n{'='*60}")
    print(f"📊 校对完成")
    print(f"{'='*60}")
    print(f"  处理: {processed} 条")
    print(f"  更新: {enriched} 条")
    print(f"  输出: {filepath}")


if __name__ == "__main__":
    main()
