#!/usr/bin/env python3
"""
Claude Code Session Backup Hook v2
세션 종료시 대화 내용을 ai_team/conversations에 YAML로 백업

구조:
  conversations/
  └── daily/
      └── YYYY/MM/DD/
          └── session_HHMMSS_claude_backup.yaml

사용법:
  ~/.claude/settings.json 에 등록 → SessionEnd 이벤트에서 자동 실행
"""
import json
import sys
import os
from pathlib import Path
from datetime import datetime
import shutil

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def main():
    # stdin에서 JSON 입력받기
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("[backup_session] No valid JSON input", file=sys.stderr)
        sys.exit(1)

    transcript_path = input_data.get('transcript_path', '')
    session_id = input_data.get('session_id', 'unknown')
    reason = input_data.get('reason', 'unknown')
    cwd = input_data.get('cwd', '')

    # 백업 디렉토리 설정 (ai_team/conversations)
    script_dir = Path(__file__).parent.parent  # ai_team/
    backup_dir = script_dir / "conversations"

    # 날짜별 폴더: daily/YYYY/MM/DD/
    now = datetime.now()
    date_path = backup_dir / "daily" / now.strftime("%Y/%m/%d")
    date_path.mkdir(parents=True, exist_ok=True)

    # 파일명: session_HHMMSS_claude_backup.yaml
    time_str = now.strftime("%H%M%S")

    # 1. transcript 파일이 있으면 백업
    if transcript_path and os.path.exists(transcript_path):
        try:
            # 원본 JSONL 복사
            jsonl_backup = date_path / f"session_{time_str}_transcript.jsonl"
            shutil.copy2(transcript_path, str(jsonl_backup))

            # YAML로 변환 저장
            if HAS_YAML:
                yaml_file = date_path / f"session_{time_str}_claude_backup.yaml"
                convert_jsonl_to_yaml(transcript_path, yaml_file, session_id, reason, cwd)
                print(f"[backup_session] Saved: {yaml_file}")
            else:
                # YAML 없으면 마크다운으로
                md_file = date_path / f"session_{time_str}_claude_backup.md"
                convert_jsonl_to_markdown(transcript_path, md_file)
                print(f"[backup_session] Saved: {md_file}")

        except Exception as e:
            print(f"[backup_session] Backup failed: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"[backup_session] No transcript found: {transcript_path}", file=sys.stderr)

    # 2. index.yaml 업데이트
    if HAS_YAML:
        update_index(backup_dir, now, session_id, reason)

    sys.exit(0)


def convert_jsonl_to_yaml(jsonl_path: str, yaml_path: Path, session_id: str, reason: str, cwd: str):
    """JSONL transcript를 YAML로 변환"""
    messages = []

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                role = entry.get("role", "unknown")
                content = entry.get("content", "")

                # content가 리스트인 경우 (tool use 등)
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                text_parts.append(item.get("text", ""))
                            elif item.get("type") == "tool_use":
                                tool_name = item.get("name", "unknown")
                                text_parts.append(f"[Tool: {tool_name}]")
                        else:
                            text_parts.append(str(item))
                    content = "\n".join(text_parts)

                # 너무 긴 내용 자르기
                if len(content) > 3000:
                    content = content[:3000] + "\n... (truncated)"

                messages.append({
                    "role": role,
                    "content": content
                })

            except json.JSONDecodeError:
                continue

    # YAML 데이터 구성
    session_data = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "status": "completed",
        "source": "claude_code_hook",
        "reason": reason,  # exit, clear, logout 등
        "cwd": cwd,
        "summary": {
            "description": f"Claude Code session backup ({len(messages)} messages)",
            "message_count": len(messages)
        },
        "messages": messages
    }

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(session_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def convert_jsonl_to_markdown(jsonl_path: str, md_path: Path):
    """JSONL transcript를 마크다운으로 변환 (YAML 없을 때 fallback)"""
    lines = [
        "# Claude Code Session Transcript",
        f"*Exported: {datetime.now().isoformat()}*",
        "---",
        ""
    ]

    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    role = entry.get("role", "unknown")
                    content = entry.get("content", "")

                    if isinstance(content, list):
                        text_parts = []
                        for item in content:
                            if isinstance(item, dict):
                                if item.get("type") == "text":
                                    text_parts.append(item.get("text", ""))
                                elif item.get("type") == "tool_use":
                                    tool_name = item.get("name", "unknown")
                                    text_parts.append(f"[Tool: {tool_name}]")
                            else:
                                text_parts.append(str(item))
                        content = "\n".join(text_parts)

                    lines.append(f"## {role.upper()}")
                    lines.append(content[:2000])
                    lines.append("")
                    lines.append("---")
                    lines.append("")

                except json.JSONDecodeError:
                    continue

    except Exception as e:
        lines.append(f"\n*Error reading transcript: {e}*")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def update_index(backup_dir: Path, now: datetime, session_id: str, reason: str):
    """index.yaml 업데이트"""
    index_file = backup_dir / "index.yaml"

    # 기존 인덱스 로드
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            index = yaml.safe_load(f) or {}
    else:
        index = {"total_sessions": 0, "daily_sessions": {}, "tags": {}}

    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")

    # daily_sessions 업데이트
    if "daily_sessions" not in index:
        index["daily_sessions"] = {}

    if date_str not in index["daily_sessions"]:
        index["daily_sessions"][date_str] = {
            "path": f"daily/{now.strftime('%Y/%m/%d')}/",
            "files": [],
            "count": 0,
            "topics": []
        }

    day_info = index["daily_sessions"][date_str]
    filename = f"session_{time_str}_claude_backup.yaml"

    if filename not in day_info.get("files", []):
        day_info["files"].append(filename)
        day_info["count"] = len(day_info["files"])

    if "Claude Code backup" not in day_info.get("topics", []):
        day_info["topics"].append("Claude Code backup")

    # tags 업데이트
    if "tags" not in index:
        index["tags"] = {}
    if "claude_code" not in index["tags"]:
        index["tags"]["claude_code"] = []
    if date_str not in index["tags"]["claude_code"]:
        index["tags"]["claude_code"].append(date_str)

    # 메타 업데이트
    total = sum(d.get("count", 0) for d in index.get("daily_sessions", {}).values())
    index["total_sessions"] = total
    index["last_updated"] = date_str

    with open(index_file, "w", encoding="utf-8") as f:
        yaml.dump(index, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


if __name__ == "__main__":
    main()
