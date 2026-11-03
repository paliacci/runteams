"""Shared workflow start selection and execution visit limit."""
from .contracts import ContractError

MAX_VISITS = 50


def start_position(definition):
    position_keys = {item["key"] for item in definition.get("positions") or []}
    targets = {edge["to"] for edge in definition.get("edges") or []
               if edge.get("to") in position_keys}
    starts = [item["key"] for item in definition.get("positions") or []
              if item["key"] not in targets]
    if not starts and definition.get("positions"):
        starts = [definition["positions"][0]["key"]]
    if len(starts) != 1:
        raise ContractError("流水线必须有且只有一个起点")
    return starts[0]
