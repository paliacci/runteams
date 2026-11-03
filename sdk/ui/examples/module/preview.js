import {createDrawerHeader, createModuleTemplate, createSection, createPresentationClient, presentationVersion} from '../../index.js';
const doc = document;
const $ = id => doc.getElementById(id);
const componentApi = {createDrawerHeader, createModuleTemplate, createSection};
const main = $('demo'), drawer = $('drawer'), context = $('context'), fullSlot = $('full-slot');
let showHeaderHelp = false;
const header = createDrawerHeader({onCollapse: () => {
  drawer.hidden = true;main.dataset.drawerCollapsed = 'true';
  $('reopen-drawer').hidden = false;$('reopen-drawer').focus();
  $('mode-caption').textContent = '当前：抽屉已折叠';
  context.querySelector('.context-center p').textContent = '点击右上角打开抽屉，继续查看和编辑。';
}});
$('reopen-drawer').addEventListener('click', () => {
  drawer.hidden = false;delete main.dataset.drawerCollapsed;
  $('reopen-drawer').hidden = true;header.collapseButton.focus();
  $('mode-caption').textContent = '当前：抽屉视图';
  context.querySelector('.context-center p').textContent = '点击右侧模块的展开按钮，查看完整工作视图。';
});
const updateHeader = () => header.setExtras($('header-extras').checked ? {
  text: '8 项内容',
  actions: [{id: 'help', label: showHeaderHelp ? '收起说明' : '使用说明', onPress: () => {showHeaderHelp = !showHeaderHelp;$('header-help').hidden = !showHeaderHelp;if(showHeaderHelp)$('drawer-content').scrollTop=0;updateHeader();}}]
} : {});
updateHeader();
$('panel-header').append(header.element);
$('header-extras').addEventListener('change', updateHeader);
const content = doc.createElement('div');
content.className = 'module-content'; content.dataset.presentation = 'panel';
content.innerHTML = `<div class="module-toolbar"><input class="rt-input" type="search" aria-label="筛选条目" placeholder="筛选条目"></div><div class="content-grid"><div><div class="item-list" aria-label="内容条目"></div><p class="empty-list" hidden>没有匹配的条目</p></div><div class="editor"><label for="draft">条目一 · 内容</label><textarea id="draft" class="rt-input" placeholder="在这里填写内容，展开后继续编辑。"></textarea><small>编辑内容会保留在当前预览中。</small></div></div>`;
const list = content.querySelector('.item-list'), draft = content.querySelector('textarea'), selectedLabel = content.querySelector('.editor label');
const names = ['条目一','条目二','条目三','条目四','条目五','条目六','条目七','条目八'];
let selected = 0;
const drafts = new Map();
for (const [index, name] of names.entries()) {
  const row = doc.createElement('button'); row.type='button';row.className='rt-button item';row.dataset.index=index;row.setAttribute('aria-pressed',String(index===0));
  const text = doc.createElement('span');text.className='item-text';
  const title=doc.createElement('span');title.textContent=name;
  const note=doc.createElement('span');note.className='item-note';note.textContent='可替换的内容与辅助信息';
  const mark=doc.createElement('span');mark.className='item-marker';mark.textContent=index===0?'✓':'';mark.setAttribute('aria-hidden','true');
  text.append(title,note);row.append(text,mark);list.append(row);
  row.addEventListener('click',()=>{
    selected=index;draft.value=drafts.get(index)||'';selectedLabel.textContent=`${name} · 内容`;
    for(const item of list.children){const chosen=Number(item.dataset.index)===index;item.setAttribute('aria-pressed',String(chosen));item.querySelector('.item-marker').textContent=chosen?'✓':'';}
  });
}
draft.addEventListener('input',()=>drafts.set(selected,draft.value));
content.querySelector('input').addEventListener('input',event=>{
  let count=0;for(const row of list.children){row.hidden=!names[Number(row.dataset.index)].includes(event.target.value);if(!row.hidden)count++;}
  content.querySelector('.empty-list').hidden=count>0;
});
// Standalone host adapter. Never used as a fallback for a failed production host.
const client=createPresentationClient({version:presentationVersion,transition(target,{signal}){
  if(signal.aborted)throw new Error('cancelled');
  if($('reject-next').checked){$('reject-next').checked=false;throw new Error('preview unavailable');}
  return target;
}});
let drawerScroll=0;
const module=componentApi.createModuleTemplate({title:'内容模块',employeeName:'员工名称',summary:'8 项内容',content,onRequestMode:mode=>{
  (mode==='full'?client.openFull('content'):client.returnToPanel()).catch(()=>{});
}});
$('drawer-content').append(module.section.element);
fullSlot.append(module.full.element);
const extraContent=doc.createElement('p');extraContent.className='section-note';extraContent.textContent='这里也可以放入任意组件。';
const extra=componentApi.createSection({title:'辅助模块',summary:'可选内容',content:extraContent,expanded:false});
$('drawer-content').append(extra.element);
const unsubscribe=client.subscribe(state=>{
  module.setPending(state.pending);
  module.setError(state.error?'暂时无法切换视图，请重试。':'');
  if(state.mode===module.mode)return;
  if(state.mode==='full')drawerScroll=$('drawer-content').scrollTop;
  // Reveal the destination, move content, then hide the source. Reading scroll
  // positions after hiding an ancestor would lose the visible scroll context.
  if(state.mode==='full')fullSlot.hidden=false;
  else drawer.hidden=false;
  module.setMode(state.mode);
  fullSlot.hidden=state.mode!=='full';
  drawer.hidden=state.mode==='full';context.hidden=state.mode==='full';
  main.dataset.mode=state.mode;
  if(state.mode==='panel')$('drawer-content').scrollTop=drawerScroll;
  $('mode-caption').textContent=state.mode==='full'?'当前：完整工作视图':'当前：抽屉视图';
});
$('theme').addEventListener('click',()=>{
  const dark=doc.documentElement.dataset.theme!=='dark';doc.documentElement.dataset.theme=dark?'dark':'light';
  $('theme').textContent=dark?'切换浅色':'切换深色';$('theme').setAttribute('aria-pressed',String(dark));
});
$('width').addEventListener('change',event=>main.dataset.width=event.target.value);
$('run-checks').addEventListener('click', async()=>{
  $('run-checks').disabled=true;
  try {
    const {runComponentChecks}=await import('./self-check.js');
    const results=await runComponentChecks(componentApi,createPresentationClient);
    $('checks').textContent=`${results.length} 项检查通过：${results.join('、')}。`;
  } catch(error){$('checks').textContent=`检查失败：${error.message}`;}
  finally{$('run-checks').disabled=false;}
});
window.addEventListener('pagehide',()=>{unsubscribe();client.dispose();module.dispose();extra.dispose();header.dispose();},{once:true});
