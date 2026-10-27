// DOM-event integration checks without a browser, network, or user data.
// Run: node --experimental-vm-modules tests/frontend_practice.mjs
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
  set innerHTML(value) { for (const m of this._html.matchAll(/\bid="([^"]+)"/g)) elements.delete(m[1]); this._html=value; parse(value); }
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

const requests=[], savedReviews=new Map();
let failReview=false, heldReview=null, enableFeedback=false, heldFeedback=null;
const fetch=async(url,options={})=>{
  const body=options.body ? JSON.parse(options.body) : null;
  requests.push({url,body});
  let data;
  if (url.endsWith('/generate')) {
    data=[{id:10,material_id:24,topic_id:body.topic_id,question:'Linked question',
      option_a:'A',option_b:'B',option_c:'C',option_d:'D',difficulty:2}];
  } else if (url.endsWith('/answer')) {
    data={question_id:Number(url.split('/')[2]),user_answer:body.answer,correct_answer:'B',
      is_correct:body.answer==='B',earned_xp:body.answer==='B'?20:0,explanation:'Original explanation',
      feedback:enableFeedback ? 'Local coaching' : undefined,
      feedback_source:enableFeedback ? 'local' : undefined};
  } else if (url.endsWith('/feedback')) {
    if (heldFeedback) return heldFeedback;
    data={feedback:'AI coaching',source:'ai'};
  } else if (url.endsWith('/review')) {
    assert.ok(body.request_id);
    data=savedReviews.get(body.request_id);
    if (!data) {
      data={question_id:Number(url.split('/')[3]),user_answer:body.answer,correct_answer:'B',
        is_correct:body.answer==='B',earned_xp:0,explanation:'Review explanation'};
      savedReviews.set(body.request_id,data);
    }
    if (heldReview) return heldReview;
    if (failReview) {failReview=false; return {ok:false,status:503,json:async()=>({detail:'response lost'})};}
  } else throw new Error('Unexpected API '+url);
  return {ok:true,status:200,json:async()=>structuredClone(data)};
};
const context=vm.createContext({document,localStorage,fetch,EventTarget,Event,DOMException,AbortController,
  setTimeout,clearTimeout,Intl,crypto:webcrypto,window:{matchMedia:()=>({matches:true})},
  FormData:class {constructor(form){this.form=form;} get(key){return this.form.values?.[key];}},console});
const modules=new Map();
function moduleFor(filename) {
  filename=path.resolve(filename.replace(/[?#].*$/,''));
  if(!modules.has(filename)) modules.set(filename,new vm.SourceTextModule(fs.readFileSync(filename,'utf8'),{context,identifier:filename}));
  return modules.get(filename);
}
const practice=moduleFor('frontend/practice.js');
await moduleFor('frontend/app.js').link((specifier,ref)=>moduleFor(path.resolve(path.dirname(ref.identifier),specifier)));
const home=moduleFor('frontend/home.js');
await home.evaluate();
await practice.evaluate();
const core=moduleFor('frontend/core.js').namespace;
const progress=moduleFor('frontend/progress.js').namespace;
const el=id=>elements.get(id);
const settle=async()=>{for(let i=0;i<12;i++) await new Promise(resolve=>setImmediate(resolve));};
const current=()=>core.state.sessions.get(24);
const markup=()=>el('practice-content').innerHTML;
const click=async id=>{assert.ok(el(id),'Missing button '+id);el(id).dispatchEvent(new Event('click'));await settle();};
const submit=async(answer,twice=false)=>{
  const form=el('answer-form');form.values={answer};
  form.dispatchEvent(new Event('submit'));
  if(twice) form.dispatchEvent(new Event('submit'));
  await settle();
};
core.state.user={id:1};core.state.token='test';core.state.material={id:24,title:'Notes'};
core.state.materials=[core.state.material];
core.state.sessions.set(24,{questions:[1,2].map(id=>({id,material_id:24,question:'Question '+id,
  option_a:'A',option_b:'B',option_c:'C',option_d:'D',difficulty:1})),
  results:[],index:0,pending:null,selection:null,materialTitle:'Notes'});
el('quiz-count').value='2';el('quiz-difficulty').value='1';
practice.namespace.initPractice();
await submit('C',true);
assert.equal(requests.length,1,'Double first submission is locked');
assert.equal(current().results[0].is_correct,false);
assert.ok(el('retry-question'));
await click('retry-question');
assert.doesNotMatch(markup(),/Original explanation|option correct|option wrong/);
assert.doesNotMatch(markup(),/<fieldset class="options" disabled/);
assert.equal(el('next-question'),undefined,'Cannot skip while retry is active');
await click('cancel-retry');
assert.ok(el('retry-question'));
assert.equal(current().results.length,1);
await click('retry-question');
await submit('A',true);
assert.equal(requests.length,2,'Double review submission is locked');
assert.equal(current().results.length,1,'Retry does not advance progress');
assert.equal(current().results[0].user_answer,'C','Original answer preserved');
assert.equal(current().results[0].review.user_answer,'A');
assert.equal(current().results[0].review.is_correct,false);
const firstId=requests[1].body.request_id;
await click('retry-question');
failReview=true;
await submit('B');
assert.equal(current().retry.uncertain,true);
assert.match(markup(),/<fieldset class="options" disabled/,'Uncertain saved answer stays locked');
assert.equal(el('cancel-retry'),undefined,'Cannot discard unconfirmed submission');
assert.equal(current().results[0].review.is_correct,false);
const retryBody=JSON.stringify(requests.at(-1).body);
assert.notEqual(requests.at(-1).body.request_id,firstId,'New attempt uses a new ID');
progress.restoreProgress();practice.namespace.renderPractice();
assert.equal(current().retry.answer,'B','Restore preserves submitted answer');
await submit('D');
assert.equal(JSON.stringify(requests.at(-1).body),retryBody,'Retry after refresh sends identical answer and ID');
assert.equal(current().retry,null);
assert.equal(current().results[0].is_correct,false,'First score remains wrong');
assert.equal(current().results[0].review.is_correct,true);
assert.equal(current().results[0].review.earned_xp,0);
assert.equal(el('retry-question'),undefined,'Correct retry is complete');
progress.restoreProgress();practice.namespace.renderPractice();
assert.equal(current().results[0].review.is_correct,true,'Latest review survives reload');
await click('next-question');
assert.equal(current().index,1);
await submit('A');await click('retry-question');
assert.equal(el('generate-button').disabled,true,'Last-question retry blocks replacing the set');
home.namespace.renderHome();
assert.match(el('home-sessions').innerHTML,/data-resume="24"/);
assert.doesNotMatch(el('home-sessions').innerHTML,/data-summary="true"/,'Pending retry remains resumable, not a completed summary');
await submit('B');await click('next-question');
assert.equal(current().index,2);
assert.match(markup(),/0\/2/,'Summary counts original answers');
assert.match(markup(),/最近重答/);
assert.equal(savedReviews.size,3,'Network retries never create another review');
// Existing snapshots without retry fields remain valid.
const snap=JSON.parse(storage.get('learning_progress_v1_1'));
delete snap.sessions[0][1].retry;
snap.sessions[0][1].results.forEach(r=>delete r.review);
storage.set('learning_progress_v1_1',JSON.stringify(snap));
progress.restoreProgress();
assert.equal(current().results.length,2);
assert.equal(current().results[0].review,null);
// Switching accounts during a pending review must not restore stale state.
current().index=0;practice.namespace.renderPractice();await click('retry-question');
let finishReview;
heldReview=new Promise(resolve=>{finishReview=resolve;});
await submit('B');
core.state.epoch++;core.state.sessions.clear();core.state.user=null;core.state.material=null;
finishReview({ok:true,status:200,json:async()=>({question_id:1,user_answer:'B',correct_answer:'B',is_correct:true,earned_xp:0})});
await settle();
assert.equal(core.state.sessions.size,0);
core.state.user={id:1};core.state.token='test';core.state.material={id:24,title:'Notes'};
core.state.sessions.set(24,{questions:[{id:3,material_id:24,question:'Question 3',
  option_a:'A',option_b:'B',option_c:'C',option_d:'D',difficulty:1}],
  results:[],index:0,pending:null,selection:null,materialTitle:'Notes'});
enableFeedback=true;
let finishFeedback;
heldFeedback=new Promise(resolve=>{finishFeedback=resolve;});
practice.namespace.renderPractice();
await submit('A');
assert.equal(current().results[0].feedback,'Local coaching','Answer renders before AI feedback resolves');
assert.match(markup(),/Local coaching/);
finishFeedback({ok:true,status:200,json:async()=>({feedback:'AI coaching',source:'ai'})});
await settle();
assert.equal(current().results[0].feedback,'AI coaching');
assert.equal(current().results[0].feedback_source,'ai');
assert.match(markup(),/AI coaching/);
core.state.sessions.delete(24);
core.state.topics=[];core.state.topicId=null;
core.events.dispatchEvent(new Event('topics'));
assert.equal(el('generate-button').disabled,true,'Missing topic blocks new generation');
const beforeGeneration=requests.length;
el('quiz-form').dispatchEvent(new Event('submit'));await settle();
assert.equal(requests.length,beforeGeneration,'Direct submit cannot bypass topic validation');
core.state.topics=[{id:9,name:'Stable topic'}];core.state.topicId=9;
core.events.dispatchEvent(new Event('topics'));
assert.equal(el('generate-button').disabled,false);
assert.equal(el('quiz-topic').readOnly,true);
el('quiz-form').dispatchEvent(new Event('submit'));await settle();
assert.equal(requests.at(-1).body.topic_id,9);
assert.equal(requests.at(-1).body.topic,'Stable topic');
console.log('PASS: wrong-answer retry, hidden solution, cancel, repeated errors, idempotent save/reload, first-score preservation, no repeat XP, next question, last question, legacy state, account switch, async feedback');
