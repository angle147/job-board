#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
每日校招数据更新编排器
======================
协调所有爬虫按顺序执行，记录日志。
用法：
    python daily_update.py                 # 全量更新
    python daily_update.py --quick         # 仅校招（跳过国考和校对）

Windows 定时任务：
    任务计划程序 → 创建基本任务 → 每天 9:00 执行
    程序: D:\Python\python.exe
    参数: D:\hanako\job-board\daily_update.py
    起始于: D:\hanako\job-board
"""

import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

PYTHON = r"D:\Python\python.exe"
BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "daily_update.log"

# 强制 UTF-8 编码，避免 subprocess 管道使用 GBK 导致 emoji 报错
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

SCRAPERS = [
    {
        "name": "山东省国资委",
        "script": "scraper.py",
        "args": ["--source", "sasac", "--max-pages", "2", "--details", "10"],
        "daily": True,
    },
    {
        "name": "应届生求职网",
        "script": "scrape_yingjiesheng.py",
        "args": ["--max-pages", "1"],
        "daily": True,
    },
    {
        "name": "海投网交通类",
        "script": "scrape_haitou.py",
        "args": ["--max-pages", "3"],
        "daily": True,
    },
    {
        "name": "应届生数据校对",
        "script": "enrich.py",
        "args": ["--source", "yingjiesheng"],
        "daily": True,
    },
    {
        "name": "51job 爬虫采集",
        "script": "run_51job_collector.py",
        "args": [],
        "daily": True,
    },
    {
        "name": "51job 数据导出+清理",
        "script": "scrape_51job.py",
        "args": [],
        "daily": True,
    },
    {
        "name": "过期岗位清理",
        "script": "cleanup_expired_jobs.py",
        "args": [],
        "daily": True,
    },
    {
        "name": "国考交通职位",
        "script": "scrape_guokao.py",
        "args": ["--transport-only"],
        "daily": False,  # 仅周日执行
    },
    {
        "name": "微博校园招聘会",
        "script": "scrape_weibo.py",
        "args": ["--max-pages", "1"],
        "daily": True,
        "pipe_safe": False,  # 输出量大，不能用 PIPE（死锁风险）
    },
]


WEIBO_LOG = BASE_DIR / "weibo_output.log"


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_scraper(name: str, script: str, args: list[str], pipe_safe: bool = True) -> bool:
    cmd = [PYTHON, str(BASE_DIR / script)] + args
    log(f"▶ 开始: {name}")
    log(f"  命令: {' '.join(cmd)}")

    try:
        if pipe_safe:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=600, cwd=str(BASE_DIR),
                                    encoding="utf-8", errors="replace",
                                    env=ENV)
            stdout = result.stdout
        else:
            # 输出到文件，避免 PIPE 死锁
            with open(WEIBO_LOG, "w", encoding="utf-8") as log_f:
                result = subprocess.run(cmd, stdout=log_f, stderr=subprocess.STDOUT,
                                        timeout=600, cwd=str(BASE_DIR),
                                        env=ENV)
            # 读回最后几行
            with open(WEIBO_LOG, "r", encoding="utf-8") as log_f:
                stdout = log_f.read()

        # 输出最后几行到日志
        for line in stdout.strip().split("\n")[-5:]:
            if line.strip():
                log(f"  {line.strip()[:120]}")

        if result.returncode != 0:
            log(f"❌ {name} 失败 (code={result.returncode})")
            if result.stderr.strip():
                log(f"  错误: {result.stderr.strip()[:200]}")
            return False

        log(f"✅ {name} 完成")
        return True

    except subprocess.TimeoutExpired:
        log(f"⏰ {name} 超时（>10分钟），已跳过")
        return False
    except Exception as e:
        log(f"💥 {name} 异常: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="仅校招，跳过校对和国考")
    args = parser.parse_args()

    log("=" * 50)
    log("🚀 每日更新开始")
    log("=" * 50)

    today = datetime.now()
    is_sunday = today.weekday() == 6  # 周日

    success = 0
    fail = 0

    for scraper in SCRAPERS:
        # 非周日跳过国考
        if not scraper["daily"] and not is_sunday:
            log(f"⏭ 跳过: {scraper['name']}（仅周日执行）")
            continue

        # quick 模式跳过校对和国考
        if args.quick and not scraper["daily"]:
            continue
        if args.quick and scraper["name"] == "应届生数据校对":
            continue

        if run_scraper(scraper["name"], scraper["script"], scraper["args"],
                       pipe_safe=scraper.get("pipe_safe", True)):
            success += 1
        else:
            fail += 1

    log(f"📊 完成: {success} 成功, {fail} 失败, 共 {success + fail} 个任务")
    log("")


if __name__ == "__main__":
    main()
