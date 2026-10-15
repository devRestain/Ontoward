# v5.0 전체 원천 데이터베이스

공급된 SNOMED CT International·Korean RF2의 전체 Snapshot과 BODHI-S 8개 CSV를 SQLite 준비 DB에 보존하고, 공유 Pattern·타입 Feature·질환별 Association·조건부 기여를 v5.0 RDF로 내보낸다. 실행 에이전트는 승인된 RDF만 사용하며 SQLite·원본·준비 코드는 제출에 포함하지 않는다.

`source_projection.py`는 build/export/admit 진입점이다. `database.py`는 원천·최신 컴포넌트·판단 기록을, `model_normalization.py`는 제한된 정규화 후보 호출을, `admission.py`는 배치 검토와 통합을, `v5.py`는 RDF 구성·출력을 담당한다.

D15의 `clinical_texts.py`는 데이터 소유의 한국어 번역·질문 문구를 준비한다. 누락된 증상 이름과 속성 이름을 정확히 대응하고 모든 실제 질문을 NFC 1–30자로 검증한다. 원천 관계·점수·질환별 계획은 변경하지 않는다.

## 전체 구축과 재개

프로젝트 루트에서 기존 dev 이미지를 사용한다. 출력은 새 준비 경로를 지정한다.

```sh
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev \
  python -B -m Dev.ontology.source_projection build \
  --international assets/snomed/SnomedCT_InternationalRF2_PRODUCTION_20260501T120000Z \
  --korean assets/snomed/SnomedCT_ManagedServiceKR_PRODUCTION_KR1000267_20260615T120000Z \
  --bodhi assets/bodhi/bodhi-s/csv \
  --output data/preparation/v5/my-full-build
```

이 명령은 네트워크와 개발 키를 차단한다. `--resume`을 추가하면 같은 원천·스키마·정규화 해시의 완료 단계와 현재 빌드를 재사용한다. 부분 export는 별도 interrupted-preview 디렉터리로 보존한다. 원본과 이전 준비 결과를 덮어쓰지 않는다.

모든 Snapshot TXT·release metadata·원천 CSV·라이선스·원래 설명을 수집한다. RF2 최신 행을 선택한 뒤 활성 여부를 적용하며 버전 충돌·미래 행·모듈 의존성 불일치는 중단한다. 식별자와 실행 역할은 별도로 판단한다. 필수 조건·연결 소견·단위·관계 그룹 범위를 해결하지 못하면 전체 의존 변형을 보류한다.

## 선택적인 개발 모델

모델이 필요한 원천 정규화에는 offline override를 제외하고 `--llm --max-calls N --daily-remaining N --allowance-date YYYY-MM-DD`를 명시한다. root .env의 NOVA_DEV_KEY를 기존 SDK에 전달하고 공식 NOVA origin의 세션 밖 openai/gpt-6.1-sol만 사용한다. 순차 요청당 최대 20 packet, medium, 8192 tokens다.

공유 llm-ledger.sqlite3가 KST 날짜별 요청을 전송 전에 예약한다. 실패·불명 요청도 포함해 최대 100회이며 캐시는 다시 호출하지 않는다. 원천 인용·타입·모든 필수 의미를 검증하고 전체 응답이 실패하면 중단한다. 모델 지식으로 관계·식별자·likelihood·단위·임계값을 추가하지 않는다. 중단된 모델 단계를 자동 재시도하거나 다음 날 자동 재개하지 않는다.

## 결과와 검토

| 산출물 | 역할 |
|---|---|
| ontology.sqlite3 | 전체 원천 행·위치·최신 컴포넌트·정규화·RDF·주장·판단·승인 기록 |
| report.json | 수집·투영·보류 집계와 모델 호출 감사 |
| preview/schema.ttl·vocabulary.ttl·clinical.ttl | 후보 실행 구조·어휘·임상 관계 |
| preview/manifest.json·scoring_policy.json | 스키마·registry·정규화·원천·정책 버전과 SHA-256 |
| preview/registry.json·target-roles.json | 의미 검토가 필요한 매핑·전체 발견 역할 |
| preview/sources.json | 원천 주장과 전체 투영·제외·보류 기록; 스트리밍 출력 |
| preview/feature-contributions.json | atomic/joint 조건부 점수 차분 |
| preview/review.md·review-batch.json | 검토 자료와 approved=false인 승인 양식 |
| preview/disease-target-coverage.csv | 질환·Target별 연관 수 |

SQLite의 source_files/source_rows는 원천, rf2_components는 최신 행, normalizations는 변환 판단, registry/patterns/associations/triples는 후보 표현, source_assertions/dispositions는 출처·처리 이유를 제공한다. 전체 준비 DB와 대용량 RDF·JSON·호출 대장은 로컬에 보존하고 간결한 검토·검증 증거만 버전 관리한다.

완료 DB를 다른 새 준비 경로에 내보내려면 다음 명령을 사용한다.

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev \
  python -B -m Dev.ontology.source_projection export \
  --database data/preparation/v5/my-full-build/ontology.sqlite3 \
  --output data/preparation/v5/my-full-export
```

review-batch.json의 빌드·후보 해시에 고정된 실제 승인 대상을 명시하고 모든 필수 매핑과 검토 규칙을 확인한다. 구체적인 사람의 승인 후에만 다음 명령을 실행한다.

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev \
  python -B -m Dev.ontology.source_projection admit \
  --database data/preparation/v5/my-full-build/ontology.sqlite3 \
  --review data/preparation/v5/my-full-build/approved-review.json
```

admit는 미승인·해시 불일치·미승인 의존 매핑을 거부한다. 임시 제출 복사본에서 prepare를 검증하고 새 자산을 배치한 뒤 manifest를 마지막에 교체한다. 후보 RDF는 preview_only이며 production reader는 이를 거부한다. D15는 원래 미승인 양식과 별도의 review-approved.json으로 전체 후보의 사용자 수용을 기록한다. accepted_rules와 독립 임상 검증 미실행을 구분하며 labels/questions의 데이터 경로·해시도 고정한다. 질환별 치료·추적·교육 계획과 진찰 요청은 별도 범위다.

## 검증

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/ontology/test_database.py
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/ontology/verify_database.py data/preparation/v5/my-full-build
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/workflow/test_workflow.py
```

전체 원천 검증은 모든 입력 해시·행 수, DB 무결성·처리 결과, 실제 RDF의 조건·점수·정교화·중복·에피소드 분리와 두 CPU·8 GB 조건의 로딩 자원을 확인한다. 전체 상담 검증은 합성 SDK를 사용한다. 실제 임상 검토·진단 성능·공식 제출과 구분한다. verify_v5.py는 보존된 세 Target preview를 위한 기존 검증이다.

기존 v4.2 도구와 문헌 파일럿은 [deprecated 목록](../../data/ontology/deprecated.json)에 보존하며 현재 입력이나 자동 재개 작업이 아니다. 정책은 [D08/D09/D15](../../DECISION_STATE.md#D15), 실행 결과와 후속 경계는 [루트 상태](../../PROJECT_STATE.md)·[데이터 상태](../../data/PROJECT_STATE.md)가 관리한다.
