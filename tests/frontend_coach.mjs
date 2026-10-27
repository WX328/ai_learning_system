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


Element.prototype.reset = function() {};
elements.get('material-file').files = [];
const requests = [];
let failure = false, hold = null;
let saved = {
 id:'11111111-1111-4111-8111-111111111111',material_id:1,goal:'学会依赖注入',
 minutes:20,status:'active',revision:0,busy:false,
 state:{plan:[{title:'讲解',minutes:20}],suggested_topics:[{name:'依赖注入',mastery:67,sample_limited:true,mastery_reason:'<script>评估</script> · 1 道不同题目'}],completed:[],
 target_questions:4,sources:[],degraded:false},messages:[],question:null,
};
const fetch = async(url, options={}) => {
 const body = options.body ? JSON.parse(options.body) : null;
 requests.push({url,body});
 if (hold && options.method === 'POST') return hold;
 let data;
 if (url === '/coach/sessions' && options.method === 'POST') {
   saved={...saved,id:body.request_id,goal:body.goal}; data=saved;
 } else if (url === '/coach/sessions') {
   data=[{id:saved.id,goal:saved.goal,status:saved.status,minutes:20}];
 } else if (url.endsWith('/turns')) {
   if (failure) {failure=false; throw new TypeError('lost response');}
   data={...saved,revision:saved.revision+1,messages:[...saved.messages,
     {role:'assistant',content:'<img src=x onerror=alert(1)>已恢复'}]};
   saved=data;
 } else if (url.startsWith('/coach/sessions/')) data=saved;
 else if (url === '/rag/ask') data={answer:'Scoped summary',status:'answered',context_source:'retrieval',
   sources:[{rank:1,chunk_id:9,chunk_index:0,excerpt:'State holds mutable data.',similarity:null,retrieval_methods:['topic']}],
   retrieval:{retrieval_method:'topic',candidate_count:1,rerank_applied:false}};
 else if (url === '/study/summary') data={};
 else data=[];
 return {ok:true,status:200,json:async()=>structuredClone(data)};
};
const context=vm.createContext({document,localStorage,fetch,EventTarget,Event,DOMException,AbortController,
 setTimeout,clearTimeout,Intl,crypto:webcrypto,
 window:{matchMedia:()=>({matches:true}),addEventListener:()=>{}},
 FormData:class {constructor(form){this.form=form;} get(key){return this.form.values?.[key];}},console});
const modules=new Map();
function moduleFor(filename) {
 filename=path.resolve(filename.replace(/[?#].*$/,''));
 if(!modules.has(filename)) modules.set(filename,new vm.SourceTextModule(fs.readFileSync(filename,'utf8'),{context,identifier:filename}));
 return modules.get(filename);
}
const app=moduleFor('frontend/app.js');
await app.link((specifier,ref)=>moduleFor(path.resolve(path.dirname(ref.identifier),specifier)));
await app.evaluate();
const core=moduleFor('frontend/core.js').namespace;
core.state.user={id:42,username:'test'}; core.state.token='fake'; core.state.materials=[{id:1,title:'Notes'}];
const settle=()=>new Promise(resolve=>setTimeout(resolve,25));
function click(id){elements.get(id).dispatchEvent(new Event('click'));}
function submit(id){elements.get(id).dispatchEvent(new Event('submit',{cancelable:true}));}
core.state.material=core.state.materials[0];
core.state.topics=[{id:7,name:'React',description:'Components'},{id:8,name:'State',description:'Mutable data'}];
core.emit('topics');
const summarySuggestion=document.querySelector('[data-suggestion-kind="summary"]');
const exampleSuggestion=document.querySelector('[data-suggestion-kind="example"]');
core.setTopic(7);
assert.equal(summarySuggestion.textContent,'总结当前知识点');
summarySuggestion.dispatchEvent(new Event('click'));
assert.equal(elements.get('chat-input').value,'请总结知识点「React」的核心概念和要点。');
core.setTopic(8);
exampleSuggestion.dispatchEvent(new Event('click'));
assert.match(elements.get('chat-input').value,/「State」/);
summarySuggestion.dispatchEvent(new Event('click'));
submit('chat-form'); await settle();
const question=requests.find(r=>r.url === '/rag/ask');
assert.equal(question.body.topic_id,8);
assert.match(question.body.query,/「State」/);
assert.match(elements.get('messages').innerHTML,/知识点正文片段/);
assert.match(elements.get('messages').innerHTML,/按原文章节顺序整理/);
assert.doesNotMatch(elements.get('messages').innerHTML,/向量 —/);
core.setTopic(null);
assert.equal(summarySuggestion.textContent,'总结核心内容');
summarySuggestion.dispatchEvent(new Event('click'));
assert.equal(elements.get('chat-input').value,'请总结这份资料的核心知识点。');
core.go('coach'); await settle();
assert.ok(!elements.get('coach-session').classList.contains('hidden'));
assert.match(elements.get('coach-topics').innerHTML,/67\/100/);
assert.match(elements.get('coach-topics').innerHTML,/初步评估/);
assert.match(elements.get('coach-topics').innerHTML,/评估依据/);
assert.match(elements.get('coach-topics').innerHTML,/&lt;script&gt;评估/);
assert.doesNotMatch(elements.get('coach-topics').innerHTML,/<script>/);
elements.get('coach-input').value='解释依赖注入';
failure=true; submit('coach-form'); await settle();
assert.ok(storage.has('coach_pending_42'),'unknown outcome must retain request');
const first=requests.filter(r=>r.url.endsWith('/turns')).at(-1);
click('coach-retry-request'); await settle();
const second=requests.filter(r=>r.url.endsWith('/turns')).at(-1);
assert.deepEqual(second.body,first.body,'retry must reuse request ID and revision');
assert.ok(!storage.has('coach_pending_42'));
assert.ok(elements.get('coach-messages').innerHTML.includes('&lt;img'),'model text must be escaped');
let release;
hold=new Promise(resolve=>{release=resolve;});
elements.get('coach-input').value='继续';
submit('coach-form'); await settle();
core.resetSession();
release({ok:true,status:200,json:async()=>saved}); hold=null; await settle();
assert.ok(elements.get('coach-session').classList.contains('hidden'),'late response after logout must not restore private data');
assert.equal(elements.get('coach-messages').innerHTML,'');
console.log('PASS: app boot, scoped chat suggestions and request, topic source labels, coach resume, idempotent retry, escaped output, logout race');
