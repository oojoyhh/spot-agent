"""단기 Memory: State 갱신·요약·체크포인트 연결. (추가 제안 파일)

담당: 역할 2 · 소유 · feature/memory
명세: docs/02_Memory.md

- StudySpotState 타입은 models/schemas.py에 선언되어 있으며 여기서는 import만 한다 (중복 선언 금지)
- 현재 대화의 조건은 State에 저장하고, 조건 변경 시 영향받는 상태를 무효화한다
- 긴 대화는 요약하되 최신 창업 조건은 원문으로 유지한다
- thread_id·user_id별로 데이터를 분리한다

현재 상태: 구조만 준비됨. 기능 미구현.
"""
