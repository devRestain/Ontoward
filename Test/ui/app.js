const $ = id => document.getElementById(id);
const activeStates = new Set(['starting', 'running']);
const names = {starting:'시작 준비 중',running:'실행 중',completed:'실행 완료',failed:'실행 실패',timeout:'시간 초과',interrupted:'실행 중단',saved:'저장된 실행'};
let runs = [], selected = location.hash.slice(1), busy = true, online = false, posting = false, polling = false, loaded = '', pendingRun = '';

function modeHelp() {
  const nova = $('backend').value === 'nova';
  $('maximum').disabled = busy || !nova;
  $('mode-help').textContent = nova
    ? `루트 .env의 키로 개발 크레딧을 사용합니다. 환자·진찰·Gateway 호출을 합쳐 최대 ${$('maximum').value || 200}회 요청합니다.`
    : '외부 호출 없이 고정 응답으로 진행합니다. 대화의 의미 해석이나 임상 정확성을 검증하는 모드는 아닙니다.';
  $('start').textContent = nova ? 'NOVA 테스트 실행' : '오프라인 테스트 실행';
}
function controls() {
  $('start').disabled = busy || posting || !online;
  $('case').disabled = $('backend').disabled = busy || posting;
  modeHelp();
}
function status(text, detail, warn=false) {
  $('run-status').replaceChildren();
  const badge = document.createElement('span'); badge.className = `badge${warn?' warn':''}`; badge.textContent = text;
  const description = document.createElement('strong'); description.textContent = detail;
  $('run-status').append(badge, description);
}
function showResult() {
  const run = runs.find(row => row.id === selected);
  const url = run?.report_url;
  $('report').hidden = $('standalone').hidden = !url;
  $('empty').hidden = !!url;
  if (url) {
    if (loaded !== `${run.id}:${run.state}`) {
      $('report').src = url;
      loaded = `${run.id}:${run.state}`;
    }
    $('standalone').href = url;
  } else {
    $('empty').textContent = run && activeStates.has(run.state)
      ? '테스트가 진행 중입니다. 완료되면 결과를 표시합니다. 이 페이지를 새로고침해도 실행은 계속됩니다.'
      : '저장된 실행을 선택하거나 새 테스트를 시작하세요. 정보 흐름에서 호출 순서와 입출력을, 객체 탐색에서 턴별 데이터 변화를 볼 수 있습니다.';
  }
}
async function poll() {
  if (polling) return;
  polling = true;
  try {
    const response = await fetch('/api/runs');
    if (!response.ok) throw new Error('실행 상태를 읽지 못했습니다.');
    const data = await response.json();
    runs = data.runs; online = data.worker_online;
    if (runs.some(row => row.id === pendingRun)) pendingRun='';
    busy = data.busy || !!pendingRun;
    const active = runs.find(row => activeStates.has(row.state));
    if (!selected || (!pendingRun && !runs.some(row => row.id === selected))) selected = active?.id || runs[0]?.id || '';
    const history = $('history'); history.replaceChildren();
    if (!runs.length) { const option = document.createElement('option'); option.textContent='실행 기록 없음'; option.value=''; history.append(option); }
    for (const run of runs) {
      const option = document.createElement('option'); option.value=run.id;
      option.textContent=`${run.case} · ${run.backend} · ${new Date(run.created*1000).toLocaleString('ko-KR')} · ${names[run.state] || run.state}`;
      history.append(option);
    }
    history.value=selected;
    if (!online) status('실행기 연결 끊김', '시작한 터미널을 확인하거나 sh Test/web.sh로 사이트를 시작하세요.', true);
    else if (active) status(names[active.state], `${active.case} · ${active.backend} · ${Math.floor(active.seconds/60)}분 ${active.seconds%60}초 경과`);
    else if (busy) status('다른 실행 진행 중', '기존 웹 또는 CLI 테스트가 끝나면 새로 실행할 수 있습니다.');
    else {
      const current = runs.find(row => row.id === selected);
      status(current ? names[current.state] || current.state : '실행 준비됨', current ? `${current.case} · ${current.backend}${current.result==='pass'?' · 로컬 검사 통과':current.result==='fail'?' · 로컬 검사 실패':''}` : '한 번에 한 증례를 실행합니다.', current && ['failed','timeout','interrupted'].includes(current.state));
    }
    $('progress').classList.toggle('running', !!active);
    controls(); showResult();
  } catch (error) {
    online=false; controls(); status('연결 오류', error.message, true);
  } finally { polling=false; }
}
$('launch').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || posting || !online || !$('launch').reportValidity()) return;
  posting=true; controls();
  try {
    const response=await fetch('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case:$('case').value,backend:$('backend').value,maximum:Number($('maximum').value)})});
    const data=await response.json();
    if (!response.ok) throw new Error(data.message || data.error);
    selected=data.id; pendingRun=data.id; location.hash=selected; loaded='';
    await poll();
  } catch(error) { status('실행 요청 실패',error.message,true); }
  finally { posting=false; controls(); }
});
$('history').addEventListener('change',()=>{ selected=$('history').value; location.hash=selected; showResult(); });
$('backend').addEventListener('change',modeHelp);
$('maximum').addEventListener('input',modeHelp);
poll(); setInterval(poll,2000);
