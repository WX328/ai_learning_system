import { $, state, events, emit, toast } from './core.js';
const VERSION = 1;
let saved = true, failureNotified = false;
const key = () => state.user ? 'learning_progress_v1_' + state.user.id : null;
const answer = value => ['A','B','C','D'].includes(value);
export function progressSaved() { return saved; }
function status(message) {
  if ($('storage-status')) $('storage-status').textContent = message;
  if ($('practice-save-status')) $('practice-save-status').textContent = message;
}
function cleanReview(value,questionId) {
  if (!value || value.question_id !== questionId || !answer(value.user_answer) ||
      !answer(value.correct_answer) || typeof value.is_correct !== 'boolean') return null;
  return {question_id:questionId,user_answer:value.user_answer,correct_answer:value.correct_answer,
    is_correct:value.is_correct,earned_xp:0,explanation:String(value.explanation ?? '')};
}
function validate(entry) {
  if (!Array.isArray(entry) || entry.length !== 2) return null;
  const [id, data] = entry;
  if (!Number.isSafeInteger(id) || id <= 0 || !data || typeof data !== 'object') return null;
  const questions = data.questions;
  if (!Array.isArray(questions) || questions.length < 1 || questions.length > 10 ||
      !questions.every(q => q && Number.isSafeInteger(q.id) && q.id > 0 && typeof q.question === 'string') ||
      new Set(questions.map(q => q.id)).size !== questions.length) return null;
  if (!Array.isArray(data.results) || data.results.length > questions.length) return null;
  if (!data.results.every((r,i) => r && r.question_id === questions[i].id && answer(r.user_answer) &&
    (r.unconfirmed === true || (typeof r.is_correct === 'boolean' && answer(r.correct_answer) && Number.isFinite(r.earned_xp))))) return null;
  if (!Number.isInteger(data.index) || data.index < 0 || data.index > questions.length || data.index > data.results.length) return null;
  const cleanQuestions = questions.map(q => ({
    id:q.id, material_id:id, question:q.question, difficulty:Number(q.difficulty) || 1,
    option_a:String(q.option_a ?? ''), option_b:String(q.option_b ?? ''), option_c:String(q.option_c ?? ''), option_d:String(q.option_d ?? ''),
  }));
  const retry = data.retry;
  const original = data.results[data.index];
  const validRetry = retry && original && original.is_correct === false && !original.unconfirmed &&
    retry.questionId === questions[data.index]?.id &&
    typeof retry.requestId === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(retry.requestId);
  return [id, {
    questions:cleanQuestions, results:data.results.map(r => ({
      question_id:r.question_id,user_answer:r.user_answer,correct_answer:r.unconfirmed ? null : r.correct_answer,
      is_correct:r.unconfirmed ? null : r.is_correct,earned_xp:r.unconfirmed ? 0 : r.earned_xp,
      explanation:String(r.explanation ?? ''),feedback:String(r.feedback ?? ''),
      feedback_source:String(r.feedback_source ?? ''),unconfirmed:!!r.unconfirmed,
      review:r.is_correct === false && !r.unconfirmed ? cleanReview(r.review,r.question_id) : null,
    })),
    retry:validRetry ? {questionId:retry.questionId,requestId:retry.requestId,
      answer:answer(retry.answer) ? retry.answer : null,uncertain:!!retry.uncertain || answer(retry.answer)} : null,
    index:data.index,selection:answer(data.selection) ? data.selection : null,
    materialTitle:String(data.materialTitle || '学习资料'),adaptive:!!data.adaptive,
    adaptiveMessage:String(data.adaptiveMessage || ''),pending:null,
    uncertain:!!data.uncertain || !!data.submitting,focus:true,
    updatedAt:Number.isFinite(data.updatedAt) ? data.updatedAt : 0,
  }];
}
export function restoreProgress() {
  state.sessions.clear(); saved = true; failureNotified = false;
  status('练习自动保存在当前浏览器，按账号区分；不跨设备同步。');
  if (!key()) return;
  try {
    const raw = localStorage.getItem(key());
    if (raw) {
      const data = JSON.parse(raw);
      if (data.version !== VERSION || !Array.isArray(data.sessions)) throw new Error('格式不兼容');
      const entries = data.sessions.map(validate).filter(Boolean);
      state.sessions = new Map(entries);
      if (entries.length !== data.sessions.length) toast('部分本地练习记录无法读取，已恢复其余有效记录',true);
      if (entries.length) status('已恢复本账号的本地练习，继续作答会自动保存。');
    }
  } catch {
    saved = false;
    status('本地练习无法读取。可继续学习，或清除本账号的本地记录后重试。');
    toast('本地练习记录未能恢复，其他功能仍可使用',true);
  }
  emit('progress');
}
export function saveProgress(current) {
  if (!key()) return;
  if (current) current.updatedAt = Date.now();
  try {
    // Preserve the last successful set while a replacement set is still generating.
    let oldEntries = [];
    try {
      const old = JSON.parse(localStorage.getItem(key()) || 'null');
      if (old?.version === VERSION && Array.isArray(old.sessions)) oldEntries = old.sessions.map(validate).filter(Boolean);
    } catch { /* A new valid snapshot replaces unreadable local data. */ }
    const entries = new Map(oldEntries);
    for (const [id, session] of state.sessions) {
      if (!session.questions.length) continue;
      const entry = validate([id,{...session,submitting:session.pending === 'answer'}]);
      if (entry) entries.set(id,entry[1]);
    }
    localStorage.setItem(key(),JSON.stringify({version:VERSION,sessions:[...entries]}));
    saved = true; failureNotified = false;
    status('已自动保存在当前浏览器 · 刷新后可恢复 · 不跨设备同步');
  } catch {
    saved = false;
    status('自动保存失败：浏览器存储不可用或空间不足。请暂时不要刷新页面。');
    if (!failureNotified) { toast('练习暂未保存，请不要刷新页面',true); failureNotified = true; }
  }
  emit('progress');
}
export function clearProgress() {
  if (!key()) return false;
  try { localStorage.removeItem(key()); }
  catch { toast('无法清除本地记录，请检查浏览器存储权限',true); return false; }
  state.sessions.clear(); saved = true; failureNotified = false;
  status('已清除本账号的本地练习。新的练习仍会自动保存。');
  emit('progress-cleared'); emit('progress');
  return true;
}
export function removeMaterialProgress(ids) {
  const removed = new Set(ids.map(Number));
  if (!removed.size || !key()) return;
  removed.forEach(id => state.sessions.delete(id));
  try {
    const snapshot = JSON.parse(localStorage.getItem(key()) || 'null');
    if (snapshot?.version === VERSION && Array.isArray(snapshot.sessions)) {
      snapshot.sessions = snapshot.sessions.filter(entry => !removed.has(Number(entry?.[0])));
      localStorage.setItem(key(), JSON.stringify(snapshot));
    }
  } catch {
    // A later save will replace a malformed snapshot with the remaining sessions.
  }
  emit('progress');
}
events.addEventListener('reset', () => {
  saved = true; failureNotified = false;
  status('练习自动保存在当前浏览器，按账号区分；不跨设备同步。');
});
