# BODHI-S 원본

bodhi-s/는 공급된 upstream 데이터이고 original_readme.md는 원래 설명이다. 원본은 변경하지 않는다. 현재 v5.0 준비는 csv/nodes_condition.csv, nodes_symptom.csv, edges_present_in.csv 세 파일을 읽는다.

증상 변형은 UUID로 식별하고 자체 SCTID·루트 SCTID·nullable 원값을 분리한다. Condition은 실제 실행 역할과 공급된 RF2 대조 결과를 확인하며 모두 Disease로 등록하지 않는다.

condition_given_symptom은 질환 지지, symptom_given_condition은 문진 정렬에 사용한다. strong_predictor는 추가 점수 없이 메타데이터와 충돌 검토에 유지한다. 라벨의 숫자 변환은 Ontoward의 정렬 정책이며 확률이 아니다.

원천 변형의 조건 묶음을 유지하고 동반 소견을 지워 높은 점수를 활성화하지 않는다. 도구는 [v5.0 투영](../../Dev/ontology/README.md), 지속 preview와 provenance는 data/preparation/v5/가 소유한다. 임상 검토·제출 수용은 별도이며 upstream의 이용 조건과 귀속 표시를 보존한다.
