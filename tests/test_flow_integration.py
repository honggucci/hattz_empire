"""
Flow Monitor Integration Test
"""
import sys
sys.path.insert(0, "c:\\Users\\hahonggu\\Desktop\\coin_master\\hattz_empire")

def test_integration():
    passed = 0
    failed = 0

    # Test 1: Flow API import
    try:
        from src.api.flow_quality import flow_bp
        print("Test 1 - Flow API import: PASS")
        passed += 1
    except Exception as e:
        print(f"Test 1 - Flow API import: FAIL - {e}")
        failed += 1

    # Test 2: FlowMonitor singleton
    try:
        from src.services.flow_monitor import get_flow_monitor
        m = get_flow_monitor()
        assert m is not None
        print("Test 2 - FlowMonitor singleton: PASS")
        passed += 1
    except Exception as e:
        print(f"Test 2 - FlowMonitor singleton: FAIL - {e}")
        failed += 1

    # Test 3: llm_caller import with FlowMonitor
    try:
        from src.core.llm_caller import get_flow_monitor as llm_get_flow_monitor
        print("Test 3 - llm_caller FlowMonitor import: PASS")
        passed += 1
    except Exception as e:
        print(f"Test 3 - llm_caller FlowMonitor import: FAIL - {e}")
        failed += 1

    # Test 4: Blueprint registration (mock app)
    try:
        from flask import Flask
        app = Flask(__name__)
        from src.api.flow_quality import flow_bp
        app.register_blueprint(flow_bp)

        # Check routes exist
        routes = [r.rule for r in app.url_map.iter_rules()]
        assert '/api/flow/report' in routes
        assert '/api/flow/violations' in routes
        print("Test 4 - Blueprint registration: PASS")
        passed += 1
    except Exception as e:
        print(f"Test 4 - Blueprint registration: FAIL - {e}")
        failed += 1

    # Test 5: Validate output endpoint logic
    try:
        from src.services.flow_monitor import FlowMonitor
        monitor = FlowMonitor()

        # Valid coder output
        result = monitor.validate_output('coder', '{"action": "edit"}', 'test-session')
        assert 'violations' in result
        print("Test 5 - Validate output logic: PASS")
        passed += 1
    except Exception as e:
        print(f"Test 5 - Validate output logic: FAIL - {e}")
        failed += 1

    print(f"\n=== Results: {passed}/{passed+failed} tests passed ===")
    return passed, failed


if __name__ == "__main__":
    passed, failed = test_integration()
    exit(0 if failed == 0 else 1)
