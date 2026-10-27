import { $, state, events, emit, api, json, esc, toast, requireMaterial, setTopic, go } from './core.js';
import { materialIds } from './materials.js';
// Only render a small, escaped Markdown subset. Raw model HTML is never inserted.
export function formatText(text) {
  return String(text ?? '').split(/(```[\s\S]*?```)/g).map(part => {
    if (part.startsWith('```')) {
      const code = part.slice(3,-3).replace(/^[\w+-]*\r?\n/, '');
      return '<pre><code>' + esc(code) + '</code></pre>';
    }
    return esc(part).split(/\n\s*\n/).filter(Boolean).map(block => {
      const formatted = block.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`\n]+)`/g, '<code>$1</code>');
      return /^#{1,3} /.test(block) ? '<h4>' + formatted.replace(/^#{1,3} /,'') + '</h4>' : '<p>' + formatted + '</p>';
    }).join('');
  }).join('');
}
function conversation(id = state.material?.id) {
  if (!state.conversations.has(id)) state.conversations.set(id, {messages:[],loaded:false,loading:false,pending:false,error:''});
  return state.conversations.get(id);
}
function metric(value) {
  if (value == null) return '—';
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(4) : '—';
}
function sourcesHTML(message) {
  const sources = Array.isArray(message.sources) ? message.sources : [];
  if (!sources.length) return message.contextSource === 'document_fallback' ?
    '<p class="retrieval-meta">未命中相关片段；本次回答基于资料正文开头，可能不完整。</p>' : '';
  const retrieval = message.retrieval || {};
  const method = retrieval.retrieval_method || 'vector';
  const methodLabel = method === 'topic' ? '知识点正文片段' : method === 'hybrid' ? '向量 + BM25 混合召回' : method === 'bm25' ? 'BM25 关键词召回' : '向量召回';
  const rerankState = retrieval.rerank_fallback ? '重排失败，已回退到召回排序' :
    (retrieval.rerank_applied ? '已使用 Reranker 重排' : method === 'topic' ? '按原文章节顺序整理' : '按召回结果排序');
  const total = Number(retrieval.total_latency_ms);
  const timing = Number.isFinite(total) ? ' · 检索流程 ' + Math.round(total) + ' ms' : '';
  return '<details class="answer-sources"><summary>资料依据 · ' + sources.length + ' 个片段</summary>' +
    '<div class="source-list">' + sources.map(source => {
      const rerank = source.rerank_score == null ? '' : ' · 重排 ' + metric(source.rerank_score);
      const bm25 = source.bm25_score == null ? '' : ' · BM25 ' + metric(source.bm25_score);
      const fusion = source.rrf_score == null ? '' : ' · 融合 ' + metric(source.rrf_score);
      const scores = method === 'topic' ? '知识点关联正文' : '向量 ' + metric(source.similarity) + bm25 + fusion + rerank;
      return '<article class="source-card"><div><b>#' + esc(source.rank) + ' 文档片段 ' + esc(source.chunk_index) +
        '</b><span>' + scores + '</span></div><p>' + esc(source.excerpt || '') + '</p></article>';
    }).join('') + '</div><p class="retrieval-meta">召回 ' + esc(retrieval.candidate_count ?? sources.length) +
    ' 个候选 · ' + esc(methodLabel) + ' · ' + esc(rerankState) + timing + '</p></details>';
}
function messageHTML(message, index) {
  return '<div class="message ' + message.role + '"><div class="avatar">' + (message.role === 'user' ? '我' : 'AI') +
    '</div><div class="message-content"><small>' + (message.role === 'user' ? '你' : 'AI 学习助手') + '</small><div class="message-body">' +
    formatText(message.text) + '</div>' + (message.role === 'assistant' ? sourcesHTML(message) + '<button class="link-button copy-button" data-copy="' + index + '">复制回答</button>' : '') + '</div></div>';
}
function renderChat() {
  const current = state.material ? conversation() : null;
  const messages = current?.messages || [];
  $('messages').innerHTML = messages.length ? messages.map(messageHTML).join('') :
    '<div class="empty"><h3>好问题，是理解的开始。</h3><p>' +
    (state.material ? '可以让我总结这份资料，或从左侧选一个知识点开始。' : '先在资料库导入并选择一份资料。') + '</p></div>';
  if (current?.pending) $('messages').insertAdjacentHTML('beforeend','<p class="muted" role="status">正在根据资料整理回答…</p>');
  $('history-status').textContent = current?.loading ? '正在加载这份资料的问答历史…' : current?.error || '';
  $('send-question').disabled = !state.material || state.selecting || !!current?.pending || !!current?.loading;
  $('send-question').textContent = current?.pending ? '回答中…' : '发送 ↑';
  $('reload-history').disabled = !state.material || !!current?.loading || !!current?.pending;
  $('messages').scrollTop = $('messages').scrollHeight;
}
function renderTopics() {
  $('topic-list').innerHTML = '<button class="topic-button' + (!state.topicId ? ' active' : '') + '" data-topic="" aria-pressed="' + !state.topicId + '"><b>整份资料</b></button>' +
    state.topics.map(topic => '<button class="topic-button' + (state.topicId === topic.id ? ' active' : '') + '" data-topic="' + topic.id + '" aria-pressed="' + (state.topicId === topic.id) +
      '"><b>' + esc(topic.name) + '</b><small>' + esc(topic.description || '') + '</small></button>').join('') +
    (!state.topics.length ? '<p class="muted">' + (state.selecting ? '正在加载知识点…' : '暂无知识点，可在资料导入时整理。') + '</p>' : '');
  const topic = state.topics.find(item => item.id === state.topicId);
  $('chat-scope').textContent = topic ? '聚焦：' + topic.name : '基于整份资料';
  document.querySelectorAll('[data-suggestion-kind]').forEach(button => {
    if (button.dataset.suggestionKind === 'summary') {
      button.textContent = topic ? '总结当前知识点' : '总结核心内容';
      button.dataset.suggestion = topic ? '请总结知识点「' + topic.name + '」的核心概念和要点。' : '请总结这份资料的核心知识点。';
    } else {
      button.dataset.suggestion = topic ? '请用一个生活中的例子解释知识点「' + topic.name + '」。' : '请用一个生活中的例子解释这份资料的核心知识点。';
    }
  });
  $('topic-practice').disabled = !state.material || state.selecting;
}
export async function loadHistory(force = false) {
  if (!state.material) return;
  const id = state.material.id, ids = materialIds(state.material), current = conversation(id), epoch = state.epoch;
  if (current.loading || current.pending || (current.loaded && !force)) return;
  current.loading = true; current.error = ''; renderChat();
  try {
    const histories = await api('/rag/history');
    if (epoch !== state.epoch) return;
    // Keep unsaved replies in this session; the API doesn't save answers without context.
    const saved = (Array.isArray(histories) ? histories : []).filter(item => ids.includes(item.material_id)).sort((a,b) => a.id-b.id)
      .flatMap(item => [{role:'user',text:item.question},{role:'assistant',text:item.answer}]);
    const local = current.messages.filter(item => item.local);
    current.messages = [...saved, ...local]; current.loaded = true;
  } catch (error) {
    if (epoch === state.epoch && error.name !== 'AbortError') current.error = '历史加载失败，可点击“加载历史”重试。';
  } finally {
    current.loading = false;
    if (epoch === state.epoch && state.material?.id === id) renderChat();
  }
}
async function ask(event) {
  event.preventDefault();
  if (!requireMaterial()) return;
  const id = state.material.id, current = conversation(id), epoch = state.epoch;
  if (current.pending || current.loading) return;
  const query = $('chat-input').value.trim();
  if (!query) return;
  const topicId = state.topicId;
  const userMessage = {role:'user',text:query,local:true};
  current.messages.push(userMessage); current.pending = true;
  $('chat-input').value = ''; renderChat();
  try {
    const data = await api('/rag/ask',{method:'POST',...json({query,material_id:id,topic_id:topicId})});
    if (epoch !== state.epoch) return;
    userMessage.local = !data.history_id;
    current.messages.push({
      role:'assistant', text:data.answer, local:!data.history_id,
      sources:Array.isArray(data.sources) ? data.sources : [], retrieval:data.retrieval || null,
      contextSource:data.context_source || null
    });
    if (data.history_id) emit('history-updated');
  } catch (error) {
    if (epoch === state.epoch && error.name !== 'AbortError') {
      current.messages.push({role:'assistant',text:'暂时无法回答：' + error.message + '。可重新发送问题。',local:true});
      if (state.material?.id === id && !$('chat-input').value) $('chat-input').value = query;
    }
  } finally {
    current.pending = false;
    if (epoch === state.epoch && state.material?.id === id) renderChat();
  }
}
export function initChat() {
  $('chat-form').addEventListener('submit',ask);
  $('chat-input').addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) {
      event.preventDefault(); $('chat-form').requestSubmit($('send-question'));
    }
  });
  $('reload-history').addEventListener('click', () => loadHistory(true));
  $('topic-list').addEventListener('click', event => {
    const button = event.target.closest('[data-topic]');
    if (button && !state.selecting) setTopic(button.dataset.topic);
  });
  $('topic-practice').addEventListener('click', () => { if (requireMaterial()) go('practice'); });
  document.querySelectorAll('[data-suggestion]').forEach(button => button.addEventListener('click', () => {
    $('chat-input').value = button.dataset.suggestion; $('chat-input').focus();
  }));
  $('messages').addEventListener('click', async event => {
    const button = event.target.closest('[data-copy]');
    if (!button || !state.material) return;
    try { await navigator.clipboard.writeText(conversation().messages[Number(button.dataset.copy)].text); toast('回答已复制'); }
    catch { toast('无法自动复制，请选择回答文字复制',true); }
  });
  events.addEventListener('material', () => { $('chat-input').value = ''; renderTopics(); renderChat(); loadHistory(); });
  events.addEventListener('topics', () => { renderTopics(); renderChat(); });
  events.addEventListener('topic', renderTopics);
  events.addEventListener('reset', () => { $('chat-input').value = ''; renderTopics(); renderChat(); });
  renderTopics(); renderChat();
}
