# Memory Module
담당: 안소유 sososoy
StudySpot의 세션 State와 사용자 장기 Memory를 관리합니다.

## 담당 기능

- 같은 세션의 대화 및 창업 조건 유지
- 사용자 조건 일부 변경 시 기존 조건 병합
- 조건 변경 시 이전 분석 결과 무효화
- Tool 결과와 점수 결과를 State에 저장
- 사용자 선호 및 관심 상권 장기 저장
- 사용자별 Memory 격리

## 파일

- `state.py`
  - State 초기화·갱신
  - Checkpointer 및 `thread_id`
  - 조건 변경 시 파생 상태 무효화

- `store.py`
  - 사용자 선호 조회·저장
  - `save_user_preferences`
  - `save_shortlist`

## 원칙

- 공통 모델은 `models/schemas.py`에서 import하며 재선언하지 않습니다.
- 현재 조건이 장기 선호보다 항상 우선합니다.
- 점수는 저장만 하며 계산하지 않습니다.
- 장기 저장은 사용자가 명시적으로 요청한 정보만 대상으로 합니다.
- API Key와 개인정보 원문은 저장·로그에 남기지 않습니다.

## 현재 한계

InMemory 저장소를 사용할 경우 프로세스 재시작 후 데이터는 유지되지 않습니다.