# Ontoward

Ontoward는 N.O.V.A. 예선의 모의 환자에게 문진·신체진찰을 수행하고 SOAP 초진 기록과 주진단을 제출하는 에이전트 프로젝트다. 현재 임상 처리는 D11의 추상 골격이며, 전체 진료와 공식 제출이 완료된 상태는 아니다.

[PRD](PRD.md)는 동작 요구사항, [결정 문서](DECISION_STATE.md)는 사용자 선택, 각 범위의 PROJECT_STATE.md는 관측된 진행과 다음 작업을 관리한다. 공모전 규칙은 [공모전 참고 자료](assets/nova-competition-2026/README.md)와 [10월 12일 변경 비교](assets/nova-competition-2026/CHANGES_2026-10-12.md)에서 확인한다.

## 구조

```text
Ontoward/
├── AGENTS.md / README.md / PRD.md
├── PROJECT_STATE.md / DECISION_STATE.md
├── Dockerfile / compose.yaml / .dockerignore
├── .gitignore / .env / .env.example
├── submission/
│   ├── run.py / settings.py / nova_sdk.py
│   ├── agents/      # 실행 객체·공통 상태·워크플로우
│   ├── knowledge/   # RDFLib 코드·실행 Turtle·필요한 JSON
│   ├── requirements.txt / .env
│   └── AGENTS.md / README.md / PROJECT_STATE.md
├── Dev/
│   ├── codex/      # 최소 CLI 환경·인증 설정
│   └── packaging/  # 제출 ZIP 구성 도구
├── data/
│   ├── ontology/   # v4.2 스키마·기초 어휘
│   ├── catalog/    # 원본 경로 목록
│   └── provenance/ # 출처 식별
├── assets/         # 주최자 원본과 공모전 참고 문서
└── Tmp/
    ├── codex/      # 임시 Codex 출력
    └── packaging/  # 생성 ZIP
```

루트는 Docker·공통 문서·Dev 도구와 범위 조정을 소유한다. [submission](submission/README.md)은 실행 코드와 애플리케이션 상태, [data](data/README.md)는 자료·준비 결과를 소유한다. 운영 상태는 [루트](PROJECT_STATE.md), [제출 코드](submission/PROJECT_STATE.md), [데이터](data/PROJECT_STATE.md) 세 곳이며 Dev·Tmp에 상태 범위를 추가하지 않는다.

실행 객체는 submission/agents/에서, RDFLib 접근 코드는 submission/knowledge/에서 수정한다. 공통 상태·자원은 agents/state.py와 agents/resources.py에서 공유하며 run.py는 agents/runtime.py의 prepare·consult를 전달한다. 별도 app/ 코드나 루트 실행 래퍼는 두지 않는다. SDK 1.0.1은 제공 원본의 수정 없는 사본이며 해시는 [출처 기록](assets/nova-competition-2026/SOURCES.md)에 있다.

## 설정과 개발환경

루트 .env는 로컬 개발용이다. .env.example과 같은 세 변수로 대회 API 주소, 개인 개발 키, 컨테이너의 지침 위치를 설정한다. 초기 키는 빈 값이며 Git과 제출 ZIP에 포함하지 않는다. Compose는 필요한 값만 dev 서비스에 전달한다.

submission/.env는 **ZIP에 포함하는 공개 실행 설정**이다. 현재 지원 값은 다음과 같다.

```dotenv
ONTOWARD_KNOWLEDGE_MANIFEST=knowledge/manifest.json
```

공통 설정을 중복하지 않도록 .env와 settings.py를 유지한다. settings.py가 prepare()에서 이 파일을 읽으며 파일 경로는 settings.py 위치를 기준으로 결정한다. 실행 위치가 바뀌어도 같은 submission/knowledge를 참조한다. 같은 이름의 환경변수가 있으면 그것이 우선하며 설정·환경값의 경로는 submission/knowledge 내부 상대 경로여야 한다. 단순 KEY=VALUE 형식으로 공백 행과 주석을 허용하고 셸 확장·따옴표 처리는 하지 않는다. 공식 토큰·세션은 실행기가 제공하며 이 파일에 넣지 않는다. 새로운 설정을 추가할 때는 코드의 허용 항목과 실제 소비 위치도 함께 추가한다.

프로젝트 의존성은 호스트에 설치하지 않고 Docker dev 환경을 사용한다.

```sh
docker compose build dev
docker compose run --rm dev
```

Dockerfile은 submission/requirements.txt의 고정 버전을 PyPI 휠로 설치한다. 별도 ontology-extraction 서비스는 gpt-6-luna·medium 설정의 최소 Codex 환경과 전용 인증 volume을 소유한다. 현재 자동 추출 프로그램과 임상 산출물은 없으며 새 준비 계약은 D09에서 정한다. 개발·환경 확인 명령이 모델 호출을 시작하지 않는다.

## ZIP 만들기

프로젝트 루트에서 다음 명령을 실행한다.

```sh
docker compose build package
docker compose run --rm -T package
```

결과는 Tmp/packaging/ontoward-submission.zip이다. 압축 루트에는 run.py·requirements.txt·설정·SDK·공개 .env가 놓이고, agents/·knowledge/ 패키지는 하위 경로를 유지한다. 제출 디렉터리의 AGENTS.md·README.md·PROJECT_STATE.md, 캐시와 루트 개발 .env는 제외된다. package 이미지는 submission/ 입력과 전용 출력만 연결하고 네트워크를 끈다. 구성 도구는 포함 파일·해시·크기·개수를 출력하며, 심볼릭 링크와 허용하지 않은 파일을 거절한다.

수동으로 압축할 때도 **submission 폴더 자체가 아니라 필요한 내부 파일**을 선택하고 안내·상태 문서를 제외한다. .env가 숨김 파일이므로 위 명령 사용을 권장한다. .gitignore는 ZIP 구성 규칙을 대신하지 않는다.

현재 ZIP은 구조 검증용이다. 임상 함수와 지식 로딩은 미구현이며 승인된 임상 묶음과 manifest도 준비되지 않았다. 빈 manifest나 임의 진단으로 이를 채우지 않는다.

## 자료와 Git 관리

자료 준비는 assets 원본에서 추출·검토하고 data에서 승인한 뒤 필요한 실행 자산만 submission/knowledge에 배치하는 흐름이다. 외부 구조는 개발용이며 실행과 테스트가 외부 data/에 의존하지 않는다. 진료 중에는 하나의 읽기 전용 RDFLib Graph를 사용하며 환자 관찰은 CaseState에 둔다. 자세한 온톨로지·고정 HPI·SOAP 계약은 PRD와 D08·D11·D12·D13·D14를 따른다.

Git에는 코드·계약·상태·PPTX 변환 Markdown·간결한 출처와 검토 요약·공개 실행 설정을 남긴다. 대용량 원본, 생성 추출 결과, 임시 작업, 캐시와 로컬 비밀값은 .gitignore로 제외한다. 실제 파일을 삭제하거나 Git 저장소를 초기화하는 규칙은 아니다.

다음 애플리케이션 작업은 세션 입력·공통 Gateway·Fixed HPI 구현이며, 실행 여부와 준비 작업의 별도 진행은 각 상태 문서에서 확인한다.
