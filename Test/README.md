# 웹에서 실행하는 공개 샘플 테스트

**D50 현재 상태:** 실제 새 지식 manifest가 없어 현재 submission으로 새 상담을 시작하면 knowledge_bundle_not_installed로 실패한다. 과거 결과·리포트는 계속 읽을 수 있다. 실제 생성/설치는 [Extraction 안내](../Extraction/README.md)를 따른다. 이번 검증은 Tmp/의 합성 새 번들로만 수행했다.

`Test/`는 기존 `submission/run.py`와 SDK를 그대로 실행하면서, 공모전의 세션 API와 예선 컨테이너 제약을 로컬에서 재현한다. 공개 `C01`·`C03`·`C10`의 `case.json`을 읽으며 공식 서버의 비공개 구현이나 채점 기준을 재현하지 않는다. 모든 결과의 채점 상태는 `not_scored`다.

에이전트 컨테이너에는 `submission/`과 자신의 출력 폴더만 연결한다. CPU 2코어·RAM 8GB·읽기 전용 루트와 제출 코드·512MB `/tmp`를 사용한다. 내부 네트워크에서 로컬 평가 API에 접근하며, 환자 대본·진찰표·개발 키와 시뮬레이터 출력은 읽을 수 없다. 테스트 하네스 코드는 컨테이너 이미지 안에 있다. 실행 입력은 ZIP 압축 해제본 대신 현재 `submission/` 디렉터리이므로 ZIP 구성 자체의 검증은 기존 package 서비스가 맡는다.

시뮬레이터는 환자에게 초기 정보와 환자 대본을, 진찰 분류 모델에게 동작 이름만 전달한다. 등록된 진찰 결과는 원본 표에서 반환한다. 미등록 실제 진찰은 초기 정보·진찰표와 모순되지 않는 구체적 소견을 생성해 동일 동작에 재사용한다. `model_record`와 참조 진단은 어떤 실행 프롬프트에도 넣지 않는다.

## 오프라인 프로젝트 흐름 지도

실행 없이 프로젝트의 구조를 읽으려면 [프로젝트 흐름 지도](atlas.html)를 브라우저에서 직접 연다. HTML 한 파일에 스타일·도식을 담았으며, 서버·스크립트·외부 폰트·CDN 없이 오프라인에서 읽는다. D46 당시의 소유자·정보 수명·진료 흐름·그래프 후보와 근거·질문 선택·준비 파이프라인·코드 위치를 목차로 탐색한다. D46 역사적 스냅샷이며 현재 D47의 책임·사실 구조는 백서를 따른다.  실행 당시의 실제 그래프는 리포트의 **실행 검증**에서 별도로 확인한다. 원문 링크는 프로젝트 안의 상대 경로이며, 아래 빌드와 웹 실행은 흐름 지도를 읽는 데 필요하지 않다.

<a id="knowledge-viewer"></a>
## 데이터베이스·온톨로지 지식 뷰어

실제 지식 데이터와 연결을 열람하는 개인용 도구다. 프로젝트 루트에서 다음 명령으로 시작하고 [http://127.0.0.1:8766](http://127.0.0.1:8766)을 연다. Docker는 켜져 있어야 하며 기존 `ontoward-dev` 이미지를 그대로 사용한다. 웹·Python 의존성을 새로 설치하거나 인터넷에 연결하지 않아도 동작한다. HTML 파일 직접 열기 방식이 아니라 로컬 컨테이너가 읽기 전용 조회를 제공한다.

```sh
sh Test/knowledge.sh start
```

- **지식 탐색:** 유형을 고르고 이름·동의어·SCTID·원래 URI 또는 SHA 일부로 검색한다. 현재 필터와 다른 유형을 찾을 때는 **전체 유형**으로 바꾼다. 항목을 선택하면 주변 연결과 모든 나가는/들어오는 관계가 나오며, 그래프나 관계의 이름을 누르면 해당 항목으로 이동한다. 긴 그래프는 가로·세로로 스크롤한다.
- **읽을 수 있는 이름:** 질환·증상은 원천의 한·영 라벨을 사용하고, 해시로 식별되는 패턴·조건·연결은 실제 Target·속성·값에서 표시 이름을 구성한다. 숫자·단위·비교 연산과 AND/OR를 유지한다. 파생 이름임을 표시하고 원래 URI·원문 속성·라벨과 동의어를 함께 제공한다. 원천에 한국어가 없으면 영어 원문을 표시한다.
- **원천 근거:** 연결 항목에서 **준비 DB의 등록 정보와 원천 근거**를 펼친다. 원천 행 버튼을 누르면 보관된 실제 행, 원본 파일 경로·줄 번호·SHA-256을 확인한다. 준비 registry의 `candidate` 기록과 현재 실행 graph의 수용 상태는 서로 다른 기록이다.
- **원천 데이터:** `Competition mappings` 또는 `Source custody`를 선택해 테이블·구조·외래 키·행을 확인한다. 행을 누르면 생략되지 않은 전체 값이 펼쳐진다. 그래프에 있는 URI는 읽기 쉬운 이름으로 연결된다. 공모전 매핑 DB의 비어 있는 원천 테이블은 원천이 없다는 뜻이 아니며 **Source custody 열기**로 공유 보관 DB에 이동한다.
- **대용량 조회:** `id`, `file_id`, `entity_id`, `concept_id` 등 검색 열과 값을 선택한다. 정확 일치가 기본이며, 문자열 포함 검색은 대용량 스캔을 피하기 위해 2초 뒤 중단될 수 있다. 행은 한 번에 50개씩 읽는다. 화면의 미리보기만 짧게 표시하고 선택 행의 전체 값은 보존한다.
- **데이터 상태:** 실행 그래프의 build·수용 상태·유형별 개수·DB 크기와 현재 manifest 자산의 해시 확인 결과를 확인한다. 그래프는 시작 시 읽은 스냅샷이므로 지식을 바꾼 뒤에는 중지하고 다시 시작한다. SQLite는 조회 시 읽는다.

포트는 localhost에만 연결하며 API 키·Docker 소켓·원본 자산은 뷰어 컨테이너에 전달하지 않는다. 데이터 디렉터리를 읽기 전용으로 연결하고 SQLite `mode=ro`와 `query_only`를 함께 적용한다. 상담·테스트·모델 호출을 시작하는 기능은 없고 제출 ZIP에도 포함하지 않는다.

```sh
sh Test/knowledge.sh status
sh Test/knowledge.sh stop
sh Test/knowledge.sh verify
```

`verify`는 네트워크 없는 프로젝트 dev 컨테이너에서 manifest 부재 상태, 임시 새 manifest/hash/effect/scope 그래프, HTTP 경계와 역사적 SQLite 읽기 전용 동작을 확인한다. 결과는 `Tmp/knowledge-viewer/verification.json`에 저장하며 브라우저 확인 기록은 별도로 둔다. 뷰어를 이용하는 데 아래 평가기 빌드는 필요하지 않다.

## 평가기 빌드

프로젝트 루트에서 실행한다. 기존 `ontoward-dev:latest` 이미지를 재사용하고 별도 Python 의존성을 추가하지 않는다.

```sh
docker compose -f Test/compose.yaml build --pull=false test-simulator
```

기반 이미지가 없는 경우 먼저 기존 프로젝트 절차인 `docker compose build dev`로 준비한다. 기반 이미지 준비에는 PyPI 다운로드가 필요할 수 있다. Test 이미지 빌드는 프로젝트의 로컬 기반 이미지에서 네트워크 없이 수행한다. Test 코드를 수정하면 이 이미지를 다시 빌드한다.

## 웹에서 실행하고 결과 확인하기

```sh
sh Test/web.sh
```

터미널을 열어 둔 채 [http://127.0.0.1:8765](http://127.0.0.1:8765)에 접속한다. 공개 증례·응답 방식·요청 상한을 선택하고 **NOVA 테스트 실행** 버튼을 누른다. 기본은 **C10 / NOVA / 최대 200회**다. NOVA는 루트 `.env`의 개발 키와 개발 크레딧을 사용하며 환자·진찰·Gateway 호출을 모두 합쳐 상한을 적용한다. 외부 호출 없이 확인하려면 **오프라인 고정 응답**을 선택한다. 사이트에서 키를 입력하거나 저장하지 않는다.

실행 설정과 저장 기록은 왼쪽 영역에 있고 결과는 오른쪽의 고정된 작업 공간을 사용한다. **새 테스트 설정**을 펼쳐 실행 조건을 정하고 **실행 설정 접기**로 결과 읽는 폭을 넓힌다. 작은 화면에서는 설정 영역을 닫은 채 시작하며 상단 버튼으로 연다. 실행 폼과 리포트를 위아래로 오가던 바깥 페이지 스크롤을 없애고, 리포트의 본문에서 내용을 읽도록 구성했다. 좁은 화면은 턴 목록 대신 선택 상자를 사용한다.

한 번에 한 증례만 실행한다. 실행 중에는 상태와 경과 시간을 표시하고, 완료되면 같은 페이지에 리포트를 띄운다. **저장된 실행**에서 이전 결과를 선택하거나 **리포트 별도 열기**로 리포트만 연다. 상태 조회가 반복되어도 선택한 리포트와 기록 선택 상자를 다시 만들지 않는다. 다른 테스트가 진행 중이어도 저장된 결과를 검토할 수 있다. 새로고침하면 진행 중인 실행을 다시 읽으며, URL의 실행 ID로 기록을 다시 선택한다. 시작한 터미널에서 `Ctrl+C`를 누르면 해당 웹 실행기가 시작한 테스트와 사이트를 정리하고 저장한 결과는 남긴다. CLI와 웹은 같은 잠금을 사용한다.

리포트 왼쪽의 내부 세션·턴을 선택하고 다음 내용을 확인한다.

- **정보 흐름:** 기본 화면이다. 그래프 노드를 위에서 아래로 따라가며 **내부 호출과 전달**을 펼친다. 객체·메서드 이름을 누르면 오른쪽에서 호출자, 인스턴스 경로, 실제 인자와 자료형, 반환값, 직접 바뀐 인자와 상태 경로를 본다. `return None`인 메서드도 상태에 기록한 결과를 따로 표시한다. SDK 행은 실제 전송 body와 응답을 보여주며 JSON 문자열은 원문과 해독한 구조를 함께 펼칠 수 있다. 그래프 사이 화살표는 `WorkflowState → 검증된 dict → 다음 노드` 경계를 나타낸다.
- **실행 검증:** 전체 실행의 소스·manifest SHA256, 알고리즘·수집기, 실제 컴파일된 그래프의 연결과 관측 횟수, 메서드별 호출 수, 노드별 revision·facts·현재 턴 수명, Assessment 고정 시점을 확인한다. 이벤트 순서·호출과 반환·SDK 요청과 응답·상태 복원·저장 값 참조·고정 후 사실 보존·평가 revision과 chief·고정 1위와 제출 진단·SOAP 수신본·완료 영수증을 각각 판정한다. 수집 완료와 상담 성공은 별도다. Ear·Brain·Mouth·Writer 버튼은 해당 역할의 실제 첫 호출로 이동한다.
- **객체 탐색:** 현재 D47의 `CaseState`·`InterviewState`·`SessionContext`·`TurnContext`를 고르고 같은 객체의 턴 이전·이후 트리와 필드별 변경을 비교한다. 변경 경로·값을 검색하거나 객체가 바뀐 턴 번호를 눌러 이동한다. 지역 `InputResult`, `ModelResult`, `EvidenceIndex` 등 임시 반환 데이터는 해당 턴의 반환 객체와 정보 흐름에서 확인한다. 트리는 값 전체를 보존하며 펼칠 때 하위 항목을 만든다.
- **대화:** 실제 Doctor 발화·환자 답변·진찰 요청과 결과·거절·전달 미확인 요청.
- **기록 · SOAP:** 현재 D47에서는 `case.facts/assessment/plan`과 제출 중의 `turn.payload.note`를 확인한다. 통합 CaseFact·선택적 graph_binding·평가와 최종 수신된 15개 SOAP 문자열을 구별한다. 과거 실행에만 존재하는 S·O·A·P 저장 필드와 완료 상태는 해당 형식으로 표시한다.
- **상태 변화:** 턴과 호출 예산, 추가·변경된 사실, 선택한 행동, 질문 계획, 해석 결과와 수용·거절, 노드별 변경분과 전체 상태.
- **진단 근거:** 현재 Assessment의 순서·기반 revision·chief·frozen 여부, 코드가 연결한 supports·against·unresolved와 한계. 과거 점수 형식은 당시 로그의 값으로 표시한다.
- **모델 호출:** 환자·진찰·Ear·Brain·Mouth 역할의 실제 messages와 응답, 호출 설정·사용량·오류·복구 이력.

상단에서 최종 진단·SOAP·제출 수신·프로세스 종료와 실행 검사를 펼쳐 볼 수 있다. 시작 실패·시간 초과·중단도 결과로 남고, 부분 로그는 부분 수집으로 표시한다. 이전 실행에 내부 상태 로그가 없으면 기존 대화와 최종 결과만 표시한다. 로그의 원시 JSON과 모델 messages는 상세 영역을 펼칠 때 표시한다.

**마지막 Note 상태 보기**를 누르면 마지막 관측 구간으로 이동한다. D47은 `case.facts/assessment/plan`을 보관하며 SOAP는 `turn.payload.note`에 제출 작업 중만 존재한다. 최종 수신본과 completed는 상단에서 별도로 확인한다. `case.assessment.differential[0]`과 별도 제출 diagnosis가 일치해야 한다. facts의 수집 상태·임상 상태·범위를 구별하며 Education 응답은 대화만 유지한다. 과거 `case.S/O/A/P`, `case.diagnosis`, `patient_reports`는 해당 저장 형식의 역사적 필드로만 읽는다.

저장된 실행을 웹에서 열면 현재 뷰어로 `report.html`을 다시 만든다. 테스트·모델 호출을 다시 실행하지 않는다. 이미 별도로 열어 둔 리포트는 새로고침한다. 내부 상태가 없는 과거 실행은 Note를 빈 상태로 추정하지 않고 미수집으로 표시하며 실제 최종 수신본만 제공한다.

새 수집 형식은 Ear·Brain·Mouth·Consultation·Writer의 메서드와 Ear의 Python exact/forced 연결·fact 생성, 각 세션의 `graph_candidates`·입력 준비·순위/질문 수용·영어 계획 함수를 감싼다. 함수는 정의된 모듈과 실제 호출 지점을 함께 기록하며 객체 메서드와 구별한다. 큰 직렬화 값은 `value` 이벤트에 한 번 보존하고 `trace_value_ref`로 참조한다. 트리를 펼치면 저장한 실제 값이 해독된다. 같은 참조는 **직렬화 내용의 일치**를 뜻하며 Python 인스턴스의 동일성을 뜻하지 않는다. 별도의 상세 값 파일 없이 `report.html`에 필요한 값과 schema를 모두 포함한다.

Submission에 audit sink나 상세 이벤트를 주입하지 않으며 Python heap과 반복 내부 조회의 상세 값은 수집하지 않는다. 반복 횟수는 노드 종료에서 확인한다. 특정 필드를 읽었다는 추정은 하지 않는다. 내부 메서드·정의 위치·실행 소스가 없는 과거 로그는 미수집으로 표시한다. 원본 `submission/`을 수정하지 않고 Test 메모리 래퍼를 실행 후 복원한다. `inspection.json`은 보존된 로그의 검사 결과이며 임상 판단을 다시 실행하지 않는다. 공개 증례와 별개인 통제 fixture 결과는 **합성 프로토콜**로 표시한다.

웹 서버는 기존 Test 이미지의 Python 표준 라이브러리를 사용하고 프론트엔드는 별도 패키지가 필요 없다. 웹 컨테이너는 출력 폴더만 읽고 쓰며, 작업 요청을 받은 호스트 셸이 기존 실행기를 호출한다. 웹 컨테이너에 Docker 소켓·개발 키·증례 원본 마운트를 전달하지 않는다. 웹 포트는 localhost에만 연결한다. 계정·DB·대기열·자동 재개는 두지 않는다.

현재 D47 로그에서는 통합 facts·graph_binding·단일 Assessment·영어 계획과 일시적인 제출 작업을 표시한다. 과거 다섯 객체 형식의 저장 로그는 해당 기록대로 읽는다. 처리된 응답과 모델 교환·복구는 그래프 상태 대신 관측 event에서 확인한다. SOAP는 실제 제출 작업과 시뮬레이터 수신 결과를 구분하며 존재하지 않는 필드를 추정하지 않는다.

## LangSmith에서 검토하는 방법

아래 LangSmith 안내는 과거 LangGraph 실행 시기의 참고 기록이다. D50은 LangGraph 없이 Consultation의 순차 작업을 Test 내부에서 관측하며 외부 trace 전송은 구현하거나 실행하지 않는다. LangGraph는 환경변수로 추적을 활성화할 수 있고, 사용자 정의 SDK 호출은 별도 래퍼나 수동 span이 필요하다. NOVA SDK는 OpenAI 클라이언트가 아니므로 `wrap_openai`만 추가해서 환자·진찰·Gateway가 모두 수집되지는 않는다. [공식 LangGraph 추적 안내](https://docs.langchain.com/langsmith/trace-with-langgraph)

현재 Test에는 LangSmith 전송 코드와 웹 연결 버튼이 없다. 에이전트는 내부 네트워크만 사용하고, Compose는 `LANGSMITH_*`를 전달하지 않는다. 루트 `.env`에 아래 값을 적는 것만으로 현재 테스트가 업로드되지는 않는다. 프로젝트 dev 이미지에는 기존 의존성을 통해 `langsmith 0.14.7`이 설치되어 있음을 확인했으며 이번 변경에서 패키지를 추가하지 않았다.

현재 격리를 유지하려면 **테스트 종료 → 저장된 로그를 별도 Test 프로세스에서 내보내기 → 웹에서 해당 LangSmith trace 링크 열기**가 가장 얇은 연결 방식이다. `agent/trace.jsonl`의 초기 상태·변경분·실제 노드·SDK 요청과 `simulator/model-calls.jsonl`의 요청 ID를 연결하면 실행 → 세션·턴 → 노드 → SDK·역할 호출의 트리를 만들 수 있다. 노드의 입력·출력에 복원된 상태를 넣고 Note와 진단을 확인한다. `scripted` 응답은 실제 LLM 호출로 표시하지 않는다. LangSmith SDK의 `Client.create_run`으로 저장된 시작·종료 시각과 상위 실행 ID를 지정할 수 있다. 이 방식은 권장 연결안이며 내보내기 기능은 아직 구현하지 않았다. [공식 SDK 참조](https://reference.langchain.com/python/langsmith/client/Client/create_run)

연동을 준비할 때는 다음 순서로 설정한다.

1. [LangSmith](https://smith.langchain.com)에 로그인하고 사용할 워크스페이스와 계정 리전을 확인한다.
2. **Settings → API Keys**에서 trace 기록용 키를 만든다. 해당 배포에서 지원하면 **Tracing Only**를 선택하고 대상 워크스페이스를 지정한다. 개인 도구에서 조회 등도 필요하면 해당 권한의 Personal Access Token을 사용한다.
3. 추적 프로젝트 이름을 `ontoward-test`처럼 정한다. 키는 루트 `.env`에서만 관리하고 `submission/.env`·브라우저 JavaScript·리포트에 넣지 않는다.
4. 연동 구현 시에는 네트워크를 사용하는 별도 Test 내보내기 프로세스에만 설정을 전달한다. 내보내기는 대화·Note·모델 messages를 지정한 LangSmith 서비스에 전송하는 동작이므로 로컬 오프라인 실행과 구분한다. 현재 웹 컨테이너나 에이전트에 키·외부 네트워크를 추가할 필요는 없다.

설정 예시는 다음과 같다. 값은 사용자가 발급받은 키와 계정 리전에 맞춘다.

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<발급받은 LangSmith 키>
LANGSMITH_PROJECT=ontoward-test
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
# 키가 여러 워크스페이스에 속하는 경우에만 설정
# LANGSMITH_WORKSPACE_ID=<대상 Workspace ID>
```

기본 API 주소는 GCP US다. EU 계정은 `https://eu.api.smith.langchain.com`처럼 해당 리전의 API 주소를 사용한다. 워크스페이스 ID는 키가 여러 워크스페이스에 속할 때 필요하며 Settings의 General에서 확인한다. `LANGSMITH_TRACING`은 자동 추적용 설정이고 수동 `Client.create_run` 내보내기는 명시적인 API 호출이다. NOVA 요청 한도와 LangSmith 로그 전송은 서로 다른 호출이며, 추적을 위해 별도 OpenAI 키를 만들 필요는 없다. [공식 키·리전·워크스페이스 설정](https://docs.langchain.com/langsmith/create-account-api-key), [프로젝트 설정](https://docs.langchain.com/langsmith/log-traces-to-project)

## 완전 오프라인 검증

```sh
sh Test/run.sh verify
sh Test/run.sh C10 scripted
```

`verify`는 네트워크를 끈 컨테이너에서 실제 SDK의 HTTP 전송, ready, 입력 비공개, 준비·진료 제한 시간, NFC 길이, 거절 턴, TEST 차단, 요청 중복·처리 중 응답, 모델 한도, SOAP 형식과 완료 수신을 검증한다. NOVA 요청은 mock으로 대체한다.

동일한 명령은 웹의 실행 생성·중복 차단·상태 복원·종료 결과·실행기 연결 끊김·저장된 리포트·경로 제한·HTML 문자열 처리를 함께 검사한다. 원본 워크플로와 관측 래퍼의 비교는 프로젝트 루트에서 다음 명령으로 수행한다. 합성 자산과 관측 결과는 `Tmp/test-web31/parity/`에만 만든다.

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T dev python Test/test_observer.py
```

Note 뷰어의 동작 검사는 `Test/test_viewer.js`가 실제 뷰어 코드를 텍스트 DOM 대역에서 실행하여 필드 매핑·턴별 상태·완료/임상 상태·출처·Unicode 구간·payload 구분·과거 및 부분 로그·키보드 탭을 확인한다. Node가 이미 있는 프로젝트 extraction 이미지가 준비되어 있으면 다음처럼 네트워크 없이 실행한다. 선택적으로 컨테이너에서 접근 가능한 `report.html` 경로를 인자로 주어 저장된 로그도 확인할 수 있다. 실제 브라우저 렌더링 검증과는 구분한다.

```sh
docker run --rm --pull never --network none --read-only --entrypoint node \
  --mount type=bind,src="$(pwd)/Test",dst=/test,readonly \
  ontoward-extraction:local /test/test_viewer.js
```

같은 실행에서 `/test/test_viewer.js` 대신 `/test/test_app.js`를 지정하면 실제 웹 제어 코드의 설정 접기·모바일 focus 경계·리포트 및 기록 선택 유지·중복 실행 차단을 검사한다. 이 검사는 텍스트 DOM 대역을 사용하며 실제 브라우저의 화면 배치·스크린샷·접근성 검사를 대체하지 않는다.

`scripted`는 외부 모델 대신 고정 환자 응답과 제공된 후보의 이름·원천 동의어를 비교하는 일반 대역을 사용한다. 증례별 검색 문자열이나 정답 개념 표는 없다. 이 대역은 한·영 자연어의 의미를 이해하는 실제 Gateway가 아니므로, 완료 여부를 주호소 매핑의 임상 정확도나 NOVA 성능으로 해석하지 않는다. 이전 C01·C03의 실패는 제거된 문자열 매처의 결함으로, 그래프에 필요한 개념이 없다는 증거가 아니다.

실제 에이전트의 D29 Gateway는 기존 Symptom 하나의 선택을 요구하고 원천 라벨·동의어와 제한된 전체 색인 재검색을 사용한다. 이 알고리즘은 `submission/`에 있으며 시뮬레이터의 대역과 구분한다. 최종 선택이 없으면 명료화 필요와 실패를 그대로 기록한다.

## NOVA 모의 환자 실행

루트 `.env`의 `NOVA_DEV_KEY`를 사용한다. 키를 명령행 인자·제출 환경·Test 파일에 복사하지 않는다. 실제 실행은 다음 명령으로 증례와 요청 상한을 지정한다.

```sh
TEST_MAX_NOVA_REQUESTS=200 sh Test/run.sh C10 nova
```

`C01` 또는 `C03`을 지정해 다른 공개 증례를 실행할 수 있다. 한 번에 한 증례만 진행한다. NOVA 모드는 시뮬레이터에만 외부 네트워크를 추가하고 `https://nova.snubhai.org/v1/chat/completions`의 세션 밖 개발 호출을 사용한다. 모델은 `openai/gpt-6-luna`다. 에이전트가 요청한 Brain 임상 판단·영어 계획은 `high`, Ear·Mouth는 `medium`을 보존한다. 환자·진찰 대역은 기존 `medium` 설정을 사용한다. 환자·진찰 분류·미등록 소견·Gateway 요청을 모두 합쳐 기본 200회로 제한하며 팀 개발 크레딧과 세션 밖 호출 한도를 사용한다. 실제 계정 잔여량은 조회하거나 추정하지 않는다.

NOVA 모드의 에이전트는 계속 내부 네트워크만 사용하지만 시뮬레이터는 외부 모델에 연결한다. 네트워크가 전혀 없는 환경에서는 `scripted`를 사용한다. 공식 또는 서버 샘플 세션 생성, 업로드, 공식 진단 제출·채점은 수행하지 않는다.

각 외부 요청 전에 ID·역할·상한을 대장에 예약하고 응답·오류를 보존한다. 통신·서비스 오류 후에는 추가 외부 요청을 중단한다. `clinical_decision`·`clinical_action`·`education`·`education_doctor`의 `PROVIDER_RESPONSE_INVALID`는 실행기의 응답 복구 1회가 새 ID로 공급자에 도달하도록 허용하며 실패 예약도 공유 요청 상한에 포함한다. 한국어 변환은 처음부터 출력 상한 최대 8,000을 사용하고 응답 복구와 문구 검증 복구를 각각 1회씩 구별한다. 다른 역할·오류와 요청 상한의 중단은 유지한다. 환자·진찰 JSON 형식이 잘못되면 역할별로 최대 두 번 판정을 시도한다. 재시작으로 같은 세션을 재개하지 않으며, 같은 로컬 요청 ID와 payload의 재전송은 결과를 재생하거나 `REQUEST_PENDING`을 반환하여 외부 요청을 중복하지 않는다. 동일 ID의 다른 payload는 거절한다.

## 출력과 완료 기준

실행마다 `Tmp/test-evaluator/<case>-<UTC시각>-<고유 ID>/`를 새로 만든다. 기존 CLI의 고유 ID는 프로세스 번호이고 웹은 별도의 임의 ID를 사용한다.

| 경로 | 내용 |
|---|---|
| `result.json` | 프로세스·제출 수신·격리 증거를 합친 실행 판정 |
| `report.html` | 외부 파일 없이 열 수 있는 대화·상태·진단·모델 리포트 |
| `inspection.json` | 보존 로그에서 계산한 관측 무결성·실제 순차 작업 또는 과거 그래프 경로·고정 평가·전송 및 수신 일치 검사와 소스 핀 |
| `run.json`, `run.args`, `status` | 웹의 선택 조건·실행기 입력·실행 상태; `run.json`은 웹 실행에만 생성 |
| `run-id` | CLI 실행의 고유 ID; 컨테이너의 `/output`이라는 마운트 이름과 구별 |
| `started`, `ended`, `exit-code`, `runner.log` | 실행기 시작·종료·종료 코드·시작 오류와 Docker 실행 로그 |
| `agent/process.json` | 종료 코드·시간·UID·메모리/CPU cgroup·마운트 관측 |
| `agent/stdout.log`, `agent/stderr.log` | 제출 에이전트 원본 출력과 오류 |
| `agent/trace.jsonl` | 초기 상태·노드별 변경분·객체/함수의 typed 입출력·중복 제거된 큰 값·세션·턴·SDK 본문·응답·오류·종료 |
| `simulator/summary.json` | 증례 해시·턴·모델 사용·정책 한도·제출 영수증 |
| `simulator/transcript.json` | 초기 정보와 실제 SAY/EXAM·거절·DIAGNOSE 이력 |
| `simulator/requests.json` | 요청 ID·payload 해시·Gateway 실제 요청 본문과 후보·처리 상태·응답 |
| `simulator/record.json` | 15개 SOAP 문자열과 별도 주진단; 제출된 경우 생성 |
| `simulator/nova-requests.jsonl` | NOVA 모드의 역할별 예약·응답·실패 기록 |
| `simulator/model-calls.jsonl` | 역할별 실제 messages·응답·호출 설정·오류와 상위 행동 요청 ID |
| `verification.json` | `verify` 명령의 오프라인 검사 결과 |

ready 이전에는 증례를 공개하지 않고 준비는 10분, ready 이후 진료는 30분이다. SAY·EXAM은 최대 50턴·NFC 1–30자, TEST는 예선에서 차단한다. 모델은 Doctor/Gateway 호출 200회·입력 500,000·출력 100,000토큰을 별도로 추적한다. DIAGNOSE는 턴을 쓰지 않아 50번째 응답 이후에도 기한 내 제출할 수 있다.

에이전트 종료 코드 0과 로컬 DIAGNOSE `completed` 영수증을 함께 확인해야 상담 성공이다. 빈/잘못된 SOAP, 비어 있지 않은 Gateway 응답 누락, 실패 프로세스나 증거 누락은 성공으로 표시하지 않는다. 웹에서 실행이 종료되어 리포트를 받는 것과 상담 성공은 각각 확인한다. scripted 응답으로 확정할 근거가 없으면 `no_supported_diagnosis`와 실패 결과를 그대로 보여준다.

`nonempty_gateway_responses`와 SDK의 `doctor_successes`는 응답 문자열의 존재만 뜻하며 빈 사실 JSON도 포함한다. 실제 수용된 연결은 `case.facts`, Test가 감싼 입력 수용 함수의 인자·반환·상태 변화에서 확인한다. 과거 로그의 model_history는 당시 저장 자료다. Test 부트스트랩은 원본 진입점을 실행하면서 메모리에서만 Consultation의 실제 작업과 SDK 경계를 감싸고 원래 함수를 한 번 호출한다. 원본 소스·질문·라우팅·순위·재시도·진단·SOAP는 바꾸지 않으며, 로그 쓰기 실패가 행동을 재실행하지 않는다. 비교용으로 `TEST_TRACE=0 sh Test/run.sh C10 scripted`를 실행하면 관측을 끌 수 있다. 각 실행의 trace_status는 complete·incomplete·not_collected로 구분한다.

공식 점수·독립 임상 검증·실제 NOVA 연결 품질은 이 오프라인 결과로 확인할 수 없다. 재현 근거는 보존된 `assets/nova-devkit/nova_local.py`, `assets/nova-starter/nova_sdk.py`, `assets/nova-competition-2026/`와 [D27](../DECISION_STATE.md#D27)·[D29](../DECISION_STATE.md#D29)·[D31](../DECISION_STATE.md#D31)다.

## Education 실행 자산

D37부터 에이전트에는 기존 submission·출력 마운트와 함께 원본 가이드라인 폴더가 /opt/nova/guidelines에 읽기 전용으로 제공된다. NOVA_GUIDELINES_DIR이 이 경로를 가리키며 문서 자체는 제출 ZIP에 포함하지 않는다. education high 요청과 education_doctor medium 요청의 reasoning 값은 로컬 모델 브리지에서도 보존한다. scripted 모드의 계획·한국어 문장은 프로토콜 검증용 대역으로 실제 모델이나 임상 품질의 증거가 아니다.

## D47 세션 대역과 저장 C03 비교

Test/brain_double.py는 순위 전용·순위와 행동·행동 복구를 구별하는 프로토콜 대역이다. 임상 정답이나 실제 모델 품질의 증거가 아니다. 모든 요청은 공통 Brain을 통과하며 Test/protocol.py가 현재 JSON 입력과 과거 Key/Value 입력을 구별해 읽는다.

프로젝트 오프라인 dev 컨테이너에서 다음 비교를 수행한다.

```sh
python -B Test/compare_d47.py --run Tmp/test-evaluator/C03-20261019T015834Z-18f944a5e9 --output Tmp/d47-2026-10-19/comparison
```

원본 C03의 네 수용 상태를 통합 사실로 변환해 모든 사실·정규화된 조건·age·sex·보고 성장 수치와 기존 후보 전달, revision 변경, 동일 요청 공급자 오류 재현을 확인한다. 프롬프트 바이트는 측정하거나 비교하지 않는다. 원본 결과와 실패는 보존하며 실제 모델 정확도·속도·새 NOVA·공식 평가는 not_run이다. 최신 경로·해시는 [D47 증빙](../data/provenance/algorithm-d47-2026-10-19.json)을 따른다.

Test/compare_d46.py와 Dev의 이전 비교 도구는 명시적으로 선택한 과거 소스 스냅샷의 재현에만 쓴다. D49에서는 compare_d47.py도 과거 스냅샷 재현용이며 현재 수용은 유지 회귀와 새 합성 번들/독립 ZIP 검증이다. 원본 SDK HTTP의 C10 경로는 합성 복통 fixture의 하네스 식별자이며 실제 공개 C10 품질 평가와 구별한다. 공개 시작 정보·숨은 대본·정답을 에이전트 입력에 섞지 않는다.

## D48 프롬프트 모듈 관측

현재 실행은 D47의 사실·세션 계약에 D48의 Python 프롬프트 선택을 적용한다. [설정 안내](../submission/config/README.md)와 [작업별 조합](../submission/config/prompts.json)에서 실제 모듈을 확인한다. 새 trace의 settings.runtime에는 설정·prompt manifest·참조 모듈의 해시와 prompt_routes를 기록한다. SDK 요청과 model-calls에는 조립된 실제 messages가 남는다. 기존 저장 실행과 report는 수정하지 않는다.

C03-20261019T045722Z-fa33440098은 첫 input_context의 upstream HTTP 530이 원본 SDK에서 INVALID_API_RESPONSE가 된 실패다. 로컬 동일 요청 재전송은 캐시된 오류를 반환했고 upstream 요청은 한 번이다. 당시 응답 본문은 보존되지 않았다. 사용자 제공 Cloudflare Tunnel 1033은 주최측 서비스 장애라는 추정을 뒷받침하며, 이 프롬프트 작업은 SDK·Brain·bridge·재시도·캐시 동작을 변경하지 않는다. [D48 증빙](../data/provenance/algorithm-d48-2026-10-19.json)에서 오프라인 재현과 새 서비스 실행 not_run을 구별한다.

## D49 무점수 번들과 독립 ZIP

활성 manifest가 없으면 지식 뷰어는 knowledge_bundle_not_installed와 빈 실행 그래프를 표시한다. 이전 Source custody/Competition mappings 테이블은 별도 역사적 준비 자료다. 새 manifest를 읽으면 다섯 asset hash와 effect·targetScope·Pattern/applicability를 표시하며 관계 출처/점수 side path를 요구하지 않는다.

Tmp/에 새 합성 번들을 만든 뒤 package 서비스의 /submission·/output을 그 임시 디렉터리에 연결해 ZIP을 만든다. 압축 해제본은 다음처럼 독립 프로세스로 검사한다. D49_SUBMISSION은 실제 압축 해제본의 절대 경로다.

```sh
D49_SUBMISSION=/absolute/path/to/Tmp/synthetic/submission \
D49_OUTPUT=/absolute/path/to/Tmp/synthetic/evidence \
docker compose -f Test/compose.d49.yaml run --rm -T d49-archive
```

하네스는 read-only root/submission·network none·2CPU·8GB에서 원본 run.py와 SDK를 실행한다. 외부 fixture responder가 loopback HTTP로 ready·chat·SAY/EXAM·DIAGNOSE를 제공하고 fifteen-field SOAP와 completed를 확인한다. 개발 키·부모 data·원자료·환자 대본은 agent에 전달하지 않는다. 프로토콜 검증이며 실제 모델·임상·공식 품질은 not_run이다. D49의 source·이미지·합성 ZIP과 세 운영 상태는 [증빙](../data/provenance/algorithm-d49-2026-10-19.json)에 연결한다.

## D50 순차 실행과 공동 교육 검증

새 trace는 format 5의 execution.kind=sequential과 실제 작업 이름·소스/schema/prompt 해시를 기록한다. execution.py는 Test에서만 작업 경계를 감싸고 중첩 검증은 객체 호출로 보존한다. 과거 그래프 trace는 저장 형식대로 읽는다. 전체 상태 복사나 audit hook은 제출 코드에 넣지 않는다.

영어 P와 한국어는 정상 high 호출 한 번에 생성하고 영어·인용·한국어 문구를 별도로 수용한다. 잘못된 한국어 그룹만 medium으로 제한 복구한다. 독립 SDK 검사에는 ONTOWARD_DENY_LANGGRAPH=1을 주어 Test 외부 guard로 LangGraph import를 차단할 수 있다. guard와 fixtures는 ZIP에 포함하지 않는다.

현재 수용 증거는 [D50 provenance](../data/provenance/algorithm-d50-2026-10-20.json)에 연결한다. 관측·텍스트 DOM·HTTP와 실제 브라우저 시각 검증, 실제 모델·임상·공식 평가는 구분한다.
