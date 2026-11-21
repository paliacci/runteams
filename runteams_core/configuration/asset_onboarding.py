"""Validate and project the optional, versioned guide carried by an asset."""
from runteams_core.configuration.configuration_schema import fields

FIELD_TYPES = frozenset({'text', 'textarea', 'select', 'multiselect', 'checklist'})
MAX_STEPS = 8


def eligible_fields(definition):
    return {field['key']: field for field in fields(definition) if field['type'] in FIELD_TYPES}


def _copy(value, limit, *, empty=False):
    if (not isinstance(value, str) or len(value) > limit or
            (not empty and not value.strip()) or any(ord(char) < 32 and char != '\n' for char in value)):
        raise ValueError('引导文案无效。')
    return value.strip()


def validate_guide(steps, definition):
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        raise ValueError('使用引导步骤无效。')
    requirements = {application['key'] for application in definition.get('application_requirements', [])}
    supported, seen, seen_apps, result = eligible_fields(definition), set(), set(), []
    for step in steps:
        if not isinstance(step, dict) or set(step) - {'application'} != {'title', 'description', 'questions'}:
            raise ValueError('使用引导步骤格式无效。')
        title = _copy(step['title'], 100)
        description = _copy(step['description'], 600, empty=True)
        questions = step['questions']
        application = step.get('application')
        if 'application' in step:
            if not isinstance(application, str) or application not in requirements or application in seen_apps:
                raise ValueError('引导必须引用唯一且已声明的应用需求。')
            seen_apps.add(application)
        if not isinstance(questions, list) or len(questions) > 8 or not (questions or description or application):
            raise ValueError('使用引导内容无效。')
        checked = []
        for question in questions:
            if not isinstance(question, dict) or set(question) - {'placeholder'} != {'field', 'prompt'}:
                raise ValueError('引导问题格式无效。')
            key = question['field']
            if not isinstance(key, str) or key not in supported or key in seen:
                raise ValueError('引导问题必须引用唯一且可填写的配置字段。')
            seen.add(key)
            item = {'field': key, 'prompt': _copy(question['prompt'], 160)}
            if 'placeholder' in question:
                if supported[key]['type'] not in ('text', 'textarea'):
                    raise ValueError('只有文字输入支持引导示例。')
                item['placeholder'] = _copy(question['placeholder'], 80)
            checked.append(item)
        result.append({'title': title, 'description': description, 'questions': checked,
                       **({'application': application} if application else {})})
    return result


def remaining_steps(definition, states):
    def has_setup(step):
        return step['questions'] or step.get('application')

    steps = definition.get('onboarding', [])
    remaining = [step for step in steps if step.get('application') or not step['questions'] or
                 any(states.get(question['field']) in ('missing', 'needs_review') for question in step['questions'])]
    if any(map(has_setup, steps)) and not any(map(has_setup, remaining)):
        return []
    return remaining

