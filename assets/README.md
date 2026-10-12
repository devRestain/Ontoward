# NOVA 제공 자료 안내

이 README는 사람이 `assets/`에서 필요한 자료를 찾기 위한 시작점이다. 전체 디렉토리의 의미와 자료 사용 흐름은 [Architecture.md](Architecture.md)에 있다. 에이전트 작업 규칙은 [AGENTS.md](AGENTS.md)와 각 하위 디렉토리의 같은 이름 파일이 담당한다.

## 자료 선택

| 필요한 내용 | 읽을 위치 |
| --- | --- |
| 공모전 일정·규칙·API·평가·제출·운영 상태와 출처 | [공모전 참고 문서 안내](nova-competition-2026/README.md) |
| SDK·기본 에이전트·공식 샘플 클라이언트의 구성 | [시작 패키지 안내](nova-starter/README.md) |
| 로컬 모의 환자와 진찰 판정 도구 | [개발 키트 안내](nova-devkit/README.md) |
| 공개 증례와 모범 초진 기록 | [샘플 안내](nova-samples-2026/README.md), [키트 내 샘플 안내](nova-devkit/samples/README.md) |
| 외부 연구 데이터셋과 라이선스·인용 | [참고 벤치마크 안내](nova-benchmarks-2026/README.md) |
| 임상 Markdown 자료와 출처별 이용 조건 | [지침 코퍼스 안내](guidelines/README.md) |
| 출처별 문서 목록을 직접 탐색 | [CSV 목록](guidelines/catalog.csv), [워크북](guidelines/catalog.xlsx) |

원본 패키지 안의 README도 사람이 읽는 제공 자료 설명이다. 그 안의 예제 명령이나 수정 안내는 프로젝트 작업의 실행 허가를 대신하지 않는다.

## 사용할 때 확인할 점

샘플의 시작 정보는 Doctor의 초기 입력이고, 상세 대본·진찰표는 시뮬레이터의 입력이다. 모범 기록은 실행 후 비교 자료다. 이 세 역할을 섞으면 정보 획득과 기록 작성 과정을 제대로 검토하기 어렵다.

지침 폴더는 교과서형 개요, 근거 리뷰, 환자용 설명, 임상 지침을 함께 담는다. 필요한 문서의 유형·언어·날짜·발행기관·라이선스를 확인하며, KR·US 접두사를 언어 표시로 사용하지 않는다. 자세한 차이는 [출처별 설명](Architecture.md#진료지침-자료의-16개-출처)에 있다.

새 안내 파일은 원본 임상 자료가 아니다. 제출 전 임상 추출에는 `guidelines/catalog.csv`에 기록된 문서 경로를 사용하고 안내용 Markdown은 제외한다. 문서별 추출·검토 결과와 승인된 출처별 Turtle 묶음은 `data/`가 소유하며, 진료 중에는 준비된 RDF 지식만 조회한다.

## 프로젝트와 연결

자료를 바꾸지 않고 원래 위치에서 읽는다. 제출 전 준비 코드는 `Dev/`, 제출 에이전트와 실행 조회는 `submission/`, 출처 기록과 지속 응답·준비 결과·파생 자료는 `data/`가 담당한다. 현재 준비 환경은 [Dev 안내](../Dev/README.md), 실제 자료 진행은 [데이터 상태](../data/PROJECT_STATE.md), 전체 제품 요구사항은 [PRD](../PRD.md), 책임 구조는 [프로젝트 안내](../README.md)에서 확인한다.

공식 배포 맥락이 더 필요하면 [NOVA 개발 가이드](https://nova.snubhai.org/docs/)를 확인한다. 자료를 이해하기 위한 설명과 모델 연결·샘플 실행·제출은 별도의 작업 범위다.

## 추가 제공 발표 자료

[개회식 26장](nova-competition-2026/slides/opening-2026-10-06.md)과 [실행 흐름·진료 예시 22장](nova-competition-2026/slides/workflow-2026-10-11.md)은 MarkItDown 변환본이다. 최신 적용 내용과 과거 발표의 차이는 [10월 12일 비교](nova-competition-2026/CHANGES_2026-10-12.md)를 먼저 확인한다. 원본 PPTX는 assets 루트에 보존하며 이 자료를 제출물이나 임상 지식에 넣지 않는다.
