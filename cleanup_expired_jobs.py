#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
过期岗位清理器
==============
基于 deadline 字段和 notes 中的日期，自动清理已过期岗位。

策略：
1. deadline 含明确日期（YYYY-MM-DD）：已过期则删
2. deadline 为「招满为止」：从 notes/updateTime 提取日期，>60 天则删
3. 51job: 从 updateTime 判断，>60 天则删

用法：
    python cleanup_expired_jobs.py              # 清理所有源
    python cleanup_expired_jobs.py --dry-run    # 预览，不实际修改
    python cleanup_expired_jobs.py --max-age 90 # 自定义保留天数
"""

import re
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# 默认：60 天前的视为过期
DEFAULT_MAX_AGE = 60

# 需要处理的 JS 数据文件
DATA_FILES = [
    "jobs.js",              # 国资委
    "jobs_yingjiesheng.js", # 应届生
    "jobs_haitou.js",       # 海投
    "jobs_51job.js",        # 51job
    "jobs_manual.js",       # 手动（只清理明确过期的）
]

# 不清理手动明确日期的：manual 的 deadline 是用户自己维护的，只删明确过期的
# 但默认也都清理


def extract_date_from_text(text: str) -> str | None:
    """从文本中提取日期，支持多种格式"""
    # 格式: 2026-04-01 或 2026.04.01 或 2026/04/01
    patterns = [
        r'(\d{4}-\d{2}-\d{2})',
        r'(\d{4}\.\d{2}\.\d{2})',
        r'(\d{4}/\d{2}/\d{2})',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            date_str = m.group(1).replace(".", "-").replace("/", "-")
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
                return date_str
            except ValueError:
                continue
    return None


def is_expired_deadline(deadline: str, today: datetime) -> bool:
    """检查 deadline 是否为已过期的明确日期"""
    if not deadline or deadline == "招满为止":
        return False
    date = extract_date_from_text(deadline)
    if date:
        d = datetime.strptime(date, "%Y-%m-%d")
        return d < today
    return False


def is_too_old(job: dict, max_age: int, today: datetime) -> bool:
    """检查岗位是否过旧（无明确 deadline 时用）"""
    cutoff = today - timedelta(days=max_age)

    # 1. 从 notes 提取日期
    notes = job.get("notes", "")
    date = extract_date_from_text(notes)
    if date and datetime.strptime(date, "%Y-%m-%d") <= cutoff:
        return True

    # 2. 从 updateTime 判断
    update = job.get("updateTime", "")
    date = extract_date_from_text(update)
    if date and datetime.strptime(date, "%Y-%m-%d") <= cutoff:
        return True

    return False


def cleanup_file(filepath: Path, max_age: int, dry_run: bool) -> tuple[int, int]:
    """
    清理单个 JS 文件
    返回: (删除数, 保留数)
    """
    content = filepath.read_text(encoding="utf-8")

    # 提取 JS 数组内容
    # 查找 const VARNAME = [ ... ];
    array_start = content.find("= [")
    if array_start == -1:
        print(f"  ⚠️ {filepath.name}: 未找到数组")
        return (0, 0, 0, 0)
    
    json_start = array_start + 2  # 跳过 "= ["
    # 找结尾 ]; —— 从末尾反向搜索更可靠
    array_end = content.rfind("];")
    if array_end == -1:
        print(f"  ⚠️ {filepath.name}: 未找到数组结尾")
        return (0, 0, 0, 0)
    
    json_text = content[json_start:array_end + 1]  # 包括 ] 不包括 ;
    
    # JS 对象可能有未加引号的键名（如 id: 1），替换为 JSON 兼容格式
    json_text = re.sub(r'(\{|,)\s*(\w+)\s*:', r'\1"\2":', json_text)

    try:
        jobs = json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"  ⚠️ {filepath.name}: JSON 解析失败 ({e}), 前100字: {json_text[:100]}")
        return (0, 0, 0, 0)

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    kept = []
    deleted = []
    expire_date_deleted = 0
    old_deleted = 0

    for job in jobs:
        deadline = job.get("deadline", "")

        if is_expired_deadline(deadline, today):
            deleted.append(job)
            expire_date_deleted += 1
            continue

        if deadline == "招满为止" or not deadline:
            if is_too_old(job, max_age, today):
                deleted.append(job)
                old_deleted += 1
                continue

        kept.append(job)

    if not dry_run and deleted:
        # 重建 JS 文件
        header_lines = []
        for line in content.split("\n"):
            if line.strip().startswith("const ") and "=" in line:
                var_name = line.split("const ")[1].split(" ")[0]
                break
        else:
            var_name = "DATA"

        # 提取头部注释
        comment_lines = []
        for line in content.split("\n"):
            if line.strip().startswith("//") or line.strip() == "":
                comment_lines.append(line)
            else:
                break

        new_json = json.dumps(kept, ensure_ascii=False, indent=2)
        # 恢复 JS 格式：去掉键名的引号（"key": → key:）
        new_json = re.sub(r'"(\w+)":', r'\1:', new_json)

        new_content = (
            "\n".join(comment_lines).rstrip("\n")
            + "\n\n"
            + f"const {var_name} = {new_json};\n"
        )
        filepath.write_text(new_content, encoding="utf-8")

    return (len(deleted), len(kept), expire_date_deleted, old_deleted)


def main():
    parser = argparse.ArgumentParser(description="过期岗位清理器")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不修改文件")
    parser.add_argument("--max-age", type=int, default=DEFAULT_MAX_AGE,
                        help=f"「招满为止」岗位保留天数（默认 {DEFAULT_MAX_AGE}）")
    args = parser.parse_args()

    today = datetime.now()
    print(f"🧹 过期岗位清理 {'[预览模式]' if args.dry_run else ''}")
    print(f"   策略: 明确截止日期已过 → 删除 | 「招满为止」>" + 
          f"{args.max_age}天 → 删除")
    print(f"   今日: {today.strftime('%Y-%m-%d')}")
    print()

    total_deleted = 0
    total_kept = 0

    for filename in DATA_FILES:
        filepath = DATA_DIR / filename
        if not filepath.exists():
            print(f"  ⏭ {filename}: 文件不存在")
            continue

        result = cleanup_file(filepath, args.max_age, args.dry_run)
        deleted, kept, ed, od = result
        total_deleted += deleted
        total_kept += kept

        if deleted > 0:
            print(f"  🗑 {filename}: 删 {deleted} 条 "
                  f"(截止日期已过: {ed}, 超{args.max_age}天: {od}) → 保留 {kept} 条")
        else:
            print(f"  ✅ {filename}: 无需清理 ({kept} 条)")

    print()
    print(f"📊 总计: 删除 {total_deleted} 条, 保留 {total_kept} 条")
    if args.dry_run:
        print("   (预览模式，未实际修改文件。去掉 --dry-run 执行真实清理)")


if __name__ == "__main__":
    main()
