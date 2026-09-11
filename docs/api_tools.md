# StudySpot API Tool 구현 명세

담당: 중우 · 브랜치: `feature/api-tools`
기준 계약: [00_공통계약.md](00_공통계약.md), [01_API_Tool.md](01_API_Tool.md)
공식 사양 및 실응답 확인일: 2026-09-11 (Asia/Seoul)

## 1. 공통 실행 규칙

- API Key는 `.env`의 `SK_OPEN_API_KEY`를 `appKey` 헤더로 전달한다.
- URL이나 오류 메시지에 API Key를 포함하지 않는다.
- Tool 내부에서는 호출 시도당 외부 요청을 한 번만 수행한다.
- 재시도, 캐시, API 실패 후 Mock fallback은 Guardrail·Middleware가 담당한다.
- 실제 응답은 공통 모델로 검증하고 `model_dump(mode="json")`으로 직렬화한다.
- 실제 0은 `value=0.0`, 누락은 `missing_data` 또는 `value=None + missing_reason`으로 구분한다.
- 확인되지 않은 식별자·좌표·수치는 생성하지 않는다.

모든 Tool은 다음 `ToolResult` 계약을 사용한다.

```text
success, source, data, error_code, error_message, is_mock
```

주요 오류 매핑:

| 상황 | ErrorCode |
|---|---|
| 잘못된 Tool 입력 | `INVALID_INPUT` |
| 필요한 코드·좌표 누락 | `MISSING_REQUIRED_INPUT` |
| 인증·상품 권한 | `API_AUTH_ERROR` |
| 호출 한도 | `API_RATE_LIMIT` |
| timeout | `API_TIMEOUT` |
| HTTP 400 | `API_BAD_REQUEST` |
| 비정상 JSON·응답 필드 | `API_RESPONSE_ERROR` |
| 지원 상권 없음 | `AREA_NOT_FOUND` |
| 사용 가능한 데이터 없음 | `NO_DATA` |
| 예상하지 못한 내부 오류 | `TOOL_INTERNAL_ERROR` |

## 2. Metric 계약

| Tool | `metric_name` | 단위 | 세부 구분 |
|---|---|---|---|
| `get_academy_demand` | `estimated_academy_call_customers` | `persons` | `academy_id`, `academy_name`, `category`, `school_age` |
| `get_station_exit_traffic` | `station_exit_user_count` | `persons/hour` | `exit_number`, `day_type`, `time_slot` |
| `get_district_congestion` | `district_congestion_density` | `persons/m2` | `day_type`, `time_slot` |
| `get_district_congestion` | `district_congestion_level` | `level_1_to_10` | `day_type`, `time_slot` |
| `get_visitor_demographics` | `visitor_age_group_rate` | `percent` | `gender`, `age_group` |
| `get_rent_and_closure_data` | `deposit_krw` | `KRW` | 없음 |
| `get_rent_and_closure_data` | `monthly_rent_krw` | `KRW/month` | 없음 |
| `get_rent_and_closure_data` | `closure_rate_percent` | `percent` | 없음 |

`search_competitors`는 원천 POI 목록을 반환한다. 경쟁점포 수는
`len(data["competitors"])`이며 API Tool에서 별도의 점수나 가중치를 만들지 않는다.

## 3. 학원 수요

### `get_academy_demand(area, target_age, period)`

- 공식 문서: [학령·분류별 지역 학원 순위](https://openapi.sk.com/products/detail?linkMenuSeq=449)
- Endpoint: `GET https://apis.openapi.sk.com/puzzle/academy/ranking/districts/{districtCode}`
- Query: `category=all`, `schoolAge={school_age}`
- `districtCode`: `AreaIdentity.administrative_code`의 10자리 법정동 코드
- API 결과: 통화 통계 기반 상위 5개 학원이며 전체 학원 목록이 아니다.
- `stat[].count`: 학원 수가 아니라 추정 통화 고객수다.
- 관측 기간: 요청 기간이 아니라 `statStartDate`~`statEndDate`를 보존한다.

허용 학령:

| Tool 입력 | API 값 |
|---|---|
| 영유아 / `preschool` | `preschool` |
| 초등학생 / `elementary` | `elementary` |
| 중학생 / `middle` | `middle` |
| 고등학생 / `high` | `high` |
| 대학생 / `univ` | `univ` |
| 전체 / `all` | `all` |

`10대`를 중학생 또는 고등학생으로 추측하지 않는다. `stat=[]`은 학원 0개로
해석하지 않고 `missing_data`에 순위 데이터 없음으로 기록한다.

정상 `data`는 `AcademyDemandData` 직렬화 사전이다.

## 4. 지하철

### `find_nearby_stations(latitude, longitude, radius_m)`

- 기준 파일: `data/reference/subway_stations.json`
- 역 코드 원천 API: `GET https://apis.openapi.sk.com/puzzle/subway/meta/stations`
- 좌표 원천: [서울시 역사마스터 정보](https://data.seoul.go.kr/bsp/wgs/dataView/data300View/10048.do)
- 계산 방식: WGS84 좌표의 Haversine 대권거리를 계산하고 `radius_m` 이하 결과를
  `distance_m` 오름차순으로 반환한다.
- 정상 `data`: `NearbyStation` 직렬화 사전 목록
- 반경 안에 지원 역이 없으면 `STATION_NOT_FOUND`를 반환한다.
- 실행 시 외부 API를 호출하지 않으므로 API 재시도·호출 한도 대상이 아니다.

SK 공식 전체 역 목록에는 좌표가 없으므로 역 코드와 서울시 좌표를 역명·호선으로
결합했다. 현재 기준 파일은 SK 공식 API 호출 한도 초과로 인해 MIT 라이선스의
2022-09-01 공개 응답 스냅샷을 사용했다. 468건 모두 좌표를 연결했으며,
역명 변경 보정과 정확한 출처·커밋은 기준 파일 `metadata`에 기록했다. 호출 한도가
복구되면 공식 API의 `type=exit`, `offset=0`, `limit=1000` 결과로 갱신해야 한다.

### `get_station_exit_traffic(station_id, period)`

- 공식 문서: [시간대별 출구 통행자 수](https://openapi.sk.com/products/detail?linkMenuSeq=418)
- Endpoint: `GET https://apis.openapi.sk.com/puzzle/subway/exit/raw/hourly/stations/{stationCode}`
- Query: `gender=all`, `ageGrp=all`, `date=YYYYMMDD`
- `station_id`: SK Puzzle `stationCode`
- 현재 Tool은 API 호출 단위에 맞춰 하루 조회만 허용한다.
- `raw[].userCount`: 해당 출구·한 시간의 통행자 수
- 동일 `exit + datetime` 중복은 한 건만 유지하고 값이 다른 중복은 응답 오류로 처리한다.

정상 `data`는 `StationTrafficData` 직렬화 사전이다.

## 5. 상권 검색과 식별

### `search_supported_districts(preferred_region)`

- 공식 문서: [데이터 제공 가능 상권](https://openapi.sk.com/products/detail?linkMenuSeq=419)
- Endpoint: `GET https://apis.openapi.sk.com/puzzle/place/meta/areas`
- Query: `offset=0`, `limit=1000`
- 공백을 제거한 상권명에 `preferred_region`이 포함된 결과를 반환한다.

### `resolve_area_entities(selected_candidate_id)`

상권 목록에서 ID를 정확히 일치시킨다. 현재 API가 `areaId`, `areaName`만 제공하므로
다음처럼 확인되지 않은 값은 `None`으로 둔다.

```json
{
  "commercial_area_id": "9307",
  "administrative_code": null,
  "area_name": "역삼역남부 3번출구",
  "latitude": null,
  "longitude": null
}
```

법정동 코드가 필요한 학원 Tool과 좌표가 필요한 경쟁점포 Tool은 해당 값이 없으면
`MISSING_REQUIRED_INPUT`을 반환한다.

## 6. 상권 혼잡도

### `get_district_congestion(area, period)`

- 공식 문서: [시간대별 상권 혼잡도](https://openapi.sk.com/products/detail?linkMenuSeq=421)
- Endpoint: `GET https://apis.openapi.sk.com/puzzle/place/congestion/stat/raw/hourly/areas/{areaId}`
- Query: `date=YYYYMMDD`
- 공식 조회 범위: 요청일 기준 D-30~D-1
- 현재 Tool은 하루 조회만 허용한다.
- `congestion`: 단위 면적당 추정 방문자 수(`persons/m2`)
- `congestionLevel`: 1~10 혼잡도 단계
- 각 원천 행을 밀도와 레벨 두 관측값으로 보존한다.

정상 `data` 구조:

```text
area, observations, missing_data
```

## 7. 방문자 연령 분포

### `get_visitor_demographics(area, target_age, period)`

- 공식 문서: [상권 방문자 연령 분포](https://openapi.sk.com/products/detail?linkMenuSeq=427)
- Endpoint: `GET https://apis.openapi.sk.com/puzzle/place/visit/seg/stat/daily/areas/{areaId}`
- 해당 상권에 10분 이상 체류한 SK텔레콤 회선 사용자의 통계다.
- API 입력에는 연령 파라미터가 없으며 응답에서 원하는 연령대를 필터링한다.
- 남성·여성 비율을 각각 보존하며 임의로 인원수로 변환하지 않는다.
- 관측 기간은 `statStartDate`~`statEndDate`를 사용한다.

허용 연령은 `10세 미만`, `10대`~`90대`, `100세 이상`이며 API 코드로는
`0`, `10`~`90`, `100_over`를 사용한다.

정상 `data` 구조:

```text
area, target_age_group, observations, missing_data
```

## 8. 경쟁점포

### `search_competitors(area, radius_m)`

- 공식 문서: [TMAP 장소 통합 검색](https://openapi.sk.com/products/detail?linkMenuSeq=12)
- Endpoint: `GET https://apis.openapi.sk.com/tmap/pois`
- 검색어: `스터디카페`
- 좌표계: `WGS84GEO`
- 거리순 정렬 후 최대 150건 요청
- TMAP API의 정수 km 반경 제약 때문에 `ceil(radius_m / 1000)` km로 조회하고,
  응답의 거리값을 다시 `radius_m` 이하로 필터링한다.
- 상권 좌표가 없으면 `MISSING_REQUIRED_INPUT`을 반환한다.

정상 `data` 구조:

```text
area, radius_m, retrieved_at, competitors
```

각 점포에는 `poi_id`, `name`, `latitude`, `longitude`, `distance_m`,
`category`, `address`만 보존한다. 전화번호는 분석에 필요하지 않아 제외한다.

## 9. 임대료·폐업 Mock

### `get_rent_and_closure_data(area, period)`

공식 API가 확정되지 않아 [rent_and_closure.json](../data/mock/rent_and_closure.json)의
시연용 값을 사용한다.

- 보증금과 월세는 면적당 단가가 아닌 총액이다.
- 등록된 상권은 상권별 값을 사용하고, 미등록 상권은 `default` 값을 사용한다.
- `success=True`, `is_mock=True`, `error_code=None`으로 반환한다.
- 각 `MetricObservation.is_mock`도 `True`로 유지한다.
- 값 변경은 JSON만 수정하면 된다.

정상 `data` 구조:

```text
area, observations, missing_data
```

## 10. 실제 연결 검증

2026-09-11 프로젝트 `.env`로 다음 최소 호출을 확인했다. API Key는 출력하거나
문서에 저장하지 않았다.

| Tool/범위 | 결과 |
|---|---|
| 학원 순위, 역삼동 법정동 코드 | 성공, 상위 5개 관측 |
| 출구 통행량, 역삼역 `221` | 성공, 152개 시간·출구 관측 |
| 지원 상권, `역삼역` 검색 | 성공, 4개 상권 |
| 상권 ID `9307` 해석 | 성공, ID·이름 확인 |
| 상권 혼잡도, `9307` | 성공, 24개 원천 시간대 |
| 방문자 20대 비율, `9307` | 성공, 남성·여성 2개 관측 |
| 스터디카페 POI, 500m | API 성공, 해당 기준점의 필터 결과 0건 |

## 11. 점수 Tool 인계 계약과 미확정 사항

점수 Tool은 현재 구조만 준비되어 있고 산식 구현은 아직 없다. 다음 입력 규칙으로
연결할 수 있도록 API Tool의 metric 이름과 단위를 이 문서에서 고정한다.

- 학원 점수: `estimated_academy_call_customers`를 사용하되 Top 5 통계임을 유지한다.
- 타깃 고객 점수: 요청 연령의 `visitor_age_group_rate` 남녀 값을 합산할 수 있다.
- 지하철 점수: `station_exit_user_count`를 출구·시간대 중복 없이 사용한다.
- 활성도 점수: `district_congestion_density` 또는 `district_congestion_level` 중
  어느 지표를 산식 기준으로 삼을지 점수 담당자 확인이 필요하다.
- 경쟁 점수: `competitors` 목록 길이와 `radius_m`를 함께 사용한다.
- 임대 점수: `deposit_krw`, `monthly_rent_krw`를 사용자 예산과 비교한다.
- 폐업률: `closure_rate_percent`를 임대 점수 또는 위험요인 중 어디에 반영할지
  점수 담당자 확인이 필요하다.

Market Tool의 최상위 payload는 아직 전용 Pydantic 모델이 없어서 직렬화된
`AreaIdentity`와 `MetricObservation`을 포함한 사전으로 반환한다. 역할 4 검토 후
필요하면 `MarketObservationData`, `CompetitorSearchData` 같은 공통 모델을 추가한다.

## 12. 현재 미완료 범위

- `find_nearby_stations` 기준 파일의 최신 SK `type=exit` 응답 갱신
- 상권 ID와 법정동 코드·상권 중심 좌표의 공식 연결
- API 실패 후 Mock fallback 및 Middleware 재시도 통합 테스트
- 보고서 전송과 현장답사 일정 등록 Tool
- Market 최상위 payload의 공통 Pydantic 모델
- 점수 Tool의 혼잡도 기준 및 폐업률 반영 위치 확정
