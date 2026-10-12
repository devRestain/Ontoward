# 개발 도구

현재 도구는 Codex 환경 설정과 제출 ZIP 구성으로 구분한다.

```text
Dev/
├── AGENTS.md / README.md
├── codex/
│   ├── Dockerfile
│   └── environment.py
└── packaging/
    └── package_submission.py
```

`codex/`는 SNU ChatGPT Workspace의 Edu 인증을 사용하는 최소 CLI 환경이다. 모델 설정은 gpt-6-luna·medium·Standard이며, 인증은 전용 Docker volume에 보관한다. 현재 자동 추출 프로그램·후보 형식·프롬프트·검토 도구는 없다. 새 방향과 준비 계약을 정한 뒤 필요한 구현을 추가한다.

프로젝트 루트에서 환경을 준비하고 로컬 로그인 상태를 확인한다.

```sh
docker compose build ontology-extraction
docker compose up -d ontology-extraction
docker compose exec ontology-extraction bash
docker compose exec -T ontology-extraction python Dev/codex/environment.py status
```

새 머신에서는 `environment.py init`으로 설정한 뒤 공식 `codex login --device-auth` 흐름에서 SNU를 선택한다. 확인한 실제 UUID로 `environment.py pin-workspace`를 실행하며 이름으로 UUID를 추측하지 않는다. 현재 로그인 저장소는 컨테이너 재생성과 독립적으로 유지한다.

`packaging/`는 submission/만 입력으로 읽는 독립 압축 도구다.

```sh
docker compose build package
docker compose run --rm -T package
```

출력은 Tmp/packaging/ontoward-submission.zip이며 Python 패키지 경로와 공개 .env를 포함한다. 안내·상태·캐시·개발 자료는 제외한다. 압축 확인이 임상 기능 완성이나 제출 승인을 의미하지 않는다.

현재 운영 사실은 [루트 상태](../PROJECT_STATE.md), 준비 모델·범위는 [D09](../DECISION_STATE.md#D09), 자료 입력은 [data](../data/README.md)에서 확인한다.
