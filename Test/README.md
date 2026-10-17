# 공개 샘플 로컬 평가 환경

`Test/`는 기존 `submission/run.py`와 SDK를 그대로 실행하면서, 공모전의 세션 API와 예선 컨테이너 제약을 로컬에서 재현한다. 공개 `C01`·`C03`·`C10`의 `case.json`을 읽으며 공식 서버의 비공개 구현이나 채점 기준을 재현하지 않는다. 모든 결과의 채점 상태는 `not_scored`다.

에이전트 컨테이너에는 `submission/`과 자신의 출력 폴더만 연결한다. CPU 2코어·RAM 8GB·읽기 전용 루트와 제출 코드·512MB `/tmp`를 사용한다. 내부 네트워크에서 로컬 평가 API에 접근하며, 환자 대본·진찰표·개발 키와 시뮬레이터 출력은 읽을 수 없다. 테스트 하네스 코드는 컨테이너 이미지 안에 있다. 실행 입력은 ZIP 압축 해제본 대신 현재 `submission/` 디렉터리이므로 ZIP 구성 자체의 검증은 기존 package 서비스가 맡는다.

시뮬레이터는 환자에게 초기 정보와 환자 대본을, 진찰 분류 모델에게 동작 이름만 전달한다. 등록된 진찰 결과는 원본 표에서 반환한다. 미등록 실제 진찰은 초기 정보·진찰표와 모순되지 않는 구체적 소견을 생성해 동일 동작에 재사용한다. `model_record`와 참조 진단은 어떤 실행 프롬프트에도 넣지 않는다.

## 빌드

프로젝트 루트에서 실행한다. 기존 `ontoward-dev:latest` 이미지를 재사용하고 별도 Python 의존성을 추가하지 않는다.

```sh
docker compose -f Test/compose.yaml build --pull=false test-simulator
```

기반 이미지가 없는 경우 먼저 기존 프로젝트 절차인 `docker compose build dev`로 준비한다. 기반 이미지 준비에는 PyPI 다운로드가 필요할 수 있다. Test 이미지 빌드는 프로젝트의 로컬 기반 이미지에서 네트워크 없이 수행한다. Test 코드를 수정하면 이 이미지를 다시 빌드한다.

## 완전 오프라인 검증

```sh
sh Test/run.sh verify
sh Test/run.sh C10 scripted
```

`verify`는 네트워크를 끈 컨테이너에서 실제 SDK의 HTTP 전송, ready, 입력 비공개, 준비·진료 제한 시간, NFC 길이, 거절 턴, TEST 차단, 요청 중복·처리 중 응답, 모델 한도, SOAP 형식과 완료 수신을 검증한다. NOVA 요청은 mock으로 대체한다.

`scripted`는 외부 모델 대신 고정 환자 응답과 제공된 후보의 이름·원천 동의어를 비교하는 일반 대역을 사용한다. 증례별 검색 문자열이나 정답 개념 표는 없다. 이 대역은 한·영 자연어의 의미를 이해하는 실제 Gateway가 아니므로, 완료 여부를 주호소 매핑의 임상 정확도나 NOVA 성능으로 해석하지 않는다. 이전 C01·C03의 실패는 제거된 문자열 매처의 결함으로, 그래프에 필요한 개념이 없다는 증거가 아니다.

실제 에이전트의 D29 Gateway는 기존 Symptom 하나의 선택을 요구하고 원천 라벨·동의어와 제한된 전체 색인 재검색을 사용한다. 이 알고리즘은 `submission/`에 있으며 시뮬레이터의 대역과 구분한다. 최종 선택이 없으면 명료화 필요와 실패를 그대로 기록한다.

## NOVA 모의 환자 실행

루트 `.env`의 `NOVA_DEV_KEY`를 사용한다. 키를 명령행 인자·제출 환경·Test 파일에 복사하지 않는다. 실제 실행은 다음 명령으로 증례와 요청 상한을 지정한다.

```sh
TEST_MAX_NOVA_REQUESTS=200 sh Test/run.sh C10 nova
```

`C01` 또는 `C03`을 지정해 다른 공개 증례를 실행할 수 있다. 한 번에 한 증례만 진행한다. NOVA 모드는 시뮬레이터에만 외부 네트워크를 추가하고 `https://nova.snubhai.org/v1/chat/completions`의 세션 밖 개발 호출을 사용한다. 모델은 `openai/gpt-6-luna`, reasoning은 `medium`이다. 환자·진찰 분류·미등록 소견·Gateway 요청을 모두 합쳐 기본 200회로 제한하며 팀 개발 크레딧과 세션 밖 호출 한도를 사용한다. 실제 계정 잔여량은 조회하거나 추정하지 않는다.

NOVA 모드의 에이전트는 계속 내부 네트워크만 사용하지만 시뮬레이터는 외부 모델에 연결한다. 네트워크가 전혀 없는 환경에서는 `scripted`를 사용한다. 공식 또는 서버 샘플 세션 생성, 업로드, 공식 진단 제출·채점은 수행하지 않는다.

각 외부 요청 전에 ID·역할·상한을 대장에 예약하고 응답·오류를 보존한다. 통신·서비스 오류 후에는 추가 외부 요청을 중단한다. 환자·진찰 JSON 형식이 잘못되면 역할별로 최대 두 번 판정을 시도한다. 재시작으로 같은 세션을 재개하지 않으며, 같은 로컬 요청 ID와 payload의 재전송은 결과를 재생하거나 `REQUEST_PENDING`을 반환하여 외부 요청을 중복하지 않는다. 동일 ID의 다른 payload는 거절한다.

## 출력과 완료 기준

실행마다 `Tmp/test-evaluator/<case>-<UTC시각>-<프로세스번호>/`를 새로 만든다.

| 경로 | 내용 |
|---|---|
| `result.json` | 프로세스·제출 수신·격리 증거를 합친 실행 판정 |
| `agent/process.json` | 종료 코드·시간·UID·메모리/CPU cgroup·마운트 관측 |
| `agent/stdout.log`, `agent/stderr.log` | 제출 에이전트 원본 출력과 오류 |
| `simulator/summary.json` | 증례 해시·턴·모델 사용·정책 한도·제출 영수증 |
| `simulator/transcript.json` | 초기 정보와 실제 SAY/EXAM·거절·DIAGNOSE 이력 |
| `simulator/requests.json` | 요청 ID·payload 해시·Gateway 실제 요청 본문과 후보·처리 상태·응답 |
| `simulator/record.json` | 15개 SOAP 문자열과 별도 주진단; 제출된 경우 생성 |
| `simulator/nova-requests.jsonl` | NOVA 모드의 역할별 예약·응답·실패 기록 |
| `verification.json` | `verify` 명령의 오프라인 검사 결과 |

ready 이전에는 증례를 공개하지 않고 준비는 10분, ready 이후 진료는 30분이다. SAY·EXAM은 최대 50턴·NFC 1–30자, TEST는 예선에서 차단한다. 모델은 Doctor/Gateway 호출 200회·입력 500,000·출력 100,000토큰을 별도로 추적한다. DIAGNOSE는 턴을 쓰지 않아 50번째 응답 이후에도 기한 내 제출할 수 있다.

에이전트 종료 코드 0과 로컬 DIAGNOSE `completed` 영수증을 함께 확인해야 성공이다. 빈/잘못된 SOAP, 비어 있지 않은 Gateway 응답 누락, 실패 프로세스나 증거 누락은 성공으로 표시하지 않는다. `nonempty_gateway_responses`와 SDK의 `doctor_successes`는 응답 문자열의 존재만 뜻하며 빈 사실 JSON도 포함한다. 직접 `consult()`를 호출한 반환값과 오프라인 회귀에서는 `model_history[].parser_result.linked_chief_facts`로 실제 수용된 연결을 확인할 수 있다. SDK 진입점은 반환 상태를 파일로 쓰지 않으므로 Test 실행의 후보·모델 응답은 `simulator/requests.json`에서 확인한다. 공식 점수·독립 임상 검증·실제 NOVA 연결 품질은 이 오프라인 결과로 확인할 수 없다. 재현 근거는 보존된 `assets/nova-devkit/nova_local.py`, `assets/nova-starter/nova_sdk.py`, `assets/nova-competition-2026/`와 [D27](../DECISION_STATE.md#D27)·[D29](../DECISION_STATE.md#D29)다.
