"""Editable Node/MCP Apps starter, explicitly a development example."""
from pathlib import Path
from runteams_core.creator_contracts import canonical
from runteams_core.employee_mcp_package import sha256


def make(key,name,libraries):
    libraries=Path(libraries)
    vendor={name:(libraries/name).read_bytes() for name in ('server.cjs','app.js','theme.css','components.css','THIRD_PARTY_NOTICES.txt','creator-server.cjs.LEGAL.txt','creator-app.js.LEGAL.txt')}
    project={'schema':'runteams.creator-project/2','key':key,'version':'1.0.0','name':name,'sdk':'mcp-apps/1-dev',
        'entrypoints':{'employees':['employees/main.json']},'dependency_lock':'dependencies.lock.json',
        'source_access':{'default':'author','public_files':[]}}
    work={'name':'SDK 接线示例','summary':'返回输入文字，用于验证自定义工具与页面接线。','objective':'验证本机工具的实际返回。',
        'input_schema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']},'output_schema':{'type':'object'},
        'steps':[{'id':'echo','instruction':'通过 echo 工具返回明确输入的文字。'}],
        'acceptance':[{'id':'same','label':'原文一致','criterion':'实际工具返回与输入一致。'}],
        'deliverables':[],'assets':[],'result_actions':[]}
    files={'project.json':canonical(project),'dependencies.lock.json':canonical({'schema':'runteams.dependencies/2','root':key,
        'runtime':{'protocol':'mcp','managed_node':'24'},'dependencies':[]}),
        'employees/main.json':canonical({'schema':'runteams.employee-source/3','key':'main','name':name,'avatar':'👤',
            'soul_file':'employees/soul.md','skill_dirs':['skills/worker'],'runtime_requirement':{'provider':'codex','model':'','effort':''}}),
        'employees/soul.md':'这是可编辑的 SDK 开发示例。通过本机工具核对真实返回，不宣称完成平台业务。\n'.encode(),
        'skills/worker/SKILL.md':b'---\nname: worker\ndescription: Editable local MCP development example\n---\nUse the echo tool to check the explicitly supplied text. This example is not a published employee or a business transaction.\n',
        'skills/worker/runteams.json':canonical({'schema':'runteams.package-extension/v3','display_name':name,'work':work,'tools':[],'execution':{}}),
        'skills/worker/mcp/manifest.json':canonical({'manifest_version':'0.3','name':key,'display_name':name,'version':'1.0.0',
            'description':'Editable local employee program','author':{'name':'Creator'},'server':{'type':'node','entry_point':'server.cjs'},
            'compatibility':{'platforms':['darwin'],'architectures':['arm64']}}),
        'skills/worker/mcp/server.cjs':b'''const {McpServer,StdioServerTransport,registerAppTool,registerAppResource,z}=require('./vendor/server.cjs');
const fs=require('node:fs'),path=require('node:path');
const server=new McpServer({name:'employee-local-tools',version:'1.0.0'});
registerAppTool(server,'echo',{description:'Return the explicitly supplied text',inputSchema:z.object({text:z.string()}),
 _meta:{ui:{resourceUri:'ui://employee/main.html'}}},async({text})=>({content:[{type:'text',text}],structuredContent:{text}}));
registerAppResource(server,'Employee','ui://employee/main.html',{},async uri=>{
 let html=fs.readFileSync(path.join(__dirname,'ui/index.html'),'utf8');
 const read=name=>fs.readFileSync(path.join(__dirname,name),'utf8');
 html=html.replace('/* PLATFORM_THEME */',()=>read('vendor/theme.css')+'\\n'+read('vendor/components.css'))
  .replace('/* MCP_LIBRARY */',()=>read('vendor/app.js').replace(/<\\/script/gi,'<\\\\/script'))
  .replace('/* AUTHOR_APPLICATION */',()=>read('ui/app.js').replace(/<\\/script/gi,'<\\\\/script'));
 return {contents:[{uri:uri.href,mimeType:'text/html;profile=mcp-app',text:html}]};
});
server.connect(new StdioServerTransport()).catch(()=>{process.exitCode=1});
''',
        'skills/worker/mcp/ui/index.html':b'<!doctype html><html data-rt-ui lang="zh-CN"><meta charset="utf-8"><style>/* PLATFORM_THEME */ body{box-sizing:border-box;min-height:100vh;margin:0;padding:var(--rt-s4)} #preview-fields{display:grid;gap:var(--rt-s3);max-width:640px} #preview-fields label{display:grid;gap:var(--rt-s1)} #run{justify-self:start}</style><body data-rt-ui><script>/* MCP_LIBRARY */</script><script>/* AUTHOR_APPLICATION */</script></body></html>',
        'skills/worker/mcp/ui/app.js':'''const app=new RunTeamsMCP.App({name:'员工开发示例',version:'1.0.0'},{});
const body=document.createElement('div');body.id='preview-fields';body.innerHTML='<label>输入文字<input class="rt-input" id="text"></label><button class="rt-button rt-primary-button" id="run" disabled>运行示例</button><p id="result" role="status"></p>';
document.body.append(RunTeamsMCP.createSection({title:'开发预览',content:body}).element);
app.ontoolinput=()=>{document.getElementById('run').disabled=false;};
const theme=context=>{for(const target of [document.documentElement,document.body])target.dataset.theme=context?.theme||'light';};
app.onhostcontextchanged=theme;
document.getElementById('run').onclick=async()=>{const result=document.getElementById('result');try{const reply=await app.callServerTool({name:'echo',arguments:{text:document.getElementById('text').value}});result.textContent=reply.structuredContent.text;}catch{result.textContent='结果尚未确认，请核对原操作。';}};
app.connect().then(()=>theme(app.getHostContext()));
'''.encode()}
    for p,b in vendor.items():files['skills/worker/mcp/vendor/'+p]=b
    files['skills/worker/mcp/dependencies.lock.json']=canonical({'schema':'runteams.mcp-dependencies/1',
        'files':{'vendor/'+p:{'sha256':sha256(b),'size':len(b)} for p,b in sorted(vendor.items())}})
    return files


def scenarios():
    return {'schema':'runteams.mcp-dev-tests/1','cases':[{'name':'original-text','tool':'echo','input':{'text':'SDK ready'},'expect':{'text':'SDK ready'}}]}
