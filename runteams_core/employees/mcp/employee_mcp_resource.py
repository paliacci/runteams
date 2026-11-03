"""Shared official Apps HTML and resource policy; no execution or credentials."""
import json
from urllib.parse import urlsplit
from runteams_core.employees.mcp.employee_mcp import MCPError, MCPAppResourceInvalid


def app_host_script(execution_runtime):
    """Verify the actual script bytes; execution retains its original runtime."""
    from runteams_core.employees.mcp.employee_mcp import presentation_runtime
    from runteams_core.employees.mcp.employee_mcp_package import sha256
    runtime = presentation_runtime(execution_runtime)
    runtime.verify()
    manifest = (runtime.root/'runtime.json').read_bytes()
    if sha256(manifest) != runtime.manifest_sha256:
        raise MCPError('mcp_runtime_integrity')
    script = (runtime.root/'app-host.js').read_bytes()
    if sha256(script) != json.loads(manifest)['files']['app-host.js']:
        raise MCPError('mcp_runtime_integrity')
    return script

def _resource_html(resource):
    # This is a completed resource, not a transport/tool outcome. A policy or
    # encoding rejection creates no bridge and cannot occupy an unknown slot.
    if not isinstance(resource, dict) or not isinstance(resource.get('text'), str):
        raise MCPAppResourceInvalid('mcp_app_resource_invalid')
    meta = resource.get('_meta', {})
    if not isinstance(meta, dict):
        raise MCPAppResourceInvalid('mcp_app_resource_invalid')
    ui = meta.get('ui', {})
    if not isinstance(ui, dict):
        raise MCPAppResourceInvalid('mcp_app_resource_invalid')
    # New device/cross-origin privileges need a trusted product grant; no
    # automatic iframe allow list based on an author's self-declaration.
    permissions = ui.get('permissions', {})
    if not isinstance(permissions, dict) or permissions:
        raise MCPAppResourceInvalid('mcp_app_permissions_not_granted')
    csp = ui.get('csp', {})
    if not isinstance(csp, dict):
        raise MCPAppResourceInvalid('mcp_app_csp_invalid')
    def domains(key):
        values = csp.get(key, [])
        if not isinstance(values, list) or len(values) > 32:
            raise MCPAppResourceInvalid('mcp_app_csp_invalid')
        for value in values:
            if not isinstance(value, str):
                raise MCPAppResourceInvalid('mcp_app_csp_invalid')
            try:
                url = urlsplit(value)
                valid = (url.scheme == 'https' and url.hostname and not url.username and not url.password and
                         url.path in ('', '/') and not url.query and not url.fragment and
                         not any(c in value for c in "'\"; <>\\\n\r"))
            except ValueError:
                valid = False
            if not valid:
                raise MCPAppResourceInvalid('mcp_app_csp_invalid')
        return ' '.join(values) or "'none'"
    for key in ('frameDomains', 'baseUriDomains'):
        values = csp.get(key, [])
        if not isinstance(values, list):
            raise MCPAppResourceInvalid('mcp_app_csp_invalid')
        if values:
            raise MCPAppResourceInvalid('mcp_app_csp_unsupported')
    connect, resources = domains('connectDomains'), domains('resourceDomains')
    images = 'data:' if resources == "'none'" else 'data: ' + resources
    policy = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
              f"connect-src {connect}; img-src {images}; "
              f"font-src {resources}; media-src {resources}; frame-src 'none'; object-src 'none'; "
              "base-uri 'none'; form-action 'none'")
    try:
        html = resource['text'].encode('utf-8')
    except UnicodeEncodeError as error:
        raise MCPAppResourceInvalid('mcp_app_resource_invalid') from error
    return html, policy


def host_html(title, tools, input_value, *, previews=None):
    config=json.dumps({'title':title,'input':input_value,'tools':tools,**({'previews':previews} if previews else {})},ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
    return ('<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>html,body{margin:0;width:100%;height:100%;overflow:hidden}</style></head><body>'
        '<script id="mcp-app-data" type="application/json">'+config+'</script>'
        '<script type="module" src="/views/app-host.js"></script></body></html>').encode('utf-8')
