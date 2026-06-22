#!/usr/bin/env python3
"""Retry Gate2 items that failed because of model/JSON parsing errors."""

import argparse

from run_gate2 import run_gate2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重试 Gate2 解析/调用失败残留")
    parser.add_argument("--limit", type=int, default=50, help="最大重试数")
    parser.add_argument("--dry-run", action="store_true", help="仅测试不写库")
    parser.add_argument("--max-attempts", type=int, default=3, help="最大尝试次数")
    args = parser.parse_args()
    run_gate2(
        limit=args.limit,
        dry_run=args.dry_run,
        retry_errors=True,
        max_attempts=args.max_attempts,
    )
