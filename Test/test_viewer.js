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
  remove(){this.parent.children=this.parent.children.filter(node=>node!==this);}
  before(node){this.insert(node,0);}
  after(node){this.insert(node,1);}
  insert(node,offset){const index=this.parent.children.indexOf(this);node.parent=this.parent;this.parent.children.splice(index+offset,0,node);}
  querySelector(selector){return walk(this).slice(1).find(node=>selector.startsWith('.')?node.className.split(' ').includes(selector.slice(1)):node.tagName===selector)||null;}
}
function walk(root){return [root,...root.children.flatMap(walk)];}
function load(data){
  const body=new Element('body');
  for(const id of ['report-data','report-meta','trace-status','summary','final-record','session-filter','timeline','turn-detail','all-logs']){const node=new Element('div');node.id=id;if(id==='report-data')node.textContent=JSON.stringify(data);body.append(node);}
  const document={getElementById:id=>walk(body).find(node=>node.id===id),createElement:tag=>new Element(tag)};
  const context=vm.createContext({document});
  vm.runInContext(fs.readFileSync(__dirname+'/ui/viewer.js','utf8'),context);
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
for(const path of process.argv.slice(2)){
  const saved=JSON.parse(fs.readFileSync(path,'utf8').match(/id="report-data">(.*?)<\/script>/s)[1]);
  const report=load(saved);walk(report.body).find(node=>node.className==='last-note').click();
  if(saved.trace.events.some(row=>row.kind==='initial')){
    for(const [section,names] of Object.entries(fields))for(const name of names)assert.ok(report.text().includes(section+'.'+name));
    assert.match(report.text(),/case.diagnosis/);
  }
  console.log(`PASS: saved report ${saved.run_id} (${saved.trace.events.length} trace events)`);
}
