# 새 지식 DB 추출

D49의 독립 실행기는 네 원자료에서 새 `v5-enum-1` 번들을 만든다. 이미지는 **ontoward-extraction:local**, 진입점은 `python -m ontoward_extraction`이다. 이번 구현에서는 이미지와 오프라인 합성 파이프라인만 검증했다. **실제 로그인·유료 모델 호출·실제 DB 생성·실제 설치는 실행하지 않았다.** 현재 제출 지식 manifest는 없으며 실제 번들이 설치되기 전 `prepare()`와 정식 패키징은 `knowledge_bundle_not_installed`로 실패한다.

| 공급자 | 인증·전송 | 초안 / 최종 분류 |
|---|---|---|
| nova_dev | 루트 환경의 NOVA_DEV_KEY, 선택 NOVA_API_BASE; 세션 밖 원본 SDK Client.chat | openai/gpt-6-luna / openai/gpt-6.1-sol |
| codex_subscription | 새 전용 volume의 ChatGPT device login; codex exec | gpt-6-luna / gpt-6.1-sol |
| openai_api | OPENAI_API_KEY; 공식 Responses API, 도구 없이 구조화 출력 | gpt-6-luna / gpt-6.1-sol |

모든 추출 effort는 **medium**이다. NOVA/API 출력 상한은 초안 8,000·최종 32,000토큰이며 요청 제한 시간은 600초다. Codex CLI에는 강제 출력 토큰 상한을 적용했다고 주장하지 않는다. 유한한 배치와 600초 프로세스 제한을 사용한다. 계정의 모델 접근 가능성은 실제 첫 실행에서 확인하며 오류가 나면 선택 모델을 유지한 채 중단한다. 자동 모델·공급자·계정 전환은 없다.

## 이미지와 키 없는 조회

프로젝트 루트에서 실행한다. 빌드는 Python 3.12와 현재 고정 Python 의존성, `@openai/codex@0.162.1`을 설치한다. 이미지에는 원자료·이전 DB·개발 키·인증 정보를 넣지 않는다.

```sh
docker compose build extraction
docker compose run --rm -T control status
docker compose run --rm -T control pause --run-id RUN_ID
docker compose run --rm -T verify verify --run-id RUN_ID
```

`status`와 `pause`는 키나 client를 만들지 않는다. 실행이 없으면 `not_started`를 반환한다. `verify`는 네트워크 없이 읽기 전용으로 번들·해시·실행 계약·기본 커버리지를 확인한다. 전체 모델 의미와 임상적 정확성을 검증하는 명령은 아니다.

## 실제 생성 때 선택할 실행

아래 명령은 다음 세션의 **실제 모델 호출**을 시작한다. 공급자 하나를 고른 뒤 실행한다. NOVA/API 키는 루트 `.env` 또는 명시적 환경으로 주입하며 제출 공개 `.env`에는 넣지 않는다.

```sh
# 둘 중 선택한 키 기반 경로 하나만 실행한다.
docker compose run --rm -T extraction run --provider nova_dev --install
docker compose run --rm -T extraction run --provider openai_api --install

# 구독 경로는 사용자가 전용 저장소에서 로그인한 뒤 실행한다.
docker compose run --rm codex-login
docker compose run --rm -T extraction run --provider codex_subscription --install
```

구독 로그인은 [공식 ChatGPT 인증](https://learn.chatgpt.com/docs/auth)과 [비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode)을 사용한다. `ontoward_extraction-codex-state` volume은 기존 `ontology-extraction` 인증 저장소와 별개다. 구독 실행에는 API/NOVA 키를 전달하지 않고, read-only sandbox·명시적 모델·JSON Schema·사용자 설정 무시·shell/web/agents 비활성 설정을 적용한다. 기존 인증 volume과 기존 컨테이너는 보존한다.

입력·공급자·모델·설정·프롬프트·생성 코드·스키마가 fingerprint를 정하며 `data/extraction/v5-enum/work/RUN_ID/jobs.sqlite3`에 저장한다. 공급자가 바뀌면 다른 RUN_ID의 새 빌드가 된다. 기존 RUN_ID와 다른 fingerprint를 강제로 재사용할 수 없다. 출력은 `data/extraction/v5-enum/output/RUN_ID/`다. 커스텀 설정은 [config.json](config.json)을 별도 읽기 전용 경로로 마운트하고 `--config`로 지정한다.

## 중단·재개·불명 결과

다른 터미널의 `control pause --run-id RUN_ID` 또는 worker의 SIGINT/SIGTERM은 새 작업·요청·전송 재시도를 막는다. 진행 중 한 요청은 최대 600초 동안 응답을 받고 저장·수용한 뒤 `paused`로 종료한다. Compose 종료 유예는 660초이고 자동 재시작은 없다. 쿼터 대기도 중단할 수 있다.

```sh
docker compose run --rm -T control status --run-id RUN_ID
docker compose run --rm -T control pause --run-id RUN_ID
# 같은 공급자·설정·입력을 사용한다.
docker compose run --rm -T extraction run --provider nova_dev --run-id RUN_ID --resume --install
```

완료된 job과 `neutral` 결과는 다시 호출하지 않는다. 받은 응답을 DB에 먼저 저장하므로 수용 도중 중단되어도 로컬 응답을 복구한다. 강제 종료로 유효한 저장 응답을 잃으면 `outcome_unknown`이다. NOVA는 같은 ID·payload의 지원된 복구를 사용한다. API·CLI는 원격 중복 방지를 가정하지 않고 중단한다. 운영자가 중복 실행 가능성을 수용하고 `--retry-unknown`을 추가해야 새 시도를 허용하며 이전 불명 요청은 보존한다.

NOVA만 KST 일일 호출 상한과 다음 날짜를 사용한다. API·Codex에는 NOVA 한도를 적용하지 않는다. 인증 오류·거절·모델 접근 오류는 명확하게 멈추고 공급자가 준 재시도 시점은 체크포인트와 함께 처리한다. status에는 단계·중단 상태·job/요청 상태·사용량이 나온다.

## 원자료·단계·설치

RF2 Snapshot·배포 메타데이터, BODHI 실제 8개 CSV, DDXPlus evidence/condition JSON, Astra 후보·속성·값·CPX 범위를 읽는다. DDXPlus 환자 ZIP, 옛 생성 RDF·질문·어휘·준비 SQLite, Astra의 과거 snapshot·등록 evidence·정책은 새 DB 입력이 아니다. 원자료 권한과 역할은 [DATA_USE.md](DATA_USE.md)에 기록한다.

인덱싱 → 개념/역할 정규화 → 질문/진찰 → 질환별 유한 관계 초안 → 관계별 최종 분류 → 충돌 해소 → 한 번의 결손 보완 → 컴파일/검증을 실행한다. 일반 관계는 최종 모델의 내부 지식으로 완성할 수 있지만 환자 관찰은 생성하지 못한다. 유효 형제 행은 먼저 확정하고 누락·무효 행만 유한 횟수로 복구한다.

번들은 schema·vocabulary·clinical Turtle, `attribute_roles`가 있는 질문 JSON, guideline index, manifest의 여섯 파일이다. `neutral`은 작업 DB에 완료 상태로 남고 RDF에서는 빠진다. 정성 effect와 명시적 조건·scope만 출력하며 관계 출처·confidence·reviewer·점수 정책은 출력하지 않는다.

`--install`을 주면 검증된 build 전용 파일을 `submission/knowledge/builds/RUN_ID/`에 놓고 manifest를 마지막에 원자적으로 바꾼다. 설치의 짧은 일관성 구간에는 중단을 뒤로 미룬다. 컴파일만 한 뒤 명시적으로 설치할 수도 있다.

```sh
docker compose run --rm -T extraction install --run-id RUN_ID
```

빈 guideline selections는 정상이며 Education이 모델 지식 출처를 명시한다. 선택한 원문이 있으면 문서 경로·hash·인용 검증을 유지한다. 새 실제 번들 설치 이후에만 정식 상담·패키징이 가능하다. 합성 검증 번들을 실제 DB로 설치하지 않는다.

물리적 EXAM의 실행 시점은 current다. 컴파일러는 등록된 진찰 요청에서 구체적인 current 질문 자산을 만든다. any 규칙은 그 자산의 실행 시점을 사용하며 가족 구성원이나 과거 시점을 EXAM으로 관찰했다고 만들지 않는다. 과거·가족의 문진 사실과 속성은 정확히 같은 주체/구성원/시점/관찰/episode에서만 연결한다.
