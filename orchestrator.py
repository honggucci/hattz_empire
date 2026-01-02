"""
QWAS AI Team Orchestrator
에이전트 간 통신 및 워크플로우 관리
"""
from typing import Optional
from dataclasses import dataclass

from .agents import (
    get_secretary, get_qa, get_archivist,
    StructuredRequest, QAReport
)


@dataclass
class WorkflowResult:
    """워크플로우 실행 결과"""
    success: bool
    request: Optional[StructuredRequest]
    pm_response: Optional[str]
    qa_report: Optional[QAReport]
    archived: bool
    error: Optional[str] = None


class Orchestrator:
    """
    QWAS AI Team Orchestrator

    워크플로우:
    1. CEO (한글) → Secretary (정리+번역)
    2. Secretary → PM (코드 작성)
    3. PM → QA (검증)
    4. All → Archivist (백업)
    """

    def __init__(self):
        self.secretary = get_secretary()
        self.qa = get_qa()
        self.archivist = get_archivist()

    def process_request(self, korean_input: str) -> WorkflowResult:
        """
        CEO의 한글 요청을 전체 워크플로우로 처리

        Args:
            korean_input: CEO의 한글 요청

        Returns:
            WorkflowResult
        """
        # Step 1: Secretary - 정리 + 번역
        print("\n[Orchestrator] Step 1: Secretary processing...")
        request = self.secretary.process(korean_input)

        if not request:
            return WorkflowResult(
                success=False,
                request=None,
                pm_response=None,
                qa_report=None,
                archived=False,
                error="Secretary failed to process request"
            )

        print(f"  → Type: {request.request_type}")
        print(f"  → Summary: {request.summary}")
        print(f"  → Priority: {request.priority}")

        # Step 2: PM 에게 전달 (Claude - 현재 세션에서 처리됨)
        # PM은 Claude Code 자체이므로 여기서는 요청서만 반환
        pm_prompt = self._build_pm_prompt(request)
        print("\n[Orchestrator] Step 2: Request prepared for PM (Claude)")
        print(f"  → Prompt length: {len(pm_prompt)} chars")

        # Step 3: 아카이브
        print("\n[Orchestrator] Step 3: Archiving...")
        self.archivist.record(
            content=f"Request: {request.summary}\n\nOriginal: {korean_input}",
            participants=["CEO", "Secretary"],
            topics=request.related_modules,
            decisions=[],
            action_items=request.requirements
        )

        return WorkflowResult(
            success=True,
            request=request,
            pm_response=pm_prompt,
            qa_report=None,  # QA는 코드 작성 후 실행
            archived=True
        )

    def _build_pm_prompt(self, request: StructuredRequest) -> str:
        """PM용 프롬프트 생성"""
        return f"""## New Request from Secretary

**Type:** {request.request_type}
**Priority:** {request.priority}
**Summary:** {request.summary}

### Requirements:
{chr(10).join(f"- {r}" for r in request.requirements)}

### Context:
{request.context}

### Related Modules:
{', '.join(request.related_modules) if request.related_modules else 'Not specified'}

---
Please implement this request following WPCN coding standards."""

    def review_code(self, code: str, context: str = "") -> QAReport:
        """
        코드 리뷰 요청

        Args:
            code: 리뷰할 코드
            context: 추가 컨텍스트

        Returns:
            QAReport
        """
        print("\n[Orchestrator] QA reviewing code...")
        report = self.qa.review_code(code, context)

        if report:
            print(f"  → Status: {report.status}")
            print(f"  → Issues: {len(report.issues)}")
            print(f"  → Suggestions: {len(report.suggestions)}")

            # Archive the review
            self.archivist.record(
                content=f"QA Review:\nStatus: {report.status}\nSummary: {report.summary}",
                participants=["PM", "QA"],
                topics=["code_review"],
                decisions=[f"Code {report.status}"],
                action_items=[issue.get("fix", "") for issue in report.issues]
            )

        return report

    def get_project_context(self, tokens: int = 10000) -> str:
        """프로젝트 컨텍스트 가져오기"""
        return self.archivist.get_context(tokens)

    def search_history(self, query: str) -> list:
        """히스토리 검색"""
        return self.archivist.search(query)


# =============================================================================
# CLI Interface
# =============================================================================

def main():
    """CLI entry point"""
    import sys

    orchestrator = Orchestrator()

    if len(sys.argv) > 1:
        # Command line input
        korean_input = " ".join(sys.argv[1:])
        result = orchestrator.process_request(korean_input)

        if result.success:
            print("\n" + "="*60)
            print("REQUEST FOR PM (Claude)")
            print("="*60)
            print(result.pm_response)
        else:
            print(f"\nError: {result.error}")
    else:
        # Interactive mode
        print("="*60)
        print("QWAS AI Team Orchestrator")
        print("="*60)
        print("Enter your request in Korean (or 'quit' to exit):\n")

        while True:
            try:
                korean_input = input("CEO> ").strip()
                if korean_input.lower() in ['quit', 'exit', 'q']:
                    break
                if not korean_input:
                    continue

                result = orchestrator.process_request(korean_input)

                if result.success:
                    print("\n" + "-"*40)
                    print("PM PROMPT:")
                    print("-"*40)
                    print(result.pm_response)
                    print("-"*40 + "\n")
                else:
                    print(f"\nError: {result.error}\n")

            except KeyboardInterrupt:
                print("\nGoodbye!")
                break


if __name__ == "__main__":
    main()
