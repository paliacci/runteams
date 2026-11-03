"""Explicit development preview over the existing official MCP client/Apps host.

No account, business provider, publication, automatic consent or model runtime.
Node is ordinary-user author code, not an offline/OS sandbox.
"""
import html
import json
from pathlib import Path
import sys
from runteams_core.foundation.resources import root as resource_root
import threading
import uuid

from runteams_core.authoring.creator_contracts import digest
from runteams_core.employees.mcp.employee_mcp import EmployeeMCP, WorkBinding, MCPError
from runteams_core.employees.mcp.employee_mcp_package import MCPBundle
from runteams_core.employees.mcp.employee_mcp_resource import _resource_html, host_html


class MCPPreview:
    methods=frozenset({'mcp.preview.enable','mcp.preview.select','mcp.tools.call'})

    def __init__(self,built,runtime,root,*,check=lambda:None,account_scope='development'):
        self.built,self.runtime,self.root,self.check_callback=built,runtime,Path(root).absolute(),check
        self.binding=WorkBinding(account_scope,built['manifest']['project_key'],digest(built['manifest']),str(uuid.uuid4()))
        self.packages={row['source']:MCPBundle.inspect(built['artifacts'][row['artifact']]) for row in built['manifest']['execution']['packages']}
        self.enabled=False;self.closed=False;self.unknown=False;self.sessions={};self.choices={};self.selected=None
        self.lock=threading.RLock()

    def check(self):
        if self.closed:raise PermissionError('本机预览已关闭。')
        try:self.check_callback()
        except BaseException:self.close();raise

    def authorize(self,binding,package,action,detail):
        self.check()
        return self.enabled and binding==self.binding and any(p.digest==package for p in self.packages.values())

    def enable(self):
        with self.lock:
            self.check()
            if self.enabled:return
            if self.runtime is None:raise MCPError('mcp_platform_runtime_unavailable')
            self.runtime.verify();self.enabled=True
            try:
                for source,package in self.packages.items():
                    session=EmployeeMCP(runtime=self.runtime,bundle=package,package_root=package.materialize(self.root/'packages'),
                        work_root=self.root/'work',binding=self.binding,authorize=self.authorize)
                    self.sessions[source]=session
                    for tool in session.list_tools():
                        if tool.get('_meta',{}).get('ui',{}).get('resourceUri'):
                            key=digest({'source':source,'tool':tool['name']});self.choices[key]=(source,tool['name'])
                self.selected=next(iter(self.choices),None)
            except BaseException:
                self.enabled=False
                for session in self.sessions.values():session.close()
                self.sessions={};self.choices={};raise

    def message(self,method,params):
        self.check()
        if method=='mcp.preview.enable' and params=={}:
            self.enable();return {'ok':True,'result':{'enabled':True}}
        if method=='mcp.preview.select' and set(params)=={'id'} and params['id'] in self.choices and self.enabled:
            self.selected=params['id'];return {'ok':True,'result':{'selected':True}}
        if method!='mcp.tools.call' or set(params)!={'name','arguments'} or not isinstance(params['arguments'],dict) or not self.enabled or not self.selected:
            raise PermissionError('请先明确启用当前本机预览。')
        source,_=self.choices[self.selected]
        try:result=self.sessions[source].call_tool(params['name'],params['arguments'],source='app')
        except BaseException:
            self.unknown=True;self.enabled=False
            for session in self.sessions.values():session.close()
            raise
        return {'ok':True,'result':result}

    def run_tests(self,specification):
        if (not isinstance(specification,dict) or set(specification)!={'schema','cases'} or
                specification['schema']!='runteams.mcp-dev-tests/1' or not 1<=len(specification['cases'])<=64):
            raise ValueError('请提供当前员工的非空 MCP 自测案例。')
        self.enable();results=[]
        for case in specification['cases']:
            if set(case)!={'name','tool','input','expect'}:raise ValueError('MCP 自测案例格式无效。')
            candidates=[s for s in self.sessions.values() if case['tool'] in {t['name'] for t in s.list_tools()}]
            if len(candidates)!=1:raise ValueError('自测工具不存在或不能唯一确定。')
            actual=candidates[0].call_tool(case['tool'],case['input'],source='agent')
            if actual.get('isError') or actual.get('structuredContent')!=case['expect']:raise ValueError('MCP 自测未通过：'+case['name'])
            results.append({'name':case['name'],'passed':True})
        return results

    def asset(self,path):
        self.check()
        policy="default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; frame-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'"
        mime='text/html; charset=utf-8'
        if path=='/views/mcp-host.html':
            if self.enabled and self.selected:
                source,_=self.choices[self.selected];session=self.sessions[source]
                choices=[{'id':key,'label':self.sessions[src].bundle.manifest.get('display_name',src)+'：'+tool,'selected':key==self.selected}
                    for key,(src,tool) in self.choices.items()]
                body=host_html(session.bundle.manifest.get('display_name',session.bundle.manifest['name']),session.list_tools(),{},previews=choices)
            else:body=self.consent_html()
        elif path=='/views/app-host.js' and self.enabled:
            self.runtime.verify();body=(self.runtime.root/'app-host.js').read_bytes();mime='text/javascript'
        elif path=='/views/mcp-app.html' and self.enabled and self.selected:
            source,tool=self.choices[self.selected];body,policy=_resource_html(self.sessions[source].read_app(tool))
        else:raise PermissionError('预览资源尚未启用。')
        return body,{'Content-Type':mime,'Content-Security-Policy':policy,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'}

    def consent_html(self):
        root=resource_root()
        folder=root/'sdk/ui/dist'
        if folder.is_dir():css=(folder/'foundation/theme.css').read_text()+(folder/'components/styles.css').read_text()
        else:css=(root/'web/ui/kit/theme.css').read_text()+(root/'web/ui/kit/components/styles.css').read_text()
        if not self.packages:content='<p>这名员工无需运行本机程序，可直接在工作对话中交办任务。</p>'
        elif self.enabled:content='<p>此程序未提供界面。可以使用开发工具运行自测。</p>'
        else:content=(' <p>这是本机开发预览，不代表员工已发布或取得平台业务权限。</p>'
            '<p>启用后，作者程序会以你的普通用户身份运行，可能访问本机文件和网络。仅启用你信任的源码。</p>'
            +('<p role="alert">原操作结果尚未确认。重新启用不会自动重发工具调用，请先核对原结果。</p>' if self.unknown else '')+
            '<label><input type="checkbox" id="trust"> 我信任并允许当前源码在本机运行。</label>'
            '<p><button class="rt-button rt-primary-button" id="enable" disabled>启用本机预览</button></p>'
            '<p id="error" role="alert"></p><script>document.getElementById("trust").onchange=e=>{document.getElementById("enable").disabled=!e.target.checked};'
            'document.getElementById("enable").onclick=async()=>{const b=document.getElementById("enable");b.disabled=true;try{await window.runteamsUI.call("mcp.preview.enable",{});location.reload()}catch{document.getElementById("error").textContent="预览尚未启用，请核对运行资源和源码。";b.disabled=false}};</script>')
        return ('<!doctype html><html lang="zh-CN" data-rt-ui><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+
            'body{padding:24px;margin:0}main{max-width:640px}p{line-height:1.7}</style><body data-rt-ui><main><h2>'+html.escape((self.built.get('compiled') or {}).get('project',{}).get('name') or self.built['manifest']['project_key'])+'</h2>'+content+'</main></body></html>').encode()

    def close(self):
        self.closed=True;self.enabled=False
        for session in self.sessions.values():session.close()
