"""StudySpot 공통 Pydantic 모델.

담당: 역할 4 · 효주 · feature/scoring (이 파일의 유일한 수정 담당)
명세: docs/00_공통계약.md 3~5절, docs/04_Scoring_Structured_Output.md

선언 예정 모델 (공통계약 A안 이름 기준):
- ToolResult, BusinessConditions, RuntimeContext, UserPreferences
- StudySpotState (의미·수명은 역할 2 · 소유가 설계, 선언은 이 파일)
- MarketScore, EvidenceItem, AreaRecommendation, StudySpotResponse
- 추가 제안: AreaIdentity, AnalysisPeriod, MetricObservation, AcademyDemandData,
  NearbyStation, StationTrafficData, ScoringInput, AgentRequest, PendingAction

공통 모델은 이 파일에서 한 번만 선언하고 다른 모듈은 import만 한다.
모델 변경이 필요하면 역할 4에게 요청한다.

현재 상태: 구조만 준비됨. 모델 선언은 공통 선언 PR에서 추가한다.
"""
