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
LOCK_FILE = BASE_DIR / ".daily_update.lock"

# 强制 UTF-8 编码，避免 subprocess 管道使用 GBK 导致 emoji 报错
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

SCRAPERS = [
    {
        "name": "山东省国资委",
        "script": "scraper.py",
        "args": ["--source", "sasac", "--max-pages", "2", "--details", "10"],
        "daily": True,
        "timeout": 180,
    },
    {
        "name": "央企招聘公告",
        "script": "scrape_mohrss_qyzp.py",
        "args": [],
        "daily": True,
        "timeout": 60,
    },
    {
        "name": "山东高速招聘公告",
        "script": "scrape_sdhsg.py",
        "args": [],
        "daily": True,
        "timeout": 90,
    },
    {
        "name": "山东港口人才需求",
        "script": "scrape_sdport.py",
        "args": [],
        "daily": True,
        "timeout": 90,
    },
    {
        "name": "应届生求职网",
        "script": "scrape_yingjiesheng.py",
        "args": ["--max-pages", "1"],
        "daily": True,
        "timeout": 180,
    },
    {
        "name": "海投网交通类",
        "script": "scrape_haitou.py",
        "args": ["--max-pages", "3"],
        "daily": True,
        "timeout": 180,
    },
    {
        "name": "应届生数据校对",
        "script": "enrich.py",
        "args": ["--source", "yingjiesheng"],
        "daily": True,
        "timeout": 300,
    },
    {
        "name": "51job 爬虫采集",
        "script": "run_51job_collector.py",
        "args": [],
        "daily": True,
        "enabled": False,
        "timeout": 180,
    },
    {
        "name": "51job 数据导出+清理",
        "script": "scrape_51job.py",
        "args": [],
        "daily": True,
        "enabled": False,
        "timeout": 60,
    },
    {
        "name": "过期岗位清理",
        "script": "cleanup_expired_jobs.py",
        "args": [],
        "daily": True,
        "timeout": 60,
    },
    {
        "name": "国考交通职位",
        "script": "scrape_guokao.py",
        "args": ["--transport-only"],
        "daily": False,  # 仅周日执行
        "timeout": 300,
    },
    {
        "name": "微博校园招聘会",
        "script": "scrape_weibo.py",
        "args": ["--max-pages", "1"],
        "daily": True,
        "enabled": False,
        "pipe_safe": False,
        "timeout": 120,  # 微博容易超时，2分钟为限
    },
]


WEIBO_LOG = BASE_DIR / "weibo_output.log"


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_scraper(name: str, script: str, args: list[str], pipe_safe: bool = True, timeout: int = 180) -> bool:
    cmd = [PYTHON, str(BASE_DIR / script)] + args
    log(f"▶ 开始: {name}")
    log(f"  命令: {' '.join(cmd)}")

    try:
        if pipe_safe:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=timeout, cwd=str(BASE_DIR),
                                    encoding="utf-8", errors="replace",
                                    env=ENV)
            stdout = result.stdout
        else:
            # 输出到文件，避免 PIPE 死锁
            with open(WEIBO_LOG, "w", encoding="utf-8") as log_f:
                result = subprocess.run(cmd, stdout=log_f, stderr=subprocess.STDOUT,
                                        timeout=timeout, cwd=str(BASE_DIR),
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
        log(f"⏰ {name} 超时（>{timeout // 60}分钟），已跳过")
        return False
    except Exception as e:
        log(f"💥 {name} 异常: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="仅校招，跳过校对和国考")
    args = parser.parse_args()

    # 锁文件：防止重复运行，同时记录 PID
    if LOCK_FILE.exists():
        try:
            old_content = LOCK_FILE.read_text().strip()
            # 检查旧进程是否还活着
            if ':' in old_content:
                old_pid = int(old_content.split(':')[-1])
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x0400, False, old_pid)  # PROCESS_QUERY_INFORMATION
                if handle:
                    kernel32.CloseHandle(handle)
                    lock_age = datetime.now().timestamp() - LOCK_FILE.stat().st_mtime
                    if lock_age < 1800:
                        log("⏭ 已有运行中的更新任务，跳过")
                        return
            # 进程已死但锁还在
        except (ValueError, OSError):
            pass
        log("⚠️ 发现过期锁文件（进程已死或>30分钟），强制继续")
    LOCK_FILE.write_text(f"{datetime.now()}:{os.getpid()}")

    try:
        _run_pipeline(args)
    finally:
        LOCK_FILE.unlink(missing_ok=True)


def _run_pipeline(args):
    log("=" * 50)
    log("🚀 每日更新开始")
    log("=" * 50)

    today = datetime.now()
    is_sunday = today.weekday() == 6  # 周日

    success = 0
    fail = 0

    for scraper in SCRAPERS:
        # 禁用的数据源（enabled=False）直接跳过
        if not scraper.get("enabled", True):
            log(f"⏭ 跳过: {scraper['name']}（已禁用）")
            continue

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
                       pipe_safe=scraper.get("pipe_safe", True),
                       timeout=scraper.get("timeout", 180)):
            success += 1
        else:
            fail += 1

        # 每完成一个爬虫就更新摘要（即使后续失败也有数据可用）
        _write_incremental_summary()

    log(f"📊 完成: {success} 成功, {fail} 失败, 共 {success + fail} 个任务")

    # 自动同步到 GitHub Pages
    log("> 开始: GitHub 同步")
    try:
        subprocess.run(
            ["git", "add", "data/", "index.html"],
            capture_output=True, text=True,
            cwd=str(BASE_DIR), env=ENV,
            encoding="utf-8", errors="replace"
        )
        commit_result = subprocess.run(
            ["git", "commit", "-m", f"📊 每日更新 {datetime.now().strftime('%Y-%m-%d')}"],
            capture_output=True, text=True,
            cwd=str(BASE_DIR), env=ENV,
            encoding="utf-8", errors="replace"
        )
        if commit_result.returncode == 0 or "nothing to commit" in commit_result.stdout + commit_result.stderr:
            push_result = subprocess.run(
                ["git", "push", "origin", "main"],
                capture_output=True, text=True,
                timeout=120, cwd=str(BASE_DIR), env=ENV,
                encoding="utf-8", errors="replace"
            )
            if push_result.returncode == 0:
                log("✅ GitHub 同步完成 → https://angle147.github.io/job-board/")
            else:
                log(f"⚠️ GitHub push 失败: {push_result.stderr.strip()[:120]}")
        else:
            log(f"⚠️ Git commit 异常: {commit_result.stderr.strip()[:120]}")
    except Exception as e:
        log(f"⚠️ GitHub 同步异常: {e}")

    log("")

    # 自动同步到 GitHub Pages（增量摘要已在每个爬虫后写入）
    # 最终摘要已在增量写入中完成，这里做最后一次确认
    _write_incremental_summary()


def _build_summary(base_dir, today):
    """统计各数据源的条目数，生成推送文案"""
    import json, re
    from pathlib import Path
    data_dir = base_dir / "data"

    def count_js(path):
        if not path.exists():
            return 0
        text = path.read_text(encoding="utf-8")
        # 数数组里的 { 数量
        return text.count('\n  {') 

    lines = []
    lines.append(f"📬 校招数据已更新 ({today.strftime('%m-%d')})")
    lines.append("")

    # 校招/社招
    lines.append("🏢 校招/社招")
    lines.append(f"  国资委: {count_js(data_dir / 'jobs.js')} 条")
    lines.append(f"  应届生求职网: {count_js(data_dir / 'jobs_yingjiesheng.js')} 条")
    lines.append(f"  海投网: {count_js(data_dir / 'jobs_haitou.js')} 条")
    lines.append(f"  51job: {count_js(data_dir / 'jobs_51job.js')} 条")
    lines.append(f"  手动维护: {count_js(data_dir / 'jobs_manual.js')} 条")
    lines.append("")

    # 线下招聘会
    uni_count = count_js(data_dir / 'university_events.js')
    weibo_count = count_js(data_dir / 'weibo_events.js')
    lines.append("🎓 线下招聘会")
    lines.append(f"  高校就业平台: {uni_count} 场")
    lines.append(f"  微博招聘会: {weibo_count} 场")
    lines.append("")

    # 国考（仅周日）
    if today.weekday() == 6:
        lines.append("🏛 公务员/事业单位")
        lines.append(f"  国考交通职位: {count_js(data_dir / 'exams.js')} 条")
        lines.append("")

    # 过期清理统计（从日志最后一段提取）
    log_file = base_dir / "daily_update.log"
    if log_file.exists():
        log_text = log_file.read_text(encoding="utf-8")
        # 找最后一次过期清理结果
        m = re.search(r'总计: 删除 (\d+) 条, 保留 (\d+) 条', log_text)
        if m:
            lines.append(f"🧹 过期清理: 删 {m.group(1)} 条, 保留 {m.group(2)} 条")

    lines.append("")
    lines.append("📱 https://angle147.github.io/job-board/")

    return '\n'.join(lines)


SUMMARY_FILE = BASE_DIR / ".daily_summary.txt"

def _write_incremental_summary():
    """每完成一个爬虫后更新摘要文件，确保 pipeline 被中断时也有数据"""
    summary = _build_summary(BASE_DIR, datetime.now())
    SUMMARY_FILE.write_text(summary, encoding="utf-8")


if __name__ == "__main__":
    main()
