#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DB 메시지 저장 검증 스크립트 (v2.6.9)

검증 항목:
1. DB 연결 상태
2. 최근 메시지 조회 (chat_messages)
3. 임베딩 큐 상태
4. 테스트 메시지 저장/조회
"""
import sys
import io
from pathlib import Path

# Windows console UTF-8 support
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 프로젝트 루트 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from src.services import database as db


def check_db_connection():
    """1. DB 연결 상태 확인"""
    print("=" * 60)
    print("1. DB 연결 상태 확인")
    print("=" * 60)

    result = db.check_db_health()
    print(f"상태: {result['status']}")
    if result['status'] == 'ok':
        print(f"데이터베이스: {result['database']}")
        print(f"세션 수: {result['sessions']}")
        print(f"메시지 수: {result['messages']}")
    else:
        print(f"에러: {result.get('message', 'Unknown')}")
    return result['status'] == 'ok'


def check_recent_messages():
    """2. 최근 메시지 조회"""
    print("\n" + "=" * 60)
    print("2. 최근 메시지 조회 (최근 10개)")
    print("=" * 60)

    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TOP 10
                    m.id,
                    m.session_id,
                    m.role,
                    m.agent,
                    LEFT(m.content, 50) as content_preview,
                    m.timestamp,
                    m.is_internal
                FROM chat_messages m
                ORDER BY m.timestamp DESC
            """)

            rows = cursor.fetchall()
            if not rows:
                print("⚠️ 메시지가 없습니다.")
                return False

            print(f"\n{'ID':<6} {'Session':<10} {'Role':<10} {'Agent':<10} {'Internal':<8} {'Content Preview':<50}")
            print("-" * 100)
            for row in rows:
                content_preview = (row.content_preview or "").replace("\n", " ")[:45]
                is_internal = "Y" if row.is_internal else "N"
                print(f"{row.id:<6} {str(row.session_id)[:8]:<10} {row.role:<10} {(row.agent or '-'):<10} {is_internal:<8} {content_preview:<50}")

            return True
    except Exception as e:
        print(f"❌ 에러: {e}")
        return False


def check_embedding_queue():
    """3. 임베딩 큐 상태 확인"""
    print("\n" + "=" * 60)
    print("3. 임베딩 큐 상태")
    print("=" * 60)

    try:
        from src.services.embedding_queue import get_embedding_queue
        eq = get_embedding_queue()

        status = {
            "running": eq.is_running(),
            "queue_size": eq._queue.qsize() if hasattr(eq, '_queue') else "N/A"
        }

        print(f"실행 중: {'✅ Yes' if status['running'] else '❌ No'}")
        print(f"대기 큐 크기: {status['queue_size']}")
        return True
    except Exception as e:
        print(f"⚠️ 임베딩 큐 확인 실패: {e}")
        return True  # 필수는 아님


def test_message_persistence():
    """4. 테스트 메시지 저장/조회"""
    print("\n" + "=" * 60)
    print("4. 테스트 메시지 저장/조회")
    print("=" * 60)

    try:
        # 테스트 세션 생성
        test_session_id = db.create_session(
            name="[TEST] DB Verification",
            project="test",
            agent="pm"
        )
        print(f"✅ 테스트 세션 생성: {test_session_id}")

        # 사용자 메시지 저장
        test_content = "[TEST] DB 저장 검증 메시지 - " + str(__import__('datetime').datetime.now())
        user_msg_id = db.add_message(
            session_id=test_session_id,
            role="user",
            content=test_content,
            agent="pm"
        )
        print(f"✅ 사용자 메시지 저장: msg_id={user_msg_id}")

        # assistant 메시지 저장
        assistant_msg_id = db.add_message(
            session_id=test_session_id,
            role="assistant",
            content="[TEST] 테스트 응답입니다.",
            agent="pm",
            model_id="test-model"
        )
        print(f"✅ 어시스턴트 메시지 저장: msg_id={assistant_msg_id}")

        # 저장된 메시지 조회
        messages = db.get_messages(test_session_id)
        print(f"✅ 조회된 메시지 수: {len(messages)}")

        for msg in messages:
            print(f"   - [{msg['role']}] {msg['content'][:50]}...")

        # 테스트 세션 삭제
        db.delete_session(test_session_id)
        print(f"✅ 테스트 세션 삭제 완료")

        return len(messages) == 2
    except Exception as e:
        print(f"❌ 에러: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_session_message_flow():
    """5. 세션별 메시지 저장 흐름 확인"""
    print("\n" + "=" * 60)
    print("5. 세션별 메시지 저장 흐름")
    print("=" * 60)

    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()

            # 최근 세션들의 메시지 수 확인
            cursor.execute("""
                SELECT TOP 5
                    s.id as session_id,
                    s.name,
                    s.agent,
                    s.created_at,
                    (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.id) as msg_count,
                    (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.id AND m.role = 'user') as user_count,
                    (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.id AND m.role = 'assistant') as assistant_count
                FROM chat_sessions s
                WHERE s.is_deleted = 0 OR s.is_deleted IS NULL
                ORDER BY s.updated_at DESC
            """)

            rows = cursor.fetchall()
            if not rows:
                print("⚠️ 활성 세션이 없습니다.")
                return True

            print(f"\n{'Session ID':<12} {'Name':<25} {'Agent':<8} {'Total':<6} {'User':<6} {'Asst':<6}")
            print("-" * 80)
            for row in rows:
                name = (row.name or "-")[:23]
                print(f"{str(row.session_id)[:10]:<12} {name:<25} {(row.agent or '-'):<8} {row.msg_count:<6} {row.user_count:<6} {row.assistant_count:<6}")

            return True
    except Exception as e:
        print(f"❌ 에러: {e}")
        return False


def main():
    """메인 검증 실행"""
    print("\n" + "=" * 60)
    print("  Hattz Empire DB 메시지 저장 검증 (v2.6.9)")
    print("=" * 60)

    results = {
        "DB 연결": check_db_connection(),
        "최근 메시지": check_recent_messages(),
        "임베딩 큐": check_embedding_queue(),
        "저장 테스트": test_message_persistence(),
        "세션 흐름": check_session_message_flow(),
    }

    print("\n" + "=" * 60)
    print("  검증 결과 요약")
    print("=" * 60)

    all_passed = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("  ✅ 모든 검증 통과!")
    else:
        print("  ❌ 일부 검증 실패")
    print("=" * 60 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
