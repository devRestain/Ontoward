# v5.0 원천 투영

현재 온톨로지 준비 코드는 [source_projection.py](source_projection.py)와 [v5.py](v5.py)다. 공급된 SNOMED CT International·Korean RF2와 BODHI-S를 읽어 공유 Pattern·타입 Feature·질환별 Association·조건부 점수 차분을 만든다. 모델 호출·원본 변경·다운로드는 수행하지 않는다.

첫 범위는 Abdominal pain, Cough, Fever다. 아래 명령은 프로젝트 루트에서 기존 dev 이미지로 실행한다. 출력은 새 경로 또는 비어 있는 경로를 사용한다.

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev \
  python -B -m Dev.ontology.source_projection \
  --international assets/snomed/SnomedCT_InternationalRF2_PRODUCTION_20260501T120000Z \
  --korean assets/snomed/SnomedCT_ManagedServiceKR_PRODUCTION_KR1000267_20260615T120000Z \
  --bodhi assets/bodhi/bodhi-s/csv \
  --output data/preparation/v5/my-preview
```

RF2의 최신 행·활성 상태·모듈 의존성을 확인하고 원천 파일 해시를 고정한다. BODHI UUID와 raw SCTID를 구분하고 Condition의 실행 역할을 확인한다. 원천 변형의 조건을 유지하며 다른 소견·단위·수식 범위를 해결하지 못한 필수 조건은 전체 변형의 이유를 남기고 보류한다.

| 산출물 | 역할 |
|---|---|
| schema.ttl·vocabulary.ttl·clinical.ttl | v5.0 구조·후보 어휘·제한된 임상 표현 preview |
| scoring_policy.json·manifest.json | 공개 정책과 스키마·registry·정규화·원천·파일 해시 |
| registry.json | 식별자 확인과 의미 매핑 검토를 구분한 후보 등록부 |
| sources.json | 원천 주장·행 위치·원값·제외와 unresolved 이유 |
| feature-contributions.json | 조건부 atomic/joint 점수 차분 |
| report.json | 투영 집계와 preview_only 수용 경계 |

검증은 다음과 같다. 두 번째 명령에는 생성한 preview 경로를 지정한다.

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/workflow/test_workflow.py
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/ontology/verify_v5.py data/preparation/v5/snomed-bodhi-2026-10-15
```

첫 검증은 임시 제출 복사본의 합성 SDK 전체 흐름이다. 원천 검증은 실제 파일·그래프와 합성 환자 관찰에서 복통 2→1→4, 공유 Pattern, atomic/joint 차분, 에피소드·출처 중복과 보류 경계를 확인한다. 임상 검토·실제 진단 성능·제출 자산 admission·공식 SDK 호출은 포함하지 않는다.

기존 v4.2 SNOMED 및 문헌 추출 코드·prompt는 제거했다. 보존할 과거 schema·JSON 인터페이스·승인 기록·파일럿 자료는 [deprecated.json](../../data/ontology/deprecated.json)에 명시되어 있으며 현재 명령의 입력이나 재개할 작업이 아니다. v5.0은 해당 인터페이스와 호환 변환을 만들지 않는다.

규칙은 [D08/D09](../../DECISION_STATE.md#D08), 구현·검증 진행은 [루트 상태](../../PROJECT_STATE.md), 원천 preview와 검토 경계는 [데이터 상태](../../data/PROJECT_STATE.md)가 관리한다.
