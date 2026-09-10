import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_SOURCE = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
WEB_STYLES = (ROOT / "web" / "runteams.css").read_text(encoding="utf-8")
COPY_GUIDE = (ROOT / "design" / "PRODUCT_COPY.md").read_text(encoding="utf-8")


class WebProductCopyTests(unittest.TestCase):
    def test_agent_real_ui_tests_cover_the_full_message_gallery(self):
        for label in (
            "普通文本", "附件与技能", "正在发送", "等待响应", "正在执行",
            "流式回复", "完成回复", "已停止", "执行失败", "需要选择",
            "等待确认", "正在应用", "已应用", "运行检查正常",
            "运行检查警告", "运行检查阻塞", "结构化草稿",
        ):
            self.assertIn('label:"{}"'.format(label), WEB_SOURCE)
        for group in ("用户消息", "助手消息", "交互状态", "运行检查", "业务草稿"):
            self.assertIn('group:"{}"'.format(group), WEB_SOURCE)

    def test_core_employee_drawer_owns_team_standard_tabs_and_motion(self):
        for retired_name in ("workersDrawerTab", "positionWorkersTabIndicator"):
            self.assertNotIn(retired_name, WEB_SOURCE)
        for active_name in (
                "corePipelinePeopleTab", "animateCorePipelinePeopleTab",
                "positionCorePipelinePeopleTabIndicator", "data-workers-tab",
                "window.setTimeout(done,190)"):
            self.assertIn(active_name, WEB_SOURCE)
        self.assertGreaterEqual(
            WEB_SOURCE.count('workers-drawer-footer workers-list-create-footer'), 2)

    def test_pipeline_header_uses_one_bordered_operation_status(self):
        self.assertNotIn("pipeline-check-trigger", WEB_SOURCE)
        self.assertNotIn("sk-pipeline-usage", WEB_SOURCE)
        self.assertNotIn("sk-pipeline-usage", WEB_STYLES)
        self.assertIn("state-running is-running soft", WEB_SOURCE)
        self.assertIn(
            ".vhead .pipeline-run-toggle{border:1px solid var(--line)}",
            WEB_STYLES)

    def test_team_header_keeps_only_the_employee_action(self):
        team = WEB_SOURCE.split("function coreTeamMain(){", 1)[1].split(
            "function corePipelineMenu", 1)[0]
        self.assertIn('${create}</div>`:""}', team)
        self.assertNotIn('onclick="openFailureStats()"', team)
        self.assertNotIn('onclick="corePipelineMenu(event)"', team)

    def test_boot_applies_the_url_rail_mode_before_the_first_real_render(self):
        boot = WEB_SOURCE.split("async function boot(){", 1)[1].split(
            "let _interventionsRefreshPromise", 1)[0]
        initial = 'const initialRail=parseRailRoute(new URLSearchParams(location.search));'
        applied = 'S.railMode=initialRail.mode;if(initialRail.mode==="assistant")S.railCollapsed=false;'
        self.assertIn(initial, boot)
        self.assertIn(applied, boot)
        self.assertLess(boot.index(applied), boot.index("renderBootShell(S.bootRoute)"))

    def test_pipeline_boot_and_poll_use_the_lightweight_local_board_catalog(self):
        boot = WEB_SOURCE.split("async function boot(){", 1)[1].split(
            "let _interventionsRefreshPromise", 1)[0]
        pipeline_sync = WEB_SOURCE.split("async function syncCorePipeline()", 1)[1].split(
            "async function syncInterventions", 1)[0]
        pipeline_open = WEB_SOURCE.split("async function openCorePipeline", 1)[1].split(
            "async function warmTeam", 1)[0]
        self.assertIn('api("/api/core/board-overview")', boot)
        self.assertIn("await refreshCoreBoard()", pipeline_sync)
        self.assertNotIn("await refreshCoreTeam()", pipeline_sync)
        self.assertIn("if(cached){S.corePipeline=cached", pipeline_open)
        self.assertIn("await refreshCoreBoard()", pipeline_open)
        self.assertNotIn("await refreshCoreTeam()", pipeline_open)

    def test_loading_skeletons_share_each_formal_page_shell(self):
        self.assertIn('<div class="app" id="app"></div>', WEB_SOURCE)
        self.assertIn("RunTeamsBoot.render();", WEB_SOURCE)
        self.assertIn("return RunTeamsBoot.pageSkeleton(kind);", WEB_SOURCE)
        self.assertIn("return RunTeamsBoot.railSkeleton();", WEB_SOURCE)
        for shell in (
                "environment-page team-page skeleton-environment-page",
                "environment-cap-grid",
                "environment-page docs-page skeleton-environment-page",
                "environment-page automation-page skeleton-environment-page",
                "trash-page skeleton-trash-page",
                "board skeleton-board",
        ):
            self.assertIn(shell, WEB_SOURCE)
        for route_kind in ("team", "extensions", "docs", "automations", "trash"):
            self.assertIn('kind==="{}"'.format(route_kind), WEB_SOURCE)
        self.assertNotIn("resource-skeleton", WEB_SOURCE)
        self.assertNotIn("resource-skeleton", WEB_STYLES)
        self.assertIn(".skeleton-board .cols{height:auto;align-items:flex-start}", WEB_STYLES)
        self.assertIn(".skeleton-column{height:auto;min-height:0;align-self:flex-start}", WEB_STYLES)
        self.assertIn(".skeleton-column .col-surface{height:auto;max-height:none}", WEB_STYLES)
        self.assertNotIn(".skeleton-board .cols{height:100%}", WEB_STYLES)
        self.assertNotIn(".skeleton-column .col-surface{height:100%;max-height:100%}", WEB_STYLES)

    def test_secondary_loading_surfaces_use_their_formal_layouts(self):
        rail = WEB_SOURCE.split("function railSkeleton(){", 1)[1].split(
            "function render(){", 1)[0]
        self.assertIn('class="rail-content-viewport"', rail)
        self.assertIn('class="rail-scroll-actions">\'+rows(5)', rail)
        self.assertIn('class="railfoot-row"', rail)
        for helper in (
                "remoteSettingsSkeleton",
                "credentialSettingsSkeleton",
                "automationWorkRecordSkeleton",
                "coreEmployeeValidationSkeleton",
                "mobilePreviewSkeleton",
        ):
            self.assertIn("function {}".format(helper), WEB_SOURCE)
        self.assertNotIn("utility-loading-modal", WEB_SOURCE)
        self.assertNotIn("settings-panel-skeleton", WEB_STYLES)
        for stale in (
                "delivery-list-skeleton",
                "workers-standards-loading",
                "detail-skeleton-stack",
                "pset-skeleton-toolbar",
                "worker-editor-skeleton",
                "chat-skeleton",
        ):
            self.assertNotIn(stale, WEB_STYLES)

    def test_resource_detail_updates_preserve_catalog_scroll_position(self):
        self.assertIn('function captureMainWorkspacePosition()', WEB_SOURCE)
        self.assertIn('function restoreMainWorkspacePosition(position)', WEB_SOURCE)
        self.assertIn('mainPosition=sameMainView?captureMainWorkspacePosition():null', WEB_SOURCE)
        self.assertIn('restoreMainWorkspacePosition(mainPosition)', WEB_SOURCE)

    def test_extension_enum_values_are_not_remapped(self):
        for mapper in ("environmentPluginCapabilityLabel", "environmentPluginComponentLabel",
                       "environmentPluginAuthPolicy"):
            self.assertNotIn(mapper, WEB_SOURCE)
        self.assertIn('components.map(value=>`<span>${esc(value)}</span>`)', WEB_SOURCE)
        self.assertIn('capabilities.map(value=>`<span>${esc(value)}</span>`)', WEB_SOURCE)

    def test_copy_guide_defines_voice_and_product_terms(self):
        for phrase in ("清楚：", "简洁：", "冷静：", "可行动：", "尊重：", "任务", "岗位", "员工", "模型渠道", "团队规范", "交付文件"):
            self.assertIn(phrase, COPY_GUIDE)

    def test_core_web_copy_uses_product_language(self):
        for phrase in (
            "正在准备你的工作区",
            "还没有员工",
            "创建可复用的员工，并把他们安排到不同流水线。",
            "执行器就绪",
            "添加能够调用工具、处理文件并交付结果的技能。",
            "可执行技能没有载入",
            "模型渠道没有连接。请先在终端完成登录",
            "附件没有读取成功。请重新选择",
            "新任务",
        ):
            self.assertIn(phrase, WEB_SOURCE)

    def test_agent_failure_states_use_plain_user_facing_language(self):
        for phrase in ("未能完成", "本地服务暂时没有响应。请确认服务正在运行后重试。",
                       "请求未能完成。请稍后重试。", "重试"):
            self.assertIn(phrase, WEB_SOURCE)

    def test_waiting_states_explain_whether_the_user_needs_to_act(self):
        for phrase in ("等待网络恢复", "等待重试", "等待你的回复",
                       "需要处理", "需要连接模型渠道",
                       "重新连接后，可以继续刚才的操作。"):
            self.assertIn(phrase, WEB_SOURCE)
        for phrase in ("任务尚未启动，也不会计入重试。", "等待自动重试"):
            self.assertNotIn(phrase, WEB_SOURCE)

    def test_errors_name_the_result_and_offer_a_next_step(self):
        for phrase in (
            "请填写流水线名称",
            "流水线已更新",
            "请为每个岗位选择员工",
            "任务没有创建",
            "员工列表没有载入。请检查本地服务后再试",
            "反馈没有提交。请检查本地服务后再试",
            "可执行技能没有载入",
            "同步预览没有生成",
            "工作记录没有载入",
        ):
            self.assertIn(phrase, WEB_SOURCE)
        for phrase in (
            "流水线名称不能为空",
            'toast("已重命名"',
            "操作失败，请重试",
            "任务没有移动，请稍后重试",
            "暂时无法读取",
            "暂时无法打开对话",
            "模型渠道连接未完成，请检查终端登录后重试",
            "无法读取附件，请重新选择文件",
            "暂无待批的能力改进",
            "暂时无法读取模板",
            "暂时无法读取员工",
        ):
            self.assertNotIn(phrase, WEB_SOURCE)

    def test_core_workflow_copy_uses_one_clear_state_vocabulary(self):
        self.assertIn('ready:"等待开始"', WEB_SOURCE)
        self.assertIn('running:"正在工作"', WEB_SOURCE)
        self.assertIn('waiting_retry:"等待重试"', WEB_SOURCE)
        self.assertIn('needs_human:"需要处理"', WEB_SOURCE)
        self.assertIn('failed:"运行失败"', WEB_SOURCE)
        self.assertIn('canceled:"已停止"', WEB_SOURCE)
        self.assertIn("回复并继续", WEB_SOURCE)
        self.assertIn("重新运行", WEB_SOURCE)

    def test_core_task_composer_creates_in_place_with_a_title(self):
        self.assertIn('aria-label="创建任务"', WEB_SOURCE)
        self.assertIn('aria-label="任务名称"', WEB_SOURCE)
        self.assertIn('placeholder="新任务"', WEB_SOURCE)
        self.assertIn('payload:{objective:title,parameters:state.parameters||{}}', WEB_SOURCE)
        self.assertIn('coreTaskParameterDeclarations', WEB_SOURCE)
        self.assertIn('api("/api/core/tasks","POST"', WEB_SOURCE)
        self.assertNotIn('className:"core-task-modal"', WEB_SOURCE)

    def test_retired_user_facing_phrases_do_not_return(self):
        for phrase in (
            '"流水线体检"',
            '"操作已完成"',
            '"协议错误"',
            '"运行完成"',
            '"工具与资料仓"',
            '"从本机目录建包"',
            '"写完岗位说明后自动理解"',
            '"已按说明重新理解"',
            '"干完直接推进"',
            '"项目级(每卡)"',
            '"全局(全线共用)"',
            "暂无记录",
            "暂无会话",
            "暂无团队规范",
            "暂无运行记录",
            "暂未检测到可用的模型渠道",
            "官方 CLI",
            "Token 消耗",
            "调用名称",
            "密文快照",
            "快照密钥",
            "跨端加密通道",
            "确定删除这条规范？",
            '"应用失败"',
            '"移动失败"',
            '"附件读取失败"',
            '"模型调用失败"',
            "使用渠道默认配置",
            "个可用模型",
            'active?"运行中":"已就绪"',
            "演练模式",
            "run_mode",
            "toggleRunMode",
            "Agent 正在修复岗位能力",
        ):
            self.assertNotIn(phrase, WEB_SOURCE)


if __name__ == "__main__":
    unittest.main()
