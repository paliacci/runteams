"""Strict finite UTF-8 JSON shared by local transport and source import."""
import json
import math


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('重复的请求字段。')
            result[key] = value
        return result

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('请求数字无效。')
        return result

    def invalid(value):
        raise ValueError('请求数字无效。')

    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                      parse_float=number, parse_constant=invalid)

