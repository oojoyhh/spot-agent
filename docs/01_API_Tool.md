# 역할 1 — StudySpot API Tool 설계 및 테스트

담당자: **중우** · 브랜치: `feature/api-tools` · 선행 문서: [공통 계약](00_공통계약.md)

## 목표

학원·지하철뿐 아니라 지원 상권·혼잡도·방문자·경쟁·임대료와 보고서 전송·일정 등록에 필요한 API Tool을 공통 형식으로 제공한다. 점수 계산과 Agent 제어는 다른 담당자에게 맡긴다.

## 파일별 개발 지시

| 파일 | 개발할 내용 |
|---|---|
| `tools/academy_tools.py` | `get_academy_demand`; 입력 검증, SK 요청 어댑터, 원천 응답 파싱, 정규화, 오류 변환 |
| `tools/subway_tools.py` | `find_nearby_stations`, `get_station_exit_traffic`; 역 식별자 연결, 거리·시간 조건 처리 |
| `tools/market_tools.py` | 지원 상권 검색·식별자 해석·혼잡도·방문자·경쟁·임대료 API 어댑터 |
| `tools/action_tools.py` | 승인된 보고서 전송·현장답사 일정 등록 API 어댑터 |
| `data/mock/*_*.json` | 정상·빈 결과·부분 누락 fixture. 내부 반환 스키마를 실데이터와 동일하게 유지 |
| `tests/test_*_tools.py` | 각 API Tool의 단위·계약 테스트 |
| `docs/api_tools.md` | 공식 문서 출처·확인일, 지원 지표, 요청/응답 매핑, 단위·기간·제한, 미지원 데이터 |

공통 모델은 직접 수정하지 않고 역할 4에게 요청한다. `.env.example`에 필요한 변수는 역할 5에게 전달한다.

공급자별 제한값은 `tools/api_types.py`의 역할 1 전용 `Literal` 타입으로 관리한다. 이는 공통 Pydantic 모델을 다시 선언하는 파일이 아니다.

## 입력/출력 계약

공통 계약의 인자와 payload를 사용한다. 공급자 HTTP 파라미터는 내부 Tool 인자와 구분해 문서화한다.

| Tool | 입력 | 정상 `ToolResult.data` |
|---|---|---|
| `get_academy_demand` | AreaIdentity, AnalysisPeriod, school_age=`all` | AcademyDemandData 사전 |
| `find_nearby_stations` | latitude, longitude, radius_m | NearbyStation 목록 |
| `get_station_exit_traffic` | station_id, AnalysisPeriod | StationTrafficData 사전 |
| `search_supported_districts` | preferred_region | AreaIdentity 목록 |
| `resolve_area_entities` | 선택 후보 ID | AreaIdentity 사전 |
| `get_district_congestion` | area, period | observations+missing_data |
| `get_visitor_demographics` | area, target_age, period | observations+missing_data |
| `search_competitors` | area, radius_m | 점포 목록+기준 시점 |
| `get_rent_and_closure_data` | area, period | observations+missing_data |
| `send_analysis_report` | 승인된 서버 측 action | 실행 결과 식별자 |
| `create_site_visit_event` | 승인된 서버 측 action | 실행 결과 식별자 |

- `commercial_area_id`·`administrative_code`는 `resolve_area_entities`의 결과를 받는다. 지역명으로 임의 코드를 만들지 않는다.
- 사용자 `target_age`는 방문자 연령대 입력이다. 학원 `school_age`로 추정 변환하지 않고, 특정 학령 요구가 없으면 `all`을 사용한다.
- `station_id`는 인근 역 조회 결과의 동일 코드 체계를 사용한다. 출구별·시간대별 값의 중복 합산을 막기 위해 집계 단위를 문서화한다.
- 원천 지표별 값·단위·대상 기간·출처·누락 이유를 남긴다. 지원하지 않는 연령 세분화·시간 단위는 제공되는 것처럼 표시하지 않는다.
- 실패는 공통 오류 코드와 `success=False`로 반환한다. 원천 누락은 None과 missing_data로 나타내며 학원 0개와 구분한다.
- HTTP 200 응답도 요청 식별자·필터·날짜 일치, 필수 필드 타입·범위, 중복 관측을 검증한다. 불일치나 비정상 값은 `API_RESPONSE_ERROR`로 처리한다.
- Mock payload는 같은 모델 검증을 통과해야 한다. source와 is_mock를 보존한다.

## 의존 모듈과 책임 경계

본 역할의 지역 검색·식별자 해석 → 원천 데이터 조회 → 역할 4의 점수 Tool → 역할 5의 추천 조립 순서다. 역할 5는 Tool 등록과 Agent 흐름 연결을 담당한다.

재시도·캐시·Fallback 정책의 소유자는 역할 3이다. 본 역할은 호출 시도당 **외부 요청 1회**와 timeout·오류 분류, Mock 로더·캐시 어댑터 연결점을 제공한다. Middleware가 최초 호출과 최대 2회 재시도를 통합 제어하며 API Tool 내부에서는 별도로 재시도하지 않는다.

실제 API 명칭·URL·지원 범위·파라미터는 개발 시 공식 문서에서 확인하고 기록한다. 과거 대화의 요금제·호출량·응답 예시는 현재 사실로 간주하지 않는다. 이 명세서는 API 상품 사양을 확정하지 않는다.

## 개발 순서

1. 공식 API 응답과 내부 payload의 매핑표를 작성하고 미지원 필드를 표시한다.
2. 역할 4와 payload·단위·누락 규칙을 확정한다.
3. Mock fixture와 계약 테스트를 먼저 준비한다.
4. 조회 어댑터를 직접 구현하고 역할 3의 재시도 경계와 연결한다.
5. 실제 호출 가능 시 최소한의 smoke test를 수행하고, 불가능하면 실 API 미검증을 명시한다.

## 테스트 범위

| ID | 입력·상황 | 통과 조건 |
|---|---|---|
| API-01 | 정상 학원/역/통행 데이터 | 정규화 모델 통과, 출처·기간·단위 유지 |
| API-02 | 잘못된 좌표·음수 반경·빈 ID | 외부 호출 없이 INVALID_INPUT |
| API-03 | 미지원 상권·없는 역 | 대응 오류 코드, 데이터 생성 없음 |
| API-04 | 정상 0건·일부 필드 누락 | 0건과 실패 구별, 누락 None 유지 |
| API-05 | timeout·인증·제한·응답 형식 오류 | 원인을 공통 오류로 변환, 키 미노출 |
| API-06 | 실제 응답 fixture와 Mock | 동일 내부 스키마, is_mock만 정확히 구별 |
| API-07 | 역 조회 후 시간대 조회 | 첫 결과의 station_id 전달, 단위 혼합 없음 |
| API-08 | Middleware 재시도 연결 | 최초 1회+재시도 최대 2회, 중첩 호출 없음 |
| API-09 | 지원 상권·식별자·혼잡도·방문자 정상 조회 | 상권 ID·행정코드·좌표·기간이 Tool 간 일관되게 전달됨 |
| API-10 | 경쟁점포·임대료·폐업 데이터 정상/빈 결과 | 실제 0건과 조회 실패 구별, 기준 시점·반경·금액 단위 유지 |
| API-11 | 보고서·일정 승인 전/거절/변경 | 외부 API 호출 0회, 실행 성공으로 표시하지 않음 |
| API-12 | 유효 승인·중복 요청·결과 불명 timeout | 같은 action_id는 최대 1회 실행, 결과 불명 상태에서 자동 재시도 없음 |

## 완료 조건

담당 API Tool 전체가 같은 계약을 사용하고 정상·실패·누락·Mock 경로가 자체 테스트를 통과한다. 점수 담당자가 API 구현을 몰라도 fixture로 점수 개발을 진행할 수 있어야 한다. 공식 사양 확인표와 실제 연결 검증 여부를 인계한다.

## 금지사항

점수 생성, 원천 데이터 조작, 비율을 인원으로 임의 변환, 미지원 지역 생성, 자연어만으로 식별자 연결, API 키 하드코딩, 무제한 호출, 공통 스키마 임의 변경을 금지한다.

## PR 체크리스트

- [ ] 공통 계약 PR 체크리스트 충족
- [ ] 담당 API Tool 전체의 이름·타입 힌트·호출 목적 docstring 제공
- [ ] 공식 사양 매핑·단위·기준 시점 기록
- [ ] 오류·0건·누락·Mock 테스트와 결과 첨부
- [ ] 재시도 소유권을 역할 3과 확인
- [ ] payload 변경은 역할 4, 호출 인자 변경은 역할 5 검토
- [ ] 실 API 검증/미검증 범위 명시
- [ ] market/action Tool의 정상·실패·승인·중복 실행 테스트 첨부
