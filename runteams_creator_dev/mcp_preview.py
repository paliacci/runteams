"""Browser development transport for the shared official MCP Apps host."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hmac
import json
import secrets
from urllib.parse import urlsplit


def serve(preview,port=0,*,ready=None):
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,body,headers):
            self.send_response(status)
            for key,value in headers.items():self.send_header(key,value)
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            try:
                path=urlsplit(self.path)
                if path.query:raise ValueError()
                name='/views/mcp-host.html' if path.path=='/' else path.path
                body,headers=preview.asset(name)
                if name=='/views/mcp-host.html':
                    adapter=('<script>if(window.top===window){const media=matchMedia("(prefers-color-scheme:dark)");Object.defineProperty(window,"runteamsHost",{value:Object.freeze({getSnapshot:()=>({theme:media.matches?"dark":"light"}),subscribe:callback=>{media.addEventListener("change",callback);return()=>media.removeEventListener("change",callback)}})});Object.defineProperty(window,"runteamsUI",{value:Object.freeze({methods:'+json.dumps(sorted(preview.methods))+
                        ',call:async(method,params)=>{const response=await fetch("/preview-message",{method:"POST",headers:{"Content-Type":"application/json","Authorization":"Bearer '+token+'"},body:JSON.stringify({method,params})});const result=await response.json();if(!response.ok||!result.ok)throw Error("Preview result is unconfirmed");return result}})});}</script>').encode()
                    body=body.replace(b'<head>',b'<head>'+adapter,1) if b'<head>' in body else body.replace(b'<meta charset=',adapter+b'<meta charset=',1)
                    headers['Content-Security-Policy']+="; frame-ancestors 'none'"
                self.reply(200,body,headers)
            except Exception:self.reply(403,b'Preview unavailable',{'Content-Type':'text/plain','Cache-Control':'no-store'})
        def do_POST(self):
            origin='http://127.0.0.1:'+str(self.server.server_port)
            try:
                if (self.path!='/preview-message' or self.headers.get('Host')!=origin.removeprefix('http://') or
                        self.headers.get('Origin')!=origin or self.headers.get('Sec-Fetch-Site')=='cross-site' or
                        not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token) or
                        self.headers.get('Content-Type')!='application/json' or self.headers.get('Transfer-Encoding')):raise PermissionError()
                length=int(self.headers.get('Content-Length','0'))
                if not 1<=length<=16384:raise ValueError()
                from runteams_core.creator_contracts import strict_json
                value=strict_json(self.rfile.read(length))
                if set(value)!={'method','params'} or not isinstance(value['params'],dict):raise ValueError()
                result=preview.message(value['method'],value['params']);status=200
            except Exception:result={'ok':False,'error':'预览操作未获确认，请核对源码、授权和原结果。'};status=403
            self.reply(status,json.dumps(result,ensure_ascii=False).encode(),{'Content-Type':'application/json','Cache-Control':'no-store'})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    value={'url':'http://127.0.0.1:'+str(server.server_port),'scope':'local-code-development-preview',
           'author_code_started':False,'cloud_verified':False,'published':False}
    if ready:ready(value)
    else:print(json.dumps(value,ensure_ascii=False),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:preview.close();server.server_close()
