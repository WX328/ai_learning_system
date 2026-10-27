import { $, state, events, emit, api, json, toast, report, busy, resetSession, go } from './core.js';
import { initMaterials, loadMaterials } from './materials.js';
import { initChat } from './chat.js';
import { initPractice } from './practice.js';
import { initUpload } from './upload.js';
import { initHome, loadRecentHistory } from './home.js';
import { restoreProgress, progressSaved } from './progress.js';
import { initStudy } from './study.js';
import { initCoach } from './coach.js';
import { initWorkspaceNavigation } from './workspace.js';
import { initAdmin } from './admin.js';

let registerMode = false, authPending = false;
function setAuthMode(register) {
  registerMode = register;
  $('auth-title').textContent = register ? '开启学习旅程' : '欢迎回来';
  $('auth-description').textContent = register ? '创建账号，密码至少 15 个字符，可使用空格和中文。' : '登录，继续你的学习旅程。';
  $('auth-submit').textContent = register ? '创建账号 →' : '登录 →';
  $('register-button').textContent = register ? '已有账号？返回登录' : '还没有账号？创建账号';
  $('confirm-label').classList.toggle('hidden',!register);
  $('confirm-password').required = register;
  $('password').autocomplete = register ? 'new-password' : 'current-password';
  $('password').minLength = register ? 15 : 0;
  $('password').maxLength = register ? 128 : 524288;
  $('auth-error').textContent = '';
}
function showAuth() {
  $('workspace-view').classList.add('hidden'); $('auth-view').classList.remove('hidden');
}
async function showWorkspace() {
  $('auth-view').classList.add('hidden'); $('workspace-view').classList.remove('hidden');
  $('current-user').textContent = state.user.username;
  emit('identity');
  restoreProgress();
  go('home');
  await Promise.all([loadMaterials(), loadRecentHistory()]);
}
async function authenticate(event) {
  event.preventDefault();
  if (authPending) return;
  const username = $('username').value.trim(), password = $('password').value;
  if (!username || !password) { $('auth-error').textContent = '请填写用户名和密码'; return; }
  if (registerMode && (username.length < 3 || password.length < 15)) {
    $('auth-error').textContent = '用户名至少 3 个字符，密码至少 15 个字符'; return;
  }
  if (registerMode && password !== $('confirm-password').value) {
    $('auth-error').textContent = '两次输入的密码不一致'; return;
  }
  authPending = true; $('auth-error').textContent = '';
  busy($('auth-submit'),true,registerMode ? '正在创建…' : '正在登录…'); $('register-button').disabled = true;
  try {
    if (registerMode) {
      await api('/users',{method:'POST',...json({username,password})});
      setAuthMode(false); toast('账号创建成功，请登录');
    } else {
      const response = await api('/auth/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({username,password})});
      state.token = response.access_token;
      try { state.user = await api('/auth/me'); }
      catch (error) { resetSession(); throw error; }
      localStorage.setItem('learning_token',state.token);
      $('password').value = ''; $('confirm-password').value = '';
      await showWorkspace();
    }
  } catch (error) { if (error.name !== 'AbortError') $('auth-error').textContent = error.message; }
  finally {
    authPending = false; busy($('auth-submit'),false); $('register-button').disabled = false;
    $('auth-submit').textContent = registerMode ? '创建账号 →' : '登录 →';
  }
}
initMaterials(); initChat(); initPractice(); initUpload(); initHome(); initStudy(); initCoach();
initWorkspaceNavigation();
initAdmin();
$('login-form').addEventListener('submit',authenticate);
$('register-button').addEventListener('click', () => { if (!authPending) setAuthMode(!registerMode); });
$('logout-button').addEventListener('click', () => { resetSession(); showAuth(); });
$('check-connection').addEventListener('click', async event => {
  const button = event.currentTarget; busy(button,true,'检查中…');
  try { await api('/'); toast('服务连接正常'); } catch (error) { report(error); }
  finally { busy(button,false); }
});
document.addEventListener('click', event => {
  const page = event.target.closest('[data-page]');
  if (page) go(page.dataset.page);
  const close = event.target.closest('[data-close]');
  if (close) $(close.dataset.close).close();
});
events.addEventListener('reset', () => {
  document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
  $('login-form').reset(); $('current-user').textContent = '';
  $('api-status').textContent = '○ 尚未检查连接'; $('toast').classList.add('hidden');
  setAuthMode(false); go('home'); showAuth();
});
events.addEventListener('expired', () => { $('auth-error').textContent = '登录已过期，请重新登录'; });
window.addEventListener('offline', () => { $('api-status').textContent = '○ 网络已断开'; });
window.addEventListener('beforeunload', event => {
  const unfinished = [...state.sessions.values()].some(session => session.pending || (!progressSaved() && session.results.length < session.questions.length));
  if ($('import-fields').disabled || unfinished) { event.preventDefault(); event.returnValue = ''; }
});
if (state.token) {
  api('/auth/me').then(user => { state.user = user; return showWorkspace(); }).catch(error => {
    resetSession();
    if (error.name !== 'AbortError') $('auth-error').textContent = error.message;
  });
}
