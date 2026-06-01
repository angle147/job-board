#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
51job 采集调度器
================
每日定时调用 Auto-JobHunter 的 51job 采集器，抓取最新交通/物流/仓储职位。

用法：
    python run_51job_collector.py           # 抓第 1 页
    python run_51job_collector.py --pages 3  # 抓前 3 页
"""

import subprocess
import sys
import os
from pathlib import Path

PYTHON = r"D:\Python\python.exe"
AHJ_DIR = Path(r"D:\hanako\Auto-JobHunter-main")
COLLECTOR_SCRIPT = AHJ_DIR / "51job_scraper" / "51job_collector.py"

ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

# 搜索关键词和城市
KEYWORDS = "交通 物流 仓储"
CITY = "济南"


def run_collector(page: int) -> bool:
    cmd = [
        PYTHON,
        str(COLLECTOR_SCRIPT),
        "--page", str(page),
        "--keyword", KEYWORDS,
        "--city", CITY,
    ]
    print(f"▶ 正在抓取第 {page} 页: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(COLLECTOR_SCRIPT.parent),
                           capture_output=True, text=True,
                           timeout=900,  # 15 分钟超时
                           encoding="utf-8", errors="replace",
                           env=ENV)

    # 输出最后 5 行
    lines = result.stdout.strip().split("\n")
    for line in lines[-5:]:
        print(f"  {line.strip()[:150]}")

    if result.returncode != 0:
        print(f"❌ 第 {page} 页失败 (code={result.returncode})")
        if result.stderr.strip():
            print(f"  错误: {result.stderr.strip()[:300]}")
        return False

    return True


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=1, help="抓取页数")
    args = parser.parse_args()

    success = 0
    for page in range(1, args.pages + 1):
        if run_collector(page):
            success += 1

    print(f"\n📊 51job 采集完成: {success}/{args.pages} 页成功")


if __name__ == "__main__":
    main()
