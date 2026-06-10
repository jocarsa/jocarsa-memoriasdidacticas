const $=id=>document.getElementById(id);
const E=['I','II','III','F','O','E'];
let subjects=[],currentSubjectId='',currentUser=null,dirty=false,statsChart=null,timer=null;

async function api(action,params={},options={}){
  const u=new URL('api.php',location.href);
  u.searchParams.set('action',action);
  Object.entries(params).forEach(([k,v])=>u.searchParams.set(k,v));
  const o={headers:{Accept:'application/json'}};
  if(options.method)o.method=options.method;
  if(options.body){
    o.headers['Content-Type']='application/json';
    o.body=JSON.stringify(options.body);
  }
  const r=await fetch(u,o);
  const d=await r.json();
  if(!r.ok||!d.ok)throw new Error(d.error||`HTTP ${r.status}`);
  return d;
}

const esc=v=>String(v??'')
  .replaceAll('&','&amp;')
  .replaceAll('<','&lt;')
  .replaceAll('>','&gt;')
  .replaceAll('"','&quot;')
  .replaceAll("'",'&#039;');

function toast(type,title,text){
  const s=$('toastStack'),t=document.createElement('article');
  t.className=`ju-toast is-${type} chaflan`;
  t.innerHTML=`<div class="ju-toast-icon chaflan">${type==='success'?'✓':type==='danger'?'×':'i'}</div><div><p class="ju-toast-title">${esc(title)}</p><p class="ju-toast-text">${esc(text)}</p></div><button class="ju-toast-close">×</button>`;
  t.querySelector('button').onclick=()=>t.remove();
  s.appendChild(t);
  setTimeout(()=>t.remove(),4500);
}

function fmt(v){
  if(v===null||v===undefined||v==='')return '—';
  const n=Number(v);
  return Number.isNaN(n)?String(v):(Number.isInteger(n)?String(n):n.toFixed(2).replace(/0+$/,'').replace(/\.$/,''));
}

function pct(v){
  const n=Number(v||0);
  return `${Number.isInteger(n)?n:n.toFixed(2).replace(/0+$/,'').replace(/\.$/,'')}%`;
}

function gclass(v){
  if(v===null||v===undefined||v==='')return'grade empty';
  const n=Number(v);
  return Number.isNaN(n)?'grade':(n>=5?'grade pass':'grade fail');
}

function status(t,c=''){
  $('saveStatus').textContent=t;
  $('saveStatus').className=`ju-pill ${c}`.trim();
}

async function checkAuth(){
  const d=await api('auth_status');
  if(d.authenticated){
    currentUser=d.user;
    showApp();
    await loadSubjects();
    if(subjects.length)await selectSubject(subjects[0].id);
  }else showLogin();
}

function showLogin(){
  $('loginScreen').hidden=false;
  $('mainApp').hidden=true;
}

function showApp(){
  $('loginScreen').hidden=true;
  $('mainApp').hidden=false;
  $('currentUserLabel').textContent=`${currentUser.display_name||currentUser.username} · ${currentUser.role}`;
  document.querySelectorAll('[data-admin-only]').forEach(x=>x.hidden=currentUser.role!=='admin');
  $('usersButton').hidden=currentUser.role!=='admin';
}

$('loginForm').onsubmit=async e=>{
  e.preventDefault();
  $('loginError').textContent='';
  try{
    const f=new FormData(e.target),d=await api('login',{},{
      method:'POST',
      body:{username:f.get('username'),password:f.get('password')}
    });
    currentUser=d.user;
    showApp();
    await loadSubjects();
    if(subjects.length)await selectSubject(subjects[0].id);
  }catch(err){
    $('loginError').textContent=err.message;
  }
};

$('logoutButton').onclick=async()=>{
  await api('logout');
  location.reload();
};

function markDirty(){
  if(!currentSubjectId)return;
  dirty=true;
  status('Cambios sin guardar','is-warning');
  clearTimeout(timer);
  timer=setTimeout(()=>saveMemory(false).catch(console.error),2500);
}

$('memoryForm').addEventListener('input',markDirty);

function formObj(){
  const d={subject_id:Number(currentSubjectId)};
  new FormData($('memoryForm')).forEach((v,k)=>d[k]=v);
  return d;
}

function fillForm(m){
  $('memoryForm').querySelectorAll('input[name],textarea[name],select[name]').forEach(el=>el.value=m[el.name]??'');
  dirty=false;
  status('Guardado','is-success');
}

async function saveMemory(show=true){
  if(!currentSubjectId)return;
  await api('memory_save',{},{
    method:'POST',
    body:formObj()
  });
  dirty=false;
  status('Guardado','is-success');
  if(show)toast('success','Memoria guardada','Los datos se han guardado.');
  await loadSubjects(false);
}

$('saveButton').onclick=()=>saveMemory(true).catch(e=>toast('danger','Error',e.message));

async function loadSubjects(){
  const d=await api('subjects');
  subjects=d.subjects||[];
  $('dbStatus').textContent=`${subjects.length} asignaturas`;
  renderOptions();
  renderCards($('search-input').value);
}

function renderOptions(){
  $('subjectSelect').innerHTML=`<option value="">Selecciona una asignatura...</option>${subjects.map(s=>`<option value="${s.id}">${esc(s.full_name||s.slug)} (${s.total_grades})</option>`).join('')}`;
  $('subjectSelect').value=currentSubjectId;
}

function renderCards(filter=''){
  const q=filter.trim().toLowerCase(),vis=subjects.filter(s=>!q||`${s.full_name} ${s.slug} ${s.teacher_username}`.toLowerCase().includes(q));
  $('subjectCards').innerHTML=vis.map(s=>`<article class="${String(s.id)===String(currentSubjectId)?'activo':''}"><a href="#" data-subject-id="${s.id}"><div class="asunto-linea"><h3>${esc(s.full_name||s.slug)}</h3><span class="badge-thread">${s.total_grades}</span></div><p class="thread-meta">${esc(s.slug)} · ${esc(s.teacher_display_name||s.teacher_username||'')}</p><p>${Number(s.has_memory)===1?'<span class="ju-pill is-success">Memoria iniciada</span>':'<span class="ju-pill is-warning">Pendiente</span>'}</p></a></article>`).join('')||'<p class="ju-table-empty">No hay asignaturas.</p>';
}

async function selectSubject(id){
  if(dirty&&!confirm('Hay cambios sin guardar. ¿Cambiar igualmente?')){
    $('subjectSelect').value=currentSubjectId;
    return;
  }

  currentSubjectId=String(id||'');
  renderOptions();
  renderCards($('search-input').value);

  if(!currentSubjectId){
    clearResults();
    return;
  }

  status('Cargando...','is-info');

  const m=await api('memory_get',{subject_id:currentSubjectId}),
        g=await api('grades',{subject_id:currentSubjectId}),
        s=await api('stats',{subject_id:currentSubjectId});

  $('subjectTitle').textContent=m.subject.full_name||m.subject.slug;
  $('subjectMeta').textContent=`${g.rows.length} alumnos · ${m.subject.slug} · ${m.subject.teacher_display_name||m.subject.teacher_username}`;

  fillForm(m.memory);
  renderGrades(g.rows);
  renderStats(s.stats);
}

$('subjectSelect').onchange=()=>selectSubject($('subjectSelect').value).catch(e=>toast('danger','Error',e.message));

$('subjectCards').onclick=e=>{
  const a=e.target.closest('[data-subject-id]');
  if(!a)return;
  e.preventDefault();
  selectSubject(a.dataset.subjectId).catch(err=>toast('danger','Error',err.message));
};

function clearResults(){
  $('gradesTableWrap').innerHTML='<p class="ju-table-empty">Selecciona una asignatura.</p>';
  $('statsTableWrap').innerHTML='<p class="ju-table-empty">Sin datos.</p>';
  ['kpiStudents','kpiFinalPass','kpiFinalFail'].forEach(id=>$(id).textContent='—');
  if(statsChart){
    statsChart.destroy();
    statsChart=null;
  }
}

function renderGrades(rows){
  if(!rows.length){
    $('gradesTableWrap').innerHTML='<p class="ju-table-empty">No hay calificaciones.</p>';
    return;
  }

  $('gradesTableWrap').innerHTML=`<table class="ju-table"><thead><tr><th>Alumno</th>${E.map(ev=>`<th>${ev}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.full_name)}</td>${E.map(ev=>`<td class="${gclass(r[ev])}">${fmt(r[ev])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

function renderStats(st){
  const f=st.F||{};
  $('kpiStudents').textContent=f.total||'—';
  $('kpiFinalPass').textContent=pct(f.pass_pct);
  $('kpiFinalFail').textContent=pct(f.fail_pct);

  $('statsTableWrap').innerHTML=`<table class="ju-table"><thead><tr><th>Eval.</th><th>Evaluados</th><th>Aprobados</th><th>Suspensos</th><th>% Ap.</th><th>% Sus.</th><th>Media</th></tr></thead><tbody>${E.map(ev=>{const x=st[ev]||{};return`<tr><td><b>${ev}</b></td><td>${x.total||0}</td><td class="grade pass">${x.passed||0}</td><td class="grade fail">${x.failed||0}</td><td class="grade pass">${pct(x.pass_pct)}</td><td class="grade fail">${pct(x.fail_pct)}</td><td>${x.average==null?'—':fmt(x.average)}</td></tr>`}).join('')}</tbody></table>`;

  chart(st);
}

function chart(st){
  if(!window.Chart)return;
  if(statsChart)statsChart.destroy();

  statsChart=new Chart($('statsChart'),{
    type:'bar',
    data:{
      labels:E,
      datasets:[
        {label:'Aprobados (%)',data:E.map(ev=>Number(st[ev]?.pass_pct||0))},
        {label:'Suspensos (%)',data:E.map(ev=>Number(st[ev]?.fail_pct||0))}
      ]
    },
    options:{
      responsive:true,
      maintainAspectRatio:false,
      plugins:{legend:{position:'bottom'}},
      scales:{y:{beginAtZero:true,max:100,ticks:{callback:v=>`${v}%`}}}
    }
  });
}

/* FIX: navegación correcta dentro del panel derecho */
function goToSection(sectionId){
  if(sectionId==='adminUsers'){
    $('adminUsers').hidden=false;

    if(currentUser&&currentUser.role==='admin'){
      loadUsers().catch(e=>toast('danger','Error',e.message));
    }
  }

  const panel=$('panel');
  const target=$(sectionId);

  if(!panel||!target)return;

  requestAnimationFrame(()=>{
    panel.scrollTo({
      top:Math.max(0,target.offsetTop-panel.offsetTop-12),
      behavior:'smooth'
    });
  });
}

document.querySelectorAll('[data-section-link]').forEach(l=>l.onclick=e=>{
  e.preventDefault();

  document.querySelectorAll('[data-section-link]').forEach(x=>x.classList.remove('activo'));
  l.classList.add('activo');

  goToSection(l.dataset.sectionLink);
});

$('usersButton').onclick=()=>{
  document.querySelectorAll('[data-section-link]').forEach(x=>x.classList.remove('activo'));

  const adminLink=document.querySelector('[data-section-link="adminUsers"]');
  if(adminLink)adminLink.classList.add('activo');

  goToSection('adminUsers');
};

async function loadUsers(){
  if(currentUser.role!=='admin')return;

  const d=await api('users');

  $('usersTableWrap').innerHTML=`<table class="ju-table"><thead><tr><th>Usuario</th><th>Nombre</th><th>Rol</th><th>Activo</th><th>Asignaturas</th><th>Acciones</th></tr></thead><tbody>${d.users.map(u=>`<tr><td>${esc(u.username)}</td><td>${esc(u.display_name||'')}</td><td>${esc(u.role)}</td><td>${Number(u.is_active)?'Sí':'No'}</td><td>${u.total_subjects}</td><td><button class="ju-btn" data-edit='${esc(JSON.stringify(u))}'>Editar</button> <button class="ju-btn" data-del="${u.id}">Borrar</button></td></tr>`).join('')}</tbody></table>`;
}

$('usersTableWrap').onclick=async e=>{
  const ed=e.target.closest('[data-edit]'),
        del=e.target.closest('[data-del]');

  if(ed){
    const u=JSON.parse(ed.dataset.edit);

    for(const[k,v]of Object.entries(u)){
      if($('userForm').elements[k]){
        if(k==='is_active')$('userForm').elements[k].checked=Number(v)===1;
        else $('userForm').elements[k].value=v??'';
      }
    }

    $('userForm').elements.password.value='';
  }

  if(del&&confirm('¿Eliminar usuario?')){
    await api('user_delete',{},{
      method:'POST',
      body:{id:Number(del.dataset.del)}
    });

    await loadUsers();
    await loadSubjects();
  }
};

$('userForm').onsubmit=async e=>{
  e.preventDefault();

  const f=new FormData(e.target);

  await api('user_save',{},{
    method:'POST',
    body:{
      id:Number(f.get('id')||0),
      username:f.get('username'),
      display_name:f.get('display_name'),
      password:f.get('password'),
      role:f.get('role'),
      is_active:e.target.elements.is_active.checked
    }
  });

  e.target.reset();
  e.target.elements.is_active.checked=true;

  await loadUsers();
  await loadSubjects();

  toast('success','Usuario guardado','Cambios aplicados');
};

$('newUserButton').onclick=()=>{
  $('userForm').reset();
  $('userForm').elements.is_active.checked=true;
};

$('searchButton').onclick=()=>renderCards($('search-input').value);
$('search-input').oninput=()=>renderCards($('search-input').value);

$('clearSearchButton').onclick=()=>{
  $('search-input').value='';
  renderCards('');
};

$('printButton').onclick=()=>window.print();

window.onbeforeunload=e=>{
  if(!dirty)return;
  e.preventDefault();
  e.returnValue='';
};

checkAuth().catch(e=>{
  showLogin();
  $('loginError').textContent=e.message;
});
