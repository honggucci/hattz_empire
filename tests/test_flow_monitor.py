"""
FlowMonitor QA Test
부트로더 원칙 준수 모니터링 테스트
"""
import sys
sys.path.insert(0, "c:\\Users\\hahonggu\\Desktop\\coin_master\\hattz_empire")

from src.services.flow_monitor import FlowMonitor

def test_flow_monitor():
    monitor = FlowMonitor()
    print("=== FlowMonitor QA Test ===\n")

    passed = 0
    failed = 0

    # Test 1: Valid coder output (JSON only)
    result = monitor.validate_output('coder', '{"action": "edit", "file": "test.py"}', 'test-session')
    if len(result["violations"]) == 0:
        print("Test 1 - Valid coder JSON: PASS")
        passed += 1
    else:
        print(f"Test 1 - Valid coder JSON: FAIL - {result['violations']}")
        failed += 1

    # Test 2: Coder with chatter (should detect violation)
    result = monitor.validate_output('coder', '이렇게 하면 더 좋을 것 같습니다. {"action": "edit"}', 'test-session')
    if len(result["violations"]) > 0:
        print(f"Test 2 - Coder chatter detection: PASS - {result['violations']}")
        passed += 1
    else:
        print("Test 2 - Coder chatter detection: FAIL - should detect violation")
        failed += 1

    # Test 3: Strategist writing code (should detect violation)
    result = monitor.validate_output('strategist', 'def calculate(): pass', 'test-session')
    if len(result["violations"]) > 0:
        print(f"Test 3 - Strategist coding detection: PASS - {result['violations']}")
        passed += 1
    else:
        print("Test 3 - Strategist coding detection: FAIL - should detect code")
        failed += 1

    # Test 4: PM DFA valid transition (DISPATCH -> RETRY)
    result = monitor.record_transition('test-session-2', 'DISPATCH', 'RETRY')
    if result["valid"]:
        print("Test 4 - DISPATCH->RETRY transition: PASS")
        passed += 1
    else:
        print(f"Test 4 - DISPATCH->RETRY transition: FAIL - {result}")
        failed += 1

    # Test 5: PM DFA invalid transition (DONE -> DISPATCH)
    result = monitor.record_transition('test-session-2', 'DONE', 'DISPATCH')
    if not result["valid"]:
        print("Test 5 - DONE->DISPATCH invalid: PASS")
        passed += 1
    else:
        print("Test 5 - DONE->DISPATCH invalid: FAIL - should be invalid")
        failed += 1

    # Test 6: Escalation monotonicity (valid sequence)
    result = monitor.record_escalation('test-session-3', 'SELF_REPAIR')
    if result["valid"]:
        print("Test 6 - SELF_REPAIR escalation: PASS")
        passed += 1
    else:
        print(f"Test 6 - SELF_REPAIR escalation: FAIL - {result}")
        failed += 1

    # Test 7: Escalation to ROLE_SWITCH (valid)
    result = monitor.record_escalation('test-session-3', 'ROLE_SWITCH')
    if result["valid"]:
        print("Test 7 - ROLE_SWITCH escalation: PASS")
        passed += 1
    else:
        print(f"Test 7 - ROLE_SWITCH escalation: FAIL - {result}")
        failed += 1

    # Test 8: Escalation monotonicity violation (back to SELF_REPAIR)
    result = monitor.record_escalation('test-session-3', 'SELF_REPAIR')
    if not result["valid"]:
        print("Test 8 - Monotonicity violation: PASS")
        passed += 1
    else:
        print("Test 8 - Monotonicity violation: FAIL - should be invalid")
        failed += 1

    # Test 9: Session report
    report = monitor.get_session_report('test-session')
    if 'quality_score' in report and 0 <= report['quality_score'] <= 100:
        print(f"Test 9 - Session report (score={report['quality_score']}): PASS")
        passed += 1
    else:
        print(f"Test 9 - Session report: FAIL - missing quality_score")
        failed += 1

    # Test 10: Global report
    global_report = monitor.get_global_report()
    if 'total_outputs' in global_report:
        print(f"Test 10 - Global report (outputs={global_report['total_outputs']}): PASS")
        passed += 1
    else:
        print(f"Test 10 - Global report: FAIL - missing total_outputs")
        failed += 1

    print(f"\n=== Results: {passed}/{passed+failed} tests passed ===")
    return passed, failed


if __name__ == "__main__":
    passed, failed = test_flow_monitor()
    exit(0 if failed == 0 else 1)
