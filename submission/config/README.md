# Gateway와 진료 문구 설정

D40의 초기 정보·응답 해석은 input_parser.txt, 기록용 표현은 medical_terminology.txt, 수집 중 공감은 empathy.txt가 담당한다. education.txt는 working diagnosis와 미완료 평가를 유지한 영어 P, education_doctor.txt는 조건을 보존한 한국어 설명을 생성한다. 임상 질문 계약과 한국어 자산은 knowledge manifest가 소유한다.

공개 설정은 submission/.env에 두며 같은 실행 환경변수가 우선한다.

```dotenv
ONTOWARD_KNOWLEDGE_MANIFEST=knowledge/manifest.json
ONTOWARD_PARSER_PROMPT=config/input_parser.txt
ONTOWARD_TERMINOLOGY_PROMPT=config/medical_terminology.txt
ONTOWARD_EMPATHY_PROMPT=config/empathy.txt
ONTOWARD_EDUCATION_PROMPT=config/education.txt
ONTOWARD_EDUCATION_DOCTOR_PROMPT=config/education_doctor.txt
ONTOWARD_TEXTS=config/texts.ko.json
ONTOWARD_EDUCATION_ENABLED=true
```

같은 실행 환경변수가 우선하고 경로는 submission 기준 knowledge/config 내부여야 한다. 수정은 prepare를 다시 실행하여 적용한다. 생성 프롬프트와 ONTOWARD_DOCTOR_PROMPT 설정은 없다.

texts.ko.json은 새 인사, 공통 intake 네 슬롯, 기본 병력 다섯 영역, Open Inquiry·명료화·공감 fallback과 영어 SOAP 표시 문구를 담는다. 모든 SAY/EXAM은 NFC 1–30자 검증을 통과하며 절단하지 않는다.

Education은 기본 활성화하고 5/10의 조건부 목표·상한을 사용한다. 응답은 대화 원문만 기록하며 해석·공감·재계획하지 않는다. 명시적 false는 교육 행동·보호 턴 없이 우회하고 P.education을 비운다.

present_replies, absent_replies, unknown_replies는 전체 응답이 정확히 일치할 때만 사용한다. 긍정형 존재 질문이라는 자산 계약이 있어야 예/아니오를 매핑한다. 복합 답이나 시점·주체 변경은 Gateway로 해석한다.

Gateway는 quote를 한 번만 반환하고 Python이 내부 text·기본값을 채운다. 환자·보호자·가족 구성원, 수치·단위·시점과 발화 역할을 보존한다. 기본 출력 4096토큰과 한 번의 잘림 복구 최대 8000토큰을 사용하며 잘린 응답은 성공으로 기록하지 않는다. 원문은 모두 유지하되 SOAP에는 임상 사실·미해결 임상 구간만 배치한다.

질문 계약은 manifest 해시로 고정하고 D20–D23 RDF·문구를 보존한다. D40 정책·설정과 원천 점수를 구별하며 기록용 수치를 진단 가중치로 만들지 않는다. SDK 필드·상태 코드·URI·분기는 Python이 소유하고 이 README는 ZIP에서 제외한다.
