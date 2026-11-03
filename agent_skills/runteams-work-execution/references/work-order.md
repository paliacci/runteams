# 正式工作单协议

仅在当前入口实际提供 RunTeams MCP 工作单协议工具时使用。普通员工对话和沿普通 Chat 执行的定时工作不因名称相似而获得这些工具。

先用 get_task 读取本次工作单、当前步骤和真实合同。employee.soul 是岗位协作约定，employee.work 是本次选定工作的声明。读取 skill_resources 中相关完整 SKILL.md、脚本与参考资料，并按需采用当前可用的专业技能和原生能力。

以本次 objective、inputs、acceptance 和冻结合同为依据。合同有步骤时按 employee.work.steps 完成，并通过 advance_step 报告实际进展；包内确定性工具通过 run_capability 调用。effect=operation 的同一业务动作使用稳定 invocation_id，重试复用原键；checkpoint 中 in_doubt 操作先核实外部实际状态，不换键重放。

assets 是运行开始时授权资料的只读副本，位于 .runteams/assets/<name>。处理实际副本，不搜索或还原原件路径，不声称修改了原件。Git 副本可能包含已提交内容、授权范围内的未提交改动与未忽略新文件；依据 working_tree 和 excluded 描述实际范围。

存在 context.previous_result 或 work_order.recovery 时，核对原版本、已完成与未完成部分，接续目标和反馈，不把原部分覆盖当作完整基线。required_verifiers 必须在最终内容完成后通过。

## 成果登记与终态

按用户和岗位的用途组织交付。文件用 publish_artifact 登记，日志与测试回执 purpose=evidence，交付项目和普通附件用 attachment。document 需要冻结合同或明确阅读用途；额外文档说明 document_reason，不重复生成报告。需要状态与后续操作的对象使用实际业务工具，其他结构化结果放 complete.output。

完成后调用 complete，提交准确的 summary、完整 output 与已验证成果。没有可打开的成果入口但完成了实质判断时，work_done 用一至三条完成事实说明用户获得什么，避免重复 summary。result_actions 只返回冻结 work.result_actions 中对当前成果有用的动作 ID，不自动派发下一项工作或增加授权。

业务条件客观阻塞用 report_blocked，技术故障用 report_failed，真正需要用户决定用 request_human。根据本次实际结果提交对应终态；提交后停止，普通最终回复不能代替终态工具。岗位对产物格式的要求仍适用，平台工具必须采用自己的结构和合同。

summary、reason 与 recovery 面向委托人说明具体结果、关键限制与必要下一步；完整事实与交接留在 output、details 或证据中，不把部分检查说成全量通过、推断说成事实或派发说成完成。用户要求详细报告时按其要求交付。
