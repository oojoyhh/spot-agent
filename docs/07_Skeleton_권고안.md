# GitHub main에 skeleton을 먼저 반영하는 방안 — 의견 제시

## 권장 의견

**팀 폴더 구조와 확정된 공통 인터페이스를 먼저 작은 PR로 main에 반영하는 방식을 권장한다.** 단, 모두 빈 파일인 상태보다 '책임을 설명하는 빈 모듈 + 공통 모델 선언 + 입력/출력 계약 문서'가 유용하다. 이후 각 팀원이 main에서 자신의 기능 브랜치를 만든다.

이 문서는 제안만 제공한다. GitHub 저장소·브랜치·파일·PR은 변경하지 않았다. 실제 skeleton 프로젝트도 생성하지 않았다. 아래 절차는 팀이 나중에 직접 적용할 때의 참고안이다.

## 장단점

| 선택 | 장점 | 단점 |
|---|---|---|
| 폴더·빈 파일만 생성 | 구조·소유권이 명확하고 구현 학습을 침해하지 않음 | 인자·payload가 없어 각자 다른 인터페이스를 만들 수 있음 |
| 구조+모델·인터페이스 선언 | 공통 import·이름·반환 타입을 일찍 맞춤, Mock 기반 독립 개발 가능 | 잘못 고정한 계약을 바꾸면 여러 모듈이 영향받음 |
| 핵심 동작까지 미리 구현 | 빠르게 데모 연결 가능 | 학생의 구현 범위를 줄이고 미합의 정책을 고착화함 |

이번 프로젝트에는 두 번째 방식이 맞다. 산식·재시도·API 호출·Memory 처리·UI 로직은 담당자가 직접 개발한다.

## 권장 구조

아래는 사용자 구조를 유지하고 패키지 표시와 책임 분리에 필요한 파일만 제안한 것이다.

```text
StudySpot/
├── app.py
├── agent/
│   ├── __init__.py
│   ├── main_agent.py
│   └── prompts.py
├── tools/
│   ├── __init__.py
│   ├── market_tools.py
│   ├── academy_tools.py
│   ├── subway_tools.py
│   ├── scoring_tools.py
│   └── action_tools.py       # 역할 1: 전송·일정 API
├── models/
│   ├── __init__.py
│   └── schemas.py
├── memory/
│   ├── __init__.py
│   ├── store.py
│   └── state.py              # 역할 2: 상태 갱신·체크포인트
├── middleware/
│   ├── __init__.py
│   ├── guardrails.py
│   └── middleware.py         # 사용자 파일 배정과 구조의 차이 해소
├── data/
│   └── mock/
│       └── .gitkeep
├── tests/
│   └── .gitkeep
├── docs/
│   ├── 설계서.md
│   └── [공통 계약과 역할별 명세서]
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

빈 디렉터리 추적을 위한 .gitkeep는 데이터·테스트가 들어오면 제거할 수 있다. Python 패키지의 __init__.py는 비워두거나 설명만 넣고 import 시 외부 연결을 만들지 않는다.

## 미리 넣을 것과 남겨둘 것

| 항목 | skeleton에 넣을 범위 | 이후 담당자가 개발할 것 |
|---|---|---|
| 공통 모델 | 이름·필드·타입·기본값·합의한 범위 제약 | 복합 검증·변환 로직 |
| 기능 모듈 | 담당자·목적·입출력 설명 | 실제 함수 본문·오류 처리 |
| Tool 인터페이스 | 합의된 시그니처를 문서 또는 Protocol 선언으로 기록 | Tool 등록·어댑터·호출 |
| State/Store | 필드 의미·수명·키 계약 | 저장소·요약·복원 구현 |
| 점수 | 고정 배점·입출력 모델 | 산식·정규화·confidence 계산 |
| UI·Prompt | 목적과 요구사항 | 화면·프롬프트 본문 |
| 테스트 | 테스트 항목·담당자·기대 결과 문서 | 실제 검증 코드·fixture |

`pass`나 `...`가 들어 있는 일반 함수는 호출 시 None을 반환해 계약 위반을 감출 수 있다. 따라서 **실행 모듈은 설명만 두고, 시그니처는 문서 또는 Protocol에 선언하는 방식**을 우선 권장한다. Stub을 선택한다면 미구현 상태가 분명해야 하고 Agent에 등록하지 않는다. 가짜 성공값은 넣지 않는다.

Mock fixture는 모델 확정 후 각 담당자가 만든다. skeleton 단계에서 실제 데이터처럼 보이는 숫자를 미리 채우지 않는다.

## 공통 파일 수정 방식

역할 5가 폴더·공통 설정·문서 구성을 준비한다. 역할 4가 `models/schemas.py`의 공통 모델 선언을 맡고, 역할 2는 `memory/state.py`의 State 갱신·체크포인트 연결을 맡는다. 역할 1은 네 API Tool 모듈과 관련 테스트를 맡는다. 같은 파일을 동시에 수정하지 않도록 작업 순서를 정한다.

권장 순서는 다음과 같다.

1. 확정된 공통 계약과 역할 1의 API Tool 범위를 팀이 확인한다.
2. 역할 5가 feature/agent-core에서 구조·소유권 문서 PR을 준비한다.
3. 다른 조원 1명 이상 검토 후 main에 merge한다. main 직접 push는 하지 않는다.
4. 역할 4가 갱신된 main을 바탕으로 feature/scoring에서 공통 선언 PR을 준비한다.
5. API·Memory·UI 담당자가 각자 소비할 타입을 확인한 후 merge한다.
6. 각자 최신 main을 본인 feature 브랜치에 반영한 뒤 기능 개발을 시작한다.

이미 기능 브랜치가 있으면 다시 만들지 않고 최신 main을 merge한다. 두 PR은 기능 구현 전 준비 단계이며, 모델 선언 PR에 계산 로직을 섞지 않는다.

## 환경 파일 권고

`.env.example`에는 `OPENAI_API_KEY`, `SK_OPEN_API_KEY`, `DATA_GO_KR_API_KEY`의 빈 값만 둔다. 어떤 키가 현재 필요한지와 선택 항목인지는 README에 적는다. Mock 모드 설정은 팀이 변수명을 확정한 뒤 문서화한다.

`.gitignore`에는 `.env`, `__pycache__/`, `*.pyc`, `.streamlit/secrets.toml`을 포함한다. requirements.txt는 역할 5가 Python·LangChain·Pydantic·Streamlit 등의 호환 버전을 검증한 후 고정한다. 이 문서는 최신 버전 번호를 추정해 제공하지 않는다.

## skeleton PR 완료 기준

- [ ] 최신 사용자 폴더 구조를 유지하고 추가 파일의 이유·소유자를 명시
- [ ] 모든 공통 모델과 Tool 이름·인자·payload를 확정하거나 보류 표시
- [ ] nullable 점수의 0점 기여·승인 전달·API Tool 담당 정책 반영
- [ ] 패키지 import만으로 API/모델/DB 연결이 일어나지 않음
- [ ] 미구현 모듈이 실제 성공 결과를 반환하지 않음
- [ ] 공통 모델의 선언·직렬화·필수 필드 최소 검증 가능
- [ ] 비밀값과 실제 사용자 정보 없음
- [ ] README에 '구조·계약만 준비됨, 기능 미구현' 명시
- [ ] 다른 조원 1명 이상 검토, main 직접 push 없음

Skeleton 완료와 기능 완료는 다르다. skeleton은 연결 규칙의 출발점이며, 각 역할 명세서의 테스트·완료 조건을 충족해야 실제 개발이 끝난다.
