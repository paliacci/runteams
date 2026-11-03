"""Bound author JSON-schema work in a separate process, never the Chat process."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from runteams_core.authoring.creator_contracts import CreatorContractError, canonical


def _worker(payload):
    raw = canonical(payload)
    if len(raw) > 128 * 1024:
        raise CreatorContractError('schema_budget')
    from runteams_core.authoring.workers.creator_worker_process import command
    with tempfile.TemporaryFile() as inp, tempfile.TemporaryFile() as out:
        inp.write(raw); inp.seek(0)
        # No credential environment or inherited descriptors in author validation.
        process = subprocess.Popen(command('schema'), stdin=inp,
            stdout=out, stderr=subprocess.DEVNULL, start_new_session=True,
            env={'PATH': os.defpath, 'LANG': 'en_US.UTF-8'})
        try:
            deadline = time.monotonic() + 3
            while process.poll() is None:
                if time.monotonic() > deadline:
                    raise CreatorContractError('schema_budget')
                from runteams_core.authoring.creator_process_memory import process_rss
                try:
                    rss = process_rss(process.pid)
                except (OSError, ValueError, StopIteration, subprocess.TimeoutExpired) as error:
                    raise CreatorContractError('schema_budget') from error
                if rss > 128 * 1024 * 1024:
                    raise CreatorContractError('schema_budget')
                time.sleep(0.01)
            out.seek(0)
            raw = out.read(1025)
            if len(raw) > 1024:
                raise RuntimeError('SDK 源码校验服务返回异常，请检查应用运行环境。')
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeError):
                raise RuntimeError('SDK 源码校验服务无法启动或返回异常，请检查应用运行环境。') from None
            error = result.get('error') if isinstance(result, dict) else None
            if isinstance(error, dict) and error.get('code') == 'validator_unavailable':
                raise RuntimeError('SDK 源码校验服务缺少运行依赖，请修复应用运行环境；这不是员工源码错误。')
            if process.returncode != 0:
                if isinstance(error, dict) and error.get('code') == 'invalid_author_schema':
                    raise CreatorContractError('invalid_author_schema', str(error.get('detail') or '无效的工作声明。'))
                raise RuntimeError('SDK 源码校验服务异常退出，请检查应用运行环境。')
            if result != {'valid': True}:
                raise CreatorContractError('invalid_author_data')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def validate_schemas(schemas):
    _worker({'schemas': schemas})


def validate_data(schema, value):
    _worker({'schemas': [schema], 'value': value})


def validate_values(schema, values):
    _worker({'schemas': [schema], 'values': values})


def validate_instances(instances):
    """One bounded worker for mixed frozen schemas, never one process per row."""
    _worker({'schemas': [schema for schema, _ in instances],
             'instances': [value for _, value in instances]})
