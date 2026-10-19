# BODHI-S 원자료

bodhi-s/와 original_readme.md는 공급된 upstream 자료이며 변경하지 않는다. D49는 실제 8개 CSV를 새 작업 SQLite에 읽고 개념·조건·관계·선행 조건·영향·관련성·진료과의 원래 의미를 보존한다.

condition_given_symptom과 symptom_given_condition, strong_predictor 같은 원자료 필드는 방향이 다른 입력 설명이다. 새 DB는 이를 숫자 진단 점수로 변환하지 않으며 최종 모델이 전체 조건·scope·applicability의 qualitative effect를 분류한다. 원자료에 관계가 없다는 사실을 환자의 음성 관찰로 만들지 않는다.

도구·공급자·안전한 중단/재개는 [Extraction 안내](../../Extraction/README.md), 원자료 역할과 이용 조건은 [DATA_USE](../../Extraction/DATA_USE.md)를 따른다. upstream 귀속과 LICENSE는 보존한다. 과거 준비 결과·승인·수용 ZIP은 data/에 남기지만 새 생성 정본으로 사용하지 않는다.
