# v5.0 원천 preview

[snomed-bodhi-2026-10-15](snomed-bodhi-2026-10-15/report.json)은 공급된 International 2026-05-01·Korean 2026-06-15 RF2와 BODHI-S를 Abdominal pain, Cough, Fever에 제한하여 투영한 결과다.

schema·vocabulary·clinical Turtle, 공개 scoring_policy, version/hash manifest, 후보 registry, raw sources/dispositions, 조건부 feature-contributions를 함께 보관한다. [verification.json](snomed-bodhi-2026-10-15/verification.json)은 원천 해시·모듈·제외/보류와 실제 그래프의 2→1→4 점수 대체 등을 검증한다. 환자 관찰은 합성이다.

registry는 candidate, 자산은 preview_only다. identifier 존재 확인과 의미상 올바른 매핑·임상 검토·제출 admission을 구분하며 자동으로 submission/knowledge/에 복사하지 않는다. 실제 모델 호출·진단 성능·공식 SDK 실행은 수행하지 않았다.

현재 준비 명령은 [Dev 안내](../../../Dev/ontology/README.md), 수용과 다음 검토 범위는 [데이터 상태](../../PROJECT_STATE.md)에서 확인한다.
