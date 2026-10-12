# 지식 데이터 디렉터리

`data/`는 Ontoward 자료의 출처·버전·라이선스·귀속 표시와 검토·준비 결과를 담당하고 추가로 채택한 원본·생성된 RDF 지식 파일을 보관한다. 주최측이 제공한 패키지는 현재의 `assets/`에 보존하며 이 디렉터리가 해당 입력의 provenance와 준비 증거를 소유한다. 환자별 대화와 진료 상태의 소유권은 `submission/`에 있다.

현재 구조는 다음과 같다. SNOMED CT·BODHI-S 자료는 후속 도입 대상이며 아래의 원본 파일명은 현재 보관 중이라는 뜻이 아니다.

```text
data/
├── AGENTS.md / README.md / PROJECT_STATE.md
├── ontology/   # 스키마·기초 어휘와 계약
├── catalog/    # 원본 경로 목록
└── provenance/ # 공모전 출처 식별
```

| 파일 또는 자료 | 역할 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 데이터 작업의 소유권과 준비 규칙 |
| [PROJECT_STATE.md](PROJECT_STATE.md) | 데이터 준비 목표와 관측한 원본·산출물 상태 |
| [ontology/](ontology/README.md) | 기본 스키마·기초 어휘·진찰 방법·소비 계약 |
| [catalog/guideline_paths.txt](catalog/guideline_paths.txt) | 원본 문서의 프로젝트 루트 기준 경로만 보관 |
| [제공 지침](../assets/guidelines/)과 카탈로그 | 제출 전 임상 추출의 입력 원본과 문서별 메타데이터 |
| [공개 샘플](../assets/nova-samples-2026/) | 초기 정보, 시뮬레이터 입력, 검토용 기록을 분리할 기준 |
| [참고 벤치마크](../assets/nova-benchmarks-2026/) | 후속 행동 선택·문진·기록 작성 자체 평가 자료 |
| SNOMED CT 원본 및 출처 정보 | 선택한 판본의 임상 용어와 검증 가능한 개념 연결의 기준 |
| `nodes_condition.csv` | BODHI-S의 질환 및 관련 임상 개념 |
| `nodes_symptom.csv` | BODHI-S의 증상 원형과 수식 정보가 있는 증상 변형 |
| `edges_present_in.csv` | BODHI-S의 증상 변형과 질환 사이의 연관 정보 |
| [provenance/competition.json](provenance/competition.json) | 두 공모전 발표 원본·변환 Markdown·SDK의 출처 식별과 해시 |

D08의 기본 스키마·기초 어휘는 클래스 11개, 객체 관계 12개, 데이터 속성 6개와 증상 42개·속성 13개·계통 15개·범주 값 77개·진찰 방법 24개를 포함한다. 통증은 ChestPain·AbdominalPain·Headache·Dysuria 등 구체적인 주호소로 나누고 세부 위치는 평면 속성 값으로 유지한다. 사용자는 2026-10-12 [영어 어휘 목록](ontology/vocabulary-candidates.md)의 Disease 100개·Symptom 100개·ExamFinding 60개·AttributeValue 100개·ContextFactor 60개·Test 40개·ExamMethod 50개를 작업 기준으로 승인했다. [승인 기록](ontology/vocabulary-approval.json)은 승인 당시 파일 SHA-256과 510개 항목 수를 보존한다. 새 통증 개념의 미지정 계통 분류와 RDF 수용은 후속 준비 계약에서 정하며 이번 승인 기록으로 기초 Turtle은 변경하지 않는다. 원문·정규화·해석 불확실성을 구분하고 같은 에피소드의 위치도 각각 확인했을 때만 병렬 기록한다. 질환·패턴·특징·진찰 소견·검사 인스턴스의 임상 관계는 후속 문헌 추출·검증 단계에서 준비한다.

D09의 준비 순서는 영어 어휘 작성 → 사용자 승인 → Pydantic 추출 스키마·준비 계약 제작 → gpt-6-luna·medium 추출 파일럿 검증이다. 어휘 승인은 완료했으며 구체적인 입력·예산·검증·검토 계약은 후속 과제에서 정한다. 기존 추출 구현과 고정 여섯 문서 파일럿 결과는 삭제한 상태다. 코퍼스에는 16개 출처 그룹의 임상 문서 15,904개, 약 597.2 MB가 있지만 이는 원본 크기이며 RDF 크기나 메모리 측정값이 아니다. 카탈로그·원문 위치·제목·기관·연도·언어·라이선스를 보존하며 자료 존재 확인을 전체 품질·제출 조건 검토나 임상 관계 생성으로 취급하지 않는다.

원본은 assets/guidelines/에 그대로 보존한다. catalog/guideline_paths.txt의 15,904개 항목은 catalog.csv를 기준으로 만든 경로만의 목록이며 복사본·추출 결과·자료 승인 목록이 아니다. 경로 기준은 프로젝트 루트이고 제목·판본·라이선스의 확인은 원본 카탈로그와 문서에서 수행한다.

긴 문서는 절별로 추출하되 문서 단위 결과로 모아 실패·검토 대기·제외·승인 상태를 기록한다. 개별 임상 관계의 원본 경로·절·적용 조건·검토 결과는 외부 준비 자료에서 유지하고 실행 그래프에는 provenance 노드를 넣지 않는다. 공통 개념 URI를 보존하고 검토와 제출 조건 확인을 통과한 결과만 출처별로 묶는다. Turtle로 바꾼 관계·발췌·번역의 제출 가능 여부도 문서별로 확인한다. SOAP A.evidence는 이 출처 기록을 설명하는 필드가 아니라 주진단 판단에 사용한 실제 문진·신체진찰 소견의 목록이다.

새 준비 계약에서 원문 근거·누락·임상 의미·RDF 제약 검토와 중단·재개 기준을 정한다. 자동 검증·전체 검토·표본 검토를 구분하고 품질 수용과 제출 수용은 별개로 관리한다. 문서별 이용 조건은 카탈로그와 원문에서 확인하며 지속 보관할 응답·검토 기록의 위치는 data 안에 정한다.

현재 ontology/의 영어 검토 목록·스키마·기초 어휘, catalog/·provenance/와 관리 문서를 유지하며 문헌 추출 응답·임상 관계 후보·임상 검토 결과·임상 Turtle·제출 manifest는 없다. 새로운 준비 산출물 경로와 형식은 D09에서 정한다. 후속 실행은 스키마·어휘와 임상 묶음을 하나의 RDFLib 그래프에 로드하므로 파일 분할만으로 메모리 절감을 주장하지 않는다. 대표 임상 추출에서 triple 수·Turtle 크기·전체 로딩 시간·최대 메모리·주요 조회 시간을 측정하고 실제 제출물의 파일 수·크기를 확인한다.

후속 SNOMED CT·BODHI-S 도입에서 위 CSV 세 파일을 사용한다. BODHI-S의 증상 변형은 원래 UUID를 유지한다. 비어 있을 수 있는 원본 SNOMED 식별자, 증상 원형의 SNOMED 식별자, 선택한 SNOMED CT 판본에서 확인한 개념 연결을 서로 구분한다. BODHI의 연관 강도는 원본의 정성적 신호로 보존하며, 임상적으로 보정된 진단 확률로 간주하지 않는다.

`assets/`의 원본은 이동·수정·중복 복사하지 않는다. 추출·후보 검증·RDF 생성·묶음 구성 코드와 준비 스키마·프롬프트는 `Dev/`, 제출 에이전트와 실행 조회 API는 `submission/`에서 구현한다. 추가 원본·지속 응답·provenance·검토·준비 결과는 이 디렉터리가 소유하며 예정된 준비·추출·지식 디렉터리에 별도 운영 상태를 만들지 않는다. 공개 샘플의 대본·진찰표·모범 기록과 벤치마크 정답은 임상 지식과 Doctor 입력에서 분리한다. 전체 동작과 파일 구조는 [PRD](../PRD.md), 판본·연결 순서·언어와 D07·D08·D09 선택은 [중앙 결정 문서](../DECISION_STATE.md)를 따른다.

승인된 자연어 어휘를 후속 작업 기준으로 사용하고 동의어 연결·속성 분해·대상별 세부 적용·외부 코드 매핑은 준비 계약에서 구체화한다. 추가 외부 용어는 별도 검토 대상으로 두며 기존 어휘 승인으로 자동 수용하지 않는다. 대안 Pattern의 검색 구조 검증에 사용하는 합성 RDF는 임상 지식으로 수용하지 않는다. 도구와 로그인 절차는 [Dev 안내](../Dev/README.md), 실제 수행한 검증과 임상 검증의 한계는 [데이터 상태](PROJECT_STATE.md)에 있다.

후속 BODHI 자료의 구조와 의미는 [공식 저장소](https://github.com/eka-care/BODHI)에서 확인할 수 있다.

실제 제출 자산은 검토·승인 후 submission/knowledge/에 배치한다. RDFLib 접근 코드는 [submission/knowledge/graph.py](../submission/knowledge/graph.py), 실행 객체·공통 환자 상태는 submission/agents/가 소유한다. 현재 제출 knowledge에는 Python 코드와 안내만 있으며 runtime manifest·Turtle·schema JSON은 없다. 이 data/ 디렉터리는 개발·준비·출처 기록용이고 제출 코드나 테스트가 참조하는 파일 의존성이 아니다.
