# 무작위 StatPearls 10문서 자료 선별·2단계 파일럿 결과

2026-10-13 KST에 새 무작위 10문서를 선별하고 통과 문서의 진단 단위 하나에 2단계 모델 호출을 수행했다. 2026-10-14 사용자는 최종 Crohn disease 관계 8개를 수용했다. 현재 후보 검토 결과는 [사용자 검토 기록](user-review.json)과 [검토된 후보](user-reviewed.json)에 보존한다.

## 모집단과 실행 경계

- 모집단: 카탈로그에 등재된 실제 nonsymlink StatPearls Markdown 9,651개. 질환·어휘로 사전 필터하지 않았다.
- seed: `1782347085644647286`. 정렬된 경로 모집단에서 비복원 추출 10개.
- 사용자 선택: 문서마다 대표 진단 단위 하나, 총 최대 20회 호출, 재추첨·재시도·자동 재개 없음.
- 실행: 프로젝트 소유 ontology-extraction 컨테이너, gpt-6-luna·medium·Standard·웹 비활성·독립 읽기 전용 순차 호출.
- 자료 선별은 에이전트의 문서 역할 확인이다. 최종 후보 수용은 사용자 검토 기록을 따른다.

## 선별 결과

| 번호 | 문서 | 결과 | 근거 |
|---|---|---|---|
| 1 | Wound Dressings | 제외 | 상처 드레싱·치유와 처치 중심 |
| 2 | Physiology, Muscle | 제외 | 근육 생리학 |
| 3 | Anatomy, Head and Neck, Eye Extraocular Muscles | 제외 | 외안근 해부학 |
| 4 | Pubovaginal Sling | 제외 | 슬링 수술·시술 중심 |
| 5 | Pearly Penile Papule | 제외 | 본문이 정상 해부학적 변이로 설명 |
| 6 | Cat Scratch Disease | 제외 | 질환 중심이지만 승인 Disease 어휘에 없음 |
| 7 | Anatomy, Bony Pelvis and Lower Limb, Knee | 제외 | 무릎 해부학 |
| 8 | Extraintestinal Manifestations of Inflammatory Bowel Disease | 통과 | 질환 중심 IBD 장; Crohn disease·Ulcerative colitis를 명시 |
| 9 | Conversion Weights | 제외 | 무게 단위·환산 안내 |
| 10 | Neuroanatomy, Prefrontal Association Cortex | 제외 | 전전두엽 신경해부학 |

모든 문서의 카탈로그 표시는 질환 개요(교과서)였지만, 본문에는 해부학·생리학·시술·기술 안내도 포함되어 있었다. 카탈로그 유형과 제목만으로 질환 중심 자료임을 확정하지 않았다. Cat Scratch Disease를 다른 승인 질환으로 치환하거나 새 어휘를 추가하지 않았다.

## 처리 단위와 두 단계 결과

통과한 문서는 Extraintestinal Manifestations of Inflammatory Bowel Disease이다. 원문 13줄은 IBD를 Crohn disease와 ulcerative colitis로 구성되는 범주로 설명한다. 선정 기록의 topic_disease는 문서가 다루는 주제 중 하나인 Crohn disease이며, IBD와 동일 개념이라는 뜻은 아니다.

모델 출력 전에 History and Physical의 유일한 문단인 원문 59줄을 고정했다. 같은 절의 앞뒤 문단이 없어 CONTEXT는 비어 있다.

| 단계 | 관측 결과 |
|---|---|
| 1차 원자 문장 | IBD 환자 표현을 사용하는 문장 8개와 Crohn disease 개념 참조 |
| 2차 구조화 | Crohn disease의 0-Feature Pattern 8개, 제외 문장 0개 |
| 자동 검증 | 두 응답 모두 스키마·승인 개념·인용·CORE 범위·연결 검증 통과 |
| 사용자 검토 | 기존 후보 8개를 변경 없이 수용 |

최종 Target은 Abdominal pain, Abdominal bloating, Diarrhea, Constipation, Fever, Fatigue, Weight loss, Tenesmus이다. 검토 결과는 전체 검증 패킷 해시에 연결되며 RDF 생성이나 제출 자산 수용을 수행하지 않는다.

## 실행·검증 증거

- 저장된 호출·응답과 고정 입력에 대한 최종 검증 16개 통과.
- 실제 호출 2회 / 선택한 최대 20회. 자동 재시도 0회, 모델 도구 사용 0건, 기록된 활성 모델 프로세스 0개.
- 호출 프로세스의 기록된 경과시간 합계 104.485초. 전체 선별·검토·도구 승인 시간을 포함한 파일럿 총 시간은 아니다.
- CLI 보고 입력 토큰 39,015개, 출력 토큰 1,604개.
- 사용자 후보 검토는 기록되었다. 독립 clinician gold·직접 추출 비교·공용 프롬프트 수정·RDF 생성 및 수용·제출은 not_run.

## 다음 제안

현재 선정 입력은 topic_disease 하나만 가진다. Ulcerative colitis에도 공통 관계를 제안하려면 문서의 복수 질환과 IBD의 문서상 구성 질환을 입력 맥락으로 제공하고, 공유 진술에서 질환별 원자 문장과 Pattern을 각각 만드는 방법을 권장한다. 모델 실행이나 스키마 변경은 아직 수행하지 않았으며, 현재 Ulcerative colitis 후보는 생성되지 않았다.

- [선별 근거](screening.json)
- [첫 단계 원응답](document-8/call-01-atomic/response.json)
- [두 번째 단계 원응답](document-8/call-02-conversion/response.json)
- [사용자 검토](user-review.json)
- [검토된 후보](user-reviewed.json)
- [최종 검증](verification.json)
