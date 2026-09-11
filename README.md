# StudySpot

서울 내 API 지원 상권 5~10곳에서 스터디카페 출점 후보를 최대 3곳 추천하는 LangChain Agent.

> **현재 상태: 구조·계약만 준비됨. 기능 미구현.**
> 각 파일 상단 docstring에 담당자·목적·명세 문서가 적혀 있다.

## 폴더 구조와 담당

| 경로 | 내용 | 담당 · 브랜치 |
|---|---|---|
| `app.py` | Streamlit UI | 6 명하 · `feature/ui` |
| `agent/main_agent.py`, `agent/prompts.py` | Agent 생성·연결, System Prompt | 5 석휘 · `feature/agent-core` |
| `tools/academy_tools.py`, `tools/subway_tools.py` | SK 학원·지하철 API Tool | 1 중우 · `feature/api-tools` |
| `tools/scoring_tools.py`, `models/schemas.py` | 점수 계산, 공통 모델 | 4 효주 · `feature/scoring` |
| `memory/store.py`, `memory/state.py` | 장기 Store, State 갱신·체크포인트 | 2 소유 · `feature/memory` |
| `middleware/guardrails.py`, `middleware/middleware.py` | Guardrail 정책, 훅·재시도 | 3 연주 · `feature/guardrails` |
| `tools/market_tools.py` | 상권·방문자·경쟁·임대 조회 | 인터페이스 5 석휘, 구현 미정 |
| `tools/action_tools.py` | 보고서 전송·일정 등록 | 미정 |
| `docs/` | 공통계약, 역할별 명세서, 설계서 | — |

## 실행 준비

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 키 값 입력, 커밋 금지
```

실행·테스트 명령은 기능 구현 후 추가한다.

## 개발 규칙

- 공통 규격의 최종 원본은 [docs/00_공통계약.md](docs/00_공통계약.md)
- 공통 모델은 `models/schemas.py`에서 한 번만 선언하고 import해서 사용한다 (수정은 역할 4에게 요청)
- 본인 feature 브랜치에서 작업 → PR → 다른 조원 1명 이상 검토 후 merge. `main` 직접 push 금지
- 작업 시작 전 최신 `main`을 본인 브랜치에 merge
- `.env`, API 키, 개인정보, `.streamlit/secrets.toml` 커밋 금지
