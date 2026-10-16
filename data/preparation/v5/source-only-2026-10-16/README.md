# 원천 전용 재구축 자료

[reset.json](reset.json)은 D18 정리 결과이며 [deletion-receipt.json](deletion-receipt.json)은 삭제한 이전 파일 버전을 기록한다. [reset-verification.json](reset-verification.json)은 삭제·빈 테이블·원천 해시·빈 RDF·실행 manifest 철회의 재검증 결과다. 원본 109개 파일과 12,586,084행을 보존했다.

`archives/ontology.sqlite3.gz`는 이전 투영·정규화·승인 테이블이 빈 상태인 D18 원천 DB의 원래 바이트를 보존한다. `build/archives/ontology.sqlite3.gz`는 과거 D18 빌드 DB다. D24에서 두 보관본의 전체 압축 해제 해시를 검증한 뒤 큰 확장본을 제거했다. [복원 영수증](../../../provenance/storage-cleanup-2026-10-16-archives.json)의 원래 경로·바이트 수·SHA-256에 맞게 복원해야 해당 과거 DB를 다시 열 수 있다. 현재 공유 원천 DB인 `findings-2026-10-16/ontology.sqlite3`는 원래 경로에 남아 있다. `base/`는 임상 노드·관계가 없는 v5 구조·정책·원천 목록이며 새 빌드와 모델 실행은 이 베이스를 덮어쓰지 않는다.

현재 D19 결과는 `findings-2026-10-16/`에 있다. 클래스별 범위는 로컬 `catalog/coverage.json`, 소견·분과·관찰 영역은 로컬 `catalog/finding-coverage.json`에 보존한다. [원천 검증](findings-2026-10-16/finding-verification.json)과 [저장 검증](findings-2026-10-16/storage-verification.json)은 간결한 버전 관리 기록이며 카탈로그·DB·한국어 작업 집합은 Git에서 제외한다. 완료 여부는 각 보고서와 [데이터 상태](../../../PROJECT_STATE.md)에서 확인한다.

원천 카탈로그는 14개 클래스·50,988개 노드·506,139개 관계이며 어휘 레코드는 30,680개다. ExamFinding 후보는 4개에서 14,178개로, FindingAttribute는 16개에서 6,577개로 늘었다. 이 중 ClinicalObservable 비교 차원은 6,559개다. 명시적 신체진찰 방법으로 연결한 소견은 466개이며 나머지는 획득 미확정 상태를 유지한다. BODHI 39개 분과 모두 원천 소견-질환 연결이 있지만 분과별 임상 충분성과 실행 가능성을 뜻하지 않는다. 확장 원천 그래프는 `catalog/source-findings.ttl`에 분리하며 검토된 진찰 요청 문구와 별도 admission을 기다린다.

Korean RF2 명칭은 4,083개 레코드에 연결했다. 누락 명칭의 중복 제거 작업은 26,454개, 임상 질문은 1,170개이고 향후 생성·별도 의미 대조의 계산된 호출 상한은 2,764회다. 이번 빌드의 실제 모델 호출·번역·검증 질문은 0개이며 CLI 작업과 한국어 전체 처리는 사용자 요청대로 후속 우선순위다. 기존 상담 회귀 검증과 새 한국어 후보를 주입한 상담을 구분한다.

한국어 작업 집합은 29,975,660바이트, 공유 근거 사전은 11,822,682바이트다. 모든 질문은 대상과 그 대상의 속성 연결 근거 ID만 참조하며 속성의 전역 근거를 복사하지 않는다. 상세 원천 표현·판단은 SQLite에 한 번 보존하고, `preview/sources.json`은 42,460바이트의 DB 조회 참조다. 비활성 최신 RF2 컴포넌트는 읽기 전용 뷰로 분류하므로 원천 행을 대량으로 다시 쓰지 않는다.

`build/`는 이전 D18 결과와 실패한 첫 CLI 요청의 과거 증빙이다. 그 안의 대용량 `preview/sources.json`, `interrupted-preview-…/sources.json`, `korean-workset.json`은 [압축 영수증](build/storage-compaction.json)과 로컬 `build/archives/`에 원래 해시로 보존했다. 2,283,410,136바이트를 압축 해제 검증한 41,495,205바이트로 보관하며 복원 명령은 영수증에 있다. 원본 assets·저장 베이스·요청 대장은 유지하고 기존 작업 DB의 바이트는 D24 보관본으로 보존한다. 파일 내용 크기와 APFS 공유 블록의 실제 점유량을 구분한다.

과거 D18 카탈로그는 18,548개 노드·3,634개 어휘 레코드였고 공식 한국어 1,104개를 연결했다. 당시 2,520개 번역·1,170개 질문·370회 상한의 작업 집합과 모델 응답 전 설정 오류로 중단한 첫 CLI 요청을 보존한다. 압축 보관을 새 모델 실행이나 새 작업 집합으로 취급하지 않는다.

생성 코드와 정확한 재실행 명령은 [온톨로지 도구](../../../../Dev/ontology/README.md)에 있다. 원천 패키지·계정 정보를 제외한 별도 생성 증빙 ZIP을 만들며, 임상 승인·런타임 admission·공식 제출과 구분한다.
