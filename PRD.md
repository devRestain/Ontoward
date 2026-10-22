# Ontoward MVP 제품 요구사항

## 목적과 실행 경계

Ontoward는 N.O.V.A. 예선의 모의 환자에게 문진·신체진찰을 수행하고 SOAP 초진 기록과 주진단 하나를 제출한다. 공모전 제출이 프로젝트의 완성 지점이다. 현재 구현은 [D63](DECISION_STATE.md#D63)으로 감별 후보·수용 Assessment·SOAP 감별 개수 제한을 전면 철회하고 병력 주체·정확한 unknown 복구·safety 우선 전달·누적 output 한도를 안정화한다. d50.12의 D61 유한 pass·최소 SOAP·정직한 수신 상태와 독립 그래프 상세 표 50개 한도는 유지한다. D58의 최신 strict 번들·현재 평가 DD Context 질문을 유지한다. [D57](DECISION_STATE.md#D57)의 초기 상세정보 수치 연결·scope·원자 질문 수집, [D55](DECISION_STATE.md#D55)의 strict 번들과 D56 진찰 문구를 유지한다. [D54](DECISION_STATE.md#D54)의 scoped 후보 유입·호출 내 참조·어휘 통합·문서 projection과 직접 연결 문서 우선 순서를 유지한다. D53의 직접 Initiation·최대 다섯 전체 문서·실패 비보충, D52 관계 공유·컨텍스트 재시도 금지와 D61의 실패 작업 pass, D51 입력 복구, D50 정보 보존·호출 병합·순차 실행과 D49 무점수 지식, D48 프롬프트 모듈, D47 객체·사실, D45 공식 행동 예산을 유지한다. 검증되지 않은 과거 DB fallback은 허용하지 않으며 실제 설치 번들의 manifest가 없으면 prepare와 정식 패키징은 knowledge_bundle_not_installed로 실패해야 한다.

진료 중에는 ZIP 내부의 읽기 전용 RDFLib Graph를 사용한다. 원본 RF2·BODHI·DDXPlus·준비 SQLite는 개발 자산이다. 등록되지 않은 질환·관계·질문을 런타임에서 만들지 않는다. 제공 가이드라인 원문은 진단을 고정한 뒤 지정 마운트에서만 읽는다. 실제 모델 품질과 공식 평가는 로컬 실행 증거와 구분한다.

## 기술과 기능 객체

| 구성 | 책임 |
|---|---|
| Python·Pydantic | 현재 사실, 그래프 조건, 실행 계약, 상태 수명, SOAP 직렬화 검증 |
| Consultation 순차 루프 | 한 증례의 입력 수용·행동·세션 이동·최종화 |
| RDFLib·Turtle | manifest에 고정한 v5.0 지식과 읽기 전용 조회 |
| 원본 NOVA SDK | 세션 조회, 지정 모델, SAY·EXAM·DIAGNOSE와 완료 확인 |
| Docker | 의존성·개발·검증·독립 ZIP 환경 |

DoctorEar는 입력 전처리·해석·사실 수용을, 다섯 세션 객체는 세션별 수집·임상 판단·응답 검증을 소유한다. EducationSession이 영어 계획의 준비·검증과 진단 안내·계획 전달 순서·턴 배분·큐 등록·준비 상태를 소유한다. DoctorMouth는 한국어 표현·SAY·EXAM 실행을 소유하며 교육 표현 결과를 반환할 때 전달 큐나 준비 상태를 수정하지 않는다. DoctorBrain은 증례당 하나인 공통 LLM 실행기로서 지정 모델·effort·호출 한도·사용량·전송 오류와 동일 요청 재전송만 담당한다. 모든 호출자에 같은 객체를 주입하며 별도 ModelClient는 없다.

지정 모델은 기존 `openai/gpt-6-luna`다. Ear·Mouth는 medium, 세션의 임상 판단과 영어 P 호출은 high를 사용한다. SOAP 작성에는 LLM을 호출하지 않는다. Consultation은 유일한 생애주기 조정자이고 SubmissionWriter만 SOAP 제출과 DIAGNOSE 완료를 처리한다.

세션 사이에는 다른 세션 객체를 전달하지 않는다. Consultation이 CC 종료 성공 여부와 평가의 현재 revision·chief 일치 및 미고정 상태를 확인한 뒤 ContextFactor에 평가 자료만 전달한다. 평가를 사용할 수 없으면 기본 병력과 준비 불가 사유를 유지한다.

## 환자 정보와 다섯 내부 세션

초기 opening과 제공 vital_signs를 첫 SAY 전에 해석한다. 이미 제공된 주호소를 다시 유도하지 않는다. 별도 인사·공감 SAY 없이 Initiation의 첫 미확인 질문을 바로 제공하며 chief가 없으면 필요한 명료화를 먼저 수행한다. 공감 signal·큐·템플릿·전달 경로·별도 행동 카운터를 두지 않는다.

| 세션 | 수행할 일 | 조건부 문진 목표 / 최대 |
|---|---|---:|
| Initiation | 초기 해석·chief 명료화·onset·course·recurrence·previous care 직접 질문 | 5 / 7 |
| ChiefComplaint | 대표 CC 하나의 적용 가능한 전체 속성·Open Inquiry | 7 / 14 |
| ContextFactor | 기본 병력 다섯 영역·관련 Context 최대 두 개 보호 수집·추가 맥락 | 7 / 9 |
| DifferentialDiagnosis | 집중 ROS·등록 특징·조건·실제 진찰 중 다음 행동 선택·평가 고정 | 3 / 10 |
| Education | 고정 진단 첫 안내·영어 P·한국어 전달; 답변은 대화 기록 전용 | 5 / 10 |

기확인·unknown·not_applicable·자산 차단·예산 중단을 구별한다. 최소 목표를 채우기 위해 반복하거나 미확인을 음성으로 만들지 않는다. 실패 질문은 같은 full scope의 passed 표식으로 마감하며 실제 수신 후 해석 실패만 unknown Answer로 남긴다. 세션별 최대치를 서로 빌리지 않는다. CC의 마지막 가용 슬롯은 Open Inquiry에 보호한다. 집중 ROS는 DD에서 chief의 계통·중복·존재 확인을 지키며 최대 여섯 대상을 기존 10행동 상한 안에서 확인한다. Context 질문 출처는 CC 종료의 유효 Assessment에 든 질환으로 고정하고 수집 중 새 후보로 확장하지 않는다. 유효 CC 평가가 없으면 기본 병력만 수집하고 관련 Context 준비 불가 사유를 남긴다. 기본 병력은 과거력·약물·알레르기·가족력·사회력이다. 환자·보호자 인구학 사실은 병력 완료 근거에서 제외한다. 가족의 과거력·약물·알레르기·사회력은 환자 슬롯을 완료하지 않으며 가족력은 실제 가족 병력의 명시적 사실·부정 또는 실제 전달한 전체 가족력 질문의 답변으로만 완료한다. 환자가 보고한 전체 가족력 부정과 해당 질문의 unknown은 보존하며 다른 목적·주체·인구학 전용 Answer는 완료로 쓰지 않는다.

원문은 DoctorEar의 참조 해석 문맥에 한 번만 보관한다. 정확한 영어 용어·허용 속성 값은 Python이 먼저 연결하고 미해결 임상 진술만 제한된 DB 후보로 정규화한다. 독립 유효 행을 보존하며 문맥과 매핑 각각 기본 1회·복구 최대 1회로 제한한다. 초기 chief 검토는 같은 문맥 복구에 포함하고 매핑 형식·참조·미해결 오류도 같은 한 번에 복구한다. 의미 근거 없이 첫 후보·첫 값을 확정하지 않으며 미해결 내용은 영어·수치·조건·scope를 가진 unbound 사실로 보존한다. 실제 모름을 양성으로 만들거나 측정값만으로 증상 존재를 만들지 않는다.

초기 원문의 전송 정본은 opening과 vital_signs를 구분한 input_segments다. 같은 초기 원문을 input·dialogue에 반복하지 않으며 일반 reply·EXAM의 input은 유지한다. 매핑은 Context가 이미 해소한 note_value 또는 짧은 의미 hint를 normalized_claim으로 함께 읽는다. 어휘 후보는 영어 hint와 한국어 인용 전체의 후보를 통합한 후 제한하며, 각 질의의 최선 별칭 일치만 합산한다. 이 어휘 유사도는 임상 근거 점수가 아니며 무관련 입력은 빈 후보를 허용한다. Target 8/32·속성 2/4·값 8/32와 기존 repair 상한을 유지한다.

첫 입력과 일반 답변에서 명시된 증상의 기간·변화량·의도성·수식어를 같은 증상의 원자 속성으로 분리한다. 이전 체중·현재 체중·감소량을 구별하고 근사값·단위·시점을 보존한다. Context가 검증한 수치는 외부 Mapping에서 다시 생성하지 않는다. Mapping은 빈 dictionary 또는 한 target·attribute의 정확한 `{"use_measurement":true}`만 반환하며 Python이 원래 measurement를 기존 수치 validator에 연결한다. 숫자와 marker의 혼합·1이나 문자열 true·단위 불일치·범주값 대체를 거절한다. 후보는 속성 의미를 확인한 뒤 단위를 검사하며 kg만 같다는 이유로 현재 체중을 감소량에 연결하지 않는다. note_value가 있어도 대상·속성·값 hint와 시점을 meaning에 보존한다.

미매핑 상세도 같은 로컬 anchor의 observation·episode를 보존하며 서로 다른 note ID는 독립 사실로 유지한다. 실제 같은 bound attribute의 상충값 검사는 유지한다. Initiation은 현재 chief의 같은 사람·시점·observation·episode·보고 취득 범위에서 onset·course 등을 판단한다. 발현 후 경과와 개별 발작의 지속시간·측정 구간을 구별하고 duration 전체를 onset으로 바꾸지 않는다. 과거의 안정적 체중을 평생 재발 부정이나 현재 course 완료로 확대하지 않는다.

사실은 주체·가족 구성원·보고자·시점·관찰·episode·수치·단위·polarity·취득 경로·source·turn을 보존한다. 정정은 같은 대상·관찰·주체·시점·취득 범위를 지키며 SAY가 초기 객관 자료나 EXAM을 덮어쓰지 못한다. CaseState.facts의 CaseFact 하나에 정규화된 영어 내용과 수치·조건을 저장하고 선택적 graph_binding에 등록 target·attribute·values·연결 방식을 둔다. 그래프 사용 자격은 현재 같은 사람·시점·observation·episode·취득 범위의 존재 확인에서 계산한다. 매핑 결과와 부가 설명을 중복 사실로 저장하지 않는다. DB에 없는 정보도 같은 정본에 보존한다.

부분 복구는 요청한 statement 또는 demographic 행만 바꾸고 생략된 정상 영역을 보존한다. 검증된 typed age는 Python으로 영문 표기하며 단위·범위·근사 여부를 유지한다. 미매핑 메모의 영문 정규화 실패도 기존 한 번의 행 복구에 포함한다. 정확한 unknown·감사 SAY와 등록 문구·scope가 고정된 affirmative presence 단답만 모델 없이 처리한다. 복합·부정형·병력 domain 질문과 추가 내용은 일반 해석으로 보낸다. 환자 감정 표현도 입력 문맥으로 해석하되 별도 공감 행동을 만들지 않는다.

환자 age·sex·historian은 같은 facts 정본에서 관리한다. 환자와 보호자를 구별하고 나이·단위·성별을 추정하지 않는다. 반복은 합치고 명시적 정정만 교체하며 미해결 충돌은 uncertain으로 둔다. 현재 임상 자산에 없는 age·sex 적용 규칙을 만들지 않는다.

## 그래프·감별·질문 알고리즘

질문 자산은 target|attribute override에 선택적 collect_via를 둘 수 있다. 같은 target에 직접 연결된 기존 원자 속성만 한 단계로 참조하며 중첩·순환·자기 참조·실행 불가 component를 prepare에서 거절한다. CC 속성 준비·required_actions·질문 큐 제거·DD 후보는 같은 전개를 사용하고 완전한 scope별 원자 질문을 한 번만 센다. 기간만 알면 감소량만, 감소량만 알면 기간만 수집한다. 수집 완료로 복합 임상 기준이나 새 graph fact·Answer를 만들지 않는다. DD의 collection_only 참조는 원래 전체 기준을 그대로 가리키며, 3개월 감소량으로 별도 6개월 감소율 질문이나 threshold를 완료 처리하지 않는다.

새 후보는 support 또는 strong_support 관계의 scoped Target→Pattern→Association→Disease 또는 applicability 경로로 회수한다. 전체 Pattern 일치는 후보 진입 조건이 아니며 against-only 경로로 무관한 새 후보를 확장하지 않는다. 기존 후보는 현재 유효한 그래프 경로가 남아 있으면 보존한다. 전체 Feature와 applicability가 모두 일치할 때만 등록 effect를 활성화한다. 부분 일치는 활성 지지가 아니고 불일치를 반대 효과로 뒤집지 않는다. 명시적 모순으로 불가능해진 관계의 나머지 조건은 질문하지 않는다.

후보 유입과 근거 구성은 호출 안에서 같은 관찰별 Pattern·applicability 판정을 공유한다. triggering Target의 관찰 그룹이나 전체 applicability가 명시적으로 모순되면 그 경로로 새 후보를 넣거나 prior를 보호하지 않는다. 다른 유효 경로와 prior의 유효한 against 경로는 보존한다. Target 미관찰 Context 경로·unknown 부분 조건·유효한 부재 지지는 유지하며 구성원·episode·취득 방식의 자료를 합쳐 조건을 완성하지 않는다.

코드는 현재 supports·against·unresolved와 실제 fact·graph 참조를 유지한다. 수치·값 불일치는 실제 관찰 참조를 남기며 서로 다른 episode의 속성을 합치지 않는다. 일반 패턴의 부합은 refinement 미확인·불일치 때문에 사라지지 않는다. 같은 관찰의 반복 출처를 독립 근거처럼 계산하지 않는다.

CaseState.assessment가 유일한 감별 정본이다. 순서가 순위이며 revision·chief·마지막 수용 응답 식별자·frozen·한계를 보관한다. Initiation과 CC는 정상 종료 때 각각 한 번 순위를 요청한다. Context 종료의 순위와 DD 첫 행동은 DD 진입의 joint decision 한 번으로 합친다. 이후 unknown을 포함한 새 DD 응답마다 순위와 행동을 판단하며 같은 응답의 재진입은 중복 호출하지 않는다. Context 도중과 DD 직전 자원 종료에서도 미처리 응답을 한 번 판단한 뒤 최신 성공 평가를 고정한다. 유효 순위는 잘못된 행동과 독립적으로 수용하고 행동만 제한 복구한다. 미등록·중복 참조와 기존 유효 후보 누락은 거절하며 그래프 경로가 소실된 후보만 코드가 무효화한다.

점수·chief coverage·완성 패턴·가상 답변 utility는 수용 gate가 아니다. 코드가 수용 LLM 순위를 재정렬하지 않는다. 정상·복구 호출의 출력 상한은 최대 8000토큰이며 실제 남은 누적 output이 더 적으면 그 잔량을 적용한다. 기능별로 필요한 dict/list만 선택하고 JSON으로 한 번 직렬화한다. 전체 상태·큰 schema·그래프 profile 전문을 주입하지 않으며 사실·조건·미확인은 지역 참조표에 한 번 정의한다. Python의 전체 적격 disease 후보와 그래프 근거를 보존하고 기존 prior·route 순서의 모델 후보 참조와 수용 Assessment에 고정 개수 상한을 두지 않는다. 모든 신규 후보의 수용을 의무화하지는 않는다. 모델용 relation·evidence·question·condition 상세 표만 각각 최대 50개로 제한하며 이 한도를 후보·Assessment·SOAP 개수 상한으로 사용하지 않는다. 제외 레코드의 참조와 미사용 조건·scope를 제거하고 환자 facts와 그 scope는 보존한다. 제외를 음성 근거로 해석하지 않는다. clinical/gateway의 프롬프트 바이트 제한·절단 정책은 추가하지 않으며 Education에만 D59의 고정 JSON 상한을 적용한다.

공개 ONTOWARD_PROMPTS manifest에 책임·출력·상황별 프롬프트 모듈을 등록한다. Ear·세션·Education·Mouth가 Python에서 현재 작업과 initial·reply·EXAM, 일반 매핑·통합 복구, 질환·증상 안내, 실제 복구에 필요한 모듈만 선택한다. LLM에 여러 작업의 조건 분기를 해석시켜 작업을 고르게 하지 않는다. 지시와 JSON 입력을 분리하고 실제 임상 조건은 입력 데이터로 보존한다. 같은 manifest와 모듈을 독립 ZIP에 포함하고 관측기에서 해시·경로 조합을 확인한다.

D52에서 target·effect·순서가 있는 전체 Pattern·rule scope·applicability가 동일한 관계는 서로 다른 질환 Association에서도 전송 정의를 공유한다. 질환별 참조·모든 후보·조건·관찰별 사실 연결과 Python의 원래 그래프 근거는 유지한다. clinical/gateway의 CONTEXT_LIMIT_EXCEEDED는 출력 잘림과 구별하여 원래 오류를 반환하고 같은 packet의 출력 한도 확대 재호출을 하지 않으며 소유자가 해당 작업을 pass한 뒤 다음 진료 단계나 최종화로 진행한다. Education 두 role은 D59에 따라 예산 동기화를 요구하고 기존 최종화로 이어간다.

모든 임상 질문은 같은 scopes 표를 참조하며 facts에 아직 없는 유효한 질문 observation·episode도 호출 내 별도 참조로 구분한다. relation과 0 기반 feature index로 정확히 복원하는 기대값만 중복 전송에서 제외하고 전체 full_pattern·effect·rule_scope·applicability·질환 membership은 유지한다. Context 기대 상태와 presence_required의 존재 전제는 명시하며 0·false·unknown·의도된 빈 배열을 일괄 제거하지 않는다.

필수 수집은 코드가 보장하고 선택적 질문은 LLM이 실행 가능한 선택지에서 고른다. 공유 relations 표에 effect·scope·전체 Pattern·applicability를 한 번 정의하고 근거와 expected_by_disease에서 참조한다. 고유 scope별로 질문을 먼저 합친 뒤 실행 가능성을 검사하며 질환별 기대 답을 보존한다. 질문 순서·SOAP category·clarification은 새 attribute_roles에서 읽는다. 실제 role clarification이 있으면 prepare에서 NFC·한글 포함·1–30자를 검사하며 null일 때 검증된 기본 문구를 사용한다. Context는 같은 CaseFact로 매칭하고 별도 supporting-context 경로를 두지 않는다. rule any와 구체 질문의 current/past/unspecified를 분리하며 해결 여부는 원래 rule scope로 검사한다. 속성만 있는 Pattern을 포함하여 같은 Target·scope의 존재를 확인한 뒤 속성 질문을 실행하며 질문의 등록 관계·문구·단계·주체·가족 구성원·시점·관찰·반복·자원을 검사한다. 유효 순위와 잘못된 행동을 분리하여 행동만 한 번 복구할 수 있다.

DD 종료는 마지막 응답 수용→최신 평가 확인·허용 복구→현재 미확인·한계 확정→Assessment와 기반 facts·chief 고정→Education 이동이다. 자원 종료도 같은 고정 절차를 사용한다. 새 정상 SAY 답변 하나가 설정된 정확한 unknown이고 facts revision·chief가 불변이며 해당 재평가가 실패하거나 모델 자원이 없으면 직전 미고정 질환 Assessment의 순위·근거·limitations·원래 based_on_response를 보존하고 미재평가 한계를 추가한다. status·content·turn·source·outcome과 오류·새 fact·이전 응답 연결을 검증하고 부정·정정·미해석 발화·parser 실패·stale 평가에는 적용하지 않는다. 정상 최신 평가는 우선한다. 그 밖에 최신 질환 평가를 얻지 못하면 확인 chief 또는 원문과 연결된 symptom route로 고정하고, 근거 없는 route만 있으면 평가 불완전성을 가진 working problem을 고정한다. Writer에서 다시 진단을 고르지 않는다.

## 예산·Education·SOAP

D45에서 SDK client.session()의 turns_remaining이 행동 예산의 기준이다. SAY·EXAM은 서버 소비를 정산하며 모델·세션 조회·내부 노드·SOAP·DIAGNOSE는 행동 턴을 차감하지 않는다. D63은 D60의 output 시험 예외를 대체하여 누적 출력 100000을 적용한다. 누적 입력 500000·보고된 요청 입력 100000·호출 출력 8000을 보존하고 실제 usage와 optional 서버 잔량만 정산한다. completion_tokens에 포함된 reasoning도 출력으로 계산하며 세부 항목을 중복 가산하지 않는다. optional output_tokens_remaining은 소비량을 바꾸지 않고 로컬 한도를 더 엄격하게만 조정하며 없으면 기본 100000이 작동한다. max_tokens는 역할 한도와 실제 출력 잔량의 최솟값이다. 잔량 0은 새 모델 호출을 막고 기존 Writer 최종화·DIAGNOSE는 계속한다. Education 입력 reserve는 복구하지 않는다. 50 행동·모델 200회·기한·retry를 유지하고 실제 서버 거절·사용량·불명 소비를 구별한다. 이는 현재 공식 서버 정책을 새로 확인했다는 주장이 아니다.

정상 응답으로 확정된 자원은 반복 GET 없이 사용한다. 불명확한 소비·서버 한도 오류는 동기화하고 제출 직전 조회를 유지한다. 세션이 필요한 질문 수를 Budget에 전달하며 Budget은 공유 비용 표와 기존 보호 하한으로 자원을 계산한다.

정상 input 2회와 최종 임상·교육에 필요한 호출 수를 보호하며 선택적 입력 복구도 남은 호출 수와 호출별 출력 상한 안에서 수행한다. 예상 토큰 소비나 새 동적 reserve를 만들지 않고 실제 출력 잔량으로만 max_tokens를 줄인다. 새 행동 전에 응답 해석, 최종 임상 판단과 허용 복구, 활성 P·한국어 안내와 제출 시간을 보호한다. Education 7턴·상한 10턴과 응답·최종화 시간 경계를 유지하며 모든 SAY·EXAM 소비를 해당 세션 actions에 계산한다. 받은 마지막 답변은 잔여 턴이 0이어도 먼저 처리하고 DIAGNOSE를 제출한다. 일시 전송 오류는 같은 ID·payload로 2초 뒤 한 번 재전송하며 불명 행동은 해당 질문만 pass하고 불명 제출은 payload·ID·오류를 보존해 반환한다.

Education은 고정 1위를 먼저 알린 뒤 원문 지침·일반 지식을 구별하여 영어 P와 대응 한국어 발화를 high 요청 한 번으로 생성한다. 영어 내용·출처 인용과 한국어 NFC 1–30 codepoint 문장을 독립 검증한다. 한국어만 잘못되면 정상 영어 P를 유지하고 해당 그룹만 medium으로 제한 복구한다. 영어 부분 복구와 한국어 공급자 응답·문구 복구의 기존 상한은 유지한다. 진단 안내 다음 미처리 계획 전체에서 safety 그룹을 routine보다 먼저 배정하고 같은 priority의 다섯 필드 분산·안정 순서를 유지한다. 문장별 utterance 그룹을 원자적으로 배정하며 capacity·30자 검증을 보존한다. 실제 SAY receipt로 전달을 확인하며, 환자 답변은 transcript-only로 facts·진단·A를 갱신하지 않는다. 명시적 교육 비활성화는 교육 행동·예약·P.education 없이 동작한다.

Education은 frozen primary Disease의 기존 selections만 조회한다. exact AND care_navigation 안정 분할과 그룹 내 순서를 유지하며 문서 다섯 개 제한을 제거한다. 경로·확장자·containment·전체 SHA-256·UTF-8 검증을 유지하고 동일 경로는 한 번 읽는다. read_cap=min(1048576+1, 잔여 총량)만 읽고 성공·실패의 실제 길이를 16777216 bytes에 누적하며 cap에 닿아 EOF가 불명확한 파일은 제외한다. 실패 후에도 같은 매핑의 뒤 후보를 볼 수 있다.

D59는 제목 경로의 고정 관리·검사·경고·의뢰·추적·교육 어휘에 해당하는 짧고 완전한 ATX leaf와 비어 있지 않은 상위 도입문만 공급한다. 원문 byte 범위·줄바꿈·공백·BOM·Unicode를 보존하고 표·HTML·fenced code·각주·원거리 조건 참조와 2048-byte JSON을 넘는 묶음은 제외한다. direct 그룹부터 문서별 경고 우선·순환 선택으로 documents JSON 8192 bytes에 묶으며 의미 있는 scope·background_only를 보존한다. 새 검색 DB·요약·임상 점수·환자 조건 엔진과 전문 fallback은 추가하지 않는다.

최종 system/user/repair messages JSON은 32768 bytes 이하이며 초기 초과 시 마지막 발췌 묶음부터 통째로 제거한다. 고정 facts·진단·지시만으로 초과하면 생성을 생략한다. 확정 packet의 spans로만 contexts를 만들고 초기·repair에 같은 packet과 contexts를 사용한다. 인용의 모든 출현을 원문 절대 byte 범위의 set으로 모아 한 위치일 때만 승인한다. repair 초과 시 호출 없이 검증된 영어 P를 유지한다. JSON 크기는 ensure_ascii=False, separators=(",", ":"), allow_nan=False 직렬화의 UTF-8 길이로 측정한다.

DoctorBrain은 Education 두 role의 pending sync·messages 초과를 ID·usage·실행 전에 각각 LOCAL_EDUCATION_BUDGET_SYNC_REQUIRED·LOCAL_EDUCATION_MESSAGE_LIMIT으로 차단한다. D60에서 누적 입력량 기반 LOCAL_EDUCATION_INPUT_BUDGET은 제거하며 finalizing에도 적용하지 않는다. 알려진 Education CONTEXT_LIMIT_EXCEEDED는 실제 요청 기록을 유지하고 소비를 추정하지 않은 채 budget_sync_required만 설정한다. 같은 prepare의 추가 Mouth 모델 호출을 차단하고 기존 외부 budget snapshot·최종화·Writer·실제 DIAGNOSE 완료 receipt를 사용한다. 검증된 영어와 사용 가능한 한국어 캐시는 보존하고 미전달을 전달로 기록하지 않는다. 지침이 없거나 개별 파일이 실패하면 model_knowledge와 빈 references를 사용할 수 있으며 정상 계획을 실패로 만들지 않는다.

모델용 문서는 document_id·relation·evidence_use·text와 의미 있는 scope만 명시적으로 투영한다. 알려진 관리용 scope 상수만 제외하며 path·sha256·미래 내부 필드를 전송하지 않는다. 내부 검증 객체와 원문 UTF-8 인용 offset은 보존하고 본문 strip·헤더 삭제·절단은 하지 않는다. 교육 생성·교육 표현·진단 안내 fallback은 한 번의 current_facts에서 만든 같은 f_ 참조로 patient와 fixed_diagnosis를 함께 투영한다. 없는 근거 참조는 오류로 드러내고 도메인 ID나 정상 안내 템플릿을 바꾸지 않는다. 프롬프트는 문서를 참고 자료로 명시하여 원래 요청·환자 사실·불확실성·안전·출력 계약을 우선한다. 문서 수 제한은 실제 NOVA 입력 수용이나 임상 품질의 증거가 아니다.

[D55](DECISION_STATE.md#D55)의 d50.6은 검증된 현재 v5 runtime 번들에 대한 제한된 오프라인 정정을 허용한다. parent manifest와 다섯 자산을 해시로 고정하고 명시된 invalid edge와 검토된 같은 역할의 Target만 새 immutable build에 변환한다. effect·조건·applicability·scope·질문 의미·값의 owner·진찰 action·지침 membership을 canonical projection으로 보존하며 불명확한 동의어와 충돌 병합은 제외한다. 폐기한 추출 DB나 job을 재개하지 않고 일반 신규 추출의 네 원자료 시작 규칙은 유지한다.

[D56](DECISION_STATE.md#D56)은 현재 번들에 저장된 시진·청진·촉진·타진의 `ExamMethod.examRequestText`를 `${부위} ${진찰법}합니다.` 형태로 정규화한다. 복합 진찰은 필요한 동작을 각각 명시하며 특수 수기·움직임·자세는 보존한다. ID·label·detectedBy·임상 관계·질문 계약을 바꾸거나 기존에 없는 실행 문구·해부학적 부위를 만들지 않는다. 원본 parent를 유지한 새 해시 번들만 활성화하고 실제 NOVA의 문구 수용 여부는 별도로 검증한다.

정식 loader는 hasAttribute range와 canHaveValue domain/range를 전수 검사한다. 정정 번들이 strict 검사·정식 loader·원래 prepare·회귀를 staging에서 통과한 뒤 manifest와 unconditional gate를 함께 로컬 활성화한다. installer는 지정한 parent build를 자동 정리하지 않고 원형 보존한다. getter 타입 방어와 잘못된 속성을 존재 질문으로 바꾸지 않는 계약도 유지한다. 검증 실패 번들은 활성화하지 않는다.

Education 전달 준비에 재진입해도 이미 큐에 있거나 전달·미전달 결과가 기록된 계획 그룹은 다시 표현하지 않는다. 준비 실패의 제한된 복구는 해당 표현 호출 안에서만 수행하며, 재진입으로 실패 그룹을 자동 재시도하거나 결과를 중복 기록하지 않는다. 실제 행동 완료·취소는 공통 QuestionLifecycle을 사용한다.

SOAP는 통합 사실·frozen Assessment·영어 계획·실제 전달 결과를 Python으로 묶는다. age·sex는 HPI 선두, 보고값은 S, 신뢰된 초기 객관 구간과 실제 EXAM의 소견·속성·적격 객관 사실는 O다. O에는 실제 취득 turn을 보존한다. 같은 관찰의 조건·시점·단위를 잃지 않으며 A는 같은 S/O 사실 문구를 재사용한다.

| 구역 | 문자열 필드 |
|---|---|
| S | cc, hpi, pmh, fh, sh, ros |
| O | exam, tests |
| A | evidence, differential |
| P | tests, treatment, disposition, follow_up, education |

별도 `diagnosis`는 frozen 목록의 1위와 일치한다. `note.A.diagnosis`를 추가하지 않는다. 예선 O.tests는 빈 문자열이다. 미질문·미시행·계획·실제 전달을 구별하며 주진단 외 수용 순위를 전부 note.A.differential 문자열에 기록하고 기록 100,000바이트·CR/LF 없는 한 행 진단 500바이트를 검증한다. 크기 초과는 명시적 오류와 기존 최소 Writer로 처리하며 임의 개수로 조용히 절단하지 않는다. 정상 작성 실패에는 추가 LLM·그래프 없는 최소 builder를 쓰고 확정 형식 반려는 기존 한 번의 실질 축소 복구를 허용한다. 정상 완료는 DIAGNOSE의 `completed` 응답이다.

## 상태·검증·제출물

Consultation.run은 수용된 상태로 순차 실행하며 LangGraph와 매 작업 전체 상태 복사·재직렬화를 사용하지 않는다. 외부 데이터는 수용 전에 검증하며 작업별 예외를 scoped pass·세션 이동·독립 최소 작성으로 수습하며 실패한 연산이나 외부 효과를 새 ID로 재생하지 않는다. WorkflowState에는 case·interview·session과 현재 turn만 둔다. CaseState는 통합 facts·chief·별도 수집 route·초기 원문·고정 diagnosis·Assessment·plan·revision, InterviewState는 현재 질문·작은 Answer·수집 중단, SessionContext는 최신 제약·사용량·종료를 소유한다. SOAP는 제출 turn과 보존된 session.final_payload에 두며 미확정 요청 ID와 실제 receipt를 분리한다. 그래프 후보 자료·LLM 교환·복구·원문 조각은 지역값이며 과거 순위·별도 진단 정본·가상 답변·런타임 audit를 보관하지 않는다.

프로젝트 Docker에서 유지 행동 회귀, 임시 새 합성 번들의 상담, 관측 유무 일치, 독립 읽기 전용 ZIP과 원본 SDK HTTP 완료를 검증한다. Test가 프로토콜 대역·재현·관측·비교를 소유하고 Dev/tests/workflow가 유지 회귀를 소유한다. 고정 응답 통과를 실제 모델 정확도나 임상 성능으로 해석하지 않는다.

Test 웹에서는 단일 증례 또는 C01·C03·C10 세 시나리오를 한 번에 시작할 수 있다. 동시 실행은 시나리오별 Docker 네트워크·시뮬레이터·에이전트·출력을 분리하고 각각의 상태와 리포트를 제공한다. NOVA 요청 상한은 시나리오별로 적용하며 전체 최대 요청 수도 실행 전에 표시한다. 한 묶음이 끝나기 전에는 새 웹·CLI 실행을 받지 않으며 자동 대기열이나 재개를 두지 않는다.

Test 관측은 현재 D59의 실제 호출 경계에서 지침 읽기·발췌 패킷·고정 인용 문맥·공유 사실/진단 투영과 모델 로컬 차단·예산 동기화·전달 결과를 추적한다. format 7은 진입점·SDK·workflow·knowledge Python·프롬프트와 관측기 해시를 기록하고 실행 중 추적 소스 변경과 선언한 관측 지점의 연결 누락을 검사한다. 기존 format 5/6과 그래프 trace에는 없는 자료를 보충하지 않는다. Test NOVA 어댑터도 Education의 확정 context 오류를 전역 중단으로 전파하지 않으며 실제 재호출과 동기화는 원래 런타임이 결정한다.

제출 ZIP에는 실행 Python·고정 requirements·공개 .env·필요 프롬프트·manifest 자산만 넣는다. 루트 개발 키·Test·Dev·원본 자료·준비 DB·문서·상태·캐시는 제외한다. 구현 설명은 [한국어 백서](submission/README.md), 사용자 선택은 [결정 문서](DECISION_STATE.md), 관측 결과는 세 운영 상태와 [D51 후속 증빙](data/provenance/algorithm-d50-2-2026-10-20.json)에서 관리하며 D50 증빙은 과거 수용 기록으로 보존한다. 임상 코퍼스 확장·실제 유료 호출·공식 평가·게시·배포는 이 구현 수용과 별도다.

## 새 지식 번들과 추출 자동화

검증된 설치 이후 사용자가 보관 해제를 명시하면 이전 추출 체크포인트·중복 staging·로그·추출 임시 기록을 삭제할 수 있다. 설치 manifest와 실행 자산·원자료·현재 생성기·인증을 유지하고 작은 최종 감사·삭제 영수증을 남긴다. 실행 상담은 작업 DB에 의존하지 않으며 삭제된 실행의 재개·복구 가능성을 주장하지 않는다.

모든 모델 작업과 요청이 확정된 뒤 정보 처리 오류가 남으면, 사용자가 명시적으로 선택한 현재 세션의 수동 교정을 허용한다. 원본 DB와 모든 완료 작업·입력·요청·응답·사용량·시도 횟수는 보존하고 새 fingerprint에 교정 전후·실행 제외 사유·수동 파생 입력 해시를 기록한다. Target/AttributeValue 역할과 실행 필드의 종류·참조를 맞추되 주체·구성원·시점·수치·조건·effect를 임의 변경하지 않는다. 시험 범위 밖 Test나 의미를 확인하지 못한 연결은 DB에 보존하고 실행 번들에서 제외한다. 생산 loader·coverage 검증을 모두 통과한 번들만 요청된 설치로 이어간다.

patch의 공통 어휘와 완료 관계는 작업마다 복제하지 않고 배치에서 한 번만 전달한다. 열 이름이 명시된 표와 등록 참조의 가역 축약을 사용하고 50,000자 이하의 JSON 메시지에 나누되, 전체 조건·scope·수치·단위·정성 effect·질문·진찰 계약을 보존한다. 검색 별칭만 wire에서 제외하며 원래 작업 입력과 완료 판단은 SQLite에 보존한다. 확정된 첫 patch 입력 크기 거절은 recover-patch로 별도 fingerprint에 복구하고, 이전 단계 결과·시도 횟수·사용량·요청·응답·원본 DB와 임상 핀을 보존하며 불명 요청은 거절한다.

초안의 단일 작업이 메시지 상한을 넘으면 source_material 레코드 목록을 작업 ID로 연결한 완전한 JSON 조각에 나누어 같은 요청에 전달한다. 작업 헤더에 참조와 전체 레코드 수를 명시하고 모든 레코드의 순서·중복·타입·값을 보존한다. 배치나 모델 호출 수를 늘리거나 원자료를 자르지 않는다. 로컬 draft_packet_item_too_large:jobs 실패는 recover-draft-packets로만 명시적으로 복구하며, 다음 배치에서 오류를 재현하고 수정된 패킷을 검증한 뒤 완료 결과·입력·요청·응답·사용량·카운터·원본 체크포인트를 보존한 새 fingerprint를 만든다. 설정·모델·임상 계약 변경과 불명 요청은 거절하고 복구에서 모델을 호출하지 않는다.

실행 지식은 schema_version 5.0, knowledge_contract v5-enum-1이다. manifest는 build_id와 schema·vocabulary·clinical·questions·guidelines 다섯 asset의 상대 경로·SHA-256만 가진다. 경로는 manifest 디렉터리 기준이며 절대 경로·경계 이탈·hash 불일치를 거절한다. 번들은 manifest 포함 여섯 파일이고 questions JSON은 attribute_roles를 포함한다. 한·영 표제와 별칭은 새 vocabulary가 제공한다. 이전 형식과의 호환 변환·policy fallback은 없다.

Disease→Association→Pattern→Feature를 유지하고 ContextFactor를 Target에 추가한다. Association은 명시적 target_scope·applicability와 정성 effect를 가진다. 생성 effect는 support·strong_support·against·strong_against·neutral이며 neutral은 작업 DB에 완료 결과로 보존하고 RDF에서는 제외한다. 점수·가중치·전형성·ScoringPolicy·scoring/reasoning policy·관계 source/confidence/reviewer·옛 admission 필수 검증을 제거한다. 환자 취득 source/turn·주체·시점과 Education의 문서 경로/hash/인용은 유지한다. 수치 진단 점수 제거는 나이·실측값·기간·통증 수치·단위·비교 연산자 제거를 뜻하지 않는다.

Extraction/의 fresh 경로는 네 원자료에서 빈 SQLite 작업 DB로 시작한다. RF2 Snapshot·배포 의존성, 실제 BODHI CSV, DDXPlus evidence/condition metadata, Astra 후보·속성·값·CPX 범위를 사용한다. 환자 ZIP·이전 생성 DB/질문/어휘/source-custody SQLite·Astra 과거 snapshot/등록 정책을 새 정본으로 사용하지 않는다. 입력 인덱싱→개념/역할 정규화→질문/진찰→유한 관계 초안→최종 분류/충돌 해소→한 번의 결손 보완→staging 컴파일/검증/명시적 설치를 수행한다. 원자료가 부족한 일반 관계는 최종 모델 내부 지식으로 완성하되 환자 관찰은 생성하지 못한다.

공급자는 nova_dev·codex_subscription·openai_api 중 빌드당 하나다. 초안 gpt-6-luna·최종 gpt-6.1-sol의 effort는 모두 medium이다. NOVA는 원본 SDK의 세션 밖 Client.chat, 구독은 새 전용 volume의 사용자 ChatGPT device login과 도구를 비활성화한 read-only codex exec, API는 도구 없는 Responses 구조화 출력을 사용한다. 인증은 선택 경로에만 전달하고 자동 모델 변경·provider fallback·계정 전환은 없다. NOVA/API 출력 상한은 8000/32000이고 CLI에는 강제 토큰 상한을 주장하지 않는다. 요청/CLI 제한은 600초, Compose 종료 유예는 660초다. NOVA KST 일일 한도와 다른 공급자의 한도·재시도 시점을 구별한다.

run·status·pause·verify·install을 제공한다. 조회·중단·검증은 client/개발 키 없이 동작한다. 입력/설정/공급자/모델/프롬프트/생성 계약 hash와 단계·chunk cursor·job 결과·재시도·usage를 SQLite transaction으로 저장하고 worker는 하나만 실행한다. 같은 fingerprint의 --resume만 허용하고 완료·neutral을 재호출하지 않는다. 전송 전 payload/인자/job ID/request ID를 기록하고 응답을 먼저 보존한다. pause·SIGINT·SIGTERM은 새 전송을 막고 한 in-flight 응답의 유효 행을 저장한 뒤 paused로 정상 종료한다. 쿼터 대기 중에도 중단할 수 있다.

NOVA에는 JSON Schema 전체를 system 메시지에 포함하고 로컬에서 엄격하게 검증한다. 요청 시작·수용/무효 건수·검증 원인을 로그에 남기며, 시도 상한에 도달한 작업만 실패로 표시한다. 스키마 전달이 누락된 버전에서 정규화가 실패했고 수용 결과가 0개인 경우에 한해 recover-normalize를 명시적으로 실행할 수 있다. 네트워크·키 없이 입력·모델·파서·스키마·실행 계약의 일치를 확인하고 완료된 원자료 인덱스를 새 fingerprint에 복사한다. 원본 DB와 요청·사용량·과거 시도는 보존하며 복구 명령 자체는 모델 호출·설치를 시작하지 않는다. 불명 요청·미완성 인덱스·수용된 결과가 있으면 이 복구를 거절한다.

요청 배치는 설정된 batch_size(현재 10개)로 고정한다. missing_result·형식 오류·출력 중단이나 과거 시도 횟수 때문에 이후 배치를 축소하지 않는다. 유효한 행은 먼저 수용하고 미완료 행만 같은 고정 배치로 재시도하며, 단계 말미의 잔여 작업만 10개보다 작을 수 있다. 작업별 6회 출력 검증 상한과 NOVA 일일 한도는 유지한다. 과거 자동 축소가 남은 실행은 안전하게 pause한 뒤 recover-normalize-batch로 동일 입력·설정·프롬프트·임상 계약과 제한된 코드 변경을 검증한다. 새 fingerprint에 모든 작업·요청·사용량을 보존하며 원본 체크포인트는 바꾸지 않는다.

BODHI 개념 행의 모든 원본 필드와 이름이 공백·Unicode format 문자만으로 비어 있고 연결된 SNOMED 설명·정의도 없으면 임상 개념을 만들 근거가 없으므로 모델 전송 전에 제외한다. 원본 행과 시도 횟수는 보존하고 빈 완료 결과와 SQLite excluded:<job_id> 사유를 기록한다. 비어 있지 않은 후보에 대한 빈 모델 결과는 계속 검증 실패다. 이 빈 행 때문에 정규화 시도 상한에 도달한 기존 실패는 recover-normalize-empty로만 복구하며, 동일 입력·프롬프트·모델·임상 계약 아래 다른 모든 작업과 사용량을 보존한다. 복구 기록은 SQLite에 유지하고 별도 recovery.json 사본은 만들지 않는다.

정규화는 임상 개념·역할을 만들고 question·exam_text·attribute_role.clarification은 null로 둔다. 이 단계에서 잘못 생성된 행동 문구는 원본 응답에 보존하고 수용 전에 제외하며, 기존 완료 결과도 저장된 바이트를 바꾸지 않고 같은 방식으로 읽는다. questions 단계가 한국어 행동 문구를 생성하고 Hangul·NFC·치환 후 1–30자와 presence 전용 affirmative·수치 질문 전용 units 계약을 검증한다. 이 경계 오류가 있는 일시 중단된 정규화 실행에는 recover-normalize-text를 명시적으로 사용한다. 동일 입력·임상 계약을 확인한 새 fingerprint에 완료 결과를 그대로 보존하고, 미완료 행은 저장된 최신 응답에서 로컬 복구하며 사용량을 중복 집계하지 않는다.

questions의 모델 출력은 id·question·exam_text·attribute_role·exam_method의 작은 패치 한 개로 제한한다. 이름·표제·별칭·속성·허용 값·system은 Python이 작업 입력에서 그대로 복원한 뒤 기존 검증을 적용한다. linked_concepts를 재출력하지 않으며 ExamFinding의 진찰 방법이 비어 있을 때만 새 ExamMethod 한 개를 허용한다. 작업 DB에는 완전한 Concept 결과를 저장한다. 잘린 Luna 질문 응답은 recover-questions로 기존 결과·요청·사용량·시도 횟수와 임상 계약을 보존한 새 fingerprint에 복구한다. 기본 설정은 Luna medium·배치 10개다. config.sol.json과 명시적 switch-sol은 questions 단계에서 Sol medium·배치 40개·32000토큰·하루 100회 모델 합산 한도로 옮기는 별도 옵션이며 자동 fallback이 아니다. 안전하게 paused이거나 허용된 확정 실패인 체크포인트만 전환하며, CONTEXT_LIMIT_EXCEEDED는 명시적 Sol 전환에서만 허용한다. 원본 입력과 완료 결과·실패 요청·시도 횟수를 보존하고 불명 요청과 관련 없는 오류는 거절한다.

questions의 전송 입력에서는 검색용 별칭과 연결 참조의 중첩 attributes·values·systems를 생략한다. 질문 대상의 임상 필드와 각 참조의 식별자·역할·영문/한국어 표제·context·행동·단위·진찰 방법은 보존한다. 완전한 등록 입력은 SQLite와 결과 복원의 정본으로 유지한다. 명시적 Sol 질문 입력 수정은 확정 INVALID_REQUEST_BODY 실패와 build.py 변경이 있는 동일 Sol 설정에서만 별도 fingerprint로 복구하며, 거절된 요청·시도 횟수·임상 핀을 보존한다.

draft의 공통 어휘는 배치 안에서 한 번만 전달한다. 열이 명시된 정의 표와 가역 개념 ID를 사용하고, 임상 정의·속성/값 연결·단위·원자료·job ID를 보존한다. 완전한 JSON 메시지 조각을 5만 자 이하로 나누어 같은 모델 요청에 전달하며 고정 배치나 모델 호출 수를 늘리지 않는다. 세 공급자의 저장 요청에서 동일 ID 복원을 수행한 뒤 기존 검증과 질환별 귀속 검증을 적용한다. 미완료 입력은 다음 배치만 읽고 시도 상한은 전체 미완료 작업에서 검사한다. recover-draft는 완료된 정규화·질문, 수용 draft 0개, 확정된 100 MB 초과 NOVA INVALID_API_RESPONSE 실패와 제한된 패킷 코드 변경만 허용하며 원본·결과·요청·사용량·카운터·임상 핀을 보존한다.

NOVA의 압축 draft 요청도 확정 INVALID_REQUEST_BODY로 실패했다면 사용자가 명시적으로 선택한 openai_api 또는 codex_subscription으로 recover-draft-provider를 실행할 수 있다. 완료된 정규화·질문과 수용 draft 0개, 완료된 원자료 인덱스, 확정된 요청만 허용한다. 사용자가 선택한 API profile은 초안·최종 gpt-6-luna medium·배치 40개·출력 상한 32000이며, 구독용 Sol profile도 유지한다. 공급자·지정 모델 profile과 NOVA 전용 api_base 이외의 설정·프롬프트·임상 생성 코드·입력·실행 계약은 같아야 한다. 원본·완료 결과·카운터·과거 공급자별 요청·응답·사용량을 그대로 보존한 별도 fingerprint를 만들고 미완료 running draft만 pending으로 되돌린다. 복구 자체는 모델을 호출하지 않으며 새로운 요청에만 선택한 공급자를 사용한다. API에는 NOVA 쿼터를 적용하지 않고 불명 결과는 이 경로로 복구하지 않는다.

초안 요청의 native JSON Schema는 배치 job ID·질환 ID, Symptom·ExamFinding·ContextFactor Target, ContextFactor applicability와 존재/속성 expectation 쌍을 제한한다. 많은 등록 참조는 enum 한도를 넘지 않는 pattern으로 제한한다. 필요한 새 개념은 명시적인 new:<Kind>:<slug> ID와 정의로 제안하며 등록 개념을 재정의하지 않는다. Python은 Target 종류·질환 귀속·속성/값 등록을 계속 검증하고 실패한 관계의 ID와 실제 종류를 구체적으로 남긴다. recover-draft-endpoints는 endpoint 오류가 있는 확정 paused API Luna draft에서만 동일 설정·임상 계약 아래 새 fingerprint를 만들고 모든 완료 결과·원본 요청·응답·사용량·카운터를 보존한다. 불명 결과나 시도 상한에 도달한 미완료 작업은 이 경로로 우회하지 않는다.

강제 종료 후 저장 응답이 없으면 outcome_unknown이다. NOVA는 지원되는 같은 ID/payload 복구를 사용하며 API/CLI는 원격 중복 방지를 가정하지 않는다. 운영자의 --retry-unknown이 있어야 새 시도를 허용하고 이전 불명 기록을 보존한다. 설치는 검증된 build 전용 파일을 먼저 쓰고 manifest를 마지막에 원자적으로 바꾼다. 완료/일시 중단 뒤 자동 재시작하지 않는다.

NOVA의 명시적 PROVIDER_RESPONSE_INVALID는 실패한 요청을 보존하고 같은 모델·설정·내용에 새 request_id를 발급하여 최대 5회 전송 시도 안에서 재시도한다. 이 전송 교체로 출력 검증 시도 횟수를 추가 소모하지 않는다. 전송 결과를 모르는 경우와 PROVIDER_UNAVAILABLE·REQUEST_PENDING은 같은 ID로 복구한다. 과거 버전의 같은-ID 오류 반복으로 정규화가 실패했다면 recover-normalize-provider를 명시적으로 사용한다. 동일 입력·프롬프트·모델·임상 계약을 검증한 새 fingerprint에 완료 결과와 모든 시도 횟수·사용량을 보존하고, 확정된 오류 기록만 failed로 바꿔 미완료 작업을 새 요청으로 재개한다. 불명 결과는 이 경로로 바꾸지 않는다.

이미지는 ontoward-extraction:local이며 Python 3.12·기존 고정 Python 의존성·@openai/codex@0.162.1을 포함한다. D49의 초기 구현 수용은 이미지·무점수 워크플로우·합성 오프라인 검증으로 한정한다. 실제 로그인·유료 생성·설치·정식 ZIP은 각각 승인된 실행 범위에서만 수행한다. 이후 별도로 승인된 실제 빌드의 진행과 설치 여부는 루트·data PROJECT_STATE가 소유하며 이 요구사항 문서를 실시간 상태로 사용하지 않는다. 기존 자산/점수 builder는 활성 경로에서 철회하고 과거 원자료·준비 결과·수용 ZIP·증거는 보존한다.

D56 검증 완료 뒤 사용자가 과거 build 삭제를 요청하면 현재 manifest가 참조하는 build와 실행 가능성을 먼저 확인하고 열거한 이전 build만 삭제한다. 원본 테스트와 과거 manifest·자산 해시·설치·정정·삭제 영수증은 보존한다.

## 기존 번들의 제한된 증분 보완 (D58)

최신 활성 manifest를 해시 검증한 부모로 삼아 불면의 약물 관련 설명과 저신장의 정상 성장변이만 별도 보완한다. 유한 누락 발견→개념→관계→한 번의 최종 임상 검토→질문을 수행하고, Python이 URI와 부모 precondition을 확정한다. 기존 정의는 명시적 append-only 확장만 허용하며 관계 대체와 공유 속성 역할 변경은 개별 allowlist와 이전 hash를 검증한다. 부모 의미·질문 override·단위·값 소유권·진찰·지침을 보존하고 단일 정적 immutable child로 컴파일한다. 상담 중 overlay와 새 서비스는 추가하지 않는다.

키 없는 plan은 실제 부모의 빈 delta round-trip을 먼저 검사한다. 각 후속 workset은 직전 완료 결과에서 한 번 고정하고 재개 시 완료·neutral·유효 형제 결과를 재사용한다. 실제 생성에는 명시적 요청 상한과 기존 선택 provider/model 설정을 적용하고 설치는 별도 명령으로 실행한다. 모든 설치가 공유하는 lock 안에서 최신 부모 일치와 manifest 원자 교체를 수행하며 augmentation은 보관 build를 정리하지 않는다. DD는 현재 평가의 미확인 Context·clarification 질문만 기존 자격·범위·중복·예산 검사로 허용한다. 모델 없는 검사·mock 생성·실제 생성·상담 정확도는 별도 보고한다.

D61의 CC 강제선택은 정상 추출·허용 clarification 뒤 최대 8개의 등록 Symptom과 gateway 논리 호출 한 번만 사용한다. 선택 route는 실제 patient fact·지지 근거와 분리하며 정상 chief에는 추가 호출이 없다. demographic echo는 같은 canonical 값·measurement·scope·비교정·현재 quote 부재를 모두 확인할 때만 제거한다. partial repair의 null·빈/생략·영역별 개수 실패는 정상 형제와 원래 anchor 위치를 보존한다. Test 개별 오류는 요청 간 전파하지 않고 공유 ceiling·동일 ID cache를 유지한다. 실제 제출 completed·Education 준비·진단 안내·expected 계획 발화·P 내용은 별도 지표이며 수신 없는 생성 payload도 표시한다.
