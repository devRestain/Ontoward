const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

// Exercise the actual viewer with a text-only DOM double; browser rendering is a separate check.
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.attributes={};this.handlers={};this._text='';this.value='';this.className='';this.classList={add:(name)=>{this.className+=' '+name;}};}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  set innerHTML(_){throw new Error('Viewer must render logs as text');}
  append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}}
  replaceChildren(...nodes){this.children=[];this._text='';this.append(...nodes);}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(name,listener){(this.handlers[name]||=[]).push(listener);}
  emit(name,event={}){for(const listener of this.handlers[name]||[])listener({preventDefault(){},...event});}
  click(){this.emit('click');}
  focus(){this.focused=true;}
  scrollIntoView(){}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(node=>node!==this);}
  before(node){this.insert(node,0);}
  after(node){this.insert(node,1);}
  insert(node,offset){const index=this.parent.children.indexOf(this);node.parent=this.parent;this.parent.children.splice(index+offset,0,node);}
  querySelector(selector){return walk(this).slice(1).find(node=>selector.startsWith('.')?node.className.split(' ').includes(selector.slice(1)):node.tagName===selector)||null;}
}
function walk(root){return [root,...root.children.flatMap(walk)];}
function load(data){
  const body=new Element('body');
  for(const id of ['report-data','report-meta','trace-status','summary','final-record','session-filter','turn-picker','timeline','turn-detail','all-logs']){const node=new Element('div');node.id=id;if(id==='report-data')node.textContent=JSON.stringify(data);body.append(node);}
  const document={getElementById:id=>walk(body).find(node=>node.id===id),createElement:tag=>new Element(tag)};
  const context=vm.createContext({document});
  vm.runInContext(fs.readFileSync(__dirname+'/ui/viewer.js','utf8')+'\n'+fs.readFileSync(__dirname+'/ui/flow.js','utf8'),context);
  return {body,context,get:id=>document.getElementById(id),text:()=>document.getElementById('detail-panel').textContent};
}
const fields={S:['cc','hpi','pmh','fh','sh','ros'],O:['exam','tests'],A:['evidence','differential'],P:['tests','treatment','disposition','follow_up','education']};
const empty=()=>Object.fromEntries(Object.entries(fields).map(([section,names])=>[section,Object.fromEntries(names.map(name=>[name,{}]))]));
const caseState=empty();
for(const [section,names] of Object.entries(fields))for(const name of names){
  const id=section+'.'+name;
  caseState[section][name][id]={id,scope:'ChiefComplaint',status:'done',acquisition:section==='O'?'EXAM':'SAY',source_refs:['source-1'],context_refs:[],
    value:{kind:'text',text:'Stored '+id,status:id==='S.hpi'?'uncertain':id==='S.ros'?'unknown':id==='O.exam'?'absent':'present',concept_ids:['symptom-1'],subject:'patient',time_context:'current'}};
}
caseState.S.hpi.unasked={id:'unasked',scope:'ChiefComplaint',status:'unasked',value:null,source_refs:[],context_refs:[]};
Object.assign(caseState,{diagnosis:'State diagnosis',diagnosis_kind:'symptom',diagnosis_evidence:['S.cc'],fixed_diagnosis:{name:'Fixed diagnosis'}});
const soap=Object.fromEntries(Object.entries(fields).map(([section,names])=>[section,Object.fromEntries(names.map(name=>[name,'Payload '+section+'.'+name]))]));
const initial={case:empty(),session:{current:'ChiefComplaint'},differential:{selected_id:null,hypotheses:[]},interaction:{history:[],model_history:[],submission_payload:null}};
const attack='</script><script>patient()</script>';
const interaction={...initial.interaction,submission_payload:{note:soap,diagnosis:'Payload diagnosis'},patient_reports:[{source_id:'source-1',text:'😀두통!',covered_spans:[[0,1]],uncovered_spans:[[1,3]]},{source_id:'source-1',text:attack,uncovered_spans:[[0,Array.from(attack).length]]}]};
const events=[{seq:1,kind:'initial',session:'ChiefComplaint',turn:0,state:initial},{seq:2,kind:'labels',labels:{'symptom-1':'두통 라벨'}},
  {seq:3,kind:'node_end',node:'build_soap',session:'ChiefComplaint',turn:1,patch:[{op:'replace',path:['case'],value:caseState},{op:'replace',path:['interaction'],value:interaction}]},{seq:4,kind:'end'}];
const data={run_id:'note-view',run:{},result:{},process:{},summary:{},record:{note:soap,diagnosis:'Submitted diagnosis'},transcript:{events:[]},models:[],requests:{},trace:{status:'complete',events},logs:{},warnings:[]};
const original=JSON.stringify(data),page=load(data);
assert.equal(page.get('tab-flow').attributes['aria-selected'],'true');
assert.match(page.text(),/객체 메서드 호출을 수집하지 않았습니다/);
page.get('tab-objects').click();
for(const name of ['CaseState','SessionContext','DifferentialState','QuestionPlan','InteractionState'])assert.match(page.text(),new RegExp(name));
assert.match(page.text(),/WorkflowState.case/);
page.get('tab-note').click();
assert.match(page.text(),/완료 0 \/ 전체 0건/);
assert.match(page.text(),/아직 생성되지 않았습니다/);
assert.doesNotMatch(page.text(),/Payload S.cc|Submitted diagnosis/);
walk(page.body).find(node=>node.className==='last-note').click();
for(const [section,names] of Object.entries(fields))for(const name of names){assert.ok(page.text().includes('Stored '+section+'.'+name));assert.ok(page.text().includes('Payload '+section+'.'+name));}
for(const value of ['완료 · done','미질문 · unasked','양성 · present','음성 · absent','불확실 · uncertain','미확인 · unknown','State diagnosis','Payload diagnosis','Fixed diagnosis','두통 라벨 · symptom-1','취득 경로 · acquisition','build_soap · seq 3'])assert.ok(page.text().includes(value),value);
assert.doesNotMatch(page.text(),/Submitted diagnosis/);
assert.ok(walk(page.get('detail-panel')).some(node=>node.tagName==='blockquote'&&node.textContent==='두통'));
assert.ok(walk(page.get('detail-panel')).some(node=>node.tagName==='blockquote'&&node.textContent===attack));
assert.equal(vm.runInContext('stateAt(0).case.S.cc["S.cc"]',page.context),undefined);
page.get('tab-note').emit('keydown',{key:'ArrowRight'});
assert.equal(page.get('tab-state').attributes['aria-selected'],'true');
page.get('tab-state').emit('keydown',{key:'ArrowLeft'});
assert.equal(page.get('tab-note').attributes['aria-selected'],'true');
assert.equal(page.get('detail-panel').attributes['aria-labelledby'],'tab-note');
const raw=walk(page.get('detail-panel')).find(node=>node.tagName==='details'&&node.children[0].textContent==='SOAP payload 원본');raw.open=true;raw.emit('toggle');
assert.match(raw.querySelector('pre').textContent,/Payload diagnosis/);
assert.equal(JSON.stringify(data),original);

const legacy=load({...data,trace:{status:'not_collected',events:[]}});legacy.get('tab-note').click();
assert.match(legacy.text(),/턴별 Note 내부 상태가 수집되지 않았습니다/);
assert.match(legacy.text(),/최종 수신된 SOAP · 선택 턴의 상태가 아님/);
assert.match(legacy.text(),/Submitted diagnosis/);
assert.doesNotMatch(legacy.text(),/완료 0/);

const partial=load({...data,record:{},trace:{status:'incomplete',events:[{...events[0],state:{...initial,case:{S:{cc:{}}}}}]}});partial.get('tab-note').click();
assert.match(partial.text(),/O.exam · 진찰 — 필드 미수집/);
assert.doesNotMatch(partial.text(),/최종 수신된 SOAP/);
console.log('PASS: Note field mapping, turn snapshots, clinical and completion states, source labels, Unicode spans, payload distinction, legacy and partial logs, keyboard tabs, text-only rendering');

const flowEvents=[
  {seq:1,kind:'initial',session:'ChiefComplaint',turn:0,state:initial},
  {seq:2,kind:'node_start',node:'process_input',operation:'InputInterpreter.process_input'},
  {seq:3,kind:'call_start',node:'process_input',call_id:1,parent_call_id:null,owner:'InputInterpreter',object_id:'consultation.interpreter',method:'process_input',inputs:{state:{type:'WorkflowState',state_reference:true}},object_state:initial},
  {seq:4,kind:'call_start',node:'process_input',call_id:2,parent_call_id:1,owner:'InputInterpreter',object_id:'consultation.interpreter',method:'_parse_text',inputs:{text:attack}},
  {seq:5,kind:'sdk_request',node:'process_input',parent_call_id:2,method:'POST',path:'/v1/chat/completions',request_id:'wire-1',body:{messages:[{content:'{"concept_ids":["symptom-1"]}'}]}},
  {seq:6,kind:'sdk_response',node:'process_input',request_id:'wire-1',response:{choices:[{message:{content:'{"facts":[]}'}}]}},
  {seq:7,kind:'call_end',node:'process_input',call_id:2,owner:'InputInterpreter',method:'_parse_text',output:{type:'ParseResult',data:{facts:[]}},writes:[]},
  {seq:8,kind:'call_end',node:'process_input',call_id:1,owner:'InputInterpreter',method:'process_input',output:null,writes:[{op:'add',path:['case','diagnosis'],value:'new diagnosis'}],object_patch:[{op:'add',path:['case','diagnosis'],value:'new diagnosis'}]},
  {seq:9,kind:'node_end',node:'process_input',session:'ChiefComplaint',turn:0,patch:[{op:'add',path:['case','diagnosis'],value:'new diagnosis'}]},
  {seq:10,kind:'end'}
];
const flowData={...data,record:{},trace:{status:'complete',events:flowEvents}},flowOriginal=JSON.stringify(flowData),flow=load(flowData);
assert.doesNotMatch(flow.text(),/객체 메서드 호출을 수집하지 않았습니다/);
const parseButton=walk(flow.get('detail-panel')).find(node=>node.className.includes('flow-call')&&node.children[0].textContent==='InputInterpreter._parse_text');
parseButton.click();
const inspector=flow.get('detail-panel').querySelector('.flow-inspector');
assert.match(inspector.textContent,/InputInterpreter.process_input → InputInterpreter._parse_text/);
assert.match(inspector.textContent,/ParseResult/);assert.match(inspector.textContent,/return/);
assert.ok(walk(inspector).some(node=>node.textContent===attack));
assert.equal(parseButton.attributes['aria-pressed'],'true');
const sdkButton=walk(flow.get('detail-panel')).find(node=>node.className.includes('sdk-call'));
sdkButton.click();assert.match(inspector.textContent,/request_id: wire-1/);assert.match(inspector.textContent,/request.body/);
flow.get('tab-objects').click();assert.match(flow.text(),/diagnosis/);
const change=walk(flow.get('detail-panel')).find(node=>node.className==='change-row add');change.open=true;change.emit('toggle');
assert.match(change.textContent,/new diagnosis/);assert.match(change.textContent,/관측 없음/);
const search=walk(flow.get('detail-panel')).find(node=>node.type==='search');search.value='missing-key';search.emit('input');assert.match(flow.text(),/검색어에 맞는 변경이 없습니다/);
search.value='diagnosis';search.emit('input');assert.match(flow.text(),/diagnosis/);
assert.equal(JSON.stringify(flowData),flowOriginal);
const interrupted=load({...data,record:{},trace:{status:'incomplete',events:flowEvents.slice(0,6)}});
const pending=walk(interrupted.get('detail-panel')).find(node=>node.className.includes('flow-call')&&node.children[0].textContent==='InputInterpreter._parse_text');pending.click();
assert.match(interrupted.text(),/반환값이 수집되지 않았습니다/);assert.match(interrupted.text(),/성공으로 해석하지 않습니다/);
const missingInitial=load({...data,record:{},trace:{status:'incomplete',events:flowEvents.slice(1,6)}});
assert.match(missingInitial.text(),/InputInterpreter.process_input/);
assert.match(missingInitial.text(),/실제 SDK 전송|POST \/v1\/chat\/completions/);
console.log('PASS: observed method sequence, parent linkage, typed return values, SDK payloads, object diffs, field search, partial calls and immutable source data');
const largeEvents=[flowEvents[0],flowEvents[1]];
for(let index=0;index<140000;index++)largeEvents.push({seq:index+3,kind:'call_end',call_id:index+1,output:null});
largeEvents.push({...flowEvents[8],seq:140003,patch:[]});
const large=load({...data,record:{},trace:{status:'incomplete',events:largeEvents}});
assert.match(large.text(),/InputInterpreter.process_input/);
console.log('PASS: large partial node trace without argument-spread overflow');
for(const path of process.argv.slice(2)){
  const saved=JSON.parse(fs.readFileSync(path,'utf8').match(/id="report-data">(.*?)<\/script>/s)[1]);
  const report=load(saved);walk(report.body).find(node=>node.className==='last-note').click();
  if(saved.trace.events.some(row=>row.kind==='initial')){
    const modern=saved.trace.events.some(row=>row.kind==='initial'&&row.state?.interview);
    if(!modern){
      for(const [section,names] of Object.entries(fields))for(const name of names)assert.ok(report.text().includes(section+'.'+name));
      assert.match(report.text(),/case.diagnosis/);
    }else assert.match(report.text(),/환자 사실/);
    report.get('tab-flow').click();
    const step=walk(report.get('detail-panel')).find(node=>node.className.split(' ').includes('flow-node-button'));
    if(step){step.click();assert.ok(report.get('detail-panel').querySelector('.flow-inspector').textContent.length>0);}
    report.get('tab-objects').click();
    for(const [key,type] of Object.entries(modern?{case:'CaseState',interview:'InterviewState',session:'SessionContext',turn:'TurnContext'}:{case:'CaseState',session:'SessionContext',differential:'DifferentialState',questions:'QuestionPlan',interaction:'InteractionState'})){
      const button=walk(report.get('detail-panel')).find(node=>node.className==='object-button'&&node.children[0].textContent===type);
      button.click();assert.ok(report.text().includes('WorkflowState.'+key));
    }
    report.get('tab-execution').click();assert.match(report.text(),/전체 실행 검증/);
    if(saved.inspection?.runtime){
      assert.ok(report.text().includes(saved.inspection.runtime.algorithm));
      const graph=walk(report.get('detail-panel')).find(node=>node.tagName==='details'&&(/^(런타임 그래프|순차 실행)/).test(node.children[0].textContent));
      graph.open=true;graph.emit('toggle');assert.match(graph.textContent,/process_initial_input/);
      const stage=walk(report.get('detail-panel')).find(node=>node.className==='pipeline-stage'&&!node.disabled);
      if(stage){stage.click();assert.equal(report.get('tab-flow').attributes['aria-selected'],'true');assert.match(report.text(),/관측된 객체 호출/);}
    }
    report.get('turn-picker').value='0';report.get('turn-picker').emit('change');assert.match(report.get('turn-detail').textContent,/턴/);
    const functionCall=saved.trace.events.find(row=>row.call_kind==='function');
    if(functionCall){
      vm.runInContext('jumpToEvent(events.find(row=>row.call_kind==="function"))',report.context);
      assert.match(report.text(),/관측된 Python 함수/);
      assert.ok(report.text().includes(functionCall.callable));
    }
  }
  console.log(`PASS: saved report ${saved.run_id} (${saved.trace.events.length} trace events)`);
}

const compact={case:{facts:{f1:{id:'f1',kind:'symptom',target:'Headache',status:'present',source_ref:'source-1'}},notes:{n1:{id:'n1',category:'previous_care',value:'No treatment',status:'absent'}},chief_fact_id:'f1',diagnosis:{kind:'symptom',name:'Headache',evidence_ids:['f1']},plan:[],revision:1},
  interview:{current:'ChiefComplaint',queue:[],answers:[],collection:{}},session:{turns_remaining:40,doctor_calls:3,input_tokens:60,output_tokens:30,termination:null},turn:null};
const compactData={...data,trace:{status:'complete',events:[{seq:1,kind:'initial',session:'ChiefComplaint',turn:10,state:compact}]}};
const compactPage=load(compactData);
compactPage.get('tab-objects').click();
for(const name of ['CaseState','InterviewState','SessionContext','TurnContext'])assert.match(compactPage.text(),new RegExp(name));
for(const name of ['DifferentialState','QuestionPlan','InteractionState'])assert.doesNotMatch(compactPage.text(),new RegExp(name));
compactPage.get('tab-note').click();assert.match(compactPage.text(),/Headache/);assert.match(compactPage.text(),/previous_care/);
compactPage.get('tab-state').click();assert.match(compactPage.text(),/D44/);
compactPage.get('tab-diagnosis').click();assert.match(compactPage.text(),/reasoner/);
assert.equal(JSON.stringify(compactData.trace.events[0].state),JSON.stringify(compact));
console.log('PASS: D44 resident owners, disposable turn, typed facts and notes, final diagnosis and legacy trace separation');

const brainState=JSON.parse(JSON.stringify(compact));
delete brainState.case.diagnosis;
brainState.case.assessment={differential:[{kind:'disease',name:'Brain primary',supports:[],against:[],unresolved:[]}],based_on_case_revision:1,based_on_chief_fact_id:'f1',frozen:true,limitations:[]};
const brainPage=load({...data,trace:{status:'complete',events:[{seq:1,kind:'initial',session:'DifferentialDiagnosis',turn:10,state:brainState}]}});
brainPage.get('tab-diagnosis').click();assert.match(brainPage.text(),/CaseState.assessment/);assert.match(brainPage.text(),/Brain primary/);
brainPage.get('tab-note').click();assert.match(brainPage.text(),/Brain primary/);
console.log('PASS: D46 current assessment ranking and frozen evidence display');

const unified=JSON.parse(JSON.stringify(brainState));
delete unified.case.notes;
unified.case.facts.f1={id:'f1',graph_binding:{kind:'symptom',target:'Headache',eligible:true},value:'Headache after exercise',status:'present',source_ref:'source-1'};
unified.case.facts.age={id:'age',category:'patient_context',context_key:'age',value:'6 years',measurement:{kind:'quantity',value:6,unit:'year'},status:'present',source_ref:'source-1'};
const unifiedPage=load({...data,trace:{status:'complete',events:[{seq:1,kind:'initial',session:'DifferentialDiagnosis',turn:10,state:unified}]}});
unifiedPage.get('tab-note').click();
assert.match(unifiedPage.text(),/통합 환자 사실/);assert.match(unifiedPage.text(),/Headache/);
assert.match(unifiedPage.text(),/patient_context/);assert.doesNotMatch(unifiedPage.text(),/과거 별도 note/);
assert.equal(JSON.stringify(unified.case.facts.f1.graph_binding),JSON.stringify({kind:'symptom',target:'Headache',eligible:true}));
console.log('PASS: D47 unified facts, graph bindings and demographic context without a duplicate note store');

const d50State=JSON.parse(JSON.stringify(unified));
delete d50State.case.facts.f1.graph_binding.eligible;
d50State.case.assessment.differential[0].supports=[{fact_ids:['f1'],graph_ref:{kind:'symptom',id:'Headache'}}];
const d50Events = [
  {seq:1,kind:'start',format_version:6},
  {seq:2,kind:'settings',execution:{kind:'sequential',operations:['enter_session']},
    pipeline:{contract:'D50',landmarks:[{id:'assessment',owners:['DifferentialDiagnosisSession'],methods:['decide']}] }},
  {seq:3,kind:'initial',state:d50State,session:'DifferentialDiagnosis',turn:10},
  {seq:4,kind:'node_start',node:'enter_session',session:'DifferentialDiagnosis',turn:10},
  {seq:5,kind:'call_start',node:'enter_session',call_id:1,parent_call_id:null,owner:'DifferentialDiagnosisSession',
    method:'decide',callable:'workflow.sessions.differential_diagnosis.DifferentialDiagnosisSession.decide',
    definition:{path:'workflow/sessions/differential_diagnosis.py',line:40},object_id:'consultation.sessions.DifferentialDiagnosis',
    inputs:{state:{type:'WorkflowState',state_reference:true}},object_state:d50State,owner_state:{last_input:null,error:null}},
  {seq:6,kind:'call_end',node:'enter_session',call_id:1,owner:'DifferentialDiagnosisSession',method:'decide',output:null,
    writes:[],owner_state:{last_input:{type:'tuple',data:[1,'f1','answer-10']},error:null}},
  {seq:7,kind:'node_end',node:'enter_session',session:'DifferentialDiagnosis',turn:10,patch:[]},
  {seq:8,kind:'end'}
];
const d50Data={...data,record:{},trace:{status:'complete',events:d50Events}},d50Original=JSON.stringify(d50Data),d50=load(d50Data);
assert.match(d50.text(),/순차 작업/);
assert.doesNotMatch(d50.text(),/deep copy|검증된 dict|그래프 노드/);
const landmark=d50.get('detail-panel').querySelector('.landmark');landmark.open=true;landmark.emit('toggle');
landmark.querySelector('button').click();
const d50Inspector=d50.get('detail-panel').querySelector('.flow-inspector');
assert.match(d50Inspector.textContent,/differential_diagnosis.py:40/);
assert.match(d50Inspector.textContent,/실행 객체가 소유한 값/);
assert.match(d50Inspector.textContent,/last_input/);
d50.get('tab-objects').click();
const ownerStates=d50.get('detail-panel').querySelector('.collaborator-states');ownerStates.open=true;ownerStates.emit('toggle');
assert.match(ownerStates.textContent,/consultation.sessions.DifferentialDiagnosis/);
assert.match(ownerStates.textContent,/호출 직전/);assert.match(ownerStates.textContent,/호출 직후/);
ownerStates.querySelector('button').click();
assert.equal(d50.get('tab-flow').attributes['aria-selected'],'true');
assert.match(d50.text(),/last_input/);
d50.get('tab-diagnosis').click();assert.match(d50.text(),/f1 · Headache/);assert.doesNotMatch(d50.text(),/undefined/);
assert.equal(JSON.stringify(d50Data),d50Original);
const d50Partial=load({...d50Data,trace:{status:'incomplete',events:d50Events.slice(0,5)}});
const partialCall=walk(d50Partial.get('detail-panel')).find(node=>node.className.includes('flow-call'));
partialCall.click();assert.match(d50Partial.text(),/종료 미수집|반환값이 수집되지 않았습니다/);
assert.doesNotMatch(d50Partial.text(),/answer-10/);
console.log('PASS: D50 sequential flow, trace landmarks, callable source locations, collaborator field snapshots, partial coverage and immutable records');

const d59Data=structuredClone(d50Data);
d59Data.trace.events[0].format_version=7;
d59Data.trace.events[1].pipeline={version:2,contract:'D59',landmarks:[
  {id:'guidelines',owners:['GuidelineEvidence'],methods:['pack_passages']},
  {id:'sync',owners:['DoctorBrain'],methods:['complete']}]};
Object.assign(d59Data.trace.events[4],{owner:'GuidelineEvidence',method:'pack_passages',
  callable:'knowledge.guideline_passages.pack_passages',definition:{path:'knowledge/guideline_passages.py',line:126}});
Object.assign(d59Data.trace.events[5],{owner:'GuidelineEvidence',method:'pack_passages'});
d59Data.inspection={status:'pass',runtime:{algorithm:'d50.9'},state_layout:'D50',pipeline:{contract:'D59'},
  checks:[{id:'runtime_sources',status:'pass',detail:{}},{id:'runtime_stability',status:'pass',detail:{}}],
  checkpoints:[],transitions:[],declared_objects:[],observed_methods:{},
  model_outcomes:[{role:'education_doctor',error:'LOCAL_EDUCATION_BUDGET_SYNC_REQUIRED',request_id:null}],
  coverage:[{object_id:'workflow.education',missing:[]}],limits:{scope:'Recorded boundaries'}};
const d59Original=JSON.stringify(d59Data),d59=load(d59Data);
assert.match(d59.text(),/매핑 원문·발췌·인용 문맥/);
assert.match(d59.text(),/모델 차단·예산 동기화/);
const packet=d59.get('detail-panel').querySelector('.landmark');packet.open=true;packet.emit('toggle');packet.querySelector('button').click();
assert.match(d59.text(),/knowledge\/guideline_passages.py:126/);
d59.get('tab-execution').click();
assert.match(d59.text(),/d50.9/);assert.match(d59.text(),/D59/);
assert.match(d59.text(),/지식 코드·진입점 소스 해시/);
const outcomes=walk(d59.get('detail-panel')).find(node=>node.tagName==='details'&&node.children[0].textContent==='모델 반환 · 로컬 차단 · 전후 예산');
outcomes.open=true;outcomes.emit('toggle');assert.match(outcomes.textContent,/LOCAL_EDUCATION_BUDGET_SYNC_REQUIRED/);
assert.equal(JSON.stringify(d59Data),d59Original);
console.log('PASS: D59 source packet navigation, guard outcomes, source checks and immutable historical reports');
const preservedData=JSON.parse(JSON.stringify(data));
preservedData.record={};preservedData.summary={status:'active',receipt:null};
preservedData.inspection={outcome:{education_status:'failed',education_reason:'provider failure',plan_count:0,
  diagnosis_announcement_delivered:1,fact_count:45,unbound_fact_count:23,payload_generated:true,
  payload:{note:soap,diagnosis:'Preserved working diagnosis'},transmitted:false,received:false,submission_confirmed:false,
  p_coverage:{tests:false,treatment:false,disposition:false,follow_up:false,education:false},plan_delivery:[]}};
const preservedOriginal=JSON.stringify(preservedData),preservedPage=load(preservedData);
assert.match(preservedPage.get('final-record').textContent,/생성·보존된 SOAP · 제출 수신 미확인/);
assert.match(preservedPage.get('final-record').textContent,/Education 준비/);
assert.match(preservedPage.get('final-record').textContent,/45 \/ 23/);
assert.match(preservedPage.get('final-record').textContent,/평가하지 않음 · not_evaluated/);
assert.match(preservedPage.get('final-record').textContent,/미확인 \/ 미확인 \/ 미확인/);
assert.equal(JSON.stringify(preservedData),preservedOriginal);
console.log('PASS: preserved unconfirmed SOAP, distinct Education metrics and immutable legacy input');
