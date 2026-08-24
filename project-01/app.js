const $=id=>document.getElementById(id);const API=window.location.origin;let pending=null;let activityCount=0;
function escapeText(v){return String(v).replace(/[<>&]/g,m=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[m]));}
function add(role,text){const d=document.createElement('div');d.className='msg '+role;d.innerHTML=`<b>${role==='user'?'USER':'ASTRA'}</b><span>${escapeText(text)}</span>`;$('log').appendChild(d);$('log').scrollTop=$('log').scrollHeight;const side=document.createElement('p');side.innerHTML=`&gt; ${role==='user'?'USER':'A.S.T.R.A.'} &gt; <span class="cyan">${escapeText(text).slice(0,180)}</span>`;$('sideLog').appendChild(side);$('sideLog').scrollTop=$('sideLog').scrollHeight;}
function activity(text){activityCount++;const d=document.createElement('div');const t=new Date().toLocaleTimeString('en-GB');d.innerHTML=`${t} <b>» ${escapeText(text)}</b>`;$('activityLog').prepend(d);while($('activityLog').children.length>6)$('activityLog').lastElementChild.remove();$('stepGauge').textContent=activityCount;}
async function run(cmd,confirmed=false){if(!cmd.trim())return;add('user',cmd);activity('RESPONDING');$('send').disabled=true;try{const endpoint='/api/command';const body={command:cmd,confirmed};const r=await fetch(API+endpoint,{method:'POST',headers:{'Content-Type':'application/json','Cache-Control':'no-cache'},body:JSON.stringify(body)});const x=await r.json();if(!r.ok)throw new Error(x.message||`HTTP ${r.status}`);add('astra',x.message||'Done.');activity(x.needs_confirmation?'CONFIRMATION REQUIRED':'COMMAND COMPLETE');if(x.needs_confirmation){pending={cmd};$('confirmText').textContent=x.message;$('confirm').classList.remove('hidden');}if('speechSynthesis'in window&&x.message){speechSynthesis.cancel();speechSynthesis.speak(new SpeechSynthesisUtterance(x.message));}}catch(e){add('astra',e.message||'Backend error.');activity('ERROR');}finally{$('send').disabled=false;}}
$('send').onclick=()=>{const v=$('cmd').value;$('cmd').value='';run(v)};$('cmd').addEventListener('keydown',e=>{if(e.key==='Enter'){const v=$('cmd').value;$('cmd').value='';run(v)}});document.querySelectorAll('.quick button').forEach(b=>b.onclick=()=>run(b.dataset.cmd));$('yes').onclick=()=>{if(pending){const x=pending;pending=null;$('confirm').classList.add('hidden');run(x.cmd,true)}};$('no').onclick=()=>{pending=null;$('confirm').classList.add('hidden');add('astra','Cancelled.');activity('CANCELLED')};
const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;if(SpeechRecognition){const rec=new SpeechRecognition();rec.lang='en-US';rec.interimResults=false;rec.continuous=false;rec.onstart=()=>{$('mic').textContent='🔴';$('mic').classList.add('listening');activity('LISTENING')};rec.onend=()=>{$('mic').textContent='🎙';$('mic').classList.remove('listening')};rec.onerror=()=>activity('MIC ERROR');rec.onresult=e=>{const t=e.results[0][0].transcript;$('cmd').value=t;run(t)}}else{$('mic').title='Speech recognition is not supported in this browser.';$('micDot').style.background='#d26b6b'}
function clock(){const d=new Date();$('clock').innerHTML=d.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})+`<em>${d.toLocaleTimeString('en-GB',{second:'2-digit'})}</em>`;$('date').textContent=d.toLocaleDateString('en-US',{weekday:'short',month:'short',day:'2-digit'}).toUpperCase()}setInterval(clock,1000);clock();
async function status(){try{const s=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());$('cpuGauge').textContent=s.cpu+'%';$('memGauge').textContent=s.memory+'%';$('memText').textContent=s.memory+'%';$('apiDot').style.background=s.backend==='CONNECTED'?'#19d9c0':'#d26b6b';$('status').textContent=s.backend==='CONNECTED'?'SYSTEM ONLINE':'BACKEND OFFLINE';const b=await fetch('/api/browser-runtime',{cache:'no-store'}).then(r=>r.json());$('runtime').textContent=b.connected?`Browser Runtime: CONNECTED (${b.pages} tabs)`:'Browser Runtime: OFFLINE';}catch(e){$('status').textContent='BACKEND OFFLINE';$('apiDot').style.background='#d26b6b'}}status();setInterval(status,3000);

// Lightweight HUD motion: keeps the interface alive without affecting commands.
(function hudMotion(){
  const radar=document.querySelector('.radar');
  const core=document.querySelector('.core');
  if(radar && core){
    let targetX=0,targetY=0,x=0,y=0;
    window.addEventListener('mousemove',e=>{
      targetX=(e.clientX/window.innerWidth-.5)*5;
      targetY=(e.clientY/window.innerHeight-.5)*4;
    },{passive:true});
    const tick=()=>{
      x+=(targetX-x)*.035; y+=(targetY-y)*.035;
      radar.style.transform=`translate3d(${x}px,${y}px,0)`;
      requestAnimationFrame(tick);
    }; tick();
  }
  setInterval(()=>{
    const online=$('status');
    if(online && online.textContent==='SYSTEM ONLINE'){
      const phrases=['LISTENING','MONITORING','READY','SYSTEM ONLINE'];
      const p=phrases[Math.floor(Math.random()*phrases.length)];
      activity(p);
    }
  },5200);
})();

$('settingsBtn').onclick=async()=>{$('settings').classList.remove('hidden');try{const s=await fetch('/api/settings').then(r=>r.json());$('apiBase').value=s.api_base||'https://api.groq.com/openai/v1';$('model').value=s.model||'qwen/qwen3.6-27b';$('maxSteps').value=s.max_steps||20;}catch(e){}};$('closeSettings').onclick=()=>$('settings').classList.add('hidden');$('navSettings').onclick=()=>$('settingsBtn').click();
$('saveSettings').onclick=async()=>{const body={provider:'groq',api_base:$('apiBase').value||'https://api.groq.com/openai/v1',model:$('model').value||'qwen/qwen3.6-27b',api_key:$('apiKey').value,max_steps:Number($('maxSteps').value||20)};const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});add('astra',(await r.json()).message)};
$('testGroq').onclick=async()=>{const body={api_base:$('apiBase').value||'https://api.groq.com/openai/v1',model:$('model').value||'qwen/qwen3.6-27b',api_key:$('apiKey').value};const r=await fetch('/api/groq-test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const x=await r.json();add('astra',x.message||'Groq test failed.');if(x.ok)add('astra','Model '+(x.model||body.model)+' is reachable.');};
