"""Optional host tool adapters; context or tool arguments never select a provider."""
from runteams_core.storage.storage_context import current_provider


def native_employee(name, arguments, context):
    return current_provider().native_employee_tool(name, arguments, context)


def creator_source(arguments, context):
    return current_provider().creator_source_tool(arguments, context)


def creator_resource(name, arguments, context):
    return current_provider().creator_resource_tool(name, arguments, context)
