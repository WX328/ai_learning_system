import { $, state, events, api, json, esc, report, emit } from './core.js';

let session = null, pending = null, working = false, loadVersion = 0;
const key = () => 'coach_pending_' + state.user?.id;
const activeKey = () => 'coach_active_' + state.user?.id;
const label = s => ({active:'进行中',waiting_answer:'待作答',completed:'已结束'}[s] || s);

function rememberPending(value) {
  pending = value;
  try {
    if (value) localStorage.setItem(key(), JSON.stringify(value));
    else localStorage.removeItem(key());
  } catch { /* Server receipts still protect retries in this page. */ }
}

function materials() {
  const selected = $('coach-material').value || String(state.material?.id || '');
  $('coach-material').innerHTML = '<option value="">请选择资料</option>' +
    state.materials.map(m => '<option value="' + m.id + '">' + esc(m.title) + '</option>').join('');
  $('coach-material').value = selected;
}

function render() {
  const blocked = working || !!pending || !!session?.busy;
  $('coach-create-fields').disabled = blocked;
  $('coach-history').disabled = blocked;
  $('coach-retry-request').classList.toggle('hidden', !pending);
  $('coach-retry-request').disabled = working;
  $('coach-refresh').disabled = working;
  $('coach-status').textContent = working ? '正在处理，学习进度会自动保存…' :
    pending ? '上次请求结果尚未确认，请重试原请求或刷新会话。' :
    session?.busy ? '会话仍在处理，请稍后刷新。' : '';
  $('coach-session').classList.toggle('hidden', !session);
  if (!session) return;
  const s = session.state, finished = session.status === 'completed';
  $('coach-session-title').textContent = session.goal;
  $('coach-session-meta').textContent = label(session.status) + ' · 计划 ' + session.minutes +
    ' 分钟 · 已练 ' + s.completed.length + ' / ' + s.target_questions + ' 题';
  $('coach-plan').innerHTML = s.plan.map(p => '<li>' + esc(p.title) + ' · ' + p.minutes + ' 分钟</li>').join('');
  $('coach-topics').innerHTML = s.suggested_topics.length ? '<p>建议关注：' +
    s.suggested_topics.map(t => esc(t.name) + (t.mastery === null ? '（未练习）' : '（规则掌握度 ' + esc(t.mastery) + '/100' + (t.sample_limited ? '，初步评估' : '') + '）')).join('、') + '</p>' +
    s.suggested_topics.filter(t => t.mastery_reason).map(t => '<details><summary>' + esc(t.name) + ' · 评估依据</summary><p>' + esc(t.mastery_reason) + '</p></details>').join('') :
    '暂无知识点记录，将围绕学习目标检索资料。';
  $('coach-messages').innerHTML = session.messages.map(m => '<article class="coach-message ' +
    (m.role === 'user' ? 'coach-user' : '') + '"><b>' + (m.role === 'user' ? '你' : '学习教练') +
    '</b><p>' + esc(m.content) + '</p>' + (m.sources?.length ? '<details><summary>查看资料依据</summary>' +
    m.sources.map(source => '<blockquote>[' + esc(source.id) + '] ' + esc(source.text) + '</blockquote>').join('') +
    '</details>' : '') + '</article>').join('');
  $('coach-messages').scrollTop = $('coach-messages').scrollHeight;
  const q = session.question;
  $('coach-question').innerHTML = q ? '<form id="coach-answer-form"><fieldset id="coach-answer-fields"' +
    (blocked ? ' disabled' : '') + '><legend>当前练习 · 难度 ' + q.difficulty + '</legend><h3>' +
    esc(q.question) + '</h3>' + ['A','B','C','D'].map(k =>
      '<label class="option"><input type="radio" name="answer" value="' + k + '" required> ' +
      k + ' · ' + esc(q['option_' + k.toLowerCase()]) + '</label>').join('') +
    '<button class="primary" type="submit">提交答案</button></fieldset></form>' : '';
  $('coach-answer-form')?.addEventListener('submit', event => {
    event.preventDefault();
    const answer = new FormData(event.currentTarget).get('answer');
    if (answer) send('answer', {answer});
  });
  const last = s.completed.at(-1);
  $('coach-result').innerHTML = last ? '<details open><summary>最近一次作答：' +
    (last.is_correct ? '回答正确' : '需要巩固') + '</summary><p>你的选择：' + esc(last.user_answer) +
    ' · 正确答案：' + esc(last.correct_answer) + '</p><p>' + esc(last.explanation) + '</p></details>' : '';
  $('coach-message-fields').disabled = blocked || finished || !!q;
  $('coach-continue').disabled = blocked || finished || !!q;
  $('coach-finish').disabled = blocked || finished;
  $('coach-retry-model').classList.toggle('hidden', !s.degraded || finished);
  $('coach-retry-model').disabled = blocked;
  $('coach-wait-note').textContent = q ? '请先完成这道练习，教练会根据作答继续辅导。' :
    finished ? '本次学习已结束，可以创建新的学习会话。' : '';
}

async function history() {
  const rows = await api('/coach/sessions');
  $('coach-history').innerHTML = '<option value="">选择历史会话</option>' + rows.map(s =>
    '<option value="' + esc(s.id) + '">' + esc(s.goal) + ' · ' + label(s.status) + '</option>').join('');
  if (session) $('coach-history').value = session.id;
  return rows;
}

function accept(data) {
  session = data;
  $('coach-history').value = session.id;
  try { localStorage.setItem(activeKey(), session.id); } catch { /* Optional convenience. */ }
  render();
}

async function execute(request) {
  if (working) return;
  working = true;
  const epoch = state.epoch;
  rememberPending(request);
  render();
  try {
    const data = await api(request.path, {method:'POST', ...json(request.body)});
    rememberPending(null);
    accept(data);
    if (request.body.action === 'message') $('coach-input').value = '';
    if (request.body.action === 'answer') emit('study-updated');
    await history();
  } catch (error) {
    if (epoch !== state.epoch) return;
    // Validation failures are definitive; network/server errors retain the same request ID.
    if (error.status && error.status < 500 && error.status !== 409) rememberPending(null);
    if (error.status === 409 && session) {
      try {
        accept(await api('/coach/sessions/' + session.id));
        if (!session.busy) rememberPending(null);
      } catch { /* Keep request for explicit retry. */ }
    }
    report(error);
  } finally {
    if (epoch === state.epoch) { working = false; render(); }
  }
}

function send(action, extra = {}) {
  if (!session || working || pending || session.busy) return;
  execute({path:'/coach/sessions/' + session.id + '/turns',
    body:{request_id:crypto.randomUUID(), revision:session.revision, action, ...extra}});
}

async function reload() {
  if (!state.user || working) return;
  const version = ++loadVersion;
  try {
    try { pending = JSON.parse(localStorage.getItem(key()) || 'null'); } catch { pending = null; }
    const rows = await history();
    if (version !== loadVersion) return;
    const pendingId = pending?.path === '/coach/sessions' ? pending.body.request_id :
      pending?.path.split('/')[3];
    const id = pendingId || session?.id || localStorage.getItem(activeKey()) || rows[0]?.id;
    if (id) {
      try {
        const data = await api('/coach/sessions/' + id);
        if (version === loadVersion) accept(data);
      } catch (error) {
        if (error.status !== 404) throw error;
        session = null;
        if (pending?.path !== '/coach/sessions') rememberPending(null);
      }
    }
    materials(); render();
  } catch (error) { report(error); }
}

export function initCoach() {
  $('coach-create').addEventListener('submit', event => {
    event.preventDefault();
    if (working || pending || session?.busy) return;
    const material_id = Number($('coach-material').value);
    const goal = $('coach-goal').value.trim();
    if (!material_id || !goal) return;
    execute({path:'/coach/sessions', body:{request_id:crypto.randomUUID(), material_id,
      goal, minutes:Number($('coach-minutes').value)}});
  });
  $('coach-form').addEventListener('submit', event => {
    event.preventDefault();
    const message = $('coach-input').value.trim();
    if (message) send('message', {message});
  });
  $('coach-continue').addEventListener('click', () => send('message',
    {message:session?.revision ? '请根据我的学习目标和最近作答，继续讲解或安排下一道练习。' : '请围绕我的学习目标开始辅导：' + session?.goal}));
  $('coach-finish').addEventListener('click', () => send('finish'));
  $('coach-retry-model').addEventListener('click', () => {
    const previous = session?.messages.filter(m => m.role === 'user').at(-1)?.content;
    send('message', {message:previous || '请继续辅导'});
  });
  $('coach-retry-request').addEventListener('click', () => { if (pending) execute(pending); });
  $('coach-refresh').addEventListener('click', reload);
  $('coach-history').addEventListener('change', async event => {
    const id = event.target.value;
    if (!id || working || pending) return;
    const version = ++loadVersion;
    try {
      const data = await api('/coach/sessions/' + id);
      if (version === loadVersion) accept(data);
    } catch (error) { report(error); }
  });
  events.addEventListener('materials', materials);
  events.addEventListener('page', () => {
    if (!$('coach-panel').classList.contains('hidden')) reload();
  });
  events.addEventListener('reset', () => {
    loadVersion++; session = null; pending = null; working = false;
    $('coach-messages').innerHTML = ''; $('coach-question').innerHTML = '';
    $('coach-create').reset(); $('coach-form').reset(); $('coach-history').innerHTML = '';
    render();
  });
}
