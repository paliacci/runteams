"""Pure local-collection schema admission, independent of employee configuration."""
from functools import lru_cache
from runteams_core.authoring.creator_contracts import strict_json


@lru_cache(maxsize=128)
def _collection_schema_checked(raw):
    from runteams_core.authoring.compilation.creator_validation import validate_schemas
    validate_schemas([strict_json(raw)])


def validate_binding(binding):
    if (binding.get('provider') != 'local_collection' or binding.get('resource_kind') != 'collection'
            or binding.get('access') not in ('read', 'read_write')
            or not isinstance(binding.get('record_schema'), dict)
            or binding['record_schema'].get('type') != 'object'):
        raise ValueError('数据集合必须声明字段结构和读写范围。')
    from runteams_core.authoring.creator_contracts import canonical
    # Only immutable public schema validity is cached. Resource/actor/rights
    # are always checked against live data and never use this cache.
    _collection_schema_checked(canonical(binding['record_schema']))
    return binding['record_schema']

