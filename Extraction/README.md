# 새 지식 DB 추출

D49의 독립 실행기는 네 원자료에서 새 `v5-enum-1` 번들을 만든다. 이미지는 **ontoward-extraction:local**, 진입점은 `python -m ontoward_extraction`이다. 이미지·합성 파이프라인과 실제 RF2/CSV의 읽기 전용 파싱을 검증했다. 모델 생성·설치는 별도 실행이다. 실제 번들이 설치되기 전 `prepare()`와 정식 패키징은 `knowledge_bundle_not_installed`로 실패한다.

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

## 실행·진행 확인·로그

요청 배치는 `config.json`의 `batch_size`인 **10개로 고정**한다. 출력 누락·형식 오류·출력 중단·과거 재시도 때문에 자동으로 5→2→1개로 줄이지 않는다. 유효한 결과는 보존하고 미완료 작업만 다음 10개 배치에 넣으며, 단계 말미에 남은 작업만 더 작은 배치가 된다. 작업별 출력 검증 6회 상한과 일일 쿼터는 유지한다. `running=10`은 병렬 요청 10회가 아니라 **요청 한 건에 들어간 작업 10개**를 뜻한다.

이전 자동 축소 버전의 정규화 실행은 먼저 안전하게 중단한 뒤 아래 순서로 옮긴다. 입력·설정·모델·프롬프트·임상 계약이 같고, 모든 요청의 결과가 확정된 paused 체크포인트만 허용한다. 원본과 완료 결과·재시도 횟수·원본 응답·사용량을 보존한 새 fingerprint를 만들고, 복구 명령에서는 모델을 호출하지 않는다. 불명 요청이 있으면 이 복구를 거절한다.

```sh
bash Extraction/extraction.sh pause --run-id OLD_RUN_ID
# status에서 paused를 확인한 뒤 실행한다.
docker compose build extraction
bash Extraction/extraction.sh recover-batch --run-id OLD_RUN_ID
# 복구 출력의 새 RUN_ID를 사용한다.
bash Extraction/extraction.sh resume --provider nova_dev --run-id NEW_RUN_ID --install
```

실행 도중 다른 작업이 런타임 reader를 변경했다면 새 정본으로 빌드한 이미지의 `runtime_contract`가 달라 복구가 거절될 수 있다. 이 검사를 우회하거나 정본을 되돌리지 않는다. 이번 배치 수정 이미지는 기존 체크포인트 이미지 `sha256:7e98251763fff539605c50dd15ae22d0b4b1f914bc632ce45a490f5d11a95138`에 추출기 수정만 올려 지식 계약을 보존했다. 재현용 Dockerfile과 검증은 `Tmp/extraction-batch-repair-2026-10-20/`, 영속 증빙은 `data/provenance/extraction-batch-repair-2026-10-20.json`에서 확인한다.

프로젝트 루트의 Bash helper는 stdout·stderr를 화면과 `data/extraction/v5-enum/logs/<UTC시각>-<PID>.log`에 함께 보존한다. 실패 종료 코드도 유지한다. `latest.log`는 가장 최근 로그를 가리킨다.

```sh
# 선택한 공급자로 새 빌드를 시작하고 콘솔 로그를 저장한다.
bash Extraction/extraction.sh run --provider nova_dev --install
```

다른 터미널에서 조회한다. status/watch는 키나 모델 client를 만들지 않고 SQLite를 읽기 전용으로 열며, watch의 Ctrl+C는 조회만 끝낸다.

```sh
bash Extraction/extraction.sh status
bash Extraction/extraction.sh watch
bash Extraction/extraction.sh logs
# 한 빌드만 확인하거나 갱신 간격을 바꾼다.
bash Extraction/extraction.sh watch --run-id RUN_ID --interval 3
```

출력에는 단계·파일 완료 수·transaction으로 확정한 레코드 수·현재 파일 cursor·단계별 job 상태·요청 상태·기록된 모델 호출 수·최근 갱신·오류와 최대 세 작업의 검증 원인이 나온다. 실행 로그의 `request_started`는 전송할 배치를, `request_validated`는 수용·무효 건수와 검증 원인을 보여준다. 시도 상한을 소진한 작업만 failed가 되며 아직 시도하지 않은 작업은 pending으로 남는다. 파일 크기와 뒤 단계의 작업량이 다르므로 파일 수를 전체 완료율이나 남은 시간으로 표시하지 않는다. JSON이 필요하면 기존 `docker compose run --rm -T control status`를 사용한다.

`docker compose run --rm`으로 이미 종료·삭제한 컨테이너의 과거 콘솔은 복구할 수 없다. 기존 실행도 DB의 오류와 cursor는 status에서 확인할 수 있다. 위 helper로 시작한 이후의 콘솔은 logs 명령으로 계속 읽을 수 있다.

### RF2 인덱싱 오류가 난 기존 빌드

실패 run `218abbb17b1438be463b58870fab9d6b`는 RF2 TSV를 일반 CSV의 quote 규칙으로 읽은 버전이다. 실제 255자 이하 term의 따옴표를 해석하다 `field larger than field limit (131072)`가 발생했고, 저장된 term 41개도 원문과 달랐다. 이 run은 보존하되 재개하지 않는다. 단순한 메모리/field limit 증설이나 같은 이미지 재시작으로 고칠 수 없다.

수정 버전은 RF2를 quote 해석 없는 TSV로, BODHI를 정상 CSV로 구분한다. 실제 긴 필드도 처리하되 열 수·CSV 형식 오류는 파일/줄과 함께 실패한다. 수정 코드의 fingerprint가 달라지므로 새 run을 시작하면 별도 DB가 만들어지고 기존 run은 자동 재사용하지 않는다. 컨테이너·인증 volume·기존 DB를 지울 필요가 없다.

```sh
# 수정 이미지가 없다면 빌드한다. 현재 작업에서는 이미 빌드했다.
docker compose build extraction
# 이 오류의 복구는 새 빌드다. 실패한 기존 ID에 --resume을 붙이지 않는다.
bash Extraction/extraction.sh run --provider nova_dev --install
```

정상적인 일시 중단을 재개할 때는 **수정 이미지에서 새로 만든 RUN_ID**와 동일 fingerprint를 사용한다.

```sh
bash Extraction/extraction.sh pause --run-id NEW_RUN_ID
bash Extraction/extraction.sh resume --provider nova_dev --run-id NEW_RUN_ID --install
```

### 정규화 `output_contract_failed:normalize` 복구

스키마 전달이 누락된 NOVA 어댑터는 Python에서 JSON Schema를 받아도 SDK의 messages에 넣지 않았다. 프롬프트는 스키마 준수를 요구했지만 모델은 `uri`, `canonical_name`, `label_ko`처럼 실행 계약과 다른 구조를 만들 수 있었다. 수정 버전은 실제 system 메시지에 스키마 전체와 정확한 최상위 `results`, `job_id`, 개념 필드를 넣는다. NOVA는 프롬프트로 형식을 요청하고 Python이 엄격하게 수용한다. API·Codex의 native JSON Schema 경로는 유지한다.

컨테이너를 다시 만드는 것만으로 기존 이미지의 이 결함은 고쳐지지 않는다. 코드가 바뀌면 fingerprint도 달라지므로 예전 ID를 강제로 `--resume`하지 않는다. **원자료 인덱싱 완료·NOVA 정규화 실패·수용 결과 0개·모든 요청 처리 완료** 조건을 만족하는 이 오류에 한해 명시적 오프라인 복구를 제공한다. RF2 파싱이 잘못된 이전 인덱스에는 사용할 수 없다.

```sh
# 수정 이미지가 없다면 빌드한다. 모델 호출이나 로그인을 하지 않는다.
docker compose build extraction
# 기존 실행이 종료된 뒤, 아래 복구를 한 번만 실행한다.
bash Extraction/extraction.sh recover --run-id OLD_RUN_ID
```

복구는 네트워크와 키 없는 `recovery` 서비스를 쓴다. 실제 원자료 hash·설정·모델·파서·스키마·실행 계약의 일치를 확인한 뒤 SQLite backup으로 별도 fingerprint의 DB를 만든다. 원본 DB는 보존한다. 과거 요청·응답·사용량은 복사하고, 이전 실패/시도 횟수는 새 DB의 recovery metadata와 `recovery.json`에 기록한다. 새 계약의 시도 횟수만 0에서 시작하며 NOVA 일일 사용량은 유지한다. 수용된 결과·불명 요청·변경된 입력이 있으면 거절한다.

완료 출력의 새 `run_id`는 `ready` 상태다. 이 명령 자체는 모델 생성이나 설치를 시작하지 않는다. 이미 복구했다면 다시 복구할 필요 없이 새 ID로 조회·재개한다. 원본 실패 ID의 일반 resume 제한은 그대로다.

```sh
bash Extraction/extraction.sh status --run-id NEW_RUN_ID
# 아래 명령부터 실제 NOVA 요청을 시작한다. 완료되면 검증 후 설치한다.
bash Extraction/extraction.sh resume --provider nova_dev --run-id NEW_RUN_ID --install
```

### 정규화 중 행동 문구 오류와 안전한 중단

`invalid_rendered_korean_length_or_normalization` 또는 `concepts.N.question`의 검증 오류는 해당 행을 재시도한다는 뜻이다. 같은 응답의 유효한 행은 이미 저장된다. `pause_requested=true`, `state=paused`, `error=null`이면 안전한 중단 요청을 처리한 상태다. 진행 중이던 응답까지 저장한 뒤 종료하며, 장애로 응답을 잃은 상태와 구별한다.

정규화 단계는 개념·역할을 만들고 실행 문구는 다음 questions 단계가 만든다. 정규화 응답의 `question`, `exam_text`, `attribute_role.clarification`은 원본 응답에 보존하되 수용 전에 null로 제외한다. 질문 생성에서는 한국어 Hangul·NFC·치환 후 1–30자를 검증하고 `affirmative=true`는 presence에만 허용한다. duration·quantity 이외 질문에는 units를 넣지 않는다. 오류에는 필드·실제 길이·언어·검증 이유가 나온다.

수정 전 버전에서 이 오류가 반복되면 먼저 안전하게 일시 중단하고 종료를 확인한다. 이후 **완료된 원자료 인덱스·동일한 입력/임상 계약·처리 완료된 요청·행동 문구 오류만 있는 정규화 단계**에서만 별도 복구를 실행한다.

```sh
bash Extraction/extraction.sh pause --run-id OLD_RUN_ID
bash Extraction/extraction.sh status --run-id OLD_RUN_ID
# paused로 종료한 뒤 실행한다. 새 모델 호출은 하지 않는다.
bash Extraction/extraction.sh recover-text --run-id OLD_RUN_ID
```

복구는 원본 DB와 이미 done인 결과 바이트·시도 횟수를 보존한다. 별도 fingerprint의 복사본에서 미완료 행의 최신 저장 응답을 로컬로 다시 검증한다. 모델 재호출이나 사용량 중복 집계 없이 회복할 수 있는 행을 done으로 저장하고, 나머지는 새 계약의 시도 예산으로 남긴다. 과거 복구 이력·요청·응답·사용량도 유지한다. 불명 요청이나 다른 임상 검증 오류가 있으면 거절한다. 이전의 수용 결과 0개 전용 recover 명령과 다른 복구 경로다.

출력의 새 RUN_ID를 사용한다. 이미 복구한 경우 아래 재개만 실행하며, 이 명령부터 실제 모델 호출이 시작된다.

```sh
bash Extraction/extraction.sh resume --provider nova_dev --run-id NEW_RUN_ID --install
```

### `PROVIDER_RESPONSE_INVALID`와 요청 ID 복구

NOVA가 유효한 모델 응답을 제공하지 못한 경우다. [현재 공식 개발 가이드](https://nova.snubhai.org/docs/)는 이 명시적 오류에는 새 요청을 사용하고, 결과가 불명인 전송·PROVIDER_UNAVAILABLE·REQUEST_PENDING에는 같은 ID를 유지하도록 안내한다. 모델이 반환한 JSON을 로컬에서 거절한 경우와 구별한다.

수정 실행기는 확정된 오류의 요청·payload·오류를 failed로 보존하고, 같은 모델·설정·내용에 새 request_id를 발급한다. 최대 5회 전송 시도 후 중단하며 모델이나 공급자를 바꾸지 않는다. 요청 교체를 출력 검증 시도로 추가 집계하지 않는다. 로그의 `provider_response_failed`는 HTTP 상태와 실패 ID를, `provider_retry_new_request_id`는 이전·새 ID를 보여준다. 응답 수용은 실제 성공한 요청 ID에 기록한다.

수정 전 이미지에서 같은 ID를 반복하다 `persistent_provider_failure:PROVIDER_RESPONSE_INVALID`로 실패한 정규화 실행은 아래 명령으로 복구한다. 불명 결과는 이 명령으로 처리하지 않는다.

```sh
# 실패한 worker가 종료한 뒤 실행한다. 이 복구 자체는 모델을 부르지 않는다.
bash Extraction/extraction.sh recover-provider --run-id OLD_RUN_ID
# 출력의 새 ID로 재개한다. 이 명령부터 실제 NOVA 요청을 시작한다.
bash Extraction/extraction.sh resume --provider nova_dev --run-id NEW_RUN_ID --install
```

입력·프롬프트·모델·임상 계약이 일치하는 별도 fingerprint의 복사본을 만든다. 완료 결과·입력 cursor·모든 시도 횟수·수용 요청·사용량을 보존한다. 명시적 오류가 남은 요청만 failed로 분류하고 미완료 작업을 pending으로 바꾼다. 원본 DB와 이전 복구 이력은 보존하며 재개 시 완료 작업을 다시 부르지 않는다. 이미 실행 중이면 중복 재개하지 않고 status/watch/logs로 확인한다.

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
