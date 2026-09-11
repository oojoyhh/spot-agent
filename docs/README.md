# StudySpot 역할별 개발 지시 명세서

## 배포 방법

팀원마다 [00_공통계약.md](00_공통계약.md)와 본인 역할 문서를 함께 전달한다. 구현은 팀원이 직접 수행한다. 이 묶음은 선언·입출력·파일 책임·테스트·완료 조건을 설명하며 기능 구현 코드는 제공하지 않는다.

| 역할 | 문서 | 브랜치 |
|---|---|---|
| 1 SK 학원·지하철 API · 중우 | [01_API_Tool.md](01_API_Tool.md) | feature/api-tools |
| 2 State·Store·Memory · 소유 | [02_Memory.md](02_Memory.md) | feature/memory |
| 3 Guardrail·Middleware · 연주 | [03_Guardrail_Middleware.md](03_Guardrail_Middleware.md) | feature/guardrails |
| 4 Structured Output·점수 · 효주 | [04_Scoring_Structured_Output.md](04_Scoring_Structured_Output.md) | feature/scoring |
| 5 구조·Flow·Prompt·Agent · 석휘 | [05_Agent_Architecture.md](05_Agent_Architecture.md) | feature/agent-core |
| 6 Streamlit·통합 테스트 · 명하 | [06_Streamlit_Integration.md](06_Streamlit_Integration.md) | feature/ui |

[07_Skeleton_권고안.md](07_Skeleton_권고안.md)은 GitHub에 구조와 선언을 먼저 반영하는 방안에 대한 **의견만** 담는다. 실제 저장소·브랜치·PR은 변경하지 않았다.

## 읽을 때 주의할 구분

기존 사용자 합의와 새로 보완한 제안을 분리했다. 특히 API payload 세부 타입, State 타입, 누락 점수의 nullable 확장, 승인 요청 전달, market/action Tool 담당은 skeleton 단계에서 팀이 확정할 제안이다. 확정된 기존 필드명·Tool 이름·기본 배점·브랜치 전략은 유지했다.

근거는 제공된 대화와 추가로 확인한 해당 대화의 공통 규격이다. 이번 작업에서 Drive의 만두스크림.docx 원문이나 실제 API 상품 사양을 재검증하지 않았다. 실제 API 연동 시 담당자가 공식 사양을 확인하도록 명시했다.
