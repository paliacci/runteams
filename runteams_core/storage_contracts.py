"""Transport-independent storage errors and row values shared by local/native ports."""
from .contracts import ContractError

FILE_PREFIX = 'supabase-file://sha256/'
CHUNK_SIZE = 1024 * 1024

class BusinessCloudError(ContractError):
    pass


class BusinessCloudConflict(BusinessCloudError):
    pass


class BusinessCloudUnknown(BusinessCloudError):
    """A commit may have succeeded. Its operation ID must be checked, not replayed."""
    def __init__(self, operation_id):
        super().__init__('保存结果尚未确认，请检查连接后重新读取。')
        self.operation_id = operation_id


class CloudRow:
    def __init__(self, columns, values):
        self.columns = tuple(columns)
        self.values = tuple(values)

    def keys(self):
        return self.columns

    def __getitem__(self, key):
        return self.values[self.columns.index(key)] if isinstance(key, str) else self.values[key]

    def __iter__(self):
        return iter(self.values)

    def __len__(self):
        return len(self.values)


class CloudCursor:
    def __init__(self, value):
        self.description = [(key, None, None, None, None, None, None) for key in value['columns']] or None
        self._rows = [CloudRow(value['columns'], row) for row in value['rows']]
        self._position = 0
        self.lastrowid = value['lastrowid']
        self.rowcount = value['rowcount']

    def fetchone(self):
        if self._position >= len(self._rows):
            return None
        row = self._rows[self._position]
        self._position += 1
        return row

    def fetchall(self):
        rows = self._rows[self._position:]
        self._position = len(self._rows)
        return rows

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row
