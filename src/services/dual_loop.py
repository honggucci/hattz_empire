"""
Dual Loop Service - GPT-5.2 <-> Claude Opus Ping-Pong

CEO가 "최고!" 프리픽스로 요청하면:
1. GPT-5.2 (Strategist): 설계/분석/방향 제시
2. Claude CLI Opus (Coder): 구현/코드 작성
3. Claude CLI Opus (Reviewer): 리뷰/승인 여부 결정
4. APPROVE -> 완료, REVISE -> 다음 iteration

최대 5회 반복 후 자동 종료
"""
import json
import time
from typing import Generator, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

# LLM 호출
from src.core.llm_caller import call_llm
from src.services.cli_supervisor import call_claude_cli
from config import MODELS

# DB 저장 (v2.6.2 - Dual Loop 대화 영속화)
from src.services.database import add_message


class LoopVerdict(Enum):
    """리뷰어 판정"""
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    ABORT = "ABORT"


@dataclass
class LoopIteration:
    """한 번의 반복 결과"""
    iteration: int
    strategy: str
    implementation: str
    review: str
    verdict: LoopVerdict
    revision_notes: Optional[str] = None


class DualLoop:
    """GPT-5.2 <-> Claude Opus 핑퐁 루프"""

    MAX_ITERATIONS = 5

    def __init__(self, session_id: str, project: str = "hattz_empire"):
        self.session_id = session_id
        self.project = project
        self.iterations: list[LoopIteration] = []
        self.final_result: Optional[str] = None

        # 모델 설정
        self.gpt_config = MODELS["gpt_thinking"]      # GPT-5.2 Thinking
        # Claude는 CLI로 직접 호출 (API 키 불필요)

    def _call_gpt_strategist(self, task: str, context: str = "") -> str:
        """GPT-5.2 Strategist 호출 - 설계/분석"""
        system_prompt = """You are a Systems Architect (Strategist).

Your role:
1. Analyze the task requirements
2. Break down into implementation steps
3. Identify potential risks and edge cases
4. Provide clear direction for the coder

Output JSON only:
{
    "analysis": "task analysis",
    "steps": ["step1", "step2", ...],
    "risks": ["risk1", "risk2"],
    "direction": "clear implementation direction for coder"
}

No chatter. No explanations outside JSON."""

        messages = [
            {"role": "user", "content": f"Task: {task}\n\nContext: {context}" if context else f"Task: {task}"}
        ]

        response = call_llm(
            model_config=self.gpt_config,
            messages=messages,
            system_prompt=system_prompt,
            session_id=self.session_id,
            agent_role="dual_strategist"
        )
        return response

    def _call_claude_coder(self, strategy: str, task: str, revision_notes: str = "") -> str:
        """Claude CLI Coder 호출 - 구현 (API 키 불필요)"""
        system_prompt = """You are an Implementation Expert (Coder).

Your role:
1. Follow the strategist's direction exactly
2. Write clean, working code
3. Include minimal comments only where logic is complex
4. Output unified diff format when modifying existing code

Output format:
```language
// code here
```

If creating new code, output the full implementation.
If modifying existing code, output unified diff.

No explanations outside code blocks. No chatter."""

        user_content = f"""## Strategy Direction
{strategy}

## Original Task
{task}"""

        if revision_notes:
            user_content += f"""

## Revision Notes (from previous review)
{revision_notes}

Apply these fixes to improve the implementation."""

        messages = [
            {"role": "user", "content": user_content}
        ]

        # Claude CLI 직접 호출 (Opus profile)
        response = call_claude_cli(messages, system_prompt, profile="coder")
        return response

    def _call_opus_reviewer(self, task: str, strategy: str, implementation: str) -> Tuple[LoopVerdict, str]:
        """Claude Opus Reviewer 호출 - 리뷰/승인"""
        system_prompt = """You are a Code Reviewer.

Review the implementation against the strategy and original task.

Output JSON only:
{
    "verdict": "APPROVE" | "REVISE" | "ABORT",
    "issues": ["issue1", "issue2"],
    "revision_notes": "specific fixes needed",
    "quality_score": 0-100
}

Rules:
- APPROVE: Implementation is correct and complete
- REVISE: Fixable issues found, provide specific revision_notes
- ABORT: Fundamentally broken, cannot be fixed

Be strict but fair. Only APPROVE when truly ready."""

        user_message = f"""## Original Task
{task}

## Strategy
{strategy}

## Implementation
{implementation}

Review this implementation and output JSON verdict."""

        messages = [
            {"role": "user", "content": user_message}
        ]

        # Claude CLI 직접 호출 (Opus profile - reviewer)
        response = call_claude_cli(messages, system_prompt, profile="reviewer")

        # Parse verdict
        try:
            # JSON 추출
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "{" in response:
                start = response.index("{")
                end = response.rindex("}") + 1
                json_str = response[start:end]
            else:
                json_str = response

            data = json.loads(json_str)
            verdict = LoopVerdict(data.get("verdict", "REVISE"))
            revision_notes = data.get("revision_notes", "")
            return verdict, revision_notes
        except Exception as e:
            print(f"[DualLoop] Review parse error: {e}")
            return LoopVerdict.REVISE, "Review parsing failed, please retry"

    def run(self, task: str) -> Generator[Dict[str, Any], None, None]:
        """
        듀얼 루프 실행 (Generator로 진행 상황 yield)

        Yields:
            {"stage": "strategy|code|review|complete|error", "iteration": n, "content": str}
        """
        print(f"[DualLoop] Starting for task: {task[:100]}...")

        context = ""
        revision_notes = ""

        for i in range(1, self.MAX_ITERATIONS + 1):
            print(f"\n[DualLoop] === Iteration {i}/{self.MAX_ITERATIONS} ===")

            # 1. Strategy (GPT-5.2)
            yield {"stage": "strategy", "iteration": i, "content": f"GPT-5.2 Strategist analyzing..."}

            try:
                if i == 1:
                    strategy = self._call_gpt_strategist(task)
                else:
                    # 이전 리뷰 피드백 포함
                    strategy = self._call_gpt_strategist(
                        task,
                        context=f"Previous revision notes: {revision_notes}"
                    )
                print(f"[DualLoop] Strategy ({len(strategy)} chars)")

                # DB 저장 + RAG 임베딩
                add_message(
                    session_id=self.session_id,
                    role="assistant",
                    content=strategy,
                    agent="dual_strategist",
                    project=self.project,
                    is_internal=False  # CEO가 볼 수 있게
                )

                yield {"stage": "strategy_done", "iteration": i, "content": strategy}
            except Exception as e:
                yield {"stage": "error", "iteration": i, "content": f"Strategy error: {str(e)}"}
                return

            # 2. Implementation (Claude)
            yield {"stage": "code", "iteration": i, "content": f"Claude Opus implementing..."}

            try:
                implementation = self._call_claude_coder(strategy, task, revision_notes)
                print(f"[DualLoop] Implementation ({len(implementation)} chars)")

                # DB 저장 + RAG 임베딩
                add_message(
                    session_id=self.session_id,
                    role="assistant",
                    content=implementation,
                    agent="dual_coder",
                    project=self.project,
                    is_internal=False
                )

                yield {"stage": "code_done", "iteration": i, "content": implementation}
            except Exception as e:
                yield {"stage": "error", "iteration": i, "content": f"Implementation error: {str(e)}"}
                return

            # 3. Review (Claude Opus)
            yield {"stage": "review", "iteration": i, "content": f"Claude Opus Reviewer evaluating..."}

            try:
                verdict, revision_notes = self._call_opus_reviewer(task, strategy, implementation)
                print(f"[DualLoop] Review verdict: {verdict.value}")

                review_content = f"Verdict: {verdict.value}"
                if revision_notes:
                    review_content += f"\nRevision notes: {revision_notes}"

                # DB 저장 + RAG 임베딩
                add_message(
                    session_id=self.session_id,
                    role="assistant",
                    content=review_content,
                    agent="dual_reviewer",
                    project=self.project,
                    is_internal=False
                )

                yield {"stage": "review_done", "iteration": i, "content": review_content, "verdict": verdict.value}
            except Exception as e:
                yield {"stage": "error", "iteration": i, "content": f"Review error: {str(e)}"}
                return

            # Save iteration
            iteration_result = LoopIteration(
                iteration=i,
                strategy=strategy,
                implementation=implementation,
                review=review_content,
                verdict=verdict,
                revision_notes=revision_notes
            )
            self.iterations.append(iteration_result)

            # Check verdict
            if verdict == LoopVerdict.APPROVE:
                self.final_result = implementation
                yield {
                    "stage": "complete",
                    "iteration": i,
                    "content": implementation,
                    "total_iterations": i
                }
                print(f"[DualLoop] APPROVED at iteration {i}")
                return

            elif verdict == LoopVerdict.ABORT:
                yield {
                    "stage": "abort",
                    "iteration": i,
                    "content": f"Task aborted: {revision_notes}",
                    "reason": revision_notes
                }
                print(f"[DualLoop] ABORTED at iteration {i}")
                return

            # REVISE - continue to next iteration
            # revision_notes는 다음 iteration에서 자동으로 사용됨 (220줄)
            print(f"[DualLoop] REVISE - continuing to iteration {i+1}...")

        # Max iterations reached
        yield {
            "stage": "max_iterations",
            "iteration": self.MAX_ITERATIONS,
            "content": self.iterations[-1].implementation if self.iterations else "No implementation",
            "message": f"Max iterations ({self.MAX_ITERATIONS}) reached without approval"
        }
        print(f"[DualLoop] Max iterations reached")

    def run_sync(self, task: str) -> Dict[str, Any]:
        """동기 실행 - 최종 결과만 반환"""
        result = None
        for event in self.run(task):
            result = event
        return result


def run_dual_loop(task: str, session_id: str, project: str = "hattz_empire") -> Generator[Dict[str, Any], None, None]:
    """Dual Loop 실행 (외부 호출용)"""
    loop = DualLoop(session_id, project)
    yield from loop.run(task)


# 테스트용
if __name__ == "__main__":
    import sys
    sys.path.insert(0, "c:\\Users\\hahonggu\\Desktop\\coin_master\\hattz_empire")

    task = "Create a simple Python function to calculate fibonacci numbers with memoization"

    for event in run_dual_loop(task, "test-session"):
        print(f"\n[{event['stage']}] Iteration {event.get('iteration', '?')}")
        print(f"Content: {event['content'][:200]}...")
