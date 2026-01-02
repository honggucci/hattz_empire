#!/usr/bin/env python3
"""
Live Session Backup
현재 진행 중인 Claude Code 세션을 실시간 백업

사용법:
  python live_backup.py              # 현재 세션 백업
  python live_backup.py --watch      # 5분마다 자동 백업
  python live_backup.py --watch 60   # 1분마다 자동 백업
"""
import json
import sys
import shutil
import time
from pathlib import Path
from datetime import datetime

# Claude Code 프로젝트 폴더
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# 백업 폴더
BACKUP_BASE = Path(__file__).parent.parent / "conversations" / "daily"


def find_active_sessions() -> list[tuple[str, Path]]:
    """현재 활성 세션 찾기 (최근 수정된 jsonl 파일)"""
    sessions = []

    if not CLAUDE_PROJECTS.exists():
        return sessions

    for project_dir in CLAUDE_PROJECTS.iterdir():
        if not project_dir.is_dir():
            continue

        # agent 파일 제외, 일반 세션만
        for jsonl in project_dir.glob("*.jsonl"):
            if jsonl.name.startswith("agent-"):
                continue

            # 파일 크기가 0이 아닌 것만
            if jsonl.stat().st_size > 0:
                sessions.append((project_dir.name, jsonl))

    # 최근 수정순 정렬
    sessions.sort(key=lambda x: x[1].stat().st_mtime, reverse=True)
    return sessions


def backup_session(project_name: str, jsonl_path: Path, title: str = None) -> Path:
    """세션 백업"""
    now = datetime.now()

    # 백업 폴더: daily/YYYY/MM/DD/
    date_path = BACKUP_BASE / now.strftime("%Y/%m/%d")
    date_path.mkdir(parents=True, exist_ok=True)

    # 파일명 (세션 ID 포함해서 고유하게)
    time_str = now.strftime("%H%M%S")
    session_id = jsonl_path.stem[:8]  # UUID 앞 8자
    safe_project = project_name.split("-")[-1][:15] if project_name else "unknown"

    backup_file = date_path / f"session_{time_str}_{safe_project}_{session_id}.jsonl"

    # 복사
    shutil.copy2(jsonl_path, backup_file)

    # 메타 정보
    meta_file = backup_file.with_suffix(".meta.json")
    meta = {
        "source": str(jsonl_path),
        "project": project_name,
        "backup_time": now.isoformat(),
        "size_bytes": jsonl_path.stat().st_size
    }
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return backup_file


def watch_and_backup(interval_seconds: int = 300):
    """주기적으로 백업 (기본 5분)"""
    print(f"[Live Backup] Watching... (interval: {interval_seconds}s)")
    print("[Live Backup] Press Ctrl+C to stop\n")

    last_sizes = {}

    while True:
        try:
            sessions = find_active_sessions()

            for project_name, jsonl_path in sessions[:3]:  # 최근 3개만
                current_size = jsonl_path.stat().st_size
                last_size = last_sizes.get(str(jsonl_path), 0)

                # 크기가 변했으면 백업
                if current_size != last_size:
                    backup_file = backup_session(project_name, jsonl_path)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Backed up: {backup_file.name} ({current_size:,} bytes)")
                    last_sizes[str(jsonl_path)] = current_size

            time.sleep(interval_seconds)

        except KeyboardInterrupt:
            print("\n[Live Backup] Stopped.")
            break


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--watch":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 300
        watch_and_backup(interval)
    else:
        # 단일 백업
        sessions = find_active_sessions()

        if not sessions:
            print("[Live Backup] No active sessions found.")
            return

        print(f"[Live Backup] Found {len(sessions)} session(s)\n")

        for project_name, jsonl_path in sessions[:3]:
            size = jsonl_path.stat().st_size
            mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime)

            print(f"  Project: {project_name}")
            print(f"  File: {jsonl_path.name}")
            print(f"  Size: {size:,} bytes")
            print(f"  Modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")

            backup_file = backup_session(project_name, jsonl_path)
            print(f"  → Backed up to: {backup_file}")
            print()


if __name__ == "__main__":
    main()
