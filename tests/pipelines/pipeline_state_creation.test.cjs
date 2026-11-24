const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const source=fs.readFileSync('web/ui/source-pipelines.js','utf8');
function fixture(){
 const columns=['employee','approval','done','dropped','pool'].map(kind=>({key:kind,kind,name:kind,tone:'gray'}));
 const state={reference:{},data:{ui:{mode:'installed'},runtime:{status:'running'},workflows:[]}};
 const context=vm.createContext({S:{sel:null},current:()=>state,captureComposer(){},
  RunTeamsSourcePipelinePanels:{columns:()=>columns,columnAvatar:()=>''},
  boardWorkflows:()=>[],boardEmpty:()=>'',esc:String,ICON:()=>'',coreWorkflowCard:()=>'',
  composeCard:(_s,c)=>`<section data-compose="${c.key}"></section>`,queuedComposeCard:()=>''});
 vm.runInContext(source.slice(source.indexOf(' function board(){'),source.indexOf(' function workspace(){')),context);
 return {context,state,columns};
}
test('all visible board positions offer task creation and preserve state styling',()=>{
 const {context,columns}=fixture();const html=context.board();
 assert.equal((html.match(/class="addcard core-add-task"/g)||[]).length,5);
 for(const column of columns)assert.ok(html.includes(`class="addcard core-add-task" data-position="${column.key}"`));
 assert.equal((html.match(/column-status core-state-column/g)||[]).length,3);
});
test('paused boards disable creation; pending state admission keeps recovery on the same column',()=>{
 const {context,state}=fixture();state.data.runtime.status='paused';
 assert.equal((context.board().match(/ disabled>/g)||[]).length,5);
 state.pending={start_column_key:'done'};const html=context.board();
 assert.equal((html.match(/ disabled>/g)||[]).length,4);
 assert.match(html,/data-position="done" onclick="RunTeamsSourcePipelines.compose\(this.dataset.position\)" ><span data-app-i18n="pipelineBoard.checkTask"/);
});
