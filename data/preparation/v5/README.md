# v5.0 준비 데이터

[full-snomed-bodhi-2026-10-15](full-snomed-bodhi-2026-10-15/report.json)은 공급된 전체 International 2026-05-01·Korean 2026-06-15 Snapshot과 BODHI-S 8개 CSV를 수집한 SQLite DB 및 후보 RDF다. 원본·라이선스·원천 설명의 해시, 모든 행, 최신 컴포넌트, 정규화, 원천 주장과 보류·미투영 판단을 함께 보존한다.

[검토 안내](full-snomed-bodhi-2026-10-15/preview/review.md), [배치 양식](full-snomed-bodhi-2026-10-15/preview/review-batch.json), [질환·Target별 집계](full-snomed-bodhi-2026-10-15/preview/disease-target-coverage.csv)에서 승인 대상을 확인한다. [원천·RDF 검증](full-snomed-bodhi-2026-10-15/verification.json)과 [격리 ZIP 검증](full-snomed-bodhi-2026-10-15/artifact-verification.json)은 기술 증거이며 임상 승인으로 대체하지 않는다.

D15의 [사용자 승인 영수증](full-snomed-bodhi-2026-10-15/review-approved.json)과 [수용 결과](full-snomed-bodhi-2026-10-15/admission.json)는 원래 preview와 별도로 보존한다. 증상 490개·속성 16개의 질문과 누락 표시 이름은 [texts](full-snomed-bodhi-2026-10-15/texts/preparation.json)에 준비하며 같은 영수증에 해시를 고정한다. 사용자 수용을 독립 임상 검증으로 표시하지 않는다.

원천 정규화의 개발 Sol 요청·응답·예약은 공용 llm-ledger.sqlite3에 보존한다. 거절된 전체 응답과 실패·불명 요청은 재시도하지 않는다. 실제 모델 사용과 검토·통합의 현재 상태는 [데이터 상태](../../PROJECT_STATE.md)가 관리한다.

[snomed-bodhi-2026-10-15](snomed-bodhi-2026-10-15/report.json)은 앞선 Abdominal pain·Cough·Fever preview이며 그대로 보존한다. registry candidate와 preview_only를 승인으로 대체하지 않으며 승인 영수증을 통한 수용만 허용한다. D15 최소 질문 외의 새 진찰 요청·치료·교육 문구는 별도 범위다.

구축·재개·export·admit·검증 명령은 [Dev 안내](../../../Dev/ontology/README.md)를 따른다. SQLite와 대용량 준비 출력은 로컬에 남기고 간결한 manifest·검토·검증 증거만 버전 관리한다.
