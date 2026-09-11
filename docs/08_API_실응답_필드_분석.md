# StudySpot API 실응답 필드 분석

## 1. 확인 범위

- 확인일: 2026-09-11 (Asia/Seoul)
- 기준 지역: 서울특별시 강남구 역삼동·역삼역
- 인증 방식: 프로젝트 `.env`의 `SK_OPEN_API_KEY`를 `appKey` 헤더로 전달
- API Key 값은 응답 기록과 이 문서에 포함하지 않는다.
- 아래 필드와 자료형은 공식 문서만 옮긴 것이 아니라 실제 호출 응답을 기준으로 확인했다.

| 범위 | 실제 호출 결과 | 사용 목적 |
|---|---:|---|
| 학원 API | HTTP 200 | 법정동 단위 학원 수요 지표 조회 |
| 지하철 API | HTTP 200 | 역 식별자·좌표 및 출구·시간별 통행량 조회 |
| 상권 코드 | HTTP 200 | SK Puzzle 지원 상권 ID 조회 |
| 지역 코드 및 좌표 | HTTP 200 | TMAP 지역 코드 확인 및 주소의 좌표 변환 |

> 주의: `commercial_area_id`, 법정동 코드, 행정동 코드, 역 코드는 서로 다른 코드 체계다. 이름이나 숫자가 비슷해도 같은 식별자로 취급하지 않는다.

## 2. 학원 API

### 2.1 호출 정보

- API: 학령·분류별 지역 학원 순위
- Method: `GET`
- Endpoint: `https://apis.openapi.sk.com/puzzle/academy/ranking/districts/{districtCode}`
- 실제 Path Parameter: `districtCode=1168010100`
- 실제 Query Parameters: `category=all`, `schoolAge=all`
- 공식 문서: [학령·분류별 지역 학원 순위](https://openapi.sk.com/products/detail?svcSeq=70&menuSeq=449)

`districtCode`는 TMAP Geocoding 응답의 `legalDongCode`를 사용했다. 임의로 생성하거나 상권 ID를 대신 넣지 않는다.

### 2.2 실제 응답 예시

```json
{
  "status": {
    "code": "00",
    "message": "success",
    "totalCount": 1
  },
  "contents": {
    "districtCode": "1168010100",
    "districtName": "서울특별시 강남구 역삼동",
    "category": "전체",
    "schoolAge": "전체",
    "stat": [
      {
        "ypId": "473863",
        "ypName": "강남대성학원",
        "category": "입시/고시",
        "schoolAge": "전체",
        "lat": 37.495853,
        "lng": 127.03096,
        "count": 1404
      },
      {
        "ypId": "3752180",
        "ypName": "강남하이퍼학원 본원",
        "category": "입시/고시",
        "schoolAge": "전체",
        "lat": 37.4995,
        "lng": 127.0300833333,
        "count": 880
      }
    ],
    "statStartDate": "20260812",
    "statEndDate": "20260910",
    "yearMonth": "202609"
  }
}
```

실제 `stat` 배열은 5건이었다. 위 예시는 구조 확인을 위해 앞의 2건만 기록했다.

### 2.3 필드와 자료형

| 경로 | 실제 자료형 | 의미 및 처리 기준 |
|---|---|---|
| `status.code` | `str` | `"00"`이면 정상 조회 |
| `status.message` | `str` | 실제 값 `"success"` |
| `status.totalCount` | `int` | 응답 내용 객체 건수이며 학원 수가 아님 |
| `contents.districtCode` | `str` | 10자리 법정동 코드 |
| `contents.districtName` | `str` | 법정동 전체 명칭 |
| `contents.category` | `str` | 적용된 학원 분류의 한글 표시값 |
| `contents.schoolAge` | `str` | 적용된 학령의 한글 표시값 |
| `contents.stat` | `list` | 통화 통계 기반 상위 학원 목록 |
| `contents.statStartDate` | `str` | 통계 시작일, `YYYYMMDD` |
| `contents.statEndDate` | `str` | 통계 종료일, `YYYYMMDD` |
| `contents.yearMonth` | `str` | 통계 기준 년월, `YYYYMM` |
| `stat[].ypId` | `str` | 학원 ID |
| `stat[].ypName` | `str` | 학원명 |
| `stat[].category` | `str` | 학원 분류 |
| `stat[].schoolAge` | `str` | 추정 주 학령 |
| `stat[].lat` | `float` | 개별 학원 위도 |
| `stat[].lng` | `float` | 개별 학원 경도 |
| `stat[].count` | `int` | 추정 통화 고객수 |

### 2.4 `get_academy_demand` 해석 기준

- Tool 입력 `school_age`는 `preschool`, `elementary`, `middle`, `high`, `univ`, `all` 중 하나이며 기본값은 `all`이다.
- 사용자 조건의 `target_age`는 방문자 연령대이므로 학령으로 자동 변환하지 않는다.
- `count`는 학원 개수가 아니라 **추정 통화 고객수**다.
- `stat`은 전체 학원 목록이 아니라 통화 통계 기반 상위 5개다.
- `lat`, `lng`는 상권 중심이나 법정동 중심이 아니라 개별 학원 좌표다.
- 따라서 `count`는 학원 수요의 근거 지표로 사용할 수 있지만, 상권 내 총 학원 수나 전체 학원 밀도로 해석하면 안 된다.
- 기간은 요청값만 믿지 않고 실제 응답의 `statStartDate`와 `statEndDate`를 보존한다.

권장 관측값 매핑 예시는 다음과 같다.

```json
{
  "metric_name": "estimated_academy_call_customers",
  "value": 1404,
  "unit": "persons",
  "dimensions": {
    "academy_id": "473863",
    "academy_name": "강남대성학원",
    "category": "입시/고시",
    "school_age": "전체"
  }
}
```

## 3. 지하철 API

지하철은 역 메타정보와 출구 통행량을 서로 다른 API로 조회한다.

### 3.1 지하철역 검색

- Method: `GET`
- Endpoint: `https://apis.openapi.sk.com/puzzle/subway/meta/search`
- 실제 Query Parameter: `name=역삼`
- 공식 문서: [지하철역 검색](https://openapi.sk.com/products/detail?svcSeq=54&menuSeq=573)

실제 응답:

```json
{
  "status": {
    "code": "00",
    "message": "success",
    "totalCount": 1
  },
  "contents": [
    {
      "subwayLine": "2호선",
      "stationName": "역삼역",
      "stationCode": "221",
      "stationCodeSeoulmetro": "0221",
      "mainStationCode": "221",
      "repLat": 37.500665213235,
      "repLng": 127.03647857603902,
      "available": {
        "searchYn": "Y",
        "congestionTrainYn": "Y",
        "congestionCarYn": "Y",
        "congestionRouteYn": "Y",
        "congestionRltmYn": "Y",
        "exitYn": "Y"
      }
    }
  ]
}
```

| 경로 | 실제 자료형 | 의미 및 처리 기준 |
|---|---|---|
| `contents[]` | `list` | 동명 역 또는 노선별 결과 가능성을 고려해 항상 목록으로 처리 |
| `subwayLine` | `str` | 노선명 |
| `stationName` | `str` | 역명 |
| `stationCode` | `str` | SK Puzzle 역 코드, `station_id` 후보 |
| `stationCodeSeoulmetro` | `str` | 서울교통공사 코드; 앞자리 0 보존 필요 |
| `mainStationCode` | `str` | 주 역사 코드 |
| `repLat` | `float` | 역 대표 위도 |
| `repLng` | `float` | 역 대표 경도 |
| `available` | `dict` | 데이터 종류별 제공 여부 |
| `available.*Yn` | `str` | Boolean이 아니라 `"Y"`/`"N"` 문자열 |

`stationCode`, `stationCodeSeoulmetro`, `mainStationCode`는 서로 구분해 원천 필드로 보존한다. 출구 통행량 API에는 `stationCode`를 사용한다.

### 3.2 시간대별 지하철역 출구 통행자 수

- Method: `GET`
- Endpoint: `https://apis.openapi.sk.com/puzzle/subway/exit/raw/hourly/stations/{stationCode}`
- 실제 Path Parameter: `stationCode=221`
- 실제 Query Parameters: `gender=all`, `ageGrp=all`, `date=latest`
- 공식 문서: [시간대별 출구 통행자 수](https://openapi.sk.com/products/detail?svcSeq=54&menuSeq=418)

실제 응답 일부:

```json
{
  "status": {
    "code": "00",
    "message": "success",
    "totalCount": 1
  },
  "contents": {
    "subwayLine": "2호선",
    "stationName": "역삼역",
    "stationCode": "221",
    "gender": "all",
    "ageGrp": "all",
    "raw": [
      {
        "exit": "1",
        "userCount": 15,
        "datetime": "20260910050000"
      },
      {
        "exit": "1",
        "userCount": 126,
        "datetime": "20260910060000"
      }
    ]
  }
}
```

- 실제 데이터 기준일: 2026-09-10
- 실제 출구: `"1"`~`"8"`
- 실제 시간: 05시~23시
- 실제 `raw` 건수: 152건

| 경로 | 실제 자료형 | 의미 및 처리 기준 |
|---|---|---|
| `contents.subwayLine` | `str` | 노선명 |
| `contents.stationName` | `str` | 역명 |
| `contents.stationCode` | `str` | 역 코드 |
| `contents.gender` | `str` | 적용된 성별 조건 |
| `contents.ageGrp` | `str` | 적용된 연령 조건 |
| `contents.raw` | `list` | 출구·시간별 관측값 |
| `raw[].exit` | `str` | 출구 번호; 숫자로 변환하지 않음 |
| `raw[].userCount` | `int` | 해당 출구·시간의 통행자 수 |
| `raw[].datetime` | `str` | `YYYYMMDDHHMMSS` |

`MetricObservation.dimensions`에는 최소한 다음 두 값을 보존해야 한다.

```json
{
  "metric_name": "station_exit_user_count",
  "value": 15,
  "unit": "persons/hour",
  "dimensions": {
    "exit_number": "1",
    "day_type": "weekday",
    "time_slot": "05:00-06:00"
  }
}
```

원천의 `datetime`은 해당 날짜와 한 시간 구간의 `AnalysisPeriod`로 변환해 보존한다.

### 3.3 `find_nearby_stations` 관련 제약

지하철역 검색 API는 `name` 기반이며 `latitude`, `longitude`, `radius_m`를 직접 받지 않는다. 역 좌표는 반환하지만 좌표 반경 검색 기능은 아니다. 따라서 공통 계약의 `find_nearby_stations(latitude, longitude, radius_m)`를 구현하려면 다음 중 하나가 추가로 필요하다.

1. 역 이름 검색 결과 또는 별도 역 좌표 목록을 캐시한 뒤 애플리케이션에서 거리 계산
2. 좌표 반경 검색을 지원하는 다른 공식 TMAP 장소 API 사용

확인되지 않은 엔드포인트를 추측해서 사용하지 않는다.

현재 구현은 1번을 채택했다. SK의 공식 `데이터 제공 가능 지하철역` API
`GET /puzzle/subway/meta/stations`가 제공하는 역 코드와 서울시 공식
`서울시 역사마스터 정보`의 좌표를 결합해
`data/reference/subway_stations.json`으로 저장한다. 실행 시에는 이 기준 파일을
읽어 Haversine 거리로 반경 내 역을 계산한다.

2026-09-11 갱신 시 SK API 호출 한도가 초과되어, 역 코드는 MIT 라이선스로 공개된
2022-09-01 API 응답 스냅샷을 사용했다. 서울시 좌표는 2026-09-02 갱신 자료다.
최종 468건 모두 좌표를 연결했으며 역명 변경 보정·출처 정보는 기준 파일의
`metadata`에 보존한다.

## 4. 상권 코드

### 4.1 호출 정보

- API: 데이터 제공 가능 상권
- Method: `GET`
- Endpoint: `https://apis.openapi.sk.com/puzzle/place/meta/areas`
- 실제 Query Parameters: `offset=0`, `limit=1000`
- 공식 문서: [데이터 제공 가능 상권](https://openapi.sk.com/products/detail?svcSeq=56&menuSeq=419)

### 4.2 실제 응답 구조

```json
{
  "status": {
    "code": "00",
    "message": "success",
    "totalCount": 948,
    "offset": 0,
    "limit": 1000
  },
  "contents": [
    {
      "areaId": "9307",
      "areaName": "역삼역남부 3번출구"
    }
  ]
}
```

| 경로 | 실제 자료형 | 의미 및 처리 기준 |
|---|---|---|
| `status.totalCount` | `int` | API가 알린 전체 상권 수 |
| `status.offset` | `int` | 조회 시작점 |
| `status.limit` | `int` | 요청한 조회 한도 |
| `contents` | `list` | 지원 상권 목록 |
| `contents[].areaId` | `str` | SK Puzzle 상권 ID |
| `contents[].areaName` | `str` | 상권명 |

역삼역 이름으로 확인된 결과:

| `areaId` | `areaName` |
|---|---|
| `9307` | 역삼역남부 3번출구 |
| `9368` | 역삼역북부 4번출구 |
| `9310` | 역삼역북부 7번출구 |
| `9308` | 역삼역남부 1번출구 |

실제 응답에서는 `status.totalCount=948`이었지만 수신한 `contents` 길이는 935였다. 두 값의 일치를 전제로 검증하거나 반복 범위를 정하지 않는다. 원천 응답의 불일치로 기록하고, 필요한 경우 페이지별 중복·누락 여부를 별도로 점검해야 한다.

이 API는 상권 ID와 이름만 반환한다. 다음 값은 반환하지 않는다.

- 법정동·행정동 코드
- 상권 중심 위도·경도
- 상권 경계 좌표
- 연결된 역 코드

따라서 이름이 비슷하다는 이유만으로 상권과 역 또는 법정동을 자동 결합하면 안 된다.

## 5. 지역 코드 및 좌표

### 5.1 지역 분류 코드 검색

- Method: `GET`
- Endpoint: `https://apis.openapi.sk.com/tmap/poi/areascode`
- 실제 Query Parameters: `version=1`, `count=8000`, `page=1`, `areaTypCd=02`, `largeCdFlag=Y`, `middleCdFlag=Y`, `smallCdFlag=Y`
- `areaTypCd=02`: 법정 코드 기준
- 공식 문서: [지역 분류 코드 검색](https://openapi.sk.com/products/detail?svcSeq=4&menuSeq=19)

TMAP 연결 후 재호출한 결과 HTTP 200으로 성공했다.

```json
{
  "areaCodeInfo": {
    "totalCnt": "5353",
    "listCnt": "5353",
    "contFlag": "0",
    "poiAreaCodes": [
      {
        "areaDepth": "M",
        "largeCd": "11",
        "middleCd": "680",
        "smallCd": "000",
        "districtName": "강남구"
      },
      {
        "areaDepth": "S",
        "largeCd": "11",
        "middleCd": "680",
        "smallCd": "101",
        "districtName": "역삼동"
      }
    ]
  }
}
```

| 경로 | 실제 자료형 | 의미 및 처리 기준 |
|---|---|---|
| `areaCodeInfo.totalCnt` | `str` | 전체 결과 수; 숫자 문자열 |
| `areaCodeInfo.listCnt` | `str` | 현재 목록 수; 숫자 문자열 |
| `areaCodeInfo.contFlag` | `str` | 다음 페이지 여부, `"0"`/`"1"` |
| `poiAreaCodes` | `list` | 지역 코드 구성요소 목록 |
| `areaDepth` | `str` | `L` 대분류, `M` 중분류, `S` 소분류 |
| `largeCd` | `str` | 시도 코드 부분 |
| `middleCd` | `str` | 시군구 코드 부분 |
| `smallCd` | `str` | 읍면동 코드 부분 |
| `districtName` | `str` | 해당 단계 지역명 |

역삼동은 `largeCd=11`, `middleCd=680`, `smallCd=101`로 확인됐다. 이 API의 분할 코드만 조합해 공통 모델의 10자리 `administrative_code`를 임의 생성하지 않고, 아래 Geocoding의 `legalDongCode`를 사용한다.

### 5.2 Geocoding

- Method: `GET`
- Endpoint: `https://apis.openapi.sk.com/tmap/geo/geocoding`
- 실제 주소 조건: `서울`, `강남구`, `역삼동`
- 실제 Query Parameters: `version=1`, `addressFlag=F01`, `coordType=WGS84GEO`
- 공식 문서: [Geocoding](https://openapi.sk.com/products/detail?svcSeq=4&menuSeq=24)

실제 응답:

```json
{
  "coordinateInfo": {
    "coordType": "WGS84GEO",
    "addressFlag": "F01",
    "matchFlag": "M33",
    "lat": "37.500692",
    "lon": "127.036978",
    "city_do": "서울",
    "gu_gun": "강남구",
    "eup_myun": "",
    "legalDong": "역삼동",
    "legalDongCode": "1168010100",
    "adminDong": "역삼1동",
    "adminDongCode": "1168064000",
    "ri": "",
    "bunji": "0",
    "newMatchFlag": "",
    "newLat": "",
    "newLon": "",
    "newRoadName": "",
    "newBuildingIndex": "",
    "newBuildingName": "",
    "newBuildingCateName": "",
    "remainder": ""
  }
}
```

| 경로 | 실제 자료형 | 의미 및 처리 기준 |
|---|---|---|
| `coordType` | `str` | 실제 값 `WGS84GEO` |
| `addressFlag` | `str` | 실제 값 `F01`, 지번 주소 검색 |
| `matchFlag` | `str` | 실제 값 `M33`, 법정동 중심 일치 |
| `lat` | `str` | 법정동 중심 위도; 공통 모델에서 검증 후 `float` 변환 |
| `lon` | `str` | 법정동 중심 경도; 공통 모델의 `longitude`로 이름 변경 |
| `legalDong` | `str` | 법정동명 |
| `legalDongCode` | `str` | 10자리 법정동 코드 |
| `adminDong` | `str` | 행정동명 |
| `adminDongCode` | `str` | 10자리 행정동 코드 |
| 기타 주소 필드 | `str` | 값이 없을 때 `null`이 아니라 빈 문자열이 올 수 있음 |

이번 결과의 좌표는 `matchFlag=M33`인 **역삼동 중심 좌표**다. 역삼역 좌표 또는 네 개 상권 각각의 중심 좌표로 해석하면 안 된다.

## 6. 네 범위의 연결 관계

| 공통 개념 | 원천 필드 | 실제 값 예 | 주의점 |
|---|---|---|---|
| 상권 ID | 상권 API `areaId` | `9307` | SK Puzzle 전용 식별자 |
| 상권명 | 상권 API `areaName` | 역삼역남부 3번출구 | 코드·좌표를 함께 주지 않음 |
| 법정동 코드 | Geocoding `legalDongCode` | `1168010100` | 학원 API의 `districtCode` 입력으로 사용 |
| 행정동 코드 | Geocoding `adminDongCode` | `1168064000` | 법정동 코드와 혼용 금지 |
| 지역 중심 좌표 | Geocoding `lat`, `lon` | `37.500692`, `127.036978` | 문자열이며 법정동 중심 |
| 역 코드 | 역 검색 `stationCode` | `221` | 출구 통행량 API 입력으로 사용 |
| 역 좌표 | 역 검색 `repLat`, `repLng` | `37.500665...`, `127.036478...` | 숫자형이며 역 대표 좌표 |
| 학원 ID | 학원 API `ypId` | `473863` | 개별 학원 식별자 |
| 학원 좌표 | 학원 API `lat`, `lng` | `37.495853`, `127.03096` | 개별 학원 좌표 |

현재 확인된 API만으로는 `areaId=9307`과 `legalDongCode=1168010100` 또는 정확한 상권 중심 좌표가 직접 연결되어 반환되지 않는다. 상권–법정동–좌표 매핑은 별도 공식 데이터, 상권 경계 데이터 또는 명시적인 위치 해석 절차가 필요하다.

## 7. 공통 스키마 매핑 시 준수사항

### 7.1 `AreaIdentity`

```json
{
  "commercial_area_id": "9307",
  "administrative_code": "1168010100",
  "area_name": "역삼역남부 3번출구",
  "latitude": null,
  "longitude": null
}
```

위 예시에서 `administrative_code`는 지역 단위 확인값이지만, `areaId=9307`과 직접 연결된다는 것을 현재 API 응답만으로 확정한 값은 아니다. 또한 법정동 중심 좌표를 상권 중심 좌표로 대신 넣지 않기 위해 좌표를 `null`로 두었다.

### 상권 식별자와 출구 기준 좌표 연결 (2026-09-11 확인)

상권 목록 API에는 좌표가 없으므로, 상권명에 출구가 명시된 역삼역 인접 상권 4개에 한해 TMAP 장소 통합 검색에서 이름이 정확히 일치하는 출구 POI를 조회했다. 아래 좌표는 **상권 중심점이 아니라 해당 출구 기준점**이다. 네 POI의 주소가 모두 `서울 강남구 역삼동`으로 반환됐고, 앞서 Geocoding으로 확인한 역삼동 법정동 코드 `1168010100`을 연결했다.

| commercial_area_id | area_name | TMAP POI | latitude | longitude | administrative_code |
|---|---|---|---:|---:|---|
| `9307` | 역삼역남부 3번출구 | 역삼역 3번출구 | 37.50012959 | 127.03529551 | `1168010100` |
| `9368` | 역삼역북부 4번출구 | 역삼역 4번출구 | 37.50043511 | 127.03512885 | `1168010100` |
| `9310` | 역삼역북부 7번출구 | 역삼역 7번출구 | 37.50110173 | 127.03693422 | `1168010100` |
| `9308` | 역삼역남부 1번출구 | 역삼역 1번출구 | 37.50046292 | 127.03721199 | `1168010100` |

연결값은 `data/reference/commercial_areas.json`에서 관리한다. 실행 시 SK 상권 목록의 ID와 이름이 모두 기준 데이터와 일치할 때만 코드·좌표를 채운다. 기준 데이터에 없거나 이름이 바뀐 상권은 값을 추측하지 않고 `null`로 유지한다.

### 7.2 `NearbyStation`

```json
{
  "station_id": "221",
  "station_name": "역삼역",
  "latitude": 37.500665213235,
  "longitude": 127.03647857603902,
  "distance_m": null
}
```

`distance_m`는 기준 좌표가 확정된 뒤 애플리케이션에서 계산한다. 역 검색 응답 자체에는 거리 값이 없다.

### 7.3 `ToolResult`

정상 호출은 원천 응답을 공통 DTO로 검증한 다음 JSON 직렬화 사전으로 넣는다.

```python
ToolResult(
    success=True,
    source="SK Open API",
    data=normalized_data.model_dump(mode="json"),
    error_code=None,
    error_message=None,
    is_mock=False,
)
```

문자열 숫자를 변환할 때는 다음을 구분한다.

- 식별자와 코드는 문자열 유지: `areaId`, `stationCode`, `stationCodeSeoulmetro`, `legalDongCode`, `adminDongCode`
- 좌표는 유효성 검증 후 실수로 정규화: Geocoding의 `lat`, `lon`
- 건수는 의미를 확인해 정수로 정규화: `totalCnt`, `listCnt`
- 빈 문자열은 필드 정책에 따라 `None` 또는 `missing_data`로 변환

## 8. 확인된 구현상 주의점

1. 학원 `count`를 학원 수로 사용하지 않는다.
2. 학원 API의 `totalCount=1`도 학원 수가 아니다.
3. 출구와 시간대는 `MetricObservation.dimensions`에 보존한다.
4. Geocoding 좌표는 문자열이고 지하철·학원 좌표는 숫자형이므로 정규화가 필요하다.
5. `lon`, `lng`, `repLng`를 공통 필드 `longitude`로 명시적으로 매핑한다.
6. 법정동 코드와 행정동 코드를 혼용하지 않는다.
7. 상권 목록에는 좌표·지역 코드가 없으므로 임의 매핑하지 않는다.
8. 상권 API의 `totalCount`와 실제 목록 길이가 다를 수 있다.
9. 빈 주소 값이 빈 문자열로 반환될 수 있으므로 누락값 처리 규칙이 필요하다.
10. 모든 외부 응답은 DTO 검증 후 `model_dump(mode="json")` 결과만 `ToolResult.data`에 넣는다.
