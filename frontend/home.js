import { $, state, events, api, esc, go, toast, busy } from './core.js';
import { selectMaterial, findMaterial } from './materials.js';
import { clearProgress, progressSaved } from './progress.js';
let recent = [], loading = false, historyError = '', requestVersion = 0;
function availableSessions() {
  return [...state.sessions].filter(([id]) => findMaterial(id)).sort((a,b) => (b[1].updatedAt || 0) - (a[1].updatedAt || 0));
}
export function renderHome() {
  const sessions = availableSessions();
  const unfinished = sessions.filter(([,s]) => s.retry || s.results.length < s.questions.length);
  const answered = sessions.reduce((sum,[,s]) => sum + s.results.filter(result => !result.unconfirmed).length,0);
  $('home-stats').innerHTML =
    '<div class="surface"><span>已收集的资料</span><b>' + state.materials.length + '<small> 份</small></b></div>' +
    '<div class="surface"><span>待完成练习</span><b>' + unfinished.length + '<small> 组</small></b></div>' +
    '<div class="surface"><span>本地保留题组 · 已确认作答</span><b>' + answered + '<small> 题</small></b></div>';
  const preferred = unfinished[0];
  const material = preferred ? findMaterial(preferred[0]) : state.material;
  const current = preferred?.[1];
  $('home-continue').innerHTML = material ?
    '<span class="badge">' + (current ? '练习还在，接着来' : '最近学习的资料') +
    '</span><h2>' + esc(material.title) + '</h2><p>' + (current ? '已提交 ' + current.results.length + ' / ' + current.questions.length + ' 题。无需重新出题，从上次进度继续。' : '从一个问题开始理解，再用几道练习检验自己。') +
    '</p><div class="summary-actions"><button class="primary" data-resume="' + (preferred ? preferred[0] : material.id) + '" data-destination="' + (current ? 'practice' : 'chat') + '">' +
    (current ? '继续上次练习 →' : '继续学习 →') + '</button><button class="quiet" data-page="library">浏览资料库</button></div>' :
    '<h2>今天，种下一个新知识。</h2><p>导入一份资料，把读过的内容变成自己的理解。</p><button class="primary" data-import>导入第一份资料 →</button>';
  $('home-sessions').innerHTML = unfinished.length ? unfinished.map(([id,s]) =>
    '<div class="resume-row"><div><b>' + esc(s.materialTitle) + '</b><p>已提交 ' + s.results.length + ' / ' + s.questions.length +
    ' 题' + (s.uncertain ? ' · 上次提交结果待确认' : '') + '</p><progress value="' + s.results.length + '" max="' + s.questions.length + '" aria-label="' +
    esc(s.materialTitle) + '的练习进度"></progress></div><button class="secondary" data-resume="' + id + '" data-destination="practice">继续 →</button></div>').join('') :
    '<div class="home-empty"><p>没有待完成的练习。选一个知识点，开启下一轮。</p><button class="link-button" data-page="practice">去练习中心 →</button></div>';
  const completed = sessions.filter(([,s]) => !s.retry && s.results.length === s.questions.length).slice(0,3);
  if (completed.length) $('home-sessions').insertAdjacentHTML('beforeend','<h3 class="recent-summary-title">最近保留的总结</h3>' +
    completed.map(([id,s]) => '<button class="recent-summary" data-resume="' + id + '" data-destination="practice" data-summary="true"><span>' +
      esc(s.materialTitle) + '</span><small>查看总结 →</small></button>').join(''));
  $('home-history-status').textContent = loading ? '正在加载最近问答…' : historyError;
  $('home-refresh').disabled = loading;
  const entries = recent.filter(item => findMaterial(item.material_id)).slice(0,4);
  $('home-history').innerHTML = entries.length ? entries.map(item => {
    const material = findMaterial(item.material_id);
    const title = material?.title || '学习资料';
    return '<button class="history-card" data-resume="' + material.id + '" data-destination="chat"><small>' + esc(title) + '</small><b>' +
      esc(item.question) + '</b><p>' + esc(String(item.answer || '').slice(0,90)) + '</p><span>打开该资料问答 →</span></button>';
  }).join('') : '<div class="home-empty"><p>' + (loading ? '你的问题，正在路上。' : historyError ? '暂时无法展示历史，可点击刷新重试。' : '还没有保存的问答，从资料中问出第一个问题吧。') + '</p></div>';
  $('clear-local-progress').disabled = [...state.sessions.values()].some(s => s.pending) || (!state.sessions.size && progressSaved());
}
export async function loadRecentHistory() {
  if (!state.user) return;
  const version = ++requestVersion;
  loading = true; historyError = ''; renderHome();
  try {
    const history = await api('/rag/history');
    if (version !== requestVersion) return;
    recent = Array.isArray(history) ? [...history].sort((a,b) => b.id - a.id) : [];
  } catch (error) {
    if (version === requestVersion && error.name !== 'AbortError') historyError = '历史加载失败，请点击刷新重试。';
  } finally {
    if (version === requestVersion) { loading = false; renderHome(); }
  }
}
export function initHome() {
  $('home-panel').addEventListener('click', async event => {
    const button = event.target.closest('[data-resume]');
    if (!button) return;
    const id = Number(button.dataset.resume);
    if (!findMaterial(id)) return toast('该资料暂时不可用，请刷新资料库',true);
    const epoch = state.epoch;
    busy(button,true,'正在打开…');
    await selectMaterial(id);
    if (epoch === state.epoch && state.material?.id === id) {
      const s = state.sessions.get(id);
      if (button.dataset.summary && s && s.results.length === s.questions.length) s.index = s.questions.length;
      go(button.dataset.destination);
    }
    busy(button,false);
  });
  $('home-refresh').addEventListener('click',loadRecentHistory);
  $('clear-local-progress').addEventListener('click', () => $('clear-progress-dialog').showModal());
  $('confirm-clear-progress').addEventListener('click', () => {
    if ([...state.sessions.values()].some(s => s.pending)) return toast('请等待当前请求完成后再清除',true);
    if (clearProgress()) { $('clear-progress-dialog').close(); toast('本地练习已清除，服务端记录未改动'); }
  });
  ['materials','progress','topics','material'].forEach(name => events.addEventListener(name,renderHome));
  events.addEventListener('page', () => {
    if (!$('home-panel').classList.contains('hidden')) renderHome();
  });
  events.addEventListener('history-updated',loadRecentHistory);
  events.addEventListener('reset', () => { requestVersion++; recent = []; loading = false; historyError = ''; renderHome(); });
  renderHome();
}
