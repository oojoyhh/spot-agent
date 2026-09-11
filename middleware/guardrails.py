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

``inspect_tool_result_for_no_data``는 retry/fallback 없이 개별 ToolResult가
분석 근거로 사용 가능한지 판정한다. data absence와 실행 오류를 구분하며,
일부 ``missing_data`` 또는 정상 0건 성공 결과를 실패로 바꾸지 않는다.

Prompt Injection은 기존 지시 체계를 변경하려는 요청이고, Secret
Disclosure는 System Prompt/API Key 같은 내부정보 공개 요청이다. Detailed
Address는 MVP 입력 정책에 따라 coarse location으로 정제할 수 있을 때만
Agent/Tool에 전달하고, 그렇지 않으면 실행 전에 차단한다. 정규식 탐지는 알려진
공격 신호를 줄이는 1차 방어선일 뿐 모든 injection이나 주소 형식을 완전히
탐지한다고 가정하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from langchain.agents.middleware import AgentMiddleware, PIIMiddleware, after_model, before_agent
from langchain.messages import AIMessage
from models.schemas import ErrorCode, ToolResult

PROMPT_INJECTION = "PROMPT_INJECTION"
SECRET_DISCLOSURE = "SECRET_DISCLOSURE"
DETAILED_ADDRESS = "DETAILED_ADDRESS"
SAFE_OUTPUT_MESSAGE = "응답에 보호해야 할 내부 정보가 포함되어 있어 해당 내용을 제공할 수 없습니다."
_NO_DATA_EVIDENCE_CODES = frozenset({
    ErrorCode.NO_DATA,
    ErrorCode.AREA_NOT_FOUND,
    ErrorCode.STATION_NOT_FOUND,
})


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
    re.compile(r"(?:[가-힣A-Za-z0-9]+)?(?:아파트|APT)\s*\d{1,4}\s*동\s*\d{1,5}\s*호", re.I),
    re.compile(r"(?:[가-힣A-Za-z0-9]+(?:빌딩|건물))\s*\d{1,3}\s*층(?:\s*\d{1,5}\s*호)?"),
    re.compile(r"(?:[가-힣]+(?:구|동))\s+\d{1,4}\s*-\s*\d{1,4}\b"),
)
_ROAD_ADDRESS_PATTERN = _DETAILED_ADDRESS_PATTERNS[0]
_BUNJI_PATTERN = _DETAILED_ADDRESS_PATTERNS[1]
_APARTMENT_DETAIL_PATTERN = _DETAILED_ADDRESS_PATTERNS[2]
_BUILDING_DETAIL_PATTERN = _DETAILED_ADDRESS_PATTERNS[3]
_DONG_LOT_PATTERN = re.compile(r"(?P<dong>[가-힣]+동)\s+\d{1,4}\s*-\s*\d{1,4}\b")
_COARSE_LOCATION_PATTERNS = (
    re.compile(r"(?:(?:서울(?:특별시)?\s+)?[가-힣]+구\s+[가-힣]+동)"),
    re.compile(r"(?:서울(?:특별시)?\s+)?[가-힣]+구"),
    re.compile(r"[가-힣]+동"),
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
        coarse_location = extract_coarse_location(value)
        if coarse_location is not None:
            return GuardrailDecision(True, sanitized_value=sanitize_detailed_address(value))
        return GuardrailDecision(False, DETAILED_ADDRESS)
    return GuardrailDecision(True, sanitized_value=value)


def detect_detailed_address(value: str) -> bool:
    """MVP에 불필요한 명확한 상세 주소만 보수적으로 탐지한다."""
    return any(pattern.search(value) for pattern in _DETAILED_ADDRESS_PATTERNS)


def extract_coarse_location(value: str) -> str | None:
    """상세 주소에서 안전하게 재사용할 수 있는 구·동 수준 위치만 추출한다."""
    for pattern in _COARSE_LOCATION_PATTERNS:
        if match := pattern.search(value):
            return match.group(0)
    return None


def sanitize_detailed_address(value: str) -> str:
    """상세 주소 span만 제거해 구·동 위치와 사용자의 분석 의도를 함께 보존한다."""
    sanitized = _ROAD_ADDRESS_PATTERN.sub("", value)
    sanitized = _APARTMENT_DETAIL_PATTERN.sub("", sanitized)
    sanitized = _BUILDING_DETAIL_PATTERN.sub("", sanitized)
    sanitized = _DONG_LOT_PATTERN.sub(r"\g<dong>", sanitized)
    sanitized = _BUNJI_PATTERN.sub("", sanitized)
    sanitized = re.sub(r"\s+(?=에서)", "", sanitized)
    return re.sub(r"\s{2,}", " ", sanitized).strip()


def inspect_model_output(value: str) -> GuardrailDecision:
    """실제 secret 값 또는 내부 prompt 원문을 드러내는 출력 형태만 차단한다."""
    if any(pattern.search(value) for pattern in _OUTPUT_SECRET_PATTERNS):
        return GuardrailDecision(False, SECRET_DISCLOSURE, SAFE_OUTPUT_MESSAGE)
    return GuardrailDecision(True, sanitized_value=value)


def inspect_tool_result_for_no_data(tool_result: ToolResult) -> GuardrailDecision:
    """ToolResult가 정상 분석 evidence로 사용 가능한지 data absence와 실행 오류를 구분해 판정한다."""
    if tool_result.success:
        return GuardrailDecision(True)
    if tool_result.error_code in _NO_DATA_EVIDENCE_CODES:
        return GuardrailDecision(False, tool_result.error_code.value)
    return GuardrailDecision(False, tool_result.error_code.value if tool_result.error_code else None)


def _last_message_text(messages: Iterable[Any]) -> str:
    for message in reversed(list(messages)):
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        if isinstance(content, str):
            return content
    return ""


def _replace_last_message_content(messages: Iterable[Any], sanitized_value: str) -> list[Any]:
    """상세 주소 원문이 이후 Agent/Tool에 전달되지 않도록 마지막 입력을 교체한다."""
    updated_messages = list(messages)
    for index in range(len(updated_messages) - 1, -1, -1):
        message = updated_messages[index]
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        if not isinstance(content, str):
            continue
        if isinstance(message, dict):
            updated_messages[index] = {**message, "content": sanitized_value}
        else:
            updated_messages[index] = message.model_copy(update={"content": sanitized_value})
        return updated_messages
    return updated_messages


@before_agent(can_jump_to=["end"])
def input_guardrail(state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
    """위험 입력이면 모델 및 Tool 노드로 가기 전에 agent를 종료한다."""
    messages = state.get("messages", [])
    user_input = _last_message_text(messages)
    decision = inspect_user_input(user_input)
    if decision.allowed:
        if decision.sanitized_value is not None and decision.sanitized_value != user_input:
            return {"messages": _replace_last_message_content(messages, decision.sanitized_value)}
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


# 상세 주소는 masking하지 않는다. coarse location을 추출하면 정제해 전달하고,
# 추출하지 못하면 before_agent에서 차단한다. 구·동·역·상권은 정상 분석 입력이다.
PHONE_NUMBER_PATTERN = r"(?<!\d)(?:\+?82[-\s]?)?0?1[0-9][\s-]?\d{3,4}[\s-]?\d{4}(?!\d)"


# 안전 판정 뒤 모델 입출력과 저장 경계에서 PII를 분리해 보호한다.
def _build_pii_rules() -> list[PIIMiddleware]:
    return [
        PIIMiddleware("email", strategy="redact", apply_to_input=True, apply_to_output=True),
        PIIMiddleware("phone_number", detector=PHONE_NUMBER_PATTERN, strategy="redact", apply_to_input=True, apply_to_output=True),
    ]


class _SequentialPIIMiddleware(AgentMiddleware):
    """여러 PII 규칙의 message 교체를 하나의 lifecycle update로 합친다.

    LangGraph의 ``messages`` reducer는 같은 message id의 마지막 update만 반영한다.
    email/phone 규칙을 순차 적용해 두 종류의 PII가 모두 다음 Model 단계에서 제거되게 한다.
    """

    def __init__(self, middlewares: list[PIIMiddleware]) -> None:
        self.middlewares = middlewares

    def before_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        return self._apply("before_model", state, runtime)

    def after_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        return self._apply("after_model", state, runtime)

    def _apply(self, hook_name: str, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        current_state = state
        changed = False
        for middleware in self.middlewares:
            update = getattr(middleware, hook_name)(current_state, runtime)
            if update is not None:
                current_state = {**current_state, **update}
                changed = True
        return {"messages": current_state["messages"]} if changed else None


def build_pii_middlewares() -> list[AgentMiddleware]:
    """LangChain 내장 email detector와 한국 전화번호 detector를 순차 적용한다."""
    return [_SequentialPIIMiddleware(_build_pii_rules())]


def mask_pii_for_storage(value: str) -> str:
    """저장/로그 경계용 마스킹 helper. 원문을 출력하지 않는다."""
    masked = value
    for middleware in _build_pii_rules():
        # TODO: LangChain private API 의존. Store 통합 시 public integration 경로 또는 안정된 sanitizer로 교체 검토.
        masked_value, _ = middleware._process_content(masked)
        if not isinstance(masked_value, str):
            raise TypeError("PII masking expected string content")
        masked = masked_value
    return masked
