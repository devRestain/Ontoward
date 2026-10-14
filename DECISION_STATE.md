# Ontoward 사용자 결정 상태

이 문서는 사용자 선택이 필요한 항목의 단일 원본이다. 권장안은 아직 선택된 값이 아니다. 사용자의 명시적인 선택을 받은 뒤 해당 항목의 상태와 선택 결과를 갱신한다. 채택한 기술은 [PRD](PRD.md)에 정리되어 있으며 여기서 다시 미결로 다루지 않는다.

운영 상태 문서는 결정 ID를 참조한다. 선택지·장단점·선택 결과를 하위 상태 문서에 복사하지 않는다. 접속 정보나 자료 위치가 필요할 때는 비밀 값을 문서에 적지 않고, 필요한 정보의 종류와 확보 여부만 기록한다.

2026-10-14 개정 D11이 현재 실행 흐름과 구현 범위를 정합니다. 최신 명시적 사용자 결정은 이전 운영 상태의 계획·다음 목표보다 우선합니다. D12의 SDK 전송·제출 구성, D13의 책임 분리, D14의 제출 내부 자산 경계는 최신 D11과 문구 분리 요청에 맞춰 적용합니다. 구현·검증 사실은 해당 운영 상태의 관측 증거로만 판단합니다.

2026-10-14 공식 사이트 재확인과 사용자의 명시적 확인에 따라 현재 예선 Doctor 선택은 `openai/gpt-6-luna`입니다. 10월 13일 시행된 모델·운영 변경은 D01·D12에 반영하며 별도의 미결 선택으로 만들지 않습니다. [현재 규칙 업데이트](assets/nova-competition-2026/CHANGES_2026-10-14.md)를 참조합니다.

<a id="D01"></a>
## D01. 첫 LLM 연결

- **상태:** 결정 완료.
- **결정할 질문:** 첫 대화 흐름에서 사용할 LLM을 어떤 경로로 연결할까요?
- **선택지 A — 대회 제공 개발 API**
  - 장점: 예선 지정 `openai/gpt-6-luna`를 SDK의 `client.chat()`으로 사용하여 실제 대회 경로에 맞출 수 있습니다.
  - 단점: 개인 개발 키·팀 크레딧·샘플 서비스가 필요하며 네트워크 실행 조건을 별도로 확인해야 합니다.
- **선택지 B — 프로젝트의 로컬 추론 컨테이너**
  - 장점: 개발 키트용 모델과 로컬 실행을 직접 관리할 수 있습니다.
  - 단점: 모델 파일 확보, 사용할 자원 확인, 별도 추론 환경 준비가 필요하여 첫 흐름까지 작업량이 늘어납니다. 공식 예선의 지정 Doctor를 대체하는 선택지는 아닙니다.
- **권장안:** 공식 샘플 API로 첫 흐름을 확인합니다.
- **사용자 선택:** A — 공식 샘플 API를 첫 연결 경로로 선택했습니다(2026-10-11). 2026-10-14 사용자가 Doctor 변경을 확인하고 선택 갱신을 요청하여 지정 모델을 `openai/gpt-6-luna`로 갱신합니다. 공식 시행일은 2026-10-13입니다.
- **역할 선택:** 2026-10-14 승인 개정에서 Doctor의 SAY 표현과 Gateway 구조화에 동일한 공식 Luna 모델을 사용하고 별도 Sol 실행 경로는 만들지 않습니다. 역할별 프롬프트·호출 기록을 분리합니다.
- **현재 모델 계약:** model을 생략한 `client.chat()`은 현재 지정 Doctor로 연결됩니다. reasoning_effort는 low·medium·high이며 temperature는 무시됩니다. 추론을 포함한 max_tokens와 실제 파싱 품질은 별도 실행 증거로 확인합니다. [변경 공지](https://nova.snubhai.org/qna/), [현재 모델 규칙](https://nova.snubhai.org/rules/)
- **선택 근거:** 예선 Doctor는 지정 모델이며 증례마다 최소 1회 호출해야 합니다. 본선의 직접 로드 모델은 별도 후속 범위입니다.
- **준비에 필요한 정보:** 개인 개발 키의 안전한 주입, 팀 크레딧·공개 샘플 UUID·서비스 가용성. 이번 작업에서는 접속 준비나 호출을 확인하지 않았습니다.
- **영향을 받는 담당 범위:** `submission/`의 모델 연결. 루트는 선택한 연결과 프로젝트 실행의 조정만 담당합니다.

<a id="D02"></a>
## D02. SNOMED 판본과 확보 경로

- **상태:** 결정 완료.
- **사용자 선택:** 임상 개념·계층·관계 원천은 SNOMED CT International Edition으로 고정합니다. 허가받아 보유한 RF2 Snapshot을 `assets/snomed/`에 수동 배치하고, 다운로드 기능은 사용하지 않습니다. 사용 가능한 실제 판본과 날짜는 RF2 파일·릴리스 문서·Module Dependency Refset에서 확인하여 기록하며 특정 월 판본을 코드 상수로 가정하지 않습니다.
- **언어 경계:** 최초 레지스트리는 영어 명칭과 동의어를 사용합니다. 한국어 Edition은 현재 파이프라인의 구조적 입력으로 요구하지 않습니다. 필요가 확인되면 InputInterpreter의 한국어 원문 연결과 Doctor의 자연어 표현 경계에만 추가 여부를 결정합니다.
- **근거:** 사용자는 SNOMED CT 데이터베이스 사용 허가를 받았으며 준비 경로를 SNOMED 직접 추출로 변경했습니다. 의미 있는 관계·계층 원천이 International Edition에 있으므로, 한국어 환자 입력 자체를 이유로 Korean Edition을 함께 적재하지 않습니다.
- **영향을 받는 담당 범위:** `assets/snomed/`의 허가된 입력, `data/preparation/snomed/`의 판본·해시·파생 준비 기록, `Dev/ontology/snomed/`의 RF2 조회·변환 코드입니다.

<a id="D03"></a>
## D03. 첫 모의환자 입력 방식

- **상태:** 결정 완료.
- **결정할 질문:** 첫 증례에서 환자 답변과 진찰·검사 결과를 어떻게 입력할까요?
- **선택지 A — 수동 CLI**
  - 장점: 사용자가 환자 답변과 실제 제공할 소견을 입력하여 작은 흐름부터 확인할 수 있고, 각 판단을 따라가기 쉽습니다.
  - 단점: 증례 진행에 사람이 참여해야 하며, 일관된 환자 정보와 결과를 준비해야 합니다.
- **선택지 B — 공식 샘플 API·SDK**
  - 장점: 공식 세션에서 환자 응답·진찰 소견을 얻고 같은 제출 인터페이스를 사용할 수 있습니다.
  - 단점: 개발 키·샘플 UUID·외부 실행 준비가 필요합니다.
- **선택지 C — 제공 로컬 개발 키트**
  - 장점: 공개 증례로 자동 흐름과 기록을 반복 검토할 수 있습니다.
  - 단점: 프로젝트 소유 모델 컨테이너 준비가 필요하고 서버 판정·채점·실행 제한을 모두 재현하지 않습니다.
- **권장안:** 공식 샘플 API·SDK로 첫 흐름을 확인합니다.
- **사용자 선택:** B — 공식 샘플 API를 첫 개발 경로로 선택했습니다(2026-10-11).
- **선택 근거:** 입력·행동·제출을 대회 인터페이스에 맞춥니다. 개발 키트는 후속 디버깅 수단이며 수동 CLI를 먼저 구현하지 않습니다.
- **준비에 필요한 정보:** 실제 샘플 세션의 초기 정보·활력징후·남은 턴·마감 시각과 API 응답. 로컬 C01·C03·C10 이름을 서버 UUID로 대신하지 않습니다.
- **영향을 받는 담당 범위:** `submission/`의 입력·출력과 행동 응답 연결.

<a id="D04"></a>
## D04. 첫 환자 입력 언어

- **상태:** 공식 경로에 대해 확정.
- **적용 범위:** D01·D03의 공식 샘플과 D06의 예선 경로에서 한국어 환자 입력·대화·제출 기록을 처리합니다. 영어와 한국어를 고르는 별도 수동 입력 환경은 첫 구현 대상에서 제외합니다.
- **기존 선택지 A — 영어로 시작하는 별도 입력 환경**
  - 장점: SNOMED·BODHI의 영어 표현을 검색에 바로 활용하기 쉬워 처음 확인할 흐름을 좁힐 수 있습니다.
  - 단점: 한국어로 환자 답변을 작성하려는 사용자에게 입력 부담이 생깁니다.
- **기존 선택지 B — 한국어**
  - 장점: 사용자가 이해하고 입력하기 편하며, 한국어 환자 표현의 실제 사용 흐름을 처음부터 확인할 수 있습니다.
  - 단점: 한국어 표현을 임상 용어에 연결하는 처리가 추가되고, 번역이나 표현 해석의 모호함을 다루어야 합니다.
- **확정 근거:** 한국어 공식 증례 경로를 선택하고 그에 맞춘 문서 개정 계획을 승인했습니다(2026-10-11). 언어를 별도로 선택한 것으로 기록하지 않고 공식 경로 채택에 따른 적용 범위를 명시합니다.
- **검색 표현:** 영어 지침과 후속 SNOMED·BODHI 검색은 사용할 수 있으나 한국어 응답 원문을 보존하고 번역·개념 연결의 불확실성을 구분합니다. 공개 샘플의 시작 정보는 `assets/nova-samples-2026/`에 있습니다.
- **영향을 받는 담당 범위:** `submission/`의 관찰 추출·개념 연결과 `data/`의 검색 표현 자료.

<a id="D05"></a>
## D05. 첫 지식 연결 순서

- **상태:** 결정 완료.
- **사용자 선택:** 온톨로지 준비의 기본 경로를 SNOMED CT 직접 추출로 전환합니다. 기존 510개 승인 어휘를 시드로 사용하되 고정 상한으로 삼지 않으며, 먼저 일곱 객체의 영어 용어 registry를 확장하고 사람 검토로 고정한 뒤 그 registry를 이용해 SNOMED 표현을 Disease–ClinicalPattern–ClinicalFeature 구조로 변환합니다.
- **선택 근거:** 가이드라인 전체에서 개념·관계를 추출하는 방식은 시간·토큰 대비 생성량이 낮았고, SNOMED CT 사용 허가를 받아 직접 관계·계층 변환이 가능해졌습니다.
- **관계 경계:** Pattern 후보는 `due to`, `associated with`, 그리고 Disease·Target 계층 교집합이라는 실제 RF2 근거만으로 Python이 찾습니다. 모델은 입력된 원천 ID·명칭·관계와 승인 registry 안에서만 개념·Feature를 대응합니다. SNOMED에 없는 질환 연관·전형적 증상·수치 조건을 생성하지 않습니다.
- **보존:** 기존 가이드라인 승인 기록, 원응답, 검토·준비 결과는 보존하며 자동 재개하지 않습니다. 가이드라인 추출은 기본 경로에서 제외합니다. 이후 사용자가 별도로 범위를 정한 보완 작업은 새로운 선택으로 다룹니다.
- **영향을 받는 담당 범위:** D09의 `Dev/`는 RF2 적재·용어 확장·구조 변환·검증·preview를, `data/`는 릴리스·출처·모델 응답·검토와 준비 결과를, `submission/`는 기존 v4.2 스키마의 preview 검증과 별도 런타임 admission 경계를 맡습니다. Korean Edition은 D02의 경계에 따릅니다.

<a id="D06"></a>
## D06. 첫 MVP의 대회 단계

- **상태:** 결정 완료.
- **결정할 질문:** 예선과 본선 중 어느 단계를 첫 구현 대상으로 둘까요?
- **선택지 A — 예선 우선**
  - 장점: 지정 Doctor API·SAY·EXAM·SOAP 제출 경로에 집중할 수 있습니다.
  - 단점: 본선 TEST·모델 로드·GPU 실행 준비는 별도 후속 작업으로 남습니다.
- **선택지 B — 예선·본선 동시 준비**
  - 장점: 두 단계의 모델·행동 경계를 함께 구현할 수 있습니다.
  - 단점: 모델 자산·자원·실행 환경 준비로 첫 수용 단위가 커집니다.
- **권장안:** A.
- **사용자 선택:** A — 예선을 첫 MVP 대상으로 선택했습니다(2026-10-11).
- **적용 결과:** 예선 TEST는 차단하고 향후 검사 계획은 `P.tests`에 작성합니다. 본선 모델·검사·발표 자료는 PRD의 후속 요구사항으로 보존합니다.
- **영향을 받는 담당 범위:** 루트의 요구사항·범위 조정과 `submission/`의 단계별 세션·행동 계약.

<a id="D07"></a>
## D07. 임상 지식 표현·검색·산출물 구조

- **상태:** 결정 완료.
- **사용자 선택:** RDFLib와 Turtle을 채택하고, 제출 전에 준비한 임상 그래프만 진료 중 조회하는 구조를 선택했습니다. 문서별 추출 결과와 출처별 제출 묶음을 구분하는 개정 계획을 승인했습니다(2026-10-11).
- **선택 근거:** 16개 출처 그룹의 임상 Markdown 15,904개, 약 597.2 MB를 단일 추출 파일로만 관리하면 실패 재개·검토·수정 범위를 추적하기 어렵습니다. 문서별 결과를 유지하고 제출에서는 출처별로 묶으면 준비 이력과 제출 파일 수를 함께 관리할 수 있습니다. 파일 분할 자체가 실행 메모리를 줄인다고 판단하지 않습니다.
- **준비 구조:** 문서별 `data/extracted/<source>/<document>.ttl`과 root data/knowledge의 묶음·준비 기록은 개발용으로 보관합니다. D14에 따라 실제 실행 지식은 submission/knowledge/의 Turtle·필요한 JSON·내부 manifest로 구성합니다. 추가 분할은 실제 규모 측정 이후 별도 작업에서 판단합니다.
- **실행 구조:** 후속 `prepare()`에서 manifest에 명시할 D08 스키마·기초 어휘와 출처별 임상 묶음을 하나의 RDFLib `Graph`에 로드하고 진료 중 읽기 전용으로 조회합니다. 원본 경로 목록과 외부 준비·검토 기록은 이 Graph에 로드하지 않습니다. 원문 검색·추출, 임의 SPARQL 생성, 선택적·지연 로딩, Dataset·Named Graph와 OWL 추론은 첫 MVP에 도입하지 않습니다.
- **지식·환자 경계:** 공통 URI와 임상 패턴은 D08을 따릅니다. 관계별 원본 경로·절·적용 조건·검토 기록은 data의 외부 준비 자료에 유지하며 실행 그래프에는 provenance 노드를 넣지 않습니다. 원본은 assets/guidelines/에 보존하고 data/catalog/guideline_paths.txt에는 경로만 둡니다. 환자 관찰은 `CaseState`에 유지하고, 관계 부재와 특징 표시를 음성 소견·질환 배제·보정된 확률로 바꾸지 않습니다. Test는 현재 진단 추론에서 제외하고 `P.tests` 계획 조회에만 사용합니다.
- **준비에 필요한 정보:** 기존 문서별 추출·검토·제출 조건, SNOMED 릴리스·잔여 호출량, 대표 자료의 triple 수·Turtle 크기·로딩 시간·최대 메모리·조회 시간. 준비 모델·실행 경로는 D09를 따르며 기본 스키마·기초 어휘는 D08의 작성 범위입니다. D07 문서 개정 당시 임상 추출·RDFLib 설치·실행은 수행하지 않았으며, 개발 산출물과 제출 묶음 수용을 구분합니다.
- **영향을 받는 담당 범위:** 루트의 PRD·안내·중앙 결정·제출 구조 조정, D09의 `Dev/` 준비 코드, `submission/`의 실행 조회 코드, `data/`의 provenance·검토·준비 결과·산출물. D08에서 기본 스키마·기초 어휘와 경로 목록 작성을 승인했습니다. D07 문서 개정 자체는 진단 코드·임상 추출·의존성 변경·Docker 인프라 변경·외부 호출·제출을 포함하지 않습니다.

<a id="D08"></a>
## D08. 기본 온톨로지 스키마와 기초 어휘

- **상태:** 결정 완료.
- **사용자 선택:** v4.2의 단일 Target ClinicalPattern 구조를 유지하고, 증상 검색의 출발점을 ChestPain·AbdominalPain·Headache·Dysuria 등 일반적인 임상 주호소 단위의 구체적인 Symptom으로 정합니다(2026-10-12). 사분면 등 세부 부위는 Location으로 표현하고 미특정 통증은 원문 미해결 상태로 유지합니다. 검토용 용어는 영어이며 한국어 환자 대화·표현 연결과 기존 ExamMethod·Test 사용처를 유지합니다.
- **결정 자료:** 첨부 「Ontoward Clinical Ontology — NOVA 공모전용 설계 컨텍스트」v4.2, 2026-10-12. SHA-256은 `1a44f193abb45f92bf49152c613fff8ff32119d731acafc9e71beda01e6219bc`입니다. 첨부의 미제공 참조 문서는 확인한 자료로 취급하지 않습니다.
- **구조:** 클래스 11개, 객체 관계 12개, 데이터 속성 6개를 사용합니다. 공통 URI는 urn:ontoward:이며 schema.ttl과 ontology/AGENTS.md가 정의와 제약을 제공합니다. `targets`는 ClinicalPattern이 소유하고 Feature는 부모의 Target을 따릅니다. RDFS domain/range는 검증기가 아니며 Symptom 또는 ExamFinding이라는 선택 관계를 복수 domain/range로 표현하지 않습니다.
- **증상 표현:** AbdominalPain·ChestPain·Headache·BackPain·NeckPain·SoreThroat·Toothache·EarPain·EyePain·JointPain·MusclePain·LimbPain·PelvicPain·FlankPain·AnalPain·Dysuria·Odynophagia·Dyspareunia·Dysmenorrhea를 구체적인 통증 Symptom으로 사용합니다. 세부 위치·좌우·양상·시간·유발·악화 요인은 기존 속성으로 보존하며 위치 계층이나 RightLowerQuadrantPain 같은 세분 노드는 추가하지 않습니다.
- **환자 표현 해석:** 환자 원문, 확인한 위치·상황, 정규화한 증상과 그 불확실성을 같은 observation·episode의 출처와 함께 보존합니다. 해석은 문진·진찰 근거로 갱신하고 정정 전 원문을 보존합니다. 진단 후보에 맞춰 증상을 바꾸지 않으며 미특정 통증을 구체적인 증상으로 강제 연결하지 않습니다. 근거가 있는 복수의 미확정 해석은 후보 검색 합집합에 사용할 수 있지만 같은 관찰을 여러 확정 증상이나 독립 지지 근거로 중복 계산하지 않습니다.
- **승인된 자연어 어휘:** 사용자는 2026-10-12 [영어 어휘 목록](data/ontology/vocabulary-candidates.md)의 일곱 객체 510개 항목을 승인하고 후속 작업의 기준으로 사용하도록 선택했습니다. 구성은 Disease 100개·Symptom 100개·ExamFinding 60개·AttributeValue 100개·ContextFactor 60개·Test 40개·ExamMethod 50개이며 기존 명칭·순서와 구체적인 통증 증상 19개를 유지합니다. [승인 기록](data/ontology/vocabulary-approval.json)에 승인 당시 파일 SHA-256과 항목 수를 보존합니다. 설명은 한국어, 용어는 영어로 유지하며 이번 승인은 자연어 작업 기준의 확정이고 RDF 수용이나 임상 관계 승인과는 별도입니다.
- **추가 후보 경계:** AttributeValue 적용 속성과 ContextFactor의 기존 contextType 10개 분류는 검토 제안입니다. 실제 수치·단위·시점·병력의 대상은 환자 상태에 보존하고 수치 임계값을 추가하지 않습니다. Test는 P.tests에 유지하며 새 ExamMethod의 한국어 요청문과 detectedBy 관계는 검토 이후 별도 작업으로 준비합니다. 추가 후보를 준비하면서 기존 Turtle·위치 값·examRequestText는 변경하지 않습니다.
- **기초 어휘 경계:** vocabulary.ttl의 구체적인 통증 증상 19개와 각각의 기존 속성 13개 연결을 유지합니다. 승인된 목록에 새 통증 개념의 BodySystem 값이 지정되어 있지 않으므로 해당 분류는 후속 어휘 수용 계약에서 정하며 임의 배정하지 않습니다. 일반 Pain 노드와 Urination 값은 두지 않습니다. 기존 계통 15개·평면 위치 45개·진찰 방법 24개·contextType 10개 문자열 분류는 유지하고, 승인된 나머지 항목의 Turtle 반영은 별도 수용 작업으로 진행합니다.
- **패턴·특징 제약:** Pattern은 질환 하나와 정확히 하나의 Symptom 또는 ExamFinding Target을 가지며 Feature는 0개 이상입니다. Feature는 Pattern 하나에 귀속하고 직접 targets를 갖지 않습니다. 속성·기대 값은 유효한 쌍으로 검증하며 상태만 표현하는 조건도 허용합니다. expectedStatus는 필요한 경우 present/absent 하나를 기록하고, clinicalRole은 검토된 supportive/characteristic/opposing 중 하나를 선택적으로 기록합니다. 아무 조건도 없는 Feature는 만들지 않습니다. 부분 매칭을 허용하고 수치 임계값·자동 범주 변환은 추가하지 않습니다.
- **수동 중요도:** Pattern의 선택적 `importance="characteristic"`와 Feature의 선택적 `clinicalRole="characteristic"`를 독립적으로 사람이 검토합니다. 미지정은 낮은 중요도가 아니며 expectedStatus=absent와 clinicalRole=opposing을 구분합니다. 문헌 언급 횟수나 자동 판정으로 중요도를 만들지 않습니다.
- **검색·선택도:** 질환 검색은 구체적인 Symptom 또는 ExamFinding에서 hasPattern→targets를 역방향 조회하며 presentsAs를 필수 경로로 사용하지 않습니다. 같은 질환은 문헌이 각각 뒷받침하는 여러 Target의 대안 Pattern을 가질 수 있고 모든 Pattern의 동시 일치를 요구하지 않습니다. StableAngina_ChestPainPattern과 StableAngina_AbdominalPainPattern은 구조 예시이며 이번에 임상 관계로 생성하지 않습니다. BodySystem으로 질환 후보를 제한하지 않으며 부분 매칭·질환 수준 집계·중복 근거 제거를 유지합니다. 선택도 계산은 후속 기능으로 남깁니다.
- **진찰 매핑:** ExamMethod URI를 내부 식별자로, examRequestText를 언어 태그 없는 실제 요청 문자열로 사용합니다. 후속 앱은 detectedBy 경로를 조회하여 단일 동작·NFC 1–30 코드 포인트를 검증한 뒤 client.exam(text)로 실행합니다. examAction 코드를 선언하지 않으며 서버 인식·실제 결과는 실행 전까지 미확인입니다.
- **TEST 경계:** Disease evaluatedBy Test는 SOAP P.tests 전용입니다. 현재 질환 후보 생성·특징 매칭·순위·다음 진단 행동에서 사용하지 않습니다. 예선 TEST 행동은 차단하고 O.tests는 비웁니다.
- **SOAP 주진단·근거:** D12에 따라 주진단을 CaseState.diagnosis와 별도 diagnosis 인자로 관리하고 note.A에는 evidence·differential만 둡니다. A.evidence는 실제로 얻고 주진단 판단에 사용한 문진·신체진찰 소견의 목록이며 지식 source나 내부 사고 과정으로 대신하지 않습니다.
- **제출 형식 확인:** 보존 SDK 1.0.1의 RECORD_FIELDS와 현재 공식 안내 표·제출 예제는 15개 SOAP 필드와 별도 diagnosis를 사용합니다. 사용자는 D12에서 이 전송 형식을 선택했습니다. SDK를 수정하지 않으며 서버 수락·제출은 not_run입니다.
- **출처 경계:** 원본은 assets/guidelines/에 유지하고 data/catalog/guideline_paths.txt에는 카탈로그의 프로젝트 루트 기준 원본 경로만 기록합니다. 관계별 원본 경로·절·적용 조건·라이선스·검토 결과는 외부 준비 자료에서 보존하며 경로 목록만으로 출처 검토나 제출 승인을 주장하지 않습니다.
- **승인 범위:** 이번 구체적 증상 개정은 schema.ttl의 설명, vocabulary.ttl의 선택한 통증 개념과 기존 속성 연결, 영어 검토 목록, 관련 계약·PRD·결정·세 운영 상태를 대상으로 합니다. 클래스·관계·속성 집합과 변경 범위 밖의 기존 어휘·원본 경로 목록은 유지합니다. 임상 Pattern 생성·환자 정규화 코드·Pydantic 추출 스키마·모델 호출·파일럿 실행은 후속 과제로 남기며 SDK 실행·의존성 변경·다운로드·인프라 변경·제출을 포함하지 않습니다.
- **영향을 받는 담당 범위:** 루트는 요구사항·중앙 결정을, data는 스키마·기초 어휘·원본 경로·준비 기록을, app는 후속 소비·매칭·SDK 계약을 소유합니다.

<a id="D09"></a>
## D09. SNOMED CT 어휘 확장과 Ontoward 데이터 변환

- **상태:** 결정 완료.
- **사용자 선택:** 2026-10-14 허가받은 SNOMED CT 데이터베이스 기반 직접 추출로 기본 경로를 전환합니다. 먼저 기존 승인 510개 영어 용어를 시드로 삼아 일곱 객체 유형의 registry를 확장하고, registry를 사람 검토로 고정한 다음 Ontoward v4.2의 Disease → ClinicalPattern → ClinicalFeature 구조로 투영합니다. 510개는 상한이 아닙니다.
- **원천·판본:** 임상 관계·계층은 International Edition RF2 Snapshot만 사용합니다. 원본은 `assets/snomed/`에 수동 배치하고 수정·다운로드하지 않습니다. 실제 판본·릴리스 날짜·언어 refset·모듈 의존성·파일 해시는 RF2에서 확인해 `data/preparation/snomed/`에 기록합니다. Korean Edition은 첫 구현에 포함하지 않습니다.
- **어휘 확장:** 영어 description 검색과 관계·계층을 우선 사용합니다. 유일한 정확 일치는 결정적으로 연결하고, 모호한 경우 로컬 SCTID 후보를 gpt-6.1-sol에 제시하며 모델이 새 SCTID를 쓰게 하지 않습니다. 새 concept는 검토 전 candidate이며 기존 URI는 보존하고 신규 URI는 검증된 SCTID에서 생성합니다. 복합 finding은 기본 Target과 명시적 qualifier로 분해합니다. 모든 registry entry는 사람이 선택하거나 제외합니다.
- **Pattern 후보:** Python은 `M is-a* T`와 `M due-to D`, `M associated-with D`, 또는 `M is-a* D` 및 `M is-a* T`의 세 경로를 사용합니다. 직접 관계 ID와 계층 경로를 보존하며 하위 질환 근거를 상위 질환의 직접 근거로 바꾸지 않습니다. `due_to`는 Pattern characteristic의 Ontoward 정책이고 RF2 `characteristicTypeId`와 무관합니다.
- **Feature 후보:** 원천 개념 M의 실제 관계와 명칭만 봅니다. 모델 입력은 RF2 Description·Relationship ID·정확한 용어·계층 경로와 고정 registry를 포함합니다. 모든 출력은 입력에 존재하는 증거를 참조하며 exact quote span을 검증합니다. 모든 packet을 accept·exclude·unresolved로 완결하고 전체 응답 검증 실패를 그대로 보존합니다.
- **Profile·표현:** 호환 Feature는 한 Disease–Target Pattern으로 병합하고 상충하는 조건 또는 명시적인 임상 profile은 결정론적 variant Pattern으로 나눕니다. 불명확한 묶음은 unresolved입니다. Pattern importance는 `due_to`에만 정책적으로 붙이고 Feature `clinicalRole`은 자동 설정하지 않습니다. 숫자·단위·연산자는 preparation evidence에 보존하며 범주형 RDF에 강제 변환하지 않습니다. 표현 불가능한 필수 조건은 전체 의존 Pattern을 제외합니다. 필요한 `detectedBy`와 검토된 요청문이 없으면 ExamFinding은 preview에서 제외합니다.
- **실행기:** `Dev/ontology/snomed/`의 Pydantic 모델·JSON Schema·CLI와 offline verifier를 사용합니다. NOVA 모델은 `openai/gpt-6.1-sol`, medium, 4,000 출력 토큰, 최대 5 packet/호출이며 `temperature`는 보내지 않습니다. dry-run이 기본이고 `--live`에는 개발 API 키, 명시적 실행 상한, KST 잔여 호출량 선언이 필요합니다. 두 단계는 하루 100회 팀 한도와 공유하는 보수적 로컬 호출 장부·캐시를 사용하고 자동 재시도·모델 전환·수정·재개를 하지 않습니다. 요청·입력은 전송 전에 기록하고 원응답은 검증 전에 저장합니다.
- **출력·수용:** SQLite·registry·packet·원응답·검토·preview 및 manifest는 `data/preparation/snomed/`에 보존합니다. preview를 `ClinicalKnowledge.validate_graph()`와 역방향 Target 조회로 검증할 수 있으나 제출용 지식 admission은 별도이며 자동 복사하지 않습니다. 이번 구현 완료 기준은 도구·실행기·dry-run·합성 RF2 offline verification입니다. 실제 RF2 커버리지·실제 API 호출·Sol 응답 품질·한국어 용어 필요성은 수행 또는 입증 전까지 미확인입니다.
- **기존 가이드라인 작업:** 과거의 선택·승인·응답·준비 산출물은 보존하되 새로운 기본 경로로 사용하거나 자동 재개하지 않습니다. 이후 필요한 보완은 별도 범위로 정합니다.
- **담당 범위:** 루트는 요구사항·Compose·Dev 실행기를, `assets/snomed/`는 허가된 원본을, `data/`는 릴리스·검토·준비 결과를, `submission/`은 기존 runtime reader와 별도 asset admission을 소유합니다.

<a id="D10"></a>
## D10. 독립 SNOMED 준비 이미지와 별도 실행 경계

- **상태:** 결정 완료.
- **사용자 선택:** 제출 에이전트 이미지와 분리된 `ontology-extraction` 이미지·컨테이너를 준비 전용으로 사용합니다. 기존 이미지·인증 volume은 보존합니다. 이번 SNOMED 경로의 실행 모델은 D09에 따릅니다.
- **현재 환경:** 컨테이너에는 Pydantic·RDFLib 및 표준 SQLite를 유지합니다. RF2는 `/workspace/assets/snomed`에서 읽기 전용, NOVA SDK 사본은 `/opt/ontoward-sdk/nova_sdk.py`에서 읽기 전용, preparation 결과는 `/workspace/data/preparation/snomed`에 기록합니다. NOVA 개발 키·API origin은 프로젝트 Compose 환경에서만 주입합니다. 이 변경은 실제 API 호출이나 인증 검증이 아닙니다.
- **환경 소유권:** 기존 Compose 프로젝트 `ontoward` 아래 별도 서비스 `ontology-extraction`, 이미지 `ontology-extraction:local`, 전용 네트워크와 `ontology-codex-state` volume을 둡니다. 기존 `dev` 서비스·루트 Dockerfile·에이전트 의존성은 분리하여 유지합니다.
- **입출력 경계:** `Dev/ontology/`, `assets/snomed/`, SDK 사본, `data/ontology/`, `submission/`은 읽기 전용입니다. `data/preparation/snomed/`와 `Tmp/snomed/`에만 준비 결과·임시 검증을 씁니다. 제출 자원 admission이나 호스트 패키지 설치는 하지 않습니다.
- **인증 경계:** SNOMED 추출은 SNU ChatGPT Codex CLI 인증을 사용하지 않습니다. 준비 API 키는 명시적인 `--live` 실행이 있을 때만 사용하고 세션 ID를 거부합니다. CLI·워크스페이스 pin 기록은 이전 문헌 작업의 환경 증거이며 새로운 SNOMED API 권한이나 성공 호출을 입증하지 않습니다.
- **WSL2 경계:** Compose 경로는 프로젝트 상대 경로로 유지하고 CPU 아키텍처를 Mac 값으로 고정하지 않습니다. 이후 대상 WSL2에서 같은 Dockerfile과 고정 의존성으로 다시 빌드하고 별도 로그인합니다. 현재 Windows 머신 접근·배포·자동 시작·연속 배치 운용은 수행하지 않습니다.
- **영향을 받는 담당 범위:** 루트는 독립 실행 환경과 Dev 도구 진행을, data는 준비 입력·추출·검토 결과를 소유합니다. app의 대회 실행·SDK 계약과 D07·D08의 지식 의미는 유지합니다.

<a id="D11"></a>
## D11. Doctor 인터페이스·집중 ROS·제출 복구 MVP (2026-10-14)

- **상태:** 결정 완료. 사용자가 이 대화의 개정 계획 전체 구현을 요청했습니다. 기존 5개 내부 세션과 Python 판단을 유지하며 아래 결정으로 실행 계약을 갱신합니다.
- **우선순위:** 최신 명시적 선택을 운영 상태의 이전 계획보다 우선합니다. 구현·실행·수용은 관측된 소유 범위의 증거로 기록합니다.
- **기반 자료:** 기존 ontoward-workflow-session-v2.md의 다섯 세션을 사용하고 이번 승인 계획이 우선합니다. Conceptual 노드·PatientAgent·별도 기억 저장소를 추가하지 않습니다.
- **모델:** 공식 평가 경로를 유지하여 Doctor와 Input Gateway 모두 `openai/gpt-6-luna`를 사용합니다. 세션 밖 개발용 Sol 경로를 추가하지 않습니다. 역할별 프롬프트와 호출·사용량 기록을 구분합니다.
- **책임:** Python이 질문·교육 선택, RDF 검색, 점수, 최종 진단과 SOAP를 담당합니다. InterviewPlanner가 준비 교육 선택을 소유하며 SubmissionWriter는 최종 답변 구성·검증·제출만 소유합니다. Doctor는 선택된 SAY의 질문·설명·교육 표현을 맡고 Gateway는 실제 응답 구조화를 맡습니다. EXAM은 준비된 단일 진찰 문구를 사용합니다.
- **시작:** 초기 정보·활력징후를 보존하고 첫 환자 행동은 반드시 인사·주호소 유도 SAY입니다. 준비 문구는 “안녕하세요. 무엇이 어떻게 불편하세요?”이며 확인한 세부 정보는 이후 HPI에서 반복하지 않습니다.
- **표현 검증:** 생성 → Python NFC 정규화 → 빈 내용·30자 검증 → 전송입니다. 공백·문장부호·줄바꿈을 포함한 코드 포인트 수를 사용합니다. 오류 종류·실제 길이를 주어 최대 두 번 재생성하고 이후 같은 검증을 통과한 준비 문구를 사용합니다. 준비 문구도 불가하면 미확인·미전달로 남기고 진행하며 임의 절단하지 않습니다.
- **원문 기억:** InteractionState가 실제 전달 한국어·환자 답·턴·요청 ID·질문 항목을 증례별 소유합니다. 두 역할에 전체 실제 대화 뷰를 제공하며 실패 생성·미전송·사용량·전송 오류를 분리합니다. 공유 PreparedResources나 모델 객체에 환자 기억을 쌓지 않습니다.
- **Gateway:** 현재 답, 실제 질문 문장, InterviewPlanner의 구조화된 질문 의도, 원문 대화, 기존 관찰과 허용 용어를 함께 해석합니다. 정확한 현재 인용과 유효한 context_refs를 남깁니다. Doctor 질문·교육을 환자 양성 소견으로 만들지 않습니다. Doctor 표현 질문의 짧은 예/아니오는 템플릿으로 자동 분류하지 않습니다. Python 단축 처리는 의미가 확정된 준비 질문과 모름·단순 교육 확인에 한정합니다.
- **흐름:** Initiation → ChiefComplaint → ContextFactor → DifferentialDiagnosis → Education → SOAP → DIAGNOSE → 제출 확인입니다. 별도 ClinicalSynthesis 호출은 없습니다.
- **집중 ROS:** HPI → 자유 Open Inquiry 1회 → 확인된 주호소 계통의 미확인 증상 최대 6개입니다. 기존 BodySystem/inSystem의 계통 합집합에서 주호소·기확인·중복을 제외하고 URI 순으로 선택합니다. HPI 준비 시 목록을 고정하고 실행 전 기확인 항목을 건너뜁니다. 새 계통을 연쇄 확장하지 않고 연결이 없으면 추정하지 않습니다. 20턴 내 Open 1턴과 가능한 ROS 6턴을 우선 확보하고 뒤쪽 HPI를 줄입니다. BodySystem은 질환 검색 필터가 아닙니다.
- **공통 루프:** scope 질문을 한 번 준비하고 대기 응답을 우선 처리합니다. 낮은 우선순위 unasked와 질문 참조를 함께 삭제하며 삭제 큐·자동 재개를 만들지 않습니다. 실제 사실·원문·전달·계획을 보존합니다. 명료화는 최대 2개의 별도 질문으로 제한합니다.
- **후보·점수:** 증상·진찰 Target의 Pattern 역조회 합집합이며 current 관찰로 매번 재계산합니다. characteristic +2, 일반 지지 +1, 명시 반대·모순 −1, 확인 Context 최대 +1, 그 외 0입니다. 같은 원관찰·조건의 중복 가산, 다른 에피소드 혼합, 불확실한 대안의 중복 확정을 금지하고 동률은 질환 URI 순입니다.
- **명료화와 진단:** 구조화 실패·주호소 불명확·후보 없음에 증례 전체 최대 2회 명료화·재검색을 허용합니다. 여전히 후보가 없으면 확인된 현재 주호소의 증상 수준 잠정진단을 별도로 표현하며 가짜 Disease 후보를 만들지 않습니다. 원인 미확정 안내만 사용하고 질환 전용 치료는 붙이지 않습니다. 근거 주호소도 없으면 명시적 실패입니다.
- **교육:** 준비된 내용만 선택하며 새 사실이 진단을 바꾸면 아직 전달하지 않은 부적합 설명만 남은 예산에서 교체합니다. 앞 세션으로 돌아가지 않으며 계획과 실제 전달을 구분합니다.
- **예산:** 행동 상한은 1/20/10/14/5, 최종 여유 120초입니다. 이전 파싱 전용 호출 예산을 두 역할·재생성 합산 증례별 200회·입력 500,000·출력 100,000토큰으로 교체합니다. 생성 전에 Gateway 한 호출·출력 여유를 확보하고 실제 사용량·서버 제한을 반영합니다. 같은 요청 재전송을 새 호출·턴으로 중복 계산하지 않습니다.
- **복구:** 전송 오류·REQUEST_PENDING은 ID·payload를 그대로 보존하여 2초·5초 후 최대 2회 재전송합니다. timeout은 최대 240초이되 남은 시간과 제출 여유를 넘지 않습니다. 명시적 환자·진찰 응답 형식 오류는 새 ID로 1회 재시도합니다. SDK 원본을 수정하지 않습니다. 진찰 거절은 소견으로 기록하지 않고 예산 부족은 확보 사실로 최종화합니다. SOAP 형식 오류는 한 번 재구성·재검증합니다.
- **종료:** 해당 DIAGNOSE의 completed만 정상 finish입니다. 만료·폐쇄·복구 소진 후 결과 불명·근거 없는 진단은 명시적 비정상 결과이며 무한 반복하지 않습니다.
- **설정·문서:** ONTOWARD_DOCTOR_PROMPT, ONTOWARD_PARSER_PROMPT, ONTOWARD_TEXTS는 config 내부의 별도 파일을 선택합니다. 백서는 submission/README.md에 실제 함수·상태·세 Mermaid 도식·실행 안내로 작성합니다. 렌더링을 못하면 미검증으로 표시합니다.
- **수용 범위:** 프로젝트 소유 dev 컨테이너의 합성 RDF·문구·SDK 대역으로 실행 코드와 전체 흐름을 검증합니다. 이전 증거를 보존하고 임시 제출 복사본을 사용합니다. PRD·관련 계약·D01/D12/D13/D14·세 운영 상태를 정합화합니다.
- **미검증:** 실제 임상 manifest·승인 묶음이 없으므로 production prepare를 빈 그래프로 우회하지 않습니다. 실제 Luna 품질·임상 승인·공식 API 제출·평가, 추출 재개·코퍼스 확대·커밋·배포는 이번 범위 밖입니다.

<a id="D12"></a>
## D12. 최신 공모전 컨텍스트와 submission 중심 구조

- **상태:** 결정 완료.
- **사용자 선택:** 2026-10-12 확인 자료와 두 PPTX를 반영하고 submission/을 제출 코드의 단일 원본으로 사용합니다. 최종 구현 요청에 따라 애플리케이션 안내·계약·상태도 submission/에 둡니다.
- **2026-10-14 규칙 갱신:** 사용자는 공식 사이트의 최신 내용과 기존 참고 자료를 대조하여 모든 프로젝트 상태를 갱신하도록 요청했습니다. D01의 `openai/gpt-6-luna` 선택을 적용하고 개발 세션 100/일·샘플 검증 10/일·세션 밖 Luna 성공 호출 1,000/일·Sol 100/일, 10월 13일 크레딧·횟수 복구와 공식 접수 개방, 본선 진출 10팀을 반영합니다. 공식 평가 1/일·증례별 예산·SDK SOAP·본선 최종 5팀 의사 평가의 기존 경계는 유지합니다. 실제 잔액·잔여 횟수와 공식 실행은 확인하지 않습니다.
- **전송 준비:** D11의 승인 개정에 따라 보존 SDK 밖 애플리케이션 경계에서 최대 240초 대기와 제출 여유, 동일 ID·payload 최대 2회 재전송, 명시적 응답 형식 오류 새 ID 1회 재시도를 구현합니다. SDK 다운로드·교체와 실제 공식 복구 검증은 별도입니다.
- **SOAP:** SDK 1.0.1의 15개 SOAP 문자열 필드와 별도 diagnosis를 채택합니다. D08·D11의 제출 경계를 이에 맞추고 A.evidence의 실제 소견 근거 원칙은 유지합니다.
- **SDK:** 원본은 보존하고 nova_sdk.py만 해시가 같은 수정 없는 실행 사본으로 포함합니다. 다른 제공 원본의 복제·수정은 허용하지 않습니다.
- **압축:** ZIP 루트에 run.py·requirements.txt와 필요한 Python을 배치하고 D13의 workflow/·knowledge/ 패키지 경로를 유지합니다. submission/AGENTS.md·README.md·PROJECT_STATE.md와 캐시, 이전 agents/ 경로는 제외합니다. Dev/packaging/package_submission.py가 이 규칙과 실제 크기·파일 수를 확인합니다.
- **환경설정:** 후속 사용자 정정에 따라 submission/.env는 ZIP에 반드시 포함하고 코드가 읽습니다. D14의 현재 값은 ONTOWARD_KNOWLEDGE_MANIFEST=knowledge/manifest.json이며 실행 환경값도 submission/knowledge 내부 경로여야 합니다. 개발 키 등 로컬 접속 정보는 root .env에 분리하고 제출하지 않습니다. root .env.example은 개발 설정의 추적 가능한 예시입니다.
- **Git:** 코드·계약·상태·PPTX 변환 Markdown·간결한 출처 및 검토 요약·승인 제출 자산을 추적합니다. 원본 대용량 자료, 임시 작업, 생성 추출 결과, 캐시와 개발 비밀값은 제외합니다. 공개 submission/.env는 명시적으로 추적합니다.
- **지식 경로:** 준비 원본과 승인 판단은 root data가 소유합니다. D14의 실제 runtime과 테스트는 submission/knowledge 내부 파일만 참조하며 없는 묶음이나 manifest를 외부 data 또는 빈 파일로 대신하지 않습니다.
- **검증 범위:** 큰 변경 단위를 모은 뒤 Docker의 휠 설치·import·그래프 구성, 실제 ZIP 구성, 문서 및 원본 보존을 함께 확인합니다. 임상 자산 수용과 공식 서버 실행은 D11의 합성 검증과 구분합니다.
- **범위 밖:** D11의 오프라인 MVP 구현을 허용하며 실제 모델 호출, 추출 재개, 자료 확대, 공식 제출·평가, 본선 모델과 다른 머신 배포는 제외합니다.

<a id="D13"></a>
## D13. 워크플로우 책임·규칙·네임스페이스 (2026-10-14 리팩토링)

- **상태:** 결정 완료. 사용자가 기존 동작을 보존하는 책임 중심 재구성, Doctor 명명, 단일 Consultation, 유지 테스트와 프로젝트 전체 상태 정합화를 선택하고 구현을 요청했습니다.
- **구조:** submission/workflow/에 실행 코드를 모으며 이전 agents/와 호환 wrapper는 제거합니다. run.py의 prepare()·consult(client, resources) SDK 계약을 유지합니다. knowledge/·config/·settings.py·SDK·공개 .env와 의존성 경로는 유지합니다.
- **조립:** workflow/runtime.py의 prepare()는 지식과 텍스트 설정만 담은 PreparedResources를 반환합니다. consult()는 증례별 실행 객체와 상태를 만듭니다. 객체에 필요한 의존성만 전달하고 변경 가능한 증례 상태를 보관하지 않습니다.
- **세션:** Consultation 하나가 Initiation·ChiefComplaint·ContextFactor·DifferentialDiagnosis·Education의 준비·진입·전환·입력 후 갱신·최종화 순서를 소유합니다. 세션별 클래스를 추가하지 않습니다. graph.py는 노드·엣지·순수 분기와 deep-copy/Pydantic 검증 경계를 소유합니다.
- **역할:** Doctor는 SAY 표현과 SAY/EXAM 실행, InputInterpreter는 입력 해석·검증·임상 사실 반영, InterviewPlanner는 질문·교육 계획 선택, ClinicalReasoner는 기존 검색·매칭·점수·진단, SubmissionWriter는 SOAP·제출 시도·수리·완료 확인을 소유합니다.
- **명명:** 클래스는 책임 명사, 함수와 그래프 노드는 동사와 대상으로 명명합니다. 내부 단계에는 session, 공식 서버에는 nova_session을 사용합니다. 기존 직렬화 scope와 상태 값, 모델 역할 doctor/gateway는 보존합니다.
- **상태 연산:** QuestionLifecycle은 placeholder·질문 참조 등록·폐기·미해결 마감, InteractionLifecycle은 selected/pending/incoming·대화·전달 기록, UsageAccounting은 사용량·명료화 횟수·서버 잔여량을 소유합니다. 폐기는 전체 대상의 pending/완료 충돌을 먼저 검사하며 없는 ID는 no-op입니다. 진료 사실·전달 교육을 폐기하지 않습니다.
- **상태 형태:** CaseState·SessionContext·DifferentialState·QuestionPlan·InteractionState와 WorkflowState의 필드·직렬화 형태를 유지합니다. initialized/questions_prepared, 처리 상태/임상 상태, 교육 계획/실제 전달을 구분합니다.
- **규칙:** workflow/rules에 불변 한도와 순수 예산·입력·행동·제출 판단을 모읍니다. 예산 정책은 상태를 수정하지 않습니다. 임상 알고리즘은 ClinicalReasoner에 보존하고 범용 규칙 엔진·BaseAgent·registry는 만들지 않습니다. Dev/architecture/WORKFLOW_RULES.md는 규칙·책임자·코드·검증·근거를 연결하는 색인입니다.
- **전송·복구:** workflow/io에 모델 호출·공식 세션 동기화·동일 요청 복구를 둡니다. 시간·sleep·ID를 주입해 검증합니다. D11의 예산·전송 전 재검사·네 복구 의미와 호출 순서를 유지합니다. SDK 정상 응답 확인에서 전달 사실을 기록하며 이후 해석 실패로 취소하지 않습니다. SubmissionWriter.begin_repair()가 제출 시도 초기화를 맡고 Consultation이 진단→계획→SOAP 재작성 순서를 유지합니다.
- **보존:** Knowledge·SDK·프롬프트·한국어 문구·설정·의존성 바이트와 외부 payload를 보존합니다. ClinicalReasoner는 클래스명·import·경로만 기계적으로 변경합니다. 기존 기능 차이를 리팩토링에 섞지 않습니다.
- **검증:** Dev/tests/workflow에 unittest 행동 검증을 유지하고 Tmp에 합성 자산·전후 trace·증거를 생성합니다. 원래 40개 사례와 추가 책임 경계, 전후 모델/SDK 요청·상태·SOAP·종료 동등성, 독립 ZIP 실행을 프로젝트 소유 컨테이너에서 검증합니다. UUID 동일성 관계를 보존하며 구조만 확인하는 테스트는 수용 기준으로 삼지 않습니다.
- **압축·문서:** D14 package 서비스가 workflow/·knowledge/·설정 문구와 공개 .env를 포함하고 이전 agents/·문서·상태·테스트·합성 자산을 제외합니다. PRD·관련 AGENTS·한국어 백서·중앙 결정과 세 운영 상태를 같은 작업에서 정합화합니다. 실제 구현·검증은 운영 상태의 관측 증거로만 기록합니다.
- **경계:** 준비 작업과 후보 검토·RDF/runtime 자산 승인 차단 사유를 보존합니다. 실제 모델·공식 API 제출·평가·코퍼스 확대·커밋·배포는 포함하지 않습니다.

<a id="D14"></a>
## D14. 제출 내부 지식과 독립 압축 경계

- **상태:** 결정 완료.
- **사용자 요청:** 모든 제출용 코드·설정·자료와 추후 테스트의 자산 입력을 submission 내부로 한정합니다. 외부 구조는 개발용이며 완성된 온톨로지 Turtle과 필요한 schema JSON은 submission/knowledge/에 둡니다(2026-10-12).
- **설정:** 공개 .env의 manifest 경로는 knowledge/manifest.json입니다. settings.py는 자기 파일 위치 기준으로 submission/knowledge 내부 경로만 허용하며 외부 data/로 폴백하지 않습니다. D11 로더는 없는 manifest를 명시적 오류로 보고하고 빈 자산으로 대체하지 않습니다. Doctor·Gateway 프롬프트와 문구 경로는 D11·D13에 따라 config 내부로 제한하며 지정 파일을 ZIP에 포함합니다.
- **지식 파일:** Python 그래프 접근 코드와 실제 실행 Turtle·필요한 JSON을 knowledge/에 함께 둡니다. JSON Schema는 필요 시 JSON 구조 검증용으로 사용하고 RDF triple 입력과 구분합니다. D11 구현의 manifest는 schema·vocabulary·하나 이상의 bundles와 선택적 questions·plans를 선언하며 각 파일의 submission 기준 상대 path와 SHA-256을 검증합니다.
- **압축 이미지:** root Dockerfile의 package target과 Compose package 서비스를 사용합니다. submission/만 /submission에 읽기 전용으로, 전용 결과 디렉터리 Tmp/packaging/만 /output에 연결합니다. 네트워크를 끄고 외부 Dev·data·assets와 root .env를 연결하지 않습니다. 압축 도구는 이미지에 포함되며 입력은 /submission으로 고정합니다.
- **결과:** ZIP 루트와 workflow/·knowledge/ 패키지 경로를 유지하고 .env와 지정 config 파일, 필요한 knowledge의 .ttl·.json을 포함합니다. 이전 agents/·문서·캐시·개발 파일·유지 테스트·합성 자산은 제외합니다. 실제 출력은 Tmp/packaging/ontoward-submission.zip입니다.
- **수용 범위:** 설정·경로·압축 입력 격리와 실제 ZIP 검증을 완료합니다. D11이 RDF 로더·조회 구현을 포함하며 임상 지식 완성과 공식 대회 호출·제출은 별도입니다.

## 결정 기록 방법

- 사용자가 고른 선택지를 해당 항목에 기록하고 상태를 `결정 완료`로 바꿉니다.
- 선택 이유와 새로 제공된 정보의 위치를 짧게 남깁니다.
- 필요한 접속 정보나 원본이 아직 없다면 선택 결과와 준비에 필요한 정보를 구분합니다.
- 공식 환경의 제약으로 선택 범위가 사라지면 그 근거와 적용 범위를 기록하고 별도 사용자 선택으로 꾸미지 않습니다.
- 영향을 받는 운영 상태는 이 문서의 결정 ID를 참조하여 다음 작업을 정합니다.
- 결정을 다시 열어야 한다면 같은 항목에 이유를 적고 사용자에게 선택을 요청합니다.
