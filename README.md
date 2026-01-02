# Hattz Empire

멀티 AI 협업 시스템. 듀얼 엔진 아키텍처 기반.

## 개요

여러 LLM(Claude, GPT, Gemini)이 각자의 역할을 수행하며 협업하는 AI 오케스트레이션 시스템.

## 팀 구성

| 역할 | 엔진 | 설명 |
|------|------|------|
| Excavator | Claude + GPT | CEO 의도 발굴 |
| Strategist | GPT + Gemini | 전략 연구 |
| Coder | Claude + GPT | 코드 생성 |
| QA | GPT + Claude | 코드 검증 |
| Analyst | Gemini | 로그 분석 |

## 설치

```bash
pip install -r requirements.txt
```

## 환경 설정

`.env.example`을 `.env`로 복사 후 API 키 설정:

```bash
cp .env.example .env
```

## 상세 문서

시스템 프롬프트 및 상세 설정은 `PROMPT.md` 참조 (gitignore 대상).
