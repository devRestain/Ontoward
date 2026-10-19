# Ontoward MVP 제품 요구사항

## 목적과 실행 경계

Ontoward는 N.O.V.A. 예선의 모의 환자에게 문진·신체진찰을 수행하고 SOAP 초진 기록과 주진단 하나를 제출한다. 공모전 제출이 프로젝트의 완성 지점이다. 현재 알고리즘은 [D49](DECISION_STATE.md#D49)의 무점수 지식 계약을 적용하고 D48 프롬프트 모듈, D47 객체·사실·호출 일정, D44 정보 수명, D45 공식 행동 예산을 유지한다. 기존 DB의 활성 사용은 철회했으며 실제 새 번들 설치 전 prepare와 정식 패키징은 knowledge_bundle_not_installed로 실패해야 한다.

진료 중에는 ZIP 내부의 읽기 전용 RDFLib Graph를 사용한다. 원본 RF2·BODHI·DDXPlus·준비 SQLite는 개발 자산이다. 등록되지 않은 질환·관계·질문을 런타임에서 만들지 않는다. 제공 가이드라인 원문은 진단을 고정한 뒤 지정 마운트에서만 읽는다. 실제 모델 품질과 공식 평가는 로컬 실행 증거와 구분한다.

## 기술과 기능 객체

| 구성 | 책임 |
|---|---|
| Python·Pydantic | 현재 사실, 그래프 조건, 실행 계약, 상태 수명, SOAP 직렬화 검증 |
| LangGraph | 한 증례의 내부 단계와 조건부 이동 |
| RDFLib·Turtle | manifest에 고정한 v5.0 지식과 읽기 전용 조회 |
| 원본 NOVA SDK | 세션 조회, 지정 모델, SAY·EXAM·DIAGNOSE와 완료 확인 |
| Docker | 의존성·개발·검증·독립 ZIP 환경 |

DoctorEar는 입력 전처리·해석·사실 수용을, 다섯 세션 객체는 세션별 수집·임상 판단·응답 검증을 소유한다. EducationSession이 영어 계획의 준비·검증과 진단 안내·계획 전달 순서·턴 배분·큐 등록·준비 상태를 소유한다. DoctorMouth는 공감·한국어 표현·SAY·EXAM 실행을 소유하며 교육 표현 결과를 반환할 때 전달 큐나 준비 상태를 수정하지 않는다. DoctorBrain은 증례당 하나인 공통 LLM 실행기로서 지정 모델·effort·호출 한도·사용량·전송 오류와 동일 요청 재전송만 담당한다. 모든 호출자에 같은 객체를 주입하며 별도 ModelClient는 없다.

지정 모델은 기존 `openai/gpt-6-luna`다. Ear·Mouth는 medium, 세션의 임상 판단과 영어 P 호출은 high를 사용한다. SOAP 작성에는 LLM을 호출하지 않는다. Consultation은 유일한 생애주기 조정자이고 SubmissionWriter만 SOAP 제출과 DIAGNOSE 완료를 처리한다.

세션 사이에는 다른 세션 객체를 전달하지 않는다. Consultation이 CC 종료 성공 여부와 평가의 현재 revision·chief 일치 및 미고정 상태를 확인한 뒤 ContextFactor에 평가 자료만 전달한다. 평가를 사용할 수 없으면 기본 병력과 준비 불가 사유를 유지한다.

## 환자 정보와 다섯 내부 세션

초기 opening과 제공 vital_signs를 첫 SAY 전에 해석한다. 이미 제공된 주호소를 다시 유도하지 않는다. 첫 인사는 “병원 오시는 길이 불편하진 않으셨나요?”이며 이후 미확인 정보를 수집한다.

| 세션 | 수행할 일 | 조건부 문진 목표 / 최대 |
|---|---|---:|
| Initiation | 초기 해석·인사·chief 명료화·onset·course·recurrence·previous care | 5 / 7 |
| ChiefComplaint | 대표 CC 하나의 적용 가능한 전체 속성·Open Inquiry | 7 / 14 |
| ContextFactor | 기본 병력 다섯 영역·관련 Context 최대 두 개 보호 수집·추가 맥락 | 7 / 9 |
| DifferentialDiagnosis | 집중 ROS·등록 특징·조건·실제 진찰 중 다음 행동 선택·평가 고정 | 3 / 10 |
| Education | 고정 진단 첫 안내·영어 P·한국어 전달; 답변은 대화 기록 전용 | 5 / 10 |

기확인·unknown·not_applicable·자산 차단·예산 중단을 구별한다. 최소 목표를 채우기 위해 반복하거나 미확인을 음성으로 만들지 않는다. 세션별 최대치를 서로 빌리지 않는다. CC의 마지막 가용 슬롯은 Open Inquiry에 보호한다. 집중 ROS는 DD에서 chief의 계통·중복·존재 확인을 지키며 최대 여섯 대상을 기존 10행동 상한 안에서 확인한다. Context 질문 출처는 CC 종료의 유효 Assessment에 든 질환으로 고정하고 수집 중 새 후보로 확장하지 않는다. 유효 CC 평가가 없으면 기본 병력만 수집하고 관련 Context 준비 불가 사유를 남긴다. 기본 병력은 과거력·약물·알레르기·가족력·사회력이다.

원문은 DoctorEar의 참조 해석 문맥에 한 번만 보관한다. 정확한 영어 용어·허용 속성 값은 Python이 먼저 연결하고 미해결 임상 진술만 제한된 DB 후보로 정규화한다. 독립 유효 행을 보존하며 문맥·형식·강제 매핑의 제한된 복구를 유지한다. 실제 모름을 양성으로 만들거나 측정값만으로 증상 존재를 만들지 않는다.

사실은 주체·가족 구성원·보고자·시점·관찰·episode·수치·단위·polarity·취득 경로·source·turn을 보존한다. 정정은 같은 대상·관찰·주체·시점·취득 범위를 지키며 SAY가 초기 객관 자료나 EXAM을 덮어쓰지 못한다. CaseState.facts의 CaseFact 하나에 정규화된 영어 내용과 수치·조건을 저장하고 선택적 graph_binding에 등록 target·attribute·values·연결 방식·그래프 사용 자격을 둔다. 매핑 결과와 부가 설명을 중복 사실로 저장하지 않는다. DB에 없는 정보도 같은 정본에 보존한다.

환자 age·sex·historian은 같은 facts 정본에서 관리한다. 환자와 보호자를 구별하고 나이·단위·성별을 추정하지 않는다. 반복은 합치고 명시적 정정만 교체하며 미해결 충돌은 uncertain으로 둔다. 현재 임상 자산에 없는 age·sex 적용 규칙을 만들지 않는다.

## 그래프·감별·질문 알고리즘

새 후보는 support 또는 strong_support 관계의 scoped Target→Pattern→Association→Disease 또는 applicability 경로로 회수한다. 전체 Pattern 일치는 후보 진입 조건이 아니며 against-only 경로로 무관한 새 후보를 확장하지 않는다. 기존 후보는 현재 유효한 그래프 경로가 남아 있으면 보존한다. 전체 Feature와 applicability가 모두 일치할 때만 등록 effect를 활성화한다. 부분 일치는 활성 지지가 아니고 불일치를 반대 효과로 뒤집지 않는다. 명시적 모순으로 불가능해진 관계의 나머지 조건은 질문하지 않는다.

코드는 현재 supports·against·unresolved와 실제 fact·graph 참조를 유지한다. 수치·값 불일치는 실제 관찰 참조를 남기며 서로 다른 episode의 속성을 합치지 않는다. 일반 패턴의 부합은 refinement 미확인·불일치 때문에 사라지지 않는다. 같은 관찰의 반복 출처를 독립 근거처럼 계산하지 않는다.

CaseState.assessment가 유일한 감별 정본이다. 순서가 순위이며 입력 revision·chief·frozen·한계를 보관한다. Initiation·CC·ContextFactor는 정상 종료 때 각각 한 번 순위만 요청하며 turn 0·중간 문진에서는 순위를 계산하지 않는다. DD는 진입 시 기존 평가로 첫 행동을 고르고 이후 환자 응답마다 순위와 다음 행동을 함께 판단한다. unknown으로 revision이 같아도 새 응답을 판단하되 동일 응답의 내부 재진입은 중복 호출하지 않는다. 종료 시 이미 성공한 최신 판단을 재사용한다. LLM은 작업별 작은 JSON만 반환하며 호출자가 Pydantic 구조 검증과 등록 참조·중복·누락·현재 범위 검사를 수행한다. 기존 유효 후보를 누락하거나 미등록·중복 참조를 반환하면 거절한다. 현재 허용 경로가 실제 모두 소실된 후보만 코드가 무효화할 수 있다.

점수·chief coverage·완성 패턴·가상 답변 utility는 수용 gate가 아니다. 코드가 수용 LLM 순위를 재정렬하지 않는다. 정상 임상 출력은 4096토큰, 한 번의 복구는 8000토큰이다. 기능별로 필요한 Key와 Value를 명시적으로 선택해 문자열로 전달한다. 전체 상태·큰 schema·그래프 profile 전문을 주입하지 않으며 사실·조건·미확인은 지역 참조표에 한 번 정의한다. 기존 유효 후보·반대 근거·미확인을 보존하고 고정 Top-K를 두지 않는다. 프롬프트 바이트 측정·목표·제한·진단 통계와 이에 따른 절단·배치·압축 기능은 사용하지 않는다.

공개 ONTOWARD_PROMPTS manifest에 책임·출력·상황별 프롬프트 모듈을 등록한다. Ear·세션·Education·Mouth가 Python에서 현재 작업과 initial·reply·EXAM, 일반·강제 매핑, 질환·증상 안내, 실제 복구에 필요한 모듈만 선택한다. LLM에 여러 작업의 조건 분기를 해석시켜 작업을 고르게 하지 않는다. 지시와 key-value 입력을 분리하고 실제 임상 조건은 입력 데이터로 보존한다. 같은 manifest와 모듈을 독립 ZIP에 포함하고 관측기에서 해시·경로 조합을 확인한다.

필수 수집은 코드가 보장하고 선택적 질문은 LLM이 실행 가능한 선택지에서 고른다. 공유 근거와 expected_by_disease에는 effect·scope·전체 Pattern·applicability를 첫 DD action-only 입력에도 전달한다. 같은 질문은 합치되 질환별 기대 답을 보존한다. 질문 순서·SOAP category·clarification은 새 attribute_roles에서 읽는다. Context는 같은 CaseFact로 매칭하고 별도 supporting-context 경로를 두지 않는다. rule any와 구체 질문의 current/past/unspecified를 분리하며 해결 여부는 원래 rule scope로 검사한다. 속성만 있는 Pattern을 포함하여 같은 Target·scope의 존재를 확인한 뒤 속성 질문을 실행하며 질문의 등록 관계·문구·단계·주체·가족 구성원·시점·관찰·반복·자원을 검사한다. 유효 순위와 잘못된 행동을 분리하여 행동만 한 번 복구할 수 있다.

DD 종료는 마지막 응답 수용→최신 평가 확인·허용 복구→현재 미확인·한계 확정→Assessment와 기반 facts·chief 고정→Education 이동이다. 자원 종료도 같은 고정 절차를 사용한다. 최신 질환 평가를 얻지 못하면 확인된 등록 chief 하나의 symptom-only 평가를 고정하고, chief도 없으면 실패한다. Writer에서 다시 진단을 고르지 않는다.

## 공식 예산·Education·SOAP

D45에서 SDK `client.session()`의 `turns_remaining`이 행동 예산의 기준이다. SAY·EXAM은 서버 소비를 정산하며 모델·세션 조회·내부 노드·SOAP·DIAGNOSE는 행동 턴을 차감하지 않는다. 공통 한도는 50 행동·모델 200회·입력 500,000·출력 100,000토큰이다. 실제 서버 오류와 거절·잘못된 행동의 소비를 구별하고 같은 요청 재전송은 한 번만 계산한다.

새 행동 전에 응답 해석, 최종 임상 판단과 허용 복구, 활성 P·한국어 안내와 제출 시간을 보호한다. Education 7턴·상한 10턴, 공감의 별도 행동 계산, 응답·최종화 시간 경계를 유지한다. 받은 마지막 답변은 잔여 턴이 0이어도 먼저 처리하고 DIAGNOSE를 제출한다. 일시 전송 오류는 같은 ID·payload로 2초 뒤 한 번 재전송하며 불명 결과는 명시적으로 종료한다.

Education은 고정 1위를 먼저 알린 뒤 원문 지침·일반 지식의 출처를 구별하여 영어 P를 만든다. 한국어는 독립 NFC 1–30 codepoint 문장으로 검증하며 조건부 문장 묶음을 부분 전달하지 않는다. 공급자 응답 복구 한 번과 문구 검증 복구 한 번을 구별하고 실패해도 영어 P를 보존한다. 환자 답변으로 facts·진단·A를 갱신하지 않는다. 명시적 `ONTOWARD_EDUCATION_ENABLED=false`는 교육 행동·예약·P.education 없이 동작한다.

Education 전달 준비에 재진입해도 이미 큐에 있거나 전달·미전달 결과가 기록된 계획 그룹은 다시 표현하지 않는다. 준비 실패의 제한된 복구는 해당 표현 호출 안에서만 수행하며, 재진입으로 실패 그룹을 자동 재시도하거나 결과를 중복 기록하지 않는다. 실제 행동 완료·취소는 공통 QuestionLifecycle을 사용한다.

SOAP는 통합 사실·frozen Assessment·영어 계획·실제 전달 결과를 Python으로 묶는다. age·sex는 HPI 선두, 보고값은 S, 신뢰된 초기 객관 구간과 실제 EXAM의 소견·속성·적격 객관 사실는 O다. O에는 실제 취득 turn을 보존한다. 같은 관찰의 조건·시점·단위를 잃지 않으며 A는 같은 S/O 사실 문구를 재사용한다.

| 구역 | 문자열 필드 |
|---|---|
| S | cc, hpi, pmh, fh, sh, ros |
| O | exam, tests |
| A | evidence, differential |
| P | tests, treatment, disposition, follow_up, education |

별도 `diagnosis`는 frozen 목록의 1위와 일치한다. `note.A.diagnosis`를 추가하지 않는다. 예선 O.tests는 빈 문자열이다. 미질문·미시행·계획·실제 전달을 구별하며 기록 100,000바이트·진단 500바이트를 검증한다. 형식 복구는 같은 고정 평가에서 한 번 재구성한다. 정상 완료는 DIAGNOSE의 `completed` 응답이다.

## 상태·검증·제출물

WorkflowState에는 case·interview·session과 현재 turn만 둔다. CaseState는 통합 facts·chief·Assessment·plan·revision, InterviewState는 현재 질문·작은 Answer·수집 중단, SessionContext는 최신 제약·사용량·종료를 소유한다. SOAP는 제출 turn에만 존재한다. 그래프 후보 자료·LLM 교환·복구·원문 조각은 지역값이며 과거 순위·별도 진단 정본·가상 답변·런타임 audit를 보관하지 않는다.

프로젝트 Docker에서 유지 행동 회귀, 임시 새 합성 번들의 상담, 관측 유무 일치, 독립 읽기 전용 ZIP과 원본 SDK HTTP 완료를 검증한다. Test가 프로토콜 대역·재현·관측·비교를 소유하고 Dev/tests/workflow가 유지 회귀를 소유한다. 고정 응답 통과를 실제 모델 정확도나 임상 성능으로 해석하지 않는다.

제출 ZIP에는 실행 Python·고정 requirements·공개 .env·필요 프롬프트·manifest 자산만 넣는다. 루트 개발 키·Test·Dev·원본 자료·준비 DB·문서·상태·캐시는 제외한다. 구현 설명은 [한국어 백서](submission/README.md), 사용자 선택은 [결정 문서](DECISION_STATE.md), 관측 결과는 세 운영 상태와 [D49 증빙](data/provenance/algorithm-d49-2026-10-19.json)에서 관리한다. 임상 코퍼스 확장·실제 유료 호출·공식 평가·게시·배포는 이 구현 수용과 별도다.

## 새 지식 번들과 추출 자동화

실행 지식은 schema_version 5.0, knowledge_contract v5-enum-1이다. manifest는 build_id와 schema·vocabulary·clinical·questions·guidelines 다섯 asset의 상대 경로·SHA-256만 가진다. 경로는 manifest 디렉터리 기준이며 절대 경로·경계 이탈·hash 불일치를 거절한다. 번들은 manifest 포함 여섯 파일이고 questions JSON은 attribute_roles를 포함한다. 한·영 표제와 별칭은 새 vocabulary가 제공한다. 이전 형식과의 호환 변환·policy fallback은 없다.

Disease→Association→Pattern→Feature를 유지하고 ContextFactor를 Target에 추가한다. Association은 명시적 target_scope·applicability와 정성 effect를 가진다. 생성 effect는 support·strong_support·against·strong_against·neutral이며 neutral은 작업 DB에 완료 결과로 보존하고 RDF에서는 제외한다. 점수·가중치·전형성·ScoringPolicy·scoring/reasoning policy·관계 source/confidence/reviewer·옛 admission 필수 검증을 제거한다. 환자 취득 source/turn·주체·시점과 Education의 문서 경로/hash/인용은 유지한다. 수치 진단 점수 제거는 나이·실측값·기간·통증 수치·단위·비교 연산자 제거를 뜻하지 않는다.

Extraction/은 네 원자료에서 빈 SQLite 작업 DB로 시작한다. RF2 Snapshot·배포 의존성, 실제 BODHI CSV, DDXPlus evidence/condition metadata, Astra 후보·속성·값·CPX 범위를 사용한다. 환자 ZIP·이전 생성 DB/질문/어휘/source-custody SQLite·Astra 과거 snapshot/등록 정책을 새 정본으로 사용하지 않는다. 입력 인덱싱→개념/역할 정규화→질문/진찰→유한 관계 초안→최종 분류/충돌 해소→한 번의 결손 보완→staging 컴파일/검증/명시적 설치를 수행한다. 원자료가 부족한 일반 관계는 최종 모델 내부 지식으로 완성하되 환자 관찰은 생성하지 못한다.

공급자는 nova_dev·codex_subscription·openai_api 중 빌드당 하나다. 초안 gpt-6-luna·최종 gpt-6.1-sol의 effort는 모두 medium이다. NOVA는 원본 SDK의 세션 밖 Client.chat, 구독은 새 전용 volume의 사용자 ChatGPT device login과 도구를 비활성화한 read-only codex exec, API는 도구 없는 Responses 구조화 출력을 사용한다. 인증은 선택 경로에만 전달하고 자동 모델 변경·provider fallback·계정 전환은 없다. NOVA/API 출력 상한은 8000/32000이고 CLI에는 강제 토큰 상한을 주장하지 않는다. 요청/CLI 제한은 600초, Compose 종료 유예는 660초다. NOVA KST 일일 한도와 다른 공급자의 한도·재시도 시점을 구별한다.

run·status·pause·verify·install을 제공한다. 조회·중단·검증은 client/개발 키 없이 동작한다. 입력/설정/공급자/모델/프롬프트/생성 계약 hash와 단계·chunk cursor·job 결과·재시도·usage를 SQLite transaction으로 저장하고 worker는 하나만 실행한다. 같은 fingerprint의 --resume만 허용하고 완료·neutral을 재호출하지 않는다. 전송 전 payload/인자/job ID/request ID를 기록하고 응답을 먼저 보존한다. pause·SIGINT·SIGTERM은 새 전송을 막고 한 in-flight 응답의 유효 행을 저장한 뒤 paused로 정상 종료한다. 쿼터 대기 중에도 중단할 수 있다.

강제 종료 후 저장 응답이 없으면 outcome_unknown이다. NOVA는 지원되는 같은 ID/payload 복구를 사용하며 API/CLI는 원격 중복 방지를 가정하지 않는다. 운영자의 --retry-unknown이 있어야 새 시도를 허용하고 이전 불명 기록을 보존한다. 설치는 검증된 build 전용 파일을 먼저 쓰고 manifest를 마지막에 원자적으로 바꾼다. 완료/일시 중단 뒤 자동 재시작하지 않는다.

이미지는 ontoward-extraction:local이며 Python 3.12·기존 고정 Python 의존성·@openai/codex@0.162.1을 포함한다. 이미지 빌드 다운로드만 이번에 허용했고 실제 로그인·유료 DB 생성·실제 설치·정식 ZIP은 실행하지 않는다. 기존 자산/점수 builder를 활성 경로에서 철회하고 과거 원자료·준비 결과·수용 ZIP·증거는 보존한다. 이번 완료는 이미지와 무점수 워크플로우의 구현·오프라인 수용으로 한정하며 다음 작업은 공급자 선택·인증 후 실제 생성/설치다.
