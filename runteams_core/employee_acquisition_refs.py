"""Deterministic signed-asset reference metadata, never an acquisition grant."""
from .creator_contracts import digest


def source_id(pin):
    return digest({'installation_id': pin['installation_id'], 'employee_source': pin['employee_source']})


def acquisition(pin):
    return {key: pin[key] for key in ('installation_id', 'release_id', 'rental_source_id') if key in pin}
