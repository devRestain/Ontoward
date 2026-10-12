# 제출 에이전트

이 디렉터리는 Ontoward 실행 코드의 단일 원본이다. run.py가 agents/runtime.py의 prepare·consult를 SDK run_agent에 전달한다. 하나의 파일에 책임을 모으지 않고 실행 객체, 공통 상태·자원, 그래프 조립과 RDFLib 접근을 분리한다.

## 구조와 책임

```text
submission/
├── run.py / nova_sdk.py / requirements.txt
├── .env / settings.py
├── agents/
│   ├── __init__.py
│   ├── runtime.py       # prepare·consult 조정
│   ├── state.py         # CaseState·InquirySlot·ActionSpec·Update
│   ├── resources.py     # 준비한 지식·Gateway·Interface 공유
│   ├── session.py       # SessionController: 초기 입력·예산
│   ├── gateway.py       # InputGateway: 응답 파싱·근거 보존
│   ├── interview.py     # InterviewAgent: HPI·추가 문진·진찰 선택
│   ├── reasoning.py     # ReasoningAgent: 후보 검색·재평가·종합
│   ├── interface.py     # InterfaceAgent: 행동 표현·검증·전송
│   ├── submission.py    # SubmissionAgent: 교육·SOAP·진단 제출
│   ├── routing.py       # 공통 상태의 순수 분기
│   └── workflow.py      # ConsultationWorkflow: 객체 메서드 연결
├── knowledge/
│   ├── __init__.py
│   ├── graph.py         # ClinicalKnowledge: RDFLib Graph·고정 조회
│   ├── README.md
│   └── 향후 .ttl·.json   # 실행 스키마·어휘·임상 묶음·manifest
└── AGENTS.md / README.md / PROJECT_STATE.md
```

객체들은 동일한 CaseState 모델과 준비 자원을 사용한다. 각 consult 호출은 새 워크플로우·실행 객체를 구성하고 환자 상태는 CaseState에만 둔다. 패키지 내부는 상대 import를 사용하며 경로를 맞추기 위한 sys.path 수정은 하지 않는다. SDK는 제공 1.0.1의 수정 없는 사본이다.

[PRD](../PRD.md), [D14](../DECISION_STATE.md#D14), [상태](PROJECT_STATE.md)에서 동작·선택·관측 결과를 확인한다. 자료 승인 결과는 [data 상태](../data/PROJECT_STATE.md)가 소유한다.

## 설정과 지식

.env와 settings.py는 여러 객체가 같은 설정·경로 규칙을 사용하도록 유지한다. .env의 ONTOWARD_KNOWLEDGE_MANIFEST 기본값은 knowledge/manifest.json이며 동일한 실행 환경변수가 있으면 우선한다. settings.py의 파일 위치를 기준으로 경로를 해석하므로 실행 작업 디렉터리에 의존하지 않는다. 설정과 실행 환경값의 경로는 submission/knowledge 내부에 있어야 한다. 실행과 추후 테스트는 이 디렉터리의 완성된 자산만 사용한다.

설정은 KEY=VALUE 형식으로 주석·빈 행을 허용한다. 셸 확장·따옴표 문법을 사용하지 않으며 지원하지 않는 항목이나 중복·빈 값은 오류로 처리한다. 루트 .env는 개발 설정용이고 공식 토큰·세션은 실행기가 제공한다.

현재 [knowledge 위치](knowledge/README.md)에는 Python 코드와 안내가 있으며 실행 Turtle·JSON·manifest는 없다. 필요한 schema.ttl·vocabulary.ttl·임상 Turtle·schema JSON도 이 안에 함께 둔다. ClinicalKnowledge는 하나의 RDFLib Graph를 보유하는 객체이며 실제 로딩·조회는 명시적 미구현 경계다. 원본·추출 결과·검토 기록을 승인 없이 복사하지 않는다.

## 압축

프로젝트 루트에서 실행한다.

```sh
docker compose build package
docker compose run --rm -T package
```

생성 경로는 Tmp/packaging/ontoward-submission.zip이다. run.py·requirements.txt·설정·SDK·**.env**는 ZIP 루트에, agents/·knowledge/는 패키지 경로 그대로 들어간다. 실행 자산이 완성되면 knowledge/ 아래의 .ttl·.json을 함께 포함한다. package 이미지는 submission/을 읽기 전용 입력으로, 전용 결과 디렉터리만 출력으로 연결한다. 모든 안내·상태 문서와 캐시는 제외하며 ZIP 안에 submission/ 상위 폴더를 만들지 않는다.

임상 처리·지식 로딩·실제 SDK 행동은 아직 미구현이다. 현재 검증은 리팩토링의 동작 보존과 압축 결과를 확인하며 전체 진료·공식 샘플·제출·채점 성공은 별도다.
