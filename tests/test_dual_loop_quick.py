"""
Quick Test - Dual Loop 루프 구조 검증

실제 LLM 호출 없이 구조만 검증
"""
import sys
import io
from pathlib import Path

# Windows console UTF-8 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from src.services.dual_loop import DualLoop, LoopVerdict


def test_dual_loop_structure():
    """Dual Loop 클래스 구조 검증"""
    print("=" * 80)
    print("Dual Loop Structure Test")
    print("=" * 80)

    checks = []

    # Check 1: DualLoop 클래스 임포트 가능
    try:
        from src.services.dual_loop import DualLoop
        checks.append(("✅", "DualLoop class imported"))
    except Exception as e:
        checks.append(("❌", f"DualLoop import failed: {e}"))

    # Check 2: LoopVerdict Enum 확인
    try:
        verdicts = [v.value for v in LoopVerdict]
        if "APPROVE" in verdicts and "REVISE" in verdicts and "ABORT" in verdicts:
            checks.append(("✅", f"LoopVerdict enum valid: {verdicts}"))
        else:
            checks.append(("❌", f"LoopVerdict incomplete: {verdicts}"))
    except Exception as e:
        checks.append(("❌", f"LoopVerdict check failed: {e}"))

    # Check 3: DualLoop 인스턴스 생성 가능
    try:
        loop = DualLoop(session_id="test", project="hattz_empire")
        checks.append(("✅", "DualLoop instance created"))
    except Exception as e:
        checks.append(("❌", f"DualLoop instance failed: {e}"))

    # Check 4: 필수 메서드 존재
    try:
        assert hasattr(loop, "_call_gpt_strategist")
        assert hasattr(loop, "_call_claude_coder")
        assert hasattr(loop, "_call_opus_reviewer")
        assert hasattr(loop, "run")
        checks.append(("✅", "All required methods exist"))
    except AssertionError:
        checks.append(("❌", "Missing required methods"))

    # Check 5: MAX_ITERATIONS 설정
    try:
        assert loop.MAX_ITERATIONS == 5
        checks.append(("✅", f"MAX_ITERATIONS = {loop.MAX_ITERATIONS}"))
    except Exception as e:
        checks.append(("❌", f"MAX_ITERATIONS check failed: {e}"))

    # 결과 출력
    print("\nChecks:")
    for status, message in checks:
        print(f"{status} {message}")

    all_pass = all(status == "✅" for status, _ in checks)

    print("\n" + "=" * 80)
    if all_pass:
        print("✅ [ALL CHECKS PASSED] Dual Loop structure is valid")
        print("=" * 80)
        return True
    else:
        failed_count = sum(1 for status, _ in checks if status == "❌")
        print(f"❌ [FAILURE] {failed_count}/{len(checks)} checks failed")
        print("=" * 80)
        return False


def test_dual_loop_method_signatures():
    """메서드 시그니처 검증"""
    print("\n" + "=" * 80)
    print("Method Signature Test")
    print("=" * 80)

    import inspect
    from src.services.dual_loop import DualLoop

    loop = DualLoop(session_id="test", project="test")

    checks = []

    # _call_gpt_strategist
    sig = inspect.signature(loop._call_gpt_strategist)
    params = list(sig.parameters.keys())
    if "task" in params and "context" in params:
        checks.append(("✅", f"_call_gpt_strategist signature: {params}"))
    else:
        checks.append(("❌", f"_call_gpt_strategist wrong signature: {params}"))

    # _call_claude_coder
    sig = inspect.signature(loop._call_claude_coder)
    params = list(sig.parameters.keys())
    if "strategy" in params and "task" in params and "revision_notes" in params:
        checks.append(("✅", f"_call_claude_coder signature: {params}"))
    else:
        checks.append(("❌", f"_call_claude_coder wrong signature: {params}"))

    # _call_opus_reviewer
    sig = inspect.signature(loop._call_opus_reviewer)
    params = list(sig.parameters.keys())
    if "task" in params and "strategy" in params and "implementation" in params:
        checks.append(("✅", f"_call_opus_reviewer signature: {params}"))
    else:
        checks.append(("❌", f"_call_opus_reviewer wrong signature: {params}"))

    # run()
    sig = inspect.signature(loop.run)
    params = list(sig.parameters.keys())
    if "task" in params:
        checks.append(("✅", f"run() signature: {params}"))
    else:
        checks.append(("❌", f"run() wrong signature: {params}"))

    # 결과 출력
    print("\nChecks:")
    for status, message in checks:
        print(f"{status} {message}")

    all_pass = all(status == "✅" for status, _ in checks)

    print("\n" + "=" * 80)
    if all_pass:
        print("✅ [ALL CHECKS PASSED] Method signatures are correct")
        print("=" * 80)
        return True
    else:
        failed_count = sum(1 for status, _ in checks if status == "❌")
        print(f"❌ [FAILURE] {failed_count}/{len(checks)} checks failed")
        print("=" * 80)
        return False


if __name__ == "__main__":
    result1 = test_dual_loop_structure()
    result2 = test_dual_loop_method_signatures()

    print("\n\n" + "=" * 80)
    print("FINAL RESULTS")
    print("=" * 80)
    print(f"Structure Test: {'✅ PASS' if result1 else '❌ FAIL'}")
    print(f"Method Signature Test: {'✅ PASS' if result2 else '❌ FAIL'}")
    print("=" * 80)

    if result1 and result2:
        print("\n✅ [ALL TESTS PASSED] Dual Loop 구조 검증 완료!")
        print("\nNote: 실제 LLM 호출 테스트는 통합 테스트에서 진행하세요.")
        sys.exit(0)
    else:
        print("\n❌ [SOME TESTS FAILED] Dual Loop 구조 점검 필요")
        sys.exit(1)
