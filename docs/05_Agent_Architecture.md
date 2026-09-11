# 역할 5 — 전체 구조도·동작 Flow·System Prompt

담당자: **석휘** · 브랜치: `feature/agent-core` · 선행 문서: [공통 계약](00_공통계약.md)

## 목표

각 담당자의 모듈을 하나의 Agent 흐름으로 연결한다. 조건 확인·Tool 선택·재계획·종료를 책임지며, 개별 Tool 내부 구현은 복제하지 않는다.

## 파일별 개발 지시

| 파일 | 개발할 내용 |
|---|---|
| `agent/main_agent.py` | Agent 생성·Tool 등록·Memory/Middleware 연결·UI 진입점·최종 출력 조립 |
| `agent/prompts.py` | 서비스 범위·Tool 선택·근거·누락·Mock·승인·종료 규칙 |
| `docs/설계서.md` | 전체 구조도·분기 흐름·모듈 의존성·상태 전이 |
| `tests/test_agent_flow.py` | 조건 누락·Tool 순서·재계획·종료·승인 흐름 |
| `README.md`, `requirements.txt`, `.env.example`, `.gitignore` | 실행 환경·버전·Mock 실행 안내·공통 설정 관리 |
| `tools/market_tools.py`, 제안 추가 `tools/action_tools.py` | 미배정 기능의 인터페이스·통합 책임을 맡는 추가 제안. 실 구현 담당은 팀이 별도 확정 |

`main_agent.py`는 이 역할이 수정한다. 다른 역할은 연결 요청과 테스트 방법을 전달한다.

## 입력/출력 계약

제안 진입점: `run_analysis(request: AgentRequest, context: RuntimeContext) -> StudySpotResponse`.

입력은 messages·business_conditions와 선택적 approval_decision이다. UI로부터 임의 State 전체나 권한을 받지 않는다. 모델 응답을 그대로 UI에 넘기지 않고 StudySpotResponse 검증 후 반환한다.

필수 입력 누락 → need_more_information. 추천 불가 → no_result. 검증한 후보 1~3개 → success. 외부 행동 준비 → approval_required. 시스템 실패는 공통 계약의 추가 제안에 따라 no_result와 분명한 오류 설명으로 전달한다.

## 구현할 흐름

```text
사용자 입력 + 신뢰 가능한 Context
  → State 복원 및 현재 조건 병합
  → 입력·보호 규칙 검사
  → 필수 조건 부족: 질문 후 종료
  → 지원 상권 검색 → 지역 식별자 해석
  → 상권·방문자·학원·경쟁·임대 데이터 조회
  → 인근 역 조회 → station_id로 출구 통행 데이터 조회
  → 오류/캐시/Mock/누락 검증
  → calculate_market_score
  → 후보 비교 → 근거 포함 Structured Output 검증 → UI

조건 변경 → 영향받는 상태 무효화 → 재계획
저장 요청 → Memory Tool
전송/일정 요청 → 실행 내용 제시 → 승인 대기
  → 승인·사용자·내용 일치 검증 → 외부 행동 → 결과 표시
  → 거절/내용 변경 → 미실행
```

실행 가능한 Tool만 등록한다. 미구현 선언을 등록하여 정상 호출처럼 보이게 하지 않는다. 여러 후보는 식별자로 구분하고 조회·계산 결과를 다른 상권과 섞지 않는다. 후보 3개를 채우려고 없는 지역을 생성하지 않는다.

## 미배정 Tool 계약 제안

| Tool | 입력 → 정상 data | 책임 |
|---|---|---|
| search_supported_districts | preferred_region → AreaIdentity 목록 | 지원 후보만 제공 |
| resolve_area_entities | 선택 후보 ID → AreaIdentity | 코드·좌표 정규화 |
| get_district_congestion | area, period → observations+missing_data | 장소 혼잡 원천 지표 |
| get_visitor_demographics | area, target_age, period → observations+missing_data | 연령·방문자 원천 지표 |
| search_competitors | area, radius_m → 점포 목록+기준 시점 | 경쟁 스터디카페 검색 |
| get_rent_and_closure_data | area, period → observations+missing_data | 임대·폐업 관련 지원 데이터 |
| send_analysis_report | 승인된 서버 측 action → 실행 결과 식별자 | 보고서 전송 |
| create_site_visit_event | 승인된 서버 측 action → 실행 결과 식별자 | 일정 생성 |

모두 ToolResult를 반환한다. 역할 4가 상세 payload를 선언한다. 역할 1의 3개 SK Tool은 이 표에 포함시켜 중복 구현하지 않는다. market/action 실 API 구현을 별도 배정하지 않았다면 Mock 데모 범위를 README에 명시한다. 비실행 Mock은 '실제 전송/등록되지 않음'을 표시한다.

## System Prompt 작성 요구

서비스 대상·지역 범위, 필수 조건 질문, 지원 Tool의 선택 조건, 식별자 의존 순서, Tool 근거만 사용, 점수 직접 생성 금지, Mock·누락 공개, 조건 변경 재분석, 승인 전 외부 행동 금지, 무관한 질문의 분석 Tool 미호출, 종료 조건을 포함한다.

전체 프롬프트를 이 문서에서 대신 구현하지 않는다. 작성 후 가짜 모델·Tool을 이용한 결정적인 흐름 테스트와 별도의 실제 모델 평가를 구분한다. 프롬프트만으로 승인·반복 제한을 보장하지 않고 역할 3의 실행 계층을 연결한다.

## 의존 모듈

역할 2는 State/Store, 역할 3은 보호·복구, 역할 4는 공통 모델·점수, 역할 1은 SK 데이터, 역할 6은 입출력 화면을 제공한다. 본 역할은 각 계약 버전·등록 여부·Mock 상태를 확인한다. 순환 import를 피하고 공통 모델이 UI·Agent 구현을 참조하지 않게 한다.

## 테스트 범위

| ID | 상황 | 통과 조건 |
|---|---|---|
| AGT-01 | 필수 입력 부족 | 필요한 질문, 데이터 Tool 0회 |
| AGT-02 | 정상 조건 | 지역→역→통행 의존성, 점수 Tool 사용, 최대 3개 결과 |
| AGT-03 | 지원 후보 없음 | no_result, 허위 후보 없음 |
| AGT-04 | 월세·시간 조건 변경 | 영향 상태 갱신 후 재계산 |
| AGT-05 | 일부 API 실패 | Mock/누락이 최종 근거에 표시 |
| AGT-06 | 관련 없는 질문 | 불필요한 데이터·행동 Tool 0회 |
| AGT-07 | 승인·거절·중복 승인 | 검증된 승인에서만 1회 이하 실행 |
| AGT-08 | 최대 반복·모델 실패 | 제한 내 종료, 구조화된 오류 설명 |

## 완료 조건

Mock 기반 전체 흐름이 API 키 없이 실행 가능하고, 상태·보호·점수·UI 경계가 일치한다. 설계서의 분기와 실제 연결 테스트가 대응한다. 실제 모델·외부 API·전송이 검증되지 않았다면 범위를 따로 기록한다.

## 금지사항

타 담당 로직 복사, 점수 직접 계산, API 키·모델 내부 상태를 UI에 노출, 미구현 Tool 등록, 프롬프트 지시만으로 승인 처리, 오류를 정상 추천으로 위장하는 행위를 금지한다.

## PR 체크리스트

- [ ] 공통 PR 체크리스트 충족
- [ ] 구조도·Tool 등록 목록·미구현 범위 최신화
- [ ] UI 진입점과 State·Middleware 연결 검토
- [ ] 필수 조건·재계획·종료·승인 흐름 테스트 첨부
- [ ] 공통 버전·Mock 실행·검증 방법 문서화
- [ ] 미배정 Tool의 담당/보류 상태 명시
