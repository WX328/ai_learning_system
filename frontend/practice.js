import { $, state, events, emit, api, json, esc, report, toast, requireMaterial, setTopic } from './core.js';
import { saveProgress } from './progress.js';
import { initRecommendation, recommendationReady, refreshRecommendation } from './recommendation.js';
$('quiz-count').max = '3';
function session(id = state.material?.id) { return state.sessions.get(id); }
function incomplete(current) { return current && (!!current.retry || current.results.length < current.questions.length); }
function focusPractice() {
  if ($('practice-panel').classList.contains('hidden')) return;
  $('practice-content').scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',block:'start'});
}
function renderControls() {
  const current = session();
  const active = !!current?.questions.length && current.index < current.questions.length;
  const focused = active && current.focus !== false;
  $('practice-panel').classList.toggle('focus-mode', focused);
  $('practice-focus-toolbar').classList.toggle('hidden', !active);
  $('toggle-practice-focus').textContent = focused ? '展开设置' : '专注答题';
  $('toggle-practice-focus').setAttribute('aria-pressed', String(focused));
  const locked = !!current?.pending || !!incomplete(current);
  $('generate-button').disabled = !state.material || state.selecting || locked || !state.topics.some(item => item.id === state.topicId);
  $('generate-button').textContent = current?.pending === 'generate' ? '正在生成…' : '生成练习';
  $('adaptive-button').disabled = !state.material || state.selecting || locked || !recommendationReady();
  $('adaptive-button').textContent = current?.pending === 'adaptive' ? '正在准备…' : '开始练习 →';
  $('practice-replace-note').classList.toggle('hidden', !incomplete(current));
  $('adaptive-status').textContent = current?.adaptiveMessage || '';
}
function renderTopicOptions() {
  const topic = state.topics.find(item => item.id === state.topicId);
  $('quiz-topic-select').innerHTML = '<option value="">请选择已提取的知识点</option>' +
    state.topics.map(item => '<option value="' + item.id + '">' + esc(item.name) + '</option>').join('');
  $('quiz-topic-select').value = state.topicId || '';
  $('quiz-topic').value = topic?.name || '';
  $('quiz-topic').readOnly = true;
  renderControls();
}
function renderSummary(current) {
  const correct = current.results.filter(result => result.is_correct).length;
  const unconfirmed = current.results.filter(result => result.unconfirmed).length;
  const confirmed = current.questions.length - unconfirmed;
  const xp = current.results.reduce((sum,result) => sum + Number(result.earned_xp || 0),0);
  $('practice-content').innerHTML = '<div class="surface question-card"><div class="summary-head"><h2>这一轮，学有所获。</h2><p class="muted">' +
    esc(current.materialTitle) + ' · ' + (unconfirmed ? unconfirmed + ' 题结果未确认，未计入本地正确率和经验值。' : correct === current.questions.length ? '全部答对了，继续保持！' : '回看错题解析，让下一次更有把握。') + '</p></div>' +
    '<div class="summary-stats"><div><b>' + (confirmed ? Math.round(correct / confirmed * 100) + '%' : '—') + '</b><span>首次作答正确率</span></div><div><b>' + correct + '/' + confirmed +
    '</b><span>首次答对题数</span></div><div><b>+' + xp + '</b><span>答题经验值 XP</span></div></div><h3>逐题回顾</h3>' +
    current.questions.map((question,index) => {
      const result = current.results[index];
      return '<details class="review-item"' + (!result.is_correct ? ' open' : '') + '><summary>' + (result.unconfirmed ? '待确认 · ' : result.is_correct ? '答对 · ' : '待巩固 · ') + (index+1) + '. ' + esc(question.question) +
        '</summary><p>你的答案：' + esc(result.user_answer) + ' · 正确答案：' + esc(result.unconfirmed ? '尚未取得' : result.correct_answer) + '</p><p>' + esc(result.feedback || result.explanation || '暂无解析') + '</p>' + (result.review ? '<p>最近重答：' + esc(result.review.user_answer) + (result.review.is_correct ? ' · 已答对' : ' · 仍需巩固') + '</p>' : '') + '</details>';
    }).join('') + '<div class="summary-actions"><button class="primary" id="new-practice">再练一组 →</button><button class="secondary" data-page="chat">回到资料问一问</button></div><p class="muted">本地保留每份资料最近一组练习，保存状态见上方提示。服务端答题记录与经验值不受本地清除影响。</p></div>';
  $('new-practice').addEventListener('click', () => {
    current.focus = false; renderControls();
    $('quiz-form').scrollIntoView({behavior:'smooth',block:'center'}); $('quiz-topic-select').focus();
    toast('在左侧选择主题，生成新的练习即可');
  });
}
export function renderPractice() {
  renderControls();
  const current = session();
  if (!current?.questions.length) {
    $('practice-content').innerHTML = '<div class="surface empty"><h3>' + (current?.pending ? '正在准备你的练习…' : '每一次练习，都离掌握更近') +
      '</h3><p>' + (current?.pending ? 'AI 正在根据资料生成题目，请稍候。' : '选择一个知识点和合适的难度，或从一道薄弱点练习开始。') + '</p></div>';
    return;
  }
  if (current.index >= current.questions.length) { renderSummary(current); return; }
  const question = current.questions[current.index], original = current.results[current.index];
  const retry = current.retry?.questionId === question.id ? current.retry : null;
  const result = retry ? null : original?.review || original;
  const locked = !!result || !!current.pending || !!retry?.answer;
  $('practice-content').innerHTML = '<form id="answer-form" class="surface question-card"><div class="question-meta"><span>' +
    (current.adaptive ? '薄弱点练习' : '知识巩固') + ' · 第 ' + (current.index+1) + ' / ' + current.questions.length + ' 题</span><span>难度 ' + esc(question.difficulty) +
    '/5</span></div><progress value="' + current.results.length + '" max="' + current.questions.length + '" aria-label="练习完成进度"></progress>' +
    '<h2>' + esc(question.question) + '</h2>' + (retry ? '<p class="muted">重新作答 · 首次记录保留，重答不重复获得 XP。</p>' + (retry.uncertain ? '<p class="submission-warning" role="status">重答保存未确认，请点击“重试保存”核对同一次提交。</p>' : '') : '') + (current.uncertain && !result ? '<p class="submission-warning" role="status">上次提交结果未确认。可以重试提交；如服务端已收录，本题将标记为待确认，不猜测对错或重复计算经验值。</p>' : '') + '<fieldset class="options"' + (locked ? ' disabled' : '') + '><legend class="sr-only">选择一个答案</legend>' +
    ['A','B','C','D'].map(key => '<label class="option' + (result?.unconfirmed ? '' : result?.correct_answer === key ? ' correct' : result?.user_answer === key ? ' wrong' : '') +
      '"><input type="radio" name="answer" value="' + key + '" required' + ((result?.user_answer || current.selection) === key ? ' checked' : '') +
      '><b>' + key + '</b><span>' + esc(question['option_' + key.toLowerCase()]) + '</span></label>').join('') + '</fieldset>' +
    (result ? '<div class="answer-result ' + (result.unconfirmed ? 'submission-warning' : result.is_correct ? 'correct' : 'wrong') + '" role="status">' +
      (result.unconfirmed ? '服务端已记录，本地结果待确认。' : result.is_correct && original?.review ? '重新作答正确！复习结果已保存。' : result.is_correct ? '回答正确！获得 ' + Number(result.earned_xp || 0) + ' XP。' : '这题还需要巩固，正确答案是 ' + esc(result.correct_answer) + '。') +
      '\n' + esc(result.feedback || result.explanation || '暂无解析') + '</div><div class="answer-actions">' + (!result.unconfirmed && !result.is_correct ? '<button class="secondary" type="button" id="retry-question">重新作答</button>' : '') + '<button class="primary" type="button" id="next-question">' + (current.index+1 < current.questions.length ? '下一题 →' : '查看本轮总结 →') + '</button></div>' :
      '<div class="answer-actions"><button class="primary" type="submit"' + (current.pending ? ' disabled' : '') + '>' + (current.pending ? '正在提交…' : retry?.answer ? '重试保存' : retry ? '提交重答 →' : '提交答案 →') + '</button>' + (retry && !retry.answer ? '<button class="secondary" type="button" id="cancel-retry">取消重答</button>' : '') + '</div>') + '</form>';
  $('answer-form').addEventListener('submit', submitAnswer);
  $('answer-form').addEventListener('change', event => { if (event.target.name === 'answer') { current.selection = event.target.value; saveProgress(current); } });
  $('retry-question')?.addEventListener('click', () => {
    if (current.pending || current.retry) return;
    current.retry = {questionId:question.id,requestId:crypto.randomUUID(),answer:null,uncertain:false};
    current.selection = null;
    saveProgress(current); renderPractice();
  });
  $('cancel-retry')?.addEventListener('click', () => {
    if (current.pending || current.retry?.answer) return;
    current.retry = null; current.selection = null;
    saveProgress(current); renderPractice();
  });
  $('next-question')?.addEventListener('click', () => { current.index++; current.selection = null; saveProgress(current); renderPractice(); focusPractice(); });
}
function validQuestion(question) {
  return question && Number.isInteger(question.id) && typeof question.question === 'string';
}
async function startPractice(adaptive) {
  if (!requireMaterial()) return;
  if (adaptive && !recommendationReady()) return;
  const id = state.material.id, epoch = state.epoch, previous = session(id);
  if (previous?.pending || incomplete(previous)) { toast('请先完成当前练习，再开始新的一组',true); return; }
  const current = {
    questions:[],results:[],index:0,pending:adaptive ? 'adaptive' : 'generate',
    adaptive,adaptiveMessage:'',materialTitle:state.material.title,selection:null,focus:true,uncertain:false,
  };
  const topicId = Number($('quiz-topic-select').value) || null;
  const topic = $('quiz-topic').value.trim();
  if (!adaptive && !state.topics.some(item => item.id === topicId)) { toast('请先提取并选择知识点，再生成练习',true); return; }
  state.sessions.set(id,current); renderPractice();
  try {
    if (adaptive) {
      const data = await api('/adaptive/next-question?material_id=' + id);
      if (!validQuestion(data?.question)) throw new Error('服务未返回有效题目');
      current.questions = [data.question];
      current.adaptiveMessage = '本次聚焦：' + data.topic.name + ' · 已练 ' + (data.topic.attempt_count || 0) + ' 次';
    } else {
      const questions = await api('/questions/generate',{method:'POST',...json({
        material_id:id,topic,topic_id:topicId,count:Number($('quiz-count').value),difficulty:Number($('quiz-difficulty').value),
      })});
      if (!Array.isArray(questions) || !questions.length || !questions.every(validQuestion)) throw new Error('没有生成有效题目，请重试');
      current.questions = questions;
    }
  } catch (error) {
    if (epoch !== state.epoch) return;
    if (previous) state.sessions.set(id,previous);
    if (adaptive && error.status === 404) {
      (previous || current).adaptiveMessage = error.message;
      void refreshRecommendation();
      toast(error.message,true);
    } else report(error);
  } finally {
    current.pending = null;
    if (epoch === state.epoch) saveProgress(state.sessions.get(id));
    if (epoch === state.epoch && state.material?.id === id) {
      renderPractice();
      if (current.questions.length) focusPractice();
    }
  }
}
async function submitAnswer(event) {
  event.preventDefault();
  const id = state.material?.id, current = session(id), epoch = state.epoch;
  if (!current || current.pending) return;
  if (current.retry) return submitRetry(event,current,id,epoch);
  if (current.results[current.index]) return;
  const answer = new FormData(event.currentTarget).get('answer');
  if (!answer) return;
  const question = current.questions[current.index];
  current.selection = answer; current.pending = 'answer'; saveProgress(current); renderPractice();
  try {
    const result = await api('/questions/' + question.id + '/answer',{method:'POST',...json({answer})});
    if (epoch !== state.epoch) return;
    current.results.push(result);
    current.uncertain = false;
    emit('study-updated');
    if (result.feedback_source === 'local') {
      void loadAnswerFeedback(current,result,id,epoch);
    }
  } catch (error) {
    if (epoch !== state.epoch) return;
    if (error.status === 400 && error.message.includes('已经回答')) {
      current.results.push({question_id:question.id,user_answer:answer,correct_answer:null,is_correct:null,earned_xp:0,unconfirmed:true,
        explanation:'之前的提交已被服务端受理，但当前接口不提供该题历史结果。本地总结不计入这题；服务端记录和经验值保持不变。'});
      current.uncertain = false;
      emit('study-updated');
    } else { current.uncertain = true; report(error); }
  }
  finally {
    current.pending = null;
    if (epoch === state.epoch) saveProgress(current);
    if (epoch === state.epoch && state.material?.id === id) renderPractice();
  }
}
async function loadAnswerFeedback(current,result,id,epoch) {
  try {
    const updated = await api('/questions/' + result.question_id + '/feedback',{method:'POST'});
    if (epoch !== state.epoch || state.sessions.get(id) !== current || !updated?.feedback) return;
    result.feedback = updated.feedback;
    result.feedback_source = updated.source || 'local';
    saveProgress(current);
    if (state.material?.id === id) renderPractice();
  } catch { /* The saved answer already includes local feedback. */ }
}
async function submitRetry(event,current,id,epoch) {
  const retry = current.retry, question = current.questions[current.index];
  const original = current.results[current.index];
  if (!retry || retry.questionId !== question?.id || !original || original.unconfirmed || original.is_correct) return;
  const answer = retry.answer || new FormData(event.currentTarget).get('answer');
  if (!answer) return;
  retry.answer = answer; retry.uncertain = false;
  current.selection = answer; current.pending = 'review';
  saveProgress(current); renderPractice();
  try {
    const result = await api('/study/mistakes/' + question.id + '/review',{
      method:'POST',...json({answer,request_id:retry.requestId}),
    });
    if (epoch !== state.epoch) return;
    original.review = {...result,earned_xp:0};
    current.retry = null; current.selection = null;
    emit('study-updated');
  } catch (error) {
    if (epoch !== state.epoch) return;
    retry.uncertain = true; report(error);
  } finally {
    current.pending = null;
    if (epoch === state.epoch) {
      saveProgress(current);
      if (state.material?.id === id) renderPractice();
    }
  }
}
export function initPractice() {
  initRecommendation(renderControls);
  $('toggle-practice-focus').addEventListener('click', () => {
    const current = session(); if (!current) return;
    current.focus = current.focus === false;
    renderControls();
    if (current.focus) focusPractice();
  });
  $('quiz-form').addEventListener('submit', event => { event.preventDefault(); startPractice(false); });
  $('adaptive-button').addEventListener('click', () => startPractice(true));
  $('quiz-topic-select').addEventListener('change', event => setTopic(event.target.value));
  function ranges() {
    $('count-output').textContent = $('quiz-count').value + ' 道';
    $('difficulty-output').textContent = ['入门','基础','进阶','较难','挑战'][Number($('quiz-difficulty').value)-1];
  }
  $('quiz-count').addEventListener('input',ranges); $('quiz-difficulty').addEventListener('input',ranges);
  events.addEventListener('material', () => { renderTopicOptions(); renderPractice(); });
  events.addEventListener('topic', renderTopicOptions);
  events.addEventListener('topics', renderTopicOptions);
  events.addEventListener('page', () => { if (!$('practice-panel').classList.contains('hidden')) renderPractice(); });
  events.addEventListener('progress-cleared', renderPractice);
  events.addEventListener('reset', () => { $('quiz-form').reset(); ranges(); renderTopicOptions(); renderPractice(); });
  ranges(); renderTopicOptions(); renderPractice();
}
