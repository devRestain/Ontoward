# Ontoward

Ontoward는 N.O.V.A. 예선의 모의 환자에게 문진·신체진찰을 수행하고 SOAP 초진 기록과 주진단을 제출하는 에이전트 프로젝트다. D17의 Pattern 중심 적합도와 D35의 세션 문진 목표·상한, 질문 가치에 따른 종료와 공감 공유 예산을 적용하며 D18에서 이전 지식·승인을 철회하고 원천 전용 v5.0 후보를 다시 준비한다. D19는 진찰 소견·관찰 속성과 근거 저장을 개선한다. 독립 임상 검증·실제 Luna 품질·공식 제출은 별도 검증 대상이다. 처음 읽는 분은 [워크플로우 백서](submission/README.md)에서 인사부터 진단 제출까지와 각 함수의 책임을 따라갈 수 있다.

[PRD](PRD.md)는 동작 요구사항, [결정 문서](DECISION_STATE.md)는 사용자 선택, 각 범위의 PROJECT_STATE.md는 관측된 진행과 다음 작업을 관리한다. 공모전 규칙은 [공모전 참고 자료](assets/nova-competition-2026/README.md)와 [현재 규칙 업데이트](assets/nova-competition-2026/CHANGES_2026-10-14.md)에서 확인한다.

[프로젝트 흐름 지도](Test/atlas.html)는 브라우저에서 직접 여는 개인용 오프라인 안내서다. 전체 구조·다섯 내부 세션·공통 행동 루프·Pattern 추론·다음 질문 선택·지식 준비를 정적 도식으로 설명한다. `Test/atlas.html` 파일을 브라우저로 열면 되며 서버·빌드·패키지 설치는 필요 없다. 2026-10-17의 문서·구현 기준으로 작성했으며 자동 갱신하지 않는다.

D26의 현재 제출 설정은 Education을 pass한다. 교육 행동과 보호 턴을 사용하지 않고 `P.education`을 비운 채 문진·진찰·해석·진단·SOAP·DIAGNOSE 확인까지 진행한다. 교육 검색은 후속 범위이며, 공식 서버 수락과 실제 점수는 별도 검증 대상이다.

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
│   ├── education/  # 질환별 고정 원문 교육 전처리
│   ├── tests/      # 워크플로우·원천 행동 검증
│   └── packaging/  # 제출 ZIP 구성 도구
├── data/
│   ├── ontology/   # v5.0 구조 계약
│   ├── preparation/v5/ # 로컬 원천 DB·준비 결과와 버전 관리할 요약
│   ├── catalog/    # 원본 경로 목록
│   └── provenance/ # 출처 식별·저장 정리와 복원 영수증
├── assets/         # 주최자 원본과 공모전 참고 문서
├── Test/           # 웹 실행기·진료 과정 리포트·NOVA 모의 환자·격리 컨테이너
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
ONTOWARD_PARSER_PROMPT=config/input_parser.txt
ONTOWARD_TEXTS=config/texts.ko.json
ONTOWARD_EDUCATION_ENABLED=false
```

공통 설정을 중복하지 않도록 .env와 settings.py를 유지한다. settings.py가 prepare()에서 이 파일을 읽으며 파일 경로는 settings.py 위치를 기준으로 결정한다. 실행 위치가 바뀌어도 같은 submission/knowledge를 참조한다. 같은 이름의 환경변수가 있으면 그것이 우선하며 manifest 경로는 submission/knowledge, 프롬프트·문구는 submission/config 내부 상대 경로여야 한다. 단순 KEY=VALUE 형식으로 공백 행과 주석을 허용하고 셸 확장·따옴표 처리는 하지 않는다. 공식 토큰·세션은 실행기가 제공하며 이 파일에 넣지 않는다. 새로운 설정을 추가할 때는 코드의 허용 항목과 실제 소비 위치도 함께 추가한다.

프로젝트 의존성은 호스트에 설치하지 않고 Docker dev 환경을 사용한다.

```sh
docker compose build dev
docker compose run --rm dev
```

Dockerfile은 submission/requirements.txt의 고정 버전을 PyPI 휠로 설치한다. D18 준비는 기존 dev 이미지의 SQLite·Pydantic·RDFLib로 전체 RF2 Snapshot·BODHI-S를 처리한다. 필요한 정규화·한국어 생성은 별도 ontology-extraction 서비스와 기존 전용 Codex 인증 volume을 사용한다. 선택 어휘의 번역·임상 질문 전체 작업 집합과 생성·의미 대조의 유한 호출 상한을 고정한다. Dev/ontology와 data가 준비·검토를, submission/knowledge가 명시적 승인 후 수용한 실행 자산을 관리한다.

## 로컬 공개 샘플 테스트

[Test 실행 안내](Test/README.md)에 SDK HTTP API와 예선 자원 제약을 재현하는 컨테이너를 둔다. `sh Test/run.sh verify`는 외부 모델 없는 API 경계 검사이고 `sh Test/run.sh C10 scripted`는 기존 제출 에이전트의 오프라인 실행이다. 별도 `nova` 모드는 루트 개발 키로 모의 환자·진찰·Gateway를 호출하며 시뮬레이터만 외부 네트워크를 사용한다. 환자 대본·진찰표·참조 SOAP·개발 키는 에이전트에 연결하지 않는다. 로컬 결과는 채점하지 않으며 공식 평가와 구분한다.

`sh Test/web.sh`로 시작한 뒤 [로컬 테스트 사이트](http://127.0.0.1:8765)에서 증례와 실행 조건을 선택할 수 있다. 기본은 C10·NOVA·최대 200회 요청이며 실행 버튼을 누르면 테스트가 시작된다. 완료되면 같은 페이지에서 실제 대화·내부 세션·턴별 상태 변화·모델 요청·진단 근거와 최종 SOAP를 확인한다. 이전 실행도 다시 열 수 있고 실행별 `report.html`을 보존한다. 사이트는 submission 파일을 수정하지 않으며 실행 실패와 부분 로그도 보여준다. 자세한 관측·실행 경계는 [D31](DECISION_STATE.md#D31)을 따른다.

[D29](DECISION_STATE.md#D29)는 실제 Input Gateway가 주호소를 기존 Symptom 하나에 매핑하도록 요구하고 원천의 한·영 라벨·동의어와 제한된 전체 색인 재검색을 사용한다. Test의 증례별 문자열 매처는 제거했다. 오프라인 회귀와 프로토콜 대역의 통과는 실제 NOVA의 자연어 해석 정확도와 구분한다.

## ZIP 만들기

프로젝트 루트에서 다음 명령을 실행한다.

```sh
docker compose build package
docker compose run --rm -T package
```

결과는 Tmp/packaging/ontoward-submission.zip이다. 압축 루트에는 run.py·requirements.txt·설정·SDK·공개 .env가 놓이고, workflow/·knowledge/ 패키지는 하위 경로를 유지한다. 제출 디렉터리의 AGENTS.md·README.md·PROJECT_STATE.md, 캐시와 루트 개발 .env는 제외된다. package 이미지는 submission/ 입력과 전용 출력만 연결하고 네트워크를 끈다. 구성 도구는 포함 파일·해시·크기·개수를 출력하며, 심볼릭 링크와 허용하지 않은 파일을 거절한다.

수동으로 압축할 때도 **submission 폴더 자체가 아니라 필요한 내부 파일**을 선택하고 안내·상태 문서를 제외한다. .env가 숨김 파일이므로 위 명령 사용을 권장한다. .gitignore는 ZIP 구성 규칙을 대신하지 않는다.

D18의 원천 전용 재구축과 D20 그래프 수용 뒤, D23에서 D22의 한국어 환자 행동 1,309개를 실행 자산으로 수용했다. 현재 manifest는 `admitted`이며 prepare는 문진 1,308개와 진찰 요청 1개를 엄격하게 검증한다. 완전한 원천 기반 표현·매핑·문구의 공모전용 사용은 승인되었으며 추가 사용자·임상 승인 대기가 없다. 의미·단위·획득 방식이 빠진 레코드는 기술적 제외로 남긴다. [런타임 수용 결과](data/preparation/v5/runtime-text-2026-10-16/README.md)에서 한국어 합성 상담·SOAP·확인 종료와 부모 data/assets 없는 독립 ZIP 검증을 확인할 수 있다. 공식 서비스 접속·제출·평가는 실행하지 않았다.

## 자료와 Git 관리

자료 준비는 공급된 International·Korean RF2와 BODHI-S 원본을 v5.0에 투영하고 data에서 검토·수용한 뒤 필요한 실행 자산만 submission/knowledge에 배치하는 흐름이다. 외부 구조는 개발용이며 실행과 테스트가 외부 data/에 의존하지 않는다. 진료 중에는 하나의 읽기 전용 RDFLib Graph를 사용하며 환자 관찰은 CaseState에 둔다. 자세한 온톨로지·핵심 HPI·적응형 문진·SOAP 계약은 PRD와 D08·D12·D13·D14·D17을 따른다.

Git에는 코드·계약·상태·PPTX 변환 Markdown·간결한 출처와 검토 요약·공개 실행 설정, 활성 manifest가 참조하는 실행 Turtle·한국어 JSON을 남긴다. 대용량 원본, 준비 DB·카탈로그·작업 집합·요청 원문·압축 보관본, 임시 작업, 캐시와 로컬 비밀값은 .gitignore로 제외한다. 이미 추적하던 생성 파일은 추적만 해제하고 로컬 준비 경로에 보존한다. 실행 자산은 GitHub에서 받은 소스에도 함께 있어야 한다.

현재 상담은 `submission/` 내부 자산만 읽는다. `data/preparation/v5/source-only-2026-10-16/findings-2026-10-16/ontology.sqlite3`는 준비용 공유 원천 DB로 원래 경로를 유지한다. 과거 D18의 두 DB 확장본은 각 `archives/ontology.sqlite3.gz`에 바이트 단위로 보관했으며 [복원 해시와 영수증](data/provenance/storage-cleanup-2026-10-16-archives.json)을 확인한 뒤 필요할 때만 원래 경로에 복원한다. 과거 스냅샷 복원은 현재 상담 실행에 필요하지 않다.

저장 공간 정리의 범위와 검증은 [정리 영수증](data/provenance/storage-cleanup-2026-10-16.json), [Docker 정리 기록](data/provenance/storage-cleanup-2026-10-16-docker.json), [D24](DECISION_STATE.md#D24)를 참고한다. `.dockerignore`는 의존성·패키징 도구만 빌드 컨텍스트에 허용하므로 로컬 DB나 원본 자료를 이미지에 복사하지 않는다. 현재 파일 목록의 독립 GitHub 소스 ZIP은 `Tmp/packaging/ontoward-github-source.zip`으로 만든다.

[D25](DECISION_STATE.md#D25)에 따라 기존 로컬 main의 작업과 기록은 `codex/pre-cleanup-20261016` 브랜치에 보존하고 정리된 소스와 실행 자산을 새 main과 origin/main에 반영했다. 기존 대용량 blob을 가진 세 로컬 커밋은 보존 브랜치에 남아 있으며 새 main은 확인한 원격 main에서 이어진다. main의 원격 반영에는 일반 push를 사용했고 보존 브랜치는 로컬에 유지한다. [게시 검증 기록](data/provenance/github-publication-2026-10-16.json)에서 원격 대상·확인한 기준 커밋·실행 파일 동일성·객체 크기 검사를 확인할 수 있다. 원천 DB·카탈로그 근거 사전·요청 대장과 보관본은 로컬 준비 경로에 유지한다.

현재 준비는 전체 International·Korean Snapshot과 BODHI-S 8개 CSV를 보존한 SQLite와 원천 전용 v5.0 후보다. [구축 도구](Dev/ontology/README.md)와 [준비 결과](data/preparation/v5/source-only-2026-10-16/README.md)에서 깨끗한 베이스·삭제 영수증·14개 클래스 추출·한국어 작업·생성 증빙을 확인한다. pre-v5 파생 자료, 이전 seed·임상 배치·번역·승인·지침 교육 초안과 그 임시 사본을 삭제했으며 원본 assets는 보존한다.

D17이 채택한 사실별 입력 검증·질문 재계획과 이전 검토의 경계는 [분석 보고서의 채택·보류 근거](Dev/architecture/NOVA_REVIEW_2026-10-15.md)에 남긴다. 작업 순서와 실제 실행 여부는 각 소유 상태에서 확인한다.
