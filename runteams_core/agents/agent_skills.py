from runteams_core.foundation.resources import root as resource_root
"""Standard Agent Skills for platform workflows, loaded through native file tools.

The initial model context includes the catalog and any shared reply defaults.
Full instructions and resources remain ordinary portable SKILL.md directories.
Native CLI skills keep their own discovery, configuration and permissions.
"""
import hashlib
import json
from pathlib import Path

from runteams_core.assets.skills.skill_metadata import frontmatter as _frontmatter


ROOT = resource_root() / 'agent_skills'
CHAT_SKILLS = ('runteams-employee-authoring', 'runteams-pipeline-design',
               'runteams-task-dispatch', 'runteams-automation-management',
               'runteams-document-work', 'runteams-work-report', 'runteams-work-item-triage',
               'runteams-work-execution', 'runteams-reply-content')
EMPLOYEE_SKILLS = ('runteams-work-execution', 'runteams-task-dispatch',
                   'runteams-document-work', 'runteams-work-report', 'runteams-automation-management',
                   'runteams-work-item-triage', 'runteams-reply-content')

REPLY_GUIDANCE = (
    '当用户要在对话里扫读、比较、排序、筛选或决定哪些记录要跟进，'
    '并且你已取得多条带共同字段的记录时，首轮最终答复默认包含原生交互视图。'
    '自行判断，无需用户点名组件：逐项比较和跟进用 Table，阅读内容和对话顺序用 Messages，'
    '比较可核对的同口径数值用 Chart。正文先给结论，逐条依据交给视图。'
    '单条事实、空结果、失败结果或用户指定纯文本时，用简短文字。'
    '使用视图前读取 runteams-reply-content 及其 references/protocol.md，'
    '在最终答复中输出有效的 runteams-view v2 围栏。'
    '逐项核对字段和值，保留缺失值，推断和建议要能与来源事实区分。'
)


def catalog(names, *, root=None):
    skill_root = ROOT if root is None else Path(root)
    result = []
    for name in names:
        if not isinstance(name, str) or '/' in name or '\\' in name or name.startswith('.'):
            raise ValueError('平台技能名称无效')
        path = skill_root / name / 'SKILL.md'
        metadata = _frontmatter(path.read_text(encoding='utf-8'))
        if metadata['name'] != name:
            raise ValueError('平台技能目录与标准名称不一致')
        result.append({'name': name, 'description': metadata['description'],
                       'location': str(path.resolve())})
    return result


def revision(names=CHAT_SKILLS, *, root=None):
    """Invalidate resumed native contexts when loaded workflow bytes change."""
    digest = hashlib.sha256()
    from runteams_core.agents.agent_guidance import BASE_AGENT_INSTRUCTION
    digest.update(BASE_AGENT_INSTRUCTION.encode('utf-8'))
    if 'runteams-reply-content' in names:
        digest.update(REPLY_GUIDANCE.encode('utf-8'))
    skill_root = ROOT if root is None else Path(root)
    for item in catalog(names, root=skill_root):
        directory = Path(item['location']).parent
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                digest.update(str(path.relative_to(skill_root.resolve())).encode())
                digest.update(b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def instructions(names=CHAT_SKILLS, *, required=None, root=None):
    skills = catalog(names, root=root)
    if required and required not in {item['name'] for item in skills}:
        raise ValueError('本轮必需的技能未提供')
    handoff = ('\n\n# 工作成果交接\n在已绑定员工工作且本轮提供汇报工具时，用户要清单、报告、方案或交给别人执行的结果时，用当前工作的 '
               'runteams_work_report 保存可独立使用的成果正文，现有 Markdown 文件可从工作目录 output/ 登记。'
               '写清范围、实际依据、待办、验收和未决事项；已保存的成果沿原入口引用。按工具成功回执提供文档链接，'
               '保存失败时修正可恢复的问题，说明剩余缺项。流水线沿当前岗位的结果合同提交，用户从原任务文档接手。'
               '短答、讨论、用户要求的特定格式或不保存按原约定处理。'
               if 'runteams-work-report' in names else '')
    return ('# RunTeams 专业技能\n'
            '按当前工作匹配下列技能，先用原生文件工具读取其 location，再按需读取包内相对引用；'
            '相对路径以该 SKILL.md 所在目录解析。无需预读所有技能。'
            '用户明确要求优先于技能中的一般建议；技能说明不授予账户、外部操作或平台数据权限。'
            '当前官方 CLI 已启用的公开 Skills、插件、MCP 与原生工具照常可用，按任务采用。\n'
            + (('本轮使用技能：' + required + '。\n') if required else '')
            + json.dumps(skills, ensure_ascii=False) + handoff
            + ('\n\n# 对话交付\n' + REPLY_GUIDANCE
               if any(item['name'] == 'runteams-reply-content' for item in skills) else ''))
