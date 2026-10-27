// Run: node --experimental-vm-modules tests/frontend_recommendation.mjs
// Executes the real recommendation + practice modules with DOM events and mocked HTTP.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';

const elements = new Map();
class Element extends EventTarget {
  constructor(id, classes = '') {
    super(); this.id=id; this.value=''; this.disabled=false; this.dataset={}; this._html='';
    const names = new Set(classes.split(/\s+/));
    this.classList = {contains:n=>names.has(n), toggle:(n,on=!names.has(n))=>on ? names.add(n) : names.delete(n)};
  }
  set innerHTML(value) {
    for (const match of this._html.matchAll(/id="([^"]+)"/g)) elements.delete(match[1]);
    this._html=value; parse(value);
  }
  get innerHTML() { return this._html; }
  setAttribute(name,value) { this[name]=value; }
  scrollIntoView() {}
  focus() {}
  reset() {}
}
function parse(html) {
  for (const match of html.matchAll(/<[^>]*\bid="([^"]+)"[^>]*>/g)) {
    elements.set(match[1],new Element(match[1],match[0].match(/class="([^"]*)"/)?.[1] || ''));
  }
}
parse(fs.readFileSync('frontend/index.html','utf8'));
const el=id=>elements.get(id);
const events = new EventTarget();
const state={user:{id:1},token:'test',epoch:0,material:null,topics:[],topicId:null,selecting:false,sessions:new Map()};
const requests=[];
const baseline={material_id:24,topic:{id:81,name:'依赖注入'},mastery_score:null,recent_correct_rate:null,
  recent_attempt_count:0,attempt_count:0,recommended_difficulty:2,has_history:false,reason:'暂无答题记录，先从基础难度开始。'};
let response=structuredClone(baseline), fail=false, held=null;
const api=async(url,options)=>{
  requests.push({url,options});
  if (url.startsWith('/adaptive/recommendation')) {
    if (held) return held;
    if (fail) throw Object.assign(new Error('服务暂不可用'),{status:503});
    return structuredClone(response);
  }
  if (url.startsWith('/adaptive/next-question')) return {topic:{id:81,name:'依赖注入',attempt_count:0},
    question:{id:12,material_id:24,topic_id:81,question:'Choose A',option_a:'one',option_b:'two',
      option_c:'three',option_d:'four',difficulty:2}};
  if (url==='/questions/12/answer') return {question_id:12,user_answer:'A',correct_answer:'A',is_correct:true,earned_xp:20};
  throw new Error('Unexpected API '+url);
};
const emit=name=>events.dispatchEvent(new Event(name));
const esc=value=>String(value ?? '').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const context=vm.createContext({Event,EventTarget,console,crypto:webcrypto,
  window:{matchMedia:()=>({matches:true})},FormData:class {get(){return 'A';}}});
const core=new vm.SyntheticModule(['$','state','events','emit','api','esc','json','report','toast','requireMaterial','setTopic'],function(){
  for (const [name,value] of Object.entries({$:el,state,events,emit,api,esc,json:data=>({body:JSON.stringify(data)}),
    report:()=>{},toast:()=>{},requireMaterial:()=>!!state.material,setTopic:()=>{}})) this.setExport(name,value);
},{context});
const progress=new vm.SyntheticModule(['saveProgress'],function(){this.setExport('saveProgress',()=>{});},{context});
const modules=new Map();
function moduleFor(filename) {
  filename=path.resolve(filename);
  if (!modules.has(filename)) modules.set(filename,new vm.SourceTextModule(fs.readFileSync(filename,'utf8'),{context,identifier:filename}));
  return modules.get(filename);
}
const practice=moduleFor('frontend/practice.js');
await practice.link((specifier,ref)=>specifier==='./core.js' ? core : specifier==='./progress.js' ? progress : moduleFor(path.resolve(path.dirname(ref.identifier),specifier)));
await practice.evaluate();
const recommendation=moduleFor('frontend/recommendation.js').namespace;
const settle=async()=>{for(let i=0;i<10;i++) await new Promise(resolve=>setImmediate(resolve));};
const click=async id=>{el(id).dispatchEvent(new Event('click'));await settle();};
const markup=()=>el('recommendation-content').innerHTML;
const previewCount=()=>requests.filter(r=>r.url.startsWith('/adaptive/recommendation')).length;
practice.namespace.initPractice();
assert.match(markup(),/选择资料/);
assert.equal(el('adaptive-button').disabled,true);
assert.equal(requests.length,0,'No data request without a selected material');

state.material={id:24,title:'Notes'};
el('practice-panel').classList.toggle('hidden',false);
el('quiz-count').value='1'; el('quiz-difficulty').value='2';
let finish;
held=new Promise(resolve=>{finish=resolve;});
emit('material');
assert.match(markup(),/正在读取/);
assert.equal(el('adaptive-button').disabled,true);
for(let i=0;i<5;i++) {emit('page');el('recommendation-refresh').dispatchEvent(new Event('click'));}
assert.equal(previewCount(),1,'Repeated clicks and page events share the in-flight read');
held=null;finish(structuredClone(baseline));await settle();
assert.match(markup(),/尚未评估/);assert.match(markup(),/暂无答题记录/);
assert.doesNotMatch(markup(),/0%/,'No history is never shown as zero accuracy');
assert.match(markup(),/★★☆☆☆/);assert.equal(el('adaptive-button').disabled,false);
emit('page');await settle();assert.equal(previewCount(),1,'Returning without changes reuses the preview');

for (const [rate,difficulty] of [[0,1],[.4,2],[.6,3],[.8,4],[1,5]]) {
  response={...baseline,has_history:true,recent_correct_rate:rate,recent_attempt_count:5,mastery_score:rate*100,recommended_difficulty:difficulty};
  await click('recommendation-refresh');
  assert.match(markup(),new RegExp(Math.round(rate*100)+'%'));
  assert.match(markup(),new RegExp('★'.repeat(difficulty)+'☆'.repeat(5-difficulty)));
}
response={...baseline,mastery_score:41,has_history:true,recent_correct_rate:0,recent_attempt_count:1,
  attempt_count:1,sample_limited:true,reviewed_question_count:1,
  mastery_reason:'<script>评估依据</script>：复习不增加样本',
  decision_reasons:{recent_performance:'最近证据占 30%，不增加不同题目数'}};
await click('recommendation-refresh');
assert.match(markup(),/41\/100/);assert.match(markup(),/初步评估/);
assert.match(markup(),/1 道不同题目/);assert.match(markup(),/已复习 1 道/);
assert.match(markup(),/查看评估依据/);assert.match(markup(),/最近证据占 30%/);
assert.match(markup(),/&lt;script&gt;评估依据/);assert.doesNotMatch(markup(),/<script>/);
response={...baseline,topic:{id:81,name:'<img src=x onerror=alert(1)>'},reason:'<script>alert(1)</script>'};
await click('recommendation-refresh');
assert.doesNotMatch(markup(),/<img|<script/);assert.match(markup(),/&lt;img/);

fail=true;await click('recommendation-refresh');
assert.match(markup(),/推荐加载失败/);assert.match(markup(),/刷新重试/);
assert.equal(el('adaptive-button').disabled,true);
fail=false;response={...baseline};await click('recommendation-refresh');
assert.equal(el('adaptive-button').disabled,false);
response={...baseline,recommended_difficulty:7};await click('recommendation-refresh');
assert.match(markup(),/服务未返回有效推荐/);assert.equal(el('adaptive-button').disabled,true);
response={...baseline,topic:null,reason:'资料还没有知识点，请先整理知识点。'};await click('recommendation-refresh');
assert.match(markup(),/没有知识点/);assert.equal(el('adaptive-button').disabled,true);

response={...baseline};await click('recommendation-refresh');
const before=requests.length;
el('adaptive-button').dispatchEvent(new Event('click'));
el('adaptive-button').dispatchEvent(new Event('click'));await settle();
assert.equal(requests.slice(before).filter(r=>r.url.startsWith('/adaptive/next-question')).length,1,'Start reuses existing adaptive flow and blocks duplicate clicks');
assert.equal(state.sessions.get(24).questions[0].id,12);
assert.equal(el('adaptive-button').disabled,true,'An unfinished practice cannot be replaced');
response={...baseline,mastery_score:67,recent_correct_rate:1,recent_attempt_count:1,attempt_count:1,has_history:true,sample_limited:true,recommended_difficulty:2};
const beforeAnswer=previewCount();
el('answer-form').dispatchEvent(new Event('submit'));await settle();
assert.equal(previewCount(),beforeAnswer+1,'Answer saved event automatically refreshes recommendation');
assert.match(markup(),/100%/);assert.match(markup(),/67\/100/);assert.match(markup(),/★★☆☆☆/);
assert.equal(state.sessions.get(24).results[0].earned_xp,20);

// A result from a previously selected material must never paint over the new one.
held=new Promise(resolve=>{finish=resolve;});
void recommendation.refreshRecommendation();
held=null;state.material={id:25,title:'New notes'};response={...baseline,material_id:25,topic:{id:82,name:'新资料知识点'}};
emit('material');await settle();
finish({...baseline,topic:{id:81,name:'旧资料知识点'}});await settle();
assert.match(markup(),/新资料知识点/);assert.doesNotMatch(markup(),/旧资料知识点/);

// An answer arriving during a read schedules exactly one fresh read afterwards.
held=new Promise(resolve=>{finish=resolve;});void recommendation.refreshRecommendation();
const during=previewCount();emit('study-updated');emit('study-updated');
held=null;finish({...response,mastery_score:10});response={...response,mastery_score:80};await settle();
assert.equal(previewCount(),during+1);assert.match(markup(),/80\/100/);

// Logout invalidates both the cache and in-flight responses, even for the same material ID.
held=new Promise(resolve=>{finish=resolve;});void recommendation.refreshRecommendation();
state.epoch++;state.user=null;state.material=null;state.sessions.clear();emit('reset');
finish({...response,topic:{id:82,name:'旧账号机密'}});held=null;await settle();
assert.match(markup(),/选择资料/);assert.doesNotMatch(markup(),/旧账号机密/);
assert.equal(el('adaptive-button').disabled,true);
state.user={id:2};state.material={id:24,title:'Account two'};response={...baseline,topic:{id:83,name:'新账号知识点'}};
emit('material');await settle();assert.match(markup(),/新账号知识点/);
assert.equal(recommendation.recommendationReady(),true);
console.log('PASS: recommendation loading, new user, rates/stars, escaping, errors/retry, malformed response, no topics, read deduplication, existing adaptive start, double click, answer refresh, material/account isolation, in-flight invalidation');
