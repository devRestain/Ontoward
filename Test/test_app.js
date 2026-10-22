const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// Run the actual controller with HTTP and DOM doubles; this does not measure layout.
class Element {
  constructor() { this.children=[];this.attributes={};this.handlers={};this.value='';this._text='';this.replacements=0;this.srcWrites=0; }
  set textContent(value) { this._text=String(value);this.children=[]; }
  get textContent() { return this._text+this.children.map(node=>node.textContent).join(''); }
  append(...nodes) { for (const node of nodes) node.parent=this; this.children.push(...nodes); }
  remove() { this.parent.children=this.parent.children.filter(node=>node!==this); }
  replaceChildren(...nodes) { this.children=nodes;this._text='';this.replacements++; }
  setAttribute(key,value) { this.attributes[key]=value; }
  getAttribute(key) { return this.attributes[key]; }
  addEventListener(name,listener) { (this.handlers[name]||=[]).push(listener); }
  async emit(name,event={}) { for(const listener of this.handlers[name]||[])await listener({preventDefault(){},...event}); }
  reportValidity() { return true; }
  set src(value) { this._src=value;this.srcWrites++; }
  get src() { return this._src; }
}

async function run() {
  const elements=Object.fromEntries(['toggle-controls','control-panel','results','case','backend','maximum','start','mode-help','run-status','active-runs','report','standalone','empty','history','selected-run','result-title','progress','launch-settings','launch'].map(id=>[id,new Element()]));
  elements.case.value='C10';elements.backend.value='nova';elements.maximum.value='200';
  const classes=new Set(),listeners={},requests=[];
  const media={matches:true,addEventListener:(name,listener)=>{listeners.media=listener;}};
  const document={body:{classList:{toggle:(name,on)=>on?classes.add(name):classes.delete(name)}},getElementById:id=>elements[id],createElement:()=>new Element()};
  elements.progress.classList={toggle(){}};
  let server={runs:[{id:'saved-run',case:'C10',backend:'scripted',created:10,state:'completed',report_url:'/runs/saved-run/report.html',result:'pass'}],busy:false,worker_online:true};
  const context=vm.createContext({document,location:{hash:'#saved-run'},window:{matchMedia:()=>media,addEventListener:(name,listener)=>{listeners[name]=listener;}},setInterval(){},fetch:async(path,options)=>{
    requests.push({path,options});
    if(options?.method==='POST'){
      if(JSON.parse(options.body).case==='all'){
        const batch=['C01','C03','C10'].map(id=>({id:'batch-'+id,case:id,backend:'nova',created:30,state:'starting',seconds:0}));
        server={...server,busy:true,runs:[...batch,...server.runs]};
        return {ok:true,json:async()=>({runs:batch})};
      }
      server={...server,busy:true,runs:[{id:'new-run',case:'C10',backend:'nova',created:20,state:'starting'},...server.runs]};
      return {ok:true,json:async()=>({id:'new-run'})};
    }
    return {ok:true,json:async()=>structuredClone(server)};
  }});
  vm.runInContext(fs.readFileSync(__dirname+'/ui/app.js','utf8'),context);
  await new Promise(setImmediate);
  assert.equal(elements['control-panel'].hidden,true);
  assert.equal(elements.report.src,'/runs/saved-run/report.html');
  assert.equal(requests.filter(r=>r.options?.method==='POST').length,0);
  await elements['toggle-controls'].emit('click');
  assert.equal(elements['toggle-controls'].getAttribute('aria-expanded'),'true');
  assert.equal(elements.results.inert,true);
  await elements['toggle-controls'].emit('click');
  assert.equal(elements.results.inert,false);
  const versions=elements.history.replacements;
  await vm.runInContext('poll()',context);
  assert.equal(elements.history.replacements,versions,'unchanged polling must retain the history control');
  assert.equal(elements.report.srcWrites,1,'unchanged polling must retain the report and its scroll');
  server={...server,busy:true,runs:[{id:'other-run',case:'C01',backend:'nova',created:20,state:'running',seconds:12},...server.runs]};
  await vm.runInContext('poll()',context);
  assert.equal(elements.report.srcWrites,1,'an active run must not replace the saved report under review');
  assert.equal(elements.start.disabled,true);
  await elements.launch.emit('submit');
  assert.equal(requests.filter(r=>r.options?.method==='POST').length,0);
  server={...server,busy:false,runs:server.runs.slice(1)};
  await vm.runInContext('poll()',context);
  await elements.launch.emit('submit');
  assert.equal(requests.filter(r=>r.options?.method==='POST').length,1);
  await elements.launch.emit('submit');
  assert.equal(requests.filter(r=>r.options?.method==='POST').length,1,'no queue or automatic double submission');
  assert.equal(elements.report.hidden,true);
  elements.history.value='saved-run';await elements.history.emit('change');
  assert.equal(elements.report.hidden,false);
  server.runs.find(run=>run.id==='saved-run').fixture_kind='protocol_fixture';
  await vm.runInContext('poll()',context);
  assert.match(elements['result-title'].textContent,/합성 프로토콜/);
  media.matches=false;listeners.media();
  assert.equal(elements['control-panel'].hidden,false);
  assert.equal(elements.results.inert,false);
  server={...server,busy:false,runs:server.runs.filter(run=>run.state==='completed')};
  await vm.runInContext('poll()',context);
  elements.backend.value='openai_api';await elements.backend.emit('change');
  assert.match(elements.start.textContent,/OpenAI API/);
  assert.match(elements['mode-help'].textContent,/OPENAI_API_KEY/);
  assert.equal(elements.maximum.disabled,false);
  elements.case.value='all';await elements.case.emit('change');
  assert.match(elements.start.textContent,/3개 시나리오 동시 실행/);
  assert.match(elements['mode-help'].textContent,/전체 최대 600회/);
  await elements.launch.emit('submit');
  assert.equal(JSON.parse(requests.filter(r=>r.options?.method==='POST').at(-1).options.body).case,'all');
  assert.equal(JSON.parse(requests.filter(r=>r.options?.method==='POST').at(-1).options.body).backend,'openai_api');
  assert.equal(elements['active-runs'].children.length,3);
  assert.match(elements['run-status'].textContent,/3개 시나리오/);
  const activeButton=elements['active-runs'].children[1];
  await activeButton.emit('click');
  assert.match(elements['result-title'].textContent,/C03/);
  await vm.runInContext('poll()',context);
  assert.equal(elements['active-runs'].children[1],activeButton,'polling must retain active button focus');
  server.runs.find(run=>run.id==='batch-C01').state='failed';
  await vm.runInContext('poll()',context);
  assert.equal(elements['active-runs'].children.length,2);
  assert.equal(elements.start.disabled,true,'one finished scenario must not allow another batch');
  assert.match(elements['result-title'].textContent,/C03/);
  console.log('PASS: stable workspace, explicit single and three-scenario launch, per-run selection, request ceilings, independent failure and duplicate prevention');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
