/* ====== 夏收行动部署看板 - 前端逻辑 ====== */
let TOKEN='',ROLE=null;

/* 角色列表从后端动态拉取 */
(async function(){
  const sel=document.getElementById('selRole');
  try{
    const res=await fetch('/api/roles');
    const groups=await res.json();
    ['管理层','公众战区','商业战区','校园战区','行业战区'].forEach((g,idx)=>{
      if(!groups[g])return;
      if(idx>0){const sep=document.createElement('option');sep.disabled=true;sep.text='──────────';sep.style.color='var(--cyan)';sep.style.fontWeight='700';sel.appendChild(sep);}
      const head=document.createElement('option');head.disabled=true;head.text='【 '+g+' 】';head.style.color='var(--cyan)';head.style.fontWeight='700';sel.appendChild(head);
      groups[g].forEach(r=>{const o=document.createElement('option');o.value=r.id;o.text='  '+r.name;sel.appendChild(o);});
    });
  }catch(e){sel.innerHTML='<option>角色加载失败</option>'}
  /* 检测 URL token 参数（从管理后台返回时），自动恢复会话进入主页 */
  const urlToken=new URLSearchParams(location.search).get('token');
  if(urlToken){
    try{
      const meRes=await fetch('/api/me?token='+encodeURIComponent(urlToken));
      if(meRes.ok){
        const meData=await meRes.json();
        TOKEN=urlToken;ROLE=meData;
        history.replaceState(null,'','/');
        showPage('main');loadMainPage();
      }
    }catch(e){}
  }else{
    showPage('login');
  }
})();
document.getElementById('txtPwd').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin();});
window.addEventListener('scroll',()=>{const tip=document.getElementById('hoverTip');if(tip)tip.classList.remove('show');},{passive:true});

function showPage(name){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  const camel='page'+name.replace(/-([a-z])/g,(_,c)=>c.toUpperCase()).replace(/^./,s=>s.toUpperCase());
  const el=document.getElementById(camel);
  if(el) el.classList.add('active');
  window.scrollTo(0,0);
}

/* 页面历史栈，用于返回上一级 */
let PAGE_HISTORY=[];
function navigate(name){
  PAGE_HISTORY.push(name);
  showPage(name);
}
function goBack(){
  PAGE_HISTORY.pop();
  const prev=PAGE_HISTORY[PAGE_HISTORY.length-1]||'main';
  showPage(prev);
}
function goMain(){PAGE_HISTORY=[];showPage('main');}
function openAdmin(){location.href='/admin?token='+encodeURIComponent(TOKEN);}

async function doLogin(){
  const rid=document.getElementById('selRole').value,pwd=document.getElementById('txtPwd').value;
  if(!rid){showErr('请选择角色');return;}if(!pwd){showErr('请输入密码');return;}
  try{
    const res=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({role_id:rid,password:pwd})});
    if(!res.ok){const d=await res.json();showErr(d.detail||'登录失败');return;}
    const data=await res.json();TOKEN=data.token;ROLE=data.role;PAGE_HISTORY=['main'];showPage('main');loadMainPage();
  }catch(e){showErr('网络错误');}
}
function showErr(m){document.getElementById('loginErr').textContent=m;}
async function doLogout(){
  try{await fetch('/api/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:TOKEN})});}catch(e){}
  TOKEN='';ROLE=null;PAGE_HISTORY=[];document.getElementById('txtPwd').value='';document.getElementById('loginErr').textContent='';showPage('login');
}

/* ====== 主页 ====== */
async function loadMainPage(){
  document.getElementById('mainRoleBadge').textContent=ROLE.name;
  document.getElementById('mainRoleBadge').style.background='linear-gradient(135deg,rgba(0,212,255,.15),rgba(46,125,255,.12))';
  document.getElementById('mainZoneBadge').textContent=ROLE.zone_name;
  document.getElementById('mainZoneBadge').style.background=ROLE.color+'44';
  const isAdmin=!!ROLE.is_admin;
  document.getElementById('btnAdmin').style.display=isAdmin?'inline-block':'none';
  document.getElementById('searchSection').style.display=isAdmin?'flex':'none';
  document.getElementById('zoneSection').style.display=isAdmin?'block':'none';
  document.getElementById('troopLabel').textContent=isAdmin?'兵种':'我的战区 · 兵种';
  try{
    const res=await fetch('/api/overview?token='+TOKEN);
    if(!res.ok){if(res.status===401){doLogout();return;}throw new Error();}
    const data=await res.json();
    renderBattleGrid(data.battles);
    if(isAdmin) renderZoneGrid(data.zones);
    renderTroopOverview(data.zones);
  }catch(e){document.getElementById('mainBattleGrid').innerHTML='<div class="empty-state">加载失败</div>';}
}

function renderBattleGrid(battles){
  const isAdmin=!!ROLE.is_admin;
  let h='';battles.forEach(b=>{
    const click=isAdmin?`openBattleZones('${b.id}')`:`openDetail('${b.id}','${ROLE.zone}')`;
    h+=`<div class="card-item" onclick="${click}"><div class="card-name" style="color:${mapBattleColor(b.color)}">${esc(b.name)}</div><div class="card-count">${b.count}条数据</div><div class="card-arrow">&#10095;</div></div>`;
  });if(!h)h='<div class="empty-state">暂无相关战役数据</div>';
  document.getElementById('mainBattleGrid').innerHTML=h;
}

/* 颜色映射：原始暖色 → 自然柔和色 */
function mapBattleColor(c){
  const m={'#8B1A1A':'#ffd980','#C0392B':'#ffb060','#A63A3A':'#c4b5e8','#2E7D32':'#8eecd0'};
  return m[c]||'#ffffff';
}

function renderZoneGrid(zones){
  let h='';zones.forEach(z=>{
    h+=`<div class="card-item card-center" onclick="openZoneBattles('${z.id}')"><div class="card-name" style="color:${mapBattleColor(z.color)}">${esc(z.name)}</div><div class="card-count">${z.count}条数据</div></div>`;
  });document.getElementById('mainZoneGrid').innerHTML=h;
}

function renderTroopOverview(zones){
  const isAdmin=!!ROLE.is_admin;
  const isZoneManager=!isAdmin && (ROLE.role_name||'').match(/分局长|客户经理/);
  const canClick=isAdmin||isZoneManager;
  let h='';zones.forEach(z=>{
    let tags='';(z.roles||[]).forEach(r=>{
      const isMe=r===ROLE.role_name;
      const cls='tz-tag'+(isMe?' is-me':'')+(canClick?' clickable':'');
      const click=canClick?` onclick="showRoleBattles('${esc(r)}')"`:'';
      const title=canClick?('点击查看'+esc(r)+'的战役信息'):'';
      tags+=`<span class="${cls}"${click} title="${title}">${esc(r)}</span>`;
    });h+=`<div class="troop-zone-group"><div class="tz-name" style="color:${mapBattleColor(z.color)}">${esc(z.name)}</div><div class="tz-roles">${tags}</div></div>`;
  });document.getElementById('mainTroopZones').innerHTML=h;
}

/* ====== 战役→战区选择 ====== */
async function openBattleZones(bid){
  navigate('battle-zones');
  document.getElementById('bzTitle').textContent='加载中...';
  document.getElementById('bzInfo').textContent='';
  document.getElementById('bzBody').innerHTML='<div class="loading">加载中...</div>';
  try{
    const res=await fetch('/api/battle-zones/'+bid+'?token='+TOKEN);
    if(!res.ok){if(res.status===401){doLogout();return;}throw new Error();}
    const data=await res.json();
    document.getElementById('bzTitle').textContent=data.battle.name;
    document.getElementById('bzInfo').textContent='共'+data.total+'条数据';
    let h='';
    if(data.battle.target){
      h+=`<div class="module-section"><div class="module-title">战役总目标</div><div class="info-card"><div class="target-text">${esc(data.battle.target)}</div></div></div>`;
    }
    h+='<div class="section-label">请选择战区</div><div class="card-grid-4">';
    data.zones.forEach(z=>{
      h+=`<div class="card-item card-center" onclick="openDetail('${bid}','${z.id}')">
        <div class="card-name" style="color:${mapBattleColor(z.color)}">${esc(z.name)}</div>
        <div class="card-count">${z.count}条数据</div></div>`;
    });
    h+='</div>';
    if(!data.zones.length)h='<div class="empty-state">该战役暂无战区数据</div>';
    document.getElementById('bzBody').innerHTML=h;
  }catch(e){document.getElementById('bzBody').innerHTML='<div class="empty-state">加载失败</div>';}
}

/* ====== 战区→战役选择 ====== */
async function openZoneBattles(zid){
  navigate('zone-battles');
  document.getElementById('zbTitle').textContent='加载中...';
  document.getElementById('zbInfo').textContent='';
  document.getElementById('zbBody').innerHTML='<div class="loading">加载中...</div>';
  try{
    const res=await fetch('/api/zone-battles/'+zid+'?token='+TOKEN);
    if(!res.ok){if(res.status===401){doLogout();return;}throw new Error();}
    const data=await res.json();
    document.getElementById('zbTitle').textContent=data.zone.name;
    document.getElementById('zbInfo').textContent='共'+data.total+'条数据';
    let h='<div class="section-label">请选择战役</div><div class="card-grid-3">';
    data.battles.forEach(b=>{
      h+=`<div class="card-item" onclick="openDetail('${b.id}','${zid}')">
        <div class="card-name" style="color:${mapBattleColor(b.color)}">${esc(b.name)}</div>
        <div class="card-count">${b.count}条数据</div>
        <div class="card-arrow">&#10095;</div></div>`;
    });
    h+='</div>';
    if(!data.battles.length)h='<div class="empty-state">该战区暂无战役数据</div>';
    document.getElementById('zbBody').innerHTML=h;
  }catch(e){document.getElementById('zbBody').innerHTML='<div class="empty-state">加载失败</div>';}
}

/* ====== 数据详情页（战役+战区交叉） ====== */
async function openDetail(bid,zid){
  navigate('detail');
  document.getElementById('detailBreadcrumb').innerHTML='<span class="loading">加载中...</span>';
  document.getElementById('detailInfo').textContent='';
  document.getElementById('detailBody').innerHTML='<div class="loading">加载中...</div>';
  try{
    const res=await fetch('/api/detail/'+bid+'/'+zid+'?token='+TOKEN);
    if(!res.ok){if(res.status===401){doLogout();return;}throw new Error();}
    const data=await res.json();
    const bc=document.getElementById('detailBreadcrumb');
    bc.innerHTML=`
      <span class="crumb" onclick="openBattleZones('${bid}')">${esc(data.battle.name)}</span>
      <span class="sep">&#10095;</span>
      <span class="crumb" onclick="openZoneBattles('${zid}')">${esc(data.zone.name)}</span>
      <span class="sep">&#10095;</span>
      <span class="crumb active">数据详情</span>`;
    document.getElementById('detailInfo').textContent='共'+data.total+'条数据';
    renderDetailPage(data);
  }catch(e){document.getElementById('detailBody').innerHTML='<div class="empty-state">加载失败</div>';}
}

function renderDetailPage(data){
  const el=document.getElementById('detailBody');let h='';

  if(data.basic){
    h+=`<div class="module-section"><div class="module-title">基本信息</div><div class="info-card"><div class="card-fields">`;
    const fields={"战役编号":"战役编号","战役":"战役","战区":"战区","指导角色":"指导角色（营销统筹/专员）","作战角色":"作战角色"};
    for(const[label,key] of Object.entries(fields)){
      const v=(data.basic[key]||'').trim();
      h+=`<div class="field-row"><div class="field-label">${esc(label)}</div><div class="field-value${v?'':' empty'}">${v?esc(v):'---'}</div></div>`;
    }
    h+=`</div></div></div>`;
  }

  if(data.targets){
    const t=data.targets;const hasVal=Object.values(t).some(v=>v&&v.trim());
    if(hasVal){
      h+=`<div class="module-section"><div class="module-title">目标</div><div class="info-card"><div class="card-fields">`;
      for(const[label,key] of [['战役总目标','战役总目标'],['战区总目标','战区总目标']]){
        const v=(t[key]||'').trim();
        h+=`<div class="field-row"><div class="field-label">${esc(label)}</div><div class="field-value${v?'':' empty'}">${v?esc(v):'---'}</div></div>`;
      }
      h+=`</div></div></div>`;
    }
  }

  if(data.paths&&data.paths.length){
    h+=`<div class="module-section"><div class="module-title">路径</div><div class="path-grid">`;
    data.paths.forEach(p=>{
      const ck=data.battle.id+'|'+data.zone.id+'|'+p.path_id;
      h+=`<div class="path-card" onclick="openPath('${data.battle.id}','${data.zone.id}','${esc(p.path_id)}')" onmouseenter="hoverPathScenes(event,'${ck}','${esc(p.path_name)}')" onmouseleave="hideHoverPreview()">
        <div class="path-name">${esc(p.path_name)}</div>
        <div class="path-target">${p.path_target?esc(p.path_target):'暂无路径目标'}</div>
        <div class="path-meta"><span class="path-id">编号 ${esc(p.path_id)}</span><span class="path-scenes">${p.scene_count}个场景</span></div>
        <span class="path-arrow">&#10095;</span></div>`;
    });
    h+=`</div></div>`;
  }

  if(!h)h='<div class="empty-state">暂无数据</div>';
  el.innerHTML=h;
}

/* ====== 路径→场景列表页 ====== */
let SCENE_CACHE={};

async function openPath(bid,zid,pid){
  navigate('path');
  document.getElementById('pathBreadcrumb').innerHTML='<span class="loading">加载中...</span>';
  document.getElementById('pathInfo').textContent='';
  document.getElementById('pathBody').innerHTML='<div class="loading">加载中...</div>';
  try{
    const res=await fetch('/api/path-detail/'+bid+'/'+zid+'/'+encodeURIComponent(pid)+'?token='+TOKEN);
    if(!res.ok){if(res.status===401){doLogout();return;}throw new Error();}
    const data=await res.json();
    SCENE_CACHE[bid+'|'+zid+'|'+pid]=data;
    const bc=document.getElementById('pathBreadcrumb');
    bc.innerHTML=`
      <span class="crumb" onclick="openBattleZones('${bid}')">${esc(data.battle.name)}</span>
      <span class="sep">&#10095;</span>
      <span class="crumb" onclick="openZoneBattles('${zid}')">${esc(data.zone.name)}</span>
      <span class="sep">&#10095;</span>
      <span class="crumb" onclick="openDetail('${bid}','${zid}')">数据详情</span>
      <span class="sep">&#10095;</span>
      <span class="crumb active">${esc(data.path?.path_name||pid)}</span>`;
    document.getElementById('pathInfo').textContent=(data.scenes?.length||0)+'个场景';
    renderPathPage(data);
  }catch(e){document.getElementById('pathBody').innerHTML='<div class="empty-state">加载失败</div>';}
}

function renderPathPage(data){
  const el=document.getElementById('pathBody');let h='';

  h+=`<div class="module-section"><div class="module-title">路径信息</div><div class="info-card"><div class="card-fields">`;
  const bname=data.battle?.name||'---',zname=data.zone?.name||'---';
  [['战役',()=>bname],['战区',()=>zname],['路径编号',()=>data.path?.path_id||'---'],['路径',()=>data.path?.path_name||'---'],['路径目标',()=>data.path?.path_target||'---']].forEach(([label,fn])=>{
    const v=(fn()||'').trim();
    h+=`<div class="field-row"><div class="field-label">${esc(label)}</div><div class="field-value${v?'':' empty'}">${v?esc(v):'---'}</div></div>`;
  });
  h+=`</div></div></div>`;

  if(data.scenes&&data.scenes.length){
    h+=`<div class="module-section"><div class="module-title">场景</div><div class="scene-grid">`;
    const ck=data.battle.id+'|'+data.zone.id+'|'+(data.path?.path_id||'');
    data.scenes.forEach((s,idx)=>{
      const sceneTitle=s['场景名称']||s['场景（对到话术、作战角色）']||'未命名场景';
      const guide=s['指导角色（营销统筹/专员）']||'',combat=s['作战角色']||'';
      const source=s['商机来源']||'',cycle=s['最短管控周期']||'';
      h+=`<div class="scene-module" onclick="openScene('${ck}',${idx})" onmouseenter="hoverSceneInfo(event,'${ck}',${idx})" onmouseleave="hideHoverPreview()">
        <div class="sm-header"><span class="sm-id">${esc(s['场景编号']||'')}</span><span class="sm-name">${esc(sceneTitle)}</span></div>
        <div class="sm-fields">
          <div class="sm-field"><span class="sm-flabel">指导角色:</span><span class="sm-fval${guide?'':' empty'}">${guide?esc(guide):'---'}</span></div>
          <div class="sm-field"><span class="sm-flabel">作战角色:</span><span class="sm-fval${combat?'':' empty'}">${combat?esc(combat):'---'}</span></div>
          <div class="sm-field"><span class="sm-flabel">商机来源:</span><span class="sm-fval${source?'':' empty'}">${source?esc(source):'---'}</span></div>
          <div class="sm-field"><span class="sm-flabel">管控周期:</span><span class="sm-fval${cycle?'':' empty'}">${cycle?esc(cycle):'---'}</span></div>
        </div>
      </div>`;
    });
    h+=`</div></div>`;
  }

  if(!data.scenes||!data.scenes.length){
    h+='<div class="empty-state">该路径暂无场景数据</div>';
  }
  el.innerHTML=h;
}

/* ====== 场景详情页（单元模块） ====== */
const UNIT_FIELDS=[
  ['指导角色（营销统筹/专员）','指导角色（营销统筹/专员）'],
  ['作战角色','作战角色'],
  ['商机来源','商机来源'],
  ['最短管控周期','最短管控周期'],
  ['最短管控动作（量）','最短管控动作（量）'],
  ['最短管控目标（积分/金额）','最短管控目标（积分/金额）'],
  ['政策','政策'],
  ['激励','激励'],
  ['标准话术/动作','标准话术'],
  ['闭环管控','闭环管控'],
  ['受理到交付的流程','受理到交付的流程'],
];

function openScene(ck,idx){
  const data=SCENE_CACHE[ck];
  if(!data||!data.scenes||!data.scenes[idx])return;
  navigate('scene');
  const s=data.scenes[idx];
  const sceneTitle=s['场景名称']||s['场景（对到话术、作战角色）']||'未命名场景';
  document.getElementById('sceneBreadcrumb').innerHTML=`
    <span class="crumb" onclick="openBattleZones('${data.battle.id}')">${esc(data.battle.name)}</span>
    <span class="sep">&#10095;</span>
    <span class="crumb" onclick="openZoneBattles('${data.zone.id}')">${esc(data.zone.name)}</span>
    <span class="sep">&#10095;</span>
    <span class="crumb" onclick="openDetail('${data.battle.id}','${data.zone.id}')">数据详情</span>
    <span class="sep">&#10095;</span>
    <span class="crumb" onclick="openPath('${data.battle.id}','${data.zone.id}','${esc(data.path?.path_id||'')}')">${esc(data.path?.path_name||'')}</span>
    <span class="sep">&#10095;</span>
    <span class="crumb active">${esc(sceneTitle)}</span>`;
  document.getElementById('sceneInfo').textContent='共'+UNIT_FIELDS.length+'个单元';
  renderSceneDetail(data,s,sceneTitle);
}

function renderSceneDetail(data,s,sceneTitle){
  const el=document.getElementById('sceneBody');let h='';
  const ck=data.battle.id+'|'+data.zone.id+'|'+(data.path?.path_id||'');
  const sceneIdx=(data.scenes||[]).indexOf(s);

  h+=`<div class="module-section"><div class="module-title">场景信息</div><div class="info-card"><div class="card-fields">`;
  [['战役',()=>data.battle?.name||'---'],['战区',()=>data.zone?.name||'---'],['路径',()=>data.path?.path_name||'---'],['场景编号',()=>s['场景编号']||'---'],['场景名称',()=>sceneTitle]].forEach(([label,fn])=>{
    const v=(fn()||'').trim();
    h+=`<div class="field-row"><div class="field-label">${esc(label)}</div><div class="field-value${v?'':' empty'}">${v?esc(v):'---'}</div></div>`;
  });
  h+=`</div></div></div>`;

  h+=`<div class="module-section"><div class="module-title">单元信息</div><div class="unit-grid">`;
  UNIT_FIELDS.forEach((u,i)=>{
    const v=(s[u[1]]||'').trim();
    const firstV=firstLine(v);
    h+=`<div class="unit-module" onclick="openUnit('${ck}',${sceneIdx},${i})" onmouseenter="hoverUnitInfo(event,'${ck}',${sceneIdx},${i})" onmouseleave="hideHoverPreview()">
      <div class="um-label">${esc(u[0])}</div>
      <div class="um-value${firstV?'':' empty'}">${firstV?esc(firstV):'---'}</div>
      <span class="um-arrow">&#10095;</span>
    </div>`;
  });
  h+=`</div></div>`;
  el.innerHTML=h;
}

/* ====== 单元信息展示页 ====== */
function openUnit(ck,sceneIdx,unitIdx){
  const data=SCENE_CACHE[ck];
  if(!data||!data.scenes||!data.scenes[sceneIdx])return;
  const s=data.scenes[sceneIdx];
  const fieldDef=UNIT_FIELDS[unitIdx];
  if(!fieldDef)return;
  const sceneTitle=s['场景名称']||s['场景（对到话术、作战角色）']||'未命名场景';
  const v=(s[fieldDef[1]]||'').trim();
  navigate('unit');
  document.getElementById('unitBreadcrumb').innerHTML=`
    <span class="crumb" onclick="openBattleZones('${data.battle.id}')">${esc(data.battle.name)}</span>
    <span class="sep">&#10095;</span>
    <span class="crumb" onclick="openZoneBattles('${data.zone.id}')">${esc(data.zone.name)}</span>
    <span class="sep">&#10095;</span>
    <span class="crumb" onclick="openDetail('${data.battle.id}','${data.zone.id}')">数据详情</span>
    <span class="sep">&#10095;</span>
    <span class="crumb" onclick="openPath('${data.battle.id}','${data.zone.id}','${esc(data.path?.path_id||'')}')">${esc(data.path?.path_name||'')}</span>
    <span class="sep">&#10095;</span>
    <span class="crumb" onclick="openScene('${ck}',${sceneIdx})">${esc(sceneTitle)}</span>
    <span class="sep">&#10095;</span>
    <span class="crumb active">${esc(fieldDef[0])}</span>`;
  document.getElementById('unitInfo').textContent='';
  renderUnitDetail(data,s,sceneTitle,fieldDef,v);
}

function renderUnitDetail(data,s,sceneTitle,fieldDef,v){
  const el=document.getElementById('unitBody');let h='';
  h+=`<div class="module-section"><div class="unit-detail-card">`;
  h+=`<div style="font-size:14px;font-weight:700;color:var(--cyan);letter-spacing:2px;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border-hover);text-shadow:0 0 8px var(--cyan-glow)">单元信息</div>`;
  h+=`<div style="display:flex;flex-wrap:wrap;gap:10px 28px;margin-bottom:18px;padding:14px 18px;background:rgba(0,212,255,.05);border-radius:var(--radius);border-left:3px solid var(--cyan)">`;
  [['战役',()=>data.battle?.name||'---'],['战区',()=>data.zone?.name||'---'],['路径',()=>data.path?.path_name||'---'],['场景',()=>sceneTitle]].forEach(([label,fn])=>{
    const lv=(fn()||'').trim();
    h+=`<div style="display:flex;align-items:center;gap:8px"><span style="font-size:12px;color:var(--cyan);font-weight:500;white-space:nowrap">${esc(label)}</span><span style="font-size:13px;color:#fff;font-weight:700">${esc(lv)}</span></div>`;
  });
  h+=`</div>`;
  h+=`<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px"><span style="width:4px;height:18px;background:linear-gradient(180deg,var(--cyan),var(--blue));border-radius:2px"></span><span style="font-size:18px;font-weight:900;color:#fff;letter-spacing:2px">${esc(fieldDef[0])}</span></div>`;
  if(v){
    const lines=v.split('\n').map(l=>l.trim()).filter(Boolean);
    if(lines.length===1){
      h+=`<div style="font-size:15px;color:#fff;line-height:1.8;padding:8px 0">${esc(lines[0])}</div>`;
    }else{
      lines.forEach((line,i)=>{
        h+=`<div style="padding:10px 16px;background:rgba(0,212,255,.04);border:1px solid var(--border);border-radius:4px;font-size:14px;color:#fff;line-height:1.7;margin-bottom:8px"><span style="color:var(--cyan);font-weight:700;margin-right:8px">${i+1}.</span>${esc(line)}</div>`;
      });
    }
  }else{
    h+='<div class="field-value empty" style="font-size:14px;padding:14px 0;text-align:center">暂无数据</div>';
  }
  h+=`</div></div>`;
  el.innerHTML=h;
}

/* ====== 悬停预览组件 ====== */
function firstLine(s){return (s||'').trim().split('\n').filter(l=>l.trim())[0]?.trim()||'';}

let HOVER_TIMER=null;
function showHoverTip(e,innerHtml){
  clearTimeout(HOVER_TIMER);
  let tip=document.getElementById('hoverTip');
  if(!tip){
    tip=document.createElement('div');tip.id='hoverTip';tip.className='hover-tip';document.body.appendChild(tip);
  }
  tip.innerHTML=innerHtml;tip.classList.add('show');
  const rect=e.currentTarget.getBoundingClientRect();
  const tw=tip.offsetWidth,th=tip.offsetHeight;
  let left=rect.left+(rect.width/2)-(tw/2);
  if(left<10)left=10;
  if(left+tw>window.innerWidth-10)left=Math.max(10,window.innerWidth-tw-10);
  let top=rect.top-th-8;
  if(top<10)top=rect.bottom+8;
  tip.style.left=left+'px';tip.style.top=top+'px';
}
function hideHoverPreview(){
  HOVER_TIMER=setTimeout(()=>{
    const tip=document.getElementById('hoverTip');if(tip)tip.classList.remove('show');
  },150);
}

async function hoverPathScenes(e,ck,pname){
  showHoverTip(e,'<div class="ht-title">「'+esc(pname)+'」场景预览</div><div style="color:var(--text-dim)">加载中...</div>');
  let data=SCENE_CACHE[ck];
  if(!data){
    const[bid,zid,pid]=ck.split('|');
    try{
      const res=await fetch('/api/path-detail/'+bid+'/'+zid+'/'+encodeURIComponent(pid)+'?token='+TOKEN);
      if(!res.ok)throw new Error();
      data=await res.json();SCENE_CACHE[ck]=data;
    }catch(err){return;}
  }
  const tip=document.getElementById('hoverTip');
  if(!tip||!tip.classList.contains('show'))return;
  const scenes=data.scenes||[];
  if(!scenes.length){tip.innerHTML='<div class="ht-title">「'+esc(pname)+'」</div><div class="ht-empty">暂无场景数据</div>';return;}
  let rows=scenes.map(s=>{
    const st=s['场景名称']||s['场景（对到话术、作战角色）']||'未命名';
    return `<div class="ht-item"><div class="ht-item-name">${esc(s['场景编号']||'')} ${esc(st)}</div>`+
      `<div class="ht-row"><span class="ht-label">指导角色</span><span class="${s['指导角色（营销统筹/专员）']?'ht-val':'ht-empty'}">${s['指导角色（营销统筹/专员）']?esc(s['指导角色（营销统筹/专员）']):'---'}</span></div>`+
      `<div class="ht-row"><span class="ht-label">作战角色</span><span class="${s['作战角色']?'ht-val':'ht-empty'}">${s['作战角色']?esc(s['作战角色']):'---'}</span></div>`+
      `<div class="ht-row"><span class="ht-label">商机来源</span><span class="${s['商机来源']?'ht-val':'ht-empty'}">${s['商机来源']?esc(s['商机来源']):'---'}</span></div>`+
      `</div>`;
  }).join('');
  tip.innerHTML='<div class="ht-title">「'+esc(pname)+'」共 '+scenes.length+' 个场景</div>'+rows;
}

function hoverSceneInfo(e,ck,idx){
  const data=SCENE_CACHE[ck];if(!data||!data.scenes||!data.scenes[idx])return;
  const s=data.scenes[idx];
  const sceneTitle=s['场景名称']||s['场景（对到话术、作战角色）']||'未命名';
  let rows=UNIT_FIELDS.map(u=>{
    const v=(s[u[1]]||'').trim();
    return `<div class="ht-row"><span class="ht-label">${esc(u[0])}</span><span class="${v?'ht-val':'ht-empty'}">${v?esc(firstLine(v)):'---'}</span></div>`;
  }).join('');
  showHoverTip(e,'<div class="ht-title">'+esc(s['场景编号']||'')+' '+esc(sceneTitle)+'</div>'+rows);
}

function hoverUnitInfo(e,ck,sceneIdx,unitIdx){
  const data=SCENE_CACHE[ck];if(!data||!data.scenes||!data.scenes[sceneIdx])return;
  const s=data.scenes[sceneIdx];
  const fd=UNIT_FIELDS[unitIdx];if(!fd)return;
  const v=(s[fd[1]]||'').trim();
  const content=v?esc(v).replace(/\n/g,'<br>'):'<span class="ht-empty">暂无数据</span>';
  showHoverTip(e,'<div class="ht-title">'+esc(fd[0])+'</div><div class="ht-val" style="line-height:1.8">'+content+'</div>');
}

function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

/* ====== 通用弹窗 ====== */
function openModal(title, bodyHTML, small){
  let mask=document.getElementById('modalMask');
  if(!mask){
    mask=document.createElement('div');
    mask.id='modalMask';mask.className='modal-mask';
    mask.innerHTML=`<div class="modal-box"><div class="modal-header"><h3 id="modalTitle"></h3><button class="modal-close" onclick="closeModal()">&times;</button></div><div class="modal-body" id="modalBody"></div></div>`;
    document.body.appendChild(mask);
    mask.addEventListener('click',e=>{if(e.target===mask)closeModal();});
  }
  document.getElementById('modalTitle').textContent=title;
  document.getElementById('modalBody').innerHTML=bodyHTML;
  mask.querySelector('.modal-box').className='modal-box'+(small?' small':'');
  mask.classList.add('show');
}
function closeModal(){const m=document.getElementById('modalMask');if(m)m.classList.remove('show');}

/* ====== 兵种标签点击查看战役信息 ====== */
async function showRoleBattles(roleName){
  openModal('「'+roleName+'」 · 战役信息','<div class="empty-state" style="padding:30px">加载中...</div>');
  try{
    const res=await fetch('/api/role-battles/'+encodeURIComponent(roleName)+'?token='+TOKEN);
    if(!res.ok){
      if(res.status===401){doLogout();return;}
      if(res.status===403){const d=await res.json();document.getElementById('modalBody').innerHTML='<div class="empty-state">'+esc(d.detail||'无权查看')+'</div>';return;}
      throw new Error();
    }
    const data=await res.json();
    if(!data.battles.length){
      document.getElementById('modalBody').innerHTML='<div class="empty-state">「'+esc(roleName)+'」暂无战役数据</div>';
      return;
    }
    let h='<div style="font-size:12px;color:var(--text-dim);margin-bottom:14px;letter-spacing:1px">「'+esc(roleName)+'」共参与 '+data.battles.length+' 个战役，'+data.total+' 条数据</div>';
    h+='<div class="card-grid-3" style="gap:12px">';
    data.battles.forEach(b=>{
      const zoneStr=(b.zones||[]).map(z=>z.name).join('、');
      h+=`<div class="card-item" onclick="closeModal();openDetail('${b.id}','${(b.zones[0]||{}).id||''}')">
        <div class="card-name" style="color:${mapBattleColor(b.color)}">${esc(b.name)}</div>
        <div class="card-count">${b.count}条数据 · ${esc(zoneStr)}</div>
        <div class="card-arrow">&#10095;</div></div>`;
    });
    h+='</div>';
    document.getElementById('modalBody').innerHTML=h;
  }catch(e){document.getElementById('modalBody').innerHTML='<div class="empty-state">加载失败</div>';}
}

/* ====== 检索侧边抽屉 ====== */
function ensureDrawer(){
  let d=document.getElementById('searchDrawer');
  if(!d){
    d=document.createElement('div');d.id='searchDrawer';d.className='search-drawer';
    d.innerHTML=`<div class="drawer-header"><h3 id="drawerTitle">检索结果</h3><button class="drawer-close" onclick="closeDrawer()">&times;</button></div>
      <div class="drawer-count" id="drawerCount"></div><div class="drawer-body" id="drawerBody"></div>`;
    document.body.appendChild(d);
  }
  return d;
}
function closeDrawer(){const d=document.getElementById('searchDrawer');if(d)d.classList.remove('show');}
function selectResult(el,bid,zid){
  document.querySelectorAll('#drawerBody .result-item').forEach(r=>r.classList.remove('active'));
  if(el)el.classList.add('active');
  openDetail(bid,zid);
}
async function doSearch(){
  const kw=document.getElementById('guideSearch').value.trim();
  if(!kw){return;}
  const d=ensureDrawer();
  document.getElementById('drawerTitle').textContent='检索：'+kw;
  document.getElementById('drawerCount').textContent='检索中...';
  document.getElementById('drawerBody').innerHTML='<div class="loading">加载中...</div>';
  d.classList.add('show');
  try{
    const res=await fetch('/api/search?keyword='+encodeURIComponent(kw)+'&token='+TOKEN);
    if(!res.ok){if(res.status===401){doLogout();return;}throw new Error();}
    const data=await res.json();
    if(!data.results.length){
      document.getElementById('drawerCount').textContent='未找到匹配';
      document.getElementById('drawerBody').innerHTML='<div class="empty-state">未找到「'+esc(kw)+'」相关的部署记录</div>';
      return;
    }
    document.getElementById('drawerCount').textContent='共 '+data.results.length+' 条匹配 · 点击查看详情';
    let h='';
    data.results.forEach((r,i)=>{
      h+=`<div class="result-item" id="ritem-${i}" onclick="selectResult(this,'${r.battle_id}','${r.warzone_id}')">
        <div class="ri-title">${esc(r.battle_name)} · ${esc(r.path_name||'路径')}</div>
        <div class="ri-meta">
          <span>战区：<b>${esc(r.warzone_name)}</b></span>
          <span>指导：<b>${esc(r.guide_role||'—')}</b></span>
          <span>作战：<b>${esc(r.combat_role||'—')}</b></span>
        </div>
      </div>`;
    });
    document.getElementById('drawerBody').innerHTML=h;
  }catch(e){document.getElementById('drawerBody').innerHTML='<div class="empty-state">检索失败</div>';}
}
