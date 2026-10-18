# DoctorEar·DoctorBrain·DoctorMouth 설정

DoctorEar의 문맥 분석은 input_parser.txt, DB dictionary 정규화는 normalization.txt가 담당한다. DoctorBrain의 질환 순위·다음 행동은 brain.txt, DoctorMouth의 수집 중 공감은 empathy.txt가 담당한다. education.txt는 working diagnosis와 미완료 평가를 유지한 영어 P, education_doctor.txt는 조건을 보존한 한국어 설명을 생성한다. 임상 질문 계약과 한국어 자산은 knowledge manifest가 소유한다.

공개 설정은 submission/.env에 두며 같은 실행 환경변수가 우선한다.

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

같은 실행 환경변수가 우선하고 경로는 submission 기준 knowledge/config 내부여야 한다. 수정은 prepare를 다시 실행하여 적용한다. 별도 일반 발화 생성 프롬프트와 ONTOWARD_DOCTOR_PROMPT 설정은 없다. Brain 임상 판단·영어 P는 high, Ear·Mouth는 medium이며 모델은 openai/gpt-6-luna다.

texts.ko.json은 새 인사, 공통 intake 네 슬롯, 기본 병력 다섯 영역, Open Inquiry·명료화·공감 fallback과 영어 SOAP 표시 문구를 담는다. 모든 SAY/EXAM은 NFC 1–30자 검증을 통과하며 절단하지 않는다.

Education은 기본 활성화하고 5/10의 조건부 목표·상한을 사용한다. 응답은 대화 원문만 기록하며 해석·공감·재계획하지 않는다. 명시적 false는 교육 행동·보호 턴 없이 우회하고 P.education을 비운다.

수집 입력은 항상 문맥 분석 LLM을 호출한다. 고정 답 목록은 호출을 생략하는 용도가 아니며, 해석 뒤 정확한 모름·수긍을 소견으로 오인하지 않는 방어에만 사용한다. Education 답변은 기록 전용이다.

문맥 분석은 정확한 인용과 주체·시점·부정·검색 힌트를, 정규화 호출은 공급 DB URI와 (+)/(-)·AttributeValue·등록 수치 형식만 반환한다. D43은 target/attribute 진술과 관찰용 수치를 분리하고 null·기본 필드 반복을 줄인다. 문맥 분석 1회와 무효 행·형식 복구 1회를 사용하며 초기 우선 호소가 미확정이면 집중 검토 1회를 추가한다. 유효 행은 고정한다. 정규화 배치별 세 의미 단계와 형식 복구 1회를 공통 예산 안에서 사용하고 마지막에는 Python이 유효 dictionary를 완성한다. 원문과 자유 영어 요약은 SOAP·진단·질문·Education·공감에 보내지 않는다.

질문 계약은 manifest 해시로 고정하고 현재 D42 임상 자산과 이전 RDF·문구 수용을 보존한다. D46은 임상 messages 전체를 64 KiB로 제한하고 질환·질문 지역 참조를 검증한다. 임상 revision별 정상 순위 판단과 한 번의 계약 복구를 허용하며 유효 순위는 행동만 복구할 때 유지한다. 원천 점수 메타데이터로 수용 순위를 재정렬하지 않고 기록용 수치·age·sex에 임의 진단 조건을 만들지 않는다. SDK 필드·상태 코드·URI·분기는 Python이 소유하고 이 README는 ZIP에서 제외한다.
