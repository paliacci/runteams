/* Named view shortcuts in the existing authorized cloud preference store. No local business cache. */
(function(global){
  'use strict';
  const KEY='runteams_sidebar_views_v1';let busy=false,opening=false;
  const valid=row=>row&&typeof row==='object'&&Object.keys(row).sort().join(',')==='chat_id,installation_id,title,view'&&/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(row.installation_id)&&Number.isSafeInteger(row.chat_id)&&row.chat_id>0&&typeof row.view==='string'&&row.view.length>0&&row.view.length<=128&&typeof row.title==='string'&&row.title.length>0&&row.title.length<=120;
  const same=(a,b)=>a.installation_id===b.installation_id&&a.view===b.view&&a.chat_id===b.chat_id;
  function rows(){if(!workspaceBusinessStorage.preferencesVerified)return [];const values=JSON.parse(workspaceBusinessStorage.getItem(KEY)||'[]');if(!Array.isArray(values)||values.length>64||values.some(row=>!valid(row)))throw Error('常用界面暂时无法读取');return values;}
  function markup(){
    if(!S.account?.signed_in)return '';
    let values=[],body='';
    try{values=rows();}catch(error){body=`<button class="rail-section-hint" type="button" onclick="refreshWorkspacePreferences().then(render).catch(e=>toast(e.message,'err'))">常用暂时无法读取，重试</button>`;}
    body=body||values.map((row,index)=>`<div class="rail-view-row"><button class="rail-primary-action rail-view-link" type="button" data-sidebar-view="${index}" ${busy?'disabled':''} onclick="RunTeamsSidebarViews.open(${index})" title="${esc(row.title)}">${ICON('panel-right-open')}<span>${esc(row.title)}</span></button><button class="rail-view-remove" type="button" aria-label="从常用移除 ${esc(row.title)}" ${busy?'disabled':''} onclick="RunTeamsSidebarViews.remove(${index})">${ICON('x')}</button></div>`).join('');
    return `<section class="rail-favorites" aria-label="常用界面" aria-busy="${busy}"><details class="rail-favorites-section" data-rail-section="favorites" ${S.railSections?.favorites===true?'open':''}><summary class="rail-section-toggle" onclick="toggleRailSectionDetails(event,'favorites')"><span>常用</span><span class="rail-section-chevron" aria-hidden="true">${ICON('chev')}</span></summary>${body}</details></section>`;
  }

  async function save(next){
    if(busy)return false;
    if(!S.account?.signed_in||!workspaceBusinessStorage.preferencesVerified)throw Error('请先核对当前工作区');
    if(next.length>64)throw Error('常用最多保留64个界面');
    const scope=workspaceAccountCacheToken(),generation=workspaceBusinessStorage.generation();busy=true;render();
    try{workspaceBusinessStorage.saveCloud(KEY,JSON.stringify(next),()=>scope===workspaceAccountCacheToken()&&generation===workspaceBusinessStorage.generation());await workspaceBusinessStorage.writes;if(scope!==workspaceAccountCacheToken()||generation!==workspaceBusinessStorage.generation())return false;return true;}
    finally{busy=false;render();}
  }
  async function pin(row){try{if(!valid(row))throw Error('界面来源无效');const values=rows();if(values.some(item=>same(item,row)))return;await save([...values,row]);}catch(error){toast(error.message||'常用未保存','err');}}
  async function remove(index){try{const values=rows();if(!values[index])return;await save(values.filter((_,i)=>i!==index));}catch(error){toast(error.message||'常用未保存','err');}}
  async function open(index){
    if(busy||opening)return;let row;try{row=rows()[index];if(!row)return;
      opening=true;
      const scope=workspaceAccountCacheToken(),generation=workspaceBusinessStorage.generation();
      const current=()=>scope===workspaceAccountCacheToken()&&generation===workspaceBusinessStorage.generation();
      // Always read the authorized chat and freshly discover the exact installation/view.
      // A saved shortcut is only a reference; it cannot authorize a view or suppress input guards.
      await openRailConversationSession(row.chat_id,{forceWorkspace:true});if(!current())return;
      const panel=S.conversationPanel;if(Number(panel?.id)!==row.chat_id)return;
      await RunTeamsCreatorWork.openShortcut(row,()=>current()&&S.conversationPanel===panel);
    }catch(error){toast(error.message||'界面暂时无法打开，可从常用移除失效入口','err');}
    finally{opening=false;}
  }
  global.RunTeamsSidebarViews=Object.freeze({markup,pin,remove,open});
})(window);
