import { $, state, events, emit, api, json, esc, go, setTopic, report } from './core.js';
import { selectMaterial, loadMaterials } from './materials.js';

const cache = {summary:null, mistakes:null, records:null, map:null};
const versions = {}, pending = {};
let mistakePage = 1, recordPage = 1, selectedNode = null, reviewing = null;
const pageSize = 8;
const dateFormat = new Intl.DateTimeFormat('zh-CN', {dateStyle:'medium',timeStyle:'short'});
const dateText = value => { const date = new Date(value); return Number.isNaN(date.valueOf()) ? '时间未知' : dateFormat.format(date); };
const localDate = value => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '' : [date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-');
};
const empty = (title, text, page = 'practice') => '<div class="study-empty"><span aria-hidden="true">◇</span><h3>' + esc(title) + '</h3><p>' + esc(text) + '</p><button class="secondary" data-page="' + page + '">' + (page === 'library' ? '去资料库' : '去练习中心') + ' →</button></div>';
function options(id, items, placeholder) {
  const previous = $(id).value;
  $(id).innerHTML = '<option value="">' + placeholder + '</option>' + items.map(item => '<option value="' + item.id + '">' + esc(item.title) + ' · #' + item.id + '</option>').join('');
  if (items.some(item => String(item.id) === previous)) $(id).value = previous;
}
function activePage() { return document.querySelector('.nav-item.active')?.dataset.page; }
function status(key, text) { if ($(key + '-status')) $(key + '-status').textContent = text; }
async function load(key, force = false) {
  if (!state.user || pending[key] || (!force && cache[key] !== null)) return;
  const version = versions[key] = (versions[key] || 0) + 1, epoch = state.epoch;
  pending[key] = true;
  status(key, '正在加载…');
  document.querySelectorAll('[data-study-refresh="' + key + '"]').forEach(button => button.disabled = true);
  if (key === 'summary' && !cache.summary) $('growth-card').innerHTML = '<p class="muted" role="status">正在加载等级与学习统计…</p>';
  try {
    const data = await api('/study/' + key);
    if (epoch !== state.epoch || version !== versions[key]) return;
    cache[key] = data;
    status(key, '');
    if (key === 'summary') renderGrowth();
    if (key === 'mistakes') {
      options('mistake-material', [...new Map(data.map(item => [item.material_id,{id:item.material_id,title:item.material_title}])).values()], '全部资料');
      renderMistakes();
    }
    if (key === 'records') renderRecords();
    if (key === 'map') {
      options('map-material',data,'请选择资料');
      if (!$('map-material').value && data.length) $('map-material').value = String(data.find(item => item.id === state.material?.id)?.id || data[0].id);
      renderMap();
    }
  } catch (error) {
    if (error.name !== 'AbortError' && epoch === state.epoch && version === versions[key]) {
      const message = '加载失败：' + error.message + '。请点击刷新重试。';
      status(key,message);
      if (key === 'summary') $('growth-card').innerHTML = '<p role="alert">' + esc(message) + '</p><button class="secondary" data-study-refresh="summary">刷新统计</button>';
    }
  } finally {
    if (epoch === state.epoch && version === versions[key]) {
      pending[key] = false;
      document.querySelectorAll('[data-study-refresh="' + key + '"]').forEach(button => button.disabled = false);
    }
  }
}
function invalidate() {
  Object.keys(cache).forEach(key => { cache[key] = null; versions[key] = (versions[key] || 0) + 1; pending[key] = false; });
  load('summary');
  const page = activePage();
  if (['mistakes','records','map'].includes(page)) load(page);
}
function renderGrowth() {
  const info = cache.summary;
  if (!info) return;
  $('account-level').textContent = 'Lv.' + info.level + ' · ' + info.total_xp + ' XP';
  $('account-level').classList.remove('hidden');
  $('mistake-nav-count').textContent = info.pending_mistakes || '';
  $('growth-card').innerHTML = '<div class="growth-level"><div class="level-emblem" aria-label="等级 ' + info.level + '"><small>等级</small><b>' + info.level + '</b></div><div class="growth-progress"><p class="context-label">每一次理解，都在积累</p><h2>' + info.total_xp.toLocaleString() + ' <small>累计 XP</small></h2><progress value="' + info.level_progress + '" max="100" aria-label="当前等级进度"></progress><p>' + (info.next_level_xp === null ? '已达到当前最高等级，继续积累知识。' : '再获得 ' + info.xp_remaining + ' XP，升至 Lv.' + (info.level + 1)) + '</p></div></div>' +
    '<div class="growth-metrics"><div><b>' + info.answered_count + '</b><span>首次作答题数</span></div><div><b>' + (info.correct_rate === null ? '—' : info.correct_rate + '%') + '</b><span>首次作答正确率</span></div><button data-page="mistakes"><b>' + info.pending_mistakes + '</b><span>待巩固错题 ↗</span></button></div><button class="growth-refresh" data-study-refresh="summary" aria-label="刷新等级与统计">↻</button>';
}
function filteredMistakes() {
  const query = $('mistake-search').value.trim().toLocaleLowerCase(), material = $('mistake-material').value, filter = $('mistake-status').value;
  return (cache.mistakes || []).filter(item => (!material || item.material_id === Number(material)) &&
    (filter === 'all' || (filter === 'resolved' ? item.resolved : !item.resolved)) &&
    (!query || (item.question + item.topic_name + item.material_title).toLocaleLowerCase().includes(query)));
}
function pagination(id, page, total, kind) {
  const pages = Math.max(1,Math.ceil(total/pageSize));
  $(id).innerHTML = '<span>共 ' + total + ' 条 · 第 ' + page + ' / ' + pages + ' 页</span><div><button class="quiet" data-paginate="' + kind + '" data-step="-1"' + (page <= 1 ? ' disabled' : '') + '>上一页</button><button class="quiet" data-paginate="' + kind + '" data-step="1"' + (page >= pages ? ' disabled' : '') + '>下一页</button></div>';
}
function renderMistakes() {
  const all = cache.mistakes || [], rows = filteredMistakes(), resolved = all.filter(item => item.resolved).length;
  $('mistake-stats').innerHTML = '<div class="surface"><span>累计错题</span><b>' + all.length + '</b></div><div class="surface"><span>待巩固</span><b>' + (all.length-resolved) + '</b></div><div class="surface"><span>最近重练答对</span><b>' + resolved + '</b></div>';
  mistakePage = Math.max(1,Math.min(mistakePage,Math.ceil(rows.length/pageSize)));
  $('mistake-list').innerHTML = rows.length ? rows.slice((mistakePage-1)*pageSize,mistakePage*pageSize).map(item =>
    '<article class="surface mistake-card"><div class="study-card-meta"><span class="status-pill ' + (item.resolved ? 'strong' : 'weak') + '">' + (item.resolved ? '重练答对' : '待巩固') + '</span><span>' + esc(item.topic_name) + ' · 难度 ' + item.difficulty + '</span><time>' + esc(dateText(item.created_at)) + '</time></div><h2>' + esc(item.question) + '</h2><p class="muted">' + esc(item.material_title) + ' · #' + item.material_id + '</p><div class="mistake-actions"><span>已复习 ' + item.review_count + ' 次</span><button class="secondary" data-review="' + item.id + '">重新练习 →</button></div><details class="mistake-details"><summary>查看原答题与解析</summary><div class="review-options">' + Object.entries(item.options).filter(([,text]) => text != null).map(([key,text]) => '<p><b>' + key + '.</b> ' + esc(text) + '</p>').join('') + '</div><p>首次答案：<b>' + esc(item.user_answer) + '</b>　正确答案：<b>' + esc(item.correct_answer) + '</b></p><p class="study-detail-text">' + esc(item.explanation || '暂无解析') + '</p></details></article>'
  ).join('') : empty(all.length ? '没有匹配的错题' : '还没有错题',all.length ? '试试其他资料或复习状态，或清空搜索关键词。' : '完成练习后，首次答错的题目会自动收集到这里。');
  pagination('mistake-pagination',mistakePage,rows.length,'mistakes');
}
function renderRecords() {
  const query = $('record-search').value.trim().toLocaleLowerCase(), type = $('record-type').value, from = $('record-from').value, to = $('record-to').value;
  if (from && to && from > to) {
    status('records','开始日期不能晚于结束日期。'); $('record-list').innerHTML = ''; $('record-pagination').innerHTML = ''; return;
  }
  status('records','');
  const rows = (cache.records || []).filter(item => (!type || item.type === type) && (!query || (item.title+item.material_title).toLocaleLowerCase().includes(query)) && (!from || localDate(item.created_at) >= from) && (!to || localDate(item.created_at) <= to));
  const labels = {answer:'首次答题',review:'错题复习',chat:'AI 问答',study:'学习'};
  recordPage = Math.max(1,Math.min(recordPage,Math.ceil(rows.length/pageSize)));
  $('record-list').innerHTML = rows.length ? rows.slice((recordPage-1)*pageSize,recordPage*pageSize).map(item =>
    '<article class="record-row"><div class="record-dot record-kind-' + item.type + '" aria-hidden="true">' + ('<svg class="icon"><use href="/frontend/icons.svg#' + ({answer:'practice',review:'mistakes',chat:'chat',study:'library'}[item.type] || 'records') + '"></use></svg>') + '</div><div class="record-main"><div class="study-card-meta"><span>' + labels[item.type] + '</span><time>' + esc(dateText(item.created_at)) + '</time>' + (typeof item.is_correct === 'boolean' ? '<span class="status-pill ' + (item.is_correct ? 'strong' : 'weak') + '">' + (item.is_correct ? '回答正确' : '回答错误') + '</span>' : '') + (item.earned_xp ? '<span class="xp-earned">+' + item.earned_xp + ' XP</span>' : '') + '</div><h3>' + esc(item.title) + '</h3><p class="muted">' + esc(item.material_title) + (item.material_id ? ' · #' + item.material_id : '') + '</p><details><summary>查看' + (item.type === 'chat' ? '回答' : '详情') + '</summary><p class="study-detail-text">' + esc(item.detail || '暂无详情') + '</p></details></div></article>'
  ).join('') : empty('没有匹配的学习记录','完成一次问答或练习后，再来这里回顾；也可以调整筛选条件。');
  pagination('record-pagination',recordPage,rows.length,'records');
}
function topicState(topic) { return topic.mastery_status || (topic.mastery_score === null ? 'unseen' : topic.mastery_score >= 80 ? 'strong' : 'weak'); }
function renderMap() {
  const material = cache.map?.find(item => item.id === Number($('map-material').value));
  if (!material) { $('map-content').innerHTML = empty('从一份资料开始','导入资料并整理知识点后，就能在这里查看知识地图。','library'); return; }
  const filter = $('map-filter').value, nodes = material.topics.filter(topic => filter === 'all' || topicState(topic) === filter);
  if (!nodes.some(topic => topic.id === selectedNode)) selectedNode = nodes[0]?.id || null;
  const node = nodes.find(topic => topic.id === selectedNode);
  const indexed = material.chunk_count > 0 && material.chunk_count === material.embedded_count;
  const ready = indexed && material.linked_count > 0;
  const warning = !material.chunk_count ? '尚未建立文本索引，请先在资料库完成导入整理。' : !indexed ? '文本索引尚未完成，部分内容可能无法检索。' : !material.topics.length ? '尚未提取知识点，可先基于整份资料问答。' : !material.linked_count ? '知识点尚未关联文本，按知识点问答可能找不到内容。可先使用整份资料问答。' : '';
  $('map-content').innerHTML = '<div class="surface map-root"><div><p class="context-label">当前资料 · #' + material.id + '</p><h2>' + esc(material.title) + '</h2><div class="map-pipeline"><span class="status-pill ' + (indexed ? 'strong' : 'weak') + '">索引 ' + material.embedded_count + '/' + material.chunk_count + '</span><span class="status-pill">' + material.topics.length + ' 个知识点</span><span class="status-pill ' + (ready ? 'strong' : 'weak') + '">' + material.linked_count + ' 个片段已关联</span></div></div><button class="secondary" data-map-open="chat" data-whole="true">整份资料问答 ↗</button></div>' +
    (warning ? '<p class="map-warning" role="status">' + warning + '</p>' : '') + '<div class="knowledge-layout"><div class="knowledge-branches">' + (nodes.length ? nodes.map(topic => '<button class="topic-node ' + topicState(topic) + (topic.id === selectedNode ? ' selected' : '') + '" data-map-node="' + topic.id + '" aria-pressed="' + (topic.id === selectedNode) + '"><span class="node-kicker">' + ({unseen:'未练习',weak:'待巩固',strong:'规则达标'}[topicState(topic)]) + '</span><strong>' + esc(topic.name) + '</strong><span class="node-score">' + (topic.mastery_score === null ? '—' : topic.mastery_score + '/100') + '<small>' + topic.attempt_count + ' 道已练习</small></span><progress value="' + (topic.mastery_score || 0) + '" max="100" aria-label="' + esc(topic.name) + '掌握度"></progress></button>').join('') : '<div class="study-empty"><h3>没有符合条件的知识点</h3><p>切换掌握状态，或先完成资料整理。</p></div>') + '</div><aside class="surface node-detail">' + (node ? '<p class="context-label">知识点详情</p><h2>' + esc(node.name) + '</h2><p class="study-detail-text">' + esc(node.description || '暂无知识点说明') + '</p>' + (node.mastery_reason ? '<details><summary>掌握度评估依据</summary><p class="study-detail-text">' + esc(node.mastery_reason) + '</p></details>' : '') + '<p class="muted">关联文本：' + node.chunk_count + ' 个片段</p>' + (!node.chunk_count ? '<p class="map-warning">此知识点尚未关联文本，请先使用上方的整份资料问答。</p>' : '') + '<div class="node-actions"><button class="primary" data-map-open="practice"' + (!node.chunk_count ? ' disabled' : '') + '>练习这个知识点 →</button><button class="secondary" data-map-open="chat"' + (!node.chunk_count ? ' disabled' : '') + '>围绕它提问</button></div>' : '<p class="muted">选择一个知识点，查看说明并开始学习。</p>') + '</aside></div>';
}
function openReview(id) {
  const item = cache.mistakes?.find(row => row.id === Number(id));
  if (!item) return;
  reviewing = {item,requestId:crypto.randomUUID(),pending:false,answer:null};
  $('review-body').innerHTML = '<p class="muted">' + esc(item.topic_name) + '</p><h3 class="review-question">' + esc(item.question) + '</h3><form id="review-form"><fieldset id="review-choices" class="options"><legend class="sr-only">选择你的答案</legend>' + Object.entries(item.options).filter(([,text]) => text != null).map(([key,text]) => '<label class="option"><input type="radio" name="answer" value="' + key + '" required><span><b>' + key + '.</b> ' + esc(text) + '</span></label>').join('') + '</fieldset><button id="review-submit" class="primary" type="submit">确认答案</button><p id="review-feedback" role="status" class="study-detail-text"></p></form>';
  if (!$('review-dialog').open) $('review-dialog').showModal();
}
async function submitReview(event) {
  event.preventDefault();
  const attempt = reviewing, epoch = state.epoch;
  if (!attempt || attempt.pending) return;
  const answer = attempt.answer || new FormData(event.target).get('answer');
  if (!answer) return;
  attempt.pending = true; attempt.answer = answer;
  $('review-choices').disabled = true; $('review-submit').disabled = true; $('review-submit').textContent = '正在保存…';
  $('review-feedback').textContent = '';
  try {
    const result = await api('/study/mistakes/' + attempt.item.id + '/review',{method:'POST',...json({answer,request_id:attempt.requestId})});
    if (epoch !== state.epoch) return;
    emit('study-updated');
    if (reviewing !== attempt) return;
    $('review-feedback').className = 'answer-result ' + (result.is_correct ? 'correct' : 'wrong');
    $('review-feedback').textContent = (result.is_correct ? '回答正确，复习结果已保存。' : '还需要巩固，正确答案是 ' + result.correct_answer + '。') + '\n' + (result.explanation || '暂无解析');
    $('review-submit').textContent = '已保存';
    $('review-feedback').insertAdjacentHTML('afterend','<button type="button" class="secondary" data-close="review-dialog">返回错题本</button>');
  } catch (error) {
    if (epoch === state.epoch && reviewing === attempt && error.name !== 'AbortError') {
      $('review-feedback').textContent = '保存未确认：' + error.message + '。点击重试将核对同一次提交。';
      $('review-submit').disabled = false; $('review-submit').textContent = '重试保存';
    }
  } finally { attempt.pending = false; }
}
export function initStudy() {
  document.addEventListener('click',async event => {
    const refresh = event.target.closest('[data-study-refresh]');
    if (refresh) load(refresh.dataset.studyRefresh,true);
    const paginate = event.target.closest('[data-paginate]');
    if (paginate) {
      if (paginate.dataset.paginate === 'mistakes') { mistakePage += Number(paginate.dataset.step); renderMistakes(); $('mistakes-panel').scrollIntoView({block:'start'}); }
      else { recordPage += Number(paginate.dataset.step); renderRecords(); $('records-panel').scrollIntoView({block:'start'}); }
    }
    const review = event.target.closest('[data-review]');
    if (review) openReview(review.dataset.review);
    const node = event.target.closest('[data-map-node]');
    if (node) { selectedNode = Number(node.dataset.mapNode); renderMap(); $('map-content').querySelector('[data-map-node="' + selectedNode + '"]')?.focus({preventScroll:true}); }
    const destination = event.target.closest('[data-map-open]');
    if (destination && !destination.disabled) {
      const epoch = state.epoch, materialId = Number($('map-material').value), topicId = destination.dataset.whole ? null : selectedNode;
      destination.disabled = true;
      try {
        if (!state.materials.length) await loadMaterials();
        if (epoch !== state.epoch) return;
        await selectMaterial(materialId,true,true);
        if (epoch !== state.epoch) return;
        if (state.material?.id !== materialId || (topicId && !state.topics.some(topic => topic.id === topicId))) throw new Error('资料或知识点已变化，请刷新知识地图');
        setTopic(topicId); go(destination.dataset.mapOpen);
      } catch (error) { report(error); }
      finally { destination.disabled = false; }
    }
  });
  ['mistake-search','mistake-material','mistake-status'].forEach(id => $(id).addEventListener(id === 'mistake-search' ? 'input' : 'change',() => { mistakePage=1; if (cache.mistakes) renderMistakes(); }));
  ['record-search','record-type','record-from','record-to'].forEach(id => $(id).addEventListener(id === 'record-search' ? 'input' : 'change',() => { recordPage=1; if (cache.records) renderRecords(); }));
  ['map-material','map-filter'].forEach(id => $(id).addEventListener('change',() => { selectedNode=null; if (cache.map) renderMap(); }));
  $('review-body').addEventListener('submit',submitReview);
  $('review-dialog').addEventListener('close',() => { reviewing=null; $('review-body').innerHTML=''; });
  events.addEventListener('page',() => {
    if (!state.user) return;
    load('summary');
    const page = activePage();
    if (['mistakes','records','map'].includes(page)) load(page);
  });
  events.addEventListener('study-updated',invalidate);
  events.addEventListener('history-updated',invalidate);
  events.addEventListener('reset',() => {
    Object.keys(cache).forEach(key => { cache[key]=null; versions[key]=(versions[key] || 0)+1; pending[key]=false; status(key,''); });
    reviewing=null; selectedNode=null; mistakePage=1; recordPage=1;
    ['growth-card','mistake-stats','mistake-list','record-list','map-content','review-body','mistake-pagination','record-pagination','mistake-nav-count'].forEach(id => $(id).innerHTML='');
    ['mistake-search','record-search','record-type','record-from','record-to'].forEach(id => $(id).value='');
    $('mistake-status').value='pending'; $('map-filter').value='all';
    options('mistake-material',[],'全部资料'); options('map-material',[],'请选择资料');
    $('account-level').textContent=''; $('account-level').classList.add('hidden');
  });
}
