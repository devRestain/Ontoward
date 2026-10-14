# IBD 복수 질환 문맥 파일럿 결과

승인한 방향을 구현하고 동일한 StatPearls 진단 문단에 2단계 파일럿을 실행했다. 원자적 문장 16개가 최종 Pattern 16개로 변환되었다. Crohn disease 8개와 Ulcerative colitis 8개이며, 이전 Crohn disease의 질환–Target 쌍 8개를 모두 회수하고 Ulcerative colitis 쌍 8개를 추가했다. 전부 Feature가 없는 가능한 연관 후보이며 변환 제외는 0개다. 별도 에이전트 원문 의미 감사는 수행하지 않았다.

## 입력과 구현

- 이전 10문서 파일럿에서 선정된 `US_StatPearls/statpearls_article-131092.md` 한 문서, *Extraintestinal Manifestations of Inflammatory Bowel Disease*를 사용했다. 재추첨과 추가 문서 선택은 0회다.
- 원본 SHA-256은 `c013e8ad561c0f7264c9f5c48150c5bcbd27d8153b16fb846f0ba0fc29a3794f`다. 카탈로그: StatPearls Publishing, 2023, 영어, 질환 개요(교과서), CC BY-NC-ND. 판본은 제공되지 않아 null이다.
- CORE는 이전과 같은 History and Physical의 59줄 한 문단이며 unit_id는 `5aa45bf796643b36`이다. 같은 절의 인접 문단 문맥은 없다. 13줄의 IBD 구성 질환 정의를 별도 `GROUP DEFINITION CONTEXT`로 추가했다.
- 선정 스키마는 `topic_diseases` 배열과 nullable `group_context`로 구성된다. 그룹에는 원문 용어, 검토한 승인 구성 질환, 정확한 정의 인용·줄 범위가 들어간다. 1차는 구성 질환별 문장을 만들며 2차는 각각 단일 Disease Pattern으로 변환한다. 질환별 제한을 다른 구성원으로 확장하지 않는 지침을 두 단계에 유지했다.
- 모든 새 원자 문장과 Pattern에는 CORE와 정의의 인용이 함께 있다. 검토 패킷은 원문·원자 문장·후보 연결·그룹 메타데이터를 보존한다. 최종 ExtractionResult와 기존 510개 어휘, RDF 클래스는 변경하지 않았다.
- 이전 단일 `topic_disease` 준비 입력은 당시 버전의 증거로 보존했다. 원응답·실행·검토 기록을 새 입력으로 자동 변경하거나 현재 선정 모델로 재실행하지 않았다. 당시 선정 스키마의 정확한 바이트는 이 결과의 `baseline-source-selection.schema.json`에도 보존했다.

## 제안된 관계

| 승인 Target | Crohn disease | Ulcerative colitis |
|---|---|---|
| Abdominal pain | 가능한 연관 | 가능한 연관 |
| Abdominal bloating | 가능한 연관 | 가능한 연관 |
| Diarrhea | 가능한 연관 | 가능한 연관 |
| Constipation | 가능한 연관 | 가능한 연관 |
| Fever | 가능한 연관 | 가능한 연관 |
| Fatigue | 가능한 연관 | 가능한 연관 |
| Weight loss | 가능한 연관 | 가능한 연관 |
| Tenesmus | 가능한 연관 | 가능한 연관 |

위 표는 모델이 생성한 후보 목록이다. `features=[]`로 저장되어 expected_status·clinicalRole·importance·확률을 추가하지 않았다. 모델의 원자 문장은 원문의 “Common presenting complaints”에 따라 “commonly presents with”를 사용하며 해당 표현은 원응답과 검토 패킷에서 확인할 수 있다.

## 실행과 검증

프로젝트 소유 ontology-extraction 컨테이너와 기존 SNU Edu ChatGPT 인증 Codex CLI를 사용했다. gpt-6-luna·medium·Standard, 웹 비활성·읽기 전용, 각 호출 300초, 순차 두 호출로 제한했다. 두 호출 모두 완료·구조 검증을 통과했다. 자동 재시도·모델 전환·응답 수정·자동 재개·모델 도구 사용은 모두 0회다.

| 확인 항목 | 관측 결과 |
|---|---|
| 기존 스키마 오프라인 검사 | 49개 통과 |
| 전체 2단계 워크플로우 검사 | 83개 통과 |
| 저장 응답·입력·링크·실행·종료 재검증 | 24개 통과 |
| 1차 원자 문장 / 2차 Pattern | 16 / 16 |
| CORE와 그룹 정의 동시 인용 | 원자 문장 16/16, Pattern 16/16 |
| 변환 제외 / Feature | 0 / 0 |
| CLI 호출 실행 시간 합 | 100.645초: 1차 53.231초, 2차 47.414초 |
| 입력 / 출력 토큰 합 | 42,434 / 4,909 |
| 이전 질환–Target 쌍 누락 | 0개 |

시간은 두 프로세스가 실행된 시간의 합이며 단계 사이의 대기 시간을 포함하지 않는다. 토큰은 CLI turn.completed의 usage 기록이며 API 과금이나 전체 계정 한도로 환산하지 않았다. reasoning_output_tokens는 416개로 별도 기록되어 있다.

보호한 기존 파일 16,315개를 SHA-256으로 비교했다. 의도한 변경은 현재 `source-selection.schema.json` 한 파일이며, 이전 준비 파일 223개·제출 파일 27개·원본 assets 파일 16,050개와 환경 설정·최종 스키마·승인 어휘는 그대로다. 이전 사용자 승인 8개 후보와 검토 기록도 변경하지 않았다. 의존성 설치·이미지 빌드·새 인증·커밋은 수행하지 않았다.

## 해석과 수용 경계

이 한 문단에서는 복수 주제와 명시적 그룹 정의를 추가한 경로가 Ulcerative colitis 후보 누락을 해결했다. 선정 입력과 문맥·프롬프트를 함께 변경한 단일 사례이므로 각 변경의 독립적인 효과, 전체 코퍼스 정확도·정답 재현율, 직접 추출 대비 성능 개선은 평가하지 않았다. 질환별 제한 문장의 실제 모델 처리는 이번 한 문단에서 시험하지 않았으며 프롬프트 규칙과 결정론적 소유권 검사 범위로 남는다.

이전 Crohn disease 8개는 기존 사용자 승인 상태를 유지한다. 새 16개 결과의 사용자 최종 검토는 `not_run`이다. 별도 에이전트 원문 의미 감사는 수용 차단 단계로 추가하지 않는다. 새 후보의 구조·어휘·인용·해시·연결 검증 완료와 사용자 수용을 구분하며 URI 확정·RDF 생성·RDF/제출 수용·런타임 편입은 모두 `not_run`이다.

`candidates.json`은 최종 네 배열만 포함한다. `review-packet.json`은 문장·근거·연결·그룹 문맥을 포함하는 검토 자료이며 `case-ibd/`에 두 호출의 수정하지 않은 프롬프트·원응답·events·execution·validated가 있다. `experiment.json`, `verification.json`, `preservation.json`, `manifest.sha256`과 `inputs/`의 당시 코드·스키마 스냅샷으로 실행과 파일 식별을 확인할 수 있다.
