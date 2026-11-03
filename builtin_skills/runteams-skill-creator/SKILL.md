---
name: runteams-skill-creator
description: 将用户的工作方法整理成可复用技能，制作代表性用例并实际评估，改进技能内容和触发条件；不把结构检查当成效果证明。
metadata:
  display_name: 技能创建与评估
---

# 技能创建与评估

先读取本包 `upstream/skill-creator/SKILL.md`，按需读取其中的评估、评分及资源说明。该目录保留 Anthropic 原文、脚本与许可证，固定来源见 `upstream-sources.json`。本入口由 RunTeams 编写，负责产品与运行渠道适配。

明确用户希望交付的结果、适用输入和不适用情形；信息足够时直接制作技能，不把访谈问题全部抛给用户。生成完整的 `SKILL.md` 和确有用途的脚本、参考资料，资源引用使用包内相对路径。

用至少一个正常输入、一个边界输入和一个失败或不适用输入实际检查。复杂技能采用同条件的旧版或无技能对照，保存任务输入、实际产物、发现的问题与改进；结构有效、脚本退出成功和员工自述都不等于效果好。比较结果不支持结论时明确说明。

## RunTeams 适配

- 技能是员工完整作品内部的资源。在员工创作对话与设置中的资产编辑器里修改同一作品源树，随员工资产一起检查、保存和发布。目录名与 YAML name 保持一致，中文名称用 metadata.display_name；不写数据库或自行调用保存接口。员工任务交付的技能目录是资源，只有实际完成员工资产保存或发布后才说明对应结果。
- 产品派工技能使用 [正式扩展合同](references/product-extension-contract.json) 生成 runteams.package-extension/v3 的稳定 work：按目标定义工作、输入、交付和完成要求，步骤来自具体方法与代表样例。方法仍在 SKILL.md，脚本和参考资料保持独立。标准资源可没有 work，但不能从正文猜为正式工作。删除 capabilities、network_access、default_mount；不写本机账户、原件路径或模型执行凭据。
- work.input_schema 直接约束业务参数，例如字符统计的输入是 `{"text":"A😀"}`，不是 `{"parameters":{"text":"A😀"}}`。任务信封的 schema、objective、context、parameters、inputs、module_bindings、asset_bindings 不进入业务输入声明。work.output_schema 直接约束 `{"count":2}` 等业务结果，不包装平台 complete.output 或工具回执。
- 代表样例的输入、实际脚本输入和正式业务参数必须对应；读回实际产物后按 output_schema 核对。正常、缺参和错误类型都要检查声明与方法，不能用“本地全部通过”掩盖真正派工参数不被声明接受。员工选用、发布和真实派工由产品流程另验；不能为自验绕过产品装配员工。
- 可点击的工作示例属于正式 work.examples（title、prompt）与 show_in_overview，不属于员工草稿。未声明或 examples=[] 就是零示例；不从正文、样例资源或旧 trial_input 猜测恢复。提示示例不构成业务授权、资产授权或路径权限。
- 只有实际使用产品功能接口时记录完整的 module_id、interface_version、operations、optional；文件处理、原生插件、MCP 和联网能力不是产品模块依赖。独立技能保持零依赖，不能猜测依赖或授予账户权限。
- 采用当前官方 Agent Runtime 的原生执行与可用评估方式。上游 `run_eval.py`、`run_loop.py` 和 `improve_description.py` 专用于 Claude CLI 的触发评估；仅在当前渠道为 Claude、官方 CLI 已可用且该评估确有需要时采用，不能在 Codex 下为评估另起 Claude、安装渠道或使用 raw LLM API。
- 普通格式验证、打包、评分汇总等不依赖模型的脚本可直接复用，按脚本要求准备任务内依赖。不要让技能声明成为原生能力白名单。
- 不强迫用户打开上游的独立评估网页；RunTeams 的对话、资源和实际结果承担反馈。需要查看 HTML 评估文件时交付为可查看资源。

交付先说明技能解决什么、实际验证了什么和仍有哪些限制；完整测试和对照记录留在资源中。

## 正式工作与代表样例

工作范围和完成标准见 [runteams.json](runteams.json)，代表样例见 [references/work-examples.json](references/work-examples.json)。只把实际执行且读回核对的结果称为工作完成；结构、健康检查和模拟分别记录。
