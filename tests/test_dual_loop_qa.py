"""
QA Test - Dual Loop 실제 작동 검증

프리픽스 없는 메시지 → Dual Loop 진입 → GPT Strategist → Claude Coder → Claude Reviewer
"""
import sys
import io
from pathlib import Path

# Windows console UTF-8 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from src.services.dual_loop import DualLoop, LoopVerdict
from src.services.database import create_session


def test_dual_loop_basic():
    """기본 Dual Loop 작동 테스트"""
    print("=" * 80)
    print("Dual Loop QA Test - Basic Flow")
    print("=" * 80)

    # DB에 세션 생성 (UUID 자동 생성)
    session_id = create_session(name="Dual Loop QA Test", project="hattz_empire", agent="dual_loop")
    print(f"Created session: {session_id}\n")

    task = "Create a simple Python function to add two numbers"

    loop = DualLoop(session_id=session_id, project="hattz_empire")

    print(f"\nTask: {task}")
    print("\nStarting Dual Loop...\n")

    iteration_count = 0
    final_verdict = None
    final_implementation = None

    for event in loop.run(task):
        stage = event.get("stage")
        iteration = event.get("iteration", "?")
        content = event.get("content", "")

        # 진행 상황 출력
        if stage == "strategy":
            print(f"[Iteration {iteration}] 📋 GPT-5.2 Strategist analyzing...")
        elif stage == "strategy_done":
            print(f"[Iteration {iteration}] ✅ Strategy completed ({len(content)} chars)")
            print(f"Preview: {content[:100]}...")

        elif stage == "code":
            print(f"[Iteration {iteration}] 💻 Claude Opus Coder implementing...")
        elif stage == "code_done":
            print(f"[Iteration {iteration}] ✅ Implementation completed ({len(content)} chars)")
            print(f"Preview: {content[:100]}...")
            final_implementation = content

        elif stage == "review":
            print(f"[Iteration {iteration}] 🔍 Claude Opus Reviewer evaluating...")
        elif stage == "review_done":
            verdict = event.get("verdict", "UNKNOWN")
            print(f"[Iteration {iteration}] ✅ Review completed - Verdict: {verdict}")
            print(f"Details: {content[:150]}")
            final_verdict = verdict
            iteration_count = iteration

        elif stage == "complete":
            print(f"\n{'='*80}")
            print(f"🎉 DUAL LOOP COMPLETED at iteration {iteration}")
            print(f"{'='*80}")
            final_implementation = content

        elif stage == "abort":
            print(f"\n{'='*80}")
            print(f"❌ DUAL LOOP ABORTED at iteration {iteration}")
            print(f"Reason: {event.get('reason', 'Unknown')}")
            print(f"{'='*80}")

        elif stage == "max_iterations":
            print(f"\n{'='*80}")
            print(f"⚠️  MAX ITERATIONS REACHED ({iteration})")
            print(f"Message: {event.get('message', 'Unknown')}")
            print(f"{'='*80}")

        elif stage == "error":
            print(f"\n{'='*80}")
            print(f"❌ ERROR at iteration {iteration}")
            print(f"Error: {content}")
            print(f"{'='*80}")

    # 결과 검증
    print(f"\n{'='*80}")
    print("Test Results")
    print(f"{'='*80}")

    checks = []

    # Check 1: Strategist 호출됨
    if iteration_count >= 1:
        checks.append(("✅", "GPT-5.2 Strategist called"))
    else:
        checks.append(("❌", "GPT-5.2 Strategist NOT called"))

    # Check 2: Coder 호출됨
    if final_implementation:
        checks.append(("✅", "Claude Opus Coder called"))
    else:
        checks.append(("❌", "Claude Opus Coder NOT called"))

    # Check 3: Reviewer 호출됨
    if final_verdict:
        checks.append(("✅", f"Claude Opus Reviewer called (verdict: {final_verdict})"))
    else:
        checks.append(("❌", "Claude Opus Reviewer NOT called"))

    # Check 4: 최소 1회 iteration
    if iteration_count >= 1:
        checks.append(("✅", f"Completed {iteration_count} iteration(s)"))
    else:
        checks.append(("❌", "No iterations completed"))

    # Check 5: 최종 결과 존재
    if final_implementation and len(final_implementation) > 0:
        checks.append(("✅", f"Final implementation exists ({len(final_implementation)} chars)"))
    else:
        checks.append(("❌", "No final implementation"))

    for status, message in checks:
        print(f"{status} {message}")

    # 전체 판정
    all_pass = all(status == "✅" for status, _ in checks)

    print(f"\n{'='*80}")
    if all_pass:
        print("🎉 [ALL CHECKS PASSED] Dual Loop is working correctly!")
        print(f"{'='*80}")
        return True
    else:
        failed_count = sum(1 for status, _ in checks if status == "❌")
        print(f"❌ [FAILURE] {failed_count}/{len(checks)} checks failed")
        print(f"{'='*80}")
        return False


def test_dual_loop_iteration_flow():
    """Iteration 흐름 테스트 (REVISE 케이스)"""
    print("\n\n" + "=" * 80)
    print("Dual Loop QA Test - Iteration Flow (REVISE scenario)")
    print("=" * 80)

    # DB에 세션 생성
    session_id = create_session(name="Dual Loop REVISE Test", project="hattz_empire", agent="dual_loop")
    print(f"Created session: {session_id}\n")

    # 의도적으로 애매한 태스크 (리뷰어가 REVISE 할 가능성 높음)
    task = "Create a complex function"

    loop = DualLoop(session_id=session_id, project="hattz_empire")

    print(f"\nTask: {task}")
    print("Note: 애매한 태스크로 REVISE 유도\n")

    verdicts = []

    for event in loop.run(task):
        if event.get("stage") == "review_done":
            verdict = event.get("verdict", "UNKNOWN")
            iteration = event.get("iteration", "?")
            verdicts.append((iteration, verdict))
            print(f"[Iteration {iteration}] Verdict: {verdict}")

    print(f"\n{'='*80}")
    print("Verdict History:")
    print(f"{'='*80}")
    for it, verd in verdicts:
        print(f"  Iteration {it}: {verd}")

    # Check: 최소 1개 verdict
    if len(verdicts) >= 1:
        print(f"\n✅ Reviewer called {len(verdicts)} time(s)")
        return True
    else:
        print(f"\n❌ Reviewer NOT called")
        return False


if __name__ == "__main__":
    print("Starting Dual Loop QA Tests...\n")

    result1 = test_dual_loop_basic()
    result2 = test_dual_loop_iteration_flow()

    print("\n\n" + "=" * 80)
    print("FINAL RESULTS")
    print("=" * 80)
    print(f"Basic Flow Test: {'✅ PASS' if result1 else '❌ FAIL'}")
    print(f"Iteration Flow Test: {'✅ PASS' if result2 else '❌ FAIL'}")
    print("=" * 80)

    if result1 and result2:
        print("\n🎉 [ALL TESTS PASSED] Dual Loop 정상 작동 확인!")
        sys.exit(0)
    else:
        print("\n❌ [SOME TESTS FAILED] Dual Loop 점검 필요")
        sys.exit(1)
