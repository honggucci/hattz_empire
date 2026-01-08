"""
로그 분석 스크립트

사용법:
    python scripts/analyze_logs.py                  # 전체 요약
    python scripts/analyze_logs.py --errors         # 에러만 표시
    python scripts/analyze_logs.py --llm            # LLM 호출 통계
    python scripts/analyze_logs.py --tail 20        # 최근 20개 로그
    python scripts/analyze_logs.py --search "coder" # 특정 키워드 검색
"""
import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

LOG_DIR = Path(__file__).parent.parent / "logs"


def read_jsonl(filepath: Path, limit: int = None) -> list:
    """JSONL 파일 읽기"""
    if not filepath.exists():
        return []

    lines = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            try:
                lines.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue

    if limit:
        return lines[-limit:]
    return lines


def print_summary():
    """전체 로그 요약"""
    server_logs = read_jsonl(LOG_DIR / "server.log")
    error_logs = read_jsonl(LOG_DIR / "error.log")
    llm_logs = read_jsonl(LOG_DIR / "llm_calls.log")

    print("=" * 60)
    print("Hattz Empire - Log Summary")
    print("=" * 60)
    print(f"\nServer logs: {len(server_logs)} entries")
    print(f"Error logs:  {len(error_logs)} entries")
    print(f"LLM calls:   {len(llm_logs)} entries")

    # 레벨별 통계
    level_counts = defaultdict(int)
    for log in server_logs:
        level_counts[log.get("level", "UNKNOWN")] += 1

    print("\n[Level Distribution]")
    for level, count in sorted(level_counts.items()):
        print(f"  {level}: {count}")

    # 최근 에러 (5개)
    if error_logs:
        print("\n[Recent Errors]")
        for log in error_logs[-5:]:
            ts = log.get("timestamp", "")[:19]
            msg = log.get("message", "")[:60]
            agent = log.get("agent", "")
            print(f"  [{ts}] {agent or '-'}: {msg}")


def print_errors():
    """에러 로그만 표시"""
    error_logs = read_jsonl(LOG_DIR / "error.log")

    if not error_logs:
        print("No errors found.")
        return

    print("=" * 60)
    print(f"Error Logs ({len(error_logs)} entries)")
    print("=" * 60)

    for log in error_logs:
        ts = log.get("timestamp", "")[:19]
        msg = log.get("message", "")
        agent = log.get("agent", "-")
        error_type = log.get("error_type", "-")

        print(f"\n[{ts}] {error_type}")
        print(f"  Agent: {agent}")
        print(f"  Message: {msg}")

        if log.get("exception"):
            exc_lines = log["exception"].split("\n")
            print(f"  Exception: {exc_lines[-1] if exc_lines else '-'}")


def print_llm_stats():
    """LLM 호출 통계"""
    llm_logs = read_jsonl(LOG_DIR / "llm_calls.log")

    if not llm_logs:
        print("No LLM calls logged.")
        return

    print("=" * 60)
    print(f"LLM Call Statistics ({len(llm_logs)} calls)")
    print("=" * 60)

    # 에이전트별 통계
    agent_stats = defaultdict(lambda: {"count": 0, "tokens": 0, "cost": 0.0, "time_ms": 0})

    for log in llm_logs:
        agent = log.get("agent", "unknown")
        agent_stats[agent]["count"] += 1
        agent_stats[agent]["tokens"] += log.get("tokens", 0)
        agent_stats[agent]["cost"] += log.get("cost", 0.0)
        agent_stats[agent]["time_ms"] += log.get("duration_ms", 0)

    print("\n[By Agent]")
    print(f"{'Agent':<15} {'Calls':<8} {'Tokens':<10} {'Cost':<10} {'Avg Time':<10}")
    print("-" * 53)

    for agent, stats in sorted(agent_stats.items(), key=lambda x: -x[1]["cost"]):
        avg_time = stats["time_ms"] / stats["count"] if stats["count"] > 0 else 0
        print(f"{agent:<15} {stats['count']:<8} {stats['tokens']:<10} ${stats['cost']:<9.4f} {avg_time:.0f}ms")

    # 총계
    total_cost = sum(s["cost"] for s in agent_stats.values())
    total_tokens = sum(s["tokens"] for s in agent_stats.values())
    print("-" * 53)
    print(f"{'TOTAL':<15} {len(llm_logs):<8} {total_tokens:<10} ${total_cost:<9.4f}")


def print_tail(n: int):
    """최근 N개 로그"""
    server_logs = read_jsonl(LOG_DIR / "server.log", limit=n)

    print(f"[Last {n} logs]")
    for log in server_logs:
        ts = log.get("timestamp", "")[:19]
        level = log.get("level", "")
        msg = log.get("message", "")[:80]

        # 색상 (터미널)
        colors = {"ERROR": "\033[31m", "WARNING": "\033[33m", "INFO": "\033[32m"}
        reset = "\033[0m"
        color = colors.get(level, "")

        print(f"{color}[{ts}] {level:<8}{reset} {msg}")


def search_logs(keyword: str):
    """키워드 검색"""
    server_logs = read_jsonl(LOG_DIR / "server.log")
    matches = []

    for log in server_logs:
        log_str = json.dumps(log, ensure_ascii=False).lower()
        if keyword.lower() in log_str:
            matches.append(log)

    print(f"Found {len(matches)} logs containing '{keyword}'")
    for log in matches[-20:]:  # 최대 20개
        ts = log.get("timestamp", "")[:19]
        level = log.get("level", "")
        msg = log.get("message", "")[:80]
        print(f"[{ts}] {level}: {msg}")


def main():
    args = sys.argv[1:]

    if not args:
        print_summary()
    elif "--errors" in args:
        print_errors()
    elif "--llm" in args:
        print_llm_stats()
    elif "--tail" in args:
        idx = args.index("--tail")
        n = int(args[idx + 1]) if len(args) > idx + 1 else 20
        print_tail(n)
    elif "--search" in args:
        idx = args.index("--search")
        keyword = args[idx + 1] if len(args) > idx + 1 else ""
        if keyword:
            search_logs(keyword)
        else:
            print("Usage: --search <keyword>")
    else:
        print_summary()


if __name__ == "__main__":
    main()
