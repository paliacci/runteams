"""Shared names only; no account binding, publication or execution authority."""
NAMES = ('runteams_describe_creator_work', 'runteams_read_creator_object')
INVOKE_NAME = 'runteams_invoke_creator_operation'
RECEIPT_NAME = 'runteams_get_creator_operation'
ALL_NAMES = NAMES+(INVOKE_NAME,RECEIPT_NAME)
