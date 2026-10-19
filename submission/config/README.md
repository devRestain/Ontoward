# 책임·내용·상황별 프롬프트 설정

D50은 D48의 모듈 선택을 유지하며 [prompts.json](prompts.json)이 작업별 모듈 조합을 정하고 [prompts/](prompts/)의 영어 지시문을 읽는다. 각 호출자가 Python에서 현재 작업을 선택한다. LLM에는 해당 작업의 자료 해석 규칙·출력 계약·상황 지시만 전달한다. DoctorBrain은 완성된 messages를 실행하며 프롬프트를 선택하지 않는다.

흐름을 먼저 이해하려면 [아틀라스의 소유권](../../Test/atlas.html#owners)과 [세션별 호출 시점](../../Test/atlas.html#consultation)을 보세요. 프롬프트를 선택하는 호출자, 모델을 실행하는 Brain, 출력을 수용하는 Python 검증을 구분해 설명합니다.

공개 설정은 [submission/.env](../.env)에 두고 같은 이름의 환경변수가 우선한다. 프롬프트 manifest와 각 모듈 경로는 submission/config 내부에 제한한다. 변경은 prepare 재실행으로 반영한다. 기존 열 개의 혼합 프롬프트 파일과 개별 프롬프트 환경변수는 제거했다.

| 설정 | 기본값 | 역할 |
|---|---|---|
| ONTOWARD_PROMPTS | config/prompts.json | 작업별 모듈 경로 목록 |
| ONTOWARD_TEXTS | config/texts.ko.json | 준비 질문·발화·SOAP 문구 |
| ONTOWARD_EDUCATION_ENABLED | true | Education 실행 여부 |
| ONTOWARD_KNOWLEDGE_MANIFEST | knowledge/manifest.json | 고정 임상 자산 |

| Python 소유자 | 선택 경로 | 선택하는 상황 |
|---|---|---|
| DoctorEar | input.initial / input.reply / input.exam | 초기 정보·문진 답변·실제 EXAM 응답 |
| DoctorEar | input.repair / input.rows_repair / input.chief_repair | 전체 형식·특정 행·초기 chief 검토가 실제 필요한 요청 |
| DoctorEar | mapping.select / mapping.forced + mapping.repair | 일반 연결·강제 연결, 해당 정책의 형식 복구 |
| 각 임상 세션 | clinical.rank / clinical.decision / clinical.action + session.* | Initiation·CC 종료 순위·DD 진입과 응답의 공동 판단·행동만 복구 |
| 각 임상 세션 | clinical.repair | 현재 계약의 제한된 복구 |
| EducationSession | plan.generate / plan.repair | 영어 P·한국어 발화 공동 생성과 정상 영어를 보존하는 부분 복구 |
| DoctorMouth | mouth.announcement.disease / mouth.announcement.symptom | 고정 질환·증상 진단 안내 |
| DoctorMouth | mouth.plan | 영어 계획의 한국어 전달 |
| DoctorMouth | mouth.response_repair / mouth.text_repair | 공급자 응답·잘림 복구 또는 문구·형식 복구 |

manifest의 각 경로는 순서가 있는 파일 목록이다. 예를 들어 clinical.rank는 data.txt → clinical_common.txt → clinical_ranking.txt → clinical_rank_output.txt를 사용하고 호출자가 해당 session.* 문구를 덧붙인다. DD에서 유효 순위와 잘못된 질문을 받으면 Python은 순위를 수용하고 clinical.action과 clinical.repair로 다음 요청을 만든다. 그 요청에는 순위를 다시 계산하는 지시가 없다.

영어 지시는 prompt-writer 스킬에 따라 목적·자료 경계·작은 JSON 결과를 명시한다. initial·reply·EXAM과 정상·복구를 한 프롬프트의 조건문으로 나열하지 않는다. 실제 환자의 조건부 진술, 지침 적용 조건과 불확실성은 판단에 필요한 데이터로 보존한다. 출력 구조·출처·참조·중복·누락·실행 가능성·NFC 1–30자 검사는 Python의 책임이다.

모델은 openai/gpt-6-luna이며 임상·영어 P와 한국어 공동 생성은 high, Ear와 Mouth의 남은 표현·복구는 medium이다. 공감은 texts.ko.json의 검증된 템플릿을 사용한다. 사실 정본·정상 4096 및 임상 복구 8000 출력 토큰·기존 복구 한도를 유지하고 호출 일정은 D50을 따른다. 입력은 필요한 dict/list를 한 번 직렬화한 JSON이며 전체 상태·큰 schema·그래프 profile을 넣지 않는다. 프롬프트 바이트 측정·제한·진단 통계·크기 기반 처리는 없다.

환자 원문은 Ear 이후 임상·계획·SOAP로 전달하지 않는다. Education은 고정 진단 안내 후 영어 계획·한국어 전달을 진행하며 응답은 transcript-only다. ONTOWARD_EDUCATION_ENABLED=false는 기존 비활성 계약을 따른다. texts.ko.json과 manifest 고정 질문 자산의 역할도 유지한다.

패키지는 manifest와 참조된 모듈만 포함한다. 문서·상태·개발 키는 제외한다. 새 Test trace에는 설정·manifest·모듈 해시와 경로 조합을 기록하고 저장된 실행은 변경하지 않는다. SDK·전송·캐시 동작과 실제 모델 품질은 프롬프트 작성 자체의 검증으로 대신하지 않는다.

D49의 clinical_common 모듈은 qualitative effect·전체 Pattern·scope·applicability를 해석한다. 부분 부합·불일치·미확인을 효과로 뒤집거나 점수를 계산하지 않는다. 공유 relations 표를 expected_by_disease와 근거에서 참조하여 effect·전체 조건·적용 범위를 보존한다. Python의 상황 선택과 독립 수용 경계를 유지한다. 실제 새 번들 전 manifest 부재는 prepare에서 knowledge_bundle_not_installed로 실패한다.
