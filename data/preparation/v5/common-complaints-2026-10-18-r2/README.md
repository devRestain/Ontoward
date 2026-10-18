# D42 일반 호소 배치

v5.0 클래스·관계와 D41 `d41.1` 입력·추론 정책을 유지하면서 일반 호소의 어휘·한국어 표현·질문·기록 속성을 추가한 로컬 배치다. 843개 질환과 기존 9,401개 Association의 점수·조건을 유지한다. 원천 DB를 다시 적재하거나 수정하지 않았으며 환자 CSV·합성 확률·새 다운로드·모델 호출을 사용하지 않는다.

기존 490개 Symptom은 533개, ContextFactor는 243개에서 310개, FindingAttribute는 16개에서 36개, AttributeValue는 373개에서 1,153개로 늘었다. Pattern은 1,797개에서 1,925개, Association은 9,401개에서 9,955개다. 진찰 Target·방법은 각각 2개이며 새 복부 압통–촉진 경로는 원천 Finding method와 준비 요청문을 갖는다. 해당 진찰에 새 질환 가중치를 추정해 붙이지 않았다.

문진 가능한 Symptom은 475개에서 518개로 늘고, 속성이 없는 문진 가능 Symptom은 190개에서 152개로 줄었다. 한국어 대체 라벨 1,785개에는 원천 Korean RF2 표현과 별도로 작성한 구어를 구분해 보존한다. 이것은 1,785개의 새 임상 주장을 뜻하지 않는다. 질환별 서로 다른 Target 수의 중앙값은 여전히 5개다.

## 출처와 공백

- `root-audit.json`은 BODHI의 비어 있지 않은 root 590개를 모두 분류한다. 424개는 기존 역할, 7개는 복원, 146개는 첫 일반 호소 범위 밖으로 보류, 2개는 중립 역할 미해결, 11개는 식별자 미해결이다. 별도 빈 root 행 1개도 보존한다. 비활성 귀 통증 `16001004`는 활성 SAME AS 이력으로 `301354004`에 대응한다.
- `variant-audit.json`은 4,037개 변형의 모든 조건을 함께 확인한다. 해석되지 않은 동반 소견·특성·단위가 있으면 부분 조건으로 단순화하지 않는다.
- `ddxplus.json`은 증거 223개와 질환 49개의 원문·대응·보류 사유를 보존한다. 증거 118개와 범주 속성 13개를 투영하고 92개를 보류한다. 질환 17개만 기존 Disease와 정확히 연결한다. 독립 증상 연관 81개와 맥락 연결 49개를 추가 출처로 기록하며 중복은 추가 점수가 되지 않는다.
- DDXPlus의 모호한 영문 통증 양상과 `palace`로 번역된 해부학 값은 보류한다. 기본값은 양성·음성 소견으로 합성하지 않는다. 허용 범주값을 실제 단위나 질환 임계값으로 바꾸지 않는다.
- `authored-provenance.json`은 작성 자료의 출처 대장이다. 이번 입력 `authored.jsonl`은 비어 있으며 사용자가 작성하지 않은 임상 판단을 사용자 자료로 수입하지 않았다.

새 `external_association`과 `authored_association`의 정성적 기본 정책 점수는 1이다. 작성자가 명시한 지지 수준 0–4는 작성자 판단으로 기록하며 확률·typicality·음성 감점으로 해석하지 않는다. 기존 SNOMED/BODHI와 같은 Association에 겹치면 기존 출처 선택 순서를 유지한다. 같은 원천 주장의 재배포나 동의어 추가도 점수를 늘리지 않는다.

신장(`cm`)은 저신장 호소, 체중(`kg`)은 체중 감소 호소의 명시적 수치 슬롯에 등록한다. 보고한 수치는 해당 관찰·에피소드에 연결되어야 한다. 수치 자체로 저신장·체중 감소·실제 진찰·질환 지지를 만들지 않는다. 독립 측정·가족 측정이나 다른 미등록 조합을 모두 지원한다는 의미는 아니다.

## 직접 작성하는 JSONL

입력은 [작성 모델](../../../../Dev/ontology/authored.py)의 `concept`, `alias`, `attribute`, `association`, `examination` 중 하나를 한 줄에 하나씩 담는다. 모든 행은 `source.author`, ISO 날짜 `source.date`, 실제 주장 `source.assertion`을 필수로 가진다. `source.references`는 없으면 빈 목록이다. 원문 지시문을 실행하거나 문헌이 있는 주장으로 꾸미지 않는다.

아래는 형식 설명용 별칭 예시이며 이번 배치에 수입한 사용자 판단이 아니다.

```jsonl
{"type":"alias","target":"urn:ontoward:SymptomSnomedCT267036007","aliases":{"ko":["숨이 가빠서 쉬어야 해요"]},"source":{"author":"작성자 이름","date":"2026-10-18","assertion":"이 표현을 호흡곤란의 환자 표현으로 사용한다","references":[]}}
```

새 개념은 `urn:ontoward:` 로컬 ID와 영어 표준명·역할을 제공한다. SCTID를 붙이면 활성 여부와 `exact/broader/narrower` 대응을 명시한다. 상하위 대응을 SCTID와 동일한 개념으로 취급하지 않는다. ContextFactor에는 기존 열 가지 `context_type` 중 하나를 지정한다.

속성 행에는 기존 `target`, 로컬 `attribute`, `label`, `question`과 필요한 `values`를 제공한다. 수치는 `question.answer_type="quantity"` 및 명시적 `units`를, 범주는 각 값의 로컬 ID·명칭을 사용한다. 질문·진찰 요청은 NFC 1–30자다. 진단 연관 행에는 기존 `disease`, 단일 `target`, 타입이 있는 `features`, ContextFactor `applicability`를 제공한다. `support`를 생략하면 정책 점수 1을 사용한다. 다른 증상의 동시 존재나 표현 불가능한 시간 관계를 필드에서 지워 수입하지 않는다.

파일을 작성한 뒤 기존 이미지를 사용해 새 배치를 준비한다. 아래는 재실행 명령이며 현재 작성 자료에 대한 새 실행을 뜻하지 않는다. `--parent-database`는 **실행 시점의 수용 배치**를 지정하고 `--output`은 비어 있는 새 경로를 사용한다.

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml -f Dev/tests/ontology/compose.build.yaml run --rm -T --no-deps --pull never dev \
  python -B -m Dev.ontology.source_projection rebuild-common \
  --parent-database data/preparation/v5/common-complaints-2026-10-18-r2/ontology.sqlite3 \
  --authored data/preparation/v5/my-authored.jsonl \
  --output data/preparation/v5/my-common-batch
```

새 배치의 `report.json`, `authored-provenance.json`, `preview/`, `review-approved.json`과 입력 해시를 확인한다. `admit --database .../ontology.sqlite3 --review .../review-approved.json`은 승인한 계획의 정확한 후보와 문구를 검증한 뒤 manifest를 바꾼다. 부모 DB·현재 runtime·생성 코드·원천 입력이 준비 후 바뀌면 수용을 중단한다. 기존 D41 동결 ZIP·과거 수용 영수증은 보존한다.

## 검증 경계

수용 결과는 `admission.json`, 소비자 검증과 ZIP 결과는 [D42 출처·수용 기록](../../../provenance/common-complaints-d42-2026-10-18.json)을 따른다. 작은 별도 구어 집합의 검색과 실제 payload·정규화·SOAP 검증은 오프라인 프로토콜 대역을 사용한다. 실제 Luna 의미 정확도, 독립 임상 정확성, 공식 평가·점수·업로드는 실행하지 않았다. 남은 관계·역할·표현 공백은 이 배치 완료와 별개로 확인해야 한다.
