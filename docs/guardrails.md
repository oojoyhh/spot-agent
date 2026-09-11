# Guardrail / Middleware 운영 기준

이 문서는 최신 Agent 등록 상태와 역할 3의 신뢰 경계를 정리한다. Guardrail은
분석·scoring·최종 응답 생성을 대체하지 않고, 각 경계에서 입력·출력·근거·실행을
검사한다.

## Guardrail 정책

| 정책 | 책임 | 상태 |
| --- | --- | --- |
| Prompt Injection | 사용자 입력의 기존 지시 무시·역할 override를 Agent 실행 전에 차단 | ✅ 등록됨 |
| Secret Disclosure | System Prompt/API Key/환경변수 공개 요청 차단 및 실제 secret 형태의 모델 출력 치환 | ✅ 등록됨 |
| PII | email·전화번호를 모델 입출력 및 저장 경계에서 redaction | ✅ 등록됨 |
| 상세주소 | 구·동 수준 coarse location을 안전하게 추출하면 span만 정제하고, 불가하면 차단 | ✅ 등록됨 |
| Tool-output Injection | Tool 결과의 privileged instruction text만 치환하고 숫자·id·source·목록을 보존 | ✅ 등록됨 |
| NoData | `NO_DATA`, `AREA_NOT_FOUND`, `STATION_NOT_FOUND`를 evidence 불가로 분류. 정상 0건과 성공한 `missing_data`는 유지 | 🟡 core 완료 |
| UnsupportedData | 최종 추천의 상권·점수·Tool provenance·수치 evidence를 검증된 결과와 대조 | 🟡 core 완료 |
| Sensitive Action | 승인된 `PendingAction`의 action/user/session을 실제 전송 직전에 재검증 | ✅ Agent 승인 경로에서 사용 |
| MaxIteration | 반복 허용 여부를 판정하는 순수 정책 | 🟡 core 완료 |

`UnsupportedData`는 strengths, risks, summary 같은 자연어를 문자열 비교하지 않는다.
대신 `commercial_area_id`, `area_name`, 세부 점수와 `total_score`, `source`,
`is_mock`, `metric_name/value/unit`을 `AreaIdentity`, `MarketScore`, `ToolResult`와
대조한다. 위반 시 현재 core는 `UNSUPPORTED_DATA`로 판정만 하며 response를 직접
삭제·변환하지 않는다.

## Retry / Fallback

- retryable: `API_TIMEOUT`, `API_RATE_LIMIT`, `API_RESPONSE_ERROR`
- non-retryable: `API_AUTH_ERROR`, `API_BAD_REQUEST`, `INVALID_INPUT`,
  `UNSUPPORTED_AREA`, `AREA_NOT_FOUND`, `STATION_NOT_FOUND`, `NO_DATA`,
  `MISSING_REQUIRED_INPUT`, `TOOL_INTERNAL_ERROR`
- 최대 호출: 최초 1회 + 재시도 2회, 총 3회
- 정상 `success=True, competitors=[]`는 정상 0건이며 fallback하지 않는다.

현재 runtime fallback은 `실제 Tool → retry → Mock → 원래 failure`다. Mock은
`mock_tool_call_provider`가 제공하며, 성공 결과에는 `is_mock=True`와
`source=mock:<tool_name>`가 남고 원 API failure의 `error_code/error_message`도
Mock provenance로 유지한다.

Cache provider interface는 retry middleware에 주입 가능하지만, cache key·저장소·TTL·
validity/invalidation 계약이 아직 없다. TTL 없는 cache 사용은 명세와 충돌하므로
실제 Cache → Mock runtime 등록은 **⚠️ 계약 변경 필요** 상태다. 확정 후에는
`실제 Tool → retry → Cache → Mock → 원래 failure` 순서를 사용한다. Cache에는 성공한
실제 API 결과(`success=True`, `is_mock=False`)만 저장하고 Mock·실패·NoData 결과는
저장하지 않는다.

## Agent runtime 등록 상태

현재 `agent/main_agent.py`는 다음 Tool middleware 순서로 등록한다.

```text
require_analysis_conditions
→ tool_output_guardrail
→ create_tool_retry_middleware(mock_provider=mock_tool_call_provider)
→ collect_analysis_results
```

따라서 Tool-output Injection Guardrail 및 Retry + Mock fallback은 이미 runtime에
등록되어 있다. 중복 middleware를 추가하지 않는다.

NoData와 UnsupportedData는 최종 응답을 안전하게 처리할 정책과 Tool call-id ↔ tool-name
mapping을 Agent가 제공한 뒤 lifecycle adapter로 연결한다. MaxIteration은 공식 iteration
counter가 State/runtime에 제공될 때 before-model adapter로 연결한다.

## 승인 상태 전이

`PendingAction`은 `pending → approved/rejected`로 전이한다. `run_analysis()`는
사용자·세션·`action_id`·`payload_version`을 저장된 action과 대조하고, approve 직전에
`ensure_sensitive_action_approved()`를 호출한다. receipt와 `attempt_started`를 저장해
duplicate approval 또는 완료 여부가 불명확한 action을 재실행하지 않는다. 현재 MVP는
`send_analysis_report`만 대상이며 HumanInTheLoopMiddleware를 별도로 등록하지 않는다.

## 현재 제한사항

- Cache TTL, key normalization, validity/invalidation과 저장소 계약이 없다.
- 공식 Agent iteration counter 및 한도 도달 시 최종 UI 응답 계약이 없다.
- UnsupportedData/NoData 위반을 evidence 제거·recommendation 제외·`no_result` 중 어떤
  방식으로 처리할지 Agent/structured-output 담당 합의가 필요하다.
- State의 Tool 결과는 call-id 중심이므로 final evidence 검증에는 Tool call-id ↔ tool-name
  mapping 계약이 필요하다.
