// Real Edge interactions and HTTP, using the explicitly labelled model substitute.
// PLAYWRIGHT_MODULE may point at the Codex bundled Playwright; no new framework.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const baseURL = process.env.S5_BASE_URL || 'http://127.0.0.1:18080';
const credentials = JSON.parse(fs.readFileSync(process.env.S5_CREDENTIALS_FILE || '.s5-local/acceptance-credentials.json','utf8'));
const output = process.env.S5_BROWSER_OUTPUT || 'evaluation/reports/s5/browser';
fs.mkdirSync(output,{recursive:true});
const report = {source:'synthetic_engineering_browser', models:'mocked_provider_http',
  browser:'Microsoft Edge / Playwright', real_participants:0, steps:[], errors:[], passed:false};
const browser = await chromium.launch({headless:true,executablePath:process.env.EDGE_PATH ||
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const context = await browser.newContext({viewport:{width:1440,height:1000}});
const page = await context.newPage();
page.on('pageerror',error=>report.errors.push(error.message));
page.setDefaultTimeout(25000);
const user = {...credentials.browser, username:credentials.browser.username+'-'+Date.now().toString().slice(-6)};
async function step(name, action) {
  report.current_step=name;
  await action(); report.steps.push({name,passed:true});
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));
}
async function screenshot(name) {
  await page.locator('#toast').waitFor({state:'hidden'});
  await page.evaluate(()=>document.fonts.ready);
  await page.screenshot({path:path.join(output,name),fullPage:true});
}
async function nav(name) {
  const button = page.locator('.nav-item[data-page="'+name+'"]');
  if(!await button.isVisible()) await page.locator('#navigation-toggle').click();
  await button.click();
  await page.locator('#'+name+'-panel').waitFor({state:'visible'});
}
async function login(account) {
  await page.locator('#username').fill(account.username);
  await page.locator('#password').fill(account.password);
  await page.locator('#auth-submit').click();
  await page.locator('#workspace-view').waitFor({state:'visible'});
}
try {
  await page.goto(baseURL+'/app');
  await step('register and login in browser', async()=>{
    await page.locator('#register-button').click();
    await page.locator('#username').fill(user.username);
    await page.locator('#password').fill(user.password);
    await page.locator('#confirm-password').fill(user.password);
    await page.locator('#auth-submit').click();
    await page.waitForFunction(()=>document.getElementById('auth-title').textContent==='欢迎回来');
    await login(user);
    assert.equal(await page.locator('#admin-nav').isVisible(),false);
  });
  await step('upload file, vectorize, extract topics', async()=>{
    await nav('library');
    await page.locator('#open-import').click();
    await page.locator('#material-file').setInputFiles({name:'browser-notes.txt',mimeType:'text/plain',
      buffer:Buffer.from('工程验收合成资料。FastAPI 使用 Depends 声明依赖，框架调用依赖函数注入参数。RAG 检索资料后生成有证据的回答。JWT 验证用户身份，服务端校验角色及学习资料归属。')});
    await page.locator('#import-submit').click();
    await page.getByText('全部导入完成',{exact:true}).waitFor();
    await page.locator('[data-close="import-dialog"]').click();
  });
  await step('RAG chat with saved evidence', async()=>{
    await nav('chat');
    await page.locator('#chat-input').fill('FastAPI 的 Depends 有什么作用？');
    const response = page.waitForResponse(r=>r.url().includes('/rag/ask') && r.request().method()==='POST');
    await page.locator('#send-question').click();
    assert.equal((await response).status(),200);
    await page.getByText('Depends 声明依赖，由框架调用依赖函数并注入参数。[1]',{exact:false}).first().waitFor();
    await screenshot('rag-desktop.png');
  });
  await step('adaptive card and answer feedback', async()=>{
    await nav('practice');
    await page.locator('#adaptive-button').waitFor({state:'visible'});
    await page.waitForFunction(()=>!document.getElementById('adaptive-button').disabled);
    await page.locator('#adaptive-button').click();
    await page.locator('#answer-form input[value="B"]').check();
    await page.locator('#answer-form button[type="submit"]').click();
    await page.locator('#next-question').waitFor();
    await screenshot('practice-desktop.png');
    await page.locator('#next-question').click();
  });
  await step('mistake review persists and map refreshes', async()=>{
    await nav('mistakes');
    await page.locator('[data-review]').first().click();
    await page.locator('#review-form input[value="A"]').check();
    await page.locator('#review-submit').click();
    await page.waitForFunction(()=>document.getElementById('review-feedback').textContent.includes('正确'));
    await page.locator('[data-close="review-dialog"]').first().click();
    await nav('map');
    await page.locator('#map-content .topic-node').first().waitFor({state:'visible'});
    await screenshot('map-desktop.png');
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
    await screenshot('map-mobile.png');
    await page.setViewportSize({width:1440,height:1000});
    await nav('records');
    assert.ok((await page.locator('#records-panel').textContent()).includes('学习记录'));
  });
  await step('coach create, retrieve evidence, finish', async()=>{
    await nav('coach');
    await page.locator('#coach-material').selectOption({label:'browser-notes'});
    await page.locator('#coach-goal').fill('理解 Depends 的用途');
    await page.locator('#coach-create button[type="submit"]').click();
    await page.locator('#coach-session').waitFor({state:'visible'});
    await page.locator('#coach-input').fill('解释 Depends 依赖注入');
    const response = page.waitForResponse(r=>r.url().includes('/turns') && r.request().method()==='POST');
    await page.locator('#coach-form button[type="submit"]').click();
    assert.equal((await response).status(),200);
    await page.waitForFunction(()=>!document.getElementById('coach-finish').disabled);
    await screenshot('coach-desktop.png');
    await page.locator('#coach-finish').click();
    await page.waitForFunction(()=>document.getElementById('coach-session-meta').textContent.includes('已结束'));
  });
  await step('admin search, detail, disable confirmation and audit', async()=>{
    await page.locator('#logout-button').click(); await login(credentials.admin);
    await nav('admin');
    await page.locator('#admin-search').fill(user.username);
    await page.locator('#admin-filter-form button[type="submit"]').click();
    await page.locator('[data-admin-detail]').first().click();
    await page.getByText('仅显示管理所需统计，不提供资料正文或私人对话。').waitFor();
    await page.locator('#admin-detail-close').click();
    await page.locator('[data-admin-status][data-enable="false"]').first().click();
    await page.locator('#admin-confirm-submit').click();
    await page.locator('#admin-confirm-dialog').waitFor({state:'hidden'});
    await page.locator('[data-admin-status][data-enable="true"]').first().waitFor();
    await page.locator('#admin-audit-refresh').click();
    await page.getByText('停用账号',{exact:true}).first().waitFor();
    await screenshot('admin-desktop.png');
  });
  await step('390px admin and disabled login', async()=>{
    await page.setViewportSize({width:390,height:844});
    await screenshot('admin-mobile.png');
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
    await page.locator('#logout-button').click();
    await page.locator('#username').fill(user.username); await page.locator('#password').fill(user.password);
    await page.locator('#auth-submit').click();
    await page.locator('#auth-error').filter({hasText:'用户名或密码错误'}).waitFor();
  });
  assert.deepEqual(report.errors,[]);
  report.passed=true;
} catch(error) {
  report.failure=String(error);
  await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{});
} finally {
  report.created_at=new Date().toISOString();
  report.browser_version=browser.version();
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));
  await browser.close();
}
console.log(JSON.stringify({passed:report.passed,steps:report.steps.length,failure:report.failure}));
process.exitCode=report.passed?0:1;
