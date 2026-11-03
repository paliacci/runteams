"""Validate current device SQLite structure without upgrading saved data."""
from functools import lru_cache
import sqlite3


def execute(connection, script):
    """Execute trusted schema statements within the caller's transaction."""
    statement = ''
    for char in script:
        statement += char
        if char == ';' and sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ''
    if statement.strip():
        connection.execute(statement)


def structure(connection):
    return {(kind, name): ' '.join(sql.split()) for kind, name, sql in connection.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}


@lru_cache(maxsize=8)
def expected(script):
    with sqlite3.connect(':memory:') as connection:
        connection.executescript(script)
        return structure(connection)


def verify(connection, script):
    if structure(connection) != expected(script):
        raise ValueError('本机数据结构不受支持，原资料保持不变。')
