# Gateway 지시문과 준비 문구

D17에서 Doctor는 준비된 한국어를 직접 전달한다. 이 폴더에는 응답을 해석하는 input_parser.txt와 편집 가능한 고정 문구 texts.ko.json이 있다. 문진 질문과 답변 계약은 knowledge manifest가 지정한 questions JSON이 소유한다.

공개 설정은 다음 세 가지다.

```dotenv
ONTOWARD_KNOWLEDGE_MANIFEST=knowledge/manifest.json
ONTOWARD_PARSER_PROMPT=config/input_parser.txt
ONTOWARD_TEXTS=config/texts.ko.json
```

같은 실행 환경변수가 우선하고 경로는 submission 기준 knowledge/config 내부여야 한다. 수정은 prepare를 다시 실행하여 적용한다. 생성 프롬프트와 ONTOWARD_DOCTOR_PROMPT 설정은 없다.

texts.ko.json은 인사·Open Inquiry·속성별 명료화·잠정 설명·이해 확인·판단 정정과 SOAP 표시 문구를 담는다. 모든 실제 SAY/EXAM은 NFC 1–30자 검증을 통과해야 하며 자르지 않는다.

present_replies, absent_replies, unknown_replies는 전체 응답이 정확히 일치할 때만 사용한다. 긍정형 존재 질문이라는 자산 계약이 있어야 예/아니오를 매핑한다. 복합 답이나 시점·주체 변경은 Gateway로 해석한다.

Gateway는 정확한 현재 인용, 주체·시간·관찰·에피소드와 제공된 문맥 참조를 보존한다. Doctor 질문·설명을 환자 소견으로 만들거나 불확실 값을 음성으로 바꾸지 않는다. 과거 문맥과 어휘는 D17 한도로 투영하고 전체 원문은 증례 상태에 남긴다.

질문 계약의 text·answer_type·affirmative·interviewable·reason과 준비 교육은 해시로 고정한다. 현재 임상 RDF는 D15 승인 배치이며 질환별 치료·교육 계획과 D16 초안의 런타임 수용은 별도다. SDK 필드·상태 코드·URI·분기는 Python이 소유하고 이 README는 ZIP에서 제외한다.
