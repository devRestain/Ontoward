# Ontoward MVP 제품 요구사항

## 목적과 실행 경계

Ontoward는 N.O.V.A. 예선의 모의 환자에게 문진·신체진찰을 수행하고 SOAP 초진 기록과 주진단 하나를 제출한다. 공모전 제출이 프로젝트의 완성 지점이다. 현재 알고리즘은 [D46](DECISION_STATE.md#D46), 임상 자산은 D42의 manifest 핀, 정보 수명은 D44, 공식 행동 예산은 D45를 따른다.

진료 중에는 ZIP 내부의 읽기 전용 RDFLib Graph를 사용한다. 원본 RF2·BODHI·DDXPlus·준비 SQLite는 개발 자산이다. 등록되지 않은 질환·관계·질문을 런타임에서 만들지 않는다. 제공 가이드라인 원문은 진단을 고정한 뒤 지정 마운트에서만 읽는다. 실제 모델 품질과 공식 평가는 로컬 실행 증거와 구분한다.

## 기술과 세 가지 LLM 층위

| 구성 | 책임 |
|---|---|
| Python·Pydantic | 현재 사실, 그래프 조건, 실행 계약, 상태 수명, SOAP 직렬화 검증 |
| LangGraph | 한 증례의 내부 단계와 조건부 이동 |
| RDFLib·Turtle | manifest에 고정한 v5.0 지식과 읽기 전용 조회 |
| 원본 NOVA SDK | 세션 조회, 지정 모델, SAY·EXAM·DIAGNOSE와 완료 확인 |
| Docker | 의존성·개발·검증·독립 ZIP 환경 |

DoctorEar는 자연어를 구조화된 사실·기록으로 수용한다. DoctorBrain은 구조화된 사실과 등록 그래프로 감별 순위·다음 질문·영어 계획을 만든다. 기존 Education의 영어 계획 생성도 DoctorBrain의 책임이다. DoctorMouth는 내부 진단·계획·공감 의도를 환자에게 전달할 한국어로 표현하고 SAY·EXAM을 실행한다.

지정 모델은 기존 `openai/gpt-6-luna`다. Ear·Mouth는 medium, Brain의 임상 판단과 영어 P는 high를 사용한다. SOAP 작성에는 LLM을 호출하지 않는다. Consultation은 유일한 생애주기 조정자이고 SubmissionWriter만 SOAP 제출과 DIAGNOSE 완료를 처리한다.

## 환자 정보와 다섯 내부 세션

초기 opening과 제공 vital_signs를 첫 SAY 전에 해석한다. 이미 제공된 주호소를 다시 유도하지 않는다. 첫 인사는 “병원 오시는 길이 불편하진 않으셨나요?”이며 이후 미확인 정보를 수집한다.

| 세션 | 수행할 일 | 조건부 문진 목표 / 최대 |
|---|---|---:|
| Initiation | 초기 해석·인사·chief 명료화·onset·course·recurrence·previous care | 5 / 7 |
| ChiefComplaint | 대표 CC 하나의 적용 가능한 전체 속성·Open Inquiry·집중 ROS | 7 / 14 |
| ContextFactor | 기본 병력 다섯 영역·관련 Context 최대 두 개 보호 수집·추가 맥락 | 7 / 9 |
| DifferentialDiagnosis | 등록 특징·조건·실제 진찰 중 다음 행동 선택·평가 고정 | 3 / 10 |
| Education | 고정 진단 첫 안내·영어 P·한국어 전달; 답변은 대화 기록 전용 | 5 / 10 |

기확인·unknown·not_applicable·자산 차단·예산 중단을 구별한다. 최소 목표를 채우기 위해 반복하거나 미확인을 음성으로 만들지 않는다. 세션별 최대치를 서로 빌리지 않는다. CC의 마지막 가용 슬롯은 Open Inquiry에 보호하며 집중 ROS는 최초 chief의 계통에서 최대 여섯 대상을 확인한다. 기본 병력은 과거력·약물·알레르기·가족력·사회력이다.

원문은 DoctorEar의 참조 해석 문맥에 한 번만 보관한다. 정확한 영어 용어·허용 속성 값은 Python이 먼저 연결하고 미해결 임상 진술만 제한된 DB 후보로 정규화한다. 독립 유효 행을 보존하며 문맥·형식·강제 매핑의 제한된 복구를 유지한다. 실제 모름을 양성으로 만들거나 측정값만으로 증상 존재를 만들지 않는다.

사실은 주체·가족 구성원·보고자·시점·관찰·episode·수치·단위·polarity·취득 경로·source·turn을 보존한다. 정정은 같은 대상·관찰·주체·시점·취득 범위를 지키며 SAY가 초기 객관 자료나 EXAM을 덮어쓰지 못한다. 실제 의미가 DB에 없으면 간결한 영어 NoteFact와 typed 수치로 기록한다.

환자 age·sex·historian은 같은 notes 정본에서 관리한다. 환자와 보호자를 구별하고 나이·단위·성별을 추정하지 않는다. 반복은 합치고 명시적 정정만 교체하며 미해결 충돌은 uncertain으로 둔다. 현재 임상 자산에 없는 age·sex 적용 규칙을 만들지 않는다.

## 그래프·감별·질문 알고리즘

현재 reasoning 사실의 Target→Pattern→Association→Disease 및 등록 Context 관계로 후보를 회수한다. 부분 패턴·음성·unknown·uncertain은 검토 경로가 될 수 있으나 자동 지지는 아니다. Pattern의 feature matching과 Association applicability를 따로 판정한다. 적용 조건 unknown은 미확인, false는 그 관계의 미적용이며 질환 전체 배제가 아니다.

코드는 현재 supports·against·unresolved와 실제 fact·graph 참조를 유지한다. 수치·값 불일치는 실제 관찰 참조를 남기며 서로 다른 episode의 속성을 합치지 않는다. 일반 패턴의 부합은 refinement 미확인·불일치 때문에 사라지지 않는다. 같은 관찰의 반복 출처를 독립 근거처럼 계산하지 않는다.

CaseState.assessment가 유일한 감별 정본이다. 순서가 순위이며 입력 revision·chief·frozen·한계를 보관한다. 임상 입력 버전당 정상 판단 호출은 최대 한 번이다. LLM은 공급된 질환 참조 순서와 다음 행동만 반환한다. 기존 유효 후보를 누락하거나 미등록·중복 참조를 반환하면 거절한다. 현재 허용 경로가 실제 모두 소실된 후보만 코드가 무효화할 수 있다.

점수·chief coverage·완성 패턴·가상 답변 utility는 수용 gate가 아니다. 코드가 수용 LLM 순위를 재정렬하지 않는다. 전체 임상 messages는 64 KiB, 정상 출력은 4096토큰, 한 번의 복구는 8000토큰으로 제한한다. 기존 후보·반대 근거·미확인은 보호하고 신규 후보는 실제 근거 경로별로 배분한다. 상세 자료 생략과 후보 배제를 구별한다.

필수 수집은 코드가 보장하고 선택적 질문은 LLM이 실행 가능한 선택지에서 고른다. 같은 질문은 합치되 질환별 기대 답을 보존한다. 존재 미확인 증상은 먼저 존재를 확인하며 질문의 등록 관계·문구·단계·주체·가족 구성원·시점·관찰·반복·자원을 검사한다. 유효 순위와 잘못된 행동을 분리하여 행동만 한 번 복구할 수 있다.

DD 종료는 마지막 응답 수용→최신 평가 확인·허용 복구→현재 미확인·한계 확정→Assessment와 기반 facts·notes·chief 고정→Education 이동이다. 자원 종료도 같은 고정 절차를 사용한다. 최신 질환 평가를 얻지 못하면 확인된 등록 chief 하나의 symptom-only 평가를 고정하고, chief도 없으면 실패한다. Writer에서 다시 진단을 고르지 않는다.

## 공식 예산·Education·SOAP

D45에서 SDK `client.session()`의 `turns_remaining`이 행동 예산의 기준이다. SAY·EXAM은 서버 소비를 정산하며 모델·세션 조회·내부 노드·SOAP·DIAGNOSE는 행동 턴을 차감하지 않는다. 공통 한도는 50 행동·모델 200회·입력 500,000·출력 100,000토큰이다. 실제 서버 오류와 거절·잘못된 행동의 소비를 구별하고 같은 요청 재전송은 한 번만 계산한다.

새 행동 전에 응답 해석, 최종 임상 판단과 허용 복구, 활성 P·한국어 안내와 제출 시간을 보호한다. Education 7턴·상한 10턴, 공감의 별도 행동 계산, 응답·최종화 시간 경계를 유지한다. 받은 마지막 답변은 잔여 턴이 0이어도 먼저 처리하고 DIAGNOSE를 제출한다. 일시 전송 오류는 같은 ID·payload로 2초 뒤 한 번 재전송하며 불명 결과는 명시적으로 종료한다.

Education은 고정 1위를 먼저 알린 뒤 원문 지침·일반 지식의 출처를 구별하여 영어 P를 만든다. 한국어는 독립 NFC 1–30 codepoint 문장으로 검증하며 조건부 문장 묶음을 부분 전달하지 않는다. 공급자 응답 복구 한 번과 문구 검증 복구 한 번을 구별하고 실패해도 영어 P를 보존한다. 환자 답변으로 facts·진단·A를 갱신하지 않는다. 명시적 `ONTOWARD_EDUCATION_ENABLED=false`는 교육 행동·예약·P.education 없이 동작한다.

SOAP는 현재 사실·유효 notes·frozen Assessment·영어 계획·실제 전달 결과를 Python으로 묶는다. age·sex는 HPI 선두, 보고값은 S, 신뢰된 초기 객관 구간과 실제 EXAM의 소견·속성·적격 objective note는 O다. O에는 실제 취득 turn을 보존한다. 같은 관찰의 조건·시점·단위를 잃지 않으며 A는 같은 S/O 사실 문구를 재사용한다.

| 구역 | 문자열 필드 |
|---|---|
| S | cc, hpi, pmh, fh, sh, ros |
| O | exam, tests |
| A | evidence, differential |
| P | tests, treatment, disposition, follow_up, education |

별도 `diagnosis`는 frozen 목록의 1위와 일치한다. `note.A.diagnosis`를 추가하지 않는다. 예선 O.tests는 빈 문자열이다. 미질문·미시행·계획·실제 전달을 구별하며 기록 100,000바이트·진단 500바이트를 검증한다. 형식 복구는 같은 고정 평가에서 한 번 재구성한다. 정상 완료는 DIAGNOSE의 `completed` 응답이다.

## 상태·검증·제출물

WorkflowState에는 case·interview·session과 현재 turn만 둔다. CaseState는 facts·notes·chief·Assessment·plan·revision, InterviewState는 현재 질문·작은 Answer·수집 중단, SessionContext는 최신 제약·사용량·종료를 소유한다. SOAP는 제출 turn에만 존재한다. 그래프 후보 자료·LLM 교환·복구·원문 조각은 지역값이며 과거 순위·별도 진단 정본·가상 답변·런타임 audit를 보관하지 않는다.

프로젝트 Docker에서 유지 행동 회귀, 실제 수용 RDF 상담, 관측 유무 일치, 독립 읽기 전용 ZIP과 원본 SDK HTTP 완료를 검증한다. Test가 프로토콜 대역·재현·관측·비교를 소유하고 Dev/tests/workflow가 유지 회귀를 소유한다. 고정 응답 통과를 실제 모델 정확도나 임상 성능으로 해석하지 않는다.

제출 ZIP에는 실행 Python·고정 requirements·공개 .env·필요 프롬프트·manifest 자산만 넣는다. 루트 개발 키·Test·Dev·원본 자료·준비 DB·문서·상태·캐시는 제외한다. 구현 설명은 [한국어 백서](submission/README.md), 사용자 선택은 [결정 문서](DECISION_STATE.md), 관측 결과는 세 운영 상태와 [D46 증빙](data/provenance/algorithm-d46-2026-10-19.json)에서 관리한다. 임상 코퍼스 확장·실제 유료 호출·공식 평가·게시·배포는 이 구현 수용과 별도다.
