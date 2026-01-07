"""Retry Escalation 불변조건 테스트 실행 스크립트"""
from enum import Enum, auto
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
import hashlib
import threading


class EscalationLevel(Enum):
    SELF_REPAIR = auto()
    ROLE_SWITCH = auto()
    HARD_FAIL = auto()


@dataclass(frozen=True)
class FailureSignature:
    error_type: str
    missing_fields: Tuple[str, ...]
    profile: str
    prompt_hash: str


class RetryEscalator:
    ROLE_SWITCH_MAP = {
        "coder": "reviewer",
        "reviewer": "coder",
        "qa": "coder",
        "council": "reviewer",
    }

    def __init__(self, max_same_signature: int = 2):
        self.max_same_signature = max_same_signature
        self._failure_history = {}
        self._role_switch_used = {}
        self._lock = threading.Lock()

    def compute_signature(self, error_type, missing_fields, profile, prompt):
        prompt_snippet = prompt[:500] if prompt else ""
        prompt_hash = hashlib.md5(prompt_snippet.encode()).hexdigest()
        return FailureSignature(
            error_type=error_type,
            missing_fields=tuple(sorted(missing_fields)) if missing_fields else (),
            profile=profile,
            prompt_hash=prompt_hash
        )

    def record_failure(self, signature):
        with self._lock:
            count = self._failure_history.get(signature, 0) + 1
            self._failure_history[signature] = count
            if count >= self.max_same_signature + 1:
                return EscalationLevel.HARD_FAIL
            elif count == self.max_same_signature:
                return EscalationLevel.ROLE_SWITCH
            else:
                return EscalationLevel.SELF_REPAIR

    def get_escalation_action(self, level, current_profile, original_prompt, error_message):
        if level == EscalationLevel.HARD_FAIL:
            return {"action": "abort", "error_type": "ESCALATION_HARD_FAIL"}
        elif level == EscalationLevel.ROLE_SWITCH:
            if self._role_switch_used.get(current_profile, False):
                return {"action": "abort", "error_type": "ROLE_SWITCH_EXHAUSTED"}
            self._role_switch_used[current_profile] = True
            new_profile = self.ROLE_SWITCH_MAP.get(current_profile, "reviewer")
            return {"action": "switch", "new_profile": new_profile, "modified_prompt": "[ROLE_SWITCH] " + original_prompt}
        else:
            return {"action": "retry", "modified_prompt": "[ERROR_FEEDBACK] " + original_prompt}

    def clear_history(self, profile=None):
        with self._lock:
            if profile:
                keys_to_remove = [k for k in self._failure_history if k.profile == profile]
                for k in keys_to_remove:
                    del self._failure_history[k]
                if profile in self._role_switch_used:
                    del self._role_switch_used[profile]
            else:
                self._failure_history.clear()
                self._role_switch_used.clear()


def run_tests():
    passed = 0
    failed = 0

    # Test 1: monotonic - escalation never decreases
    print("=== MONOTONIC Tests ===")
    e = RetryEscalator(max_same_signature=2)
    sig = e.compute_signature("JSON_PARSE_ERROR", ["summary"], "coder", "test prompt")

    level1 = e.record_failure(sig)
    level2 = e.record_failure(sig)
    level3 = e.record_failure(sig)

    if level1 == EscalationLevel.SELF_REPAIR and level2 == EscalationLevel.ROLE_SWITCH and level3 == EscalationLevel.HARD_FAIL:
        print("PASS: test_escalation_is_monotonic")
        passed += 1
    else:
        print(f"FAIL: test_escalation_is_monotonic ({level1}, {level2}, {level3})")
        failed += 1

    if level2.value >= level1.value and level3.value >= level2.value:
        print("PASS: test_level_never_decreases")
        passed += 1
    else:
        print("FAIL: test_level_never_decreases")
        failed += 1

    # Test 2: terminal - HARD_FAIL is terminal
    print("\n=== TERMINAL Tests ===")
    e2 = RetryEscalator(max_same_signature=2)
    sig2 = e2.compute_signature("FORMAT_ERROR", ["verdict"], "reviewer", "review task")
    e2.record_failure(sig2)
    e2.record_failure(sig2)
    level = e2.record_failure(sig2)

    if level == EscalationLevel.HARD_FAIL:
        action = e2.get_escalation_action(level, "reviewer", "original", "error")
        if action["action"] == "abort":
            print("PASS: test_hard_fail_is_terminal")
            passed += 1
        else:
            print("FAIL: test_hard_fail_is_terminal")
            failed += 1
    else:
        print("FAIL: test_hard_fail_is_terminal")
        failed += 1

    # Test 3: HARD_FAIL stays HARD_FAIL
    all_hard_fail = True
    for _ in range(10):
        l = e2.record_failure(sig2)
        if l != EscalationLevel.HARD_FAIL:
            all_hard_fail = False
    if all_hard_fail:
        print("PASS: test_hard_fail_no_recovery")
        passed += 1
    else:
        print("FAIL: test_hard_fail_no_recovery")
        failed += 1

    # Test 4: once - ROLE_SWITCH only once
    print("\n=== ONCE Tests ===")
    e3 = RetryEscalator(max_same_signature=2)

    action1 = e3.get_escalation_action(EscalationLevel.ROLE_SWITCH, "coder", "task1", "error1")
    if action1["action"] == "switch" and action1["new_profile"] == "reviewer":
        print("PASS: first role_switch allowed")
        passed += 1
    else:
        print("FAIL: first role_switch should be allowed")
        failed += 1

    action2 = e3.get_escalation_action(EscalationLevel.ROLE_SWITCH, "coder", "task2", "error2")
    if action2["action"] == "abort" and "ROLE_SWITCH_EXHAUSTED" in action2.get("error_type", ""):
        print("PASS: test_role_switch_only_once")
        passed += 1
    else:
        print("FAIL: test_role_switch_only_once")
        failed += 1

    # Test 5: role switch per profile
    action_qa = e3.get_escalation_action(EscalationLevel.ROLE_SWITCH, "qa", "qa task", "error")
    if action_qa["action"] == "switch":
        print("PASS: test_role_switch_per_profile")
        passed += 1
    else:
        print("FAIL: test_role_switch_per_profile")
        failed += 1

    # Test 6: clear resets role switch
    e3.clear_history("coder")
    action3 = e3.get_escalation_action(EscalationLevel.ROLE_SWITCH, "coder", "task", "error")
    if action3["action"] == "switch":
        print("PASS: test_role_switch_clear_resets")
        passed += 1
    else:
        print("FAIL: test_role_switch_clear_resets")
        failed += 1

    # Test 7: signature tests
    print("\n=== SIGNATURE Tests ===")
    e4 = RetryEscalator()
    sig_a = e4.compute_signature("JSON_PARSE_ERROR", ["field1"], "coder", "same prompt")
    sig_b = e4.compute_signature("JSON_PARSE_ERROR", ["field1"], "coder", "same prompt")
    if sig_a == sig_b:
        print("PASS: test_same_error_same_signature")
        passed += 1
    else:
        print("FAIL: test_same_error_same_signature")
        failed += 1

    sig_c = e4.compute_signature("SEMANTIC_NULL", [], "coder", "prompt")
    if sig_a != sig_c:
        print("PASS: test_different_error_different_signature")
        passed += 1
    else:
        print("FAIL: test_different_error_different_signature")
        failed += 1

    # Test 8: action tests
    print("\n=== ACTION Tests ===")
    e5 = RetryEscalator()

    action_retry = e5.get_escalation_action(EscalationLevel.SELF_REPAIR, "coder", "task", "error")
    if action_retry["action"] == "retry":
        print("PASS: test_self_repair_returns_retry")
        passed += 1
    else:
        print("FAIL: test_self_repair_returns_retry")
        failed += 1

    action_abort = e5.get_escalation_action(EscalationLevel.HARD_FAIL, "coder", "task", "error")
    if action_abort["action"] == "abort":
        print("PASS: test_hard_fail_returns_abort")
        passed += 1
    else:
        print("FAIL: test_hard_fail_returns_abort")
        failed += 1

    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    return failed == 0


if __name__ == "__main__":
    run_tests()
