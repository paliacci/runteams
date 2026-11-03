"""Canonical frozen worker entry, dispatched before any application/account imports."""
import sys

FLAGS={'--runteams-creator-inspect','--runteams-creator-schema','--runteams-creator-build'}


def dispatch(arguments):
    if len(arguments)!=1 or arguments[0] not in FLAGS:return False
    if arguments[0]=='--runteams-creator-inspect':
        from runteams_core.authoring.workers import creator_import_worker
    elif arguments[0]=='--runteams-creator-schema':
        from runteams_core.authoring.workers import creator_validator_worker
    else:
        from runteams_core.authoring.workers import creator_local_build_worker
    return True
