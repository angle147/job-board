#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
51job 数据导出器
========================
从 Auto-JobHunter 的 SQLite 数据库中读取 51job 采集数据，
输出为 job-board 兼容的 JS 文件格式，并执行过期清理。

用法：
    python scrape_51job.py                    # 导出 + 清理
    python scrape_51job.py --cleanup-only     # 仅清理过期
    python scrape_51job.py --export-only      # 仅导出
    python scrape_51job.py --max-age 30       # 保留最近 N 天
"""

import json
import sqlite3
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_FILE = DATA_DIR / "jobs_51job.js"

# 51job SQLite 数据库路径
DB_PATH = Path(r"D:\hanako\Auto-JobHunter-main\data\job_hunter.db")

# 默认保留天数（30 天前的数据视为过期）
DEFAULT_MAX_AGE = 30


def db_connect():
    """连接 SQLite 数据库"""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"数据库不存在: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def export_to_js(conn, max_age: int = DEFAULT_MAX_AGE) -> int:
    """从 raw_jobs 导出 51job 数据到 JS 文件"""
    cutoff = (datetime.now() - timedelta(days=max_age)).strftime("%Y-%m-%d")

    cursor = conn.execute("""
        SELECT job_title, company_name, salary, work_address,
               city, industry, education_req, experience_req,
               welfare_tags, company_size, publish_date,
               job_link, hr_activity
        FROM raw_jobs
        WHERE platform = '51job'
          AND publish_date >= ?
        ORDER BY publish_date DESC
    """, (cutoff,))

    jobs = []
    for i, row in enumerate(cursor, 1):
        jobs.append({
            "id": f"51job_{i}",
            "companyName": row["company_name"] or "未知公司",
            "companyType": "企业",
            "industry": row["industry"] or "交通/物流",
            "recruitType": "社招",
            "targetYears": "不限",
            "location": row["work_address"] or row["city"] or "",
            "positions": row["job_title"] or "",
            "status": "未投递",
            "updateTime": row["publish_date"] or "",
            "deadline": "招满为止",
            "applyLink": row["job_link"] or "",
            "noticeLink": row["job_link"] or "",
            "examInfo": "",
            "companyScale": row["company_size"] or "",
            "salary": row["salary"] or "",
            "notes": f"来源: 51job | {row['education_req'] or ''} | {row['experience_req'] or ''}"
        })

    js_content = f"""// 51job — 交通/物流/仓储行业
// {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
// 共 {len(jobs)} 条（最近 {max_age} 天）

const JOBS_51JOB = {json.dumps(jobs, ensure_ascii=False, indent=2)};
"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(js_content)

    return len(jobs)


def cleanup_expired(conn, max_age: int = DEFAULT_MAX_AGE) -> int:
    """清理超过 max_age 天的 51job 过期数据（保守策略：仅删明确超期的，保留空日期）"""
    cutoff = (datetime.now() - timedelta(days=max_age)).strftime("%Y-%m-%d")

    cursor = conn.execute("""
        DELETE FROM raw_jobs
        WHERE platform = '51job'
          AND publish_date < ?
          AND publish_date IS NOT NULL
          AND publish_date != ''
    """, (cutoff,))

    conn.commit()
    deleted = cursor.rowcount
    return deleted


def main():
    parser = argparse.ArgumentParser(description="51job 数据导出与清理")
    parser.add_argument("--max-age", type=int, default=DEFAULT_MAX_AGE,
                        help=f"保留最近 N 天数据（默认 {DEFAULT_MAX_AGE}）")
    parser.add_argument("--cleanup-only", action="store_true", help="仅清理过期数据")
    parser.add_argument("--export-only", action="store_true", help="仅导出数据")

    args = parser.parse_args()

    conn = db_connect()

    try:
        if not args.cleanup_only:
            count = export_to_js(conn, args.max_age)
            print(f"✅ 51job 数据导出完成: {count} 条 → {OUTPUT_FILE}")

        if not args.export_only:
            deleted = cleanup_expired(conn, args.max_age)
            print(f"🧹 51job 过期清理完成: 删除 {deleted} 条（>{args.max_age}天前）")

        if args.cleanup_only and args.export_only:
            # 不可能同时出现，但如果出现就都做
            pass

    finally:
        conn.close()


if __name__ == "__main__":
    main()
