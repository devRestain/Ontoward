# Ontoward 사용자 결정 상태

이 문서는 사용자 선택이 필요한 항목의 단일 원본이다. 권장안은 아직 선택된 값이 아니다. 사용자의 명시적인 선택을 받은 뒤 해당 항목의 상태와 선택 결과를 갱신한다. 채택한 기술은 [PRD](PRD.md)에 정리되어 있으며 여기서 다시 미결로 다루지 않는다.

운영 상태 문서는 결정 ID를 참조한다. 선택지·장단점·선택 결과를 하위 상태 문서에 복사하지 않는다. 접속 정보나 자료 위치가 필요할 때는 비밀 값을 문서에 적지 않고, 필요한 정보의 종류와 확보 여부만 기록한다.

D08/D09의 v5.0 개정과 D11의 실행 계약에 2026-10-15 D15의 배치 수용·정보 보존·어휘 제한·최소 질문을 적용합니다. 최신 명시적 사용자 결정은 이전 운영 상태의 계획·다음 목표보다 우선합니다. D12의 SDK 전송·제출 구성, D13의 책임 분리, D14의 제출 내부 자산 경계는 유지합니다. 구현·검증 사실은 해당 운영 상태의 관측 증거로만 판단합니다.

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
- **사용자 선택:** 공급된 International 2026-05-01 기반과 Korean 2026-06-15 확장을 함께 사용합니다. 실제 릴리스 메타데이터와 Module Dependency의 모듈·버전 조합으로 구성을 고정하며 자동 다운로드하지 않습니다.
- **결합 규칙:** Korean 모듈이 요구하는 core·foundation의 20260501을 공급된 기반과 대조합니다. 동일 SCTID의 최신 effectiveTime 행을 선택한 뒤 활성 여부를 적용하고 같은 날짜의 충돌·미래 행·누락된 의존성을 거부합니다.
- **명칭:** 영어 명칭과 Korean description을 같은 SCTID의 언어 표현으로 연결합니다. Korean 고유 개념은 확장 모듈과 날짜를 보존합니다. 식별자 존재 확인과 의미상 매핑 검토는 구분합니다.
- **소유 범위:** 원본은 assets/snomed/, 준비와 해시·매핑 기록은 data/preparation/v5/, 변환은 Dev/ontology/source_projection.py가 소유합니다.

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
## D05. 지식 구축의 기본 경로

- **상태:** 결정 완료.
- **사용자 선택:** 실제 SNOMED CT와 BODHI-S를 보존하면서 v5.0에 투영합니다. Disease → ClinicalPattern → ClinicalFeature, Pattern 기반 후보 검색, Feature 기반 점수 계산을 유지하고 공유 Pattern·질환별 Association·타입 값·자동 점수 정책을 채택합니다.
- **원천 역할:** SNOMED는 식별·명칭·계층·관계 구조를, BODHI는 변형 묶음과 두 방향 likelihood를 제공합니다. 기존 510개 승인 용어는 시드이며 표현 상한이 아닙니다.
- **현재 범위:** 2026-10-15 사용자가 전체 International Snapshot·Korean 확장·BODHI-S 수집, SQLite 준비 DB와 v5.0 RDF export, 명시적 배치 승인 후 지식 자산 통합을 선택했습니다. 기존 세 Target preview와 승인 영수증은 보존합니다.
- **모델 사용:** 결정론적 처리가 우선입니다. 원천에 명시된 의미의 미해결 정규화·역할 후보에만 NOVA_DEV_KEY의 세션 밖 openai/gpt-6.1-sol을 사용하며, 공유 KST 대장에서 실패·불명 요청도 포함해 일일 최대 100회로 제한합니다. 사용자가 확인한 100회 잔여 예산은 2026-10-15 KST에만 적용합니다.
- **수용:** 자동 preview와 후보 registry를 먼저 검증하고 사람의 매핑·임상 검토 및 제출 자산 수용은 별도로 진행합니다.
- **레거시:** 사용자가 삭제를 허용한 v4.2 SNOMED 및 가이드라인 Dev 파이프라인은 제거합니다. 원본·승인 영수증·유용한 준비 결과는 deprecated로 구분하여 보존하며 자동 재개하지 않습니다.

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
## D07. 지식 표현과 실행 산출물

- **상태:** 결정 완료.
- **사용자 선택:** 준비된 v5.0 Turtle과 공개 JSON 점수 정책을 하나의 RDFLib Graph와 Python 계산 구조로 사용합니다.
- **준비:** data/preparation/v5/의 SQLite에 전체 원천 행·위치·모듈·관계 그룹·UUID·원값·매핑·정규화·보류·승인 기록을 저장하고 RDF preview와 검토 자료를 생성합니다. 원천·스키마·정규화 해시가 같은 현재 빌드만 명시적으로 재개합니다. 기존 문헌 준비 기록은 deprecated evidence입니다.
- **실행:** submission/knowledge/의 manifest에 고정된 스키마·어휘·임상 묶음을 prepare()에서 전부 로드합니다. 선택된 표현·Association 적용 조건·라벨·관계 범위·최소 sourceRef만 실행 그래프에 유지하고 환자 관찰·진단 점수는 CaseState와 워크플로 상태에 둡니다.
- **경계:** 진료 중 RF2·원문 검색, 임의 SPARQL, OWL 추론, Named Graph나 별도 그래프 서버는 사용하지 않습니다. 준비 preview의 자동 복사와 runtime admission은 별개입니다.
- **버전:** schema_version, registry_version, normalization_version, source_snapshots 및 파일 해시, scoring_policy_version과 정책 파일 해시를 모두 고정합니다. 파일 분할은 메모리 절감의 증거가 아닙니다.

<a id="D08"></a>
## D08. 온톨로지 스키마 v5.0

- **상태:** 결정 완료. 사용자가 v5.0 계획 구현과 레거시 파이프라인 제거를 승인했습니다.
- **핵심 구조:** Disease —hasAssociation→ DiseasePatternAssociation —pattern→ ClinicalPattern —hasFeature→ ClinicalFeature입니다. 각 Pattern은 단일 Symptom 또는 ExamFinding Target과 비어 있지 않은 원자 조건을 가지며 여러 질환이 공유할 수 있습니다. Feature는 Pattern 하나에 귀속됩니다.
- **동일성:** Pattern은 Disease·출처와 독립적으로 Target, 조건, 연산, 단위, 부정·시간·AND/OR 및 수식 범위가 같을 때 공유합니다. Association은 Disease + Pattern + 적용 조건으로 식별하며 동일 연관의 원천 주장들은 준비 기록에 모두 보존합니다.
- **값:** ExpectedValue는 concept, concept_set(any_of/all_of), quantity(값·연산·단위), interval(경계·단위)을 구분합니다. 존재·부재는 expectedStatus입니다. TimeSinceOnset과 EpisodeDuration, Location과 RadiationLocation을 분리합니다. 월·년은 달력 단위이며 일수로 환산하지 않습니다.
- **원천 의미:** BODHI characteristic는 실제 수식 축으로 해석합니다. 다른 소견을 요구하는 변형은 linked_finding_deferred로 보류하며 이를 지우거나 일반 양상으로 바꿔 높은 점수를 활성화하지 않습니다. RF2 그룹 및 변형 조건을 합쳐 넓히지 않습니다.
- **점수 정책:** 공개 submission/knowledge/scoring_policy.json을 manifest에 고정합니다. condition_given_symptom의 zero/rare/low/medium/high/very_high는 0/0.5/1/2/3/4입니다. symptom_given_condition은 문진 정렬에 사용하고 strong_predictor는 보조 정보와 충돌 검토에만 사용합니다.
- **SNOMED 대체:** 동일 질환·완전한 표현·범위에 BODHI 라벨이 없을 때 정확한 due_to=2, associated_with=1, subtype-intersection 또는 조건을 보존한 일반화=0.5를 사용합니다. BODHI zero를 누락으로 취급하지 않습니다. 점수는 프로젝트 정렬 정책이며 확률이나 likelihood ratio가 아닙니다.
- **FeatureContribution:** 정교화 Association 점수 − 기준 Association 점수입니다. 한 조건 변경은 atomic, 여러 조건 변경은 joint로 유지합니다. 기준이 없는 세부 Pattern은 전체 점수를 사용하되 개별 기여는 미식별입니다. 음수 차분은 지지의 조정이며 자동 반대 근거가 아닙니다.
- **검색과 활성화:** Target에서 후보를 넓게 찾고 점수는 모든 Feature와 적용 조건이 일치할 때만 활성화합니다. 더 구체적인 일치 Pattern은 점수가 내려가도 조상을 대체합니다. 비교 불가능한 변형은 최대값 한 번, 같은 Disease–Target은 반복·에피소드·출처와 관계없이 한 번 집계합니다. 서로 다른 Target은 합산합니다.
- **관찰 경계:** 다른 에피소드를 합치지 않고 미질문·불확실·불일치 상세 조건에서 추가 점수나 자동 감점을 만들지 않습니다. 유병률·집단 보정·그래프 빈도·자동 부재 감점은 보류합니다. 기존 D11의 확인 Context 최대 +1은 유지하며 후보를 만들지 않습니다.
- **개념 비교:** 검증된 제한적 ValueMatch 경로만 사용합니다. is_a, regional_part, approved_region을 구분하고 근거를 보존하며 환자 관찰을 추가 생성하지 않습니다.
- **임상 역할:** Disorder 분류나 snomed_id라는 필드명만으로 Disease를 등록하지 않습니다. 병력·가족력·검사 소견은 실행 역할·획득 방식에 따라 제외·보류합니다. 구체적인 통증 주호소와 관찰 원문·불확실성·별도 에피소드를 유지합니다.
- **실행 계약:** get_patterns_by_target와 get_disease_patterns는 Association을 포함하고 get_pattern_features는 타입 조건을, get_feature_contributions는 조건부 차분을 반환합니다. 점수와 기여는 실수형으로 보존합니다.
- **보존과 수용:** 기존 510-term 승인 영수증은 유지합니다. v4.2 schema/vocabulary는 data/ontology/v4.2/에 보존하며 old extraction 인터페이스와 준비 결과는 deprecated.json으로 표시합니다. v5.0 reader가 v5.0 자산만 읽으며 의미를 삭제하는 v4.2 변환은 만들지 않습니다.
- **기존 실행 역할:** BodySystem은 문진 범위에만 사용합니다. ExamFinding은 detectedBy와 검토 요청문을 요구하고 Test/evaluatedBy는 SOAP P.tests 전용입니다. A.evidence는 실제 문진·진찰 소견이며 SDK의 15개 SOAP 필드와 별도 diagnosis를 유지합니다.

<a id="D09"></a>
## D09. 실제 원천의 v5.0 투영

- **상태:** 결정 완료.
- **구현 방향:** Dev/ontology/source_projection.py의 build/export/admit와 책임별 SQLite·정규화·승인 helper가 전체 원천 DB와 v5.0 실행 후보를 구성합니다. 제거된 구형 파이프라인과 호환 계층은 복원하지 않습니다.
- **전체 입력:** International 20260501과 Korean 20260615의 모든 Snapshot TXT·release metadata, BODHI-S 8개 CSV와 보존 라이선스·원천 설명입니다. Full 과거 이력, 다운로드와 원본 수정은 제외합니다. 모든 입력 행의 수집·투영·제외·보류·미투영 결과를 기록합니다.
- **표현:** 원천 변형 경계를 유지합니다. UUID와 자체 SCTID·루트 SCTID를 분리하고 단위·기간·양상·위치·방사를 D08 타입으로 보존합니다. 승인되지 않은 연결이나 필수 조건의 의미를 생성하지 않습니다.
- **SNOMED 경로:** 실제 due_to, associated_with, subtype-intersection 경로만 사용하며 직접 관계 ID, 계층 경로, 원천 개념과 그룹·모듈·버전을 보존합니다. 표현 불가능한 필수 관계가 있으면 해당 전체 변형은 unresolved입니다.
- **분류:** 확인된 활성 disorder와 BODHI 실행 역할을 함께 확인합니다. 원천 ID 미확인·비활성·과거력·가족력·검사 소견·지원하지 않는 동반 소견은 지정된 제외/보류 사유와 원값을 남깁니다.
- **자동 계산:** BODHI 두 방향 라벨을 분리하고 동일 Association의 여러 출처는 주장별 보존 후 평가를 선택합니다. 충돌은 검토 목록에 두고 조건부 atomic/joint 차분을 준비합니다.
- **산출물:** data/preparation/v5/에 ontology.sqlite3, schema·vocabulary·clinical Turtle, 정책·manifest·registry·sources·report·feature-contributions, 전체 Target 역할과 배치 검토 자료를 보존합니다. 승인 전 registry는 candidate이고 RDF는 preview_only입니다.
- **검증:** 유지 중인 Dev/tests/workflow의 Docker 전체 흐름과 Dev/tests/ontology/verify_v5.py의 실제 원천 검증을 사용합니다. 가중치 2→1→4, 공유 표현·질환별 점수, 에피소드·출처 중복, 타입 기간, 적용 조건 미확인 및 보류 결과를 확인합니다.
- **권한과 수용:** 사용자가 선택한 배치 승인 기록은 빌드·후보 집합 해시, 승인 Association·필수 매핑과 검토 규칙을 고정합니다. 모델 판단과 자동 검증은 승인으로 대체하지 않습니다. 승인 후 지식 자산만 통합하며 신규 문진·진찰 요청·치료·교육 문구는 별도입니다. Sol 외 외부 호출·공식 제출·진단 성능은 포함하지 않습니다.

<a id="D10"></a>
## D10. 준비 컨테이너와 실행 경계

- **상태:** 결정 완료.
- **환경:** 기존 dev 이미지의 표준 SQLite·Pydantic·RDFLib를 사용합니다. 전체 build는 읽기 전용 원천과 두 CPU·8 GB override로 실행하고 offline 검증에서는 네트워크·개발 키를 차단합니다. 호스트 의존성 설치와 다운로드는 하지 않습니다.
- **별도 준비 서비스:** ontology-extraction 이미지·인증 volume·기존 컨테이너는 보존합니다. Compose의 RF2·BODHI·Dev·스키마·submission 입력은 읽기 전용이며 새 준비 출력은 data/preparation/v5/, 임시 출력은 Tmp/ontology-v5/입니다. 변경된 mount를 사용한 기존 컨테이너 재생성은 관측 증거 없이 실행된 것으로 기록하지 않습니다.
- **인증:** 전체 build의 선택적 정규화만 root 개발 키로 공식 NOVA origin의 세션 없는 Sol을 호출합니다. --llm, 현재 KST allowance date, max-calls, daily-remaining을 요구하며 순차 최대 20 packet·medium·8192 tokens로 호출합니다. 자동 재시도·다음 날 대기·이전 작업 재개는 하지 않습니다. Codex 인증 volume은 사용하지 않습니다.
- **배포:** Colima와 Docker context는 고정 인프라입니다. WSL2·다른 컴퓨터·배포·자동 시작·연속 배치는 별도 요청 없이 수행하지 않습니다.

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
- **후보·점수:** D08 v5.0의 Target 기반 후보 합집합과 완전 조건 매칭·원천 라벨·정교화 대체·Target별 중복 제거를 적용합니다. 확인 Context는 최대 +1이며 미확인/부재는 0입니다. 불확실한 대안을 중복 확정하지 않고 최종 동률은 질환 URI 순입니다.
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
- **지식 파일:** Python 그래프 접근 코드와 실제 실행 Turtle·필요한 JSON을 knowledge/에 함께 둡니다. v5.0 structural schema와 공개 scoring_policy는 임상 admission 전에도 포함할 수 있습니다. 임상 자산은 schema·vocabulary·하나 이상의 bundles와 선택 questions·plans를 선언하는 manifest를 요구하며 D08의 모든 버전·해시를 고정합니다. JSON Schema는 JSON 검증용이며 RDF triple 입력과 구분합니다.
- **압축 이미지:** root Dockerfile의 package target과 Compose package 서비스를 사용합니다. submission/만 /submission에 읽기 전용으로, 전용 결과 디렉터리 Tmp/packaging/만 /output에 연결합니다. 네트워크를 끄고 외부 Dev·data·assets와 root .env를 연결하지 않습니다. 압축 도구는 이미지에 포함되며 입력은 /submission으로 고정합니다.
- **결과:** ZIP 루트와 workflow/·knowledge/ 패키지 경로를 유지하고 .env와 지정 config 파일, 필요한 knowledge의 .ttl·.json을 포함합니다. 이전 agents/·문서·캐시·개발 파일·유지 테스트·합성 자산은 제외합니다. 실제 출력은 Tmp/packaging/ontoward-submission.zip입니다.
- **수용 범위:** 설정·경로·압축 입력 격리와 실제 ZIP 검증을 완료합니다. D11이 RDF 로더·조회 구현을 포함하며 임상 지식 완성과 공식 대회 호출·제출은 별도입니다.

<a id="D15"></a>
## D15. 전체 v5.0 배치 수용과 정보 보존 (2026-10-15)

- **상태:** 결정 완료. 사용자가 이 세션의 계획 전체 구현을 명시적으로 요청했습니다.
- **배치:** 빌드 `b4954e33d5c04f4d76949149d9bf6affec1d2ab8c4b34fa99085003933d346aa`, 후보 집합 `b03983497c4ed8246ff16d61de6bb8f9f4cb4bdd34c5c9b3694e2b2910c74151`의 Association 9,400개와 registry 1,701개를 사용 승인합니다. 기존 미승인 검토 자료는 보존하고 `data/preparation/v5/full-snomed-bodhi-2026-10-15/review-approved.json`에 사용자 후보 수용과 독립 임상 검증 미실행을 구분합니다.
- **최소 문구:** 증상 490개의 존재 질문과 속성 16개 질문을 준비하고 누락된 한국어 표시 이름을 별도 labels JSON으로 보완합니다. 원천 URI·관계·조건·가중치는 유지하며 모든 실제 질문을 NFC 1–30자로 검증합니다. manifest의 선택 labels/questions와 해시를 승인 영수증에 고정합니다. 질환별 치료·추적·교육 계획은 포함하지 않습니다.
- **정보 보존:** 실제 전달 질문인 was_asked와 근거가 해결된 has_resolved_evidence를 분리합니다. unknown/uncertain을 확정 관찰로 취급하지 않고 기존 2회 명료화 안에서 미해결 조건을 확인합니다. SOAP에 주체·시간·발현·값·단위·범위를 결정론적으로 보존합니다. 주진단과 감별은 evidence_score>0을 공유하고 선택 질환을 제외한 감별 최대 5개를 표시합니다.
- **Gateway:** 기본 어휘 256개·32 KiB, 확장 1,024개·128 KiB입니다. 현재 질문의 필수 어휘를 우선 보존합니다. 유효 응답의 미연결 증상에만 기존 공유 예산 안에서 확장 1회를 허용하고 최초 유효 사실을 보존합니다. 잘못된 JSON·진찰 거절에는 확장하지 않습니다. 전체 실제 대화와 관찰은 보존합니다.
- **보존:** D08 점수·정교화·에피소드·중복 제거, D11 다섯 세션·상한·Doctor/Gateway 표현 정책, D12 SDK·SOAP, D13 책임 분리와 D14 독립 제출 경계를 유지합니다. D11/D13의 과거 동작 보존 중 이번에 명시한 정보 보존 오류와 어휘 전송만 변경합니다.
- **검증:** 실제 지식 로드와 기존 52개 시나리오 및 추가 회귀, 전체 원천/승인 검증, 실제 RDF와 합성 환자의 전체 흐름, 독립 ZIP 실행을 오프라인 프로젝트 컨테이너에서 확인합니다. 사용 승인·기술 검증을 임상 정확성이나 실제 Luna·공식 서버 수락으로 승격하지 않습니다.
- **후속:** 다음 단일 작업은 사실별 입력 검증과 질문 목적별 복구입니다. 질문 재계획·턴 재배분·설명 의무·준비 문구 우선 비교·모델 판단 확대는 보류합니다. 외부 호출·공식 제출·평가·커밋·배포·코퍼스 확대는 포함하지 않습니다.

## 결정 기록 방법

- 사용자가 고른 선택지를 해당 항목에 기록하고 상태를 `결정 완료`로 바꿉니다.
- 선택 이유와 새로 제공된 정보의 위치를 짧게 남깁니다.
- 필요한 접속 정보나 원본이 아직 없다면 선택 결과와 준비에 필요한 정보를 구분합니다.
- 공식 환경의 제약으로 선택 범위가 사라지면 그 근거와 적용 범위를 기록하고 별도 사용자 선택으로 꾸미지 않습니다.
- 영향을 받는 운영 상태는 이 문서의 결정 ID를 참조하여 다음 작업을 정합니다.
- 결정을 다시 열어야 한다면 같은 항목에 이유를 적고 사용자에게 선택을 요청합니다.
