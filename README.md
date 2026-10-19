# Ontoward

Ontoward는 N.O.V.A. 예선의 모의 환자에게 문진·신체진찰을 수행하고 **SOAP 초진 기록과 주진단 하나를 제출하는 에이전트**다. 현재 알고리즘은 **D47·d47.1**이다. 세션 객체가 통합 사실과 등록 그래프를 전처리해 공통 DoctorBrain으로 LLM을 호출하고 결과를 검증한다. DD 종료 때 고정한 단일 평가를 Education과 Python SOAP가 함께 읽는다.

[워크플로우 백서](submission/README.md)는 네 알고리즘과 입력부터 완료 수신까지의 실행을 설명한다. [PRD](PRD.md)는 요구사항, [결정 문서](DECISION_STATE.md#D47)는 선택한 방향, [D47 증빙](data/provenance/algorithm-d47-2026-10-19.json)은 실제 검증과 독립 ZIP 신원을 기록한다. 운영 상태는 [루트](PROJECT_STATE.md)·[제출 코드](submission/PROJECT_STATE.md)·[데이터](data/PROJECT_STATE.md)의 세 범위로 유지한다.

## 현재 진료 알고리즘

| 소유자 | 책임 | LLM effort |
|---|---|---|
| DoctorEar | 초기 입력과 SAY·EXAM의 문맥 분석, 정확한 Python 연결, 선택적 DB 정규화와 수용 | medium |
| DoctorBrain | 모든 모델 실행·역할별 effort·한도·사용량·전송 오류와 재전송 | 호출 역할에 따름 |
| 다섯 세션 객체 | 수집과 임상 입력 전처리·순위/행동 수용·고정·영어 계획 | 임상·계획 high |
| DoctorMouth | 준비 문구 검증, 공감·진단·한국어 안내, SAY·EXAM 실행 | medium |
| Consultation | 다섯 세션·예산·입력→판단→행동·DD 고정 | 없음 |
| SubmissionWriter | 고정 자료의 Python SOAP, DIAGNOSE·완료 확인 | 없음 |

모든 기능은 같은 DoctorBrain을 통해 기존 `openai/gpt-6-luna`를 호출한다. 입력 해석·임상 판단·환자 표현의 권한을 분리하고 기존 이름의 호환 객체는 두지 않는다. 외부 `prepare()`·`consult()`와 원본 SDK 계약은 유지한다.

1. **초기 그래프와 갱신:** 초기부터 현재 Target·Attribute·등록 Context의 실제 경로로 질환을 회수한다. 부분 패턴·음성·미확인도 검토 경로가 된다. Python이 관찰·episode·주체를 지키며 지지·불일치·미확인을 구성한다.
2. **감별과 주진단:** LLM은 요청에 제공된 질환 참조 순서를 선택한다. 기존 유효 후보는 보존하고 점수로 재정렬하지 않는다. 첫 세 세션 종료에 각각 한 번 평가하고 DD에서는 unknown을 포함한 환자 응답마다 순위와 다음 행동을 판단한다. 동일 응답의 내부 재진입은 중복 호출하지 않는다. DD 마지막 입력 후 평가·기반 사실을 고정한다.
3. **질문:** 필수 주호소 전체 속성·Open Inquiry·기본 병력은 코드가 준비한다. 선택 질문은 미확인 feature·applicability에서 만들고 LLM이 실행 가능한 참조 하나를 고른다. 증상 존재 확인이 속성 질문보다 먼저다. 질환별 기대 답·조건과 가족 구성원별 완료 범위를 보존한다.
4. **SOAP:** 환자 age·sex·historian, 주체·시점·조건·단위·수치 범위, 실제 EXAM 취득을 보존한다. S/O에 사용한 문구를 A에서 재사용하고 고정 1위를 별도 diagnosis로 제출한다. 최종 형식은 15개 SOAP 문자열이며 `O.tests`는 빈 문자열이다.

D38의 점수 선택기·가상 답변·utility·완성 패턴 진단 gate는 정상 런타임에서 제거했다. 비교·추적·비용 분석은 Test가 담당한다. Submission에는 통합 facts·Assessment·plan, 현재 질문과 compact Answer, 공식 세션 예산, 처리 중 turn만 둔다. 원문 대화는 Ear의 참조 해석용 한 벌이다.

D45 공식 `turns_remaining`이 행동 예산의 기준이다. 다섯 세션 목표/상한은 **5/7·7/14·7/9·3/10·5/10**, 전체는 **50턴·모델 200회·입력 500,000·출력 100,000토큰**이다. 새 행동 전에 응답 처리·최종 판단과 복구·활성 계획/한국어 안내·제출을 보호한다. Education 비활성 설정은 교육 예약을 하지 않는다. 내부 판단·SOAP·DIAGNOSE는 행동 턴을 소비하지 않는다.

## 실행 지식과 준비 경계

현재 [manifest](submission/knowledge/manifest.json)는 schema `5.0`, status `admitted`, algorithm `d47.1`이다. 읽기 전용 RDFLib Graph 하나에 **113,062 triples·843 Disease·533 Symptom·1,925 Pattern·9,955 Association**을 로드한다. 임상 그래프·어휘·질문·한국어 문구·가이드라인 핀은 이번 개편에서 바꾸지 않았다. age·sex·historian·보고 수치도 같은 사실 정본에서 임상·계획·HPI에 전달하며 없는 인구학 진단 조건을 만들지 않는다.

v5.0의 14개 클래스·관계와 원천→준비→수용 경로는 [백서의 스키마](submission/README.md#ontology-schema)와 [준비 파이프라인](submission/README.md#extraction-pipeline)을 따른다. 원천 점수 메타데이터와 수용 영수증은 보존하지만 현재 진단 순위의 Python 점수 gate로 사용하지 않는다. D42 일반 호소 배치와 이전 승인·ZIP도 보존한다.

고정 진단 뒤 EducationSession은 공통 Brain 호출로 [가이드라인 탐색 인덱스](submission/knowledge/guideline-index.json)를 사용해 영어 P를 생성한다. 원문은 `NOVA_GUIDELINES_DIR`의 제공 마운트에서 해시 검증 후 읽으며 ZIP에 넣지 않는다. 원문 근거와 모델 지식 보완을 구분한다. Mouth는 진단부터 NFC 1–30자 한국어로 안내하며 계획 준비와 실제 전달 결과를 따로 기록한다. 부모 `data/`의 준비 DB와 환자 대본·모범 기록은 에이전트 입력이 아니다.

## 디렉터리

```text
Ontoward/
├── AGENTS.md / README.md / PRD.md
├── PROJECT_STATE.md / DECISION_STATE.md
├── Dockerfile / compose.yaml
├── submission/
│   ├── run.py / settings.py / nova_sdk.py / requirements.txt / .env
│   ├── workflow/    # Ear·Brain·Mouth·Consultation·Writer·규칙·상태·전송
│   ├── config/      # 프롬프트·임상 문구
│   └── knowledge/   # RDFLib reader·실행 자산·manifest
├── Dev/            # 원천 투영·수용·유지 행동 회귀·패키징
├── data/           # 원천 보관·준비 결과·수용과 검증 영수증
├── assets/         # 보존한 주최자 원본과 공모전 참고 문서
├── Test/           # 평가 API·모델 대역·관측·비교·로컬 뷰어
└── Tmp/            # 실행별 증빙·독립 ZIP·격리 검증
```

루트는 Docker·공통 문서·범위 조정, submission은 실행 코드, data는 자료와 수용 신원을 소유한다. 규칙→구현→검증 매핑은 [규칙 색인](Dev/architecture/WORKFLOW_RULES.md)에서 확인한다. 준비 코드와 테스트는 제출 ZIP에 들어가지 않는다.

## 설정과 프로젝트 컨테이너

호스트에 프로젝트 의존성을 설치하지 않는다. 선언된 root Compose의 `dev`가 Python 개발·검증 환경이다. 기존 이미지가 준비된 오프라인 행동 회귀는 다음과 같다.

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T dev python -B -m unittest discover -s Dev/tests/workflow -p 'test_*.py'
```

루트 `.env`는 로컬 개발 키·서버 주소를 위한 파일이며 제출에 넣지 않는다. [submission/.env](submission/.env)는 공개 실행 설정이다. 경로는 제출 내부에 제한하고 같은 이름의 환경변수가 우선한다.

```dotenv
ONTOWARD_KNOWLEDGE_MANIFEST=knowledge/manifest.json
ONTOWARD_PARSER_PROMPT=config/input_parser.txt
ONTOWARD_NORMALIZATION_PROMPT=config/normalization.txt
ONTOWARD_BRAIN_PROMPT=config/brain.txt
ONTOWARD_EMPATHY_PROMPT=config/empathy.txt
ONTOWARD_EDUCATION_PROMPT=config/education.txt
ONTOWARD_EDUCATION_DOCTOR_PROMPT=config/education_doctor.txt
ONTOWARD_TEXTS=config/texts.ko.json
ONTOWARD_EDUCATION_ENABLED=true
```

원천 준비는 `Dev/ontology`와 별도 `ontology-extraction` 서비스에서 담당한다. 기존 준비 DB·전용 인증 volume·원천 파일을 유지한다. 이번 알고리즘 개편은 원천 다운로드·코퍼스 확장·중단한 모델 작업 재개·배포를 포함하지 않는다.

## Test와 확인 도구

[Test 안내](Test/README.md)는 SDK HTTP API·예선 자원 제약을 재현하는 로컬 실행기와 증빙을 설명한다. `sh Test/run.sh verify`는 외부 모델 없는 API·웹 경계 검사다. `scripted`와 Brain 응답 대역의 완료는 프로토콜·흐름 검증이며 실제 자연어 해석·임상 정확도의 증거가 아니다. `nova` 실행은 별도 외부 호출과 크레딧을 사용하므로 실제 수행 기록과 구분한다.

웹 실행기는 `sh Test/web.sh`로 시작하고 localhost에서 실제 대화·객체 호출·상태·고정 Assessment·최종 SOAP를 읽는다. 새 실행은 UI의 명시적 실행 선택으로 시작한다. 관측은 Test가 실제 메서드·LangGraph·SDK를 감싸며 제출 코드에 audit를 주입하지 않는다. 관측 실패가 환자 행동을 반복시키지 않는다.

읽기 전용 [지식 뷰어](Test/README.md#knowledge-viewer)는 `sh Test/knowledge.sh start`로 시작한다. 그래프의 실제 이름·조건·연결·원천 행과 두 준비 SQLite를 확인한다. 모델·인터넷 없이 기존 프로젝트 이미지를 사용한다. [정적 프로젝트 지도](Test/atlas.html)는 D40 시점의 보존된 설명이며 현재 알고리즘은 워크플로우 백서를 따른다.

## 제출 ZIP과 현재 증거

```sh
docker compose build package
docker compose run --rm -T package
```

결과는 `Tmp/packaging/ontoward-submission.zip`이다. `submission/` 자체를 한 단계 감싸지 않고 필요한 내부 파일을 압축 루트에 배치한다. package 서비스는 submission을 읽기 전용으로 연결하고 전용 출력만 쓰며 네트워크를 끈다. 심볼릭 링크·허용하지 않은 파일은 거절한다. 공개 `.env`는 포함하고 안내·운영 상태·테스트·원본 문서·준비 DB·캐시·개발 키는 제외한다.

D47 검증은 소스 행동 회귀, 실제 수용 RDF 대표 상담, Test 관측 유무 비교, 독립 ZIP의 네트워크 차단 실행, 원본 SDK의 프로젝트 내부 HTTP 완료로 나누어 기록한다. 최종 ZIP과 각 결과의 경로·해시는 [D47 영수증](data/provenance/algorithm-d47-2026-10-19.json)에 있다. 실제 Luna 응답 품질·독립 임상 정확도·공식 NOVA 세션·업로드·검증·점수는 별도 `not_run`이다.

## 원천과 이전 산출물 보존

공급된 RF2·BODHI·주최자 자료는 원본을 보존하고 준비·수용 경계를 거쳐 필요한 실행 자산만 배치한다. Git에는 실행 자산·코드·공개 설정·간결한 영수증을, 로컬에는 대용량 원본·준비 DB·요청 대장·보관본을 유지한다. 이전 정리·게시 결과는 [저장 정리 영수증](data/provenance/storage-cleanup-2026-10-16.json)과 [게시 영수증](data/provenance/github-publication-2026-10-16.json)에 기록된 당시 증거다. 이번 작업의 실행 여부는 최신 운영 상태와 D47 영수증을 따른다.
