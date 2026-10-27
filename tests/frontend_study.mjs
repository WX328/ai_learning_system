// DOM-event integration checks without a browser, network, or user data.
// Run: node --experimental-vm-modules tests/frontend_study.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';

const elements = new Map(), anonymous = [];
class Classes {
  constructor(value='') { this.values=new Set(value.split(/\s+/).filter(Boolean)); }
  contains(name) { return this.values.has(name); }
  add(name) { this.values.add(name); }
  remove(name) { this.values.delete(name); }
  toggle(name,on=!this.contains(name)) { on ? this.add(name) : this.remove(name); return on; }
}
function matches(element,selector) {
  if (selector.startsWith('.')) return selector.slice(1).split('.').every(name => element.classList.contains(name));
  const data = selector.match(/^\[data-([\w-]+)(?:="([^"]*)")?\]$/);
  if (data) {
    const key=data[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
    return key in element.dataset && (data[2] === undefined || element.dataset[key] === data[2]);
  }
  return false;
}
class Element extends EventTarget {
  constructor(id='',classes='') { super(); this.id=id; this.classList=new Classes(classes); this.dataset={}; this.value=''; this.disabled=false; this.open=false; this._html=''; this.textContent=''; }
  set innerHTML(value) { this._html=value; parse(value); }
  get innerHTML() { return this._html; }
  set className(value) { this.classList=new Classes(value); }
  get className() { return [...this.classList.values].join(' '); }
  setAttribute() {}
  removeAttribute() {}
  closest(selector) { return matches(this,selector) ? this : null; }
  scrollIntoView() {}
  focus() {}
  showModal() { this.open=true; }
  close() { this.open=false; this.dispatchEvent(new Event('close')); }
  querySelector(selector) { return document.querySelector(selector); }
  insertAdjacentHTML(_,html) { this._html+=html; parse(html); }
}
function parse(html) {
  for (const match of html.matchAll(/<([a-z][\w-]*)\b([^>]*)>/gi)) {
    const attrs=Object.fromEntries([...match[2].matchAll(/([\w-]+)="([^"]*)"/g)].map(a=>[a[1],a[2]]));
    if (!attrs.id && !attrs.class && !Object.keys(attrs).some(k=>k.startsWith('data-'))) continue;
    const element=new Element(attrs.id || '',attrs.class || '');
    for (const [key,value] of Object.entries(attrs)) if (key.startsWith('data-')) element.dataset[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=value;
    if (attrs.value) element.value=attrs.value;
    if (attrs.id) elements.set(attrs.id,element); else anonymous.push(element);
  }
}
const html=fs.readFileSync('frontend/index.html','utf8');
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
assert.equal(ids.length,new Set(ids).size,'HTML IDs must be unique');
parse(html);
const document=new EventTarget();
document.getElementById=id=>elements.get(id) || null;
document.querySelectorAll=selector=>[...elements.values(),...anonymous].filter(e=>matches(e,selector));
document.querySelector=selector=>document.querySelectorAll(selector)[0] || null;
const storage=new Map();
const localStorage={getItem:key=>storage.get(key) ?? null,setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)};
const summary={level:2,total_xp:120,level_progress:13,xp_remaining:130,next_level_xp:250,answered_count:10,correct_rate:50,pending_mistakes:9};
const mistakes=Array.from({length:9},(_,i)=>({id:i+1,material_id:24,material_title:'Agent notes',topic_name:'Core',difficulty:2,question:i===0 ? '<img src=x onerror=alert(1)> What is an Agent?' : 'Question '+(i+1),created_at:'2026-09-10T01:00:00+00:00',options:{A:'one',B:'two',C:'three',D:'four'},user_answer:'A',correct_answer:'B',explanation:'The explanation',review_count:0,resolved:false}));
const map=[{id:24,title:'Agent notes',chunk_count:2,embedded_count:2,linked_count:1,topics:[{id:81,name:'Core',description:'Core topic',mastery_score:50,mastery_status:'weak',mastery_reason:'<script>样本偏少</script> · 2 道不同题目',attempt_count:2,chunk_count:1},{id:82,name:'Memory',description:'Memory topic',mastery_score:null,attempt_count:0,chunk_count:0}]}];
const records=[{id:'answer-1',type:'answer',title:'What is an Agent?',material_title:'Agent notes',material_id:24,created_at:'2026-09-10T01:00:00+00:00',detail:'A detailed answer',is_correct:true,earned_xp:20}];
let failedReview=true, failRecords=false, delayedSummary=null;
const requests=[];
const fetch=async (url,options={})=>{
  requests.push({url,...options});
  if (url==='/study/summary' && delayedSummary) return delayedSummary;
  let data,status=200;
  if (url.includes('/review')) {
    if (failedReview) { failedReview=false; status=503; data={detail:'temporary error'}; }
    else { data={is_correct:true,correct_answer:'B',explanation:'The explanation'}; }
  } else if (url==='/study/records' && failRecords) { status=503; data={detail:'records unavailable'}; }
  else data=({'/study/summary':summary,'/study/mistakes':mistakes,'/study/map':map,'/study/records':records,'/learning-materials/24/topics':map[0].topics}[url]);
  assert.notEqual(data,undefined,'Unexpected API: '+url);
  return {ok:status===200,status,json:async()=>structuredClone(data)};
};
const context=vm.createContext({document,localStorage,fetch,EventTarget,Event,DOMException,AbortController,setTimeout,clearTimeout,Intl,crypto:webcrypto,FormData:class {constructor(form){this.form=form;} get(key){return this.form.values?.[key];}},console});
const modules=new Map();
function moduleFor(filename) {
  filename=filename.replace(/[?#].*$/,'');
  filename=path.resolve(filename);
  if (!modules.has(filename)) modules.set(filename,new vm.SourceTextModule(fs.readFileSync(filename,'utf8'),{context,identifier:filename}));
  return modules.get(filename);
}
const app=moduleFor('frontend/app.js');
await app.link((specifier,ref)=>moduleFor(path.resolve(path.dirname(ref.identifier),specifier)));
// Link the complete frontend graph to check imports, then evaluate the new module only.
const study=moduleFor('frontend/study.js');
await study.evaluate();
const core=moduleFor('frontend/core.js').namespace;
study.namespace.initStudy();
const el=id=>elements.get(id);
const settle=async()=>{ for(let i=0;i<12;i++) await new Promise(resolve=>setImmediate(resolve)); };
const change=(id,value,type='change')=>{ el(id).value=value; el(id).dispatchEvent(new Event(type)); };
async function click(dataset) {
  const target=new Element(); target.dataset=dataset;
  const event=new Event('click'); Object.defineProperty(event,'target',{value:target});
  document.dispatchEvent(event); await settle();
}
core.state.user={id:1,username:'learner'}; core.state.token='test';
core.state.materials=[{id:24,title:'Agent notes',content:'content',material_type:'text'}];
el('mistake-status').value='pending'; el('map-filter').value='all';
core.go('home'); await settle();
assert.match(el('growth-card').innerHTML,/120/);
assert.equal(el('account-level').textContent,'Lv.2 · 120 XP');
assert.equal(el('account-level').classList.contains('hidden'),false);

core.go('mistakes'); await settle();
assert.match(el('mistake-list').innerHTML,/&lt;img/,'Question HTML is escaped');
assert.doesNotMatch(el('mistake-list').innerHTML,/<img src=x/);
assert.match(el('mistake-pagination').innerHTML,/共 9 条/);
await click({paginate:'mistakes',step:'1'});
assert.match(el('mistake-list').innerHTML,/Question 9/);
change('mistake-search','What','input');
assert.match(el('mistake-pagination').innerHTML,/共 1 条/);
assert.doesNotMatch(el('mistake-list').innerHTML,/Question 9/);

await click({review:'1'});
assert.equal(el('review-dialog').open,true);
assert.doesNotMatch(el('review-body').innerHTML,/The explanation/);
const form=el('review-form'); form.values={answer:'B'};
const submit=new Event('submit'); Object.defineProperty(submit,'target',{value:form});
el('review-body').dispatchEvent(submit); await settle();
assert.match(el('review-feedback').textContent,/保存未确认/);
assert.equal(el('review-submit').disabled,false);
el('review-body').dispatchEvent(submit); await settle();
assert.match(el('review-feedback').textContent,/回答正确/);
const posts=requests.filter(r=>r.url.includes('/review'));
assert.equal(posts.length,2); assert.equal(posts[0].body,posts[1].body,'Retry reuses submission ID');
el('review-dialog').close();

failRecords=true; core.go('records'); await settle();
assert.match(el('records-status').textContent,/加载失败/);
failRecords=false; await click({studyRefresh:'records'});
assert.match(el('record-list').innerHTML,/What is an Agent/);
change('record-from','2026-09-11'); change('record-to','2026-09-10');
assert.match(el('records-status').textContent,/开始日期不能晚于/);
change('record-from','2026-09-09');
assert.match(el('record-pagination').innerHTML,/共 1 条/);

core.go('map'); await settle();
assert.match(el('map-content').innerHTML,/Core/);
assert.match(el('map-content').innerHTML,/50\/100/);
assert.match(el('map-content').innerHTML,/掌握度评估依据/);
assert.match(el('map-content').innerHTML,/&lt;script&gt;样本偏少/);
assert.doesNotMatch(el('map-content').innerHTML,/<script>/);
await click({mapNode:'82'});
assert.match(el('map-content').innerHTML,/此知识点尚未关联文本/);
assert.match(el('map-content').innerHTML,/data-map-open="practice" disabled/);
change('map-filter','weak');
assert.doesNotMatch(el('map-content').innerHTML,/data-map-node="82"/);
await click({mapOpen:'practice'});
assert.equal(core.state.material.id,24);
assert.equal(core.state.topicId,81);
assert.equal(el('page-label').textContent,'练习中心');

let resolveSummary;
delayedSummary=new Promise(resolve=>{resolveSummary=resolve;});
core.emit('study-updated'); await settle();
core.resetSession();
resolveSummary({ok:true,status:200,json:async()=>summary}); await settle();
assert.equal(el('growth-card').innerHTML,'','Late response cannot restore another account data');
assert.equal(el('account-level').classList.contains('hidden'),true);
assert.equal(el('mistake-list').innerHTML,'');
assert.equal(el('map-content').innerHTML,'');
console.log('PASS: module imports, progress, filtering/pagination, escaping, review retry, errors, dates, map navigation, logout race.');
