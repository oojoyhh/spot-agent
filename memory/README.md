# Memory Module

StudySpot의 세션 State와 사용자 장기 Memory를 관리합니다.

## 담당 기능

- `thread_id` 기반 세션별 State 분리
- 창업 조건 부분 수정 및 기존 조건 유지
- 조건 변경 시 영향받는 분석 결과 초기화
- Tool 결과와 점수 결과를 State에 저장
- 사용자 선호 및 관심 상권 장기 저장
- 사용자별 Store 격리
- 새 세션에서 저장된 선호 복원

## 주요 파일

- `state.py`
  - Checkpointer
  - State 초기화 및 조건 병합
  - 조건 변경 시 분석 결과 무효화
  - 요약 메시지 State 갱신

- `store.py`
  - `InMemoryStore`
  - 사용자 선호 조회·저장
  - `save_user_preferences`
  - `save_shortlist`

## 주요 원칙

- 공통 모델은 `models/schemas.py`에서 import합니다.
- 현재 사용자 입력이 장기 선호보다 우선합니다.
- `priority_metrics`는 점수 가중치를 변경하지 않습니다.
- `priority_metrics` 변경 시 점수는 유지하지만 `pending_action`은 초기화합니다.
- 점수는 Memory에서 계산하지 않습니다.
- 사용자 ID는 `RuntimeContext`에서만 사용합니다.
- 장기 저장은 사용자가 명시적으로 요청한 정보만 대상으로 합니다.

## 현재 한계

`InMemorySaver`와 `InMemoryStore`를 사용하므로
프로세스가 재시작되면 세션 State와 장기 Memory가 모두 초기화됩니다.