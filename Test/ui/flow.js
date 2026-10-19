const stateObjects = {
  interview: ['InterviewState', '질문과 수집 진행', '현재 세션 대기열, 작은 완료 기록, 필요한 중단 사유'],
  turn: ['TurnContext', '현재 작업', '노드 간 요청과 응답, 처리 후 해제'],
  case: ['CaseState', '환자 사실과 평가', '통합 facts와 graph_binding, chief, 현재·고정 Assessment와 영어 계획'],
  session: ['SessionContext', '세션과 예산', '현재 세션, 남은 턴, 모델 사용량, 종료 준비'],
  differential: ['DifferentialState', '추론 결과', '질환 후보, Pattern, 점수 기여, 선택된 후보'],
  questions: ['QuestionPlan', '질문 계획', '등록된 질문, 수집 상태, 선택 평가, 교육 계획'],
  interaction: ['InteractionState', '입출력과 전달', '입력, 선택 행동, 대화, 파서 결과, 제출 payload']
};
const roleNames = {
  DoctorEar: '입력 해석', DoctorBrain: 'LLM 호출', DoctorMouth: '환자 전달',
  InitiationSession: '초기 수집·평가', ChiefComplaintSession: '주호소 수집·평가',
  ContextFactorSession: '맥락 수집·평가', DifferentialDiagnosisSession: '감별·다음 행동', EducationSession: '계획·교육',
  InputBinding: 'Python 입력 연결', GraphEvidence: '그래프 후보·근거', EnglishPlan: '영어 계획',
  InputInterpreter: '해석', ClinicalKnowledge: 'DB 조회', ClinicalReasoner: '추론',
  InterviewPlanner: '계획', Doctor: '행동', SubmissionWriter: '제출',
  Consultation: '조정', ModelClient: '이전 모델 실행기', RequestExecutor: '전송', QuestionTools: '질문 계약',
  NovaSessionClient: '서버 상태', BudgetPolicy: '예산', InteractionLifecycle: '전달 상태',
  QuestionLifecycle: '질문 상태', UsageAccounting: '사용량', CanonicalSnapshot: '표준화', EvidenceIndex: '근거'
};
const flowSelection = new Map();
let objectSelection = 'case';
const eventIndex = new Map(events.map((event, index) => [event.seq, index]));
const callEnds = new Map(events.filter(event => event.kind === 'call_end' || event.kind === 'call_error').map(event => [event.call_id, event]));
const callStarts = new Map(events.filter(event => event.kind === 'call_start').map(event => [event.call_id, event]));
const sdkEnds = new Map();
let pendingSdk;
for (const event of events) {
  if (event.kind === 'sdk_request') pendingSdk = event;
  else if (pendingSdk && ['sdk_response', 'sdk_error'].includes(event.kind)) { sdkEnds.set(pendingSdk.seq, event); pendingSdk = null; }
}
const stateSchema = events.find(event => event.kind === 'settings')?.state_schema;
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);
const atPath = (value, path) => path.reduce((item, key) => resolveValue(item)?.[key], value);

function shortValue(value) {
  value = resolveValue(value);
  if (value === undefined) return '관측 없음';
  if (value === null) return 'null';
  if (typeof value === 'string') return value === '' ? '빈 문자열' : value;
  if (Array.isArray(value)) return `Array · ${value.length}개`;
  if (typeof value === 'object') {
    if (value.type && value.data !== undefined) return `${value.type} · ${shortValue(value.data)}`;
    if (value.state_reference) return 'WorkflowState · 호출 시점의 전체 상태';
    if (value.reference_only) return `${value.type} · 서비스 참조`;
    return `Object · ${Object.keys(value).length}개 필드`;
  }
  return String(value);
}

function resolveSchema(schema) {
  if (schema?.$ref) schema = stateSchema?.$defs?.[schema.$ref.split('/').pop()];
  if (schema?.anyOf) return resolveSchema(schema.anyOf.find(item => item.type !== 'null') || schema.anyOf[0]);
  return schema;
}

function dataTree(value, name = 'data', depth = 0, schema) {
  const reference=value?.trace_value_ref;
  value=resolveValue(value);
  schema = resolveSchema(schema);
  const complex = value !== null && typeof value === 'object';
  const encoded = typeof value === 'string' && /^[\s]*[\[{]/.test(value);
  let decoded;
  if (encoded) { try { decoded = JSON.parse(value); } catch {} }
  if (!complex && decoded === undefined) {
    const row = el('div', null, 'tree-leaf');
    row.append(el('span', name, 'tree-key'), el('span', shortValue(value), `tree-value ${typeof value}`));
    if (labels[value]) row.append(el('span', labels[value], 'concept-label'));
    return row;
  }
  const box = el('details', null, 'data-tree');
  const heading = el('summary');
  const typeName = schema?.properties && schema.title ? `${schema.title} · ` : '';
  heading.append(el('span', name, 'tree-key'), el('span', decoded !== undefined ? 'JSON 문자열 · 원문 보존' : typeName + shortValue(value), 'tree-type'));
  if(reference)heading.append(el('span',`저장 값 ${reference.slice(0,10)}`,'tree-type'));
  box.append(heading);
  let built = false;
  const build = () => {
    if (built) return;
    built = true;
    const content = el('div', null, 'tree-children');
    if (decoded !== undefined) {
      content.append(dataTree(decoded, '해독한 JSON', depth + 1), el('pre', value));
    } else {
      for (const [key, item] of Object.entries(value)) content.append(dataTree(item, key, depth + 1, schema?.properties?.[key] || schema?.items || schema?.additionalProperties));
      if (!Object.keys(value).length) content.append(note(Array.isArray(value) ? '빈 배열 []' : '빈 객체 {}'));
    }
    box.append(content);
  };
  box.addEventListener('toggle', () => { if (box.open) build(); });
  if (depth < 1) { box.open = true; build(); }
  return box;
}

function objectStateAt(index) {
  let state = null;
  for (let i = 0; i <= index; i++) {
    const event = events[i];
    if (event.object_state) state = copy(event.object_state);
    else if (state && event.object_patch) state = apply(state, event.object_patch);
  }
  return state;
}

function nodeSteps(group) {
  const nodes = [];
  let current;
  for (const event of group.events) {
    if (event.kind === 'node_start') {
      current = {kind: 'node', start: event, end: null, children: []};
      nodes.push(current);
    } else if (event.kind === 'call_start' || event.kind === 'sdk_request') {
      const step = {kind: event.kind === 'call_start' ? 'call' : 'sdk', start: event,
        end: callEnds.get(event.call_id)};
      if (step.kind === 'sdk') step.end = sdkEnds.get(event.seq);
      if (!current) { current = {kind: 'node', start: event, end: null, children: []}; nodes.push(current); }
      current.children.push(step);
    } else if (event.kind === 'node_end' || event.kind === 'node_error') {
      if (!current) { current = {kind: 'node', start: event, children: []}; nodes.push(current); }
      current.end = event;
      current = null;
    }
  }
  return nodes;
}

function stepName(step) {
  const event = step.start;
  if (step.kind === 'sdk') return `${event.method} ${event.path}`;
  return step.kind === 'call' ? callName(event) : event.operation || event.node || '초기 상태';
}

function callName(event) { return event.call_kind === 'function' ? event.callable : `${event.owner}.${event.method}`; }

function stepState(step, end = false) {
  const event = end ? step.end : step.start;
  if (!event) return null;
  const index = eventIndex.get(event.seq);
  return step.kind === 'call' ? objectStateAt(index) : stateAt(end ? index : index - 1);
}

function changeRows(before, after, patch, query = '') {
  const box = el('div', null, 'change-list');
  let rows = patch || [];
  if (query) rows = rows.filter(change => `${change.path.join('.')} ${JSON.stringify(atPath(before, change.path))} ${JSON.stringify(atPath(after, change.path))}`.toLowerCase().includes(query.toLowerCase()));
  if (!rows.length) { box.append(note(query ? '이 검색어에 맞는 변경이 없습니다.' : '이 구간에서 관측된 필드 변경이 없습니다.')); return box; }
  let count = 0;
  const more = el('button', '변경 더 보기', 'load-more'); more.type = 'button';
  const add = () => {
    const limit = Math.min(count + 60, rows.length);
    for (; count < limit; count++) {
      const change = rows[count], path = change.path;
      const row = el('details', null, `change-row ${change.op}`), summary = el('summary');
      summary.append(el('span', {add: '추가', remove: '삭제', replace: '변경'}[change.op] || change.op, 'change-kind'), el('code', path.join('.') || '(root)'));
      row.append(summary);
      row.addEventListener('toggle', () => {
        if (!row.open || row.querySelector('.value-pair')) return;
        const pair = el('div', null, 'value-pair');
        for (const [title, value] of [['이전', atPath(before, path)], ['이후', change.op === 'remove' ? undefined : change.value]]) {
          const side = el('div'); side.append(el('h4', title), dataTree(value, path[path.length - 1] || 'state')); pair.append(side);
        }
        row.append(pair);
      });
      box.append(row);
    }
    more.remove();
    if (count < rows.length) { more.textContent = `변경 더 보기 · ${count} / ${rows.length}`; box.append(more); }
  };
  more.addEventListener('click', add); add();
  return box;
}

function stepInspector(step, root) {
  root.replaceChildren();
  const start = step.start, end = step.end, failed = end?.kind?.endsWith('error');
  const before = stepState(step), after = stepState(step, true);
  root.append(el('span', step.kind === 'sdk' ? '실제 SDK 전송' : step.kind === 'call' ? start.call_kind==='function'?'관측된 Python 함수':'관측된 객체 호출' : '그래프 노드', 'inspector-kind'),
    el('h3', stepName(step)), note(`seq ${start.seq}${end ? ` → ${end.seq}` : ' · 종료 미수집'}${end?.elapsed !== undefined ? ` · ${(end.elapsed * 1000).toFixed(1)} ms` : ''}`));
  if (start.object_id) root.append(el('code', start.object_id, 'instance-path'));
  if (start.callable) root.append(note(`정의 위치: ${start.callable}`));
  if (failed) root.append(el('p', `${end.error}: ${end.message || ''}`, 'inline-error'));
  if (step.kind === 'sdk') {
    root.append(note(`상위 호출 #${start.parent_call_id ?? '미수집'} · request_id: ${start.request_id ?? '없음'}`),
      el('h4', '전송한 형식과 데이터'), dataTree(start.body, 'request.body'),
      el('h4', '수신 결과'), dataTree(end?.response ?? (end ? {error: end.error, message: end.message} : undefined), 'response'));
    return;
  }
  if (step.kind === 'call') {
    const parent = callStarts.get(start.parent_call_id);
    root.append(note(parent ? `호출한 객체: ${callName(parent)} → ${callName(start)}` : '그래프 노드가 호출한 최상위 객체입니다.'),
      el('h4', '입력 · 이름과 실제 자료형'), dataTree(start.inputs, 'arguments'));
    if (Object.values(start.inputs || {}).some(value => value?.state_reference)) {
      root.append(dataTree(before, 'WorkflowState · 호출 직전', 0, stateSchema));
    }
    root.append(el('h4', '출력 · return'), end ? dataTree(end.output, 'return') : note('반환값이 수집되지 않았습니다.'));
    if (parent && end && !failed) root.append(note(`반환 경로: ${callName(start)} → ${callName(parent)}`));
    if (end && end.output === null) root.append(note('return은 None입니다. 상태를 직접 갱신하는 메서드의 결과는 아래 변경분에 나타납니다.'));
    if (end?.argument_writes?.length) root.append(el('h4', '입력 인자에 직접 기록한 값'), changeRows(start.inputs, end.arguments_after, end.argument_writes));
  } else {
    root.append(note('WorkflowState를 deep copy한 뒤 검증된 dict로 다음 그래프 노드에 전달합니다.'),
      dataTree(before, 'WorkflowState · 입력', 0, stateSchema), dataTree(after, 'dict · 검증된 노드 출력', 0, stateSchema));
    if (Object.keys(end?.suppressed_calls || {}).length) root.append(note('임상 판단 안의 반복 DB·예산 조회는 횟수만 기록합니다. 그래프 후보 구성과 판단 결과는 별도 호출의 입력·반환에서 확인합니다.'), dataTree(end.suppressed_calls, '내부 반복 호출 · 상세 값 미수집'));
  }
  root.append(el('h4', '상태에 쓴 결과 · 하위 호출 포함'));
  const writes = step.kind === 'call' ? end?.writes : end?.patch;
  root.append(changeRows(before, after, writes));
  if (!end) root.append(note('호출이 끝나지 않았거나 수집이 중단되었습니다. 성공으로 해석하지 않습니다.'));
  root.append(jsonDetail('관측 이벤트 원본', {start, end: end || null}));
}

function stateStrip(before, after, onSelect) {
  const strip = el('div', null, 'state-strip');
  for (const [key, [type, title]] of Object.entries(stateObjects).filter(([key]) => after?.interview ? ['case','interview','session','turn'].includes(key) : !['interview','turn'].includes(key))) {
    const button = el('button', null, `state-cell ${after && !same(before?.[key], after[key]) ? 'changed' : ''}`); button.type = 'button';
    button.append(el('strong', type), el('span', title), el('small', !after ? '미수집' : same(before?.[key], after[key]) ? '유지' : '이 턴에서 변경'));
    button.addEventListener('click', () => onSelect(key)); strip.append(button);
  }
  return strip;
}

function flowPanel(group, before, after) {
  const root = panel('객체 사이의 정보 흐름'); root.className += ' flow-panel';
  const nodes = nodeSteps(group), calls = group.events.filter(event => event.kind === 'call_start');
  root.append(note('위에서 아래로 실제 실행 순서를 읽습니다. 객체나 전달 단계를 선택하면 입력 → 반환값 → 상태 변경을 확인할 수 있습니다.'));
  if (!calls.length) root.append(el('p', '이 실행은 객체 메서드 호출을 수집하지 않았습니다. 저장된 그래프 노드와 SDK 전송만 표시합니다. 새 관측 실행부터 내부 객체와 반환값이 기록됩니다.', 'coverage-message'));
  const heading = el('div', null, 'flow-legend');
  heading.append(el('span', `그래프 ${nodes.length}단계`), el('span', `내부 호출 ${calls.length}회`), el('span', `SDK 전송 ${group.events.filter(e => e.kind === 'sdk_request').length}회`));
  root.append(heading, stateStrip(before, after, key => { objectSelection = key; tab = 'objects'; detail(); $('tab-objects').focus(); }));
  root.append(pipelinePath(group.events));
  if (!nodes.length) { root.append(note(after ? '초기 WorkflowState입니다. 각 상태 객체를 선택해 초기 데이터를 확인하세요.' : '이 구간에는 내부 실행 관측이 없습니다. 대화와 수신 기록 탭에서 보존된 결과를 확인하세요.')); return root; }
  const workbench = el('div', null, 'flow-workbench'), sequence = el('div', null, 'flow-sequence'), inspector = el('aside', null, 'flow-inspector');
  inspector.setAttribute('aria-label', '선택한 실행 단계의 입출력');
  const buttons = [];
  const choose = (step, button) => {
    flowSelection.set(selected, step.start.seq + ':' + step.kind);
    for (const item of buttons) item.setAttribute('aria-pressed', item === button ? 'true' : 'false');
    stepInspector(step, inspector);
  };
  const makeButton = (step, title, cls) => {
    const owner = step.start.owner || step.start.operation?.split('.')[0] || 'graph';
    const button = el('button', null, `${cls} role-${owner}`); button.type = 'button'; button.setAttribute('aria-pressed', 'false');
    button.append(el('span', title), el('small', step.kind === 'sdk' ? `body → ${step.end?.kind === 'sdk_response' ? 'response' : '미완료 / 오류'}` : `seq ${step.start.seq} · ${roleNames[step.start.owner] || '상태 전달'}`));
    button.addEventListener('click', () => choose(step, button)); buttons.push(button);
    return button;
  };
  let initial;
  nodes.forEach((step, index) => {
    const block = el('article', null, 'flow-node');
    block.append(el('span', String(index + 1).padStart(2, '0'), 'flow-index'));
    const main = makeButton(step, stepName(step), 'flow-node-button');
    main.append(el('small', `graph.${step.start.node || 'unknown'} · ${step.end?.kind === 'node_error' ? '오류' : step.end ? '완료' : '종료 미수집'}`, 'graph-name'));
    block.append(main);
    if (!initial) initial = [step, main];
    if (flowSelection.get(selected) === step.start.seq + ':' + step.kind) initial = [step, main];
    if (step.children.length) {
      const nested = el('details', null, 'nested-calls');
      nested.append(el('summary', `내부 호출과 전달 ${step.children.length}개`));
      let rendered = false;
      const build = () => {
        if (rendered) return; rendered = true;
        let count = 0;
        const more = el('button', '호출 더 보기', 'load-more'); more.type = 'button';
        const add = () => {
          const limit = Math.min(count + 80, step.children.length);
          for (; count < limit; count++) {
            const child = step.children[count], button = makeButton(child, stepName(child), child.kind === 'sdk' ? 'flow-call sdk-call' : 'flow-call');
            const parent = step.children.find(item => item.start.call_id === child.start.parent_call_id);
            if (parent) button.append(el('small', `호출자: ${callName(parent.start)}`, 'caller-name'));
            nested.append(button);
            if (flowSelection.get(selected) === child.start.seq + ':' + child.kind) { initial = [child, button]; choose(child, button); }
          }
          more.remove(); if (count < step.children.length) { more.textContent = `호출 더 보기 · ${count} / ${step.children.length}`; nested.append(more); }
        };
        more.addEventListener('click', add); add();
      };
      nested.addEventListener('toggle', () => { if (nested.open) build(); });
      if (nodes.length <= 4 || step.children.some(child => flowSelection.get(selected) === child.start.seq + ':' + child.kind)) { nested.open = true; build(); }
      block.append(nested);
    }
    sequence.append(block);
    if (index < nodes.length - 1) sequence.append(el('div', '↓ WorkflowState → 검증된 dict → 다음 노드', 'flow-transfer'));
  });
  workbench.append(sequence, inspector); root.append(workbench);
  if (initial) choose(...initial);
  root.append(note('색상과 함께 객체 이름·메서드·호출자·seq를 표시합니다. 변경분은 실제 쓰기 결과이며 개별 필드를 읽었다는 추정은 하지 않습니다.'));
  return root;
}

function objectPanel(group, before, after) {
  const root = panel('정보를 가진 객체와 턴별 변화');
  if (!after) { root.append(note('이 실행에는 내부 객체 상태가 수집되지 않았습니다.')); return root; }
  root.append(note(after.interview?'WorkflowState의 상주 상태 3개와 현재 턴 작업을 구분합니다. 현재 턴 응답은 처리 후 해제됩니다.':'저장된 WorkflowState의 다섯 상태 객체를 경로와 자료형으로 구분합니다.'));
  if(after.interview&&!['case','interview','session','turn'].includes(objectSelection))objectSelection='case';
  const workbench = el('div', null, 'object-workbench'), catalog = el('nav', null, 'object-catalog'), inspector = el('div', null, 'object-inspector');
  catalog.setAttribute('aria-label', 'WorkflowState 객체');
  for (const [key, [type, title, description]] of Object.entries(stateObjects).filter(([key]) => after?.interview ? ['case','interview','session','turn'].includes(key) : !['interview','turn'].includes(key))) {
    const button = el('button', null, 'object-button'); button.type = 'button'; button.setAttribute('aria-pressed', objectSelection === key ? 'true' : 'false');
    button.append(el('strong', type), el('code', `state.${key}`), el('span', title), el('small', description));
    button.addEventListener('click', () => { objectSelection = key; detail(); }); catalog.append(button);
  }
  const key = objectSelection, old = before?.[key], value = after[key], type = stateObjects[key][0];
  inspector.append(el('h3', type), el('code', `WorkflowState.${key}`, 'instance-path'));
  const life = el('div', null, 'object-lifeline'); life.setAttribute('aria-label', `${type}의 변경 턴`);
  for (let index = 0; index < groups.length; index++) {
    const g = groups[index];
    const changed = g.events.some(event => event.kind === 'initial' && event.state?.[key] !== undefined || event.patch?.some(change => !change.path.length || change.path[0] === key));
    if (!changed) continue;
    const button = el('button', `${g.turn}`, 'life-turn'); button.type = 'button';
    button.setAttribute('aria-current', index === selected ? 'true' : 'false');
    button.title = `${scopes[g.session] || g.session} · 턴 ${g.turn}에서 변경`;
    button.addEventListener('click', () => select(index)); life.append(button);
  }
  inspector.append(note('이 객체가 바뀐 턴 · 선택하면 해당 시점으로 이동'), life);
  // Compare endpoints once: intermediate writes remain inspectable at each flow step.
  const endpoints = diffValues(old, value);
  const label = el('label', '변경 경로와 값 검색', 'search-label'), search = el('input');
  search.type = 'search'; search.placeholder = '예: incoming, concept_ids, diagnosis'; search.setAttribute('aria-label', '객체의 변경 경로와 값 검색');
  const changes = el('div');
  const renderChanges = () => changes.replaceChildren(changeRows(old, value, endpoints, search.value));
  search.addEventListener('input', renderChanges);
  inspector.append(el('h4', `이 턴의 최종 변화 · ${endpoints.length}개 경로`), label, search, changes); renderChanges();
  const pair = el('div', null, 'value-pair');
  for (const [title, data] of [['턴 이전', old], ['턴 이후', value]]) { const side = el('div'); side.append(el('h4', title), dataTree(data, type, 0, stateSchema?.properties?.[key])); pair.append(side); }
  inspector.append(pair);
  const outputs = group.events.filter(event => event.kind === 'call_end' && event.output !== null && event.output !== undefined);
  if (outputs.length) {
    const temporary = el('details', null, 'transient-objects'); temporary.append(el('summary', `이 턴에서 반환된 임시 데이터 객체 ${outputs.length}개`));
    let built = false;
    temporary.addEventListener('toggle', () => {
      if (!temporary.open || built) return; built = true;
      for (const event of outputs) temporary.append(dataTree(event.output, `${event.owner}.${event.method} · seq ${event.seq}`));
    }); inspector.append(temporary);
  }
  const settings = events.find(event => event.kind === 'settings');
  inspector.append(jsonDetail('관측 대상 실행 객체와 메서드', settings?.objects || {status: '이전 수집 형식 · 객체 목록 미수집'}));
  workbench.append(catalog, inspector); root.append(workbench);
  return root;
}

function diffValues(before, after, path = []) {
  if (same(before, after)) return [];
  if (before === undefined) return [{op: 'add', path, value: after}];
  if (after === undefined) return [{op: 'remove', path}];
  if (before === null || after === null || typeof before !== 'object' || typeof after !== 'object' || Array.isArray(before) !== Array.isArray(after)) return [{op: 'replace', path, value: after}];
  const result = [];
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) result.push(...diffValues(before[key], after[key], [...path, key]));
  return result;
}

function jumpToEvent(event) {
  const index=groups.findIndex(group=>group.events.some(row=>row.seq===event.seq));
  if(index<0)return;
  $('session-filter').value='';tab='flow';
  flowSelection.set(index,`${event.seq}:call`);select(index);
  $('tab-flow').focus();
}

function pipelinePath(rows) {
  const root=el('div',null,'pipeline-path');root.setAttribute('aria-label','관측된 역할별 호출');
  for(const [owner,title] of [['DoctorEar','입력 → 통합 사실'],['InitiationSession','초기 수집 → 첫 평가'],
    ['ChiefComplaintSession','주호소 → 종료 평가'],['ContextFactorSession','CC 감별 → 맥락 → 평가'],
    ['DifferentialDiagnosisSession','응답 → 순위·질문 → 고정'],['EducationSession','고정 진단 → 계획'],
    ['DoctorBrain','준비된 입력 → LLM 응답'],['DoctorMouth','표현 → SAY·EXAM'],['SubmissionWriter','SOAP → DIAGNOSE']]){
    const calls=rows.filter(row=>row.kind==='call_start'&&row.owner===owner);
    const button=el('button',null,'pipeline-stage');button.type='button';button.disabled=!calls.length;
    button.append(el('strong',owner),el('small',title),el('small',calls.length?`${calls.length}회 · 첫 호출 보기`:'이 구간에서 호출 미관측'));
    button.addEventListener('click',()=>jumpToEvent(calls[0]));root.append(button);
  }
  return root;
}

function executionPanel() {
  const root=panel('전체 실행 검증과 관측 범위'),inspection=data.inspection;
  root.append(note('보존된 trace와 수신 기록만 검사합니다. 고정 응답 실행의 의미 해석·임상 정확도와 공식 채점은 검증하지 않습니다.'),pipelinePath(events));
  if(!inspection){root.append(el('p','이 저장 리포트에는 실행 검증 파일이 없습니다. 웹에서 리포트를 다시 열면 보존 로그로 생성합니다.','coverage-message'));return root;}
  root.append(kv([['실행 알고리즘',inspection.runtime?.algorithm||'당시 미수집'],['상태 구조',inspection.state_layout],
    ['관측 검사',inspection.status],['Assessment 고정',inspection.frozen?`seq ${inspection.frozen.seq} · ${inspection.frozen.primary}`:'미관측']]));
  const titles={event_sequence:'이벤트 순서',trace_boundaries:'수집 시작·종료',recorded_values:'저장 값 참조의 완전성',call_boundaries:'객체 호출·반환과 부모 연결',node_boundaries:'노드 시작·종료',sdk_boundaries:'SDK 요청·응답',state_reconstruction:'전체 노드 상태 복원',graph_transitions:'실제 그래프 경로',frozen_patient_state:'고정 후 사실·평가 보존',assessment_revision:'고정 평가의 revision·chief 일치',submission_primary:'고정 1위와 제출 진단 일치',received_soap:'전송 SOAP와 수신 기록 일치',confirmed_completion:'로컬 완료 영수증과 종료 상태'};
  for(const check of inspection.checks){
    const row=el('div',null,'inspection-check'),status=el('span',({pass:'확인',fail:'불일치',not_collected:'미수집'})[check.status]||check.status,`badge ${check.status==='pass'?'good':'warn'}`);
    const content=el('div');content.append(el('strong',titles[check.id]||check.id),jsonDetail('판정 근거',check.detail));row.append(status,content);root.append(row);
  }
  const graph=el('details',null,'detail-json');graph.append(el('summary','런타임 그래프 · 실제로 지난 연결과 미실행 분기'));
  graph.addEventListener('toggle',()=>{
    if(!graph.open||graph.querySelector('table'))return;
    if(!inspection.graph){graph.append(note('이전 trace에는 그래프 구조가 수집되지 않았습니다.'));return;}
    const table=el('table',null,'data-table'),head=el('tr');for(const title of ['출발 노드','도착 노드','관측 횟수'])head.append(el('th',title));table.append(head);
    for(const edge of inspection.graph.edges){const count=inspection.transitions.find(item=>item.source===edge.source&&item.target===edge.target)?.count||0,row=el('tr'),boundary=edge.source==='__start__'||edge.target==='__end__';for(const value of [edge.source,edge.target,count||(boundary?'경계 · 호출 관측 제외':'미실행')])row.append(el('td',value));table.append(row);}graph.append(table);
  });
  root.append(graph,jsonDetail('노드별 revision · facts · Assessment · TurnContext 생애',inspection.checkpoints),
    jsonDetail('실제 실행 소스 SHA256 · manifest',inspection.runtime||{status:'당시 미수집'}));
  const coverage=el('details',null,'detail-json');coverage.append(el('summary','관측 대상 메서드 · 실제 호출 수'));
  coverage.addEventListener('toggle',()=>{
    if(!coverage.open||coverage.querySelector('table'))return;
    const table=el('table',null,'data-table');
    for(const object of inspection.declared_objects)for(const method of object.methods){const row=el('tr');row.append(el('td',object.callable||`${object.type}.${method}`),el('td',inspection.observed_methods[`${object.owner||object.type}.${method}`]||'이 실행에서 미호출'));table.append(row);}
    coverage.append(table);
  });
  root.append(coverage,note(inspection.limits.scope),note('큰 직렬화 값은 내용 해시로 한 번 저장하고 펼칠 때 참조를 해독합니다. 같은 저장 값은 내용의 일치만 뜻하며 Python 인스턴스의 동일성을 뜻하지 않습니다.'),note('반복 조회의 상세 값·Python heap·개별 필드 읽기는 수집하지 않습니다. 미실행 분기와 과거 로그의 미수집 정보를 추정하지 않습니다.'));
  return root;
}

timeline(); detail();
