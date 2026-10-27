import { $, state, events, api, esc } from './core.js';

let entry = null, updateControls = () => {};
const visible = () => !$('practice-panel').classList.contains('hidden');
export function recommendationReady() {
  return !!(entry && entry.epoch === state.epoch && entry.materialId === state.material?.id &&
    entry.data?.topic && !entry.error && !entry.pending && !entry.dirty);
}
function render() {
  const content = $('recommendation-content');
  $('recommendation-refresh').disabled = !state.material || !!entry?.pending;
  content.setAttribute('aria-busy', String(!!entry?.pending));
  if (!state.material) {
    content.innerHTML = '<p class="muted">选择资料后查看学习建议。</p>';
  } else if (entry?.error) {
    content.innerHTML = '<p role="alert">推荐加载失败：' + esc(entry.error) + '。请点击刷新重试。</p>';
  } else if (!entry?.data) {
    content.innerHTML = '<p class="muted" role="status">正在读取学习表现…</p>';
  } else {
    const data = entry.data;
    if (!data.topic) {
      content.innerHTML = '<p class="muted">' + esc(data.reason) + '</p>';
    } else {
      const score = data.mastery_score;
      const rate = data.recent_correct_rate;
      const difficulty = Math.max(1, Math.min(5, data.recommended_difficulty));
      content.innerHTML = '<p class="recommendation-topic">' + esc(data.topic.name) + '</p>' +
        '<dl class="recommendation-metrics"><div><dt>规则掌握度</dt><dd>' + (score === null ? '尚未评估' : esc(score) + '/100') + '</dd></div></dl>' +
        '<progress max="100" value="' + (score === null ? 0 : Number(score)) + '" aria-label="知识点掌握度"' +
        (score === null ? ' aria-valuetext="尚未评估"' : '') + '></progress>' +
        '<dl class="recommendation-metrics"><div><dt>最近 5 道首次正确率</dt><dd>' + (rate === null ? '暂无答题记录' : Math.round(rate * 100) + '%') + '</dd></div>' +
        '<div><dt>推荐练习难度</dt><dd><span class="recommendation-stars" aria-label="难度 ' + difficulty + '，共 5 星">' +
        '★'.repeat(difficulty) + '☆'.repeat(5 - difficulty) + '</span> <span>' + difficulty + '/5</span></dd></div></dl>' + // taste-skill-ignore: requested difficulty stars
        (data.recent_attempt_count ? '<p class="muted recommendation-sample">按最近 ' + Number(data.recent_attempt_count) + ' 次首次作答统计</p>' : '') +
        (data.has_history ? '<p class="muted">已练习 ' + Number(data.attempt_count) + ' 道不同题目' + (data.sample_limited ? ' · 初步评估' : '') +
          (Number(data.reviewed_question_count) ? ' · 已复习 ' + Number(data.reviewed_question_count) + ' 道（不增加样本）' : '') + '</p>' : '') +
        '<p class="recommendation-reason">' + esc(data.reason) + '</p>' +
        (data.mastery_reason ? '<details><summary>查看评估依据</summary><p>' + esc(data.mastery_reason) + '</p>' +
          (data.decision_reasons?.recent_performance ? '<p>' + esc(data.decision_reasons.recent_performance) + '</p>' : '') + '</details>' : '') +
        (entry.pending ? '<p class="muted" role="status">正在更新推荐…</p>' : '');
    }
  }
  updateControls();
}
export async function refreshRecommendation() {
  if (!state.user || !state.material) { entry = null; render(); return; }
  const materialId = state.material.id, epoch = state.epoch;
  if (entry?.materialId === materialId && entry.epoch === epoch && entry.pending) {
    return;
  }
  const previous = entry?.materialId === materialId && entry.epoch === epoch ? entry.data : null;
  const current = entry = {materialId, epoch, data:previous, pending:true, dirty:false, error:null};
  render();
  try {
    const data = await api('/adaptive/recommendation?material_id=' + materialId);
    if (entry !== current || epoch !== state.epoch || state.material?.id !== materialId) return;
    if (!data || !Object.hasOwn(data,'topic') || typeof data.reason !== 'string') throw new Error('服务未返回有效推荐');
    if (data.topic && (typeof data.topic.name !== 'string' || !Number.isInteger(data.recommended_difficulty) ||
      data.recommended_difficulty < 1 || data.recommended_difficulty > 5 ||
      !(data.mastery_score === null || (Number.isFinite(data.mastery_score) && data.mastery_score >= 0 && data.mastery_score <= 100)) ||
      !(data.recent_correct_rate === null || (Number.isFinite(data.recent_correct_rate) && data.recent_correct_rate >= 0 && data.recent_correct_rate <= 1)))) {
      throw new Error('服务未返回有效推荐');
    }
    current.data = data;
  } catch (error) {
    if (entry === current && epoch === state.epoch && error.name !== 'AbortError') current.error = error.message;
  } finally {
    if (entry === current && epoch === state.epoch && state.material?.id === materialId) {
      current.pending = false;
      render();
      if (current.dirty && visible()) void refreshRecommendation();
    }
  }
}
export function initRecommendation(onChange) {
  updateControls = onChange;
  $('recommendation-refresh').addEventListener('click', () => {
    if (!entry?.pending) void refreshRecommendation();
  });
  events.addEventListener('material', () => {
    entry = null;
    render();
    if (visible()) void refreshRecommendation();
  });
  events.addEventListener('page', () => {
    if (visible() && (!entry?.data || entry.dirty || entry.materialId !== state.material?.id)) void refreshRecommendation();
  });
  events.addEventListener('study-updated', () => {
    if (entry) entry.dirty = true;
    if (visible()) void refreshRecommendation();
  });
  events.addEventListener('reset', () => { entry = null; render(); });
  render();
  if (visible() && state.material) void refreshRecommendation();
}
