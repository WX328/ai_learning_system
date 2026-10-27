import { $, state, events, api, json, esc, go, toast } from './core.js';

const cache = {stats:null,users:null,audit:null}, versions = {};
let userPage=1, auditPage=1, detailId=null, detailVersion=0, confirmation=null;
const pageSize=10;
const allowed=()=>state.user?.role === 'admin';
const visible=()=>!$('admin-panel').classList.contains('hidden');
const date=value=>value ? new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : value+'Z').toLocaleString('zh-CN') : '历史时间未知';
const roleText=role=>role === 'admin' ? '管理员' : '普通用户';
const activeText=active=>active ? '已启用' : '已停用';
function identity() { $('admin-nav').classList.toggle('hidden',!allowed()); }
function failure(error, epoch) {
  if(epoch!==state.epoch || error.name==='AbortError') return false;
  if(error.status===403) {
    state.user.role='user'; identity(); clear(); go('home'); toast('管理员权限已变化，请重新登录确认',true);
    return false;
  }
  return true;
}
function query(kind) {
  if(kind==='stats') return '/admin/stats';
  if(kind==='audit') return '/admin/audit-logs?page='+auditPage+'&page_size='+pageSize;
  const params = new URLSearchParams({page:String(userPage),page_size:String(pageSize)});
  if($('admin-search').value.trim()) params.set('search',$('admin-search').value.trim());
  if($('admin-role').value) params.set('role',$('admin-role').value);
  if($('admin-active').value) params.set('is_active',$('admin-active').value);
  return '/admin/users?'+params;
}
function pagination(kind,data) {
  const pages=Math.max(1,Math.ceil(data.total/data.page_size));
  $(kind==='users'?'admin-users-pagination':'admin-audit-pagination').innerHTML=
    '<span>共 '+data.total+' 条 · 第 '+data.page+' / '+pages+' 页</span><button class="quiet" data-admin-page="'+kind+'" data-step="-1"'+(data.page<=1?' disabled':'')+'>上一页</button>'+
    '<button class="quiet" data-admin-page="'+kind+'" data-step="1"'+(data.page>=pages?' disabled':'')+'>下一页</button>';
}
function renderStats(data) {
  const metrics=[['用户总数',data.total_users],['已启用账号',data.enabled_users],['近 30 天学习用户',data.active_users_30d],
    ['学习资料',data.material_count],['已生成题目',data.question_count],['首次答题次数',data.answer_count]];
  $('admin-stats').innerHTML=metrics.map(([label,value])=>'<div><span>'+label+'</span><b>'+esc(value)+'</b></div>').join('');
}
function renderUsers(data) {
  $('admin-users').innerHTML=data.items.length ? '<table class="admin-table"><thead><tr><th>用户</th><th>角色与状态</th><th>注册时间</th><th class="admin-number">累计 XP</th><th>操作</th></tr></thead><tbody>'+data.items.map(user=>
    '<tr><td data-label="用户"><b>'+esc(user.username)+'</b><small>#'+user.id+'</small></td><td data-label="角色与状态">'+roleText(user.role)+' · '+activeText(user.is_active)+
    '</td><td data-label="注册时间">'+esc(date(user.created_at))+'</td><td data-label="累计 XP" class="admin-number">'+user.total_xp+'</td><td class="admin-row-actions">'+
    '<button class="quiet" data-admin-detail="'+user.id+'">详情</button><button class="quiet" data-admin-status="'+user.id+'" data-enable="'+!user.is_active+'"'+
    (user.id===state.user.id?' disabled title="不能停用自己"':'')+'>'+ (user.is_active?'停用':'启用') +'</button></td></tr>').join('')+'</tbody></table>' : '<p class="admin-empty">没有符合条件的用户，请调整筛选条件。</p>';
  pagination('users',data);
}
const actions={enable_user:'启用账号',disable_user:'停用账号',bootstrap_admin:'初始化管理员'};
const results={changed:'已变更',unchanged:'状态未变',created:'已创建',denied_self:'拒绝停用自己',denied_last_admin:'拒绝停用最后一个管理员',not_found:'用户不存在'};
function renderAudit(data) {
  $('admin-audit').innerHTML=data.items.length ? '<ol class="admin-audit-list">'+data.items.map(log=>'<li><div><b>'+esc(actions[log.action]||log.action)+'</b><span>'+esc(results[log.result]||log.result)+
    '</span></div><p>操作者 '+esc(log.actor_username||'未知')+' (#'+esc(log.actor_user_id)+') · 目标 '+esc(log.target_username||'未知')+' (#'+esc(log.target_user_id)+')</p><time>'+esc(date(log.created_at))+'</time></li>').join('')+'</ol>' : '<p class="admin-empty">暂无管理操作日志。</p>';
  pagination('audit',data);
}
async function load(kind) {
  if(!allowed()) return;
  const version=versions[kind]=(versions[kind]||0)+1, epoch=state.epoch;
  $('admin-'+kind+'-status').textContent='正在加载…';
  try {
    const data=await api(query(kind));
    if(epoch!==state.epoch || version!==versions[kind] || !allowed()) return;
    if(kind!=='stats' && data.page>Math.max(1,Math.ceil(data.total/data.page_size))) {
      const last=Math.max(1,Math.ceil(data.total/data.page_size));
      if(kind==='users') userPage=last; else auditPage=last;
      void load(kind); return;
    }
    cache[kind]=data;
    if(kind==='stats') renderStats(data); else if(kind==='users') renderUsers(data); else renderAudit(data);
    $('admin-'+kind+'-status').textContent='';
  } catch(error) {
    if(version===versions[kind] && failure(error,epoch)) $('admin-'+kind+'-status').textContent='加载失败：'+error.message+'。请点击刷新重试。';
  }
}
function refresh() { for(const kind of ['stats','users','audit']) void load(kind); }
async function showDetail(id) {
  if(!allowed()) return;
  detailId=Number(id); const version=++detailVersion,epoch=state.epoch;
  $('admin-detail').innerHTML='<p role="status">正在读取用户统计…</p>';
  if(!$('admin-detail-dialog').open) $('admin-detail-dialog').showModal();
  try {
    const data=await api('/admin/users/'+detailId);
    if(epoch!==state.epoch || version!==detailVersion || !allowed()) return;
    const stats=data.statistics;
    const metrics=[['学习资料',stats.material_count],['知识点',stats.topic_count],['已生成题目',stats.question_count],
      ['首次答题',stats.answer_count],['首次正确率',stats.correct_rate===null?'尚无记录':stats.correct_rate+'%'],
      ['错题复习',stats.review_count],['问答次数',stats.qa_count],['教练会话',stats.coach_session_count]];
    $('admin-detail').innerHTML='<h3>'+esc(data.username)+'</h3><p>'+roleText(data.role)+' · '+activeText(data.is_active)+' · #'+data.id+'</p><p>注册时间：'+esc(date(data.created_at))+'</p>'+
      '<p>累计 XP：'+data.total_xp+' · 等级 '+data.level+'</p><dl class="admin-detail-stats">'+metrics.map(([label,value])=>'<div><dt>'+label+'</dt><dd>'+esc(value)+'</dd></div>').join('')+'</dl><p class="muted">仅显示管理所需统计，不提供资料正文或私人对话。</p>';
  } catch(error) {
    if(version===detailVersion && failure(error,epoch)) $('admin-detail').innerHTML='<p role="alert">加载失败：'+esc(error.message)+'</p><button class="secondary" id="admin-detail-retry">重试</button>';
    $('admin-detail-retry')?.addEventListener('click',()=>showDetail(id));
  }
}
function confirmStatus(id,enabled) {
  if(!allowed() || confirmation?.pending) return;
  const user=cache.users?.items.find(item=>item.id===Number(id));
  if(!user || (user.id===state.user.id && !enabled)) return;
  confirmation={id:user.id,enabled,pending:false};
  $('admin-confirm-text').textContent=(enabled?'启用':'停用')+'用户「'+user.username+'」？'+(enabled?'启用后用户需要重新登录。':'停用后，该账号的登录和旧登录凭证将失效。学习数据会保留。');
  $('admin-confirm-error').textContent='';
  $('admin-confirm-submit').disabled=false; $('admin-confirm-submit').textContent='确认'+(enabled?'启用':'停用');
  $('admin-confirm-cancel').disabled=false;
  $('admin-confirm-dialog').showModal();
}
async function submitStatus(event) {
  event.preventDefault();
  const current=confirmation,epoch=state.epoch;
  if(!allowed() || !current || current.pending) return;
  current.pending=true; $('admin-confirm-submit').disabled=true; $('admin-confirm-cancel').disabled=true;
  $('admin-confirm-error').textContent=''; $('admin-confirm-submit').textContent='正在保存…';
  try {
    await api('/admin/users/'+current.id+'/status',{method:'PATCH',...json({is_active:current.enabled})});
    if(epoch!==state.epoch || confirmation!==current) return;
    $('admin-confirm-dialog').close(); toast('账号状态已更新'); refresh();
    if(detailId===current.id && $('admin-detail-dialog').open) void showDetail(detailId);
  } catch(error) {
    if(confirmation===current && failure(error,epoch)) $('admin-confirm-error').textContent='操作未确认：'+error.message+'。可刷新用户列表核对后重试。';
  } finally {
    if(epoch===state.epoch && confirmation===current) {
      current.pending=false; $('admin-confirm-submit').disabled=false; $('admin-confirm-cancel').disabled=false;
      $('admin-confirm-submit').textContent='重试保存';
    }
  }
}
function clear() {
  for(const kind of ['stats','users','audit']) {
    cache[kind]=null; versions[kind]=(versions[kind]||0)+1;
    $('admin-'+kind).innerHTML=''; $('admin-'+kind+'-status').textContent='';
  }
  detailVersion++; detailId=null; confirmation=null; userPage=1; auditPage=1;
  for(const id of ['admin-detail-dialog','admin-confirm-dialog']) if($(id).open) $(id).close();
  for(const id of ['admin-detail','admin-users-pagination','admin-audit-pagination']) $(id).innerHTML='';
  for(const id of ['admin-search','admin-role','admin-active']) $(id).value='';
}
export function initAdmin() {
  $('admin-refresh').addEventListener('click',refresh);
  $('admin-audit-refresh').addEventListener('click',()=>load('audit'));
  $('admin-filter-form').addEventListener('submit',event=>{event.preventDefault();userPage=1;void load('users');});
  for(const id of ['admin-role','admin-active']) $(id).addEventListener('change',()=>{userPage=1;void load('users');});
  $('admin-confirm-form').addEventListener('submit',submitStatus);
  $('admin-confirm-cancel').addEventListener('click',()=>{if(!confirmation?.pending) $('admin-confirm-dialog').close();});
  $('admin-confirm-dialog').addEventListener('cancel',event=>{if(confirmation?.pending) event.preventDefault();});
  $('admin-confirm-dialog').addEventListener('close',()=>{confirmation=null;});
  $('admin-detail-close').addEventListener('click',()=>$('admin-detail-dialog').close());
  $('admin-detail-dialog').addEventListener('close',()=>{detailId=null;detailVersion++;$('admin-detail').innerHTML='';});
  document.addEventListener('click',event=>{
    const detail=event.target.closest('[data-admin-detail]'); if(detail) void showDetail(detail.dataset.adminDetail);
    const status=event.target.closest('[data-admin-status]'); if(status && !status.disabled) confirmStatus(status.dataset.adminStatus,status.dataset.enable==='true');
    const page=event.target.closest('[data-admin-page]');
    if(page && !page.disabled && allowed()) {
      if(page.dataset.adminPage==='users') {userPage+=Number(page.dataset.step);void load('users');}
      else {auditPage+=Number(page.dataset.step);void load('audit');}
    }
  });
  events.addEventListener('identity',identity);
  events.addEventListener('page',()=>{identity();if(visible() && allowed()) refresh();});
  events.addEventListener('reset',()=>{clear();identity();});
  identity();
}
