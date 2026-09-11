# StudySpot 모듈 연결 규격

이 문서는 UI, Agent, Tool, Memory, Middleware가 주고받을 값을 정리한다. `8반_1조_설계서(초안).docx`의 2.4·2.5·3.1절에 명시된 이름과 타입을 기준으로 하며, 구현에 필요한 보완사항은 **연결 제안**, 아직 정하지 못한 정책은 **합의 필요**로 표시한다. 제안된 필드와 함수 배치는 팀 합의가 끝난 규격이 아니다.

작성 시점인 2026-09-10에는 `models/schemas.py`, `agent/main_agent.py` 등 통합 코드는 없다. 이 문서는 구현을 위한 계약 초안이다. [전체 구조](architecture.md) · [동작 흐름](flow.md)

## 1. 공통 원칙

1. UI는 메시지와 Runtime Context를 Agent 진입점에 전달하고, 검증된 `StudySpotResponse`를 화면에 표시한다. 진입 함수명과 동기·비동기 방식은 아직 정하지 않았다.
2. Tool은 원천 응답을 공통 `ToolResult`로 변환한다. Agent가 API마다 다른 원문 필드를 직접 해석하지 않도록 한다.
3. 식별자는 이름 대신 코드로 연결한다. 같은 이름의 상권·역을 문자열만으로 결합하지 않는다.
4. 조회 실패나 없는 데이터는 `null` 또는 실패·누락 정보로 전달한다. 확인된 0과 미확보 값을 구분한다.
5. 총점, 세부 점수, 신뢰도는 합의한 결정론적 계산 정책으로 반환한다. LLM은 값을 만들거나 수정하지 않는다.
6. Runtime Context의 사용자 정보와 승인 상태를 실행 계층에서 확인한다. 모델이 생성한 `user_id`나 승인 플래그는 실행 권한이 아니다.

## 2. UI 입력과 상태

### Runtime Context

| 필드 | 타입 | 원문 기준과 연결 방식 |
| --- | --- | --- |
| `user_id` | `str` | 애플리케이션이 제공하는 사용자 식별자. Store 분리에 사용한다. |
| `session_id` | `str` | 애플리케이션이 제공하는 세션 식별자. 같은 대화에서는 유지한다. |
| `user_role` | `str` | 호출 시 고정된 역할. 허용 값과 권한 정책은 합의 필요다. |

**연결 제안:** Checkpointer의 `thread_id`는 `(user_id, session_id)`에 일대일 대응하도록 서버에서 만든다. Store namespace는 `(user_id, 정보 종류)`로 분리한다. 브라우저가 임의 입력한 식별자를 인증된 사용자 ID처럼 신뢰하지 않는다. 인증 없는 발표 시연에서 어떤 수준으로 사용자를 구분할지도 정해야 한다.

### 창업 조건

원문의 `business_conditions: dict`를 아래 형태로 구체화하는 **연결 제안**이다. 수집 중에는 값이 없을 수 있으나 분석 진입 전에 필수 값을 검증한다.

| 필드 제안 | 타입 | 의미와 검증 |
| --- | --- | --- |
| `preferred_region` | `str` 또는 `null` | 희망 지역. 서울 내 지원 여부는 검색 Tool에서 확인한다. |
| `deposit_budget` | `int` 또는 `null` | 보증금 상한, 원 단위, 0 이상. `null`을 0으로 바꾸지 않는다. |
| `monthly_rent_budget` | `int` 또는 `null` | 월세 상한, 원 단위, 0 이상. |
| `target_age` | `str` 또는 `null` | 사용자 목표 연령. “학생”처럼 모호하면 구체화한다. API별 연령 구간 변환은 Tool 담당이 정한다. |
| `operating_start_time` | `dict` 또는 `null` | 운영 요일·시작 시간. 예: `day_types`, `timezone`. |
| `operating_end_time` | `dict` 또는 `null` | 운영 요일·종료 시간. 예: `day_types`, `timezone`. |

금액의 “만원”은 입력 단계에서 원으로 변환한다. 단위가 불명확하면 확인한다. 시간대는 서비스 범위에 맞게 `Asia/Seoul`을 사용하는 안이며, 자정을 넘는 운영시간을 오류로 취급하지 말고 API 조회 기간으로 분해한다. `AnalysisPeriod`의 실제 허용 값은 제공 API 확인 후 고정한다.

### Agent State

| 원문 필드 | 타입 | 저장 내용 |
| --- | --- | --- |
| `business_conditions` | `dict` | 현재 분석에 적용할 최신 창업 조건 |
| `searched_areas` | `list` | 검색된 전체 후보와 식별자 |
| `tool_results` | `dict` 또는 `list` | 조회 인자와 결과를 다시 연결할 수 있는 Tool 결과 |
| `current_candidates` | `list` | 계산 및 비교 중인 후보, 최종 상위 후보 |
| `messages` | `list[Message]` | 대화 맥락; 실제 메시지 타입은 프레임워크 선택 후 확정 |

**연결 제안:** `tool_results`에는 결과뿐 아니라 `tool_name`, 상권·역 ID, 조회 인자, 조회 시점, 데이터 기준 시점이 필요하다. 동일 Tool이 여러 역·시간대를 조회해도 덮어쓰지 않도록 호출별로 식별한다. `pending_action`과 실행 결과 기록도 승인·중복 실행 방지를 위해 State 또는 별도 저장소에 추가한다. 구체적인 저장 모델은 소유·연주·석휘가 정한다.

## 3. ToolResult와 데이터 출처

### 원문의 공통 반환 형식

| 필드 | 타입 | 처리 규칙 |
| --- | --- | --- |
| `success` | `bool` | 해당 호출이 유효한 결과를 확보했는지 표시 |
| `source` | `str` | 실제 원천 또는 Mock 식별 정보. 호출하지 않은 API 이름을 출처처럼 기재하지 않음 |
| `data` | `dict` 또는 `list` | Tool별 정규화된 데이터 |
| `error_code` | `str` 또는 `null` | 성공이면 `null`; 오류 분류 |
| `error_message` | `str` 또는 `null` | 비밀정보를 제거한 오류 설명 |
| `is_mock` | `bool` | Mock 데이터 사용 여부 |

원문은 실패 때의 `data` 모양을 정하지 않았다. **연결 제안:** 실패는 `success=false`, `data={}`, 오류 코드·메시지를 채운다. 정상 검색 0건은 `success=true`, `data=[]`로 구분한다. 대체 데이터가 스키마 검증을 통과하면 데이터 확보 성공으로 반환하고, 원래 오류 코드·Fallback 설명은 `data`와 `evidence`에 보존한다.

최종 화면에도 출처·기준 시점·캐시·Mock 여부가 전달되어야 한다. 최소한 `evidence`와 `missing_data`에서 이를 설명한다. 자료가 신선해 보이도록 캐시 조회 시각을 원천 데이터 갱신 시각으로 사용하지 않는다.

### 공통 식별자

| 필드 | 형식 제안 | 규칙 |
| --- | --- | --- |
| `area` | `str` | 상권 조인의 기준. 원천 간 매핑을 확인한다. |
| `administrative_code` | `str` | 행정코드. 앞자리 0을 유지하며 숫자로 변환하지 않는다. |
| `station_id` | `str` | 역·출구 조회 연결에 사용한다. 이름이 같은 역은 코드로 구분한다. |
| `latitude`, `longitude` | `float` | 위도 -90~90, 경도 -180~180. 좌표계 확인 후 통일한다. |
| `area_name` | `str` | 사용자 표시용 이름. 식별자 대신 조인 키로 쓰지 않는다. |

출구 데이터와 상권이 자동으로 일대일 대응한다고 가정하지 않는다. 여러 역·출구·행정구역을 상권에 연결하는 반경, 경계, 중복 제거, 집계 방식은 별도 합의가 필요하다. 선택 반경의 임의 기본값은 이 문서에서 정하지 않는다.

## 4. Tool 입력과 반환 데이터

함수명과 입력은 원문 기준이다. 반환 데이터의 세부 필드가 없으므로 아래 “반환에 필요한 내용”은 **연결 제안**이며 실제 API 응답을 확인한 뒤 효주의 공통 모델과 맞춘다. 모든 반환은 `ToolResult`로 감싼다.

| Tool | 원문 입력 | 반환에 필요한 내용 |
| --- | --- | --- |
| `search_supported_districts` | `preferred_region: str` | 지원 후보 목록, 표시명, 원천 식별 정보, 데이터 제공 범위 |
| `resolve_area_entities` | 선택 후보 ID | 상권 ID, 행정코드, 좌표; 실패 시 `AREA_NOT_FOUND` |
| `get_academy_demand` | `area: AreaIdentity`, `target_age: str \| None`, `period: AnalysisPeriod` | 상권별 학원·교육 수요 원천 지표와 집계 범위 |
| `find_nearby_stations` | `latitude: float`, `longitude: float`, `radius_m: int` | 역 ID, 역명, 위치·거리; 정상 0건은 빈 목록 |
| `get_station_exit_traffic` | `station_id: str`, `period: AnalysisPeriod` | 역·출구·요일·시간대별 통행량과 단위 |
| `get_district_congestion` | `commercial_area_id: str`, `date_or_day_type: str`, `period: str` | 시간대별 혼잡도·활성도 원천 지표 |
| `get_visitor_demographics` | `commercial_area_id: str`, `target_age: str` | 연령별 방문자 수 또는 비율과 단위 |
| `search_competitors` | `latitude: float`, `longitude: float`, `radius_m: int` | 경쟁점포 목록·수, 업종 분류, 중복 제거 기준 |
| `get_rent_and_closure_data` | `commercial_area_id: str`, `administrative_code: str` | 임대료·보증금 자료, 면적·가격 단위, 개폐업 지표; 미제공 필드는 누락 |
| `calculate_market_score` | `scoring_input: ScoringInput` | 후보 식별자, 총점·6개 세부 점수, 누락·신뢰도, 계산 정책 식별 정보 |
| `save_user_preferences` | `preferences: dict`, `context: RuntimeContext` | 저장된 허용 선호 항목과 성공·실패 |
| `save_shortlist` | `user_id: str`, `area_ids: list[str]` | 저장된 상권 ID와 성공·실패 |
| `create_site_visit_event` | `area_id: str`, `visit_datetime: str` | 확인된 일정 식별자와 실행 결과 |
| `send_analysis_report` | `recipient: str`, `report: dict` | 확인된 전송 결과 또는 성공 여부 불명 상태 |

`area_id`와 `area_ids`는 `commercial_area_id`를 사용하는 별칭으로 통일하는 안이다. 저장 Tool의 사용자 식별은 `context`에서 주입·검증한다. `visit_datetime`은 시간대가 포함된 값으로 정규화한다.

원문의 점수 Tool 입력에는 현재 예산·가중치가 없지만 요구사항에는 조건 변경에 따른 재계산이 있다. **연결 제안:** `business_conditions`, `weights`, `scoring_policy_version`을 명시적으로 전달하거나, 같은 정보를 타입이 정해진 계산 입력 모델에 포함한다. 계산 함수가 전역 State를 몰래 읽는 대신 입력만으로 재현될 수 있게 한다.

원문이 명시한 오류 코드는 `AREA_NOT_FOUND`다. 추가 코드로 `UNSUPPORTED_AREA`, `INVALID_INPUT`, `API_TIMEOUT`, `API_ERROR`, `INVALID_TOOL_RESULT`, `INSUFFICIENT_DATA`를 제안한다. 의미와 재시도 여부는 연주·Tool 담당이 확정하며, API 오류 원문·키·수신처를 그대로 사용자에게 노출하지 않는다.

## 5. 최종 응답

### StudySpotResponse 원문 필드

| 필드 | 타입 | 제약 |
| --- | --- | --- |
| `status` | `Literal["success", "need_more_information", "no_result", "approval_required"]` | 네 가지 값만 허용 |
| `recommendations` | `list[AreaRecommendation]` | 필수, 최대 3개 |
| `message` | `str` | 사용자에게 보여줄 설명 |
| `missing_required_inputs` | `list[str]` | 아직 없는 필수 입력 필드명 |
| `requires_approval` | `bool` | 필수, 보고서 전송·일정 등록 승인 대기 시 `true` |
| `approval_action` | `str` | 승인 대기 행동 |

### AreaRecommendation 원문 필드

모든 필드는 필수다. 세부 점수의 `null`은 필드 생략과 다르며, 자료 미확보 사실을 `missing_data`에 함께 기록한다.

| 필드 | 타입 | 제약 |
| --- | --- | --- |
| `area_name` | `str` | Tool에서 확인한 상권명 |
| `total_score` | `float` | 0~100, 계산 Tool 값 |
| `academy_demand_score` | `float` 또는 `null` | 0~25 |
| `target_customer_score` | `float` 또는 `null` | 0~20 |
| `station_traffic_score` | `float` 또는 `null` | 0~15 |
| `activity_score` | `float` 또는 `null` | 0~15 |
| `rent_score` | `float` 또는 `null` | 0~15 |
| `competition_score` | `float` 또는 `null` | 0~10 |
| `strengths` | `list[str]` | Tool 근거가 있는 장점 |
| `risks` | `list[str]` | Tool 근거 또는 명시된 데이터 한계 |
| `evidence` | `list[EvidenceItem]` | 수치의 근거·출처·Mock 여부 |
| `missing_data` | `list[str]` | 확보하지 못한 데이터, 없으면 `[]` |
| `confidence` | `float` | 0~1, 데이터 품질에 관한 값이며 창업 성공 확률이 아님 |

총점을 산출할 수 없는 후보는 `total_score=0`으로 채우지 말고 추천 목록에서 제외하는 연결안을 사용한다. 부분 자료만으로 총점을 낼 수 있는지는 아래 점수 정책 합의에 따른다.

**상태별 불변 조건:** 분석 성공은 추천 1~3개를 반환하고, 추가 정보 요청·분석 실패에서는 새 추천을 반환하지 않는다. 승인 대기는 `status="approval_required"`, `requires_approval=true`, 유효한 `approval_action`을 함께 요구한다. 다른 상태는 `requires_approval=false`다.

UI와 Agent는 공통 응답 모델 외 필드를 임의로 추가하지 않는다. Pydantic 모델은 효주가 관리하고 석휘·명하·연주가 상태별 필수값과 검증을 함께 맞춘다.

## 6. 점수 계산과 미정 정책

### 원문 기본 배점

| 항목 | 최대 점수 | 원천 |
| --- | --- | --- |
| 학원·교육 수요 | 25 | `get_academy_demand` |
| 타깃 연령 방문자 | 20 | `get_visitor_demographics` |
| 지하철 통행량 | 15 | 역 검색과 `get_station_exit_traffic` |
| 저녁·주말 활성도 | 15 | `get_district_congestion` |
| 임대료 적합성 | 15 | `get_rent_and_closure_data`와 현재 예산 |
| 경쟁점포 포화도 | 10 | `search_competitors` |
| 합계 | 100 | `calculate_market_score` |

경쟁점포 수나 임대료가 크다고 점수가 높아지는 것은 아니다. 각 원천 지표가 적합도에 어떤 방향으로 영향을 주는지와 정규화 구간을 효주가 정의해야 한다. 개·폐업 자료는 현재 별도 배점이 없으므로 안정성에 관한 근거·위험요인으로 사용한다.

### 사용자 우선순위와 고정 세부 점수 범위

원문은 “가중치 변경”과 “고정된 세부 점수 상한”을 동시에 요구한다. 임대료 비중을 높이면서 `rent_score` 자체를 15점보다 크게 만들면 원문 스키마와 충돌한다.

**연결 제안:** 세부 점수 `c_i`는 기존 상한 `m_i` 안의 기준 점수로 유지하고, 사용자의 가중치 `w_i`는 총점 계산에만 적용한다. 모든 지표가 확보된 경우 아래 식을 검토할 수 있다.

```text
q_i = c_i / m_i
각 w_i >= 0, 합계는 1
total_score = 100 × Σ(w_i × q_i)
기본 w_i = m_i / 100 이면 total_score = Σ(c_i)
```

이 식은 **제안이며 확정 공식이 아니다.** 원천 지표를 `c_i`로 바꾸는 정규화, 우선순위 언어를 가중치로 변환하는 방식은 여전히 필요하다. 사용자 가중치를 바꾸면 총점과 세부 점수 단순 합이 달라질 수 있으므로 UI에 적용 가중치를 표시해야 한다. 다른 방식을 택하면 세부 점수 필드의 의미와 범위를 함께 수정해야 한다.

### 구현 전에 합의할 계산 정책

| 정책 | 결정할 내용 |
| --- | --- |
| 정규화 | 구간·최솟값·최댓값, 고정 기준인지 현재 후보 집합 기준인지, 방향성 |
| 누락 | 누락된 요소는 0점으로 처리 |
| 신뢰도 | 실제·캐시·Mock·누락·기준 시점 차이에 따른 결정론적 산식과 비교 기준 |
| 예산 필터 | 상권 평균 임대료와 실제 매물 비용의 구분, 보증금·월세 비교 단위, 예산 초과 처리 |
| 후보 간 비교 | 서로 다른 누락 항목·자료 품질로 산출한 점수를 함께 순위화할 조건 |
| 동점·반올림 | 정렬 우선순위, 반올림 자리수와 적용 시점, 안정적인 최종 순서 |
| 재현성 | 입력 데이터, 적용 가중치, 정규화 기준, `scoring_policy_version` 기록 |

누락 지표는 0점으로 처리하고 계산을 진행한다.

## 7. 저장과 외부 행동 계약

| 구분 | 실행 근거 | 호출 정책 |
| --- | --- | --- |
| 단기 State 저장 | 대화 처리를 위한 상태 유지 | 같은 사용자·세션 범위에서 저장·복원 |
| 선호·관심 상권 저장 | 명시적인 요청 또는 동의 | Store 쓰기 전 사용자와 허용 필드 검증, 실패 시 임의 재시도 금지 |
| 보고서 전송 | 확정된 대상·내용에 대한 승인 | 실행 전 대기 행동 확인, 중복 실행 방지 |
| 현장답사 일정 | 확정된 상권·일시에 대한 승인 | 실행 전 대기 행동 확인, 중복 실행 방지 |

**연결 제안:** 승인 레코드는 사용자, 세션, 행동 ID, Tool 종류, 확정 인자 또는 안전한 참조, 승인 대상 버전, 승인·실행 상태를 묶는다. 내용 수정 시 기존 승인을 무효화하고, 새 세션의 단순한 “응”을 이전 행동 승인으로 취급하지 않는다. 모델이 생성한 승인 값만으로 Tool을 실행하지 않는다.

이메일 수신처 같은 실행에 필요한 개인정보는 마스킹된 대화·로그·장기 선호와 분리해야 한다. 원문은 마스킹과 실제 전송을 모두 요구하지만 원본 값을 안전하게 보관·해석하는 방법은 없다. UI에서 받은 실행 인자를 제한된 임시 저장소로 참조하는 방법과 만료 정책을 연주·소유·명하가 합의해야 한다.

## 8. 합의 순서와 담당

| 우선순위 | 확정할 내용 | 관련 담당 |
| --- | --- | --- |
| 1 | 상권 조회 담당, 실제 API 지원 범위, 시연 후보 5~10곳, ID·단위·집계 매핑 | 상권 담당 미정, 중우, 석휘 |
| 2 | ToolResult 확장, Tool별 payload, State 참조 방식 | 효주, 소유, 중우, 연주, 석휘 |
| 3 | 정규화·가중치·누락·신뢰도·예산 필터·동점 정책 | 효주, 석휘 |
| 4 | 상태별 응답 필드와 UI 동작, 승인 내용·실행 결과 모델 | 효주, 명하, 연주, 석휘 |
| 5 | Checkpointer·Store·캐시 구현, 세션 식별, 반복 한도·타임아웃·TTL | 소유, 연주, 석휘 |
| 6 | 전송·일정 기능의 구현 범위, 실행기 담당, 승인·중복 실행 방지 | 담당 합의 필요, 연주, 소유, 명하, 석휘 |

합의한 항목은 해당 제안 표시를 제거하고 변경 내용을 기록한다. 함수명·타입·배점·오류 코드가 바뀌면 [구조도](architecture.md), [흐름도](flow.md), 실제 `models/schemas.py`와 관련 테스트를 함께 맞춘다.
