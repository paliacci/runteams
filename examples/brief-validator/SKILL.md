---
name: brief-validator
description: 员工交接工作前，确认结构化简报包含明确目标和可用上下文，避免下游收到无法执行的任务。
metadata:
  display_name: 交接简报检查方法
---

# 交接简报检查方法

把 JSON 交接简报传给其他员工前，使用 `scripts/validate_brief.py` 检查内容。
有效简报必须包含非空的 `objective`，并且 `context` 必须是对象。
