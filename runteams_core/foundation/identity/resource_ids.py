"""Canonical creator UUID syntax; not a route or access grant."""
import uuid
from runteams_core.authoring.creator_contracts import CreatorContractError


def resource_id(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise CreatorContractError('invalid_resource_ref') from None
