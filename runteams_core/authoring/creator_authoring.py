from runteams_core.foundation.resources import root as resource_root
"""Common SDK source helpers shared by the source store, tools and asset retention.

The local SDK source is authoritative. No cloud-project authoring adapter or
definition-authoring compatibility path is provided.
"""
import base64
import hashlib
from pathlib import PurePosixPath

from runteams_core.authoring.creator_contracts import ROOT, strict_json


# Explicit packaged references, independent of a developer checkout or network.
# Read the same bytes used by validators/builders; never accept an author path.
REFERENCES = {
    'project':'mcp-v1/project.schema.json',
    'dependencies':'mcp-v1/dependencies.schema.json',
    'authoring':'mcp-v1/AUTHORING.md',
}


def reference(kind):
    if kind not in REFERENCES:
        raise ValueError('请选择已提供的作品开发参考。')
    path = REFERENCES[kind]
    body = (ROOT / path).read_bytes()
    value={'kind': kind, 'sha256': hashlib.sha256(body).hexdigest(),
        **({'schema': strict_json(body)} if path.endswith('.json') else {'content': body.decode('utf-8')})}
    if kind=='authoring':
        from pathlib import Path
        root=resource_root()
        paths=['sdk/runtime/LICENSE', 'sdk/runtime/README.md', 'sdk/runtime/contract-provenance.json', 'sdk/runtime/index.d.ts', 'sdk/runtime/index.js', 'sdk/runtime/internal/guards.js', 'sdk/runtime/internal/requests.d.ts', 'sdk/runtime/internal/requests.js', 'sdk/runtime/package.json', 'sdk/shared/guards.js']
        value['native_runtime']={'host_expression':'globalThis.runteamsRuntimeHost','factory':'createRuntime',
            'capabilities':['connection.http'],'requires':['native library source owner','declared sdk_connection','explicit service consent','original program enablement','active admitted original MCP tool call'],
            'client_files':[file_payload('vendor/'+name,(root/name).read_bytes()) for name in paths]}
    return value


def config_context(session, value):
    current = session.get('context') or {}
    if current.get('creator_local_source_id') and value is not None:
        raise ValueError('作品绑定由创作流程维护，请只修改模型设置。')
    return value


def file_payload(path,body):
    fingerprint = {'path': path, 'sha256': hashlib.sha256(body).hexdigest(), 'size': len(body)}
    images = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
              '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml'}
    media = images.get(PurePosixPath(path).suffix.lower())
    if media:
        return {**fingerprint, 'kind': 'image', 'media_type': media,
            'data_url': 'data:' + media + ';base64,' + base64.b64encode(body).decode()}
    try:
        return {**fingerprint, 'kind': 'text', 'content': body.decode('utf-8')}
    except UnicodeDecodeError:
        return {**fingerprint, 'kind': 'binary', 'content_base64': base64.b64encode(body).decode()}

