const data=JSON.parse(document.getElementById('report-data').textContent);
const events=data.trace.events, labels=Object.assign({},...events.filter(e=>e.kind==='labels').map(e=>e.labels));
const scopes={Initiation:'시작',ChiefComplaint:'주호소',ContextFactor:'병력·맥락',DifferentialDiagnosis:'감별 진단',Education:'교육'};
const $=id=>document.getElementById(id), copy=value=>JSON.parse(JSON.stringify(value));
function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined&&text!==null)node.textContent=String(text);if(cls)node.className=cls;return node;}
function jsonDetail(title,value){
  const box=el('details',null,'detail-json');box.append(el('summary',title));
  box.addEventListener('toggle',()=>{if(box.open&&!box.querySelector('pre'))box.append(el('pre',typeof value==='string'?value:JSON.stringify(value,null,2)));});return box;
}
function panel(title){const node=el('section',null,'panel');node.append(el('h3',title));return node;}
function note(text){return el('p',text,'muted small');}
function kv(values){const list=el('dl',null,'key-value');for(const [key,value] of values){list.append(el('dt',key),el('dd',value??'—'));}return list;}
function labeled(id){return labels[id]?`${labels[id]} · ${id}`:id;}
function apply(state,patch){
  for(const change of patch||[]){
    const path=change.path;
    if(!path.length){state=copy(change.value);continue;}
    let parent=state;for(const key of path.slice(0,-1))parent=parent[key];
    const key=path[path.length-1];
    if(change.op==='remove'){if(Array.isArray(parent))parent.splice(key,1);else delete parent[key];}
    else if(change.op==='add'&&Array.isArray(parent))parent.splice(key,0,copy(change.value));
    else Object.defineProperty(parent,key,{value:copy(change.value),enumerable:true,writable:true,configurable:true});
  }return state;
}
function stateAt(index){let state=null;for(let i=0;i<=index;i++){const row=events[i];if(row.kind==='initial')state=copy(row.state);else if(state&&row.patch)state=apply(state,row.patch);}return state;}
const groups=[];
let pending=[],boundary=-1;
for(let i=0;i<events.length;i++){
  const row=events[i];pending.push(row);
  if(row.kind==='initial'||row.kind==='node_end'||row.kind==='node_error'){
    const previous=groups[groups.length-1];
    const session=row.session??previous?.session??'unknown',turn=row.turn??previous?.turn??0;
    let group=previous;
    if(!group||group.session!==session||group.turn!==turn){group={session,turn,before:boundary,to:i,events:[]};groups.push(group);}
    group.to=i;for(const event of pending)group.events.push(event);pending=[];boundary=i;
  }
}
if(pending.length&&groups.length){for(const event of pending)groups[groups.length-1].events.push(event);groups[groups.length-1].to=events.length-1;}
if(!groups.length){
  groups.push({session:'unknown',turn:0,before:-1,to:events.length-1,events:[...events],initial:true});
  for(const row of data.transcript.events||[])groups.push({session:'unknown',turn:row.turn??'—',before:-1,to:-1,events:[],legacy:row});
}
const requestIds=group=>new Set([...group.events.map(row=>row.request_id).filter(Boolean),...(group.legacy?[group.legacy.request_id]:[])]);
function actions(group){const ids=requestIds(group);return group.legacy?[group.legacy]:(data.transcript.events||[]).filter(row=>ids.has(row.request_id));}
let selected=0,tab='flow';
function visible(){const scope=$('session-filter').value;return groups.map((g,i)=>({g,i})).filter(({g})=>!scope||g.session===scope);}
function timeline(){
  const root=$('timeline');root.replaceChildren();
  for(const {g,i} of visible()){
    const button=el('button',null,'turn-button');button.type='button';button.setAttribute('aria-current',i===selected?'true':'false');
    button.append(el('span',`TURN ${String(g.turn).padStart(2,'0')}`,'number'),el('span',scopes[g.session]||'내부 상태 미수집','name'));
    const action=actions(g).find(row=>row.content);
    button.append(el('span',action?.content||g.events.find(row=>row.kind==='node_error')?.error||'상태 처리','preview'));
    button.addEventListener('click',()=>select(i));root.append(button);
  }
}
function select(index){selected=index;timeline();detail();}
function speech(parent,who,text,doctor=false){if(text!==undefined&&text!==null){const node=el('div',null,`speech${doctor?' doctor':''}`);node.append(el('span',who,'who'),el('span',text));parent.append(node);}}
function conversation(group,after){
  const root=panel('실제로 전달된 대화와 행동');
  if(selected===0)speech(root,'환자 · 초기 발화',data.transcript.initial?.opening);
  const rows=actions(group);
  for(const row of rows){
    const box=el('div');box.id=`action-${row.request_id}`;
    if(row.action==='DIAGNOSE'){box.append(note('진단 제출'),jsonDetail('제출 응답',row.response||row));}
    else {
      speech(box,row.action==='EXAM'?'Doctor · 진찰 요청':'Doctor',row.content,true);
      if(row.effective_content&&row.effective_content!==row.content)speech(box,'시뮬레이터가 처리한 발화',row.effective_content);
      if(row.response)speech(box,row.action==='EXAM'?'진찰 결과':'환자',row.response.content??row.response.result);
      if(row.error)box.append(el('p',row.error,'inline-error'));
      box.append(jsonDetail('요청 ID · 실제 응답',row));
    }root.append(box);
  }
  const delivered=new Set(rows.map(row=>row.request_id));
  for(const row of group.events.filter(row=>row.kind==='sdk_error'||row.kind==='node_error'))root.append(el('p',`${row.error}: ${row.message||''}`,'inline-error'));
  for(const row of group.events.filter(row=>row.kind==='sdk_request'&&row.body?.action&&!delivered.has(row.request_id)))root.append(jsonDetail('완료 응답이 없는 요청 · 대화 전달 미확인',row));
  if(!rows.length&&selected!==0)root.append(note('이 구간에는 실제 SAY/EXAM 응답이 없습니다.'));
  const history=after?.interaction?.history||[];
  const ids=requestIds(group);
  for(const row of history.filter(row=>ids.has(row.id)&&!row.delivered))root.append(jsonDetail('에이전트의 미전달 이력',row));
  return root;
}
function records(state){const result=[];for(const section of ['S','O','A','P'])for(const [field,items] of Object.entries(state?.case?.[section]||{}))for(const item of Object.values(items))result.push({field:`${section}.${field}`,...item});return result;}
function evidence(parent,ids,state){
  const all=records(state),history=state?.interaction?.history||[];
  for(const id of ids||[]){
    const item=all.find(row=>row.id===id),entry=history.find(row=>row.id===id);
    const button=el('button',item?`${item.field} · ${item.value?.text||id}`:id,'evidence-button');button.type='button';
    button.addEventListener('click',()=>{
      let box=parent.querySelector('.evidence-focus');if(box)box.remove();
      box=el('div',null,'record-block evidence-focus');box.append(el('h3','기록된 근거'),el('pre',JSON.stringify(item||entry||{id,label:labels[id]||null},null,2)));
      if(item)for(const ref of item.source_refs||[]){const source=history.find(row=>row.id===ref);if(source)box.append(el('pre',JSON.stringify(source,null,2)));}
      parent.append(box);box.tabIndex=-1;box.focus();
    });parent.append(button);
  }
}
function statePanel(group,before,after){
  const root=panel('턴 전후 상태');
  if(!after){root.append(note('이 실행에는 내부 상태 관측 로그가 없습니다.'));return root;}
  const prev=before?.session||{},next=after.session;
  root.append(kv([['내부 세션',`${prev.current||'초기화 전'} → ${next.current}`],['남은 턴',`${prev.turns_remaining??'—'} → ${next.turns_remaining}`],['Gateway 호출',`${prev.doctor_calls??0} → ${next.doctor_calls}`],['입력 / 출력 토큰',`${next.input_tokens} / ${next.output_tokens}`],['명료화 횟수',next.clarifications],['종료 상태',after.interaction.termination||'진행 중']]));
  const oldRecords=new Map(records(before).map(row=>[row.id,row]));
  const changed=records(after).filter(row=>JSON.stringify(row)!==JSON.stringify(oldRecords.get(row.id)));
  const acquired=changed.filter(row=>row.status==='done');
  if(acquired.length){root.append(el('h3','추가·변경된 사실'));for(const row of acquired){const item=el('div',null,'record-block');item.append(el('strong',`${row.field} · ${row.value?.text||row.id}`),note(`${row.value?.status||row.status} · ${row.value?.subject||'—'} · ${row.value?.time_context||'—'}`));item.append(jsonDetail('값 · 원문 출처 · 연결',row));evidence(item,row.source_refs,after);root.append(item);}}
  const previousModels=before?.interaction?.model_history?.length||0;
  const newModels=(after.interaction.model_history||[]).slice(previousModels);
  for(const model of newModels)if(model.parser_result)root.append(jsonDetail('Gateway 해석 결과 · 연결·수용 검증',model.parser_result));
  root.append(jsonDetail('선택된 행동과 질문',after.interaction.selected),jsonDetail('질문 계획 · 턴 전',before?.questions||null),jsonDetail('질문 계획 · 턴 후',after.questions));
  if(after.interaction.parse_rejections?.length)root.append(jsonDetail('거절·미해결 해석',after.interaction.parse_rejections));
  root.append(jsonDetail('세션별 사용량과 전체 설정',next),jsonDetail('노드별 상태 변경분',group.events.filter(row=>row.patch)),jsonDetail('전체 상태 · 턴 전',before),jsonDetail('전체 상태 · 턴 후',after));
  return root;
}
const noteFields={
  S:{cc:'주호소',hpi:'현병력',pmh:'과거력',fh:'가족력',sh:'사회력',ros:'계통 문진'},
  O:{exam:'진찰',tests:'검사'},
  A:{evidence:'판단 근거',differential:'감별 진단'},
  P:{tests:'추가 검사',treatment:'치료',disposition:'처치 결정',follow_up:'추적',education:'환자 교육'}
};
const noteNames={S:'주관적 정보',O:'객관적 정보',A:'판단',P:'계획'};
function soapNote(title,payload){
  const box=el('details',null,'note-payload');box.append(el('summary',title));
  box.append(kv([['diagnosis',payload.diagnosis??'미설정']]));
  for(const [section,fields] of Object.entries(noteFields)){
    const block=el('section',null,'record-block');block.append(el('h4',`${section} · ${noteNames[section]}`));
    for(const [field,name] of Object.entries(fields)){
      const value=payload.note?.[section]?.[field];
      block.append(el('strong',`${section}.${field} · ${name}`),el('p',value===undefined?'(필드 미수집)':value===''?'(빈 문자열)':value,'note-text'));
    }box.append(block);
  }
  box.append(jsonDetail('SOAP payload 원본',payload));return box;
}
function noteRecord(item,before,state){
  const card=el('article',null,'note-record');
  card.append(el('strong',item.value?.text||item.id));
  const status=el('div',null,'note-status');
  status.append(el('span',`${{done:'완료',unasked:'미질문'}[item.status]||'미수집'} · ${item.status??'—'}`,'badge'));
  if(item.value){const value=item.value.status;status.append(el('span',`${{present:'양성',absent:'음성',uncertain:'불확실',unknown:'미확인'}[value]||'미수집'} · ${value??'—'}`,`badge ${value==='uncertain'||value==='unknown'?'warn':''}`));}
  else status.append(el('span','값 미설정','badge'));
  if(JSON.stringify(before)!==JSON.stringify(item))status.append(el('span',before?'이 구간에서 변경':'이 구간에서 추가','badge good'));
  card.append(status,note(`기록 ID: ${item.id} · 내부 세션: ${scopes[item.scope]||item.scope||'미수집'}`));
  const value=item.value;
  card.append(kv([['취득 경로 · acquisition',item.acquisition??'미설정 / 미수집'],
    ...(value?[['값 종류 · kind',value.kind],['주체 / 시점',`${value.subject??'—'} / ${value.time_context??'—'}`],
    ['개념 · concept_ids',(value.concept_ids||[]).map(labeled).join('\n')||'없음'],
    ['관찰 / 에피소드',`${value.observation_id??'—'} / ${value.episode_id??'—'}`]]:[])]));
  if(value?.attribute_id)card.append(kv([['속성',labeled(value.attribute_id)],['속성 값',(value.values||[]).map(labeled).join('\n')||'없음']]));
  if(value?.measurement)card.append(jsonDetail('수치 · 단위 · 범위',value.measurement));
  if(value?.record_category)card.append(note(`의무기록 범주 · ${value.record_category}`));
  for(const detail of value?.record_details||[]){card.append(el('p',detail.english,'note-text'),el('blockquote',detail.quote,'note-quote'));}
  if(item.source_refs?.length){card.append(note('원문 출처 · source_refs'));evidence(card,item.source_refs,state);}
  if(item.context_refs?.length){card.append(note('해석 문맥 · context_refs'));evidence(card,item.context_refs,state);}
  card.append(jsonDetail('기록 원본 · 상태와 연결',item));return card;
}
function notePanel(group,before,after){
  const root=panel('Note 상태 · S / O / A / P / diagnosis');
  if(!after?.case){
    root.append(note('이 실행에는 턴별 Note 내부 상태가 수집되지 않았습니다. 빈 Note로 추정하지 않습니다.'));
    if(data.record.note)root.append(soapNote('최종 수신된 SOAP · 선택 턴의 상태가 아님',data.record));
    return root;
  }
  const last=[...group.events].reverse().find(row=>row.kind==='node_end'||row.kind==='node_error'||row.kind==='initial');
  root.append(note(`선택 구간의 마지막 관측 상태 · ${last?.node||last?.kind||'미확인'} · seq ${last?.seq??'—'}`),
    note('case에 저장된 기록을 필드별로 표시합니다. 완료 상태와 임상 값 상태는 별개이며, 저장된 기록 모두가 최종 SOAP에 포함되는 것은 아닙니다. 정정·상충 처리 후의 실제 제출 문자열은 아래 SOAP payload에서 확인하세요.'));
  for(const [section,fields] of Object.entries(noteFields)){
    const block=el('section',null,'note-section');block.append(el('h4',`${section} · ${noteNames[section]}`),note(`상태 경로: case.${section} → note.${section}`));
    for(const [field,name] of Object.entries(fields)){
      const items=after.case[section]?.[field],rows=Object.values(items||{}),done=rows.filter(row=>row.status==='done').length;
      const box=el('details',null,'note-field');box.open=done>0;
      box.append(el('summary',`${section}.${field} · ${name} — ${items===undefined?'필드 미수집':`완료 ${done} / 전체 ${rows.length}건`}`));
      if(!rows.length)box.append(note(items===undefined?'관측 로그에 이 필드가 없습니다.':'이 시점에 저장된 기록이 없습니다.'));
      for(const row of rows)box.append(noteRecord(row,before?.case?.[section]?.[field]?.[row.id],after));
      block.append(box);
    }root.append(block);
  }
  const reports=(after.interaction?.patient_reports||[]).filter(report=>report.uncovered_spans?.length);
  if(reports.length){
    const block=el('section',null,'note-section');block.append(el('h4','원문 감사 기록 · 미구조화 환자 보고'),note('interaction.patient_reports에 보존된 원문 구간입니다. 원문 보존과 canonical 사실 수용은 별개이며 실제 SOAP 반영 여부는 생성된 제출 payload에서 확인합니다.'));
    for(const report of reports){
      const card=el('article',null,'note-record');card.append(note(`출처: ${report.source_id}`));
      for(const [start,end] of report.uncovered_spans)card.append(el('blockquote',Array.from(report.text).slice(start,end).join(''),'note-quote'));
      card.append(jsonDetail('원문 · 수용 인용 구간 · 미포함 구간',report));evidence(card,[report.source_id],after);block.append(card);
    }root.append(block);
  }
  const diagnosis=el('section',null,'note-section');diagnosis.append(el('h4','diagnosis · 별도 제출 필드'),
    note('case.diagnosis → submission_payload.diagnosis입니다. note.A와 별도로 제출합니다.'),
    kv([['case.diagnosis',after.case.diagnosis??'아직 설정되지 않음'],['case.diagnosis_kind',after.case.diagnosis_kind??'미설정'],
      ['선택된 질환 ID',after.differential?.selected_id?labeled(after.differential.selected_id):'미설정'],
      ['고정된 진단',after.case.fixed_diagnosis?.name??'미설정 / 미수집']]));
  diagnosis.append(note('진단 근거 · case.diagnosis_evidence'));evidence(diagnosis,after.case.diagnosis_evidence,after);
  if(!after.case.diagnosis_evidence?.length)diagnosis.append(note('기록된 근거 ID가 없습니다.'));
  diagnosis.append(jsonDetail('고정 진단 원본 · fixed_diagnosis',after.case.fixed_diagnosis??null));root.append(diagnosis);
  const payload=after.interaction?.submission_payload;
  if(payload?.note)root.append(soapNote('이 시점에 생성된 SOAP payload · 수신 확인과 별개',payload));
  else root.append(note('이 시점에는 interaction.submission_payload.note가 아직 생성되지 않았습니다. 최종 제출 SOAP는 상단의 수신 기록에서 확인하세요.'));
  return root;
}
function diagnosisPanel(before,after){
  const root=panel('기록된 진단 후보와 근거');
  if(!after){root.append(note('이 실행에는 후보와 선택 상태가 수집되지 않았습니다.'));return root;}
  const chosen=after.differential.selected_id;
  root.append(kv([['현재 진단',after.case.diagnosis||'아직 설정되지 않음'],['진단 종류',after.case.diagnosis_kind||'—'],['선택된 질환 ID',chosen?labeled(chosen):'없음']]));
  if(before?.case?.diagnosis!==after.case.diagnosis)root.append(el('p',`${before?.case?.diagnosis||'미설정'} → ${after.case.diagnosis||'미설정'}`,'diagnosis-change'));
  evidence(root,after.case.diagnosis_evidence,after);
  const candidates=after.differential.hypotheses||[];
  if(candidates.length){
    root.append(note('에이전트에 기록된 후보 순서입니다. 총점 = 근거 점수 + 맥락 가산 − 모순 감점.'));
    const wrap=el('div',null,'table-wrap'),table=el('table',null,'data-table'),head=el('tr');
    for(const text of ['후보','총점','근거','맥락','감점','주호소 포함률'])head.append(el('th',text));table.append(head);
    for(const h of candidates){const row=el('tr',null,h.disease_id===chosen?'chosen':'');for(const value of [labeled(h.disease_id),Math.round((h.evidence_score+(h.context_bonus||0)-h.contradiction_penalty)*1000)/1000,h.evidence_score,h.context_bonus??0,h.contradiction_penalty,`${Math.round(h.chief_coverage*100)}%`])row.append(el('td',value));table.append(row);}
    wrap.append(table);root.append(wrap);
    for(const h of candidates){const details=jsonDetail(`${labels[h.disease_id]||h.disease_id} · 점수 기여·조건·Pattern`,h);root.append(details);}
  }else root.append(note('이 시점에 기록된 질환 후보가 없습니다.'));
  root.append(jsonDetail('Pattern 일치·모순·미해결 상태',after.differential.pattern_matches),jsonDetail('Association 적용 상태',after.differential.association_matches));return root;
}
function modelPanel(group,before,after){
  const root=panel('실제 모델 요청과 응답'),ids=requestIds(group),calls=new Map();
  for(const row of data.models)if(ids.has(row.parent_request_id)||ids.has(row.request_id))calls.set(row.request_id,row);
  for(const row of calls.values()){
    const card=el('div',null,'model-card');card.append(el('strong',`${row.role} · ${row.status}`),note(row.backend==='scripted'?'오프라인 응답 대역 · 외부 모델 호출 없음':`${row.backend} · ${row.model} · reasoning ${row.reasoning_effort} · 최대 ${row.max_tokens} 출력 토큰`));
    const content=row.response?.choices?.[0]?.message?.content;
    if(content!==undefined)card.append(el('pre',content));
    if(row.error)card.append(el('p',row.error,'inline-error'));
    card.append(jsonDetail('전송된 전체 messages',row.messages),jsonDetail('모델 응답 · 사용량 · 요청 연결',row));root.append(card);
  }
  const history=(after?.interaction?.model_history||[]).slice(before?.interaction?.model_history?.length||0);
  for(const item of history)root.append(jsonDetail('에이전트 Gateway 이력 · 파서 결과 · 복구',item));
  for(const id of ids)if(data.requests[id]?.path==='/v1/chat/completions')root.append(jsonDetail('시뮬레이터가 수신한 Gateway 요청과 응답',data.requests[id]));
  if(!calls.size&&!history.length)root.append(note('이 구간에는 수집된 모델 호출이 없습니다.'));
  root.append(jsonDetail('SDK 전송·오류·응답',group.events.filter(row=>row.kind.startsWith('sdk_'))));return root;
}
function detail(){
  const group=groups[selected],before=stateAt(group.before),after=stateAt(group.to),root=$('turn-detail');root.replaceChildren();
  const heading=el('div',null,'turn-heading');heading.append(el('h2',`턴 ${group.turn} · ${scopes[group.session]||'상태 미수집'}`));
  const controls=el('div',null,'controls'),indices=visible().map(row=>row.i),position=indices.indexOf(selected);
  for(const [text,offset] of [['이전',-1],['다음',1]]){const button=el('button',text);button.type='button';button.disabled=position+offset<0||position+offset>=indices.length;button.addEventListener('click',()=>select(indices[position+offset]));controls.append(button);}heading.append(controls);root.append(heading);
  root.append(el('p',`실제 내부 세션: ${group.session} · ${group.events.filter(row=>row.kind==='node_end').length}개 노드 처리`,'session-note'));
  const tabs=el('div',null,'tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','턴 상세 보기');
  const choices=[['flow','정보 흐름'],['objects','객체 탐색'],['dialogue','대화'],['note','Note 상태'],['state','상태 변화'],['diagnosis','진단 근거'],['models','모델 호출']];
  for(const [id,title] of choices){const button=el('button',title);button.type='button';button.id=`tab-${id}`;button.setAttribute('role','tab');button.setAttribute('aria-selected',tab===id?'true':'false');button.setAttribute('aria-controls','detail-panel');button.tabIndex=tab===id?0:-1;
    button.addEventListener('click',()=>{tab=id;detail();$(`tab-${id}`).focus();});
    button.addEventListener('keydown',event=>{let index=choices.findIndex(row=>row[0]===id);if(event.key==='ArrowRight')index=(index+1)%choices.length;else if(event.key==='ArrowLeft')index=(index+choices.length-1)%choices.length;else if(event.key==='Home')index=0;else if(event.key==='End')index=choices.length-1;else return;event.preventDefault();tab=choices[index][0];detail();$(`tab-${tab}`).focus();});tabs.append(button);}
  root.append(tabs);
  const body=tab==='flow'?flowPanel(group,before,after):tab==='objects'?objectPanel(group,before,after):tab==='note'?notePanel(group,before,after):tab==='state'?statePanel(group,before,after):tab==='diagnosis'?diagnosisPanel(before,after):tab==='models'?modelPanel(group,before,after):conversation(group,after);
  body.id='detail-panel';body.setAttribute('role','tabpanel');body.setAttribute('aria-labelledby',`tab-${tab}`);root.append(body);
  const nodes=el('div',null,'node-list');for(const row of group.events.filter(row=>row.kind==='node_end'||row.kind==='node_error'))nodes.append(el('span',row.node));root.append(nodes);
}
const summary=data.summary,result=data.result,finalState=stateAt(events.length-1);
const known=(...values)=>values.find(value=>value&&value!=='unknown');
const backend=known(result.backend,summary.backend,data.run.backend);
$('report-meta').textContent=`${known(result.case_id,summary.case_id,data.run.case)||'증례 미확인'} · ${backend||'모드 미확인'}${backend==='nova'&&data.run.maximum?` · 최대 ${data.run.maximum}회 요청`:''} · ${data.run_id}`;
$('trace-status').textContent={complete:'내부 상태 수집 완료',incomplete:'내부 상태 일부 수집',not_collected:'내부 상태 미수집'}[data.trace.status];
$('trace-status').classList.add(data.trace.status==='complete'?'good':'warn');
if(finalState?.interaction?.reason){const outcome=el('p',`진료 종료: ${finalState.interaction.termination} · ${finalState.interaction.reason}`,'inline-error');$('summary').before(outcome);}
for(const [title,value,warning] of [['로컬 실행 검사',result.status==='pass'?'통과':result.status==='fail'?'실패':'결과 없음',result.status!=='pass'],['최종 진단',data.record.diagnosis||finalState?.case?.diagnosis||'미제출',false],['사용한 턴',`${summary.turns??'—'} / 50`,false],['Gateway / 전체 모델',`${summary.doctor_calls??'—'} / ${summary.model_requests??'—'}`,false],['공식 채점','미실행 · not_scored',false]]){const box=el('div',null,'metric');box.append(el('small',title),el('strong',value,warning?'error-text':''));$('summary').append(box);}
const final=$('final-record');
final.append(kv([['진단',data.record.diagnosis||'제출 기록 없음'],['프로세스 종료',data.process.exit_code??data.process.status??'미수집'],['프로세스 경과 시간',data.process.seconds!==undefined?`${data.process.seconds}초`:'미수집'],['수신 확인',summary.receipt?.status||'없음'],['모드',summary.backend==='scripted'?'고정 응답 대역':summary.backend||data.run.backend||'미확인']]));
if(data.record.note)final.append(soapNote('시뮬레이터에 수신된 최종 SOAP',data.record));
else final.append(note('시뮬레이터에 수신된 최종 SOAP가 없습니다.'));
final.append(jsonDetail('실행 검사 · 누락된 증거',result),jsonDetail('최종 제출 영수증',summary.receipt||null));
const lastNote=el('button','마지막 Note 상태 보기');lastNote.type='button';lastNote.className='last-note';
lastNote.addEventListener('click',()=>{$('session-filter').value='';tab='note';select(groups.length-1);$('tab-note').focus();$('turn-detail').scrollIntoView({block:'start'});});
$('final-record').after(lastNote);
for(const scope of [...new Set(groups.map(group=>group.session))]){const option=el('option',scopes[scope]?`${scopes[scope]} · ${scope}`:'내부 상태 미수집');option.value=scope;$('session-filter').append(option);}
const settings=events.find(row=>row.kind==='settings');
if(settings?.education_enabled===false)$('final-record').after(el('p','교육 세션: 공개 설정에서 비활성화되어 발화와 예약 턴을 사용하지 않습니다.','session-note'));
$('session-filter').addEventListener('change',()=>{const choices=visible();if(!choices.some(row=>row.i===selected)&&choices.length)selected=choices[0].i;timeline();detail();});
const logs=$('all-logs');logs.append(jsonDetail('수집 상태와 경고',{trace:data.trace.status,warnings:data.warnings}),jsonDetail('실행기 로그 · 마지막 64 KiB',data.logs.runner),jsonDetail('에이전트 오류 · 마지막 64 KiB',data.logs.stderr),jsonDetail('에이전트 출력 · 마지막 64 KiB',data.logs.stdout));
