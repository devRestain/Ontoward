# 프롬프트와 문구 수정

이 폴더는 제출 에이전트가 사용하는 LLM 지시문과 고정 문구의 편집 위치다. 수정 후 `prepare()`를 다시 실행하면 반영된다. 진료 중 파일을 자동으로 다시 읽지 않는다.

| 파일 | 수정할 내용 | 경로를 지정하는 환경변수 |
|---|---|---|
| `doctor.txt` | 선택된 질문·설명을 한국어로 표현하는 Doctor 프롬프트 | `ONTOWARD_DOCTOR_PROMPT` |
| `input_parser.txt` | 실제 발화·원래 질문 의도·원문 대화와 함께 응답을 구조화하는 Gateway 프롬프트 | `ONTOWARD_PARSER_PROMPT` |
| `texts.ko.json` | 시작 질문·Open Inquiry·엄격한 답변 어휘·미확인 표시·SOAP 문구 | `ONTOWARD_TEXTS` |

기본 경로는 `submission/.env`에 있다.

```dotenv
ONTOWARD_KNOWLEDGE_MANIFEST=knowledge/manifest.json
ONTOWARD_DOCTOR_PROMPT=config/doctor.txt
ONTOWARD_PARSER_PROMPT=config/input_parser.txt
ONTOWARD_TEXTS=config/texts.ko.json
```

같은 이름의 실행 환경변수를 설정하면 `.env` 값보다 우선한다. 경로는 `submission/` 기준이며 프롬프트·문구는 `config/` 안에, 지식 manifest는 `knowledge/` 안에 있어야 한다. 절대 경로·상위 경로·외부로 나가는 심볼릭 링크는 허용하지 않는다. 공개 설정에 인증키를 넣지 않는다.

`texts.ko.json`의 `chief_question`, `unmapped_question`, `open_question`, `clarification_question`, `ros_question`은 준비 질문이다. Doctor는 이 의도를 표현하며 실제 SAY/EXAM은 독립적인 Python 검증에서 NFC 정규화 후 1–30자여야 한다. Doctor 생성은 최초 1회와 재생성 2회까지이며 이후 같은 검증을 통과한 준비 문구를 사용한다. 그것도 실패하면 미확인·미전달로 남긴다. 문장을 자르지 않는다. `symptom_education`과 `symptom_assessment`는 원인 미확정 안내와 기록 문구다.

`present_replies`, `absent_replies`, `unknown_replies`는 **전체 답변이 정확히 일치할 때만** 처리할 수 있는 어휘다. 서로 겹치지 않게 작성한다. 예/아니오의 Python 처리는 긍정형 존재 질문으로 명시된 준비 문구에만 적용한다. 기본 ROS 문구 `{symptom}도 있나요?`를 바꾸면 이 단축 처리가 해제된다. Doctor가 표현한 질문은 실제 발화와 함께 Gateway로 보낸다. `education_acknowledgements`는 교육 후 확인에만 적용된다. “아니요, 하지만 어제는 있었어요” 같은 복합 답은 모델이 해석한다.

SOAP 형식의 자리표시자는 유지해야 한다.

- `education_format`, `plan_format`: `{text}`
- `finding_format`: `{labels}`, `{status}`, `{text}`
- `unlinked_format`: `{text}`, `{status}`
- `ros_question`: `{symptom}`
- `exam_turn_format`: `{text}`, `{turn}`
- `initial_exam_format`: `{text}`
- `status_labels`: `present`, `absent`, `uncertain`, `unknown` 키를 유지하고 표시 값만 수정한다.

증상별 HPI·Context·감별 질문은 지식 manifest의 `questions` JSON, 질환별 치료·추적·교육은 `plans` JSON에서 읽는다. `questions`는 속성 또는 대상 URI를 문구에 연결하며 `{symptom}`을 대상 명칭으로 치환한다. 단순 예/아니오를 받는 Context·증상 문구는 대상의 존재를 긍정형으로 묻도록 준비한다. `plans`는 질환 URI별 `tests`, `treatment`, `disposition`, `follow_up` 문자열과 `education` 문자열 목록이다. 진찰 문구는 RDF의 `ExamMethod.examRequestText`를 사용한다. 지식 파일을 수정하면 manifest의 SHA-256도 해당 검토·승인 절차에 따라 갱신해야 한다.

현재 승인된 임상 지식·질문·치료·교육 묶음은 없다. 임시 검증용 합성 자료는 이 제출 디렉터리에 포함하지 않는다. SDK 필드명·상태 코드·URI와 분기 조건은 Python의 실행 계약이므로 문구 파일에서 변경하지 않는다. 이 안내 파일은 ZIP에서 제외되며 `.env`가 지정한 프롬프트·문구 파일은 포함된다.
