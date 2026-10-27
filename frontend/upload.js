import { $, state, events, emit, api, json, esc, toast, report } from './core.js';
import { upsertMaterial, selectMaterial, renderMaterials } from './materials.js';
let mode = 'upload', tasks = [], processing = false;
function renderTasks() {
  if (!tasks.length) { $('upload-progress').innerHTML = ''; return; }
  const complete = tasks.filter(task => task.done).length;
  const failed = tasks.filter(task => task.error).length;
  // Each confirmed API stage contributes one step; no simulated time progress.
  const steps = tasks.reduce((total,task) => total + (task.done ? 3 : task.indexed ? 2 : task.material?.id ? 1 : 0),0);
  const percent = Math.floor(steps / (tasks.length * 3) * 100);
  const active = tasks.find(task => task.active);
  const title = complete === tasks.length ? '全部导入完成' : processing ? '正在导入资料' : failed ? '部分资料未完成' : '导入已暂停';
  const detail = active ? active.name + ' · ' + active.status : complete === tasks.length
    ? '资料已整理完成，可以开始学习了。' : processing ? '正在准备导入…' : '可在下方重试未完成的资料，已完成的阶段会保留。';
  const summary = '已完成 ' + complete + ' / ' + tasks.length + ' 份' + (failed ? ' · ' + failed + ' 份失败' : '');
  $('upload-progress').innerHTML = '<section class="import-progress-card' + (active ? ' is-processing' : '') + '">' +
    '<div class="import-progress-heading"><b>' + title + '</b><strong>' + percent + '%</strong></div>' +
    '<progress value="' + steps + '" max="' + (tasks.length * 3) + '" aria-label="资料导入阶段进度" aria-valuetext="' + percent + '%，' + summary + '"></progress>' +
    '<div class="import-progress-summary">' + summary + '</div><p class="import-progress-detail">' + esc(detail) + '</p>' +
    '<small>进度按保存资料、建立索引、整理知识点三个阶段计算；单个阶段耗时可能较长。</small></section>' +
    tasks.map((task,index) =>
    '<div class="upload-row"><b>' + esc(task.name) + '</b><span class="' + (task.error ? 'upload-error' : '') + '">' +
    esc(task.status) + '</span>' + (task.error ? '<button class="quiet" data-retry="' + index + '"' + (processing ? ' disabled' : '') + '>重试这份资料</button>' : '') + '</div>').join('');
}
function switchMode(value) {
  if (processing) return;
  mode = value;
  document.querySelectorAll('[data-mode]').forEach(button => {
    const active = button.dataset.mode === mode;
    button.classList.toggle('active',active); button.setAttribute('aria-pressed',String(active));
  });
  $('upload-fields').classList.toggle('hidden',mode !== 'upload');
  $('paste-fields').classList.toggle('hidden',mode !== 'paste');
  $('material-title').required = mode === 'paste';
  $('material-content').required = mode === 'paste';
}
function lock(on) {
  processing = on; $('import-fields').disabled = on;
  document.querySelectorAll('[data-mode]').forEach(button => button.disabled = on);
  $('import-submit').textContent = on ? '正在整理，请稍候…' : '导入并整理知识点 →';
}
function showFiles() {
  const files = Array.from($('material-file').files);
  $('file-name').textContent = files.length ? '已选择 ' + files.length + ' 个文件：' + files.map(file => file.name).join('、') : '尚未选择文件';
}
async function prepare(task) {
  task.error = false; task.active = true;
  try {
    if (!task.material) {
      task.status = task.file ? '正在上传…' : '正在保存…'; renderTasks();
      if (task.file) {
        const form = new FormData(); form.append('files',task.file);
        // The existing FastAPI route reads title/type from query parameters.
        const query = new URLSearchParams({material_type:task.type});
        if (task.prefix) query.set('title',task.prefix);
        const response = await api('/learning-materials/upload?' + query.toString(),{method:'POST',body:form});
        task.material = Array.isArray(response) ? response[0] : response;
      } else {
        task.material = await api('/learning-materials',{method:'POST',...json(task.text)});
      }
      if (!task.material?.id) throw new Error('上传接口没有返回有效资料');
      task.reused = task.material.reused === true;
      task.indexed = task.material.indexed === true;
      upsertMaterial(task.material);
    }
    if (!task.indexed) {
      task.status = '已保存 · 正在建立检索索引…'; renderTasks();
      await api('/learning-materials/' + task.material.id + '/index',{method:'POST'});
      task.indexed = true;
    }
    task.status = task.material.has_topics ? '资料已存在，读取已有知识点…' : '正在整理知识点…'; renderTasks();
    task.topics = task.material.has_topics
      ? await api('/learning-materials/' + task.material.id + '/topics')
      : await api('/learning-materials/' + task.material.id + '/extract-topics',{method:'POST'});
    task.material.indexed = true; task.material.has_topics = true;
    task.material.topic_count = task.topics.length;
    task.status = (task.reused ? '资料已存在，已复用' : '已完成') + ' · ' + task.topics.length + ' 个知识点';
    task.done = true;
    emit('study-updated');
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    task.error = true; task.status = '未完成：' + error.message;
  } finally { task.active = false; }
  renderTasks();
}
async function processTasks(queue) {
  if (processing) return;
  const epoch = state.epoch;
  lock(true); renderTasks();
  try {
    for (const task of queue) {
      await prepare(task);
      if (epoch !== state.epoch) return;
    }
    const complete = tasks.filter(task => task.done);
    if (complete.length && !state.material) await selectMaterial(complete[0].material.id);
    if (state.material) {
      const current = complete.find(task => task.material.id === state.material.id);
      if (current) { state.topics = current.topics; renderMaterials(); emit('topics'); }
    }
    if (epoch === state.epoch) {
      toast(tasks.some(task => task.error) ? '部分资料未完成，可在下方逐份重试' : '资料已整理完成，关闭窗口后即可开始学习',tasks.some(task => task.error));
    }
  } catch (error) { report(error); }
  finally { if (epoch === state.epoch) { lock(false); renderTasks(); } }
}
async function importMaterials(event) {
  event.preventDefault();
  if (processing) return;
  if (mode === 'upload') {
    const files = Array.from($('material-file').files);
    if (!files.length) return toast('请先选择至少一个文件',true);
    tasks = files.map(file => ({file,name:file.name,prefix:$('upload-title').value.trim(),type:$('material-type').value,status:'等待处理'}));
  } else {
    const title = $('material-title').value.trim(), content = $('material-content').value.trim();
    if (!title || !content) return toast('请填写标题和资料内容',true);
    tasks = [{name:title,status:'等待处理',text:{title,content,material_type:$('material-type').value}}];
  }
  await processTasks(tasks);
}
export function initUpload() {
  $('open-import').addEventListener('click', () => $('import-dialog').showModal());
  document.addEventListener('click', event => {
    if (event.target.closest('[data-import]')) $('import-dialog').showModal();
    const button = event.target.closest('[data-mode]');
    if (button) switchMode(button.dataset.mode);
  });
  $('material-file').addEventListener('change',showFiles);
  ['dragenter','dragover'].forEach(name => $('dropzone').addEventListener(name, event => {
    event.preventDefault(); if (!processing) $('dropzone').classList.add('dragover');
  }));
  ['dragleave','drop'].forEach(name => $('dropzone').addEventListener(name, event => {
    event.preventDefault(); $('dropzone').classList.remove('dragover');
    if (name === 'drop' && !processing && event.dataTransfer.files.length) {
      const transfer = new DataTransfer();
      Array.from(event.dataTransfer.files).forEach(file => transfer.items.add(file));
      $('material-file').files = transfer.files; showFiles();
    }
  }));
  $('material-form').addEventListener('submit', importMaterials);
  $('upload-progress').addEventListener('click', event => {
    const button = event.target.closest('[data-retry]');
    if (button && !processing) processTasks([tasks[Number(button.dataset.retry)]]);
  });
  events.addEventListener('reset', () => {
    tasks = []; lock(false); $('material-form').reset(); switchMode('upload'); showFiles(); renderTasks();
  });
  switchMode('upload');
}
