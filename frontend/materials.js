import { $, state, events, emit, api, esc, report, busy, go, toast } from './core.js';
import { removeMaterialProgress } from './progress.js';
let selectionVersion = 0;
let loadVersion = 0;
let reindexMaterialId = null;
let deleteMaterialId = null;
const typeLabels = {document:'文档',text:'文本',note:'笔记',article:'文章'};
export const materialIds = material => material ? [material.id, ...(material.duplicate_ids || [])] : [];
export const findMaterial = id => state.materials.find(material => materialIds(material).includes(Number(id)));
function displayTitle(material) {
  const sameName = state.materials.filter(item => item.title === material.title).length > 1;
  return material.title + (sameName ? ' · 内容版本 #' + material.id : '');
}
export function upsertMaterial(material) {
  state.materials = state.materials.filter(item => !(material.duplicate_ids || []).includes(item.id));
  const index = state.materials.findIndex(item => item.id === material.id);
  if (index === -1) state.materials.push(material);
  else state.materials[index] = material;
  renderMaterials();
}
export function renderMaterials() {
  const query = $('material-search').value.trim().toLocaleLowerCase();
  const type = $('material-filter').value;
  const materials = [...state.materials].sort((a,b) => b.id - a.id)
    .filter(item => (!query || item.title.toLocaleLowerCase().includes(query)) && (!type || item.material_type === type));
  $('nav-count').textContent = state.materials.length;
  $('material-count').textContent = state.materials.length;
  $('topic-count').textContent = state.material ? (state.selecting ? '…' : state.topics.length) : '—';
  $('current-material-summary').textContent = state.material?.title || '选一份资料，开始吧';
  $('material-list').innerHTML = materials.length ? materials.map(material => {
    const selected = materialIds(material).includes(state.material?.id);
    return '<article class="surface material-card' + (selected ? ' selected' : '') + '">' +
      '<div class="card-meta"><span class="file-icon">' + esc(typeLabels[material.material_type] || '资料') + '</span>' +
      (selected ? '<span class="badge">正在学习</span>' : '<span>' + (String(material.content || '').length).toLocaleString() + ' 字</span>') + '</div>' +
      '<h3>' + esc(displayTitle(material)) + '</h3><p class="material-excerpt">' + esc((material.content || '暂无内容预览').slice(0,180)) + '</p>' +
      '<div class="card-actions"><button class="secondary" data-material="' + material.id + '" data-destination="chat">问答 →</button>' +
      '<button class="quiet" data-material="' + material.id + '" data-destination="practice">练习</button>' +
      '<button class="link-button" data-reindex="' + material.id + '">重建向量</button>' +
      '<button class="link-button delete-material" data-delete-material="' + material.id + '">删除</button>' +
      '<button class="link-button preview-button" data-preview="' + material.id + '">预览</button></div></article>';
  }).join('') : '<div class="surface empty"><h3>' + (state.materials.length ? '没有找到匹配的资料' : '知识，从第一份资料开始') +
    '</h3><p>' + (state.materials.length ? '试试其他标题，或切换资料类型。' : '导入笔记、文章或课程文档，开始提问和练习。') + '</p>' +
    (!state.materials.length ? '<button class="primary" data-import>＋ 导入第一份资料</button>' : '') + '</div>';
  document.querySelectorAll('.material-select').forEach(select => {
    select.innerHTML = '<option value="">请选择资料</option>' + [...state.materials].sort((a,b) => b.id-a.id).map(material =>
      '<option value="' + material.id + '">' + esc(displayTitle(material)) + '</option>').join('');
    select.value = findMaterial(state.material?.id)?.id || '';
  });
  emit('materials');
}
export async function selectMaterial(id, force = false, exact = false) {
  const canonical = findMaterial(id);
  if (!canonical) return;
  // Old saved exercises keep their original material/topic IDs. They share one
  // library entry but remain accessible via the home page's resume action.
  const selectedId = exact || state.sessions.has(Number(id)) ? Number(id) : canonical.id;
  const material = {...canonical, id:selectedId, duplicate_ids:materialIds(canonical).filter(value => value !== selectedId)};
  if (!force && material.id === state.material?.id && !state.selecting) return;
  const version = ++selectionVersion;
  state.material = material; state.topics = []; state.topicId = null; state.selecting = true;
  renderMaterials(); emit('material');
  try {
    const topics = await api('/learning-materials/' + material.id + '/topics');
    if (version !== selectionVersion) return;
    state.topics = Array.isArray(topics) ? topics : [];
    localStorage.setItem('learning_material_' + state.user.id, material.id);
  } catch (error) {
    if (version === selectionVersion) report(error);
  } finally {
    if (version === selectionVersion) {
      state.selecting = false; renderMaterials(); emit('topics'); emit('topic');
    }
  }
}
export async function loadMaterials() {
  const version = ++loadVersion;
  $('library-status').textContent = '正在加载资料…';
  try {
    const materials = await api('/learning-materials');
    if (version !== loadVersion) return;
    state.materials = Array.isArray(materials) ? materials : [];
    renderMaterials();
    const remembered = Number(localStorage.getItem('learning_material_' + state.user.id));
    const selectedId = findMaterial(state.material?.id) ? state.material.id : findMaterial(remembered) ? remembered : [...state.materials].sort((a,b) => b.id-a.id)[0]?.id;
    if (selectedId) await selectMaterial(selectedId, true);
    else {
      state.material = null; state.topics = []; state.topicId = null;
      renderMaterials(); emit('material'); emit('topics');
    }
    if (version === loadVersion) $('library-status').textContent = state.materials.length ? '共 ' + state.materials.length + ' 份资料 · 选择一份，继续学习' : '';
  } catch (error) {
    if (version === loadVersion && error.name !== 'AbortError') $('library-status').textContent = '加载失败：' + error.message + '。可点击“刷新”重试。';
    report(error);
  }
}
export function initMaterials() {
  $('material-search').addEventListener('input', renderMaterials);
  $('material-filter').addEventListener('change', renderMaterials);
  $('refresh-materials').addEventListener('click', async event => {
    const button = event.currentTarget; busy(button,true,'加载中…');
    await loadMaterials(); busy(button,false);
  });
  document.querySelectorAll('.material-select').forEach(select => select.addEventListener('change', event => {
    if (event.target.value) selectMaterial(event.target.value);
    else event.target.value = findMaterial(state.material?.id)?.id || '';
  }));
  $('material-list').addEventListener('click', async event => {
    const target = event.target.closest('[data-material]');
    if (target) { await selectMaterial(target.dataset.material); if (state.token) go(target.dataset.destination); }
    const preview = event.target.closest('[data-preview]');
    if (preview) {
      const material = state.materials.find(item => item.id === Number(preview.dataset.preview));
      if (!material) return;
      $('preview-title').textContent = material.title;
      $('preview-content').textContent = material.content || '暂无可预览内容';
      $('preview-dialog').showModal();
    }
    const reindex = event.target.closest('[data-reindex]');
    if (reindex) {
      const material = findMaterial(reindex.dataset.reindex);
      if (!material) return;
      reindexMaterialId = material.id;
      $('reindex-title').textContent = '重新建立向量索引';
      $('reindex-description').textContent = '将使用当前百炼模型重新生成“' + displayTitle(material) + '”的全部向量。知识点关联会保留；这会调用百炼 API 并产生相应费用。';
      $('confirm-reindex').textContent = '开始重建';
      if (!$('reindex-dialog').open) $('reindex-dialog').showModal();
    }
    const deletion = event.target.closest('[data-delete-material]');
    if (deletion) {
      const material = findMaterial(deletion.dataset.deleteMaterial);
      if (!material) return;
      deleteMaterialId = material.id;
      $('delete-material-title').textContent = '删除这份资料？';
      $('delete-material-description').textContent = '“' + displayTitle(material) + '”及其隐藏的重复副本会被永久删除。相关文本片段、知识点、问答、题目、答题记录和学习教练会话也会被清除；账户 XP、等级和成就会保留。';
      $('confirm-delete-material').textContent = '永久删除';
      if (!$('delete-material-dialog').open) $('delete-material-dialog').showModal();
    }
  });
  $('confirm-reindex').addEventListener('click', async event => {
    if (!reindexMaterialId) return;
    const button = event.currentTarget;
    busy(button, true, '正在生成向量…');
    try {
      const result = await api('/learning-materials/' + reindexMaterialId + '/index?force=true', {method:'POST'});
      $('reindex-dialog').close();
      toast('已用 ' + (result.embedding_model || '当前模型') + ' 重建 ' + result.chunk_count + ' 个文本片段的向量');
      emit('study-updated');
      await loadMaterials();
    } catch (error) {
      report(error);
    } finally {
      busy(button, false);
    }
  });
  $('reindex-dialog').addEventListener('close', () => { reindexMaterialId = null; });
  $('confirm-delete-material').addEventListener('click', async event => {
    if (!deleteMaterialId) return;
    const button = event.currentTarget;
    busy(button, true, '正在删除…');
    try {
      const result = await api('/learning-materials/' + deleteMaterialId, {method:'DELETE'});
      const ids = Array.isArray(result.deleted_material_ids) ? result.deleted_material_ids.map(Number) : [deleteMaterialId];
      removeMaterialProgress(ids);
      ids.forEach(id => state.conversations.delete(id));
      if (ids.includes(Number(state.material?.id))) {
        state.material = null; state.topics = []; state.topicId = null; state.selecting = false;
        localStorage.removeItem('learning_material_' + state.user.id);
        emit('material'); emit('topics'); emit('topic');
      }
      $('delete-material-dialog').close();
      toast('已删除 ' + Number(result.deleted_material_count || ids.length) + ' 份资料及其相关学习数据');
      emit('study-updated');
      await loadMaterials();
    } catch (error) {
      report(error);
    } finally {
      busy(button, false);
    }
  });
  $('delete-material-dialog').addEventListener('close', () => { deleteMaterialId = null; });
  events.addEventListener('reset', () => {
    selectionVersion++; loadVersion++;
    $('material-search').value = ''; $('material-filter').value = ''; $('library-status').textContent = '';
    $('preview-title').textContent = '资料预览'; $('preview-content').textContent = '';
    reindexMaterialId = null;
    deleteMaterialId = null;
    renderMaterials();
  });
}
