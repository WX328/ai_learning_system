export const $ = id => document.getElementById(id);
export const state = {
  token: localStorage.getItem('learning_token'), user: null, epoch: 0,
  materials: [], material: null, topics: [], topicId: null, selecting: false,
  sessions: new Map(), conversations: new Map(), controllers: new Set(),
};
export const events = new EventTarget();
export const emit = name => events.dispatchEvent(new Event(name));
export const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({
  '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;',
}[c]));
export const json = data => ({headers: {'Content-Type':'application/json'}, body:JSON.stringify(data)});
let toastTimer;
export function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').className = 'toast' + (error ? ' error-toast' : '');
  toastTimer = setTimeout(() => $('toast').classList.add('hidden'), 4500);
}
export function busy(button, on, text = '处理中…') {
  if (!button) return;
  if (on) { button.dataset.label = button.textContent; button.textContent = text; }
  else if (button.dataset.label) { button.textContent = button.dataset.label; delete button.dataset.label; }
  button.disabled = on;
}
export function report(error) {
  if (error.name !== 'AbortError') toast(error.message || '操作失败，请重试', true);
}
function detailText(detail) {
  if (Array.isArray(detail)) return detail.map(item => item.msg || String(item)).join('；');
  if (detail && typeof detail === 'object') return detail.msg || JSON.stringify(detail);
  return detail;
}
export async function api(path, options = {}) {
  const epoch = state.epoch;
  const controller = new AbortController();
  state.controllers.add(controller);
  const headers = {...options.headers};
  if (state.token) headers.Authorization = 'Bearer ' + state.token;
  try {
    const response = await fetch(path, {...options, headers, signal:controller.signal});
    let data = null;
    try { data = await response.json(); } catch { /* Some errors have no JSON body. */ }
    if (epoch !== state.epoch) throw new DOMException('会话已切换', 'AbortError');
    $('api-status').textContent = '● 服务可访问';
    if (!response.ok) {
      const error = new Error(detailText(data?.detail) || '请求失败（' + response.status + '）');
      error.status = response.status;
      if (response.status === 401 && state.token && path !== '/auth/login') {
        resetSession();
        emit('expired');
      }
      throw error;
    }
    return data;
  } catch (error) {
    if (error instanceof TypeError && epoch === state.epoch) {
      $('api-status').textContent = '○ 连接失败，请检查服务';
      throw new Error('无法连接服务，请确认 FastAPI 已启动后重试');
    }
    throw error;
  } finally {
    state.controllers.delete(controller);
  }
}
export function resetSession() {
  state.epoch++;
  state.controllers.forEach(controller => controller.abort());
  state.controllers.clear();
  state.token = null; state.user = null; state.material = null;
  state.materials = []; state.topics = []; state.topicId = null; state.selecting = false;
  state.sessions.clear(); state.conversations.clear();
  localStorage.removeItem('learning_token');
  emit('reset');
}
export function go(page) {
  if (!['home','library','chat','coach','practice','mistakes','records','map','admin'].includes(page)) return;
  if (page === 'admin' && state.user?.role !== 'admin') return;
  document.querySelectorAll('.panel').forEach(panel => panel.classList.toggle('hidden', panel.id !== page + '-panel'));
  document.querySelectorAll('.nav-item').forEach(button => {
    button.classList.toggle('active', button.dataset.page === page);
    if (button.dataset.page === page) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  $('page-label').textContent = {home:'学习首页',library:'资料库',chat:'AI 问答',coach:'学习教练',practice:'练习中心',mistakes:'错题本',records:'学习记录',map:'知识地图',admin:'管理后台'}[page];
  emit('page');
}
export function requireMaterial() {
  if (!state.material || state.selecting) {
    toast(state.selecting ? '正在加载资料，请稍候' : '请先在资料库中选择一份资料', true);
    return false;
  }
  return true;
}
export function setTopic(id) {
  state.topicId = state.topics.some(topic => topic.id === Number(id)) ? Number(id) : null;
  emit('topic');
}
