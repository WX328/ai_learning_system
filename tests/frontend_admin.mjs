// Run: node --experimental-vm-modules tests/frontend_admin.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const elements=new Map(),anonymous=[];
class Classes {
  constructor(value=''){this.values=new Set(value.split(/\s+/).filter(Boolean));}
  contains(n){return this.values.has(n);} add(n){this.values.add(n);} remove(n){this.values.delete(n);}
  toggle(n,on=!this.contains(n)){on?this.add(n):this.remove(n);return on;}
}
function matches(e,s){
  if(s.startsWith('.')) return s.slice(1).split('.').every(n=>e.classList.contains(n));
  const m=s.match(/^\[data-([\w-]+)(?:="([^"]*)")?\]$/);
  if(m){const key=m[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase());return key in e.dataset&&(m[2]===undefined||e.dataset[key]===m[2]);}
  return false;
}
class Element extends EventTarget {
  constructor(id='',classes=''){super();this.id=id;this.classList=new Classes(classes);this.dataset={};this.value='';this.disabled=false;this.open=false;this._html='';this.textContent='';}
  set innerHTML(v){for(const m of this._html.matchAll(/id="([^"]+)"/g)) elements.delete(m[1]);this._html=v;parse(v);}
  get innerHTML(){return this._html;}
  setAttribute(){} removeAttribute(){} focus(){} scrollIntoView(){}
  closest(s){return matches(this,s)?this:null;}
  showModal(){this.open=true;} close(){this.open=false;this.dispatchEvent(new Event('close'));}
}
function parse(html){
  for(const m of html.matchAll(/<([a-z][\w-]*)\b([^>]*)>/gi)){
    const attrs=Object.fromEntries([...m[2].matchAll(/([\w-]+)="([^"]*)"/g)].map(a=>[a[1],a[2]]));
    if(!attrs.id&&!attrs.class&&!Object.keys(attrs).some(k=>k.startsWith('data-'))) continue;
    const e=new Element(attrs.id||'',attrs.class||'');e.disabled=/\bdisabled\b/.test(m[2]);
    for(const [k,v] of Object.entries(attrs)) if(k.startsWith('data-')) e.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=v;
    attrs.id?elements.set(attrs.id,e):anonymous.push(e);
  }
}
const html=fs.readFileSync('frontend/index.html','utf8');parse(html);
assert.equal([...html.matchAll(/\bid="([^"]+)"/g)].length,elements.size,'IDs must be unique');
const document=new EventTarget();document.getElementById=id=>elements.get(id)||null;
document.querySelectorAll=s=>[...elements.values(),...anonymous].filter(e=>matches(e,s));
document.querySelector=s=>document.querySelectorAll(s)[0]||null;
const storage=new Map();const localStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)};
let authorized=true,failUsers=false,failPatch=false,heldUsers=null,heldPatch=null;
const users=Array.from({length:23},(_,i)=>({id:i+1,username:i===1?'<img src=x onerror=alert(1)>':'learner-'+(i+1),role:i===0?'admin':'user',is_active:true,created_at:i===2?null:'2026-10-20T01:00:00Z',total_xp:i*10,level:1}));
const logs=[],requests=[];
const response=(data,status=200)=>({ok:status===200,status,json:async()=>structuredClone(data)});
const fetch=async(url,options={})=>{
  requests.push({url,...options});assert.equal(options.headers.Authorization,'Bearer test');
  if(!authorized)return response({detail:'需要管理员权限'},403);
  const parsed=new URL(url,'http://local'),params=parsed.searchParams;
  if(parsed.pathname==='/admin/stats') return response({total_users:users.length,enabled_users:users.filter(u=>u.is_active).length,active_users_30d:4,material_count:12,question_count:30,answer_count:20});
  if(parsed.pathname==='/admin/audit-logs')return response({total:logs.length,page:Number(params.get('page')),page_size:10,items:logs});
  if(parsed.pathname==='/admin/users'){
    if(heldUsers)return heldUsers;
    if(failUsers)return response({detail:'暂时无法查询用户'},503);
    const filtered=users.filter(u=>(!params.get('search')||u.username.includes(params.get('search')))&&(!params.get('role')||u.role===params.get('role'))&&(!params.get('is_active')||String(u.is_active)===params.get('is_active')));
    const page=Number(params.get('page')),size=Number(params.get('page_size'));
    return response({total:filtered.length,page,page_size:size,items:filtered.slice((page-1)*size,page*size)});
  }
  const id=Number(parsed.pathname.split('/')[3]),user=users.find(u=>u.id===id);
  if(parsed.pathname.endsWith('/status')){
    if(heldPatch)return heldPatch;
    if(failPatch)return response({detail:'保存响应未确认'},503);
    user.is_active=JSON.parse(options.body).is_active;
    logs.unshift({id:logs.length+1,actor_user_id:1,actor_username:'admin',target_user_id:id,target_username:user.username,action:user.is_active?'enable_user':'disable_user',result:'changed',created_at:'2026-10-22T05:00:00Z'});
    return response(user);
  }
  return response({...user,statistics:{material_count:2,topic_count:3,question_count:4,answer_count:1,correct_rate:0,review_count:0,qa_count:0,coach_session_count:0}});
};
const context=vm.createContext({document,localStorage,fetch,EventTarget,Event,DOMException,AbortController,URLSearchParams,setTimeout,clearTimeout,Intl,console});
const modules=new Map();
function moduleFor(filename){filename=path.resolve(filename);if(!modules.has(filename))modules.set(filename,new vm.SourceTextModule(fs.readFileSync(filename,'utf8'),{context,identifier:filename}));return modules.get(filename);}
const admin=moduleFor('frontend/admin.js');await admin.link((s,r)=>moduleFor(path.resolve(path.dirname(r.identifier),s)));await admin.evaluate();
const core=moduleFor('frontend/core.js').namespace,el=id=>elements.get(id);
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};
async function click(dataset){const target=new Element();target.dataset=dataset;const e=new Event('click');Object.defineProperty(e,'target',{value:target});document.dispatchEvent(e);await settle();}
async function button(id){el(id).dispatchEvent(new Event('click'));await settle();}
async function submit(id){el(id).dispatchEvent(new Event('submit'));await settle();}
admin.namespace.initAdmin();
core.state.token='test';core.state.user={id:2,role:'user'};core.emit('identity');core.go('admin');await settle();
assert.equal(el('admin-nav').classList.contains('hidden'),true);assert.equal(requests.length,0,'Ordinary users cannot navigate to admin');
core.state.user={id:1,role:'admin'};core.emit('identity');core.go('admin');await settle();
assert.equal(el('admin-nav').classList.contains('hidden'),false);assert.match(el('admin-stats').innerHTML,/23/);
assert.match(el('admin-users').innerHTML,/&lt;img/);assert.doesNotMatch(el('admin-users').innerHTML,/<img/);
assert.match(el('admin-users').innerHTML,/历史时间未知/);assert.match(el('admin-users-pagination').innerHTML,/1 \/ 3/);
await click({adminPage:'users',step:'1'});assert.match(el('admin-users-pagination').innerHTML,/2 \/ 3/);
el('admin-search').value='learner-23';await submit('admin-filter-form');assert.match(el('admin-users').innerHTML,/learner-23/);assert.match(el('admin-users-pagination').innerHTML,/共 1 条/);
el('admin-search').value='none';await submit('admin-filter-form');assert.match(el('admin-users').innerHTML,/没有符合条件/);
el('admin-search').value='';el('admin-role').value='admin';el('admin-role').dispatchEvent(new Event('change'));await settle();assert.match(el('admin-users').innerHTML,/learner-1/);assert.doesNotMatch(el('admin-users').innerHTML,/learner-23/);
el('admin-role').value='';await submit('admin-filter-form');
await click({adminDetail:'2'});assert.equal(el('admin-detail-dialog').open,true);assert.match(el('admin-detail').innerHTML,/0%/);assert.doesNotMatch(el('admin-detail').innerHTML,/<img/);
await button('admin-detail-close');assert.equal(el('admin-detail').innerHTML,'');
await click({adminStatus:'1',enable:'false'});assert.equal(el('admin-confirm-dialog').open,false,'Self-disable blocked in UI too');
await click({adminStatus:'2',enable:'false'});assert.equal(el('admin-confirm-dialog').open,true);await button('admin-confirm-cancel');assert.equal(logs.length,0,'Cancel performs no mutation');
await click({adminStatus:'2',enable:'false'});failPatch=true;await submit('admin-confirm-form');assert.match(el('admin-confirm-error').textContent,/未确认/);assert.equal(el('admin-confirm-submit').disabled,false);
failPatch=false;await submit('admin-confirm-form');assert.equal(users[1].is_active,false);assert.equal(logs.length,1);assert.match(el('admin-audit').innerHTML,/停用账号/);
await click({adminStatus:'2',enable:'true'});
let finish;heldPatch=new Promise(resolve=>{finish=resolve;});
const before=requests.filter(r=>r.method==='PATCH').length;
el('admin-confirm-form').dispatchEvent(new Event('submit'));el('admin-confirm-form').dispatchEvent(new Event('submit'));await settle();
assert.equal(requests.filter(r=>r.method==='PATCH').length,before+1,'Duplicate saves are locked');assert.equal(el('admin-confirm-cancel').disabled,true);
heldPatch=null;users[1].is_active=true;finish(response(users[1]));await settle();assert.equal(el('admin-confirm-dialog').open,false);
failUsers=true;await button('admin-refresh');assert.match(el('admin-users-status').textContent,/加载失败/);
failUsers=false;await button('admin-refresh');assert.equal(el('admin-users-status').textContent,'');
authorized=false;await button('admin-refresh');assert.equal(el('admin-nav').classList.contains('hidden'),true);assert.equal(el('admin-users').innerHTML,'','403 clears admin data');
authorized=true;core.state.user={id:1,role:'admin'};core.emit('identity');core.go('admin');await settle();
heldUsers=new Promise(resolve=>{finish=resolve;});void button('admin-refresh');await settle();
core.resetSession();heldUsers=null;finish(response({total:1,page:1,page_size:10,items:[{...users[0],username:'OLD ADMIN PRIVATE'}]}));await settle();
assert.equal(el('admin-nav').classList.contains('hidden'),true);assert.equal(el('admin-users').innerHTML,'');assert.equal(el('admin-stats').innerHTML,'');
assert.equal(el('admin-detail-dialog').open,false);
console.log('PASS: server identity navigation, stats, safe rendering, search/filter/pagination, empty/errors/retry, details, self protection, confirmation/cancel, save lock, audit refresh, 403 cleanup, logout race');
