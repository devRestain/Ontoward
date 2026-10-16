# D23 한국어 런타임 수용

[D23](../../../../DECISION_STATE.md#D23)에 따라 D20의 정확한 그래프와 D22의 검증된 한국어 환자 행동을 공모전용으로 수용했다. 완전한 원천 기반 후보·매핑·문구는 추가 사용자·임상 승인 대기를 두지 않는다. 불완전한 의미·단위·획득 방식과 직접 문진할 수 없는 대상은 기술적 제외로 유지한다.

| 수용 항목 | 내용 |
|---|---|
| 원천 그래프 | 기존 9,401개 Association과 모든 임상 표현·정책을 보존 |
| 한국어 문진 | 증상 존재 475개·대상별 속성 590개·Context 243개, 합계 1,308개 |
| 진찰 요청 | 정확한 ExamMethod에 연결한 한국어 요청 1개 |
| 발화 검증 | 준비·전달 양쪽의 독립 NFC 1–30자 검사와 원래 문구 전달 |
| 실행 manifest | admitted, 원래 99,104 triples에 진찰 요청 문구 한 triple을 추가한 99,105 triples |
| 기술적 직접 문진 제외 | 진단을 전제하는 Target 15개 |

[review-approved.json](review-approved.json)은 원래 그래프 승인과 D22 문구·검증 해시를 연결한다. [graph-manifest.json](graph-manifest.json)은 문구 수용 전 manifest의 원래 바이트다. [competition-acceptance.json](competition-acceptance.json)은 공모전용 사용 승인을 기존 검토 대기 표현에 적용한다. 원래 그래프의 admission.json과 D22 생성 요청·원응답·별도 의미 대조 증빙은 덮어쓰지 않았다.

[admission.json](admission.json)은 실제 엄격한 prepare의 측정 결과이며, [verification.json](verification.json)은 프로젝트 컨테이너에서 수행한 검증과 개별 보고서를 연결한다. 유지 워크플로우 69개·원천 및 수용 제어 52개·기존 실제 RDF 상담 3개를 통과했다. 한국어 Context 양성·음성·미확인 전체 상담과 별도 EXAM 획득 경로에서는 577개 검사를 통과했다. 각 전체 상담은 집중 ROS 여섯 번 이내, SOAP 15개 필드, DIAGNOSE completed 확인으로 종료했다. 진찰 검사는 자동 후보 발견 전체 흐름과 구분해 준비 요청→실제 전달→Gateway 해석→O.exam→SOAP→확인 종료를 검증했다.

[packaging.json](packaging.json)은 부모 data/assets와 네트워크 없이 추출한 42개 파일 ZIP의 검증 결과다. 2 CPU·8 GB·읽기 전용 실행 자산 환경에서 같은 69개 워크플로우·기존 실제 RDF 상담 3개·한국어 검사 577개를 통과했다. ZIP에는 활성 manifest가 참조하는 지식과 필수 실행 파일만 들어간다. 최종 파일은 프로젝트 루트 `Tmp/packaging/ontoward-submission.zip`이다.

이번 실행은 한국어 합성 환자와 스크립트 Gateway를 사용했다. 추가 실제 모델 호출·공식 서비스 접속·공식 제출·평가·배포는 실행하지 않았다. 관측된 상태와 인계는 [데이터 상태](../../../PROJECT_STATE.md), 상담 실행은 [애플리케이션 상태](../../../../submission/PROJECT_STATE.md)가 관리한다.
