"""
CLI Session Resume 비판적 테스트 (v2.6.6)

이 테스트는 현재 구현의 치명적 결함을 증명합니다:
- `--session-id`만 사용하면 대화가 이어지지 않음
- `--resume`이 필요함을 검증

실행: python tests/test_session_resume_critical.py
"""
import subprocess
import uuid
import os
import sys
import time

# 프로젝트 경로 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Claude CLI 경로
CLAUDE_CLI_PATH = r"C:\Users\hahonggu\AppData\Roaming\npm\claude.cmd"


def run_cli_command(args: list, prompt: str, timeout: int = 60) -> tuple:
    """CLI 명령 실행 (stdout, stderr, returncode 반환)"""
    cmd = [CLAUDE_CLI_PATH] + args
    print(f"\n[CMD] {' '.join(cmd)}")
    print(f"[PROMPT] {repr(prompt[:50])}...")

    try:
        # Windows 환경변수 설정 (UTF-8 강제 + Node.js PATH 추가)
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        # Node.js 경로를 PATH 맨 앞에 추가
        node_path = r"C:\Program Files\nodejs"
        npm_path = r"C:\Users\hahonggu\AppData\Roaming\npm"
        env['PATH'] = f"{node_path};{npm_path};{env.get('PATH', '')}"

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=PROJECT_ROOT,
            shell=True,  # Windows에서 .cmd 실행
            env=env,
        )
        stdout, stderr = proc.communicate(
            input=prompt.encode('utf-8'),
            timeout=timeout
        )
        return (
            stdout.decode('utf-8', errors='replace'),
            stderr.decode('utf-8', errors='replace'),
            proc.returncode
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        return ("", "TIMEOUT", -1)
    except Exception as e:
        return ("", str(e), -2)


def test_session_id_only():
    """
    테스트 1: --session-id만 사용 (현재 구현)

    예상 결과: 두 번째 호출에서 첫 번째 대화를 기억하지 못함
    """
    print("\n" + "="*60)
    print("TEST 1: --session-id만 사용 (현재 구현)")
    print("="*60)

    session_uuid = str(uuid.uuid4())
    print(f"Session UUID: {session_uuid}")

    # 첫 번째 호출: 숫자를 기억하라고 요청
    prompt1 = "내가 말하는 숫자를 기억해. 그 숫자는 42야. '42를 기억했습니다'라고만 답해."
    stdout1, stderr1, code1 = run_cli_command(
        ['--print', '--session-id', session_uuid, '--dangerously-skip-permissions'],
        prompt1
    )
    print(f"[RESULT 1] code={code1}")
    print(f"[STDOUT 1] {stdout1[:500]}")

    if code1 != 0:
        print("[SKIP] CLI 실행 실패")
        return None

    # 잠시 대기
    time.sleep(2)

    # 두 번째 호출: 같은 session-id로 숫자를 물어봄
    prompt2 = "내가 아까 말한 숫자가 뭐였지? 숫자만 답해."
    stdout2, stderr2, code2 = run_cli_command(
        ['--print', '--session-id', session_uuid, '--dangerously-skip-permissions'],
        prompt2
    )
    print(f"[RESULT 2] code={code2}")
    print(f"[STDOUT 2] {stdout2[:500]}")

    # 결과 분석
    remembers = "42" in stdout2
    print(f"\n[ANALYSIS] Remembers: {'YES' if remembers else 'NO'}")

    return remembers


def test_session_id_with_resume():
    """
    테스트 2: --session-id + --resume 사용 (제안된 수정안)

    예상 결과: 두 번째 호출에서 첫 번째 대화를 기억함
    """
    print("\n" + "="*60)
    print("TEST 2: --session-id (첫번째) + --resume (두번째)")
    print("="*60)

    session_uuid = str(uuid.uuid4())
    print(f"Session UUID: {session_uuid}")

    # 첫 번째 호출: --session-id로 세션 생성
    prompt1 = "내가 말하는 숫자를 기억해. 그 숫자는 77이야. '77을 기억했습니다'라고만 답해."
    stdout1, stderr1, code1 = run_cli_command(
        ['--print', '--session-id', session_uuid, '--dangerously-skip-permissions'],
        prompt1
    )
    print(f"[RESULT 1] code={code1}")
    print(f"[STDOUT 1] {stdout1[:500]}")

    if code1 != 0:
        print("[SKIP] CLI 실행 실패")
        return None

    # 잠시 대기
    time.sleep(2)

    # 두 번째 호출: --resume으로 세션 복원
    prompt2 = "내가 아까 말한 숫자가 뭐였지? 숫자만 답해."
    stdout2, stderr2, code2 = run_cli_command(
        ['--print', '--resume', session_uuid, '--dangerously-skip-permissions'],
        prompt2
    )
    print(f"[RESULT 2] code={code2}")
    print(f"[STDOUT 2] {stdout2[:500]}")

    # 결과 분석
    remembers = "77" in stdout2
    print(f"\n[ANALYSIS] Remembers: {'YES' if remembers else 'NO'}")

    return remembers


def test_resume_only():
    """
    테스트 3: --resume만 사용 (모든 호출)

    예상 결과: 첫 번째 호출도 --resume으로 가능한지 확인
    """
    print("\n" + "="*60)
    print("TEST 3: --resume만 사용 (모든 호출)")
    print("="*60)

    session_uuid = str(uuid.uuid4())
    print(f"Session UUID: {session_uuid}")

    # 첫 번째 호출: --resume으로 시작 (새 세션이 자동 생성되는지 확인)
    prompt1 = "내가 말하는 숫자를 기억해. 그 숫자는 99야. '99를 기억했습니다'라고만 답해."
    stdout1, stderr1, code1 = run_cli_command(
        ['--print', '--resume', session_uuid, '--dangerously-skip-permissions'],
        prompt1
    )
    print(f"[RESULT 1] code={code1}")
    print(f"[STDOUT 1] {stdout1[:500]}")
    print(f"[STDERR 1] {repr(stderr1[:200]) if stderr1 else 'None'}")

    if code1 != 0:
        print(f"[NOTE] --resume with new UUID: code={code1}")
        # 새 UUID로 --resume하면 에러가 날 수 있음
        return None

    # 잠시 대기
    time.sleep(2)

    # 두 번째 호출
    prompt2 = "내가 아까 말한 숫자가 뭐였지? 숫자만 답해."
    stdout2, stderr2, code2 = run_cli_command(
        ['--print', '--resume', session_uuid, '--dangerously-skip-permissions'],
        prompt2
    )
    print(f"[RESULT 2] code={code2}")
    print(f"[STDOUT 2] {stdout2[:500]}")

    # 결과 분석
    remembers = "99" in stdout2
    print(f"\n[ANALYSIS] Remembers: {'YES' if remembers else 'NO'}")

    return remembers


def main():
    print("="*60)
    print("CLI Session Resume 비판적 테스트")
    print("="*60)
    print(f"CLI Path: {CLAUDE_CLI_PATH}")
    print(f"Project Root: {PROJECT_ROOT}")

    # CLI 존재 확인
    if not os.path.exists(CLAUDE_CLI_PATH):
        print(f"\n[ERROR] Claude CLI not found: {CLAUDE_CLI_PATH}")
        return

    results = {}

    # 테스트 실행
    results['session_id_only'] = test_session_id_only()
    results['session_id_with_resume'] = test_session_id_with_resume()
    results['resume_only'] = test_resume_only()

    # 결과 요약
    print("\n" + "="*60)
    print("결과 요약")
    print("="*60)
    for test_name, result in results.items():
        if result is None:
            status = "[SKIP]"
        elif result:
            status = "[PASS] Remembers"
        else:
            status = "[FAIL] Does NOT remember"
        print(f"  {test_name}: {status}")

    # 결론
    print("\n" + "="*60)
    print("결론")
    print("="*60)

    if results['session_id_only'] == False and results['session_id_with_resume'] == True:
        print("[CONFIRMED] Hypothesis verified:")
        print("   - --session-id alone does NOT continue conversation")
        print("   - --resume is REQUIRED to continue conversation")
        print("   - Current v2.6.6 implementation needs fix")
    elif results['session_id_only'] == True:
        print("[UNEXPECTED] Different result:")
        print("   - --session-id alone DOES continue conversation")
        print("   - CLI version may behave differently")
        print("   - Further investigation needed")
    else:
        print("[INCOMPLETE] Test incomplete:")
        print("   - Some tests did not run")
        print("   - Manual verification needed")


if __name__ == "__main__":
    main()
