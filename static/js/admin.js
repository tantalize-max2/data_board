/* ====== 夏收行动部署看板 - 管理后台逻辑 ====== */
const TOKEN = new URLSearchParams(location.search).get('token') || sessionStorage.getItem('admin_token') || '';
if(TOKEN) sessionStorage.setItem('admin_token', TOKEN);
if(!TOKEN){ location.href='/'; }

/* 当前用户信息（启动时加载） */
let ME=null, IS_ADMIN=false, IS_ZONE_ADMIN=false;

/* 权限等级：3=管理员 2=战区管理员 1=指导员 0=普通 */
function userLevel(u){return u.is_admin?3:u.is_zone_admin?2:u.is_guide?1:0;}
function canEditUser(target){
  if(!target||target.username===ME?.username)return true;
  return userLevel(ME)>userLevel(target);
}
(async()=>{
  try{
    ME=await api('/api/me');
    IS_ADMIN=!!ME.is_admin;
    IS_ZONE_ADMIN=!!ME.is_zone_admin;
    initAdminWatermark();
  }catch(e){}
})();

/* 管理后台水印 */
function initAdminWatermark(){
  const layer=document.getElementById('watermarkLayer');
  if(!layer||!ME||!ME.name)return;
  const text=ME.name+'_'+(ME.phone||ME.username||'');
  const cols=5,rows=3;
  let h='';
  for(let r=0;r<rows;r++){
    for(let c=0;c<cols;c++){
      const xPct=8+(84*c/(cols-1));
      const yPct=10+(80*r/(rows-1));
      h+=`<div class="wm-item" style="left:${xPct}%;top:${yPct}%">${esc(text)}</div>`;
    }
  }
  layer.innerHTML=h;
  layer.style.display='block';
}

/* 自定义确认弹窗（替代原生confirm） */
let _adminConfirmCb=null;
function showConfirm(msg,cb){
  const m=document.getElementById('confirmMask');
  document.getElementById('confirmMsg').textContent=msg;
  _adminConfirmCb=cb;
  m.style.display='flex';
}
function closeAdminConfirm(){
  document.getElementById('confirmMask').style.display='none';
  _adminConfirmCb=null;
}
function execAdminConfirm(){
  const cb=_adminConfirmCb;
  document.getElementById('confirmMask').style.display='none';
  _adminConfirmCb=null;
  if(cb)cb();
}

/* 自定义输入弹窗（替代原生prompt） */
let _adminPromptCb=null;
function showAdminPrompt(title,msg,defaultVal,cb){
  document.getElementById('promptTitle').textContent=title;
  document.getElementById('promptMsg').textContent=msg||'';
  const inp=document.getElementById('promptInput');
  inp.value=defaultVal||'';
  _adminPromptCb=cb;
  document.getElementById('promptMask').style.display='flex';
  setTimeout(()=>inp.focus(),50);
}
function closeAdminPrompt(){
  document.getElementById('promptMask').style.display='none';
  _adminPromptCb=null;
}
function execAdminPrompt(){
  const val=document.getElementById('promptInput').value.trim();
  const cb=_adminPromptCb;
  closeAdminPrompt();
  if(cb)cb(val);
}

function backToBoard(){
  localStorage.setItem('xs_token',TOKEN);
  location.href='/';
}

/* 颜色映射：原始暖色 → 自然柔和色 */
function mapColor(c){
  const m={'#8B1A1A':'#ffd980','#C0392B':'#ffb060','#A63A3A':'#c4b5e8','#2E7D32':'#8eecd0',
           '#1565c0':'#ffd980','#2e7d32':'#8eecd0','#7b1fa2':'#c4b5e8','#e65100':'#ffb060'};
  return m[c]||'#ffffff';
}

const ZONE_LABEL = {public:'公众战区',business:'商客战区',education:'校园战区',industry:'行业战区',all:'全部战区'};
const ZONE_CLASS = {public:'tag-public',business:'tag-business',education:'tag-education',industry:'tag-industry',all:'tag-admin'};
let DASHBOARD=null, RECORD_SCHEMA=null;

async function api(path, {method='GET', body}={}){
  const sep = path.includes('?')?'&':'?';
  const url = path + sep + 'token=' + encodeURIComponent(TOKEN);
  const opts = {method};
  if(body!==undefined){ opts.headers={'Content-Type':'application/json'}; opts.body=JSON.stringify(body); }
  const res = await fetch(url, opts);
  if(res.status===401){ location.href='/'; throw new Error('未登录'); }
  if(res.status===403){
    const d=await res.json().catch(()=>({}));
    toast(d.detail||'无操作权限','error'); throw new Error(d.detail||'无权限');
  }
  if(!res.ok){ const d=await res.json().catch(()=>({})); throw new Error(d.detail||'请求失败'); }
  return res.json();
}

function esc(s){return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function toast(msg, type=''){
  const t=document.getElementById('toast');
  t.textContent=msg; t.className='toast show '+type;
  clearTimeout(t._t); t._t=setTimeout(()=>t.className='toast '+type, 2400);
}
function openModal(title, bodyHTML, footerHTML, large){
  document.getElementById('drawerTitle').textContent=title;
  document.getElementById('drawerBody').innerHTML=bodyHTML;
  document.getElementById('drawerFooter').innerHTML=footerHTML||'';
  const drawer=document.getElementById('adminDrawer');
  drawer.className='admin-drawer'+(large?' large':'');
  document.getElementById('drawerMask').classList.add('show');
  drawer.classList.add('show');
}
function closeModal(){
  document.getElementById('adminDrawer').classList.remove('show');
  document.getElementById('drawerMask').classList.remove('show');
}
function closeDrawer(){closeModal();}
document.getElementById('drawerMask').addEventListener('click',closeModal);

/* Tab 切换 */
const TAB_LOADERS = {overview:loadOverview, users:loadUsers, access:loadAccess, content:loadContent};
document.querySelectorAll('.nav-item').forEach(item=>{
  item.addEventListener('click',()=>{
    document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
    item.classList.add('active');
    const tab=item.dataset.tab;
    document.getElementById('tab-'+tab).classList.add('active');
    TAB_LOADERS[tab]();
  });
});

/* ====== 数据概览 ====== */
async function loadOverview(){
  const el=document.getElementById('tab-overview');
  el.innerHTML='<div class="loading">加载中...</div>';
  try{
    DASHBOARD = await api('/api/admin/dashboard');
    const zu = DASHBOARD.zone_users;
    el.innerHTML=`
      <div class="panel-title">数据概览</div>
      <div class="stat-grid">
        <div class="stat-card"><div class="stat-label">在册人员</div><div class="stat-value">${DASHBOARD.users}</div><div class="stat-sub">个岗位账号</div></div>
        <div class="stat-card"><div class="stat-label">部署记录</div><div class="stat-value">${DASHBOARD.records}</div><div class="stat-sub">条业务数据</div></div>
        <div class="stat-card"><div class="stat-label">权限规则</div><div class="stat-value">${DASHBOARD.access_rules}</div><div class="stat-sub">条授权关系</div></div>
        <div class="stat-card"><div class="stat-label">战役数</div><div class="stat-value">${DASHBOARD.battles.length}</div><div class="stat-sub">个战役</div></div>
      </div>
      <div class="panel-title">各战区人员分布</div>
      <div class="stat-grid">
        ${DASHBOARD.warzones.map(w=>`
          <div class="stat-card"><div class="stat-label">${esc(w.name)}</div><div class="stat-value">${zu[w.id]||0}</div><div class="stat-sub">人</div></div>
        `).join('')}
      </div>
      <div class="panel-title">战役清单</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px">
        ${DASHBOARD.battles.map(b=>`<div style="background:var(--bg-card);border:1px solid var(--border);border-left:3px solid ${mapColor(b.color)};padding:12px 16px;border-radius:var(--radius)"><div style="font-weight:700;color:${mapColor(b.color)}">${esc(b.name)}</div><div style="font-size:10px;color:var(--text-dim);margin-top:4px">编号 ${esc(b.id)}</div></div>`).join('')}
      </div>`;
  }catch(e){ el.innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>'; }
}

/* ====== 人员管理 ====== */
let USERS_STATE = {q:'', zone:''};

async function loadUsers(){
  const el=document.getElementById('tab-users');
  el.innerHTML=`
    <div class="panel-title">人员管理 <span class="count" id="usersCount"></span></div>
    <div class="toolbar">
      <div class="search-box with-icon"><span class="icon">&#128269;</span><input id="userQ" placeholder="搜索姓名 / 岗位 / 电话 / 账号" value="${esc(USERS_STATE.q)}"></div>
      <select id="userZone" class="toolbar-select">
        <option value="">全部战区</option>
        <option value="public"${USERS_STATE.zone==='public'?' selected':''}>公众战区</option>
        <option value="business"${USERS_STATE.zone==='business'?' selected':''}>商客战区</option>
        <option value="education"${USERS_STATE.zone==='education'?' selected':''}>校园战区</option>
        <option value="industry"${USERS_STATE.zone==='industry'?' selected':''}>行业战区</option>
      </select>
      <button class="btn btn-primary" onclick="fetchUsers()">搜索</button>
      <button class="btn btn-ghost" onclick="openUserEdit(null)">+ 新增人员</button>
      <button class="btn btn-ghost" onclick="openPositionManager()">岗位管理</button>
    </div>
    <div id="usersTable"><div class="loading">加载中...</div></div>`;
  document.getElementById('userQ').addEventListener('keydown',e=>{if(e.key==='Enter')fetchUsers();});
  document.getElementById('userZone').addEventListener('change',()=>{USERS_STATE.zone=document.getElementById('userZone').value;fetchUsers();});
  fetchUsers();
}

/* ====== 岗位管理 ====== */
async function openPositionManager(){
  try{
    const data=await api('/api/admin/positions');
    const grouped=data.grouped||[];
    let bodyHtml='<div style="margin-bottom:10px;font-size:13px;color:var(--text-dim)">管理各战区下的岗位，可新增、编辑、删除岗位名称。删除岗位后该岗位下的人员将被清空角色名。</div>';
    grouped.forEach(g=>{
      bodyHtml+=`<div style="margin-bottom:16px">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid var(--border-hover)">
          <span style="font-size:13px;font-weight:700;color:var(--cyan)">${esc(g.zone_name)}</span>
          <button class="btn btn-primary btn-sm" style="font-size:11px;padding:4px 12px" onclick="addPosition('${esc(g.zone)}','${esc(g.zone_name)}')">+ 新增岗位</button>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:8px">`;
      (g.positions||[]).forEach(p=>{
        bodyHtml+=`<div style="display:flex;align-items:center;gap:6px;padding:6px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:rgba(0,0,0,.15)">
          <span>${esc(p.role_name)}</span>
          <span style="font-size:10px;color:var(--text-dim)">${p.count}人</span>
          <button style="background:none;border:none;color:var(--cyan);cursor:pointer;font-size:12px;padding:0 4px" onclick="editPosition('${esc(g.zone)}','${esc(p.role_name)}')" title="编辑">&#9998;</button>
          <button style="background:none;border:none;color:#ff6b6b;cursor:pointer;font-size:12px;padding:0 4px" onclick="deletePosition('${esc(g.zone)}','${esc(p.role_name)}',${p.count})" title="删除">&times;</button>
        </div>`;
      });
      bodyHtml+='</div></div>';
    });
    openModal('岗位管理',bodyHtml,`<button class="btn btn-ghost" onclick="closeModal()">关闭</button>`);
  }catch(e){toast(e.message,'error');}
}

async function addPosition(zone,zoneName){
  showAdminPrompt('新增岗位','请输入岗位名称：','',async(name)=>{
    if(!name)return;
    try{
      await api('/api/admin/positions',{method:'POST',body:{zone,role_name:name}});
      toast('岗位已新增','success'); openPositionManager();
    }catch(e){toast(e.message,'error');}
  });
}

async function editPosition(zone,oldName){
  showAdminPrompt('编辑岗位','请输入新的岗位名称：',oldName,async(newName)=>{
    if(!newName||newName===oldName)return;
    try{
      await api('/api/admin/positions',{method:'PUT',body:{zone,old_name:oldName,new_name:newName}});
      toast('岗位已更新','success'); openPositionManager();
    }catch(e){toast(e.message,'error');}
  });
}

async function deletePosition(zone,roleName,count){
  if(count>0){
    showConfirm('岗位「'+roleName+'」下还有'+count+'人，删除后这些人员的角色名将被清空。确认删除？',async()=>{
      try{await api('/api/admin/positions?zone='+encodeURIComponent(zone)+'&role_name='+encodeURIComponent(roleName),{method:'DELETE'});toast('岗位已删除','success');openPositionManager();}
      catch(e){toast(e.message,'error');}
    });
  }else{
    try{await api('/api/admin/positions?zone='+encodeURIComponent(zone)+'&role_name='+encodeURIComponent(roleName),{method:'DELETE'});toast('岗位已删除','success');openPositionManager();}
    catch(e){toast(e.message,'error');}
  }
}

async function fetchUsers(){
  const q=document.getElementById('userQ').value.trim();
  USERS_STATE.q=q;
  const params=new URLSearchParams({q, zone:USERS_STATE.zone});
  try{
    const data=await api('/api/admin/users?'+params.toString());
    document.getElementById('usersCount').textContent='共 '+data.total+' 人';
    const tb=document.getElementById('usersTable');
    if(!data.users.length){ tb.innerHTML='<div class="empty">无匹配人员</div>'; return; }
    tb.innerHTML=`
      <div class="table-scroll">
        <table class="data-table">
          <thead><tr><th>姓名</th><th>岗位</th><th>战区</th><th>手机号</th><th>角色</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>${data.users.map(u=>`
            <tr>
              <td style="font-weight:700">${esc(u.name)}</td>
              <td>${esc(u.role_name)}</td>
              <td><span class="tag ${ZONE_CLASS[u.zone]||''}">${esc(ZONE_LABEL[u.zone]||u.zone_name)}</span></td>
              <td style="color:var(--text-dim)">${esc(u.phone||u.username||'—')}</td>
              <td>${u.is_admin?'<span class="tag tag-admin">管理员</span>':u.is_zone_admin?'<span class="tag" style="background:rgba(0,212,255,.15);color:var(--cyan)">战区管理员</span>':'<span style="color:var(--text-dim)">普通</span>'}</td>
              <td>${u.is_active?'<span class="tag tag-active">在用</span>':'<span class="tag tag-stopped">停用</span>'}</td>
              <td>
                ${canEditUser(u)?`<button class="btn btn-ghost btn-sm" onclick="openUserEdit(${u.id})">编辑</button>`:`<button class="btn btn-ghost btn-sm" disabled style="opacity:.3;cursor:not-allowed">编辑</button>`}
                ${u.is_active?`<button class="btn btn-danger btn-sm" ${canEditUser(u)?`onclick="stopUser(${u.id},'${esc(u.name)}')"`:'disabled style="opacity:.3;cursor:not-allowed"'}>停用</button>`:`<button class="btn btn-primary btn-sm" ${canEditUser(u)?`onclick="activateUser(${u.id},'${esc(u.name)}')"`:'disabled style="opacity:.3;cursor:not-allowed"'}>启用</button>`}
                ${canEditUser(u)?`<button class="btn btn-ghost btn-sm" onclick="openUserRoles(${u.id})" title="赋予额外角色">角色</button>`:`<button class="btn btn-ghost btn-sm" disabled style="opacity:.3;cursor:not-allowed">角色</button>`}
                ${canEditUser(u)?`<button class="btn btn-danger btn-sm" onclick="deleteUser(${u.id},'${esc(u.name)}')">删除</button>`:`<button class="btn btn-danger btn-sm" disabled style="opacity:.3;cursor:not-allowed">删除</button>`}
              </td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
  }catch(e){ document.getElementById('usersTable').innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>'; }
}

async function openUserEdit(uid){
  let u=null;
  if(uid){
    const all=await api('/api/admin/users');
    u=all.users.find(x=>x.id===uid);
    if(!u){toast('人员不存在','error');return;}
    if(!canEditUser(u)){toast('无权限编辑同级或更高级人员','error');return;}
  }
  const zones=Object.entries(ZONE_LABEL).filter(([k])=>k!=='all');
  const zoneLocked=IS_ZONE_ADMIN&&!IS_ADMIN;
  const canSetAdmin=IS_ADMIN;                     /* 总经理 */
  const canSetZoneAdmin=IS_ADMIN;                 /* 战区管理员 */
  const canSetGuide=IS_ADMIN||IS_ZONE_ADMIN;      /* 指导员 - 战区管理员也可设置 */
  const currentZone=zoneLocked?(ME?.zone||''):(u?.zone||'business');
  /* 获取本战区岗位列表 */
  let positions=[];
  try{
    const posData=await api('/api/admin/positions');
    const zg=(posData.grouped||[]).find(g=>g.zone===currentZone);
    if(zg)positions=zg.positions.map(p=>p.role_name);
  }catch(e){}
  const roleOpts=positions.length>0?positions:[u?.role_name||''].filter(Boolean);
  /* 确保当前角色在列表中 */
  if(u?.role_name&&!roleOpts.includes(u.role_name)) roleOpts.unshift(u.role_name);
  openModal(uid?'编辑人员':'新增人员', `
    <div class="form-grid">
      <div class="form-field"><label>姓名</label><input id="f_name" value="${esc(u?.name||'')}"></div>
      <div class="form-field"><label>岗位名称</label>
        <select id="f_role_name" style="width:100%;background:rgba(0,0,0,.25);border:1px solid var(--border-hover);border-radius:6px;color:#fff;padding:8px 12px;font-size:14px">
          ${roleOpts.map(r=>`<option value="${esc(r)}" ${r===(u?.role_name||'')?'selected':''}>${esc(r)}</option>`).join('')}
        </select></div>
      <div class="form-field"><label>手机号 <span class="hint">（用于登录）</span></label><input id="f_phone" value="${esc(u?.phone||u?.username||'')}" placeholder="请输入手机号"></div>
      <div class="form-field"><label>所属战区</label><select id="f_zone" onchange="onUserZoneChange(this.value)" ${zoneLocked?'disabled':''}>${zones.map(([k,v])=>`<option value="${k}"${currentZone===k?' selected':''}>${v}</option>`).join('')}</select></div>
      <div class="form-field"><label>密码 <span class="hint">${uid?'留空不修改':'默认 Xs@2026'}</span></label><input id="f_password" type="password" placeholder="留空不修改"></div>
      ${canSetAdmin?`<div class="form-field full"><div class="checkbox-row"><input id="f_admin" type="checkbox" ${u?.is_admin?'checked':''}> <label for="f_admin" style="margin:0">设为总经理（可访问全部数据与管理后台）</label></div></div>`:''}
      ${canSetZoneAdmin?`<div class="form-field"><label>战区管理员</label><div class="checkbox-row"><input id="f_zone_admin" type="checkbox" ${u?.is_zone_admin?'checked':''}> <label for="f_zone_admin" style="margin:0">设为战区管理员（可管理本战区人员与内容）</label></div></div>`:''}
      ${canSetGuide?`<div class="form-field"><label>指导员</label><div class="checkbox-row"><input id="f_guide" type="checkbox" ${u?.is_guide?'checked':''}> <label for="f_guide" style="margin:0">设为指导员（可编辑内容，无管理后台和增删权限）</label></div></div>`:''}
    </div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">取消</button><button class="btn btn-primary" onclick="saveUser(${uid||0})">保存</button>`);
}

/* 切换战区时刷新岗位下拉 */
async function onUserZoneChange(zone){
  let positions=[];
  try{
    const posData=await api('/api/admin/positions');
    const zg=(posData.grouped||[]).find(g=>g.zone===zone);
    if(zg)positions=zg.positions.map(p=>p.role_name);
  }catch(e){}
  const sel=document.getElementById('f_role_name');
  if(sel){
    sel.innerHTML=positions.map(r=>`<option value="${esc(r)}">${esc(r)}</option>`).join('');
  }
}

async function saveUser(uid){
  const zoneEl=document.getElementById('f_zone');
  const body={
    name:document.getElementById('f_name').value.trim(),
    role_name:document.getElementById('f_role_name').value.trim(),
    phone:document.getElementById('f_phone').value.trim(),
    zone:zoneEl.value||zoneEl.querySelector('option[selected]')?.value||ME?.zone||'public',
    password:document.getElementById('f_password').value,
    is_admin:document.getElementById('f_admin')?document.getElementById('f_admin').checked:false,
    is_zone_admin:document.getElementById('f_zone_admin')?document.getElementById('f_zone_admin').checked:false,
    is_guide:document.getElementById('f_guide')?document.getElementById('f_guide').checked:false,
  };
  if(!body.name||!body.role_name){toast('姓名与岗位必填','error');return;}
  if(!body.phone){toast('手机号必填','error');return;}
  body.username=body.phone;  /* 手机号即账号 */
  try{
    if(uid) await api('/api/admin/users/'+uid,{method:'PUT',body});
    else{
      await api('/api/admin/users',{method:'POST',body});
    }
    toast(uid?'已更新':'已新增','success'); closeModal(); fetchUsers();
  }catch(e){toast(e.message,'error');}
}

async function stopUser(uid,name){
  showConfirm('确认停用「'+name+'」？停用后该账号无法登录。',async()=>{
    try{ await api('/api/admin/users/'+uid,{method:'DELETE'}); toast('已停用','success'); fetchUsers(); }
    catch(e){toast(e.message||'操作失败','error');}
  });
}

async function activateUser(uid,name){
  showConfirm('确认启用「'+name+'」？',async()=>{
    try{ await api('/api/admin/users/'+uid+'/activate',{method:'PUT'}); toast('已启用','success'); fetchUsers(); }
    catch(e){toast(e.message||'操作失败','error');}
  });
}

async function deleteUser(uid,name){
  showConfirm('确认删除「'+name+'」？此操作不可恢复，将永久删除该人员所有数据！',async()=>{
    try{ await api('/api/admin/users/'+uid+'?hard=1',{method:'DELETE'}); toast('已删除','success'); fetchUsers(); }
    catch(e){toast(e.message||'操作失败','error');}
  });
}
async function openUserRoles(uid){
  try{
    const d=await api('/api/admin/user-roles/'+uid);
    const grouped=d.all_roles_grouped||[];
    const userZone=d.user_zone||'';
    let bodyHtml='<div style="margin-bottom:10px;font-size:13px;color:var(--text-dim)">勾选需要赋予的额外角色，赋予后该用户将拥有这些角色的数据视角：</div>';
    const extraSet=new Map();  /* key=zone|role_name */
    (d.extra_roles||[]).forEach(r=>extraSet.set((r.zone||'')+'|'+r.role_name,true));
    grouped.forEach(g=>{
      const isMine=g.zone===userZone;
      bodyHtml+=`<div style="margin-bottom:14px">
        <div style="font-size:12px;font-weight:700;color:var(--cyan);margin-bottom:6px;padding-bottom:4px;border-bottom:1px solid var(--border-hover)">${esc(g.zone_name)}${isMine?' <span style="color:var(--text-dim);font-weight:400">（本战区）</span>':''}</div>
        <div style="display:flex;flex-wrap:wrap;gap:8px">`;
      (g.roles||[]).forEach(r=>{
        if(r===d.primary_role&&isMine){bodyHtml+=`<label style="display:flex;align-items:center;gap:6px;padding:6px 14px;border:1px solid var(--border-hover);border-radius:6px;font-size:13px;opacity:.5;cursor:default">
          <input type="checkbox" checked disabled> ${esc(r)} <span style="font-size:10px;color:var(--text-dim)">主角色</span></label>`;return;}
        const key=g.zone+'|'+r;
        const checked=extraSet.has(key)?'checked':'';
        bodyHtml+=`<label style="display:flex;align-items:center;gap:6px;padding:6px 14px;border:1px solid var(--border);border-radius:6px;cursor:pointer;font-size:13px;transition:all .2s" onmouseover="this.style.borderColor='var(--cyan)'" onmouseout="this.style.borderColor='var(--border)'">
          <input type="checkbox" class="role-cb" data-zone="${esc(g.zone)}" data-role="${esc(r)}" ${checked}> ${esc(r)}</label>`;
      });
      bodyHtml+='</div></div>';
    });
    openModal('赋予角色 · '+d.name+'（'+d.user_zone_name+' · '+d.primary_role+'）',bodyHtml,
      `<button class="btn btn-ghost" onclick="closeModal()">取消</button><button class="btn btn-primary" onclick="saveUserRoles(${uid})">保存</button>`);
  }catch(e){toast(e.message,'error');}
}

async function saveUserRoles(uid){
  const roles=[...document.querySelectorAll('.role-cb:checked')].map(cb=>({role_name:cb.dataset.role,zone:cb.dataset.zone}));
  try{
    await api('/api/admin/user-roles/'+uid,{method:'PUT',body:{roles}});
    toast('角色已更新','success'); closeModal();
  }catch(e){toast(e.message,'error');}
}

/* ====== 权限分配 ====== */
let ACCESS_STATE={role_id:'',battles:[],warzones:[],granted:new Set(),roles:[],roles_grouped:[]};

function buildRoleSelect(grouped,q){
  let opts='<option value="">— 选择角色 —</option>';
  grouped.forEach(g=>{
    const filtered=q?g.roles.filter(r=>r.toLowerCase().includes(q.toLowerCase())):g.roles;
    if(!filtered.length)return;
    opts+=`<optgroup label="${esc(g.zone_name)}">`;
    filtered.forEach(r=>{opts+=`<option value="${esc(r)}">${esc(r)}</option>`;});
    opts+='</optgroup>';
  });
  return opts;
}

async function loadAccess(){
  const el=document.getElementById('tab-access');
  el.innerHTML='<div class="loading">加载中...</div>';
  try{
    const data=await api('/api/admin/access');
    ACCESS_STATE.battles=data.battles; ACCESS_STATE.warzones=data.warzones; ACCESS_STATE.roles=data.roles;
    ACCESS_STATE.all_roles=data.roles; ACCESS_STATE.roles_grouped=data.roles_grouped||[];
    el.innerHTML=`
      <div class="panel-title">角色权限分配</div>
      <div class="toolbar" style="gap:10px;flex-wrap:wrap">
        <div class="search-box" style="flex:1;min-width:200px">
          <input type="text" id="accessSearch" placeholder="搜索角色..." oninput="filterRoles2(this.value)" style="width:100%;background:rgba(0,0,0,.25);border:1px solid var(--border);border-radius:6px;color:#fff;padding:6px 12px;font-size:13px">
        </div>
      </div>
      <div id="accessRoleList" style="margin-top:10px;max-height:240px;overflow-y:auto;border:1px solid var(--border);border-radius:8px;padding:4px"></div>
      <div id="accessBox" style="margin-top:12px"><div class="empty">选择角色后显示权限矩阵</div></div>`;
    renderRoleList('');
    if(ACCESS_STATE.role_id) selectRole(ACCESS_STATE.role_id);
  }catch(e){ el.innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>'; }
}

function renderRoleList(q){
  const el=document.getElementById('accessRoleList');
  const grouped=ACCESS_STATE.roles_grouped;
  let h='';
  grouped.forEach(g=>{
    const roles=q?g.roles.filter(r=>r.toLowerCase().includes(q.toLowerCase())):g.roles;
    if(!roles.length)return;
    h+=`<div style="font-size:11px;font-weight:700;color:var(--cyan);padding:6px 8px 2px;letter-spacing:1px">${esc(g.zone_name)}</div>`;
    const cols=Math.min(roles.length,4);
    h+=`<div style="display:grid;grid-template-columns:repeat(${cols},1fr);gap:2px;padding:0 4px 6px">`;
    roles.forEach(r=>{
      const sel=r===ACCESS_STATE.role_id?'role-tag-selected':'';
      h+=`<div class="role-tag ${sel}" onclick="selectRole2('${esc(r)}')">${esc(r)}</div>`;
    });
    h+=`</div>`;
  });
  el.innerHTML=h||'<div style="padding:20px;text-align:center;color:var(--text-dim)">无匹配角色</div>';
}

function filterRoles2(q){
  renderRoleList(q);
}

function selectRole2(roleId){
  /* 高亮更新 */
  document.querySelectorAll('.role-tag').forEach(el=>el.classList.remove('role-tag-selected'));
  document.querySelectorAll('.role-tag').forEach(el=>{if(el.textContent===roleId)el.classList.add('role-tag-selected');});
  selectRole(roleId);
}

async function selectRole(roleId){
  ACCESS_STATE.role_id=roleId;
  const box=document.getElementById('accessBox');
  if(!roleId){ box.innerHTML='<div class="empty">请先选择一个岗位</div>'; return; }
  box.innerHTML='<div class="loading">加载权限...</div>';
  try{
    const d=await api('/api/admin/access?role_id='+encodeURIComponent(roleId));
    ACCESS_STATE.granted=new Set((d.granted||[]).map(g=>g[0]+'|'+g[1]));
    renderMatrix();
  }catch(e){ box.innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>'; }
}

function renderMatrix(){
  const box=document.getElementById('accessBox');
  const bs=ACCESS_STATE.battles, ws=ACCESS_STATE.warzones;
  let html=`<div class="access-grid">
    <table class="access-matrix">
      <thead><tr><th class="row-h">战役 \\ 战区</th>${ws.map(w=>`<th style="color:${mapColor(w.color)}">${esc(w.name)}</th>`).join('')}</tr></thead>
      <tbody>
        ${bs.map(b=>`<tr><th class="row-h" style="color:${mapColor(b.color)}">${esc(b.name)}</th>
          ${ws.map(w=>{const k=b.id+'|'+w.id;return `<td class="cell${ACCESS_STATE.granted.has(k)?' checked':''}" onclick="toggleCell('${b.id}','${w.id}')"></td>`;}).join('')}
        </tr>`).join('')}
      </tbody>
    </table>
    <div style="margin-top:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <span style="font-size:11px;color:var(--text-dim)">共 ${ACCESS_STATE.granted.size} 个授权</span>
      <button class="btn btn-ghost btn-sm" onclick="toggleAll(true)">全选</button>
      <button class="btn btn-ghost btn-sm" onclick="toggleAll(false)">全不选</button>
      <div style="flex:1"></div>
      <button class="btn btn-primary" onclick="saveAccess()">保存权限</button>
    </div>
  </div>`;
  box.innerHTML=html;
}

function toggleCell(bid,wid){
  const k=bid+'|'+wid;
  if(ACCESS_STATE.granted.has(k)) ACCESS_STATE.granted.delete(k); else ACCESS_STATE.granted.add(k);
  const cells=document.querySelectorAll('#accessBox .cell');
  const bs=ACCESS_STATE.battles, ws=ACCESS_STATE.warzones;
  cells.forEach((c,i)=>{
    const b=Math.floor(i/ws.length), w=i%ws.length;
    const key=bs[b].id+'|'+ws[w].id;
    c.classList.toggle('checked', ACCESS_STATE.granted.has(key));
  });
  const cnt=document.querySelector('#accessBox span');
  if(cnt) cnt.textContent='共 '+ACCESS_STATE.granted.size+' 个授权';
}

function toggleAll(on){
  if(on){
    ACCESS_STATE.battles.forEach(b=>ACCESS_STATE.warzones.forEach(w=>ACCESS_STATE.granted.add(b.id+'|'+w.id)));
  }else{ ACCESS_STATE.granted.clear(); }
  renderMatrix();
}

async function saveAccess(){
  if(!ACCESS_STATE.role_id){toast('请先选择岗位','error');return;}
  const grants=[...ACCESS_STATE.granted].map(k=>{const[b,w]=k.split('|');return{battle_id:b,warzone_id:w};});
  try{
    await api('/api/admin/access',{method:'PUT',body:{role_id:ACCESS_STATE.role_id,grants}});
    toast('权限已保存（'+grants.length+' 条）','success');
  }catch(e){toast(e.message,'error');}
}

/* ====== 内容编辑 ====== */
let CONTENT_STATE={battle_id:'',zone_id:''};

async function loadContent(){
  const el=document.getElementById('tab-content');
  if(!RECORD_SCHEMA){
    try{ RECORD_SCHEMA=await api('/api/admin/record-schema'); }
    catch(e){ el.innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>'; return; }
  }
  el.innerHTML=`
    <div class="panel-title">内容编辑 <span class="count" id="recCount"></span></div>
    <div class="toolbar">
      <select id="fltBattle" class="toolbar-select">
        <option value="">全部战役</option>
        ${RECORD_SCHEMA.battles.map(b=>`<option value="${b.id}"${CONTENT_STATE.battle_id===b.id?' selected':''}>${esc(b.name)}</option>`).join('')}
      </select>
      <select id="fltZone" class="toolbar-select">
        <option value="">全部战区</option>
        ${RECORD_SCHEMA.warzones.map(w=>`<option value="${w.id}"${CONTENT_STATE.zone_id===w.id?' selected':''}>${esc(w.name)}</option>`).join('')}
      </select>
      <button class="btn btn-primary" onclick="fetchRecords()">筛选</button>
      <button class="btn btn-ghost" onclick="openRecordEdit(null)">+ 新增记录</button>
    </div>
    <div id="recordList"><div class="loading">加载中...</div></div>`;
  document.getElementById('fltBattle').addEventListener('change',()=>{CONTENT_STATE.battle_id=document.getElementById('fltBattle').value;});
  document.getElementById('fltZone').addEventListener('change',()=>{CONTENT_STATE.zone_id=document.getElementById('fltZone').value;});
  fetchRecords();
}

async function fetchRecords(){
  const p=new URLSearchParams();
  if(CONTENT_STATE.battle_id)p.set('battle_id',CONTENT_STATE.battle_id);
  if(CONTENT_STATE.zone_id)p.set('zone_id',CONTENT_STATE.zone_id);
  try{
    const d=await api('/api/admin/records?'+p.toString());
    document.getElementById('recCount').textContent='共 '+d.total+' 条';
    const el=document.getElementById('recordList');
    if(!d.records.length){ el.innerHTML='<div class="empty">无记录，点击"新增记录"添加</div>'; return; }
    const showFields=['battle_name','warzone_name','path_no','path_name','scene_no','scene_title','guide_role','combat_role'];
    el.innerHTML=`
      <div class="table-scroll">
        <table class="data-table">
          <thead><tr>
            <th>ID</th>${showFields.map(k=>{const f=RECORD_SCHEMA.fields.find(x=>x.key===k);return '<th>'+(f?f.label:k)+'</th>';}).join('')}<th>操作</th>
          </tr></thead>
          <tbody>${d.records.map(r=>`
            <tr>
              <td style="color:var(--text-dim);font-size:11px">${r.id}</td>
              ${showFields.map(k=>{
                const v=String(r[k]||'').trim();
                const short=v.length>28?v.slice(0,28)+'...':v;
                return '<td title="'+esc(v)+'" style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(short?esc(short):'<span style="color:var(--text-dim)">—</span>')+'</td>';
              }).join('')}
              <td style="white-space:nowrap">
                <button class="btn btn-ghost btn-sm" onclick="openRecordEdit(${r.id})">编辑</button>
                <button class="btn btn-danger btn-sm" onclick="delRecord(${r.id})">删除</button>
              </td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
  }catch(e){ document.getElementById('recordList').innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>'; }
}

async function openRecordEdit(rid){
  let rec={};
  if(rid){
    const d=await api('/api/admin/records');
    rec=d.records.find(r=>r.id===rid)||{};
  }
  const fs=RECORD_SCHEMA.fields;
  const zs=RECORD_SCHEMA.warzones;
  const formHTML=`<div class="form-grid">${fs.map(f=>{
    const val=rec[f.key]??'';
    if(f.type==='select_warzone'){
      return `<div class="form-field full"><label>${esc(f.label)}</label><select id="rf_${f.key}"><option value="">— 请选择 —</option>${zs.map(z=>`<option value="${esc(z.name)}" ${val===z.name?'selected':''}>${esc(z.name)}</option>`).join('')}</select></div>`;
    }
    if(f.type==='textarea'){
      return `<div class="form-field full"><label>${esc(f.label)}</label><textarea id="rf_${f.key}">${esc(val)}</textarea></div>`;
    }
    return `<div class="form-field"><label>${esc(f.label)}</label><input id="rf_${f.key}" value="${esc(val)}"></div>`;
  }).join('')}</div>`;
  openModal(rid?'编辑记录 #'+rid:'新增记录', formHTML,
    `<button class="btn btn-ghost" onclick="closeModal()">取消</button><button class="btn btn-primary" onclick="saveRecord(${rid||0})">${rid?'保存修改':'创建'}</button>`, true);
}

async function saveRecord(rid){
  const body={};
  RECORD_SCHEMA.fields.forEach(f=>{ body[f.key]=document.getElementById('rf_'+f.key).value.trim(); });
  if(!body.battle_name){toast('战役名称必填','error');return;}
  try{
    if(rid) await api('/api/admin/records/'+rid,{method:'PUT',body});
    else await api('/api/admin/records',{method:'POST',body});
    toast(rid?'已保存':'已创建','success'); closeModal(); fetchRecords();
  }catch(e){toast(e.message,'error');}
}

async function delRecord(rid){
  if(!confirm('确认删除记录 #'+rid+'？此操作不可恢复。'))return;
  try{ await api('/api/admin/records/'+rid,{method:'DELETE'}); toast('已删除','success'); fetchRecords(); }
  catch(e){toast(e.message,'error');}
}

/* 启动 */
loadOverview();
