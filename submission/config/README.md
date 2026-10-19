# 세션과 DoctorEar·DoctorBrain·DoctorMouth 설정

DoctorBrain은 모든 모델 호출의 실행기이며 프롬프트를 선택하거나 임상 결과를 수용하지 않는다. DoctorEar가 입력 문맥·DB 연결을, 세션 객체가 임상 입력과 순위·행동을, EducationSession이 영어 P를, DoctorMouth가 공감·한국어 표현을 준비하고 검증한다.

공개 설정은 submission/.env에 두며 환경변수가 우선한다. 경로는 submission 내부 config/knowledge로 제한하며 prepare 재실행으로 반영한다.

| 설정 | 기본 파일 |
|---|---|
| ONTOWARD_PARSER_PROMPT | input_parser.txt |
| ONTOWARD_NORMALIZATION_PROMPT | normalization.txt |
| ONTOWARD_CLINICAL_PROMPT | clinical.txt |
| ONTOWARD_INITIATION_PROMPT | initiation.txt |
| ONTOWARD_CHIEF_COMPLAINT_PROMPT | chief_complaint.txt |
| ONTOWARD_CONTEXT_FACTOR_PROMPT | context_factor.txt |
| ONTOWARD_DIFFERENTIAL_DIAGNOSIS_PROMPT | differential_diagnosis.txt |
| ONTOWARD_EMPATHY_PROMPT | empathy.txt |
| ONTOWARD_EDUCATION_PROMPT | education.txt |
| ONTOWARD_EDUCATION_DOCTOR_PROMPT | education_doctor.txt |
| ONTOWARD_TEXTS | texts.ko.json |

모델은 openai/gpt-6-luna다. 임상·영어 P는 high, 입력·공감·한국어 표현은 medium이다. 모델 입력은 기능별로 선택한 Key와 Value의 문자열이며 전체 상태·큰 Pydantic schema·전체 그래프 profile을 넣지 않는다. 프롬프트 바이트 측정·제한·진단 통계·크기 기반 조각 처리는 없다. 임상 출력은 정상 4096·한 번의 복구 8000토큰이다.

첫 세 세션은 종료 때 순위만 한 번 요청한다. DD는 기존 평가로 첫 행동을 선택하고 이후 각 환자 응답에 순위와 행동을 함께 요청한다. Pydantic 구조와 참조·범위·중복·누락·실행 가능성은 호출자가 검증하며 유효 순위는 행동 복구 중 보존한다. ClinicalFact·NoteFact 대신 통합 CaseFact의 정규화된 내용·graph_binding을 목적별로 선택한다.

texts.ko.json은 인사·공통 경과·기본 병력 다섯 영역·Open Inquiry·명료화·공감 fallback·영어 SOAP 문구를 담는다. 질문 계약은 manifest 고정 자산이다. 환자 원문은 Ear 해석 이후 임상·계획·SOAP로 보내지 않는다. SAY·EXAM은 독립 NFC 1–30자 검증을 통과한다.

Education은 기본 활성화하고 고정 진단을 먼저 안내한다. manifest로 검증한 지침 원문과 통합 환자 사실에서 영어 P를 만들고 인용과 모델 지식을 구별한다. 공급자 응답 복구와 한국어 문구 복구는 별개이며 전체 발화 예산 안에서 전달한다. 응답은 transcript-only다. 명시적 ONTOWARD_EDUCATION_ENABLED=false는 교육 행동·보호 턴·P.education 없이 동작한다. SDK 필드·상태 코드·내부 ID·source·turn은 Python이 소유하고 이 문서는 ZIP에서 제외한다.
