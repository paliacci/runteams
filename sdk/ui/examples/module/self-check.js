// Opt-in local component acceptance. No business data or host bridge.
export async function runComponentChecks(api, createClient) {
  const checks=[];
  const assert=(ok,label)=>{if(!ok)throw new Error(label);checks.push(label);};
  const previous=document.activeElement;
  const fixture=document.createElement('div');fixture.dataset.rtUi='';
  fixture.style.cssText='position:fixed;left:-2000px;top:0;width:360px;height:400px;overflow:auto';
  document.body.append(fixture);
  const content=document.createElement('div');
  const input=document.createElement('textarea');input.value='尚未保存的内容';
  const scroller=document.createElement('div');scroller.style.cssText='height:60px;overflow:auto';
  const filler=document.createElement('div');filler.style.height='500px';scroller.append(filler);content.append(input,scroller);
  let opens=0;
  const module=api.createModuleTemplate({title:'检查模块',summary:'说明',content,onRequestMode:()=>opens++});
  fixture.append(module.section.element,module.full.element);
  let collapses=0;
  const header=api.createDrawerHeader({onCollapse:()=>collapses++});
  fixture.prepend(header.element);
  try {
    const collapseButton=header.collapseButton;
    collapseButton.click();
    assert(collapses===1&&collapseButton.getAttribute('aria-label')==='折叠抽屉','固定折叠按钮独立触发');
    const initialHeight=header.element.getBoundingClientRect().height;
    let presses=0;
    const action={id:'example',label:'示例按钮',onPress:()=>presses++};
    header.setExtras({text:'<b>按纯文本显示</b>',actions:[action]});
    const control=header.element.querySelector('.rt-drawer-action');control.focus();control.click();
    assert(presses===1&&!header.element.querySelector('b'),'页眉动作与纯文本');
    header.setExtras({text:'更新内容',actions:[{...action,label:'更新按钮',onPress:()=>presses+=2}]});
    control.click();
    assert(presses===3&&header.element.querySelector('.rt-drawer-action')===control&&document.activeElement===control,'页眉更新保留按钮与焦点');
    let rejected=false;
    try{header.setExtras({text:'不能部分写入',actions:[action,action]});}catch{rejected=true;}
    assert(rejected&&header.element.querySelector('.rt-drawer-text').textContent==='更新内容','非法页眉更新不部分生效');
    header.setExtras({actions:[{...action,disabled:true}]});control.click();
    assert(presses===3&&control.disabled&&document.activeElement===collapseButton,'禁用动作与焦点回收');
    header.setExtras({text:'LongText'.repeat(25),actions:[{...action,label:'LongAction'.repeat(15)}]});
    assert(header.element.scrollWidth<=header.element.clientWidth&&header.element.getBoundingClientRect().height===38,'页眉长内容不挤走折叠按钮或撑高');
    header.setExtras();
    assert(header.collapseButton===collapseButton&&!collapseButton.disabled&&header.element.getBoundingClientRect().height===initialHeight&&initialHeight===38,'清空扩展恢复原页眉骨架');
    header.setExtras({actions:[action]});
    const lastControl=header.element.querySelector('.rt-drawer-action');header.dispose();lastControl.click();collapseButton.click();
    header.setExtras({text:'不能更新'});
    assert(presses===3&&collapses===1&&collapseButton.disabled&&lastControl.disabled&&header.element.querySelector('.rt-drawer-text').textContent==='','页眉卸载清理');
    module.section.toggle.click();
    assert(!module.section.expanded&&module.section.body.hidden,'折叠语义');
    module.section.openButton.click();
    assert(opens===1&&!module.section.expanded,'展开独立触发');
    module.section.setExpanded(true);
    scroller.scrollTop=400;
    input.focus();input.setSelectionRange(2,4);
    // Test a layout change occurring when the presentation attribute changes.
    const style=document.createElement('style');
    style.textContent='[data-presentation=full] .check-scroll {height:300px!important}';
    content.prepend(style);scroller.className='check-scroll';
    module.setMode('full');
    assert(module.full.body.contains(content)&&input.value==='尚未保存的内容','同一内容与草稿');
    assert(document.activeElement===input&&input.selectionStart===2&&input.selectionEnd===4,'输入焦点与选区');
    assert(scroller.scrollTop===200,'完整视图滚动边界');
    module.full.backButton.focus();
    module.setMode('panel');
    assert(document.activeElement===module.section.openButton,'返回焦点');
    assert(scroller.scrollTop===400,'返回原滚动位置');
    assert(module.section.body.contains(content)&&!module.full.element.getClientRects().length,'单一可见视图');
    module.section.setExpanded(false);
    module.setError('切换失败');
    assert(module.section.element.querySelector('[role="alert"]').getClientRects().length>0,'折叠时失败可见');
    module.setPending(true);
    assert(module.section.openButton.disabled&&module.full.backButton.disabled,'切换中禁止重复操作');
    module.setPending(false);
    const before=module.section.expanded;module.dispose();module.section.toggle.click();
    assert(module.section.expanded===before,'卸载监听清理');
    const client=createClient({version:'0.1.0',transition:()=>{throw new Error('unavailable');}});
    try{await client.openFull('test');}catch{}
    assert(client.getSnapshot().mode==='panel'&&client.getSnapshot().error==='unavailable','失败保留原视图');
    client.dispose();
    return checks;
  } finally {header.dispose();module.dispose();fixture.remove();previous?.focus({preventScroll:true});}
}
