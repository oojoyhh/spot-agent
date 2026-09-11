"""Agent Graph의 입력 보호 경계.

실행 흐름: 사용자 입력 → Input Guardrail → PII 처리 → 안전한 입력만
Agent/Model 단계로 전달한다.

``inspect_user_input``은 framework와 독립적으로 정책을 판정하고,
``input_guardrail``은 LangChain ``before_agent`` hook에서 위험 요청을
Agent 실행 전에 종료한다. ``build_pii_middlewares``는 email/phone을
모델 입력·출력에서 보호하며, ``mask_pii_for_storage``는 저장 경계의
보조 helper다.

``inspect_model_output``은 모델 응답의 실제 내부정보 노출 형태를
framework와 독립적으로 검사한다. ``output_secret_guardrail``은
``after_model`` hook에서 위반 응답을 고정 안전 문구로 교체한다.

Prompt Injection은 기존 지시 체계를 변경하려는 요청이고, Secret
Disclosure는 System Prompt/API Key 같은 내부정보 공개 요청이다. Detailed
Address는 마스킹 후 처리하지 않고 MVP 입력 정책에 따라 Agent/Tool에
전달하기 전 차단한다. 정규식 탐지는 알려진 공격 신호를 줄이는 1차 방어선일
뿐 모든 injection이나 주소 형식을 완전히 탐지한다고 가정하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from langchain.agents.middleware import PIIMiddleware, after_model, before_agent
from langchain.messages import AIMessage

PROMPT_INJECTION = "PROMPT_INJECTION"
SECRET_DISCLOSURE = "SECRET_DISCLOSURE"
DETAILED_ADDRESS = "DETAILED_ADDRESS"
SAFE_OUTPUT_MESSAGE = "응답에 보호해야 할 내부 정보가 포함되어 있어 해당 내용을 제공할 수 없습니다."


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
_DETAILED_ADDRESS_PATTERNS = (
    re.compile(r"(?:[가-힣A-Za-z]+(?:로|길))\s*\d{1,5}(?:\s*-\s*\d{1,4})?"),
    re.compile(r"\d{1,4}(?:\s*-\s*\d{1,4})?\s*번지"),
    re.compile(r"(?:아파트|APT)\s*\d{1,4}\s*동\s*\d{1,5}\s*호", re.I),
)
_OUTPUT_SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bbearer\s+[A-Za-z0-9._~-]{16,}\b", re.I),
    re.compile(r"\b(?:api[ _-]?key|access[ _-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9._~-]{12,}", re.I),
    re.compile(r"\b(?:secret|password)\s*[:=]\s*['\"]?[^\s'\"]{8,}", re.I),
    re.compile(r"비밀번호\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
    re.compile(r"(?:system|developer)\s+prompt\s*[:=]\s*\S+", re.I),
    re.compile(r"(?:시스템|개발자)\s*프롬프트\s*[:=]\s*\S+"),
)


# Agent Graph에 연결되기 전에도 검증 가능한 입력 보안 정책 계층.
def inspect_user_input(value: str) -> GuardrailDecision:
    """알려진 인젝션/비밀 공개 요청을 검사한다; 원문을 기록하지 않는다."""
    if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        return GuardrailDecision(False, SECRET_DISCLOSURE)
    if any(pattern.search(value) for pattern in _INJECTION_PATTERNS):
        return GuardrailDecision(False, PROMPT_INJECTION)
    if detect_detailed_address(value):
        return GuardrailDecision(False, DETAILED_ADDRESS)
    return GuardrailDecision(True, sanitized_value=value)


def detect_detailed_address(value: str) -> bool:
    """MVP에 불필요한 명확한 상세 주소만 보수적으로 탐지한다."""
    return any(pattern.search(value) for pattern in _DETAILED_ADDRESS_PATTERNS)


def inspect_model_output(value: str) -> GuardrailDecision:
    """실제 secret 값 또는 내부 prompt 원문을 드러내는 출력 형태만 차단한다."""
    if any(pattern.search(value) for pattern in _OUTPUT_SECRET_PATTERNS):
        return GuardrailDecision(False, SECRET_DISCLOSURE, SAFE_OUTPUT_MESSAGE)
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
    if decision.reason == DETAILED_ADDRESS:
        message = (
            "상세 주소는 개인정보 보호를 위해 분석에 사용하지 않습니다. "
            "구·동·역·상권 단위의 희망 지역을 입력해 주세요. "
            "왼쪽 분석 조건 입력폼이나 채팅에서 모두 입력할 수 있습니다."
        )
    else:
        message = f"요청이 안전 정책에 의해 차단되었습니다. ({decision.reason})"
    return {
        "messages": [AIMessage(content=message)],
        "jump_to": "end",
    }


@after_model(can_jump_to=["end"])
def output_secret_guardrail(state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
    """모델 응답의 secret 노출을 사용자 반환 전에 고정 안전 문구로 치환한다."""
    messages = state.get("messages", [])
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, AIMessage) or not isinstance(message.content, str):
            continue
        decision = inspect_model_output(message.content)
        if decision.allowed:
            return None
        updated_messages = list(messages)
        updated_messages[index] = message.model_copy(update={"content": SAFE_OUTPUT_MESSAGE})
        return {"messages": updated_messages, "jump_to": "end"}
    return None


# 상세 주소는 masking 대상이 아니라 MVP 입력 정책상 before_agent에서 차단한다.
# 구·동·역·상권 단위 위치는 정상 분석 입력으로 Agent에 전달한다.
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
