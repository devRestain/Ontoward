# Ontoward MVP 제품 요구사항

## 목적과 이번 산출물

Ontoward는 N.O.V.A. 모의 환자의 초기 정보에서 출발하여 문진·신체진찰로 필요한 정보를 모으고, S·O·A·P 초진 기록과 주진단 하나를 제출하는 진단 에이전트다. 첫 구현 대상은 예선이며, 본선의 검사 실행과 참가자 모델은 후속 단계로 구분한다.

첫 MVP는 한 증례를 메모리에서 진행한다. 사용자는 에이전트가 어떤 정보를 얻었고, 어떤 후보를 고려하며, 왜 다음 행동을 제안하는지 확인할 수 있어야 한다.

현재 제출 에이전트 범위는 D11의 2026-10-14 Doctor 인터페이스·집중 ROS·제출 복구 MVP이며, D12의 제출 구성, D13의 상태·실행 책임 분리, D14의 제출 내부 자산 경계를 따른다. 별도 준비 범위 D09는 사용자의 최신 선택에 따라 SNOMED CT 기반 용어 확장 후 스키마 변환을 기본 경로로 삼는다. 코드와 합성 전체 흐름의 검증을 실제 임상 자산 승인·Doctor 품질·공식 제출 성공과 구분한다.

공식 요구사항 확인일은 **2026-10-14 KST**이다. [개발 가이드](https://nova.snubhai.org/docs/), [참가 규칙](https://nova.snubhai.org/rules/), [평가](https://nova.snubhai.org/evaluation/)와 [10월 13일 공지](https://nova.snubhai.org/qna/)를 보존 SDK 1.0.1 및 기존 참고 문서와 대조했다. 현재 적용 변경은 [10월 14일 규칙 업데이트](assets/nova-competition-2026/CHANGES_2026-10-14.md)에 기록한다. 두 제공 PPTX의 변환과 [10월 12일 비교](assets/nova-competition-2026/CHANGES_2026-10-12.md)는 당시 자료로 유지한다. 홈페이지의 정확한 수정 시각과 새 시작 패키지의 실제 SDK 버전·바이트는 확인하지 않았다.

## 채택한 기술과 역할

| 기술 | 책임 |
|---|---|
| Python | 데이터 준비와 에이전트 실행 코드 |
| LangGraph | 한 증례의 단계와 조건부 이동 |
| Pydantic | 관찰·세션·행동·SOAP·진단의 구조와 경계 검증 |
| N.O.V.A. SDK | 지정 Doctor 호출, 세션 확인, 행동 실행과 최종 제출 |
| 제공 진료지침 | 기존 입력과 승인·응답·준비 결과를 보존하며, 현재 기본 추출 경로로 자동 재개하지 않음 |
| SNOMED CT International Edition | 현재 기본 준비 원천; RF2 어휘 확장 뒤 기존 스키마에 관계와 Feature를 투영 |
| NOVA 개발 API | 명시적으로 실행한 준비 단계에서만 세션 없는 `openai/gpt-6.1-sol` 사용; 기본은 dry-run |
| RDFLib | RDF 생성·로드·조회; 진료 중 준비된 임상 그래프 검색 |
| Turtle | 문서별 추출 결과와 출처별 제출 지식 묶음의 저장 형식 |
| BODHI-S | 후속 단계의 질환과 증상 변형 사이의 출처가 있는 연관 근거 |
| Docker | Python 실행과 의존성 설치 환경 |

JEV, Laya, HPOA는 사용하지 않는다. 이번 MVP는 대표 합성 사례의 전체 실행을 검증하며 배포·호환성 매트릭스는 도입하지 않는다.

첫 경로는 공식 샘플 API와 지정 `openai/gpt-6-luna` Doctor 모델이며, 한국어 증례·환자 대화·제출 기록을 처리한다. 2026-10-13 시행된 모델 변경을 사용자가 10월 14일 확인했으며 D01의 선택에 반영한다. 사전 준비는 허가된 International Edition SNOMED CT에서 어휘를 확장하고 그 다음 Disease–ClinicalPattern–ClinicalFeature 변환을 수행한다. 준비 호출은 세션 없는 NOVA 개발 API에서 `openai/gpt-6.1-sol`을 사용하며 Doctor의 Luna 설정과 분리한다. 선택과 적용 범위는 [결정 상태](DECISION_STATE.md)의 D01·D02·D03·D04·D05·D06·D07·D08·D09·D10·D11·D12가 소유한다. 진료 중 SNOMED 원본이나 지침 문서 검색은 사용하지 않는다.

## 사용자가 경험할 흐름

다섯 내부 세션은 하나의 공식 NOVA 세션 안에서 진행한다. Doctor는 선택된 SAY의 표현을, Gateway는 실제 응답 구조화를 담당하며 모두 `openai/gpt-6-luna`를 사용한다. 질문·교육 선택, 검색, 점수, 진단 선택, SOAP 구성은 Python이다.

| 내부 세션 | 준비와 종료 조건 | 행동 상한 |
|---|---|---:|
| Initiation | 초기 정보·활력징후 보존 후 반드시 인사와 주호소 유도로 시작 | 1 |
| ChiefComplaint | 유지된 HPI → Open Inquiry 1회 → 주호소 계통의 미확인 ROS 최대 6개 | 20 |
| ContextFactor | 증상 후보 합집합 검색, 제한된 명료화·재검색, 관련 Context 문진 | 10 |
| DifferentialDiagnosis | Context 가점과 특징·진찰 질문 처리, 마지막 답까지 재계산 | 14 |
| Education | 질환 또는 증상 수준 진단 선택, InterviewPlanner가 준비 교육 선택 | 5 |
| 최종화 | SOAP 구성·검증·필요 시 1회 재구성 → DIAGNOSE → completed 확인 | 0 |

시작 준비 문구는 “안녕하세요. 무엇이 어떻게 불편하세요?”다. 초기 정보가 있어도 인사·주호소 유도를 수행하며 이미 확인한 세부 사실은 HPI에서 반복하지 않는다. EXAM은 준비된 단일 진찰 문구를 사용한다.

현재 scope 질문은 한 번 준비한다. 대기 응답을 먼저 처리하고 예산에 맞춰 낮은 우선순위 unasked와 QuestionPlan 참조를 함께 삭제한다. 삭제 항목을 다시 만들거나 deferred 큐에 넣지 않는다. 원문·확보 사실·대기 행동·전달 이력·계획은 보존한다. 명료화는 아래의 증례별 한도 안에서 추가하는 별도 질문이다.

집중 ROS는 확인된 주호소의 기존 `inSystem`과 `BodySystem` 관계를 사용한다. 계통들의 증상을 합집합으로 모아 주호소 자체·기확인·중복을 제외하고 URI 순으로 최대 6개 준비한다. HPI 준비 시 목록을 고정하며 Open Inquiry에서 확인한 항목은 실행 전에 건너뛴다. 새 ROS 증상으로 다른 계통을 확장하거나 연결이 없는 계통을 추정하지 않는다. 보존 우선순위는 Open Inquiry, ROS, HPI이며 실행 순서는 HPI, Open Inquiry, ROS다. ChiefComplaint 20턴 안에서 뒤쪽 HPI를 줄여 Open 1턴·가능한 ROS 6턴을 확보한다. BodySystem은 질환 후보 검색을 제한하지 않는다.

Context 질문은 연결 후보 수, 감별 질문은 후보 순위와 검토된 characteristic 표시로 정렬한다. 단독 선두라도 남은 감별을 계속한다. 새로운 관찰·정정·교육 응답이 들어오면 현재 사실에서 후보와 점수를 다시 계산한다. 교육 중 진단이 바뀌면 아직 전달하지 않은 부적합한 설명만 남은 예산 안에서 교체하며 앞 세션으로 돌아가지 않는다. SubmissionWriter는 최종 기록·검증·제출만 담당한다.

점수는 characteristic 지지 +2, 일반 지지 +1, 명시적 반대·모순 −1이다. 확인된 관련 Context는 후보당 최대 +1이고 그 외 0이다. 같은 원관찰·조건을 대안 Pattern이나 출처 수만큼 가산하지 않으며 불확실한 개념 대안·다른 에피소드를 합치지 않는다. 최종 동률은 질환 URI 순이다. 별도 ClinicalSynthesis는 없다.

| 복구 상황 | 처리 |
|---|---|
| Doctor 출력 실패 | 최초 생성 + 최대 2회 재생성 → 검증된 준비 문구 → 그것도 불가하면 미확인/미전달 |
| 구조화 실패·주호소 불명확·후보 없음 | 원문 보존, 증례 전체 명료화 최대 2회와 재검색 |
| 후보가 계속 없음 | 확인된 현재 주호소의 증상 수준 잠정진단, 원인 미확정 표시, 질환 치료 없이 준비 안내 |
| 진단 근거 주호소도 없음 | 명시적 실패 |
| 진찰 거절·실행 불가능 | 실제 소견으로 만들지 않고 가능한 다음 행동 |
| 일시 전송 오류·REQUEST_PENDING | 같은 ID·payload로 2초·5초 후 최대 2회 재전송 |
| 명시적인 환자·진찰 응답 형식 오류 | 새 요청 ID로 한 번 재시도 |
| 수집 예산 소진 | 대기 답변 처리 후 확보 사실로 SOAP·DIAGNOSE |
| SOAP 형식 오류 | 보존 사실에서 한 번 재구성하고 재검증 |

Doctor·Gateway·재생성은 증례 전체 200회·입력 500,000·출력 100,000토큰을 공유한다. 이전 파싱 전용 scope 호출 상한은 사용하지 않는다. 행동 상한은 세션 간 차용하지 않으며 실제 서버 제약을 우선한다. 질문 계획에 표현·응답 처리 호출을 함께 계산하고 Doctor 생성·재생성에서 Gateway 한 호출과 최대 2,048 출력토큰을 남긴다. 입력 토큰은 실제 usage를 누적하며 서버 제한 오류 시 새 수집을 멈춘다. 최종 제출에 120초를 남기고 graph-step 상한은 SDK 턴과 구분한다. 정상 finish는 해당 DIAGNOSE의 completed를 확인한 경우뿐이며 만료·폐쇄·복구 소진 후 결과 불명은 명시적 비정상 종료다.

## 공식 세션·실행 계약

| 항목 | 예선 요구사항 |
|---|---|
| 준비 | `prepare()`에서 증례 접근 없이 지식 자원 준비, 최대 10분 |
| 진료 | 준비 알림 후 `consult(client, resources)`에서 세션 접근, 최대 30분 |
| 모델 | 지정 `openai/gpt-6-luna` Doctor API를 증례당 최소 1회·최대 200회; 입력 500,000·출력 100,000토큰 |
| 행동 | `SAY`·`EXAM`은 각각 1턴, `DIAGNOSE`는 0턴, `TEST`는 차단 |
| 입력 길이 | SAY·EXAM·본선 TEST는 NFC 정규화 후 1–30 유니코드 코드 포인트; 공백·문장부호·줄바꿈 포함 |
| 상호작용 | 최대 50턴; 50번째 응답 이후에도 제한 시간 안에서 DIAGNOSE 가능 |
| 실행 자원 | 증례별 컨테이너, CPU 2코어·RAM 8GB·GPU 없음 |

세션 응답의 남은 턴·마감 시각·허용 행동을 실행 판단에 반영한다. Doctor 생성 이후 별도 Python 단계가 NFC 정규화·빈 출력·30자 한도를 검증한다. 실패 이유와 실제 길이를 전달하여 최대 두 번 재생성한 뒤 준비 문구도 같은 검증기로 확인한다. 임의 절단은 하지 않는다. 필요한 설명, 기록 작성, 모델 호출과 제출에 쓸 시간을 남겨 둔다. 시작 패키지의 30턴 사용과 3분 여유는 예제 정책이며 대회가 요구하는 고정값이 아니다. [실행 제한](https://nova.snubhai.org/rules/)

형식·의미 거절은 실제 수행이나 관찰로 확정하지 않는다. 공개 문서에서 `EXAM_NOT_SPECIFIC`·`EXAM_NOT_RECOGNIZED`는 결과 없이 1턴을 사용하며, `ACTION_NOT_AVAILABLE`은 턴을 쓰지 않는다. 응답의 남은 턴을 확인하고 반복 거절을 무한 재시도하지 않는다. 전송 결과가 불명확한 동일 요청은 같은 `request_id`와 내용을 유지한다. 명시적인 모델·환자·진찰 판정 실패가 반환되어 비용·턴을 쓰지 않은 경우의 새 시도는 새 요청으로 구분한다. D11의 제한된 동일 요청 재전송과 명시적 환자·진찰 응답 오류의 새 ID 재시도만 허용하며 세션 종료·만료는 명시적 종료다. 기본 예제의 재시도 코드와 개발 키트만으로 공식 서버의 중복 처리·복구 동작을 검증했다고 주장하지 않는다. [요청과 오류 규칙](https://nova.snubhai.org/docs/)

서버가 받은 빈 내용·길이 초과 SAY/EXAM과 부적절한 EXAM은 1턴을 쓴다. SDK가 전송 전에 ValueError로 막은 요청은 턴을 쓰지 않는다. 빈 Doctor 답변은 호출 200회에는 포함되지만 토큰 예산과 Doctor 비용에서는 제외된다. 공식 session()의 events에 의존하지 않고 대화·행동·응답 이력을 InteractionState에 유지한다.

Doctor는 `client.chat()`에서 model을 생략해도 현재 지정 모델로 연결된다. `reasoning_effort`는 low·medium·high를 사용하며 temperature는 전송해도 무시된다. 추론 토큰이 max_tokens에 포함되므로 실제 파싱 결과와 남은 토큰 예산을 보고 출력 한도를 판단한다. 현재 소스는 model을 명시하고 temperature는 생략한다. Doctor 표현은 low·최대 1,024토큰, Gateway 구조화는 medium·최대 2,048토큰이며 남은 출력 예산에 맞춰 낮춘다. 실제 Luna 응답의 형식·품질은 미검증이다. [Doctor 변경 공지](https://nova.snubhai.org/qna/)

최신 가이드는 제공자 응답 시작 한도를 180초, 새 SDK 기본 대기 시간을 240초로 설명하며 `REQUEST_PENDING`(HTTP 503/409)과 `PROVIDER_UNAVAILABLE`에는 같은 request_id를 유지한 재요청을 안내한다. 보존 SDK 1.0.1의 기본 120초는 수정하지 않는다. 애플리케이션 전송 경계가 최대 240초와 남은 시간·제출 여유로 호출 대기를 제한하고 원래 timeout을 복원한다. 재전송은 같은 요청으로 기록하여 턴·호출·사용량을 중복 계산하지 않는다. 합성 복구와 실제 서버 복구는 별도 검증이다. [요청 대기·문제 해결](https://nova.snubhai.org/docs/)

개발용 create_sample은 팀당 KST 하루 100개, 제출 후 샘플 검증은 별도로 하루 10회, 공식 평가는 팀·단계별 하루 1회다. 세션 종료·만료로 생성 횟수가 돌아오지 않는다. 세션 밖 성공한 gpt-6-luna 호출은 model 생략 여부를 포함해 하루 1,000회로 합산하고 gpt-6.1-sol은 100회다. 증례 안 Doctor 호출은 이 일일 호출 한도와 별도로 증례별 한도를 적용한다. SNOMED 준비의 두 단계는 팀 일일 호출 한도를 공유하며 다른 팀원의 사용량은 자동 조회할 수 없으므로 실행자가 잔여량을 선언한다. [개발 한도](https://nova.snubhai.org/docs/)

## 최소 데이터·입출력 계약

| 객체 | 소유 정보 |
|---|---|
| CaseState | 구조화된 S/O/A/P, diagnosis, 질환/증상 종류와 근거 ID |
| SessionContext | 현재 내부 세션, 초기화 여부, 세션별·전역 예산과 마감 |
| DifferentialState | 후보·Pattern·Feature 연결, 점수·순위와 기록 참조 |
| QuestionPlan | 기록 참조, 행동 종류, 실행 순서·삭제 우선순위·준비 문구 |
| InteractionState | 전체 원문 대화·역할별 모델 기록·대기 행동·전달 이력·복구·제출 결과 |

SOAP 항목은 id·scope·status·value·출처 참조를 가진다. status는 unasked/done으로 처리 여부만 나타내며, value의 present/absent/uncertain/unknown은 임상 의미를 구분한다. 모른다는 답도 done으로 닫을 수 있으나 음성으로 바꾸지 않는다. 대상·현재/과거·가족력·관찰·에피소드와 정정을 보존한다. 수치·단위·시간은 원문에 남기며 근거 없는 범주를 추정하지 않는다.

InputInterpreter는 현재 응답, 실제 전달된 문장, InterviewPlanner의 구조화된 질문 의도, 전체 한국어 대화, 기존 관찰과 허용 용어를 함께 읽는다. 정확한 현재 답변 인용과 유효한 대화 context_refs를 검증한다. Doctor의 말·교육을 환자의 양성 소견으로 바꾸지 않는다. Doctor가 표현한 질문의 짧은 답은 원래 템플릿으로 자동 분류하지 않는다. Python 단축 처리는 긍정형 존재 질문으로 명시된 준비 문구와 모름·교육 확인에만 적용한다. 해석 실패는 원문·문제를 보존하고 제한된 명료화를 허용한다. 실제 EXAM 없이 O.exam 소견을 만들지 않는다.

InteractionState는 증례별 실제 전달 문장·환자 답·턴·요청 ID·질문 항목을 보존한다. dialogue()가 두 역할에 같은 전체 대화 뷰를 제공하며 최근 네 로그로 자르지 않는다. 실패 생성·미전송 문구·사용량·전송 오류는 별도 실행 기록에 둔다. PreparedResources나 모델 객체에 증례 기억을 누적하지 않는다. Doctor 프롬프트는 ONTOWARD_DOCTOR_PROMPT, Gateway는 ONTOWARD_PARSER_PROMPT, 문구는 ONTOWARD_TEXTS로 config 내부 파일을 선택한다. 모든 노드 갱신을 검증하며 분기에는 모델을 호출하지 않는다.

## SOAP 기록과 최종 제출

최종 결과는 `client.diagnose(note=..., diagnosis=...)`로 제출한다. 화면·stdout·파일은 공식 제출을 대신하지 않는다. D12에 따라 SDK 1.0.1의 15개 SOAP 문자열 필드와 별도 주진단을 전송 계약으로 사용한다.

| 제출 항목 | 필수 필드 | 내용 |
|---|---|---|
| S | `cc`, `hpi`, `pmh`, `fh`, `sh`, `ros` | 주호소, 현병력, 과거력·약물·알레르기, 가족력, 사회력, 계통 문진 |
| O | `exam`, `tests` | 받은 진찰·검사 소견과 획득 턴; 초기 활력징후는 초기 정보로 표시 |
| A | `evidence`, `differential` | 판단에 사용한 문진·신체진찰 소견 목록과 중요한 감별진단 |
| P | `tests`, `treatment`, `disposition`, `follow_up`, `education` | 추가 검사, 치료, 처치 결정, 추적·경고 증상, 교육 계획 |
| 별도 값 | `diagnosis` | CaseState.diagnosis의 비어 있지 않은 주진단 하나 |

모든 SOAP 칸은 문자열이고 내용이 없는 칸은 빈 문자열로 둔다. 단, 기록 전체를 빈 문자열로만 채우지 않는다. 주진단은 CaseState.diagnosis에 유지하고 별도 diagnosis 인자로 비어 있지 않은 문자열 하나를 보낸다. note.A에는 evidence·differential만 넣는다. 누락·추가 필드와 잘못된 자료형은 제출 전에 거절한다. A.evidence에는 실제로 확보하고 판단에 사용한 문진·신체진찰 소견을 간결하게 목록화하며, 지식 출처나 내부 사고 과정으로 대신하지 않는다. 미확인·미시행 항목은 근거로 채우지 않고 원문·획득 턴은 InteractionState에서 추적하고 CaseState는 출처 ID를 참조한다.

공식 안내 표와 제출 예제는 주진단을 별도 diagnosis 값으로 보내도록 안내한다. 사용자는 D12에서 SDK 전송 형식을 선택했다. SDK를 수정하지 않으며 note.A.diagnosis를 추가하지 않는다. 문서·코드의 일치는 공식 서버 수락을 검증한 결과와 구분한다.

예선의 `O.tests`는 빈 문자열이며 향후 필요한 검사와 이유는 `P.tests`에 쓴다. 기록 전체는 UTF-8 100,000바이트, 주진단은 500바이트까지이며 30자 대화 한도는 기록에 적용하지 않는다. 전송 문자열과 기록 크기를 검증한다. 형식 오류는 한 번 재구성하며 서버 INVALID_RECORD_FIELDS 복구는 새 요청 ID를 사용한다. 제출 응답 completed로만 정상 종료를 확인한다. [기록 작성·크기 규칙](https://nova.snubhai.org/docs/)

음성·없음은 질문·확인 또는 제공된 결과가 있을 때만 기록한다. 미확인은 `Allergy ( )`처럼 남기고, 미시행 진찰·검사와 향후 계획을 실제 결과로 채우지 않는다. 수치·단위·참고범위는 환경이 제공한 것을 보존한다. S·O의 사실은 관찰과 출처·턴으로, A·P의 판단과 계획은 해당 사실과 지침 근거로 추적한다. 내부 사고 과정 전문 대신 사실과 판단을 연결하는 간결한 근거를 작성한다.

교육 계획을 기록하는 것과 환자에게 실제 설명하는 것을 구분한다. 필요한 설명·공감·추적 및 경고 증상 안내는 종료 전에 SAY로 전달하고, 전달 내용과 응답을 증례 상태에 남긴다. 시간·턴 부족으로 설명하지 못한 내용을 설명 완료로 기록하지 않는다. 설명 행동을 더 실행할 수 없으면 준비된 교육 계획과 이미 전달한 이력을 보존하고 미질문 항목은 예산 정책에 따라 삭제한 뒤 기록·진단 제출을 마친다.

## 지식 준비와 검색

자료 준비는 제공 원본에서 임상 관계와 계획 근거를 추출·검토하여 RDF 지식으로 만드는 후속 작업이다. 제공받은 원본 패키지는 assets/에 보존하며 D12의 수정 없는 SDK 실행 사본만 복제를 허용한다. `Dev/`는 제출 전 추출·후보 검증·RDF 생성·묶음 구성 코드와 프롬프트를, `submission/`는 제출 에이전트와 실행 그래프 조회를, `data/`는 출처·판본·라이선스와 지속 응답·검토·준비 결과·생성 산출물을 맡는다. `Tmp/`는 삭제 가능한 실행 입력·초안이다. Dev·Tmp는 루트 상태에 기록하며 운영 상태는 루트·submission·data 세 범위만 유지한다.

### 1단계: SNOMED CT에서 어휘집 확장

입력은 허가받은 International Edition RF2 Snapshot을 수동으로 보관한 `assets/snomed/`이다. 자동 다운로드를 하지 않는다. Concept, Description, inferred Relationship, English Language Refset, Module Dependency Refset을 준비용 SQLite에 적재하고 SCTID를 문자열로 유지한다. 같은 구성요소의 최신 행을 먼저 선택한 뒤 활성 여부를 적용한다. 같은 ID·유효 날짜의 충돌, 혼합 판본, 미래 행, 누락된 의존 모듈은 거부한다. 릴리스 날짜·모듈 의존성·언어 refset과 각 파일의 SHA-256을 기록한다. Concrete Values가 있으면 정확한 출처 행으로 보존하되 범주형 Feature로 바꾸지 않는다.

기존 일곱 객체 유형과 2026-10-12 승인한 510개 영어 어휘는 시드로 사용하며 확장 상한으로 삼지 않는다. 로컬 정확 일치와 계층 근거를 우선하고, 모호한 어휘나 새 후보에만 모델을 쓴다. 모델은 제공된 SCTID 후보를 선택하거나 미연결·제외로 처리할 수 있고 새로운 SCTID를 작성하지 않는다. Symptom과 ExamFinding, Test와 ExamMethod는 semantic tag나 계층만으로 자동 판정하지 않는다. 복합 소견은 기본 Target과 실제 근거가 있는 수식 정보로 분해한다. 신규 어휘 URI는 검증된 SCTID에서 결정론적으로 만들며 기존 승인 URI는 보존한다. 버전·해시 기반 registry를 만들고 사람이 모든 항목을 선택·제외한 뒤 2단계 입력으로 고정한다.

### 2단계: SNOMED 표현을 Ontoward 스키마로 변환

Python은 `M is-a* T`와 `M due-to D`, `M associated-with D`, 또는 `M is-a* D` 및 `M is-a* T`의 세 경로로 Pattern 후보를 찾는다. 직접 관계 ID와 다단계 계층 경로를 유지하고 질환 하위 유형 근거를 상위 질환의 직접 근거로 승격하지 않는다. `due_to`는 선택한 변환 정책에 따라 Pattern에 `importance="characteristic"`을 부여하며 RF2 `characteristicTypeId`는 사용하지 않는다.

모델은 제시된 Disease·Target·원천 명칭·Relationship ID·Description ID와 고정 registry 안에서 Feature를 대응한다. Feature는 Target을 표현하는 원천 개념 `M`의 관계와 명칭에서만 얻는다. 질환의 위치·경과·중증도를 모든 Target에 복사하지 않는다. 각 출력은 실제 source ID와 관계 또는 정확한 Description 부분 문자열·문자 위치로 검증한다. 모든 입력 packet에 처리나 제외 결과를 요구하며 응답 일부를 삭제해 통과시키지 않는다.

같은 Disease–Target의 호환 가능한 Feature를 기본 Pattern에 병합하고 근거 ID를 모두 보존한다. 서로 상충하거나 명시적으로 다른 profile은 결정론적 variant Pattern으로 분리하고, 불명확한 경우 미해결로 남긴다. 생성된 Feature의 `clinicalRole`은 자동 부여하지 않는다. 숫자·단위·비교 연산자는 준비 자료에 보존하고 현재 범주형 RDF로 임의 변환하지 않는다. 표현할 수 없는 필수 조건을 버리면 의미가 넓어지는 전체 관계는 제외한다. ExamFinding은 검토된 `detectedBy`와 유효한 `examRequestText`가 확보되지 않으면 preview에서 제외한다.

### 준비용 모델 실행과 산출물 경계

도구는 `Dev/ontology/snomed/`의 import, vocabulary expansion/freeze, projection, extract, validate, preview export 및 verify 명령으로 구성한다. NOVA 호출은 기본 dry-run이며 `--live` 실행에만 세션 없는 Client, `NOVA_DEV_KEY`, 명시적인 일일 상한과 팀 잔여량을 사용한다. 모델은 `openai/gpt-6.1-sol`, medium, 4,000 출력 토큰, 최대 5 packet/호출이다. 가이드라인·Doctor 모델의 `gpt-6-luna`와 별도 역할이다. 실행 간 KST 호출 장부·입력 해시 캐시·요청 ID·원응답·사용량을 보존한다. 자동 재시도, 모델 전환, 응답 수정, 자동 재개는 하지 않는다. timeout 등 완료가 불명확하면 중단한다.

SQLite, registry, packets, 요청·원응답, 검토와 preview Turtle·manifest는 `data/preparation/snomed/`에 보존한다. preview 검증은 기존 `ClinicalKnowledge.validate_graph()`와 역방향 Target 조회를 사용한다. preview는 임상 승인이나 제출 knowledge admission이 아니며 `submission/`으로 자동 복사하지 않는다. 현재 작업 완료 범위는 도구·실행기·dry-run·합성 RF2 오프라인 검증까지다. 실제 RF2 커버리지, NOVA 응답 품질, 실제 모델 호출과 임상 및 제출 수용은 확인되지 않았다.

### 보존된 기존 가이드라인 준비 결과

가이드라인 기반 후보·승인 기록·원응답·파일럿 결과는 기존 source identity와 그대로 보존한다. 해당 추출 경로는 새로운 기본 작업이 아니며 자동으로 재개하지 않는다. SNOMED 결과를 보고 가이드라인 보완이 필요하다고 판단되면 별도 요청의 입력·목표·호출 한도를 먼저 정한다.

### 기본 온톨로지와 임상 지식 모델

기존 문헌 준비 모델인 [Pydantic 모델](Dev/ontology/models.py)과 [기계용 어휘](data/ontology/extraction-vocabulary.json)는 보존된 가이드라인 작업물로 유지하며 SNOMED의 어휘 확장 상한이나 registry로 사용하지 않는다. 새 RF2 근거·용어 후보·패턴 후보용 별도 Pydantic 모델과 JSON Schema는 `Dev/ontology/snomed/`에서 만들고, 데이터셋별 해시와 결과는 `data/preparation/snomed/`에 둔다. 두 준비 경로 모두 기존 v4.2 runtime RDF 계약을 따른다.

[오프라인 도구](Dev/ontology/tools.py)는 카탈로그 상대 문서 경로·파일 SHA-256·허용 줄 범위로 프롬프트를 만들거나 응답을 검증한다. 관계·Feature별 정확한 인용과 절 맥락을 연결하고, 구조·어휘·근거 실패 시 전체 응답을 거부한다. 새로운 대상·속성·승인 값 조합은 문헌 근거가 있는 후보로 허용하지만 candidate_validated는 형식과 인용 검증만 의미한다. 임상 정합성·동의어 대응·필수 적용 조건·RDF 수용은 별도 검토가 필요하다.

[기존 영어 추출 지침](Dev/ontology/extraction_prompt.md)은 저장된 문헌 후보 검증의 일부로만 유지한다. SNOMED 신규 prompt는 실제 RF2 packet과 고정 registry 밖의 개념이나 관계를 추론하지 않으며 근거가 없는 정보·표현 불가능한 필수 조건을 제외한다. 준비 JSON 검증은 임상 정합성·검토·RDF admission을 대신하지 않는다.

| 개념 또는 관계 | 의미 |
|---|---|
| `Disease` | 진단 후보로 다룰 질환 |
| `Symptom` | 환자가 진술할 수 있는 구체적인 임상 주호소; 통증은 ChestPain·AbdominalPain·Dysuria 등으로 구분 |
| `FindingAttribute`·`AttributeValue` | 증상 속성과 재사용하는 범주형 값; 위치는 평면 구조 |
| `BodySystem` | 비배타적 문진 분류; 질환 후보 필터로 사용하지 않음 |
| `ContextFactor` | 과거력·노출·가족력 등의 맥락; 분류는 contextType 문자열 |
| `ExamFinding`·`ExamMethod` | 신체진찰 소견과 구체적 동작; detectedBy와 examRequestText로 연결 |
| `ClinicalPattern`·`ClinicalFeature` | 질환별 단일 Target 프로필과 그 관찰의 원자적 속성·상태 조건 |
| `Test` | SOAP P.tests의 검사 계획 대상; 현재 진단 추론에서는 사용하지 않음 |
| `hasPattern`·`hasFeature` | 질환의 Pattern과 0개 이상의 부분 매칭 Feature; 자동 AND 규칙이 아님 |
| `presentsAs` | 유지하는 선택적 관계; v4.2 후보 검색의 필수 경로가 아님 |
| `targets`·`onAttribute`·`expectsValue` | Pattern의 단일 Symptom/ExamFinding Target과 Feature의 속성·기대 값 |
| `importance`·`clinicalRole` | 독립적으로 사람이 검토하는 Pattern 중요도와 Feature 역할 |
| `hasSupportingContext` | 패턴 밖의 지지 맥락; 부재를 반대 근거로 사용하지 않음 |
| `evaluatedBy` | SOAP Plan 전용 질환–검사 관계 |
| 명칭·동의어 | 언어를 보존한 표현과 공통 개념 URI |

기본 구조는 [스키마](data/ontology/schema.ttl)와 [기초 어휘](data/ontology/vocabulary.ttl)에 작성한다. v4.2는 클래스 11개, 객체 관계 12개, 데이터 속성 6개를 사용하며 URI는 `urn:ontoward:`로 통일한다. 질환·패턴·특징·맥락 요인·진찰 소견·검사 인스턴스의 제출 임상 관계는 후속 추출·검토로 채운다. 전체 규칙은 [온톨로지 계약](data/ontology/AGENTS.md)과 D08을 따른다. RDFS 선언 자체는 cardinality나 선택 타입을 강제하지 않는다.

통증은 ChestPain·AbdominalPain·Headache·BackPain·Dysuria 등 일반적인 임상 주호소 단위의 구체적인 Symptom으로 구분한다. RightLowerQuadrantPain 같은 세분 노드는 추가하지 않으며 우하복부 통증은 AbdominalPain과 확인한 Location=RightLowerQuadrant로 표현한다. 위치는 평면 구조이고 확인되지 않은 Abdomen을 자동 추가하지 않는다. 같은 에피소드에서 넓은 위치와 세부 위치를 각각 확인했다면 출처와 함께 병렬 보존한다. 양상·시간·유발·악화 요인은 기존 속성을 사용하고 별개 에피소드의 정보를 합치지 않는다. ChestPain의 음성은 AbdominalPain 등 다른 증상의 음성으로 확장하지 않는다.

Dysuria·Odynophagia·Dyspareunia·Dysmenorrhea는 각각 독립적인 Symptom으로 두고 명칭에 담긴 발생 상황과 추가 확인한 속성을 보존한다. 기초 어휘에는 선택한 통증 개념 19개와 기존 통증 속성 13개 연결을 유지한다. 승인된 목록에 새 BodySystem 값이 지정되어 있지 않으므로 해당 분류는 후속 어휘 수용 계약에서 정한다. 일반 Pain이나 Urination 값은 기초 어휘에 두지 않는다. 승인된 나머지 항목의 Turtle 반영은 별도 수용 작업으로 진행한다.

환자 원문, 확인한 위치·상황, 정규화한 증상과 그 불확실성을 같은 observation·episode의 출처와 함께 보존한다. 문진·진찰 근거로 해석을 갱신하고 정정 전 원문을 유지하며, 진단 후보에 맞춰 증상을 바꾸지 않는다. 미특정 통증은 미해결 원문으로 남겨 부위·상황을 확인한다. 근거가 있는 복수의 미확정 증상 해석은 후보 검색 합집합에 사용할 수 있지만 같은 관찰을 여러 확정 증상이나 독립 지지 근거로 중복 계산하지 않는다. 예산이 부족하면 기존의 근거 제한 최종화 경계를 따른다.

한 질환은 문헌이 각각 뒷받침하는 여러 증상 Target의 대안 Pattern을 소유할 수 있다. 예를 들어 StableAngina_ChestPainPattern은 ChestPain을, StableAngina_AbdominalPainPattern은 AbdominalPain을 Target으로 하는 구조를 사용할 수 있다. 이 예시는 구조 설명이며 현재 임상 지식으로 생성하지 않는다. 각 Target에서 독립적으로 질환 후보를 조회하고 모든 Pattern의 동시 일치를 요구하지 않는다. BodySystem으로 질환 후보를 제한하지 않는다. 문헌상 대안적인 질환 표현과 환자 표현의 정정을 구분하며 표현 오류를 보완하려고 근거 없는 질환–증상 관계를 추가하지 않는다.

각 Pattern은 질환 하나와 정확히 하나의 Symptom 또는 ExamFinding Target을 가진다. Feature는 0개 이상이며 각 Feature는 Pattern 하나에서 Target을 상속하고 직접 targets를 갖지 않는다. 속성 조건은 onAttribute·expectsValue를 유효한 쌍으로 두며, 상태 조건은 선택적 expectedStatus=present/absent로 표현한다. 값 쌍이나 상태 조건이 없는 빈 Feature를 만들지 않는다. Test·ContextFactor는 Pattern Target이 아니다. 정확한 수치·기간·시점은 환자 상태에서 관리하고 수치 임계값은 추가하지 않는다.

Pattern의 선택적 importance=characteristic과 Feature의 선택적 clinicalRole=supportive/characteristic/opposing은 사람이 검토하여 독립적으로 부여한다. 미지정은 낮은 중요도가 아니며 기대 부재와 반대 역할을 혼동하지 않는다. 문헌 언급 횟수·자동 중요도·검증되지 않은 복합 증상 가산점은 사용하지 않는다. Selectivity는 완성된 그래프의 Target별 질환 연결 분포에 기반한 후속 기능이며, 현재 스키마 선언·수식·자료형·반영 비율을 정하거나 초기 실행 조건으로 삼지 않는다.

후속 조회는 관찰한 증상·진찰 소견에서 Pattern targets와 hasPattern을 역방향으로 따라 질환을 찾고, 동일 에피소드의 관찰과 Feature를 비교한다. 결과는 matched·contradicted·unknown을 구분한다. 미확인·관계 부재는 unknown이며 범주 값이 다르다는 이유만으로 반대 근거를 만들지 않는다. contradicted는 같은 관찰에서 명시적으로 양립할 수 없는 조건이 확인된 경우에만 사용한다. 역할은 실제 매칭된 조건을 기준으로 해석하며 매칭·순위·다음 행동은 앱의 책임이다.

관계별 원본 경로·절·적용 조건·출처 메타데이터·상충 내용·검토 기록은 data의 준비 자료에서 보존하며 실행 그래프에 출처 노드를 넣지 않는다. 원본은 `assets/guidelines/`에 유지하고 [경로 목록](data/catalog/guideline_paths.txt)은 원본 확인을 위한 경로만 담는다. 파일명이나 이 목록만으로 provenance 검토를 완료했다고 판단하지 않는다. Source·ClinicalClaim·Evidence·SUPPORTED_BY와 환자 상태·SOAP·점수·워크플로 노드는 도입하지 않는다. SOAP A.evidence는 주진단 판단에 사용한 실제 문진·신체진찰 소견 목록이다. 검사 외 치료·처치 결정·추적·교육 계획의 구성은 후속 프로그램 책임이며 이를 위한 새 온톨로지 노드를 이번에 추가하지 않는다.

ExamMethod는 방법 URI를 내부 식별자로, `examRequestText`를 실제 요청 문장으로 사용한다. 후속 앱은 `ExamFinding → detectedBy → ExamMethod → examRequestText`를 조회하고 단일 동작·NFC 1–30 코드 포인트 조건을 검증한 뒤 `client.exam(text)`로 실행한다. SDK에는 공식 진찰 코드 목록이 없으며 요청 문장의 존재는 서버 인식이나 실제 결과를 뜻하지 않는다. examAction 코드를 선언하지 않고 실제 거절·결과를 앱에서 처리한다.

### 문서별 결과와 출처별 제출 묶음

확인한 코퍼스는 16개 출처 그룹의 임상 Markdown 15,904개, 597,185,304바이트다. 이는 원본 규모이며 RDF의 크기·triple 수나 실행 메모리의 측정값이 아니다. 문서별 결과를 유지하면 실패·검토·수정 범위를 구분할 수 있고, 출처별 묶음은 제출 파일 수를 줄인다. 단일 최종 파일로 전체 결과를 고정하지 않는다.

현재 data/ontology/의 스키마·기초 어휘, data/catalog/의 원본 경로 목록과 data/provenance/의 출처 식별을 유지한다. 새로운 문서별 결과·검토·지식 묶음의 개발 경로와 형식은 준비 계약을 채택할 때 정한다. 현재 준비 산출물 디렉터리나 빈 지식 묶음을 만들지 않는다.

| 위치 | 역할 | 제출 포함 |
|---|---|---|
| Dev/codex/ | Codex CLI 설정·인증 준비 | 제외 |
| Dev/packaging/ | 독립 압축 도구 | 제외 |
| Tmp/codex/ | 현재 작업의 임시 출력 | 제외 |
| Tmp/packaging/ | 생성 ZIP | 제외 |
| data/ontology/ | 준비용 스키마·기초 어휘 | 직접 포함하지 않음 |
| data/ontology/vocabulary-candidates.md | 사용자 검토용 영어 Disease·Symptom 자연어 후보 | 제외 |
| data/catalog/·data/provenance/ | 원본 탐색·출처 식별 | 제외 |
| `submission/knowledge/*.ttl` | 완성된 실행 스키마·어휘·임상 관계 묶음 | 포함 |
| `submission/knowledge/manifest.json` | 제출 내부 자산의 상대 경로 목록 | 포함 |
| 필요한 `submission/knowledge/schema.json` | JSON 구조 검증용 스키마 | 포함 |

승인된 결과가 있는 기존 출처 그룹별로 묶음을 만든다. 새로운 진료과 분류 체계는 도입하지 않는다. 문서별 실패·검토 대기·제외·승인 상태와 원본 식별은 데이터 준비 기록이 관리한다. 추가 분할은 실제 산출물 규모를 측정한 뒤 별도 작업에서 판단한다. 운영 상태는 기존 세 범위에만 유지한다. 준비 산출물 형식이 정해지기 전 실행 자산을 임의로 생성하지 않는다.

### 대회 실행: 준비된 그래프만 조회

`prepare()`는 manifest에 명시할 스키마·기초 어휘와 제출 임상 묶음 전체를 하나의 RDFLib `Graph`에 로드한다. 증례 접근이나 원문 추출 없이 준비 알림 전에 실행 자원을 구성하고, `consult(client, resources)`에서 출처 그룹을 가로질러 임상 관계를 조회한다. data의 원본 경로 목록과 준비·검토 기록은 실행 그래프의 입력이 아니다. 여러 파일을 모두 로드하므로 파일 분할 자체를 메모리 절감의 근거로 취급하지 않는다. 첫 MVP에서는 선택적·지연 로딩, Dataset·Named Graph, OWL 추론, 임베딩·벡터 검색이나 별도 그래프 서버를 도입하지 않는다.

검색 계층의 최소 인터페이스 책임은 다음과 같다. 후속 코드의 구체적인 자료형은 `submission/`가 구현한다.

| 조회 기능 | 반환할 내용과 경계 |
|---|---|
| 개념 후보 연결 | URI·명칭 후보와 연결 불확실성; 복합 표현의 증상·속성을 보존하고 미연결 원문 유지 |
| 증상 속성 조회 | 증상에 연결된 속성과 적합한 범주 값; 연속 값은 환자 상태에 유지 |
| 계통과 증상 조회 | 기존 inSystem·BodySystem으로 주호소 계통의 ROS 범위를 정하며 질환 후보에는 계통 필터를 적용하지 않음 |
| 질환 후보 조회 | 관찰한 Target에서 Pattern과 Disease를 역방향 조회한 합집합; presentsAs 의존·확진·확률·계통 필터 없음 |
| 패턴·감별 특징 조회 | Pattern의 단일 대상·수동 중요도와 Feature의 선택적 상태·역할·속성 값; 부분 매칭하며 다른 에피소드를 합치지 않음 |
| 지지 맥락 조회 | 질환에 직접 연결된 ContextFactor; 부재를 반대 근거로 사용하지 않음 |
| 진찰 방법 조회 | detectedBy로 연결된 방법 URI와 examRequestText; 자동 실행·실제 결과가 아님 |
| 검사 계획 조회 | evaluatedBy와 Test를 SOAP P.tests에서만 조회; 진단 추론·다음 진단 행동에서는 사용하지 않음 |

고정된 조회 함수와 필요시 사전 정의한 질의를 사용하며 LLM이 임의 SPARQL을 생성하게 하지 않는다. 한국어 원문과 번역·개념 연결의 불확실성을 유지한다. 중요한 새 관찰이나 후보 변화가 있을 때 조회와 후보 판단을 갱신한다. 조회된 연관·특징 표시는 확률이 아니며 관계의 부재를 질환 배제나 음성 소견으로 해석하지 않는다. 임상 출처별 상충 내용과 적용 조건은 제출 전 data의 외부 준비 기록에서 검토한다.

HPI 이후의 후보 우선순위·다음 행동·최종 진단은 실제 관찰과 세션 예산을 함께 검토하는 앱의 책임이다. 근거가 있는 감별 가치, 미확인 여부, 이미 받은 답변·거절 이력, 남은 턴·시간을 고려해 행동 하나를 선택한다. HPI에는 고정 슬롯 정책을 적용한다. 그래프에 연결되었다는 이유만으로 질문·진찰·검사를 자동 실행하지 않는다.

지침별 출처·라이선스를 유지하고 대회 목적의 비상업적 이용 조건을 따른다. Turtle로 표현한 관계·계획 근거·발췌·번역 등 파생 자료를 제출물에 포함할 때 문서별 조건을 먼저 확인한다. CC BY-ND·BY-NC-ND·공공누리 제4유형 등 변경본 배포가 금지된 자료의 변환본은 제출물에 넣지 않는다. RDF 형식으로 바꾸는 것이 이용 조건을 없애지 않는다. 원본 ZIP의 공식 SHA-256을 압축 해제 폴더의 검증 결과로 대신하지 않는다. [제공 자료의 조건](assets/guidelines/README.md)

### 후속 단계: BODHI-S와 선택적 출처 보강

SNOMED CT International Edition 직접 추출이 현재 준비의 기본 경로다. 개념 연결이 실패해도 환자 원문과 현재 런타임의 검색 후보 계약을 유지한다. BODHI-S는 별도 사용자 선택에 따른 후속 입력이며 SNOMED registry 확장이나 검증을 대체하지 않는다.

BODHI를 도입할 때의 첫 범위는 다음 세 BODHI-S CSV다.

- `nodes_condition.csv`: 원본 질환·임상 항목과 유형.
- `nodes_symptom.csv`: UUID로 식별하는 증상 변형과 수식 정보.
- `edges_present_in.csv`: 증상 UUID와 원본 condition 식별자를 잇는 연관 근거.

BODHI의 증상 변형은 동일한 SNOMED 루트 개념을 공유할 수 있다. UUID, 개별 SNOMED 표기 값, 루트 개념, 기간·위치 등의 수식 정보를 보존한다. 원본의 SNOMED 표기 값은 비어 있거나 검증되지 않았을 수 있으므로, 채택한 SNOMED 판본과 대조한 개념 연결과 구분한다. Condition 유형을 확인하여 가족력·생활습관 같은 항목을 무조건 최종 질환으로 취급하지 않는다. [BODHI 원본과 스키마](https://github.com/eka-care/BODHI)

SNOMED CT의 동의어와 계층은 개념을 식별하고 확장 범위를 정하는 데 사용한다. 질환의 모든 하위 개념을 그 질환의 증상 목록으로 해석하지 않으며 Disease–Target 연결은 위의 명시된 관계·계층 경로에서만 생성한다. 이후 BODHI 연결은 별도 원천으로 구분하고 해당 원천에 있는 relation scope만 보강한다. [SNOMED 지식 표현 범위](https://docs.snomed.org/snomed-ct-specifications/snomed-ct-editorial-guide/readme/snomed-ct-introduction/knowledge-representation)

후속 보강 흐름은 `환자 표현 → 용어 후보 → 검증된 개념 연결 또는 미연결 원문 → BODHI 연관 조회 → 감별 후보와 미확인 항목`이다. 개념 연결이 실패해도 원문과 추론 후보를 보존한다. 자료에 없는 연결을 질환 배제 근거로 사용하지 않는다.

후속 자료도 공통 개념 URI와 원본 식별·검증된 연결을 구분하여 RDF 지식에 반영한다. 진료 중 조회 경로는 RDFLib로 유지하며 SNOMED RF2나 문헌 원문을 런타임 검색하지 않는다. 환자 입력 언어, 현재 SNOMED 기본 경로, 지식 표현·검색·산출물 구조는 D04·D05·D07을 참조한다.

## 제공 샘플·벤치마크의 역할

| 자료 | 사용할 단계 | 경계 |
|---|---|---|
| 시작 패키지 | SDK·prepare/consult·공식 샘플 연결의 기준 | 기본 에이전트의 실행·성능·재시도 적합성은 검증하지 않음 |
| 공개 증례 C01·C03·C10 | 초기 정보 입력과 실행 후 누락 검토 | 대본·진찰표·모범 기록을 Doctor의 사전 지식이나 정답 검색에 넣지 않음 |
| 개발 키트 | 후속 로컬 시뮬레이션·디버깅 | 모델·판정·복구가 서버와 같다고 가정하지 않으며 채점·인터넷 차단을 검증하지 않음 |
| AgentClinic-MedQA | 후속 문진·진찰·진단 흐름 자체 평가 | TEST 결과는 예선 실행에서 제외하고 정답은 검토 측에 분리 |
| DDXPlus | 후속 단일 질문 선택·정보 획득 자체 평가 | 증상 코드와 답을 문진으로 연결해야 하며 진찰·검사는 제공하지 않음 |
| ACI-Bench | 후속 대화→SOAP 사실 일치·누락 검토 | 별도 정답 진단 라벨이 없고 화자 표기 오류 가능성을 고려 |

벤치마크는 영어·다른 형식의 외부 자료이며 대회 평가 증례가 아니다. 한국어 30자 질문에 맞추는 번역·재작성의 출처와 처리 과정을 보존한다. 학습·개발·검토 분할을 유지하고 AgentClinic 기본판/확장판 및 ACI 파생 대화의 중복을 관리한다. 전체 벤치마크를 첫 구현이나 제출물에 일괄 포함하지 않는다. 출처·라이선스·인용은 각 패키지에 유지한다. [공개 샘플 안내](assets/nova-samples-2026/README.md), [개발 키트 안내](assets/nova-devkit/README.md), [벤치마크 안내](assets/nova-benchmarks-2026/README.md)

## 제출환경과 실행 자산

submission/run.py는 workflow/runtime.py의 prepare()와 consult(client, resources)를 SDK run_agent()에 전달한다. prepare()는 읽기 전용으로 사용하는 지식과 텍스트 설정을 PreparedResources에 담고 consult()는 증례별 객체와 새 상태를 조립한다. D13의 Consultation 하나가 다섯 내부 세션을 조정하며 graph.py는 노드·엣지·상태 기반 분기와 deep-copy/Pydantic 검증을 연결한다. Doctor·InputInterpreter·InterviewPlanner·ClinicalReasoner·SubmissionWriter는 각각 환자 행동·입력 사실·질문과 교육·진단 추론·최종 제출을 맡는다. rules/는 불변 한도와 순수 판단, state/는 기존 다섯 상태 모델과 질문·상호작용·사용량 변경 연산, io/는 모델 호출·공식 NOVA 세션·전송 복구를 맡는다. 기존 agents/와 호환 wrapper는 남기지 않는다. knowledge/graph.py의 ClinicalKnowledge는 하나의 RDFLib Graph를 소유한다. import는 API 호출이나 지식 로딩을 수행하지 않는다.

submission/을 런타임 코드의 단일 원본으로 사용한다. 공개 설정인 submission/.env는 ZIP에 포함하고, 같은 폴더의 AGENTS.md·README.md·PROJECT_STATE.md는 제출에서 제외한다. SDK는 assets/nova-starter/nova_sdk.py의 수정 없는 사본이며 버전과 해시는 공모전 출처 기록에 남긴다. 원본 복제 허용은 이 SDK 사본으로 한정한다.

코드 ZIP의 압축 루트에는 run.py와 requirements.txt가 있어야 한다. Dev/packaging/package_submission.py는 package 이미지에 포함되며 입력을 /submission으로 고정한다. Compose package 서비스는 submission/만 읽기 전용으로 연결하여 실행 Python·고정 의존성·공개 .env·config/의 프롬프트와 문구·knowledge/의 필요한 Turtle·JSON만 압축한다. 결과 디렉터리는 Tmp/packaging/만 /output으로 연결한다. root .env, 안내·상태 문서, Dockerfile, Dev·Tmp·원본·추출 중간 결과·캐시는 제외한다. 크기는 압축 50,000,000바이트, 해제 500,000,000바이트, 파일 수는 5,000개 이하다. 심볼릭 링크·경로 이동·중복 경로·암호화를 허용하지 않는다.

제출 의존성은 PyPI의 미리 빌드된 휠을 사용할 수 있는 `name==version` 한 줄 형식으로 고정한다. URL·Git·편집 설치·버전 범위·다른 저장소·소스 빌드는 사용하지 않는다. 의존성 빌드는 제출 버전마다 한 번이며 20분 제한이고 내려받는 휠 합계는 8GB 이하다. 실행 중 인터넷은 차단되고 지정 대회 API만 허용된다. 필요한 자산은 허용된 제출물 또는 제공된 로컬 경로에서 읽는다. 개발 키는 비밀로 유지하고 코드·ZIP·문서에 저장하거나 코딩 도구에 연결하지 않는다. [참가·실행 규칙](https://nova.snubhai.org/rules/), [의존성 오류 한도](https://nova.snubhai.org/docs/)

제출 의존성은 submission/requirements.txt에서 LangGraph 1.2.13, Pydantic 2.14.0, RDFLib 7.6.0으로 고정한다. 루트 Dockerfile은 이 파일을 PyPI 휠로만 설치한다. 추출 도구와 MarkItDown은 제출 의존성에 포함하지 않는다. 기존 ontology-extraction 서비스와 관련 저장소는 별도 준비 환경이며, 그 실행 결과를 제출 환경 검증으로 대체하지 않는다.

공개 설정 submission/.env는 ONTOWARD_KNOWLEDGE_MANIFEST, ONTOWARD_DOCTOR_PROMPT, ONTOWARD_PARSER_PROMPT, ONTOWARD_TEXTS를 선언한다. 기본값은 각각 knowledge/manifest.json, config/doctor.txt, config/input_parser.txt, config/texts.ko.json이다. 실행 환경의 같은 변수값이 우선하며 모두 submission 기준 상대 경로다. settings.py는 manifest/지식은 knowledge 내부, 프롬프트/문구는 config 내부로 제한하고 외부 경로·심볼릭 링크 탈출·상위 디렉터리 폴백을 차단한다. config의 JSON은 고정 질문, 엄격한 답변 어휘, 임상 상태 표시, SOAP 문자열 형식을 담는다. SDK 필드명·상태 코드·RDF URI는 기계 계약으로 Python에 남긴다. 환경값을 적용하려면 prepare()를 다시 실행한다.

지식 manifest는 schema·vocabulary·하나 이상의 bundles와 선택적 questions·plans를 선언하고 각 항목은 submission 기준 상대 path와 SHA-256을 가진다. questions JSON은 속성/대상 URI를 질문 문자열로 매핑하며 {symptom} 자리만 치환한다. plans JSON은 질환 URI별 tests·treatment·disposition·follow_up 문자열과 education 문자열 목록을 담는다. EXAM 문구는 RDF ExamMethod.examRequestText를 사용한다. 없는 질문·임상 관계·계획은 생성하지 않는다. 실제 자산은 제출 내부에 있어야 하며 root data로 폴백하지 않는다. 개발 자격증명은 root .env, 공식 토큰·세션은 실행기 소유이며 공개 문구 설정이 덮어쓰지 않는다.

문서별 추출 파일은 제출에서 제외하고 승인된 지식 묶음과 manifest만 필요한 코드와 함께 구성한다. 원본 약 597.2 MB를 RDF 크기로 간주하지 않으며, 제출 묶음의 실제 압축·해제 크기와 코드 전체 파일 수를 확인한다. 준비 10분과 예선 RAM 8GB 제한은 전체 실행 자원에 적용한다. 대표 추출에서 문서 길이·유형을 나누어 triple 수, Turtle 크기, 전체 로딩 시간, 최대 메모리와 주요 조회 시간을 측정한다. 후속 대표 추출의 수치는 data 준비 기록에 남기며 전체 제출 그래프나 진료 실행 환경의 수용 증거로 일반화하지 않는다.

본선에서는 별도 모델 ZIP 최대 32GB와 PPT/PPTX가 필요하다. `prepare()`에서 `NOVA_MODEL_DIR`의 읽기 전용 모델을 직접 로드하고 `client.chat()`을 사용하지 않는다. 가중치·KV 캐시·실행 메모리를 포함하여 A6000 48GB급 GPU 한 장, CPU 8코어·RAM 32GB 안에서 실행해야 한다. 본선 모델 선택·확보·학습·GPU 검증은 후속 단계이며 이번 작업에서 진행하지 않는다.

## MVP에서 확인할 결과와 책임

첫 MVP에서 확인할 결과는 한 증례에 대해 관찰이 누적되고, 관련 근거가 조회되며, 다음 행동과 최종 진단의 이유를 사람이 따라갈 수 있는 흐름이다. 별도의 성능 수치나 임상 정확도를 이 문서만으로 주장하지 않는다.

HPI는 고정된 정보 슬롯을 처리하고, 그 이후에는 현재 후보 판단을 바꿀 가치가 있는 미확인 항목을 선택한다. 이미 답한 항목을 불필요하게 반복하지 않는다. 최종화에서는 중요한 대안·모순·설명되지 않은 소견을 검토하되 앞선 세션으로 자동 회귀하지 않는다. 예산과 미해결 불확실성을 기록하고 교육·제출을 준비한다.

| 평가 영역 | 배점 | 제품 흐름의 검토 기준 |
|---|---|---|
| 정보수집 | 25 | 필요한 질문·진찰을 실제 수행하고 S·O에 기록 |
| 진단추론 | 15 | 주진단의 공개 5점 척도 판정과 사실에 연결된 근거·감별; 영역 점수 환산은 미공개 |
| 검사·추적 | 10 | 예선의 추가 검사 이유와 추적 계획 |
| 안전 | 15 | 위험 신호 확인, 적절한 처치 결정과 경고 증상 안내 |
| 의사소통 | 15 | 실제 SAY 설명·공감과 환자의 이해 확인 |
| 효율 | 20 | 중복 행동·불필요한 검색·모델 비용 감소 |

이 표는 공개된 평가 영역을 제품 검토에 연결한 것이며 비공개 세부 채점 기준을 재현하지 않는다. 로컬 개발 키트는 채점하지 않는다. 서버 샘플 검증의 참고 점수와 공식 평가 점수도 구분한다. 샘플 검증 없이 리더보드 제출을 선택할 수 있다. 개발 키 sample.py는 비채점이며 제출 ZIP의 샘플 검증은 gpt-6-luna 참고 점수를 제공한다. 공식 평가는 팀·단계별 KST 하루 1회, 예선 5증례를 gpt-6.1-sol로 채점하며 마지막 10증례는 GPT·Claude·Gemini의 평균을 사용한다. 샘플·외부 벤치마크 결과를 공식 성능이나 임상 정확도로 일반화하지 않는다. [평가 단계와 기준](https://nova.snubhai.org/evaluation/)

예선 리더보드 제출은 2026-10-13 오후 KST부터 접수한다. 공개 순위는 팀별 최고 점수이며 동점은 먼저 제출한 팀이 앞선다. 팀이 최종 평가에 선택한 제출과 공개 최고점 순위는 구분한다. 예선 결과로 10팀이 본선에 진출하며, 본선 최종 5팀의 의사 평가와 그 결합 방식은 별도다. 10월 13일 개발 크레딧을 지급액 40,000원으로 복구하고 12:30 이전의 개발 호출·샘플 세션·검증 횟수를 일시 초기화한 것은 해당 날짜의 운영 조치다. 현재 팀 잔액·잔여 횟수·제출 성공은 확인하지 않았다. [운영 공지](https://nova.snubhai.org/qna/), [리더보드 표시 기준](https://nova.snubhai.org/leaderboard/)

### 구현 수용 시나리오

구현 단위를 조립한 뒤 Dev/tests/workflow의 유지 테스트를 프로젝트 dev 컨테이너에서 하나의 오프라인 묶음으로 검증한다. Dev/architecture/WORKFLOW_RULES.md는 실행 규칙과 검증 위치의 색인이다. 리팩토링 전후의 상태 스키마·모델/SDK 요청·질문 순서·사용량·SOAP·종료 의미를 비교한다. 작은 합성 RDF·질문·계획은 임시 제출 복사본의 knowledge 내부에만 배치하며 실제 제출 자산으로 승격하지 않는다.

- 초기 입력 → Doctor 인사·주호소 유도 → HPI → Open Inquiry → 집중 ROS → 후보 검색 → Context → 감별 → 교육 → SOAP → 확인된 제출의 전체 흐름.
- 역할별 프롬프트·호출 기록, 독립 NFC 30자 검증, 2회 재생성·준비 문구·미전달 격리, 실제 질문과 전체 대화의 문맥 참조.
- ROS 계통 합집합·기확인 제외·최대 6개·교차 계통 후보와 명료화 2회·증상 수준 진단·근거 없음의 명시적 실패.
- 동일 요청 ID·payload·턴·사용량 보존, 공유 모델 예산과 응답 처리 여유, 교육 중 새 사실, SOAP 1회 재구성.
- 초기화 전 빈 목록·대기 응답·현재 scope 완료·Context 0점·후보 없음·질문이 남은 선두 후보의 Python 분기와 분기용 LLM 0회.
- CaseState와 QuestionPlan 동시 삭제, Open Inquiry 보존, 삭제 재생성 방지, 확인 사실·대기 행동·교육 계획 보존.
- 중복 가산 방지·정정 재계산·에피소드 분리·Context 음성/미확인·characteristic 가중치·URI 동률·마지막 특징에 따른 순위 변경.
- 엄격한 답과 복합 자유서술, 잘못된 모델 출력, NFC 30/31자, 진찰 거절, TEST 차단, 만료·닫힘·결과 불명, 50번째 응답 뒤 제출.
- 정확한 SOAP 15개 문자열 필드·별도 진단·UTF-8 한도·Doctor 최소 호출·교육 계획과 실제 전달 구분.
- 외부 경로 폴백 차단·누락 manifest 오류·준비 문구 누락·환경값에 따른 문구 변경·SDK 원본과 패키징 경계.
- 최신 D11과 루트·submission·data 상태의 정합화, 병행 추출 결과와 임상 검토 차단 사유 보존.

승인된 임상 실행 묶음과 치료·교육 자산은 아직 준비되지 않았다. 합성 검증은 자산 소비 코드와 전체 흐름을 검증하며 실제 Doctor 품질·임상 정확성·공식 SDK 수락·제출·평가는 별도 미검증으로 남긴다. 추출 재개·코퍼스 확대·외부 호출·커밋·배포를 포함하지 않는다. 구현·검증 관측값은 [제출 상태](submission/PROJECT_STATE.md), 준비 결과는 [데이터 상태](data/PROJECT_STATE.md), 교차 범위 조정은 [루트 상태](PROJECT_STATE.md)에 기록한다.
