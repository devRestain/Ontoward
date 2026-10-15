# 교육 원문 전처리

현재 승인된 런타임 Disease를 기존 지침·교과서의 고정된 원문 구간에 연결하는 D16 준비 도구다. 원문과 출처를 사용자 검토 전 초안으로 만들며, 한국어 교육 문구 작성과 제출 에이전트 연결은 별도다.

## 실행

프로젝트 루트에서 기존 dev 이미지와 네트워크가 꺼진 검증 설정을 사용한다. 새 의존성을 설치하거나 문서를 다운로드하지 않는다.

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T dev python -B -m Dev.education.prepare inventory --output data/preparation/education/runtime842-2026-10-15/inventory.json

docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T dev python -B -m Dev.education.prepare build --inventory data/preparation/education/runtime842-2026-10-15/inventory.json --mappings data/preparation/education/runtime842-2026-10-15/mappings.json --output data/preparation/education/runtime842-2026-10-15

docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T dev python -B -m Dev.education.prepare verify --inventory data/preparation/education/runtime842-2026-10-15/inventory.json --mappings data/preparation/education/runtime842-2026-10-15/mappings.json --output data/preparation/education/runtime842-2026-10-15

docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T dev python -B Dev/tests/education/test_prepare.py
```

`inventory`는 manifest와 선언 자산의 해시를 확인하고 모든 Disease URI·명칭·동의어, 카탈로그와 문서별 해시, 제목 탐색 후보를 고정한다. `build`는 직접 작성한 매핑을 검증하여 원문 발췌와 보고서를 생성한다. `verify`는 입력 해시와 지정 구간을 다시 확인하고 저장된 결과가 재추출 결과와 정확히 같은지 비교하며 파일을 수정하지 않는다.

## 검토와 수정

[검토 보고서](../../data/preparation/education/runtime842-2026-10-15/review.md)에서 질환 URI, 선정 이유, 출처 링크, 적용 제한과 구간을 확인한다. [매핑 파일](../../data/preparation/education/runtime842-2026-10-15/mappings.json)은 편집 입력이고 [원문 JSONL](../../data/preparation/education/runtime842-2026-10-15/excerpts.jsonl)은 전체 발췌를 담는 생성 결과다.

- `mapped_draft`는 원문 구간을 지정한 초안이고 `needs_review`는 아직 구간을 선택하지 못한 상태다. 탐색 후보는 적합성이나 문서 부재를 증명하지 않는다.
- `source`는 카탈로그에 있는 guidelines 기준 상대 경로다. 문서의 `source_sha256`과 목록의 해시가 같아야 한다.
- `heading_path`는 실제 제목 계층이며 `start_line`·`end_line`은 1부터 시작하고 양끝을 포함한다. `selection=section`은 하위 제목까지 포함한 전체 구간, `selection=lines`는 해당 제목 안의 명시적 문단 범위다.
- 각 선택은 질환 확인·문서 역할·선정 이유·적용 대상·제한·조건 보존에 관한 설명을 가진다. 더 좁은 질환·연령·진료 상황의 권고를 다른 대상에게 자동 적용하지 않는다.
- 수정 후 `build`와 `verify`를 실행한다. 입력 manifest·카탈로그·원문이 바뀌면 새 목록을 만들고 관련 매핑을 다시 검토한다.

원문 언어·줄바꿈·조건·예외·표·인용을 그대로 보존하며 SAY의 30자 제한을 적용하지 않는다. 문서별 라이선스와 발행 정보를 함께 유지하고 제출 외 준비 영역에 둔다. 사용자 선택·독립 임상 검증·최신성 외부 확인·runtime plans 수용은 각각 별도이며, 도구에는 승인이나 제출 편입 명령이 없다.

준비 결과의 관측 증거는 [데이터 상태](../../data/PROJECT_STATE.md), 코드·검증과 교차 범위 인계는 [루트 상태](../../PROJECT_STATE.md), 선택은 [D16](../../DECISION_STATE.md#D16)이 소유한다.
