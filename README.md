# Ontoward

Ontoward는 N.O.V.A. 예선의 모의 환자에게 문진·신체진찰을 수행하고 SOAP 초진 기록과 주진단을 제출하는 에이전트 프로젝트다. D15에서 사용자 승인 v5.0 지식과 최소 한국어 질문을 수용하고 정보 보존·파서 어휘 제한을 반영했다. 독립 임상 검증·실제 Luna 품질·공식 제출은 별도 검증 대상이다. 처음 읽는 분은 [워크플로우 백서](submission/README.md)에서 인사부터 진단 제출까지와 각 함수의 책임을 따라갈 수 있다.

[PRD](PRD.md)는 동작 요구사항, [결정 문서](DECISION_STATE.md)는 사용자 선택, 각 범위의 PROJECT_STATE.md는 관측된 진행과 다음 작업을 관리한다. 공모전 규칙은 [공모전 참고 자료](assets/nova-competition-2026/README.md)와 [현재 규칙 업데이트](assets/nova-competition-2026/CHANGES_2026-10-14.md)에서 확인한다.

## 구조

```text
Ontoward/
├── AGENTS.md / README.md / PRD.md
├── PROJECT_STATE.md / DECISION_STATE.md
├── Dockerfile / compose.yaml / .dockerignore
├── .gitignore / .env / .env.example
├── submission/
│   ├── run.py / settings.py / nova_sdk.py
│   ├── workflow/    # 책임 객체·규칙·상태·실행 흐름
│   ├── knowledge/   # RDFLib 코드·실행 Turtle·필요한 JSON
│   ├── requirements.txt / .env
│   └── AGENTS.md / README.md / PROJECT_STATE.md
├── Dev/
│   ├── codex/      # 최소 CLI 환경·인증 설정
│   ├── ontology/   # 현재 v5.0 원천 투영
│   ├── tests/      # 워크플로우·원천 행동 검증
│   └── packaging/  # 제출 ZIP 구성 도구
├── data/
│   ├── ontology/   # v5.0 구조·기초 어휘·deprecated v4.2
│   ├── preparation/v5/ # 전체 원천 SQLite·후보 RDF·검토 자료
│   ├── catalog/    # 원본 경로 목록
│   └── provenance/ # 출처 식별
├── assets/         # 주최자 원본과 공모전 참고 문서
└── Tmp/
    ├── codex/      # 임시 Codex 출력
    └── packaging/  # 생성 ZIP
```

루트는 Docker·공통 문서·Dev 도구와 범위 조정을 소유한다. [submission](submission/README.md)은 실행 코드와 애플리케이션 상태, [data](data/README.md)는 자료·준비 결과를 소유한다. 운영 상태는 [루트](PROJECT_STATE.md), [제출 코드](submission/PROJECT_STATE.md), [데이터](data/PROJECT_STATE.md) 세 곳이며 Dev·Tmp에 상태 범위를 추가하지 않는다.

실행 코드는 submission/workflow/에 모여 있다. Consultation 하나가 다섯 세션을 조정하고 Doctor·InputInterpreter·InterviewPlanner·ClinicalReasoner·SubmissionWriter가 각 기능을 맡는다. rules/에서 규칙을, state/에서 상태와 변경 연산을, io/에서 모델·공식 세션·전송 복구를 찾을 수 있다. run.py는 workflow/runtime.py의 prepare·consult를 SDK에 전달한다. RDFLib 조회와 실행 자산은 submission/knowledge/에 둔다. 자세한 함수·상태·예제는 [제출 워크플로우 백서](submission/README.md), 규칙별 구현과 테스트는 [규칙 색인](Dev/architecture/WORKFLOW_RULES.md)을 참고한다.

## 설정과 개발환경

루트 .env는 로컬 개발용이다. .env.example과 같은 세 변수로 대회 API 주소, 개인 개발 키, 컨테이너의 지침 위치를 설정한다. 초기 키는 빈 값이며 Git과 제출 ZIP에 포함하지 않는다. Compose는 필요한 값만 dev 서비스에 전달한다.

submission/.env는 **ZIP에 포함하는 공개 실행 설정**이다. 현재 지원 값은 다음과 같다.

```dotenv
ONTOWARD_KNOWLEDGE_MANIFEST=knowledge/manifest.json
ONTOWARD_DOCTOR_PROMPT=config/doctor.txt
ONTOWARD_PARSER_PROMPT=config/input_parser.txt
ONTOWARD_TEXTS=config/texts.ko.json
```

공통 설정을 중복하지 않도록 .env와 settings.py를 유지한다. settings.py가 prepare()에서 이 파일을 읽으며 파일 경로는 settings.py 위치를 기준으로 결정한다. 실행 위치가 바뀌어도 같은 submission/knowledge를 참조한다. 같은 이름의 환경변수가 있으면 그것이 우선하며 manifest 경로는 submission/knowledge, 프롬프트·문구는 submission/config 내부 상대 경로여야 한다. 단순 KEY=VALUE 형식으로 공백 행과 주석을 허용하고 셸 확장·따옴표 처리는 하지 않는다. 공식 토큰·세션은 실행기가 제공하며 이 파일에 넣지 않는다. 새로운 설정을 추가할 때는 코드의 허용 항목과 실제 소비 위치도 함께 추가한다.

프로젝트 의존성은 호스트에 설치하지 않고 Docker dev 환경을 사용한다.

```sh
docker compose build dev
docker compose run --rm dev
```

Dockerfile은 submission/requirements.txt의 고정 버전을 PyPI 휠로 설치한다. 별도 ontology-extraction 서비스와 인증 volume은 보존한다. 현재 D09는 기존 dev 이미지의 SQLite·Pydantic·RDFLib로 전체 RF2 Snapshot·BODHI-S를 준비한다. 결정론적 처리가 기본이며 필요한 원천 정규화만 명시적 KST 예산 안에서 개발 Sol을 호출한다. Dev/ontology와 data가 준비·검토를, submission/knowledge가 명시적 승인 후 수용한 실행 자산을 관리한다.

## ZIP 만들기

프로젝트 루트에서 다음 명령을 실행한다.

```sh
docker compose build package
docker compose run --rm -T package
```

결과는 Tmp/packaging/ontoward-submission.zip이다. 압축 루트에는 run.py·requirements.txt·설정·SDK·공개 .env가 놓이고, workflow/·knowledge/ 패키지는 하위 경로를 유지한다. 제출 디렉터리의 AGENTS.md·README.md·PROJECT_STATE.md, 캐시와 루트 개발 .env는 제외된다. package 이미지는 submission/ 입력과 전용 출력만 연결하고 네트워크를 끈다. 구성 도구는 포함 파일·해시·크기·개수를 출력하며, 심볼릭 링크와 허용하지 않은 파일을 거절한다.

수동으로 압축할 때도 **submission 폴더 자체가 아니라 필요한 내부 파일**을 선택하고 안내·상태 문서를 제외한다. .env가 숨김 파일이므로 위 명령 사용을 권장한다. .gitignore는 ZIP 구성 규칙을 대신하지 않는다.

현재 ZIP은 승인된 실제 RDF·manifest, 증상 490개와 속성 16개의 질문, 257개 한국어 표시 이름을 포함한다. 독립 추출 환경에서 실제 자산의 prepare와 합성 환자·모델 응답을 사용한 전체 흐름을 검증했다. 실제 배치에는 진찰·Context 개념과 질환별 계획이 없으므로 해당 기능의 임상 자산까지 준비됐다는 뜻은 아니다.

## 자료와 Git 관리

자료 준비는 공급된 International·Korean RF2와 BODHI-S 원본을 v5.0에 투영하고 data에서 검토·수용한 뒤 필요한 실행 자산만 submission/knowledge에 배치하는 흐름이다. 외부 구조는 개발용이며 실행과 테스트가 외부 data/에 의존하지 않는다. 진료 중에는 하나의 읽기 전용 RDFLib Graph를 사용하며 환자 관찰은 CaseState에 둔다. 자세한 온톨로지·고정 HPI·SOAP 계약은 PRD와 D08·D11·D12·D13·D14를 따른다.

Git에는 코드·계약·상태·PPTX 변환 Markdown·간결한 출처와 검토 요약·공개 실행 설정을 남긴다. 대용량 원본, 생성 추출 결과, 임시 작업, 캐시와 로컬 비밀값은 .gitignore로 제외한다. 실제 파일을 삭제하거나 Git 저장소를 초기화하는 규칙은 아니다.

현재 준비는 전체 International·Korean Snapshot과 BODHI-S 8개 CSV를 수집하는 SQLite DB와 v5.0 후보 RDF다. [구축 도구](Dev/ontology/README.md)와 [준비 결과](data/preparation/v5/README.md)에서 입력·manifest·제외/보류·배치 검토·검증을 확인한다. 앞선 세 Target preview와 [deprecated 자료](data/ontology/deprecated.json)는 보존하며 구형 작업을 재개하지 않는다.

다음 단일 작업은 사실별 입력 검증과 질문 목적에 맞는 복구 설계다. [분석 보고서의 채택·보류 근거](Dev/architecture/NOVA_REVIEW_2026-10-15.md)를 프로젝트 자료로 남겼다. 질환별 치료·추적·교육 문구와 실제 모델·공식 실행 여부는 각 소유 상태에서 확인한다.
