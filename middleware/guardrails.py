"""Agent Graph의 입력 보호 경계.

실행 흐름: 사용자 입력 → Input Guardrail → PII 처리 → 안전한 입력만
Agent/Model 단계로 전달한다.

``inspect_user_input``은 framework와 독립적으로 정책을 판정하고,
``input_guardrail``은 LangChain ``before_agent`` hook에서 위험 요청을
Agent 실행 전에 종료한다. ``build_pii_middlewares``는 email/phone을
모델 입력·출력에서 보호하며, ``mask_pii_for_storage``는 저장 경계의
보조 helper다.

Prompt Injection은 기존 지시 체계를 변경하려는 요청이고, Secret
Disclosure는 System Prompt/API Key 같은 내부정보 공개 요청이다. 정규식
탐지는 알려진 공격 신호를 줄이는 1차 방어선일 뿐 모든 injection을
완전히 탐지한다고 가정하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from langchain.agents.middleware import PIIMiddleware, before_agent
from langchain.messages import AIMessage

PROMPT_INJECTION = "PROMPT_INJECTION"
SECRET_DISCLOSURE = "SECRET_DISCLOSURE"


@dataclass(frozen=True)
class GuardrailDecision:
    """프레임워크와 독립적인 입력 검사 결과."""

    allowed: bool
    reason: str | None = None
    sanitized_value: str | None = None


_INJECTION_PATTERNS = (
    re.compile(r"(?:이전|기존|앞선)\s*(?:지시|명령|규칙).{0,20}(?:무시|ignore)", re.I),
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|rules?)", re.I),
    re.compile(r"(?:역할|role).{0,20}(?:변경|바꿔|change|override)", re.I),
)
_SECRET_PATTERNS = (
    re.compile(r"(?:api[ _-]?key|access[ _-]?token|secret|비밀번호|인증\s*정보).{0,20}(?:알려|보여|공개|출력|reveal|show|print)", re.I),
    re.compile(r"(?:environment\s*variables?|환경\s*변수|내부\s*설정).{0,20}(?:알려|보여|공개|출력|reveal|show|print)", re.I),
    re.compile(r"(?:system\s*prompt|시스템\s*프롬프트|developer\s*prompt|내부\s*지시).{0,20}(?:알려|보여|공개|출력|reveal|show|print)", re.I),
)


# Agent Graph에 연결되기 전에도 검증 가능한 입력 보안 정책 계층.
def inspect_user_input(value: str) -> GuardrailDecision:
    """알려진 인젝션/비밀 공개 요청을 검사한다; 원문을 기록하지 않는다."""
    if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        return GuardrailDecision(False, SECRET_DISCLOSURE)
    if any(pattern.search(value) for pattern in _INJECTION_PATTERNS):
        return GuardrailDecision(False, PROMPT_INJECTION)
    return GuardrailDecision(True, sanitized_value=value)


def _last_message_text(messages: Iterable[Any]) -> str:
    for message in reversed(list(messages)):
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        if isinstance(content, str):
            return content
    return ""


@before_agent(can_jump_to=["end"])
def input_guardrail(state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
    """위험 입력이면 모델 및 Tool 노드로 가기 전에 agent를 종료한다."""
    decision = inspect_user_input(_last_message_text(state.get("messages", [])))
    if decision.allowed:
        return None
    return {
        "messages": [AIMessage(content=f"요청이 안전 정책에 의해 차단되었습니다. ({decision.reason})")],
        "jump_to": "end",
    }


# 주소는 분석 대상 상권/사업장 위치일 수 있어 1차 규칙 기반 마스킹에서 제외한다.
PHONE_NUMBER_PATTERN = r"(?<!\d)(?:\+?82[-\s]?)?0?1[0-9][\s-]?\d{3,4}[\s-]?\d{4}(?!\d)"


# 안전 판정 뒤 모델 입출력과 저장 경계에서 PII를 분리해 보호한다.
def build_pii_middlewares() -> list[PIIMiddleware]:
    """LangChain 내장 email detector와 한국 전화번호 custom detector를 사용한다."""
    return [
        PIIMiddleware("email", strategy="redact", apply_to_input=True, apply_to_output=True),
        PIIMiddleware("phone_number", detector=PHONE_NUMBER_PATTERN, strategy="redact", apply_to_input=True, apply_to_output=True),
    ]


def mask_pii_for_storage(value: str) -> str:
    """저장/로그 경계용 마스킹 helper. 원문을 출력하지 않는다."""
    masked = value
    for middleware in build_pii_middlewares():
        # TODO: LangChain private API 의존. Store 통합 시 public integration 경로 또는 안정된 sanitizer로 교체 검토.
        masked_value, _ = middleware._process_content(masked)
        if not isinstance(masked_value, str):
            raise TypeError("PII masking expected string content")
        masked = masked_value
    return masked
