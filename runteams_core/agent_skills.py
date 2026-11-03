from runteams_core.resources import root as resource_root
"""Standard Agent Skills for platform workflows, loaded through native file tools.

Only names, descriptions and locations enter the initial model context. Full
instructions and resources remain ordinary portable SKILL.md directories.
Native CLI skills keep their own discovery, configuration and permissions.
"""
import hashlib
import json
from pathlib import Path

from .skill_metadata import frontmatter as _frontmatter


ROOT = resource_root() / 'agent_skills'
CHAT_SKILLS = ('runteams-employee-authoring', 'runteams-pipeline-design',
               'runteams-task-dispatch', 'runteams-automation-management',
               'runteams-document-work', 'runteams-work-report', 'runteams-work-item-triage',
               'runteams-work-execution', 'runteams-reply-content')
EMPLOYEE_SKILLS = ('runteams-work-execution', 'runteams-task-dispatch',
                   'runteams-document-work', 'runteams-work-report', 'runteams-automation-management',
                   'runteams-work-item-triage', 'runteams-reply-content')


def catalog(names):
    result = []
    for name in names:
        if not isinstance(name, str) or '/' in name or '\\' in name or name.startswith('.'):
            raise ValueError('平台技能名称无效')
        path = ROOT / name / 'SKILL.md'
        metadata = _frontmatter(path.read_text(encoding='utf-8'))
        if metadata['name'] != name:
            raise ValueError('平台技能目录与标准名称不一致')
        result.append({'name': name, 'description': metadata['description'],
                       'location': str(path.resolve())})
    return result


def revision(names=CHAT_SKILLS):
    """Invalidate resumed native contexts when loaded workflow bytes change."""
    digest = hashlib.sha256()
    from agent_guidance import BASE_AGENT_INSTRUCTION
    digest.update(BASE_AGENT_INSTRUCTION.encode('utf-8'))
    for item in catalog(names):
        directory = Path(item['location']).parent
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                digest.update(str(path.relative_to(ROOT.resolve())).encode())
                digest.update(b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def instructions(names=CHAT_SKILLS, *, required=None):
    skills = catalog(names)
    if required and required not in {item['name'] for item in skills}:
        raise ValueError('本轮必需的技能未提供')
    return ('# RunTeams 专业技能\n'
            '按当前工作匹配下列技能，先用原生文件工具读取其 location，再按需读取包内相对引用；'
            '相对路径以该 SKILL.md 所在目录解析。无需预读所有技能。'
            '用户明确要求优先于技能中的一般建议；技能说明不授予账户、外部操作或平台数据权限。'
            '当前官方 CLI 已启用的公开 Skills、插件、MCP 与原生工具照常可用，按任务采用。\n'
            + (('本轮使用技能：' + required + '。\n') if required else '')
            + json.dumps(skills, ensure_ascii=False))
