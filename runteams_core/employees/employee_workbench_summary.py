"""Platform-rendered workbench data from an employee's existing local state."""
from hashlib import sha256

from runteams_core.assets.collections.local_collections import Collections
from runteams_core.configuration.configuration_schema import managed_fields
from runteams_core.employees import managed_employee_data, source_employee_runtime
from runteams_core.employees.mcp.employee_applications import ApplicationTurn, storage_key
from runteams_core.storage import device_data


def eva_summary(reference, revision):
    description = source_employee_runtime.describe(reference, revision=revision, project_key='eva-executive-assistant')
    if description is None:
        return None
    employee = description['asset']['employee']
    fields = {row['key']: row for row in managed_fields(employee.get('configuration', {}))}
    if not {'mail_history', 'gmail_sync'} <= fields.keys():
        return None

    store = Collections()
    counts = dict.fromkeys(('reply', 'action', 'waiting', 'reference', 'archived'), 0)
    drafts, cursor = 0, ''
    history = managed_employee_data.existing(reference, fields['mail_history'])
    if history:
        for _ in range(10):
            page = store.query(fields['mail_history'], history, limit=100, cursor=cursor)
            for row in page['items']:
                category = row['value'].get('category')
                if isinstance(category, str) and category in counts:
                    counts[category] += 1
                    drafts += bool(row['value'].get('draft_id'))
            cursor = page['next_cursor']
            if not cursor:
                break

    applications = ApplicationTurn(storage_key(reference), device_data.identity(), None, None).bindings()
    accounts = {service: applications.get('composio:' + service, {}).get('account')
                for service in ('gmail', 'outlook', 'googlecalendar', 'googlemeet')}
    gmail_sync = False
    if accounts['gmail']:
        checkpoint = managed_employee_data.existing(reference, fields['gmail_sync'])
        if checkpoint:
            binding_key = sha256((accounts['gmail'].get('id') or 'composio:gmail').encode()).hexdigest()
            key = sha256(binding_key.encode()).hexdigest()
            gmail_sync = store.read(fields['gmail_sync'], checkpoint, key)['exists']
    store.check()
    return {'kind': 'eva-inbox', 'total': sum(counts.values()), 'counts': {**counts, 'drafts': drafts},
            'limited': bool(cursor), 'connections': {key: bool(account) for key, account in accounts.items()},
            'gmail_initialized': gmail_sync}
