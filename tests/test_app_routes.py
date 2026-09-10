import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from unittest import mock

import app


class AppRouteTests(unittest.TestCase):
    def test_main_workspace_supports_deduplicated_switchable_windows(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('const WORKSPACE_WINDOWS_KEY="runteams_workspace_windows_v1"', source)
        self.assertIn("function workspaceKeyFromRoute(route)", source)
        self.assertIn('if(kind==="core-pipeline")return `pipeline:${value.id}`', source)
        self.assertIn('if(kind==="docs")return value.documentId?`document:${value.documentId}`:"docs:list"', source)
        self.assertIn("function activateWorkspaceWindow(key)", source)
        self.assertIn("function closeWorkspaceWindow(key)", source)
        self.assertIn('role="tablist" aria-label="最近工作窗口"', source)
        self.assertIn('id="rgWorkspaceContent"', source)
        self.assertIn('workspaceCaptureCurrent();workspaceRestoreSnapshot(targetWorkspaceKey)', source)

    def test_chat_stop_freezes_stream_immediately_on_both_surfaces(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        stop_chat = source.split("async function stopChat(){", 1)[1].split(
            "function chatMenu", 1
        )[0]
        stop_panel = source.split("async function stopConversationPanel(){", 1)[1].split(
            "async function openCoreEmployeeConversation", 1
        )[0]

        self.assertIn("function finalizeStoppedAgentMessage(message)", source)
        self.assertIn("function stopLiveAgentMessageImmediately(messages)", source)
        self.assertIn("function restoreOptimisticallyStoppedMessage(snapshot)", source)
        self.assertLess(
            stop_chat.index("stopLiveAgentMessageImmediately(S.chatMsgs)"),
            stop_chat.index("api(`/api/chat/${S.chatId}/cancel`"),
        )
        self.assertLess(
            stop_panel.index("stopLiveAgentMessageImmediately(panel.messages)"),
            stop_panel.index("api(`/api/chat/${panel.id}/cancel`"),
        )
        self.assertIn('if(S.chatStopRequested)return;applyAgentStreamEvent', source)
        self.assertIn('if(panel.stopRequested)return;applyAgentStreamEvent', source)
        self.assertIn("if(cancelled||S.chatStopRequested)", source)
        self.assertIn("if(cancelled||panel.stopRequested)", source)
        self.assertIn("panel.busy&&!panel.stopRequested&&!panel.stopping", source)
        self.assertIn("const stopping=(panelCurrent&&S.conversationPanel?.stopRequested)||(pageCurrent&&S.chatStopRequested)", source)
        self.assertIn("if(!stopping&&(ch?.awaiting_reply", source)
        self.assertIn("panelWorking=S.conversationPanel&&conversationPanelIsVisibleHere()&&S.conversationPanel.busy&&!S.conversationPanel.stopRequested&&!S.conversationPanel.stopping", source)
        self.assertIn("restoreOptimisticallyStoppedMessage(snapshot)", stop_chat)
        self.assertIn("restoreOptimisticallyStoppedMessage(snapshot)", stop_panel)

    def test_chat_summaries_expose_active_reply_state(self):
        summaries = [{"id": 7, "kind": "general", "title": "运行中的对话"},
                     {"id": 8, "kind": "general", "title": "已完成的对话"}]
        with mock.patch.object(app.store, "list_chats", return_value=summaries):
            with app._CHAT_TURN_LOCK:
                previous = dict(app._CHAT_TURN_CANCELS)
                app._CHAT_TURN_CANCELS.clear()
                app._CHAT_TURN_CANCELS[7] = threading.Event()
            try:
                result = app._formal_chat_summaries()
            finally:
                with app._CHAT_TURN_LOCK:
                    app._CHAT_TURN_CANCELS.clear()
                    app._CHAT_TURN_CANCELS.update(previous)

        self.assertTrue(result[0]["awaiting_reply"])
        self.assertFalse(result[1]["awaiting_reply"])

    def test_home_chat_rows_render_waiting_reply_spinner(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("ch?.awaiting_reply", source)
        self.assertIn("正在等待 AI 回复", source)
        self.assertIn('setInterval(syncChats,2000)', source)

    def test_production_import_graph_never_loads_legacy_store_or_workspace_modules(self):
        root = Path(__file__).parents[1]
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; import app; "
             "blocked={'store','workspaces','work_locations'} & set(sys.modules); "
             "raise SystemExit('legacy modules loaded: '+','.join(sorted(blocked)) if blocked else 0)"],
            cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_formal_navigation_binds_core_types_and_explicit_targets(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('if(/^\\d+$/.test(parts[1]))return {kind:"core-pipeline"', source)
        self.assertIn('return {kind:"core-pipeline",id:Number(parts[1])', source)
        self.assertIn('data-core-pipeline-id="${Number(p.id)}"', source)
        self.assertIn('onclick="corePipelineRowClick(event,${Number(p.id)})"', source)
        self.assertIn('function corePipelineRowClick(event,pid)', source)
        self.assertIn('openCorePipeline(pid)', source)
        self.assertIn("onclick=\"toggleCorePipelinePanel('core-pipeline-employees')\" title=\"员工\"", source)
        self.assertNotIn("onclick=\"go(", source)

        self.assertIn('onclick="openCoreEmployeeEditor(${item.id})"', source)
        self.assertIn('fn:()=>openCoreEmployeeConversation(id)', source)
        self.assertIn('target_employee_id:employeeId||null', source)

    def test_documents_support_safe_internal_links_and_new_window_reader(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'if(path==="/docs")return {kind:"docs",documentId:/^\\d+$/.test(query.get("document")||"")?Number(query.get("document")):0,anchor:location.hash?safeRoutePart(location.hash.slice(1)):""};',
            source,
        )
        self.assertIn('function documentInternalLinkId(value)', source)
        self.assertIn('runteams://document/<id>', source)
        self.assertIn('data-runteams-document-id', source)
        self.assertIn('setAppUrl(routeWithRailState(documentInternalLinkHref(doc.id,options.anchor||""),currentRailRouteValue())', source)
        self.assertIn('function documentLinkOpenInNewWindow(event)', source)
        self.assertIn('.doc-reader-content a[href]', source)
        self.assertIn('link.target="_blank";link.rel="noopener noreferrer"', source)
        self.assertIn('window.open(link.href,"_blank","noopener,noreferrer")', source)
        self.assertIn('document.addEventListener("pointerdown",documentLinkPrepareForNewWindow,true)', source)
        self.assertIn('function openDocumentLinkDialog(event)', source)
        self.assertIn('function documentLinkDialogRows(query="")', source)
        self.assertIn('runteams://document/${Number(doc.id)}', source)
        # 插入链接不再占用文档顶栏，统一从光标行左侧的块菜单进入。
        self.assertNotIn('class="doc-reader-link-action"', source)
        self.assertIn('id="i-link"', source)
        self.assertIn('const outlineClass=S.docOutlineCollapsed?" is-outline-collapsed":""', source)
        self.assertIn('layout?.classList.toggle("is-outline-collapsed",!!S.docOutlineCollapsed)', source)
        css = (Path(__file__).parents[1] / "web" / "runteams.css").read_text(
            encoding="utf-8"
        )
        self.assertIn('.doc-reader-prose .ProseMirror a', css)
        self.assertIn('color:var(--link)', css)
        self.assertIn('.doc-reader-prose .milkdown .milkdown-slash-menu{left:0;width:168px', css)
        self.assertIn('[data-runteams-outline-position]{left:var(--runteams-menu-left)!important;top:var(--runteams-menu-top)!important}', css)
        self.assertIn('transform:none}', css)
        self.assertIn('.milkdown-slash-menu .tab-group{display:none}', css)
        self.assertIn('.menu-group ul{display:grid;grid-template-columns:repeat(5', css)
        self.assertIn('gap:1px;padding:0!important;margin:0!important', css)
        self.assertIn('min-height:34px', css)
        self.assertIn('margin:0!important;border-radius:6px', css)
        self.assertIn('li svg{color:var(--runteams-format-icon-color);fill:var(--runteams-format-icon-color)}', css)
        self.assertIn('.milkdown-block-handle .operation-item + .operation-item{display:none}', css)
        editor_source = (Path(__file__).parents[1] / "frontend" / "doc-editor" / "src" / "main.js").read_text(encoding="utf-8")
        self.assertIn('function toEditorMarkdown(value)', editor_source)
        self.assertIn('function fromEditorMarkdown(value)', editor_source)
        # 普通左键必须是导航，不应被 Milkdown 的链接编辑工具条抢走。
        self.assertNotIn('feature/link-tooltip', editor_source)
        self.assertNotIn('.addFeature(linkTooltip)', editor_source)
        self.assertIn('captureSelection:', editor_source)
        self.assertIn('getCapturedSelectionText:', editor_source)
        self.assertIn('insertLink:', editor_source)
        self.assertIn('buildMenu: (builder)', editor_source)
        self.assertIn('label: "链接"', editor_source)
        self.assertIn('label: "复制"', editor_source)
        self.assertIn('label: "删除"', editor_source)
        self.assertIn('function bindBlockMenuHover(root, openMenuAt = null, getBlockLabel = null)', editor_source)
        self.assertIn('syncBlockStyleButton', editor_source)
        self.assertIn('runteamsBlockLabel', editor_source)
        self.assertIn('getBlockLabel = (target)', editor_source)
        self.assertIn('const dispatchPointer = (type)', editor_source)
        self.assertIn('document.createEvent("Event")', editor_source)
        self.assertIn('const scheduleFrame = typeof requestAnimationFrame', editor_source)
        self.assertIn('const cancelFrame = typeof cancelAnimationFrame', editor_source)
        self.assertIn('const syncMenuLeft = (menu, anchor = null)', editor_source)
        self.assertIn('anchorRect.left - editorRect.left', editor_source)
        self.assertIn('const preferredLeft = anchorRect.left - editorRect.left - menuWidth - 8', editor_source)
        self.assertIn('const minLeft = mainRect ? mainRect.left + 8 - editorRect.left', editor_source)
        self.assertIn('activeMenu.dataset.show = "true"', editor_source)
        self.assertIn('Date.now() - startedAt >= 240', editor_source)
        self.assertIn('const positionSyncTimer = setInterval', editor_source)
        self.assertIn('root.addEventListener("mousemove", onPointerMove, true)', editor_source)
        self.assertIn('hoverTimer = setTimeout(() =>', editor_source)
        self.assertIn('}, 0);', editor_source)
        self.assertIn('const onAddPointerUp = (event)', editor_source)
        self.assertIn('ctx.get("menuAPICtx").show(', editor_source)
        self.assertIn('root.addEventListener("pointerleave", onPointerLeave, true)', editor_source)
        self.assertIn('const hideMenu = (menu)', editor_source)
        self.assertIn('menu.style.setProperty("visibility", "hidden", "important")', editor_source)
        self.assertIn('const revealMenu = (menu)', editor_source)
        self.assertIn('.milkdown-slash-menu.is-repositioning{visibility:hidden!important;pointer-events:none}', css)

    def test_formal_context_uses_core_pipeline_workflow_and_package_objects(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        page_context = source.split("function currentPageContext(){", 1)[1].split(
            "function currentConversationWorkspaceKey", 1
        )[0]

        self.assertIn('S.sel?.type==="core-workflow"', page_context)
        self.assertIn('surface:"workflow"', page_context)
        self.assertIn('workflow_id:Number(S.sel.id)', page_context)
        self.assertIn('surface:"pipeline"', page_context)
        self.assertNotIn('surface:"card"', page_context)
        self.assertNotIn('surface:"node"', page_context)

        self.assertIn('if(parts[0]==="skills")', source)
        self.assertIn('kind:"package",channel_id:"core",id:Number(parts[1])', source)
        self.assertIn(
            "onclick=\"openEnvironmentDetail('package','core',${Number(item.id)})\"",
            source,
        )

    def test_formal_frontend_has_no_retired_worker_card_node_run_runtime(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        for endpoint in (
            "/api/workers",
            "/api/worker/",
            "/api/cards",
            "/api/card/",
            "/api/node/",
            "/api/outcome/",
            "/api/pipeline/",
            "/api/pipelines",
            "/api/run/",
        ):
            self.assertNotIn(endpoint, source)
        for function_name in (
            "openCard",
            "openNode",
            "pickPipeline",
            "runCard",
            "openColumnGroupEditor",
        ):
            self.assertNotIn(f"function {function_name}(", source)
        for state_ref in ("S.pid", "S.pl", "S.pipelines", "S.skills"):
            self.assertNotIn(state_ref, source)

    def test_extensions_load_only_core_packages_and_environment_snapshot(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        open_environment = source.split("async function openEnvironment(options={}){", 1)[
            1
        ].split("function syncChannelsFromEnvironment", 1)[0]

        self.assertIn('api("/api/core/packages")', open_environment)
        self.assertIn("warmEnvironment(false,true)", open_environment)
        self.assertNotIn('api("/api/skills")', open_environment)
        self.assertNotIn("S.skills", open_environment)

    def test_channel_assets_are_not_employee_package_bindings(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        picker = source.split("function coreEmployeeCapabilityCatalog(){", 1)[1].split(
            "function toggleCoreEmployeeCapability", 1
        )[0]
        extensions = source.split("function environmentCapabilities(env){", 1)[1].split(
            "async function refreshCorePackages", 1
        )[0]
        catalog = source.split("function environmentPluginIdentity(item){", 1)[1].split(
            "function isEnvironmentDetail", 1
        )[0]
        plugin_rows = source.split("function environmentPluginRows(items){", 1)[1].split(
            "function corePackageLabel", 1
        )[0]

        self.assertIn("S.corePackages", picker)
        self.assertNotIn("S.environment", picker)
        self.assertNotIn("available_plugins", picker)
        self.assertIn("environmentExtensionRows", extensions)
        self.assertIn("environmentExtensionViewItems", extensions)
        self.assertIn("env.available_plugins", catalog)
        self.assertIn("env.plugins", catalog)
        self.assertIn("S.corePackages", catalog)
        self.assertIn("installed:true", catalog)
        self.assertNotIn("function employeeSkillsPage", source)
        self.assertIn("item?.channel_id", catalog)
        self.assertIn("providerBrandIcon", plugin_rows)
        self.assertNotIn("environment-channel-pill", plugin_rows)
        self.assertIn("environment-plugin-installed-state", plugin_rows)
        self.assertNotIn("environment-plugin-remove", plugin_rows)
        self.assertNotIn(">发现<", extensions)
        self.assertNotIn(">能力包<", extensions)
        self.assertNotIn("openCorePackageImport", extensions)
        self.assertNotIn("导入能力包", extensions)
        self.assertIn('label:"全部"', source)
        self.assertIn("已安装", extensions)
        self.assertIn("environment-extension-header", extensions)
        self.assertIn("environment-extension-title-row", extensions)
        self.assertNotIn("environment-extension-channels", extensions)
        self.assertNotIn("environment-catalog-toolbar", extensions)
        self.assertIn(">卸载</button>", source)

    def test_employee_cards_show_actionable_state_without_release_versions(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        state = source.split("function coreEmployeeCardState(item){", 1)[1].split(
            "async function openFailureStats", 1
        )[0]
        cards = source.split("function coreTeamMain(){", 1)[1].split(
            "function corePipelineMenu", 1
        )[0]

        self.assertIn('label:"缺少凭据"', state)
        self.assertIn('label:"能力可升级"', state)
        self.assertIn('label:"未发布"', state)
        self.assertIn('label:"待发布"', state)
        self.assertIn("return null", state)
        self.assertIn("stateBadge=state?", cards)
        self.assertNotIn("release.version", cards)
        self.assertNotIn("releaseLabel", cards)

    def test_employee_editor_shows_release_facts_and_draft_changes(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        styles = (Path(__file__).parents[1] / "web" / "runteams.css").read_text(
            encoding="utf-8"
        )
        release_badge = source.split("function coreEmployeeReleaseBadge(item){", 1)[
            1
        ].split("function syncCoreEmployeeGoalSummary", 1)[0]
        editor = source.split("function openCoreEmployeeEditor(id){", 1)[1].split(
            "async function saveCoreEmployee", 1
        )[0]

        self.assertIn("有待发布修改", release_badge)
        self.assertIn("尚未发布", release_badge)
        self.assertIn("缺少凭据", release_badge)
        self.assertIn("能力可升级", release_badge)
        self.assertIn("发布前需要补充凭据", release_badge)
        self.assertIn("正在运行的工作不受影响", release_badge)
        self.assertIn('data-tooltip="${esc(description)}"', release_badge)
        self.assertIn('tabindex="0"', release_badge)
        self.assertNotIn("digest", release_badge)
        self.assertNotIn("package_key", release_badge)
        self.assertNotIn("coreEmployeeReleaseStatus", source)
        self.assertIn("function coreEmployeePackageUpgrades(item)", source)
        self.assertIn("能力可升级", source)
        self.assertIn("coreEmployeePublishButton(id)", editor)
        header = editor.split("headerHtml:", 1)[1].split("headerClass:", 1)[0]
        footer = editor.split("footer:", 1)[1].split("footerClass:", 1)[0]
        self.assertIn("coreEmployeeReleaseBadge(item)", header)
        self.assertIn("coreEmployeeValidationBadge(item)", header)
        self.assertLess(
            header.index("coreEmployeeReleaseBadge(item)"),
            header.index("coreEmployeeValidationBadge(item)"),
        )
        self.assertIn('id:"worker_avatar",editor:true', header)
        self.assertNotIn("coreEmployeePublishButton(id)", header)
        self.assertIn("coreEmployeePublishButton(id)", footer)
        self.assertNotIn("coreEmployeeValidationBadge(item)", footer)
        self.assertIn("core-employee-publish-cluster", footer)
        self.assertLess(footer.index("保存草稿"), footer.index("coreEmployeePublishButton(id)"))
        self.assertIn("function coreEmployeeValidationBadge(item)", source)
        self.assertIn('title="测试用例验证通过"', source)
        self.assertIn("function markCoreEmployeeValidationStale", source)
        self.assertIn("function openWorkerAvatarPicker(event)", source)
        self.assertIn("function discardPendingCoreEmployeeAvatar()", source)
        self.assertIn('{name,avatar,draft}', source)
        self.assertIn('document.getElementById("core_employee_validation_badge")?.remove()', source)
        self.assertIn("worker-editor-meta", editor)
        self.assertIn('employeeGoal=coreEmployeeGoal(item||{draft_json:draft})', editor)
        self.assertIn('id="core_employee_goal_summary"', header)
        self.assertNotIn("当前发布 v", header)
        self.assertIn('oninput="syncCoreEmployeeGoalSummary(this.value);coreEmployeeTextareaInput(this)"', editor)
        self.assertIn('oninput="coreEmployeeTextareaInput(this)"', editor)
        self.assertEqual(editor.count("data-core-employee-autosize"), 5)
        self.assertIn("requestAnimationFrame(()=>initCoreEmployeeTextareas(dialog))", editor)
        self.assertIn("function sizeCoreEmployeeTextarea(field", source)
        self.assertIn('field.dataset.employeeManualSize==="1"', source)
        self.assertIn("function initCoreEmployeeTextareas(root)", source)
        self.assertIn("function coreEmployeeTextareaInput(field)", source)
        self.assertNotIn("发布时固定当前能力包版本", editor)
        self.assertIn("core-employee-capability-sections", editor)
        capability_picker = source.split("function coreEmployeeCapabilityOptions(){", 1)[1].split(
            "function renderCoreEmployeeCapabilities", 1
        )[0]
        capability_menu = source.split("function coreEmployeeCapabilityMenuItems(){", 1)[1].split(
            "function toggleCoreEmployeeCapability", 1
        )[0]
        skill_picker = source.split("function filterSkillPickerMenu(value){", 1)[1].split(
            "function openNestedMenu", 1
        )[0]
        self.assertIn("core-employee-capability-section", capability_picker)
        self.assertIn('<span>可执行技能</span>', capability_picker)
        self.assertIn("core-employee-selected-capabilities", capability_picker)
        self.assertIn("core-employee-capability-tag", capability_picker)
        self.assertIn('aria-haspopup="menu"', capability_picker)
        self.assertIn("openCoreEmployeeCapabilityMenu(event)", capability_picker)
        self.assertIn("openSkillPickerMenu", capability_menu)
        self.assertIn('placeholder="搜索可执行技能"', skill_picker)
        self.assertIn("filterSkillPickerMenu", skill_picker)
        self.assertIn('variant:"skillPicker"', skill_picker)
        responsibility = editor.split("worker-responsibility-section", 1)[1].split(
            "</section>", 1
        )[0]
        self.assertNotIn("detail-head-ai", responsibility)
        self.assertIn("core-employee-ai-adjust", footer)
        self.assertNotIn("core-employee-system-instruction", footer)
        self.assertIn("coreEmployeeSystemInstructionSection(item,id)", editor)
        self.assertIn('class="worker-section core-employee-system-section"', source)
        self.assertIn('ontoggle="loadCoreEmployeeSystemInstruction(this,${Number(id)})"', source)
        self.assertIn("function loadCoreEmployeeSystemInstruction", source)
        self.assertIn("function coreEmployeeSystemInstructionMarkup", source)
        self.assertNotIn("core-system-instruction-modal", source)
        self.assertNotIn("openCoreEmployeeSystemInstruction", source)
        self.assertNotIn("openCorePositionSystemInstruction", source)
        self.assertNotIn("固定工作程序", editor)
        self.assertNotIn("技能与工具", editor)
        self.assertNotIn("每行一步", editor)
        self.assertNotIn("每行一条", editor)
        self.assertNotIn("<span>决定这名员工会怎样完成专业工作</span>", capability_picker)
        self.assertNotIn("<span>由当前模型渠道提供</span>", capability_picker)
        for heading in ("岗位职责", "工作目标", "有序步骤", "验收标准", "交付文档"):
            self.assertIn(f'<div class="worker-section-head"><span>{heading}</span></div>', editor)
        self.assertIn('aria-label="搜索可执行技能"', skill_picker)
        self.assertNotIn("<b>员工技能</b>", capability_picker)
        self.assertNotIn("<b>工作工具</b>", capability_picker)
        self.assertIn("packages.filter(item=>!item.on)", capability_menu)
        self.assertIn("native.filter(item=>!item.on&&item.compatible)", capability_menu)
        self.assertIn('iconBox:"users"', capability_menu)
        self.assertIn('class="menu-icon menu-vector-icon"', source)
        self.assertNotIn("employee-skill-grid", capability_picker)
        self.assertNotIn("employee-tool-grid", capability_picker)
        self.assertNotIn("渠道扩展", capability_picker)
        self.assertNotIn("core-capability-glyph", capability_picker)
        self.assertNotIn("core-capability-toggle", capability_picker)
        self.assertNotIn("packageItem.version", capability_picker)
        self.assertNotIn("core-employee-validation-entry", editor)
        self.assertNotIn("openCoreEmployeeValidation", editor)
        self.assertIn('aria-label="关闭" title="关闭" onclick="closeModal()"', editor)
        self.assertNotIn('>取消</button>', editor)
        self.assertNotIn(".core-employee-validation-entry", styles)
        self.assertIn(".core-employee-title-row", styles)
        self.assertIn(".core-employee-release-badge", styles)
        self.assertIn(".core-employee-release-badge::after", styles)
        self.assertIn("content:attr(data-tooltip)", styles)
        self.assertIn(".core-employee-validation-badge", styles)
        self.assertIn(".core-employee-publish-cluster", styles)
        self.assertIn(".core-employee-publish-button", styles)
        self.assertNotIn(".core-employee-publish-copy", styles)
        self.assertIn(".core-employee-capability-tag{", styles)
        self.assertIn(".capability-menu-surface{", styles)
        self.assertIn(".skill-picker-search{", styles)
        self.assertIn("flex:0 0 29px", styles)
        self.assertIn(".capability-menu-surface .menu-vector-icon{", styles)
        self.assertNotIn(".employee-capability-menu{", styles)
        self.assertNotIn(".employee-capability-search{", styles)
        self.assertNotIn(".core-employee-capability-picker{", styles)
        self.assertNotIn(".core-employee-capability-choice{", styles)
        self.assertNotIn(".core-capability-toggle", styles)
        self.assertIn(".core-employee-editor .worker-responsibility-section{padding-bottom:10px}", styles)
        self.assertIn(".worker-editor-unified .core-employee-program-section,.worker-editor-unified .core-employee-capability-section{padding:4px 0 10px}", styles)
        self.assertIn(".core-employee-release-badge.unpublished", styles)
        self.assertIn(".core-employee-release-badge.blocked", styles)
        self.assertNotIn(".core-employee-release-notice", styles)
        self.assertIn("textarea[data-core-employee-autosize]", styles)
        self.assertIn("max-height:min(520px,55vh)", styles)
        self.assertIn(
            ".core-employee-editor .jd-input,.core-employee-editor .jd-input:hover",
            styles,
        )
        self.assertIn(
            ".core-employee-editor .core-employee-field textarea:focus",
            styles,
        )
        self.assertIn(".core-employee-editor .worker-title-input:focus", styles)

    def test_employee_asset_lifecycle_actions_remain_available(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        menu = source.split("function coreEmployeeRowMenu", 1)[1].split(
            "function coreLines", 1
        )[0]

        self.assertIn("复制员工", menu)
        self.assertIn("放弃未发布修改", menu)
        self.assertIn("移到垃圾箱", menu)
        self.assertIn("duplicateCoreEmployee", menu)
        self.assertIn("discardCoreEmployeeDraft", menu)
        self.assertIn("trashCoreEmployee", menu)
        self.assertIn("/api/core/employees/${id}/restore", source)
        self.assertIn("/api/core/employees/${id}/delete", source)
        self.assertIn('kind==="employee"', source)

    def test_core_pipeline_sidebar_order_is_a_local_ui_preference(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('const RAIL_PIPELINE_ORDER_KEY=', source)
        self.assertIn("railPipelineOrder:loadRailPipelineOrder()", source)
        self.assertIn('draggable="true" data-core-pipeline-id=', source)
        self.assertIn("ondragstart=\"corePipelineDragStart", source)
        self.assertIn("function corePipelineDrop(event,targetId)", source)
        self.assertIn("saveRailPipelineOrder()", source)
        self.assertNotIn('/api/pipelines/reorder', source)

    def test_verified_package_without_legacy_runner_does_not_claim_unverified(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        drawer = source.split("function environmentPackageDetailModel(item){", 1)[1].split(
            "function environmentPackageDrawer", 1
        )[0]

        self.assertIn('runner=verification.runner||""', drawer)
        self.assertIn('RunTeams 内置 Python', drawer)
        self.assertIn('["验证环境",runnerLabel]', drawer)
        self.assertNotIn("历史记录未包含", drawer)

    def test_package_detail_prioritizes_capabilities_and_readiness(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        drawer = source.split("function environmentPackageDetailModel(item){", 1)[1].split(
            "function environmentPackageDrawer", 1
        )[0]
        shared = source.split("function environmentExtensionDrawer(model,title=", 1)[1].split(
            "function environmentPluginDetailModel", 1
        )[0]
        plugin_adapter = source.split("function environmentPluginDrawer(item,channel){", 1)[1].split(
            "function corePackageCapabilityMeta", 1
        )[0]
        package_adapter = source.split("function environmentPackageDrawer(item){", 1)[1].split(
            "function environmentDetailDrawer", 1
        )[0]

        self.assertIn("这项技能如何工作", drawer)
        self.assertIn("可执行技能详情", shared)
        self.assertNotIn("能力包详情", drawer)
        self.assertIn("员工把它作为一项完整技能使用", drawer)
        self.assertIn("coreCapabilityPurpose", drawer)
        self.assertIn("可正常使用", drawer)
        self.assertIn("失败详情", drawer)
        self.assertIn('failed&&failedChecks.length', drawer)
        self.assertNotIn("查看验证详情", drawer)
        self.assertIn("技术信息", drawer)
        self.assertIn('core-package-technical-section', drawer)
        self.assertIn('environmentExtensionFacts', drawer)
        self.assertIn('environmentExtensionDrawer(environmentPluginDetailModel', plugin_adapter)
        self.assertIn('environmentExtensionDrawer(environmentPackageDetailModel', package_adapter)
        self.assertNotIn("版本事实", drawer)
        self.assertNotIn("item.digest", drawer)
        self.assertNotIn("不可变版本", drawer)

    def test_package_catalog_matches_two_column_channel_density(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        rows = source.split("function corePackageRows(items){", 1)[1].split(
            "function environmentPluginDrawer", 1
        )[0]

        self.assertIn('environment-cap-row core-package-row', rows)
        self.assertIn('environment-cap-grid', source)
        self.assertIn("ready?'可用':'待验证'", rows)
        self.assertIn("environment-extension-state core-package-row-state", rows)
        self.assertIn('ready?ICON("check")', rows)
        self.assertNotIn("项技能", rows)
        self.assertNotIn("个工具", rows)
        self.assertNotIn('core-package-card-meta', rows)
        self.assertNotIn('environment-channel-pill">能力包', rows)

    def test_package_semantics_are_reused_in_employee_capability_picker(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        picker = source.split("function coreEmployeeCapabilityCatalog(){", 1)[1].split(
            "function toggleCoreEmployeeCapability", 1
        )[0]

        self.assertIn("corePackageLabel", picker)
        self.assertNotIn("coreCapabilityPurpose", picker)
        self.assertIn("可执行技能", picker)
        self.assertIn("coreEmployeeCapabilityMenuItems", picker)

    def test_package_detail_has_read_only_immutable_resource_browser(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        drawer = source.split("function environmentPackageDetailModel(item){", 1)[1].split(
            "function environmentPackageDrawer", 1
        )[0]

        self.assertIn("corePackageResourceButton(item)", drawer)
        self.assertIn("async function openCorePackageResources(packageId)", source)
        resource_dialog = source.split(
            "async function openCorePackageResources(packageId)", 1
        )[1].split("function dockedEnvironmentDetailDrawer", 1)[0]
        self.assertIn('className:"core-package-resources-modal"', source)
        self.assertIn("openChildDialog", source)
        self.assertIn("打开资源", source)
        self.assertIn("function corePackageResourcePayload(item)", source)
        self.assertIn("data-extension-resource-viewer", source)
        self.assertIn("RunTeamsResourceViewer.mount", source)
        self.assertIn("RunTeamsResourceViewer.unmount", source)
        self.assertNotIn("footer:", resource_dialog)
        self.assertNotIn(">完成<", resource_dialog)
        self.assertIn('title:`${corePackageLabel(manifest,item.key)} 资源`', resource_dialog)
        self.assertNotIn("个文件", resource_dialog)
        self.assertNotIn("subtitle:", resource_dialog)
        self.assertNotIn("只读版本", resource_dialog)
        self.assertIn('/vendor/resource-viewer.js?v=', source)
        self.assertIn('/vendor/resource-viewer.css?v=', source)
        self.assertIn("/api/core/packages/${id}/file?path=", source)
        self.assertNotIn("function corePackageMarkdownPreview", source)
        self.assertNotIn("function corePackageSourceLines", source)

        viewer = (
            Path(__file__).parents[1]
            / "frontend"
            / "resource-viewer"
            / "src"
            / "main.jsx"
        ).read_text(encoding="utf-8")
        self.assertIn("SandpackFileExplorer", viewer)
        self.assertIn("SandpackCodeEditor", viewer)
        self.assertIn("EditorState.readOnly.of(true)", viewer)
        self.assertIn("EditorView.editable.of(false)", viewer)
        self.assertIn("showLineNumbers", viewer)
        self.assertIn("showRunButton={false}", viewer)
        self.assertIn("@codemirror/lang-python", viewer)
        self.assertIn("function markdownBody(source)", viewer)
        self.assertIn("window.marked.parse(markdownBody(source))", viewer)
        self.assertIn("function folderPaths(paths)", viewer)

    def test_installed_extensions_share_the_lazy_resource_browser(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        plugin_drawer = source.split("function environmentPluginDetailModel(item,channel){", 1)[1].split(
            "function environmentPluginDrawer", 1
        )[0]
        self.assertIn('if(installed&&item.has_resources!==false)sections.push(environmentExtensionSection("资源"', plugin_drawer)
        self.assertIn("installedPluginResourceButton(item)", plugin_drawer)
        self.assertIn("async function openInstalledPluginResources", source)
        self.assertIn("/api/environment/plugin-resources?channel_id=", source)
        self.assertIn("/api/environment/plugin-resource/${encodeURIComponent(token)}?path=", source)
        self.assertIn("loaded:false", source)
        self.assertIn("data-extension-resource-viewer", source)

        viewer = (Path(__file__).parents[1] / "frontend" / "resource-viewer" / "src" / "main.jsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("function ResourcePane({ loadFile, initialLoaded })", viewer)
        self.assertIn("sandpack.updateFile(activeFile", viewer)
        self.assertIn("initialCollapsedFolder={folderPaths(paths)}", viewer)
        self.assertIn("function ImagePreview({ source, path, scale })", viewer)
        self.assertIn('aria-label="图片显示方式"', viewer)
        self.assertIn('imageScale === "fit"', viewer)
        self.assertIn('imageScale === "actual"', viewer)
        self.assertIn('file.kind==="image"', source)
        self.assertNotIn("SHA-256", viewer)
        self.assertNotIn('className="rt-resource-header"', viewer)

    def test_first_employee_creation_uses_employee_designer_for_complete_draft(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        team = source.split("function coreTeamMain(){", 1)[1].split(
            "function corePipelineMenu", 1
        )[0]
        pipeline_picker = source.split("function corePipelineAddPositionTile(){", 1)[1].split(
            "function corePipelineBoard", 1
        )[0]
        pipeline_editor = source.split("function openCorePipelineEditor(id=0){", 1)[1].split(
            "function renderCorePipelineEditor", 1
        )[0]

        self.assertIn('onclick="openCoreEmployeeConversation(0)"', team)
        self.assertNotIn('onclick="openCoreEmployeeEditor(0)"', team)
        self.assertIn('onclick="openCoreEmployeeConversation(0)"', source)
        self.assertIn('const draft=!Number(id)&&isCorePipelineDraft()', pipeline_editor)
        self.assertIn('_corePipelineEditor={id:draft?0:Number(id),draft,name:item.name||"",positions}', pipeline_editor)
        self.assertNotIn('openCoreEmployeeConversation(0)', pipeline_editor)
        self.assertIn('onclick="createCoreEmployeeFromPipeline(event)"', pipeline_picker)
        self.assertNotIn('return openCoreEmployeeEditor(0)', pipeline_editor)
        self.assertIn("与 AI 调整", source)

    def test_new_pipeline_uses_a_blank_page_instead_of_a_creation_dialog(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")

        self.assertIn('if(parts[1]==="new")return {kind:"core-pipeline-new"};', source)
        self.assertNotIn('kind:"core-pipeline-new",canonical:"/team"', source)
        route = source.split('if(route.kind==="core-pipeline-new"){', 1)[1].split(
            'if(route.kind==="team")', 1
        )[0]
        self.assertIn('beginCorePipelineDraft({route:false})', route)
        self.assertNotIn('openTeam({route:false})', route)
        self.assertNotIn('openCorePipelineEditor(0)', route)
        create = source.split('function beginCorePipelineDraft(options={}){', 1)[1].split(
            'function corePipelineWorkflows', 1
        )[0]
        self.assertIn('S.surface="core-pipeline"', create)
        self.assertIn('S.corePipeline=corePipelineDraftGraph(name)', create)
        self.assertIn('setAppUrl(routeWithRailState("/pipelines/new"),!!options.replace)', create)
        self.assertNotIn('closeConversationPanelForRoute', create)
        board = source.split('function corePipelineBoard(){', 1)[1].split(
            'function corePipelineTitleButton', 1
        )[0]
        header = source.split('function corePipelineHeaderButtons(item,draft){', 1)[1].split(
            'function corePipelineHead', 1
        )[0]
        self.assertIn('${corePipelineAddPositionTile()}', board)
        board_columns = source.split('function corePipelineBoardColumns(){', 1)[1].split(
            'function corePipelineColumnName', 1
        )[0]
        self.assertIn('...states.filter(state=>state.kind==="pool").map(stateColumn)', board_columns)
        self.assertIn('...states.filter(state=>state.kind!=="pool").map(stateColumn)', board_columns)
        self.assertIn('...(!draft&&!hasDone?[{key:"__completed"', board_columns)
        self.assertIn('orderedCoreBoardColumns(corePipelineBoardColumns(),grouped', board)
        self.assertIn('column.type==="position"||column.kind==="done"', board)
        self.assertIn('`<button class="addcard core-add-task"', board)
        self.assertIn('openCoreTaskComposer(\'${esc(column.key)}\')', board)
        self.assertIn('composing?coreInlineTaskComposer()', board)
        self.assertNotIn('column.type==="position"&&index===0', board)
        self.assertIn('class="chd column-drag-zone k-${column.kind}"', board)
        self.assertIn('onpointerdown="coreBoardColumnPointerDown(event,', board)
        self.assertIn('title="拖动调整列的显示顺序"', board)
        self.assertIn('onclick="corePipelineColumnClick(event,', board)
        self.assertIn('class="column-worker-title"', board)
        self.assertIn('editCorePipelineEmployeeTitle(event,${Number(employee.id)})', board)
        self.assertIn('${esc(employee.name||column.name)}', board)
        self.assertNotIn('corePipelinePositionDownstream(position)', board)
        self.assertNotIn('class="bo-toggle core-position-route"', board)
        self.assertNotIn('openCorePipelinePositionRoute', board)
        self.assertIn('corePipelinePositionMenu(event,', board)
        self.assertIn('class="column-more"', board)
        self.assertIn('column-color-${corePipelineColumnTone(column)}', board)
        self.assertIn('function corePipelineColumnColorItems(column,columnType,key)', source)
        self.assertIn('{head:true,label:"颜色"}', source)
        self.assertIn('swatch:item.value||"default"', source)
        self.assertIn('updateCorePipelineColumnColor(columnType,key,item.value)', source)
        self.assertIn('{label:isCorePipelineDraft()?"移除岗位":"移到垃圾箱",icon:"trash",fn:()=>trashCorePipelinePosition(key)}', source)
        self.assertIn('...corePipelineColumnColorItems(position,"position",key)', source)
        self.assertIn('...corePipelineColumnColorItems(state,"state",key)', source)
        self.assertIn('function trashCorePipelinePosition(key)', source)
        self.assertIn('`/api/core/pipelines/${Number(S.corePipeline.id)}/positions/trash`', source)
        self.assertIn('positionColumn=position=>({...position,employee:corePositionEmployee(position)', source)
        self.assertIn('column-swatch-${esc(corePipelineColumnColor(item)||corePipelineColumnDefaultColor(item))}', source)
        self.assertIn('column-swatch-${esc(color)}', source)
        self.assertIn('function editCorePipelineEmployeeTitle(event,employeeId)', source)
        self.assertIn('function saveCorePipelineEmployeeTitle(input,employeeId)', source)
        self.assertIn('function updateCorePipelineEmployeeName(employeeId,name)', source)
        self.assertIn('function renameCorePipelineEmployee(employeeId,key)', source)
        self.assertIn('function refreshCorePipelineBoardMarkup()', source)
        self.assertIn('draft:employee.draft_json', source)
        self.assertIn('.column-worker-title-input{width:100%;min-width:0;height:22px;padding:0;', styles)
        self.assertIn('appearance:none;background:transparent;color:var(--ink);font-family:var(--sans);font-size:14px;font-weight:600;line-height:22px;letter-spacing:-.01em;box-shadow:none', styles)
        self.assertNotIn('新任务', header)
        self.assertNotIn('.core-add-task{', styles)
        self.assertIn('.col.column-color-purple{--column-accent:#9481bd;', styles)
        self.assertIn('.card:hover,.card.menu-trigger-active{background:var(--column-hover-bg);border-color:var(--column-hover-border)}', styles)
        self.assertIn('.card.sel{background:var(--column-hover-bg);border-color:var(--column-hover-border)}', styles)
        self.assertIn('function coreBoardColumnPointerMove(event)', source)
        self.assertIn('function previewCoreBoardColumnReorder(target,clientX)', source)
        self.assertIn('function mergeCoreBoardVisibleColumnOrder(visibleKeys)', source)
        self.assertIn('saveCoreBoardGroupPrefs(S.corePipeline?.id,{sort:"manual"})', source)
        self.assertIn('.cols.column-reorder-active{cursor:grabbing;user-select:none}', styles)
        self.assertIn('.column-drag-ghost{position:fixed;', styles)
        self.assertIn('body.column-pointer-dragging .core-workflow-card{pointer-events:none}', styles)
        self.assertIn('ghost.style.backgroundColor=surfaceStyle.backgroundColor', source)
        self.assertNotIn('.column-drag-ghost{position:fixed;z-index:9999;display:flex;flex-direction:column;max-height:360px;overflow:hidden;padding:8px 8px 6px;border:1px solid var(--line);', styles)
        core_card = source.split('function coreWorkflowCard(workflow){', 1)[1].split(
            'const CORE_PIPELINE_STATE_PRESETS', 1
        )[0]
        self.assertIn('function coreWorkflowCurrentRuns(workflow)', source)
        self.assertIn('const runs=coreWorkflowCurrentRuns(workflow)', source)
        self.assertIn("title-only", core_card)
        self.assertIn("isnew", core_card)
        self.assertIn('st card-status run', core_card)
        self.assertIn('<div class="ex">', core_card)
        self.assertIn('draggable="${canDrag}"', core_card)
        self.assertIn('onclick="coreWorkflowCardClick(event,${Number(workflow.id)})"', core_card)
        self.assertIn('ondragstart="coreWorkflowDragStart(event,${Number(workflow.id)})"', core_card)
        self.assertIn('ondragend="coreWorkflowDragEnd()"', core_card)
        self.assertIn('function coreWorkflowDragOver(event,columnKey)', core_card)
        self.assertIn('function coreWorkflowDrop(event,columnKey)', core_card)
        self.assertIn('function showCoreWorkflowDropPreview(column,columnKey)', core_card)
        self.assertIn('source:event.currentTarget,preview:null,previewColumnKey:""', core_card)
        self.assertIn('preview=drag.source.cloneNode(true)', core_card)
        self.assertIn('lane.insertBefore(drag.preview,add)', core_card)
        self.assertIn('function clearCoreWorkflowDropPreview()', core_card)
        self.assertIn('function optimisticCoreWorkflowMove(id,columnKey)', core_card)
        self.assertIn('function moveCoreWorkflow(id,columnKey,options={})', core_card)
        self.assertIn('Date.now()+250', core_card)
        self.assertIn('replaceCoreWorkflowLocal(original)', core_card)
        self.assertIn('oncontextmenu="coreWorkflowMenu(event,${Number(workflow.id)})"', core_card)
        self.assertIn('function coreWorkflowMenu(event,id)', source)
        self.assertIn('{label:"编辑",icon:"edit",fn:()=>openCoreWorkflowTaskEditor(id)}', source)
        self.assertIn('className:"task-draft-modal core-task-edit-modal"', source)
        self.assertIn('id="core_task_edit_title"', source)
        self.assertIn('id="core_task_edit_objective"', source)
        self.assertIn('/api/core/workflows/${Number(id)}/update', source)
        self.assertIn('.core-task-edit-note{margin:0;', styles)
        self.assertIn('{label:"移动到…",icon:"shuffle",submenu:true,keepOpen:true,hoverFn:item=>coreWorkflowMoveTargetMenu(item,id),fn:item=>coreWorkflowMoveTargetMenu(item,id)}', source)
        self.assertIn('if(_coreWorkflowMoveMenu&&_coreWorkflowMoveAnchor?.closest("#popmenu")===m&&_coreWorkflowMoveAnchor!==a)closeCoreWorkflowMoveMenu()', source)
        self.assertIn('await moveCoreWorkflow(id,item.key,{optimistic:true})', source)
        self.assertIn('{label:"移到垃圾箱",icon:"trash",danger:true,fn:()=>trashCoreWorkflow(id)}', source)
        self.assertIn('title=workflow?.task?.title||workflow?.snapshot_json?.task?.title||"这项任务"', source)
        self.assertNotIn('label:"查看详情"', core_card)
        self.assertNotIn('label:"查看并处理"', core_card)
        self.assertNotIn('label:"删除任务"', core_card)
        self.assertIn('aria-label="任务的更多操作"', source)
        self.assertIn("ondragover=\"coreWorkflowDragOver(event,'${esc(column.key)}')\"", source)
        self.assertIn('ondragleave="coreWorkflowDragLeave(event)"', source)
        self.assertIn("ondrop=\"coreWorkflowDrop(event,'${esc(column.key)}')\"", source)
        self.assertIn('.col.drop-target .col-surface{', styles)
        self.assertIn('.card[draggable="true"]{cursor:grab}', styles)
        self.assertIn('.card.dragging{opacity:.34;', styles)
        self.assertIn('.card.core-workflow-drag-preview{opacity:.76;', styles)
        self.assertIn('.board.card-drag-active .lane{min-height:76px}', styles)
        self.assertNotIn('core-workflow-state', core_card)
        column_drawer = source.split('function corePipelineColumnDrawer(){', 1)[1].split(
            'function corePipelineEmployeesDrawer', 1
        )[0]
        self.assertIn('className:"node-detail-drawer core-position-detail-drawer"', column_drawer)
        self.assertIn('class="node-detail-heading"', column_drawer)
        self.assertIn('class="node-header-runtime"', column_drawer)
        self.assertIn('class="node-worker-section"', column_drawer)
        self.assertIn('class="node-contract"', column_drawer)
        self.assertIn('class="node-route-section"', column_drawer)
        self.assertIn('displayName=String(employee?.name||position.name||`第 ${index+1} 岗`)', column_drawer)
        self.assertIn('onclick="${renameAction}">${esc(displayName)}</div>', column_drawer)
        self.assertNotIn('node-assignee-sub', column_drawer)
        self.assertNotIn('由 ${esc(assigneeName)} 执行', column_drawer)
        self.assertIn('<b>工作下游</b>', column_drawer)
        self.assertIn('<span class="bo-label">完成后</span>', column_drawer)
        self.assertIn('<button class="csel"', column_drawer)
        self.assertIn('<span class="cv"><b class="column-group-name column-swatch-${esc(corePipelineColumnTone(target))}">${esc(target.name)}</b></span>', column_drawer)
        self.assertNotIn('column-color-${corePipelineColumnTone(position)}', column_drawer)
        self.assertNotIn('core-node-route-value', column_drawer)
        self.assertIn('openCorePipelinePositionRouteMenu(event,', column_drawer)
        route_menu = source.split('function openCorePipelinePositionRouteMenu(event,key,when=""){', 1)[1].split(
            'async function setCorePipelinePositionDownstream', 1
        )[0]
        self.assertIn('labelClass:`column-group-name column-swatch-${corePipelineColumnTone(item)}`', route_menu)
        self.assertNotIn('openCorePipelineColumn(', column_drawer)
        self.assertIn('function setCorePipelinePositionDownstream(sourceKey,targetKey,when="")', source)
        self.assertIn('String(edge.when||"completed")===condition', source)
        self.assertIn('edges.push({from:sourceKey,to:targetKey,...(condition!=="completed"?{when:condition}:{})})', source)
        capability_resolver = source.split('function corePipelinePositionCapabilities(snapshot){', 1)[1].split(
            'function corePipelinePositionMenu', 1
        )[0]
        self.assertIn('ref?.package_key', capability_resolver)
        self.assertIn('corePackageLabel', capability_resolver)
        position_menu = source.split('function corePipelinePositionMenu(event,key){', 1)[1].split(
            'async function updateCorePipelineColumnColor', 1
        )[0]
        self.assertIn('label:"编辑群组"', position_menu)
        self.assertIn('submenu:true', position_menu)
        self.assertIn('keepOpen:true', position_menu)
        self.assertIn('hoverFn:item=>openCoreColumnGroupEditor(item)', position_menu)
        self.assertIn('openCoreColumnGroupEditor(item)', position_menu)
        self.assertIn('label:"编辑员工"', position_menu)
        self.assertNotIn('系统指令', position_menu)
        self.assertNotIn('label:"与 AI 调整"', position_menu)
        self.assertNotIn('label:"流水线设置"', position_menu)
        self.assertNotIn('label:"移除岗位"', position_menu)
        group_editor = source.split('const CORE_BOARD_GROUP_SORT_OPTIONS=', 1)[1].split(
            'function corePipelinePositionMenu', 1
        )[0]
        self.assertIn('label:"手动"', group_editor)
        self.assertIn('label:"按字母顺序"', group_editor)
        self.assertIn('label:"按反向字母顺序"', group_editor)
        self.assertIn('隐藏空白分组', group_editor)
        self.assertIn('全部隐藏', group_editor)
        self.assertIn('toggleCoreBoardGroupVisibility(event)', group_editor)
        self.assertIn('coreColumnGroupRowPointerDown(event)', group_editor)
        self.assertIn('saveCoreBoardColumnOrder', group_editor)
        self.assertIn('if(_coreColumnGroupEditor&&_coreColumnGroupEditorAnchor===anchor)return', group_editor)
        self.assertIn('it.submenu?\' aria-haspopup="menu" aria-expanded="false"\':\'\'', source)
        self.assertIn('class="menu-submenu-arrow"', source)
        self.assertIn('if(it.hoverFn)it.hoverFn(a)', source)
        self.assertIn('.menu-submenu-arrow{width:14px;height:14px;', styles)
        self.assertNotIn('function runDeleteCoreWorkflow(id,acknowledged)', source)
        self.assertIn('.core-position-detail-drawer .node-contract,', styles)
        self.assertIn(
            '.core-position-detail-drawer .node-requirement-row{display:grid;grid-template-columns:76px minmax(0,1fr)',
            styles,
        )
        self.assertIn('async function runCorePipelineDraft()', source)
        self.assertIn('await api("/api/core/pipelines","POST"', source)
        self.assertIn('onclick="runCorePipelineDraft()"', source)
        self.assertIn('aria-label="打开员工"', source)
        self.assertIn('aria-label="打开最近动态"', source)
        self.assertIn('aria-label="打开团队参数"', source)
        self.assertIn('onclick="openCorePipelineParameters()"', source)
        self.assertIn('function pipelineSettingsDrawer()', source)
        self.assertIn('className:"pipeline-settings-drawer"', source)
        self.assertIn('function saveParamsSchema()', source)
        self.assertIn('definition={...current,parameters}', source)
        self.assertIn(
            '.pipeline-settings-drawer .param-pop .pop-f:has(>.csel){pointer-events:none}',
            styles,
        )
        self.assertNotIn(
            '.pipeline-settings-drawer .pset-field-card:hover::before',
            styles,
        )
        self.assertNotIn(
            '.pipeline-settings-drawer .pset-field-card:focus-within::before',
            styles,
        )
        self.assertIn(
            '.pipeline-settings-drawer .pset-field-source{min-width:0;margin-left:3px}',
            styles,
        )
        self.assertIn('function corePipelineEmployeesDrawer()', source)
        self.assertIn('function corePipelineActivityDrawer()', source)
        activity_drawer = source.split('function corePipelineActivityDrawer(){', 1)[1].split(
            'function corePipelineDrawer', 1
        )[0]
        workflow_drawer = source.split('function coreWorkflowDrawer(){', 1)[1].split(
            'function cancelCoreWorkflow', 1
        )[0]
        self.assertNotIn('core-pipeline-activity-icon', activity_drawer)
        self.assertIn('grid-template-columns:minmax(0,1fr) auto 13px', styles)
        self.assertIn('returnToCorePipelineActivity()', workflow_drawer)
        self.assertIn('aria-label="返回最近动态"', workflow_drawer)
        self.assertNotIn('snapshot.pipeline_name', workflow_drawer)
        self.assertIn('const returnTo=S.sel?.type==="core-pipeline-activity"', source)
        self.assertIn('const returnTo=S.sel?.returnTo||""', source)
        self.assertIn('if(state.draft){S.corePipeline.name=name;', source)
        self.assertIn('>岗位</button><button type="button" role="tab"', source)
        self.assertIn('>状态</button>', source)
        self.assertNotIn('corePipelineCreateMain', source)
        self.assertNotIn('.core-pipeline-create-page{', styles)

    def test_employee_capability_selection_survives_opening_the_editor(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        close_modal = source.split("function closeModal(){", 1)[1].split(
            "function confirmModal", 1
        )[0]
        picker = source.split("function coreEmployeeCapabilityOptions(){", 1)[1].split(
            "function coreRuntimeOptions", 1
        )[0]
        editor = source.split("function openCoreEmployeeEditor(id){", 1)[1].split(
            "async function publishCoreEmployee", 1
        )[0]

        self.assertNotIn("_coreEmployeeEditor=null", close_modal)
        self.assertIn("_coreEmployeeEditor={id:Number(id)||0", editor)
        self.assertIn("capabilities:(_coreEmployeeEditor?.capabilities||[])", editor)
        self.assertIn('aria-haspopup="menu" aria-expanded="false"', picker)
        self.assertIn("openCoreEmployeeCapabilityMenu(event)", picker)
        self.assertIn("coreEmployeeCapabilityMenuItems", picker)
        self.assertIn("refs.push({package_id:Number(packageId)", picker)

    def test_employee_runtime_reuses_header_model_and_effort_controls(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        editor = source.split("function openCoreEmployeeEditor(id){", 1)[1].split(
            "async function publishCoreEmployee", 1
        )[0]

        self.assertIn("${coreEmployeeRuntimeControls()}", editor)
        self.assertIn('modelCsel("core_employee_model",coreEmployeeModelItems(runtime)', source)
        self.assertIn('effortCsel("core_employee_effort",coreEmployeeEffortItems(runtime)', source)
        self.assertIn('<span class="kv-tag">思考</span>${effortCsel("core_employee_effort"', source)
        self.assertIn("workerModelItems(current.id", source)
        self.assertIn("effectiveModelValue(channel,runtime?.model||\"\")", source)
        self.assertIn("runtimeModel=effectiveModelValue(runtimeChannel,runtime.model||\"\")", editor)
        self.assertNotIn("CORE_DEFAULT_MODEL", source)
        self.assertNotIn("默认模型`", source)
        self.assertNotIn('id="core_employee_channel"', editor)
        self.assertNotIn("模型渠道", editor)
        self.assertNotIn("运行配置", editor)
        self.assertIn("runtime=_coreEmployeeEditor?.runtime", editor)

    def test_package_disable_requires_impact_preview_and_hides_disabled_bindings(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        drawer = source.split("function environmentPackageDetailModel(item){", 1)[1].split(
            "function environmentPackageDrawer", 1
        )[0]
        impact = source.split("async function openCorePackageImpact(id){", 1)[1].split(
            "async function disableCorePackage", 1
        )[0]
        picker = source.split("function coreEmployeeCapabilityCatalog(){", 1)[1].split(
            "function toggleCoreEmployeeCapability", 1
        )[0]

        self.assertIn("openCorePackageImpact", drawer)
        self.assertIn("重新启用", drawer)
        self.assertIn("/impact", impact)
        self.assertIn("受影响员工", impact)
        self.assertIn("这些运行已经冻结版本", impact)
        self.assertIn("blocked?'disabled'", impact)
        self.assertIn("packageItem.enabled!==false", picker)

    def test_employee_list_uses_the_core_employee_context_menu(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        menu = source.split("function coreEmployeeRowMenu(event,id)", 1)[1].split("function openCoreEmployeeConversation", 1)[0]

        self.assertIn('class="team-card" role="button" tabindex="0" onclick="openCoreEmployeeEditor(${item.id})" oncontextmenu="coreEmployeeRowMenu(event,${item.id})"', source)
        self.assertIn('event.type==="contextmenu"?{at:{x:event.clientX,y:event.clientY}}:{}', menu)
        self.assertLess(menu.index('label:"编辑"'), menu.index('label:"与 AI 对话调整"'))
        self.assertIn('if(item&&item.has_unpublished_changes)items.push({label:"发布新版本"', menu)
        self.assertIn('const used=coreEmployeeUsage(id)', menu)
        self.assertIn('label:`打开「${pipeline.name}」`', menu)

    def test_card_facts_expand_button_overlays_bottom_without_reserving_right_column(self):
        styles = (Path(__file__).parents[1] / "web" / "runteams.css").read_text(encoding="utf-8")
        self.assertIn('.card-detail-drawer .card-detail-more{right:0;bottom:0}', styles)
        facts_rule = styles.split(
            '.card-detail-drawer .card-facts-section.has-overflow .card-detail-facts,', 1
        )[1].split('}', 1)[0]
        self.assertIn('padding-bottom:34px', facts_rule)
        self.assertNotIn('padding-right', facts_rule)

    def test_confirmation_buttons_use_short_action_labels(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'const actionLabel=danger&&/删除/.test(String(title||""))?"删除":"确定";',
            source,
        )
        self.assertNotIn(
            'String(title||"确认").replace(/[？?]\\s*$/,"")', source
        )

    def test_automation_http_lifecycle_exposes_work_record_trash_and_retry(self):
        old_db = app.local_database.DB_PATH
        temporary = tempfile.TemporaryDirectory(prefix="runteams-automation-http-")
        app.local_database.DB_PATH = str(Path(temporary.name) / "runteams.db")
        app.store.init_product_db()
        channel = app.store.get_default_channel()
        automation = app.automations.save_automation({
            "name": "HTTP audit", "prompt": "执行检查",
            "channel_id": channel["id"], "model": "agent-test",
        })
        app.automations.run_automation_now(automation["id"])
        job = app.automations.claim_next_automation_run()
        app.automations.add_automation_run_event(job["id"], "agent_event", {
            "kind": "work_delta", "id": "read", "delta": "已读取数据"})
        app.automations.finish_automation_run(job["id"], "completed", "完成")
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            connection.request("GET", "/api/automation-run/{}".format(job["id"]))
            response = connection.getresponse()
            record = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(record["events"][0]["content"]["delta"], "已读取数据")

            queued = app.automations.run_automation_now(automation["id"])

            def cancel_current(automation_id, reason, wait_timeout=0):
                app.automations.cancel_queued_automation_runs(automation_id, reason)
                return True

            with mock.patch.object(app.AUTOMATION_SCHEDULER, "cancel_automation",
                                   side_effect=cancel_current):
                connection.request("POST", "/api/automation/{}/cancel".format(automation["id"]), b"{}",
                                   {"Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertTrue(json.loads(response.read().decode("utf-8"))["ok"])
            self.assertTrue(app.automations.get_automation(automation["id"])["enabled"])
            self.assertEqual(app.automations.get_automation_run(queued["id"])["status"], "cancelled")

            with mock.patch.object(app.AUTOMATION_SCHEDULER, "cancel_automation", return_value=True):
                connection.request("POST", "/api/automation/{}/delete".format(automation["id"]), b"{}",
                                   {"Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertTrue(json.loads(response.read().decode("utf-8"))["trashed"])
            self.assertEqual(app.automations.list_automations(), [])

            connection.request("POST", "/api/trash/automation/{}/restore".format(automation["id"]), b"{}",
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertTrue(json.loads(response.read().decode("utf-8"))["ok"])

            retry_source = app.automations.run_automation_now(automation["id"])
            claimed = app.automations.claim_next_automation_run()
            app.automations.finish_automation_run(claimed["id"], "failed", "模型不可用")
            body = json.dumps({"action": "retry"}).encode("utf-8")
            with mock.patch.object(app.AUTOMATION_SCHEDULER, "wake") as wake:
                connection.request("POST", "/api/automation-attention/{}/action".format(
                    retry_source["id"]), body,
                                   {"Content-Type": "application/json"})
                response = connection.getresponse()
                result = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertIn("automation_run_id", result)
            wake.assert_called_once_with()
            self.assertEqual(app.automations.automation_attention_catalog(), [])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.local_database.DB_PATH = old_db
            temporary.cleanup()

    def test_default_route_opens_home_sidebar_without_creating_a_chat(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'if(path==="/"||path==="/index.html")return {kind:"home"', source
        )
        self.assertIn('if(route.kind==="home")', source)
        self.assertIn('corePipelineRoute(pipeline.id,{chat:null})', source)
        self.assertIn('const pipeline=S.corePipelines[0]', source)
        self.assertNotIn('if(path==="/")return {kind:"chat-new"', source)

    def test_split_workspace_route_keeps_primary_page_and_left_chat_in_one_url(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("function parseRailRoute(query)", source)
        self.assertIn('query.get("chat")', source)
        self.assertIn('target.searchParams.set("chat",String(value))', source)
        self.assertIn("function routeWithRailState(url,chat)", source)
        self.assertIn(
            "await applyRailRouteState(rail,{focus:false,initial:initialRailHydration})",
            source,
        )
        self.assertIn("railRouteHydrating:false", source)
        self.assertIn("const deferInitialRender=options.initial===true", source)
        self.assertIn("render:!deferInitialRender", source)
        self.assertIn(
            '!S.railRouteHydrating&&!railConversationIsVisible(S.conversationPanel)',
            source,
        )
        self.assertIn("function conversationViewIdentity()", source)
        self.assertIn('panel.kind||"general"', source)
        self.assertIn("syncRailRoute(panel.id,true)", source)
        self.assertIn('if(panel.kind==="general")return true', source)
        self.assertIn("setAppUrl(environmentRoute(null))", source)
        self.assertIn("setAppUrl(routeWithRailState(`/design-system?theme=${theme}`),true)", source)

    def test_trash_page_has_recovery_first_layout_and_live_sync(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        trash = source.split("async function openTrash(options={})", 1)[1].split(
            "async function refreshAutomations", 1)[0]

        self.assertIn("const TRASH_SYNC_INTERVAL_MS=2500;", source)
        self.assertIn('setInterval(syncTrash,TRASH_SYNC_INTERVAL_MS)', source)
        self.assertIn('refreshTrash({silent:true,renderIfChanged:true})', source)
        self.assertIn('window.addEventListener("focus",()=>{refreshPendingChannelLogins();if(S.surface==="trash")syncTrash();})', source)
        self.assertIn('document.addEventListener("visibilitychange"', source)
        self.assertIn('S.trashItems=result.items||[];', trash)
        self.assertNotIn('api("/api/pipelines")', trash)
        self.assertNotIn('S.trashFilter', trash)
        self.assertNotIn('trashFilterKind', trash)
        self.assertNotIn('counts[key]||0', trash)
        self.assertIn('class="trash-list-summary"', trash)
        self.assertIn('class="trash-list-columns"', trash)
        self.assertIn('class="trash-list-row trash-type-${esc(kind)}"', trash)
        self.assertIn('class="trash-list-main"', trash)
        self.assertIn('class="trash-list-lifecycle"', trash)
        self.assertIn('class="trash-list-inline-meta"', trash)
        self.assertIn('class="trash-restore"', trash)
        self.assertIn('class="trash-delete"', trash)
        self.assertIn("onclick=\"permanentlyDeleteTrashItem('${esc(kind)}'", trash)
        self.assertNotIn('class="trash-list-more"', trash)
        self.assertNotIn('${ICON("back")}<span>恢复</span>', trash)
        self.assertIn('class="trash-list-expiry ${expiry.urgent?"urgent":""}"', trash)
        self.assertIn(".trash-list-wrap{", styles)
        self.assertIn(".trash-list-row{", styles)
        self.assertIn(".trash-list-row:hover{", styles)
        self.assertIn(".trash-list-row:focus-within{outline:0;box-shadow:none}", styles)
        self.assertIn('pipeline=kind==="pipeline"', trash)
        self.assertIn('position=kind==="position"', trash)
        self.assertIn('`/api/core/pipelines/${id}/restore`', trash)
        self.assertIn('`/api/core/pipelines/${id}/delete`', trash)
        self.assertIn('`/api/core/pipeline-positions/${id}/restore`', trash)
        self.assertIn('`/api/core/pipeline-positions/${id}/delete`', trash)
        self.assertNotIn(".trash-list-row.trash-type-card .trash-list-icon{", styles)
        self.assertIn(".trash-list-icon .i{width:20px;height:20px", styles)
        self.assertIn(".trash-empty-icon{", styles)

    def test_core_pipeline_sidebar_restores_the_shared_action_menu(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("function corePipelineRowMenu(event,id)", source)
        self.assertIn('label:railPipelinePinned(id)?"取消置顶":"置顶"', source)
        self.assertIn('{label:"重命名",icon:"edit",fn:()=>renameCorePipeline(id)}', source)
        self.assertIn('{label:"移到垃圾箱",icon:"trash",fn:()=>trashCorePipeline(id)}', source)
        self.assertIn('oncontextmenu="corePipelineRowMenu(event,${Number(p.id)})"', source)
        self.assertIn('title="更多操作"', source)
        self.assertIn('onclick="corePipelineRowMenu(event,${Number(p.id)})"', source)
        self.assertIn('railOrderedCorePipelines().map(p=>', source)
        self.assertIn('`/api/core/pipelines/${Number(id)}/trash`', source)
        self.assertNotIn('api("/api/pipeline/"+pid+"/delete"', source)

    def test_all_modal_surfaces_use_the_shared_dialog_shell(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")

        self.assertIn("function dialogMarkup(opts={})", source)
        self.assertIn("function openDialog(opts)", source)
        self.assertIn("function replaceDialog(opts)", source)
        self.assertIn("function openChildDialog(opts)", source)
        self.assertIn("function replaceChildDialog(opts)", source)
        self.assertIn("function closeChildDialog()", source)
        self.assertEqual(source.count("openModal("), 2)
        self.assertNotIn('class="scrim"', source)
        self.assertIn(".dialog-shell>.mh{", styles)

    def test_signed_out_login_uses_an_independent_dialog(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")

        self.assertIn("function openLoginDialog()", source)
        self.assertIn("className:'account-login-modal'", source)
        self.assertNotIn("if(!S.account.signed_in){openLoginDialog();return;}", source)
        self.assertIn("if(!S.account.signed_in)return `${settingsPageHead('移动设备'", source)
        self.assertIn("/api/account/otp/request", source)
        self.assertIn("/api/account/otp/verify", source)
        self.assertIn(".account-login-modal{width:420px}", styles)
        self.assertNotIn("function accountSettingsPanel()", source)
        self.assertIn("function generalSettingsPanel()", source)

    def test_mobile_settings_keep_privacy_visible_and_preview_nested(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        panel = source.split("function remoteSettingsPanel()", 1)[1].split(
            "function generalSettingsPanel()", 1
        )[0]
        preview = source.split("async function openMobilePreview()", 1)[1].split(
            "function closeChannels()", 1
        )[0]

        self.assertIn("settingsSectionHead('已关联设备')", panel)
        self.assertIn("settingsSectionHead('同步与隐私')", panel)
        self.assertLess(
            panel.index("settingsSectionHead('已关联设备')"),
            panel.index("settingsSectionHead('同步与隐私')"),
        )
        self.assertIn("仅保留在本机", panel)
        self.assertIn("完整任务说明、本地工作文件、凭据和模型对话", panel)
        self.assertNotIn('<details class="settings-disclosure">', panel)
        self.assertIn("openChildDialog(", preview)
        self.assertIn("replaceChildDialog(", preview)
        self.assertIn('onclick="closeChildDialog()"', preview)
        self.assertNotIn("openDialog(", preview)
        self.assertNotIn("replaceDialog(", preview)

    def test_appearance_picker_uses_preview_led_selection(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        option = source.split("function appearanceOption(", 1)[1].split(
            "function entitlementStatusLabel", 1
        )[0]

        self.assertIn('aria-pressed="${S.account.theme===value?', option)
        self.assertIn('class="appearance-preview ${value}"', option)
        self.assertIn('class="appearance-radio"', option)
        self.assertIn("button.setAttribute('aria-pressed'", source)
        self.assertIn(".appearance-option.on{border-color:", styles)
        self.assertIn(".appearance-preview.system{", styles)

    def test_sidebar_account_button_has_non_blocking_list_fade(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        styles = (Path(__file__).parents[1] / "web" / "runteams.css").read_text(encoding="utf-8")

        self.assertIn(".railfoot-wrap{position:relative;z-index:2;", styles)
        self.assertIn(".rail{position:relative;background:var(--rail);border-right:1px solid var(--line);padding:40px 0 8px;", styles)
        self.assertIn("width:100%", styles.split(".railfoot-wrap{", 1)[1].split("}", 1)[0])
        self.assertIn(".railfoot-wrap:after{content:\"\";position:absolute;left:0;right:0;top:0;height:1px;", styles)
        self.assertIn(".railfoot-wrap:before{content:\"\";", styles)
        self.assertIn("linear-gradient(to bottom,transparent 0%", styles)
        self.assertIn("pointer-events:none", styles.split(".railfoot-wrap:before", 1)[1].split("}", 1)[0])
        self.assertIn('S.account.signed_in?S.account.name:"登录"', source)
        self.assertNotIn("<small>账号</small>", source)
        self.assertNotIn("sk-rail-meta", source)
        self.assertNotIn("acmore", source + styles)

    def test_sidebar_feedback_entry_uses_shared_dialog_and_remote_proxy(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        backend = (root / "app.py").read_text(encoding="utf-8")
        relay = (root / "relay_sync.py").read_text(encoding="utf-8")

        self.assertIn('class="rail-feedback"', source)
        self.assertIn('aria-label="提交产品反馈"', source)
        self.assertIn('function openProductFeedback(event)', source)
        self.assertIn('openDialog({className:"feedback-modal"', source)
        self.assertIn('id="feedback_submit" onclick="submitProductFeedback()"', source)
        self.assertIn('api("/api/feedback","POST"', source)
        self.assertIn('${ICON("bug")}', source)
        self.assertIn('<symbol id="i-bug" viewBox="0 0 24 24"><path d="M12 20v-9"/><path d="M14 7a4 4 0 0 1 4 4v3a6 6 0 0 1-12 0v-3a4 4 0 0 1 4-4z"/>', source)
        self.assertIn('title:"产品反馈",subtitle:"分享你的建议、问题或想法"', source)
        self.assertIn('placeholder="写下你希望我们改进的地方"', source)
        self.assertIn('if(!message){toast("请先填写反馈内容","err")', source)
        self.assertNotIn('syncProductFeedback', source)
        self.assertNotIn('feedback_count', source)
        self.assertNotIn('不包含流水线或任务内容', source)
        self.assertNotIn('.railfoot-row:hover{background:var(--rail-active)}', styles)
        self.assertIn('.rail-account-actions:hover{background:var(--rail-active)}', styles)
        self.assertIn('.rail-feedback:hover,.rail-feedback:focus-visible{color:var(--ink)}', styles)
        self.assertNotIn('.rail-feedback:hover{background:', styles)
        self.assertIn('.rail-feedback{', styles)
        self.assertIn('.feedback-modal{width:500px}', styles)
        self.assertIn('if p == "/api/feedback":', backend)
        self.assertIn('relay_sync.feedback_request(d)', backend)
        self.assertIn('"POST", "/v1/feedback", payload, token=account_access_token()', relay)

    def test_sidebar_shows_silent_update_state_before_collapse_control(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        backend = (root / "app.py").read_text(encoding="utf-8")

        self.assertIn('appUpdate:{state:"idle"}', source)
        self.assertIn('function appUpdateButton()', source)
        self.assertIn('["downloading","ready"].includes(state)', source)
        self.assertIn('new URLSearchParams(location.search).get("mock_update")', source)
        self.assertIn('["127.0.0.1","localhost"].includes(location.hostname)', source)
        self.assertIn('available_version:"0.2.0",preview:true', source)
        self.assertNotIn('即将在后台静默下载', source)
        self.assertIn('正在后台静默下载', source)
        self.assertIn('下次完整重启应用时会自动更新', source)
        self.assertIn('refreshAppUpdate(false)', source)
        self.assertIn('setInterval(()=>refreshAppUpdate(true),15000)', source)
        self.assertIn('const updateButton=appUpdateButton();', source)
        footer = source.split('const accountFooter=`', 1)[1].split('`;', 1)[0]
        self.assertIn('${updateButton?"":`<button class="rail-feedback"', footer)
        self.assertGreater(footer.index('${updateButton}'), footer.index('class="rail-account-actions"'))
        self.assertNotIn('rail-collapse-bottom', footer)
        self.assertIn('.rail-update{', styles)
        self.assertIn('color:var(--sub);background:transparent', styles)
        self.assertNotIn('.rail-update.state-ready', styles)
        self.assertNotIn('rail-update-state', source + styles)
        self.assertIn('class="rail-update-scan" aria-hidden="true"', source)
        self.assertIn('animation:railupdatescan 1.55s ease-in-out infinite', styles)
        self.assertIn('@keyframes railupdatescan{', styles)
        self.assertIn('@media (prefers-reduced-motion:reduce){.rail-update-scan{display:none}}', styles)
        self.assertIn('if p == "/api/app-update":', backend)

    def test_sidebar_lists_fade_and_marquee_without_visible_meta_labels(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")

        self.assertIn('class="railmid-shell"', source)
        self.assertIn(".railmid-shell{position:relative;display:flex;flex:1;min-height:0;padding:0 8px}", styles)
        self.assertNotIn(".railmid-shell:after{", styles)
        self.assertIn("function railMarqueeStart(row)", source)
        self.assertIn("function syncRailMarquees(root=document)", source)
        self.assertIn('new ResizeObserver(entries=>entries.forEach(entry=>syncRailMarquee(entry.target)))', source)
        self.assertIn('if(available<=0){label.classList.remove("has-overflow","is-overflowing")', source)
        self.assertIn('hasOverflow=overflow>2', source)
        self.assertIn('document.fonts.ready.then(()=>syncRailMarquees(document.getElementById("rgRail")))', source)
        self.assertIn(".rail-marquee.is-overflowing .rail-marquee-text{animation:", styles)
        self.assertIn("linear .08s infinite alternate", styles)
        self.assertIn(".rail-marquee.has-overflow{-webkit-mask-image:linear-gradient(to right,#000 0%,#000 calc(100% - 18px),transparent 100%)", styles)
        self.assertIn(".rail-marquee.is-overflowing{-webkit-mask-image:linear-gradient(to right,transparent 0%,#000 18px,#000 calc(100% - 18px),transparent 100%)", styles)
        self.assertIn("0%,4%{transform:translateX(0)}", styles)
        self.assertIn("distance=Math.ceil(content-Math.max(0,available-18))", source)
        self.assertIn(".fd{display:flex;align-items:center;", styles)
        self.assertNotIn("fdtime", source + styles)
        self.assertNotIn("fdaction", source + styles)
        self.assertIn("function railItemEnter(row)", source)
        self.assertIn("function railPreviewTime(ts)", source)
        self.assertIn('data-rail-pipeline="${esc(railPreviewPipeline(', source)
        self.assertNotIn('title="${esc(detail)}"', source)
        self.assertNotIn('title="${esc(item.reason||title)}"', source)
        self.assertIn(".rail-item-preview{position:fixed;", styles)

    def test_dialog_and_floating_surface_colors_use_shared_theme_tokens(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")

        self.assertIn("--dialog-bg:#fcfcfb", styles)
        self.assertIn("--floating-bg:rgba(249,249,248,.92)", styles)
        self.assertIn("--dialog-bg:#232120", styles)
        self.assertIn("--floating-bg:rgba(35,33,32,.92)", styles)
        self.assertIn(".modal{width:520px;max-width:92%;max-height:88vh;background:var(--dialog-bg)", styles)
        self.assertIn(".rail-command{", styles)
        self.assertIn("background:var(--dialog-bg)", styles)
        self.assertIn(".menu a .i{width:15px;height:15px;color:currentColor}", styles)
        self.assertIn(".usage-badge{", styles)
        self.assertNotIn(".usage-mini{", styles)
        self.assertIn(".wirebubble{", styles)
        self.assertIn(".param-pop{position:fixed;", styles)
        self.assertIn("overflow:auto;background:var(--floating-bg)", styles)
        self.assertIn(".cap-picker{position:fixed;", styles)
        self.assertIn("flex-direction:column;background:var(--floating-bg)", styles)
        self.assertNotIn(".menu a.active.danger{", styles)
        self.assertNotIn(".menu a.danger{", styles)
        self.assertNotIn("background:#fcfcfb", styles)
        preview = source.split("function openRailPreview(row)", 1)[1].split("function railItemEnter(row)", 1)[0]
        self.assertIn('${ICON("flow")}', preview)
        self.assertNotIn('ICON("folder")', preview)
        self.assertIn("Math.min(rect.top,window.innerHeight-pop.offsetHeight-gap)", preview)
        self.assertNotIn("rect.top+(rect.height-pop.offsetHeight)/2", preview)

    def test_provider_catalog_drives_channels_and_frontend_metadata(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        app_source = (root / "app.py").read_text(encoding="utf-8")
        catalog = (root / "provider_catalog.py").read_text(encoding="utf-8")

        self.assertIn('"providers": model_channels.public_providers()', app_source)
        self.assertIn('S.providerCatalog=mc.providers||[]', source)
        self.assertIn('function providerDefinitions()', source)
        self.assertIn('providerDefinitions().map(item=>', source)
        self.assertIn('"plugin_add_command": "codex plugin add {id}"', catalog)
        self.assertIn('"plugin_add_command": "claude plugin install {id}"', catalog)

    def test_delivery_markdown_uses_local_gfm_parser_and_html_sanitizer(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        marked = (root / "web" / "vendor" / "marked.js").read_text(encoding="utf-8")
        purify = (root / "web" / "vendor" / "purify.min.js").read_text(encoding="utf-8")
        self.assertIn('<script src="/vendor/marked.js"></script>', source)
        self.assertIn('<script src="/vendor/purify.min.js"></script>', source)
        self.assertIn('window.marked.parse(source,{gfm:true,breaks:true,pedantic:false})', source)
        self.assertIn('window.DOMPurify.sanitize(', source)
        self.assertIn('USE_PROFILES:{html:true}', source)
        self.assertIn('rel="noopener noreferrer"', source)
        self.assertIn('.md-preview table{', styles)
        self.assertIn('.md-preview blockquote{', styles)
        self.assertIn('.md-preview li:has(>input[type="checkbox"]){', styles)
        self.assertIn('marked v17.0.5', marked)
        self.assertIn('DOMPurify 3.4.10', purify)
        self.assertNotIn('function inlineMarkdown(', source)

    def test_billing_routes_proxy_through_the_local_account_boundary(self):
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            with mock.patch(
                "app.relay_sync.billing_request",
                side_effect=[
                    {"configured": True, "can_checkout": True},
                    {"url": "https://checkout.stripe.com/c/pay/test"},
                ],
            ) as request:
                connection.request("GET", "/api/billing/status")
                status = connection.getresponse()
                self.assertEqual(status.status, 200)
                self.assertTrue(json.loads(status.read())["configured"])

                connection.request(
                    "POST", "/api/billing/checkout", body=b"{}",
                    headers={"Content-Type": "application/json", "Content-Length": "2"},
                )
                checkout = connection.getresponse()
                self.assertEqual(checkout.status, 200)
                self.assertTrue(json.loads(checkout.read())["url"].startswith(
                    "https://checkout.stripe.com/"
                ))
                self.assertEqual(request.call_args_list[0].args, (
                    "GET", "/v1/billing/status"
                ))
                self.assertEqual(request.call_args_list[1].args, (
                    "POST", "/v1/billing/checkout-session"
                ))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_health_endpoint_exposes_frontend_compatibility_version(self):
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            connection.request("GET", "/api/health")
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["app"], "RunTeams.ai")
            self.assertEqual(payload["api_version"], app.API_COMPAT_VERSION)
            self.assertIsInstance(payload["pid"], int)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_frontend_and_desktop_launcher_guard_against_stale_backend(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        launcher = (root / "desktop" / "build.sh").read_text(encoding="utf-8")
        self.assertNotIn("const r=await fetch(path,o); return r.json();", source)
        self.assertIn("当前版本不支持这项操作。请重新打开 RunTeams", source)
        self.assertIn("EXPECTED_API_VERSION={}".format(app.API_COMPAT_VERSION), launcher)
        self.assertIn("/api/health", launcher)
        self.assertIn("*runteams-server*", launcher)
        self.assertIn("LAUNCH_LOCK", launcher)
        self.assertIn("/usr/bin/nohup", launcher)
        self.assertNotIn('kill -TERM "$SERVER_PID"', launcher)

    def test_new_chat_navigation_tracks_the_active_conversation(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        self.assertIn('function newRailChat(options={})', source)
        self.assertIn('onclick="newRailChat()"', source)
        self.assertNotIn('inChat', source)
        self.assertNotIn('(inChat ? chatMain()', source)
        self.assertIn('const newConversationActive=mode==="assistant"', source)
        self.assertIn('else requestAnimationFrame(()=>setRailMode("assistant"))', source)
        self.assertIn('startedAsNew=S.chatId==="new"', source)
        self.assertIn("function activateCreatedChat()", source)
        self.assertIn('if(startedAsNew)activateCreatedChat()', source)
        self.assertIn(".rail-primary-action:hover,.rail-primary-action.on{", styles)

    def test_chat_composer_enter_sends_and_shift_enter_keeps_a_newline(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('function conversationComposerKeydown(event,surface)', source)
        self.assertIn('if(event.shiftKey)return;', source)
        self.assertIn('if(surface==="panel")sendConversationPanel();else sendChat();', source)
        self.assertIn('function chatKeydown(event)', source)
        self.assertIn('function conversationPanelKeydown(event)', source)

    def test_running_conversations_can_continue_while_the_user_switches(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('conversationPanelsByChat:{}', source)
        self.assertIn('function cachedConversationPanel(id)', source)
        self.assertIn('const cached=cachedConversationPanel(id)', source)
        self.assertIn('refreshLiveAgentMessage(live,"panel",panel)', source)
        self.assertNotIn('助手完成当前工作后即可切换', source)
        self.assertNotIn('助手完成当前工作后即可开始新对话', source)

    def test_live_agent_plan_actions_keep_the_real_message_index(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        # A live panel message is initially patched in place.  Its proposal
        # buttons must target the message's actual array index; using -1 makes
        # confirmPlan/cancelPlan silently no-op until a full reload.
        self.assertIn('messageIndex=messages.indexOf(message)', source)
        self.assertIn('botConversationBody(message,messageIndex,surface)', source)
        self.assertNotIn('botConversationBody(message,-1,surface)', source)

    def test_pipeline_conversations_render_under_their_pipeline_and_in_recent(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('function chatPipelineId(chat)', source)
        self.assertIn('function railChatsForPipeline(pid)', source)
        self.assertIn('chats=railChatsForPipeline(p.id)', source)
        self.assertIn('open=!!chats.length&&railPipelineChatsOpen(p.id)', source)
        self.assertNotIn('还没有对话', source)
        self.assertIn('class="rail-pl-body ${open?"":"collapsed"}"', source)
        self.assertIn('function railOtherChats(){return railOrderedChats();}', source)
        self.assertIn('const chatRow=(ch)=>', source)
        self.assertIn('pipelineId=explicitScope?options.scopePipelineId:railConversationPipelineId()', source)

    def test_home_sidebar_conversations_do_not_keep_a_selected_background(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        rail_rows = source.split("function rail(){", 1)[1].split(
            "const pipelineTree=", 1
        )[0]

        self.assertIn("const chatRow=(ch)=>", rail_rows)
        self.assertNotIn("ch.id===S.chatId", rail_rows)
        self.assertNotIn("S.conversationPanel?.id", rail_rows)
        self.assertIn('railChatPinned(ch.id)', rail_rows)

    def test_sidebar_scrollbar_is_hidden_without_disabling_scroll(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        self.assertIn(".railmid{width:100%;flex:1;min-height:0;overflow-y:auto;overflow-anchor:none;overscroll-behavior:none;scroll-behavior:auto", styles)
        self.assertIn("scrollbar-width:none", styles)
        self.assertIn(".railmid::-webkit-scrollbar{display:none}", styles)
        self.assertIn(".rail-section-head{position:relative;", styles)
        self.assertNotIn(".rail-section-head{position:sticky", styles)
        self.assertIn(".rail-fixed{position:relative;z-index:4;", styles)
        self.assertIn(".rail-actions{position:relative;display:flex;width:100%;flex:0 0 auto;flex-direction:column;gap:1px;padding:", styles)
        self.assertIn(".rail-navigation-pane>.rail-actions.is-scrolled:after{background:", styles)
        self.assertIn(".railfoot-wrap:after{content:\"\";position:absolute;left:0;right:0;top:0;height:1px;", styles)
        self.assertIn('actions.classList.toggle("is-scrolled",overflow&&mid.scrollTop>0)', source)
        self.assertIn(".rail-primary-action{width:100%;min-height:32px;", styles)
        self.assertIn("transform:scale(var(--rail-icon-scale,1));transform-origin:center", styles)
        self.assertIn(".rail-new-chat{--rail-icon-scale:.94}", styles)
        navigation_body = source.split('const navigationBody=`', 1)[1].split(
            'const railActions=', 1
        )[0]
        self.assertIn("rail-new-chat", source)
        self.assertNotIn("rail-new-pipeline", source)
        self.assertIn("rail-section-add", source)
        self.assertIn(".rail-team{--rail-icon-scale:.92}", styles)
        self.assertIn(".rail-automations{--rail-icon-scale:.96}", styles)
        self.assertIn(".rail-environment{--rail-icon-scale:1.06}", styles)
        self.assertIn(".rail-environment>.i{stroke-width:1.9}", styles)
        self.assertIn('<symbol id="i-plug" viewBox="0 0 24 24"><path d="M12 22v-5"/><path d="M15 8V2"/><path d="M17 8a1 1 0 0 1 1 1v4a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1z"/><path d="M9 8V2"/></symbol>', source)
        self.assertIn(".rl a{display:flex;align-items:center;gap:8px;width:100%;min-height:30px;padding:3px 10px;", styles)
        self.assertIn(".fd{display:flex;align-items:center;width:100%;min-height:30px;padding:3px 8px 3px 18px;", styles)
        self.assertIn(".rail-more{width:100%;min-height:30px;", styles)
        self.assertIn(".boot-rail-row{height:31px;", styles)

    def test_sidebar_merges_attention_into_recent_without_feed_skeleton(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        self.assertIn("railSections:{pipelines:true,recent:true}", source)
        self.assertNotIn("railFeedLoading", source)
        boot_body = source.split("async function boot(){", 1)[1].split("\n}\nlet _interventionsRefreshPromise", 1)[0]
        self.assertNotIn('api("/api/pipelines")', boot_body)
        self.assertNotIn('api("/api/workers")', boot_body)
        self.assertNotIn("refreshRailFeed(),", boot_body)
        self.assertIn("refreshInterventions(),", boot_body)
        self.assertNotIn('${section("attention","待你处理"', source)
        self.assertIn('function attentionRow(item)', source)
        self.assertNotIn("railFeedSkeleton", source)
        self.assertNotIn(".rail-feed-skeleton{", styles)

    def test_core_workflow_detail_uses_shared_docked_drawer(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        self.assertIn('const corePipelineDetailDrawer = S.surface==="core-pipeline"&&!!S.sel;', source)
        self.assertIn('const drawerContent = resourceDrawer?dockedEnvironmentDetailDrawer(environmentDetailDrawer()):corePipelineDrawer();', source)
        self.assertIn('const drawerWidth=showDrawer?`${activeRightDetailWidth()}px`:"0px";', source)
        self.assertIn('function detailResizeHandle()', source)
        self.assertIn('onpointerdown="detailResizeStart(event)"', source)
        self.assertIn('function detailResizeKeydown(event)', source)
        self.assertIn('系统已经尝试', source)
        self.assertIn('继续后从哪里恢复', source)
        self.assertIn('function openFailureStats()', source)
        self.assertIn('api("/api/failure-stats")', source)
        self.assertIn('运行检查', source)
        self.assertIn('function openCorePipelineCheck()', source)
        self.assertIn('function previewCoreArtifact(artifact)', source)
        self.assertIn('/api/core/artifacts/${Number(artifact.id)}/open', source)
        self.assertIn('/api/core/artifacts/${Number(artifact.id)}/export', source)
        self.assertIn('预览', source)
        self.assertIn('打开', source)
        self.assertIn('导出', source)
        self.assertIn('RIGHT_DETAIL_COLLAPSE_SNAP=180', source)
        self.assertIn('.detail-resize-handle{', styles)
        self.assertIn('body.rail-resizing,body.detail-resizing', styles)

    def test_task_detail_files_use_preview_and_download_only(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        artifact_row = source.split("function coreArtifactRow(artifact)", 1)[1].split(
            "function coreWorkflowRunRow", 1)[0]
        input_panel = source.split("function coreWorkflowTaskInputPanel(workflow,payload)", 1)[1].split(
            "function coreWorkflowDeliverables", 1)[0]
        self.assertIn("下载", artifact_row)
        self.assertIn("previewCoreArtifact", artifact_row)
        self.assertNotIn('core-artifact-actions">${previewable?', artifact_row)
        self.assertNotIn("打开</button>", artifact_row)
        self.assertNotIn("导出</button>", artifact_row)
        self.assertIn("previewCoreTaskInput", input_panel)
        self.assertIn("downloadCoreTaskInput", input_panel)
        self.assertNotIn('card-input-actions">${previewable?', input_panel)
        self.assertIn("S.docReaderOrigin", source)
        self.assertIn("routeWithRailState(\"/docs\",currentRailRouteValue())", source)
        self.assertIn("if(!options.keepReader){S.docReaderOrigin=null;S.docReaderStack=[];if(S.docReader)teardownDocumentReader();}", source)
        self.assertIn("openDocs({route:false,keepReader:true})", source)
        self.assertIn(".doc-reader-page .doc-reader-back span{display:none}", (root / "web" / "runteams.css").read_text(encoding="utf-8"))
        self.assertIn('backButton.setAttribute("aria-label","返回")', source)
        self.assertIn("workflowId", source.split("function closeDocumentReader()", 1)[1].split("function teardownDocumentReader", 1)[0])
        self.assertIn("/api/core/workflows/(\\d+)/inputs", (root / "app.py").read_text(encoding="utf-8"))
        self.assertIn("card-input-section+.core-workflow-deliverables", (root / "web" / "runteams.css").read_text(encoding="utf-8"))

    def test_work_history_is_newest_first_and_hover_fills_drawer(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        self.assertIn("function coreEmployeeRunTimestamp(value)", source)
        self.assertIn("[...(runs||[])].sort((a,b)=>", source)
        self.assertIn("b.updated_at||b.created_at", source)
        self.assertIn(".core-workflow-drawer .core-run-overview::before", styles)
        self.assertIn(".core-workflow-drawer .core-run-overview:hover::before", styles)
        self.assertIn("pointer-events:none", styles)
        self.assertIn("border-radius:0;background:transparent;pointer-events:none", styles)
        self.assertIn(".core-workflow-drawer .card-input-item::before,.core-workflow-drawer .core-artifact::before", styles)
        self.assertIn(".core-workflow-drawer .card-input-item:hover::before,.core-workflow-drawer .card-input-item:focus-within::before,.core-workflow-drawer .core-artifact:hover::before", styles)
        self.assertIn(".core-workflow-drawer .card-input-item,.core-workflow-drawer .core-artifact{position:relative;width:calc(100% + 16px);", styles)
        self.assertIn(".core-workflow-drawer .core-artifact:not(.core-file-row)+.core-artifact:not(.core-file-row){border-top:0}", styles)
        self.assertIn(".core-run-detail-drawer .core-artifact::before", styles)
        self.assertIn(".core-run-detail-drawer .core-artifact:hover::before,.core-run-detail-drawer .core-artifact:focus-within::before", styles)
        self.assertIn(".core-run-detail-drawer .run-progress-row+.run-progress-row::before{display:none}", styles)
        self.assertIn(".core-run-detail-drawer .run-progress-row::after", styles)
        self.assertIn(".core-run-detail-drawer .run-progress-row:hover::after,.core-run-detail-drawer .run-progress-row:focus-within::after", styles)
        self.assertIn(".core-workflow-drawer .card-run-section .core-run-overview{position:relative;width:calc(100% + 16px);", styles)
        self.assertIn("padding:var(--detail-space-3) var(--detail-space-3)", styles)

    def test_detail_body_disallows_horizontal_scroll_and_uses_overlay_scrollbar(self):
        styles = (Path(__file__).parents[1] / "web" / "runteams.css").read_text(encoding="utf-8")
        self.assertIn(".right-detail-drawer .right-detail-body", styles)
        self.assertIn("overflow-x:hidden", styles)
        self.assertIn("overflow-y:auto", styles)
        self.assertIn("scrollbar-gutter:auto", styles)
        self.assertIn("scrollbar-width:none", styles)
        self.assertIn("::-webkit-scrollbar{width:0;height:0;display:none}", styles)

    def test_agent_chat_messages_have_copy_and_edit_actions_without_regeneration(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")

        self.assertIn('function copyConversationMessage(surface,index)', source)
        self.assertIn('function editConversationMessage(surface,index)', source)
        self.assertNotIn('function retryConversationMessage(surface,index)', source)
        self.assertIn('class="cmessage-actions" role="toolbar"', source)
        self.assertIn('title="编辑并重新发送"', source)
        self.assertNotIn('title="重新尝试"', source)
        self.assertIn('rewind_message_id:', source)
        self.assertIn('已经执行的任务、流水线和文件改动会保留', source)
        self.assertIn('.cmessage-stack:hover .cmessage-actions,.cmessage-stack:focus-within .cmessage-actions,.cmessage-actions:hover', styles)
        self.assertIn('top:calc(100% - 3px)', styles)
        self.assertIn('.cmsg.user .cmessage-actions{right:0;left:auto}', styles)

    def test_agent_ui_cases_use_native_tools_and_failure_card_has_local_accent(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        cases = source.split("const CONVERSATION_AGENT_TEST_CASES=[", 1)[1].split("];", 1)[0]

        self.assertIn("runteams_request_choice", cases)
        self.assertIn("runteams_propose_automation", cases)
        self.assertNotIn("JSON", cases)
        self.assertNotIn("最终 JSON", cases)
        self.assertNotIn("actions 只能包含", cases)
        self.assertNotIn("不要返回 actions", cases)
        self.assertIn("function conversationFailureCopy(text)", source)
        self.assertIn("function retryFailedConversationMessage(surface,index)", source)
        self.assertIn("retryFailedConversationMessage('${surface}',${index})", source)
        self.assertNotIn('options.retry||"editFailedChat"', source)
        self.assertNotIn('retry:"editFailedConversationPanelMessage"', source)
        self.assertIn('class="cerror-source"', source)
        self.assertIn(".conversation-messages .cerror-title:before", styles)
        self.assertIn(".conversation-messages .cerror-source", styles)

    def test_employee_validation_polling_keeps_one_result_focused_dialog(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        validation = source.split(
            "function coreValidationCaseStats", 1)[1].split(
                "function startCoreEmployeeValidationDesign", 1)[0]

        self.assertIn("host.dataset.validationSignature!==view.signature", validation)
        self.assertIn("body.innerHTML=view.body", validation)
        self.assertIn("clearTimeout(_coreEmployeeValidationTimer)", validation)
        self.assertIn("测试场景", validation)
        self.assertIn("预期", validation)
        self.assertIn("实际", validation)
        self.assertIn("技术详情", validation)
        self.assertNotIn("查看输入输出接口", validation)
        self.assertNotIn("覆盖 ${covers}", validation)
        case_markup = source.split(
            "function coreEmployeeValidationMarkup", 1)[1].split(
                "function coreEmployeeValidationDialogState", 1)[0]
        inline_detail = source.split(
            "function coreEmployeeInlineTrialMarkup", 1)[1].split(
                "function toggleCoreEmployeeTrialDetail", 1)[0]
        dialog_state = source.split(
            "function coreEmployeeValidationDialogState", 1)[1].split(
                "async function openCoreEmployeeValidation", 1)[0]
        dialog_open = source.split(
            "async function openCoreEmployeeValidation", 1)[1].split(
                "async function runAllCoreEmployeeTrials", 1)[0]
        self.assertIn("toggleCoreEmployeeTrialDetail", case_markup)
        self.assertIn('class="env-spinner" aria-hidden="true"', case_markup)
        self.assertIn('action=repairing?', validation)
        self.assertIn(':starting?', validation)
        self.assertIn(':running||revalidating?"":unstable?', validation)
        self.assertIn("core-validation-case-detail", inline_detail)
        self.assertIn("core-trial-report", inline_detail)
        self.assertIn("core-trial-report-flow", inline_detail)
        self.assertIn("core-trial-report-actual", inline_detail)
        self.assertIn("core-trial-rerun", inline_detail)
        self.assertIn('rerun=running||locked?""', inline_detail)
        self.assertIn("coreEmployeeInlineTrialMarkup(trial,item.id,locked)", case_markup)
        self.assertIn("再次运行", inline_detail)
        self.assertNotIn("重新验证", inline_detail)
        self.assertIn('actualStatus=running?""', inline_detail)
        self.assertIn('coreTrialRouteLabel(result.expected_route)', inline_detail)
        self.assertIn('coreTrialRouteLabel(result.actual_route)', inline_detail)
        self.assertNotIn("env-spinner", inline_detail)
        self.assertNotIn('core-trial-rerun" disabled', inline_detail)
        self.assertIn("core-trial-technical", inline_detail)
        self.assertIn("${technical}</div></dl>", inline_detail)
        self.assertNotIn("</dl>${technical}", inline_detail)
        self.assertNotIn("core-validation-case-detail-actions", inline_detail)
        self.assertNotIn("core-trial-result-line", inline_detail)
        self.assertNotIn("core-trial-journey", inline_detail)
        self.assertNotIn("core-validation-expect", case_markup)
        self.assertNotIn("core-validation-actual", case_markup)
        self.assertNotIn("openCoreEmployeeTrialDetail", case_markup)
        self.assertNotIn("replaceChildDialog", inline_detail)
        self.assertNotIn("重新生成用例", dialog_state)
        self.assertIn("AI 自动修复", dialog_state)
        self.assertIn("runCoreEmployeeRepair", dialog_state)
        self.assertIn('repair?.state==="validating"', dialog_state)
        self.assertIn("AI 修复没有完成", dialog_state)
        self.assertIn("候选修复未应用", dialog_state)
        self.assertIn("没有回归", dialog_state)
        self.assertIn("running||revalidating?\"\"", dialog_state)
        self.assertNotIn("重新验证中</button>", dialog_state)
        self.assertIn("并行验证 ${stats.running} 个场景 · 每个", dialog_state)
        self.assertNotIn("正在并行验证 ${stats.running} 个场景，每个场景至少独立运行", dialog_state)
        self.assertIn("_coreEmployeeValidationStarting.has", dialog_state)
        self.assertIn("runAllCoreEmployeeTrials(${employeeId},this)", dialog_state)
        self.assertIn('bodyClass:"mb core-employee-validation-body"', dialog_open)
        self.assertIn("coreEmployeeValidationSkeleton()", dialog_open)
        self.assertIn("sk-validation-footnote", dialog_open)
        self.assertIn('body.innerHTML=view.body', dialog_open)
        self.assertNotIn("utility-loading-modal", dialog_open)
        self.assertNotIn("replaceChildDialog", dialog_open)
        self.assertNotIn("headerActions:coverage.complete", validation)
        self.assertIn("max-height:min(240px,32vh)", styles)
        self.assertIn("overscroll-behavior:contain", styles)
        self.assertIn(
            ".core-trial-technical .core-value{max-height:none;overflow:visible",
            styles,
        )

    def test_inline_ui_handlers_resolve_to_live_frontend_functions(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        definitions = set(re.findall(
            r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", source
        ))
        definitions.update(re.findall(
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
            r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
            source,
        ))
        definitions.update(re.findall(
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
            r"(?:async\s*)?function\b",
            source,
        ))
        ignored = {
            "Array", "Boolean", "Math", "Number", "Object", "String",
            "decodeURIComponent", "encodeURIComponent", "if",
            "requestAnimationFrame", "setTimeout",
        }
        missing = set()
        attributes = re.compile(
            r"\bon(?:click|change|input|keydown|keyup|contextmenu|pointerdown|"
            r"mousedown|scroll|dragstart|dragend|dragover|drop|focus|blur|submit)"
            r"\s*=\s*([\"'`])([\s\S]*?)\1"
        )
        for match in attributes.finditer(source):
            for call in re.finditer(
                r"(?<![.])\b([A-Za-z_$][\w$]*)\s*\(", match.group(2)
            ):
                name = call.group(1)
                if name not in definitions and name not in ignored:
                    missing.add(name)

        self.assertEqual(missing, set(), "unresolved inline UI handlers")

    def test_agent_chat_thinking_copy_has_no_trailing_dots(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")

        self.assertIn('function conversationThinking(label="正在思考",startedAt=Date.now())', source)
        self.assertIn('current:"正在思考"', source)
        self.assertIn('elapsed.seconds>=20', source)
        self.assertIn('setInterval(syncConversationThinkingTimers,1000)', source)
        self.assertIn('.cthinking.is-timed{height:auto;min-height:32px;margin-bottom:8px;padding:0 1px 6px;border-bottom:1px solid var(--line2)}', styles)
        self.assertIn('.agent-work-action.failed{color:var(--msg-text-muted)}', styles)
        self.assertNotIn('class="cthinking-dots"', source)
        self.assertNotIn('.cthinking-dots', styles)

    def test_chat_stream_rewinds_context_but_keeps_product_changes_out_of_scope(self):
        temporary = tempfile.TemporaryDirectory()
        old_db = app.local_database.DB_PATH
        app.local_database.DB_PATH = str(Path(temporary.name) / "runteams.db")
        app.store.init_product_db()
        channel = app.store.get_default_channel()
        cid = app.store.create_chat(channel["id"])
        kept_user = app.store.add_chat_message(cid, "user", "保留的请求")
        kept_bot = app.store.add_chat_message(cid, "bot", "保留的回复")
        target = app.store.add_chat_message(cid, "user", "原请求")
        app.store.add_chat_message(cid, "bot", "旧分支回复")
        app.store.set_chat_runtime(cid, "codex", "thread-old")
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        headers = {"Content-Type": "application/json"}
        try:
            with mock.patch.object(app.chat, "run_chat", return_value={
                    "reply": "新分支回复", "applied": [], "run_cards": [],
            }) as run_chat, mock.patch.object(app.codex_threads, "delete_thread") as delete_thread:
                connection.request("POST", "/api/chat/{}/stream".format(cid), json.dumps({
                    "message": "修改后的请求", "rewind_message_id": target,
                }), headers)
                response = connection.getresponse()
                events = [json.loads(line) for line in response.read().decode("utf-8").splitlines()]

            self.assertEqual(response.status, 200)
            accepted = next(item for item in events if item["type"] == "accepted")
            self.assertIsInstance(accepted["message_id"], int)
            history = run_chat.call_args.args[1]
            runtime = run_chat.call_args.args[2]
            self.assertEqual([item["id"] for item in history], [kept_user, kept_bot])
            self.assertEqual(runtime["runtime_thread_id"], "")
            delete_thread.assert_called_once()
            saved = app.store.get_chat(cid)
            self.assertEqual([item["text"] for item in saved["messages"]], [
                "保留的请求", "保留的回复", "修改后的请求", "新分支回复",
            ])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.local_database.DB_PATH = old_db
            temporary.cleanup()

    def test_chat_stream_persists_agent_tool_trace_for_reload(self):
        temporary = tempfile.TemporaryDirectory()
        old_db = app.local_database.DB_PATH
        app.local_database.DB_PATH = str(Path(temporary.name) / "runteams.db")
        app.store.init_product_db()
        channel = app.store.get_default_channel()
        cid = app.store.create_chat(channel["id"])
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        headers = {"Content-Type": "application/json"}

        def fake_run_chat(_message, _history, _config, *_args, **kwargs):
            sink = kwargs["on_activity"]
            sink.on_event({"kind": "step", "id": "tool-1", "step_kind": "command",
                           "label": "运行 pwd", "status": "running"})
            sink.on_event({"kind": "step", "id": "tool-1", "step_kind": "command",
                           "label": "运行 pwd", "status": "completed",
                           "output": "/tmp/workspace"})
            return {"reply": "检查完成", "applied": [], "run_cards": []}

        try:
            with mock.patch.object(app.chat, "run_chat", side_effect=fake_run_chat):
                connection.request("POST", "/api/chat/{}/stream".format(cid),
                                   json.dumps({"message": "检查目录"}), headers)
                response = connection.getresponse()
                response.read()

            self.assertEqual(response.status, 200)
            saved = app.store.get_chat(cid)["messages"][-1]
            self.assertEqual(saved["text"], "检查完成")
            trace = saved["metadata"]["trace"]
            self.assertTrue(trace["complete"])
            self.assertEqual([item["event"]["kind"] for item in trace["events"]],
                             ["step", "step"])

            source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
                encoding="utf-8")
            self.assertIn("function restoredAgentTrace(metadata)", source)
            self.assertIn("function storedConversationMessage(message)", source)
            self.assertIn(".map(storedConversationMessage)", source)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.local_database.DB_PATH = old_db
            temporary.cleanup()

    def test_native_choice_and_proposal_survive_reload_and_apply(self):
        temporary = tempfile.TemporaryDirectory()
        old_db = app.local_database.DB_PATH
        app.local_database.DB_PATH = str(Path(temporary.name) / "runteams.db")
        app.store.init_product_db()
        channel = app.store.get_default_channel()
        cid = app.store.create_chat(channel["id"])
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        headers = {"Content-Type": "application/json"}
        actions = [{"op": "upsert_automation", "name": "每日复盘",
                    "prompt": "整理今日工作"}]
        replies = [
            {"reply": "请选择检查范围", "options": [
                {"label": "当前流水线", "description": "只检查当前对象"},
                {"label": "全部流水线", "description": "扫描全部对象"},
            ], "applied": [], "run_cards": []},
            {"reply": "自动化方案已准备好", "pending": True,
             "plan": {"count": 1, "actions": actions}, "options": [],
             "applied": [], "run_cards": []},
        ]

        def fake_run_chat(_message, _history, _config, *_args, **kwargs):
            sink = kwargs["on_activity"]
            sink.on_event({"kind": "step", "id": "native-tool", "step_kind": "tool",
                           "label": "整理交互结果", "status": "completed"})
            return replies.pop(0)

        try:
            with mock.patch.object(app.chat, "run_chat", side_effect=fake_run_chat):
                for message in ("请让我选择", "创建每日复盘"):
                    connection.request("POST", "/api/chat/{}/stream".format(cid),
                                       json.dumps({"message": message}), headers)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    response.read()

            reloaded = app.store.get_chat(cid)
            bot_messages = [item for item in reloaded["messages"] if item["role"] == "bot"]
            self.assertEqual([item["label"] for item in
                              bot_messages[0]["metadata"]["options"]],
                             ["当前流水线", "全部流水线"])
            self.assertTrue(bot_messages[1]["metadata"]["pending"])
            self.assertEqual(bot_messages[1]["metadata"]["plan"]["actions"], actions)
            self.assertEqual(bot_messages[1]["metadata"]["trace"]["events"][0]
                             ["event"]["label"], "整理交互结果")

            with mock.patch.object(app.chat, "apply_actions", return_value=(
                    ["已更新自动化「每日复盘」"], [], None)), \
                    mock.patch.object(app.AUTOMATION_SCHEDULER, "wake"):
                connection.request("POST", "/api/chat/{}/apply-plan".format(cid),
                                   json.dumps({"message_id": bot_messages[1]["id"]}), headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()

            applied = app.store.get_chat_message(cid, bot_messages[1]["id"])
            self.assertEqual(applied["metadata"]["plan_resolution"], "applied")
            self.assertNotIn("pending", applied["metadata"])
            self.assertEqual(applied["applied"], ["已更新自动化「每日复盘」"])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.local_database.DB_PATH = old_db
            temporary.cleanup()

    def test_agent_failure_persists_completed_trace_without_interactive_state(self):
        temporary = tempfile.TemporaryDirectory()
        old_db = app.local_database.DB_PATH
        app.local_database.DB_PATH = str(Path(temporary.name) / "runteams.db")
        app.store.init_product_db()
        channel = app.store.get_default_channel()
        cid = app.store.create_chat(channel["id"])
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)

        def failed_run(_message, _history, _config, *_args, **kwargs):
            kwargs["on_activity"].on_event({
                "kind": "step", "id": "read-context", "step_kind": "tool",
                "label": "读取当前上下文", "status": "completed",
            })
            raise RuntimeError("模型连接已中断")

        try:
            with mock.patch.object(app.chat, "run_chat", side_effect=failed_run):
                connection.request("POST", "/api/chat/{}/stream".format(cid),
                                   json.dumps({"message": "检查当前页面"}),
                                   {"Content-Type": "application/json"})
                response = connection.getresponse()
                events = [json.loads(line) for line in
                          response.read().decode("utf-8").splitlines()]

            self.assertEqual(response.status, 200)
            self.assertTrue(any(item["type"] == "error" for item in events))
            saved = app.store.get_chat(cid)["messages"][-1]
            self.assertTrue(saved["metadata"]["failed"])
            self.assertTrue(saved["metadata"]["trace"]["failed"])
            self.assertEqual(saved["metadata"]["trace"]["events"][0]
                             ["event"]["id"], "read-context")
            self.assertNotIn("pending", saved["metadata"])
            self.assertNotIn("options", saved["metadata"])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.local_database.DB_PATH = old_db
            temporary.cleanup()

    def test_chat_stream_persists_ui_test_health_for_reload(self):
        temporary = tempfile.TemporaryDirectory()
        old_db = app.local_database.DB_PATH
        app.local_database.DB_PATH = str(Path(temporary.name) / "runteams.db")
        app.store.init_product_db()
        channel = app.store.get_default_channel()
        cid = app.store.create_chat(channel["id"])
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            with mock.patch.object(app.chat, "run_chat", return_value={
                    "reply": "检查完成", "applied": [], "run_cards": [],
            }):
                connection.request("POST", "/api/chat/{}/stream".format(cid), json.dumps({
                    "message": "这是 Agent Chat 的健康警告 UI 测试", "ui_test_state": "health_warn",
                }), {"Content-Type": "application/json"})
                response = connection.getresponse()
                events = [json.loads(line) for line in response.read().decode("utf-8").splitlines()]

            result = next(item for item in events if item["type"] == "result")
            self.assertEqual(result["health"]["warn"], 1)
            saved = app.store.get_chat(cid)["messages"][-1]
            self.assertEqual(saved["metadata"]["health"], result["health"])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.local_database.DB_PATH = old_db
            temporary.cleanup()

    def test_apply_plan_uses_saved_message_and_persists_applied_state(self):
        temporary = tempfile.TemporaryDirectory()
        old_db = app.local_database.DB_PATH
        app.local_database.DB_PATH = str(Path(temporary.name) / "runteams.db")
        app.store.init_product_db()
        channel = app.store.get_default_channel()
        cid = app.store.create_chat(channel["id"])
        actions = [{"op": "upsert_automation", "name": "状态测试"}]
        message_id = app.store.add_chat_message(
            cid, "bot", "方案已准备好", metadata={
                "trace": {"complete": True},
                "pending": True,
                "plan": {"count": 1, "actions": actions},
            })
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            with mock.patch.object(app.chat, "apply_actions", return_value=(
                    ["已更新自动化「状态测试」"], [], None)) as apply_actions, \
                    mock.patch.object(app.AUTOMATION_SCHEDULER, "wake"):
                connection.request("POST", "/api/chat/{}/apply-plan".format(cid),
                                   json.dumps({"message_id": message_id}),
                                   {"Content-Type": "application/json"})
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertTrue(payload["ok"])
            apply_actions.assert_called_once_with(actions, action_context={
                "chat_id": cid, "conversation_context": {},
            })
            saved = app.store.get_chat_message(cid, message_id)
            self.assertEqual(saved["applied"], ["已更新自动化「状态测试」"])
            self.assertNotIn("pending", saved["metadata"])
            self.assertNotIn("plan", saved["metadata"])
            self.assertEqual(saved["metadata"]["plan_resolution"], "applied")
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.local_database.DB_PATH = old_db
            temporary.cleanup()

    def test_retired_node_detail_is_not_reachable_from_the_renderer(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        render = source.split("function render(){", 1)[1].split("function renderRightWorkspace", 1)[0]
        self.assertNotIn('nodeDetailOpen', render)
        self.assertNotIn('syncNodeWorkerCopyOverflow', render)
        self.assertNotIn('drawer()', render)

    def test_core_pipeline_is_the_default_and_projects_frozen_runs_without_legacy_cards(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")

        self.assertIn('function corePipelineRoute(id,options={}){const base=`/pipelines/${encodeURIComponent(id)}`', source)
        self.assertNotIn('?legacy=1', source)
        self.assertIn('await openCorePipeline(route.id,{route:false})', source)
        render = source.split("function render(){", 1)[1].split("function renderRightWorkspace", 1)[0]
        self.assertIn('S.surface==="core-pipeline"?corePipelineBoard():teamMain()', render)
        self.assertNotIn(':board()', render)
        self.assertIn('function coreWorkflowColumnKey(workflow,positions,states=corePipelineStates())', source)
        self.assertIn(
            'if(workflow.state==="completed")return states.find(state=>state.kind==="done")?.key||"__completed"',
            source,
        )
        self.assertIn('function coreWorkflowDrawer()', source)
        self.assertIn('function coreWorkflowDisplayPositionName(workflow,positions)', source)
        self.assertIn('position?.employee?.name||position?.name||""', source)
        self.assertIn('/^第\\s*\\d+\\s*岗$/.test(name)?"":name', source)
        self.assertNotIn('RUN-${Number(workflow.id)}', source)
        self.assertIn('function corePipelineColumnDrawer()', source)
        self.assertIn('if(S.sel?.type==="core-pipeline-column")return corePipelineColumnDrawer()', source)
        employee_goal = source.split('function coreEmployeeGoal(item){', 1)[1].split(
            'function coreEmployeeCardState', 1
        )[0]
        position_drawer = source.split('function corePipelineColumnDrawer(){', 1)[1].split(
            'function corePipelineEmployeesDrawer', 1
        )[0]
        self.assertIn('program.objective', employee_goal)
        self.assertNotIn('draft.role', employee_goal)
        self.assertIn('还没有设置员工目标', employee_goal)
        self.assertIn('class="sub node-goal-sub"', position_drawer)
        self.assertIn('employeeGoal=String(program.objective||"").trim()', position_drawer)
        save_employee = source.split('async function saveCoreEmployee(id,publish){', 1)[1].split(
            'let _coreEmployeeValidationSequence', 1
        )[0]
        self.assertIn('if(!objective){toast("请填写工作目标"', save_employee)
        self.assertIn('program:{objective,steps:', save_employee)
        self.assertNotIn('||role', save_employee)
        self.assertIn('function coreWorkflowHumanRequest(workflow,runs)', source)
        self.assertIn('workflow.state==="needs_human"', source)
        self.assertIn('/api/core/workflows/${Number(id)}/respond', source)
        self.assertIn('回复已交给员工，任务继续运行', source)
        self.assertIn('openDocumentReader(docFromArtifact(artifact,coreArtifactContext(artifact.id)))', source)
        self.assertIn('function docContentUrl(doc){return doc?.task_input_url||`/api/core/artifacts/${Number(doc.id)}/content`;', source)
        self.assertIn('await api("/api/core/tasks","POST"', source)
        self.assertIn('setInterval(syncCorePipeline,3500)', source)
        self.assertIn('function openCorePipelineEditor(id=0)', source)
        self.assertIn('function moveCorePipelinePosition(index,delta)', source)
        self.assertIn('function saveCorePipeline()', source)
        self.assertIn('const item=await api(`/api/core/pipelines/${state.id}`', source)
        self.assertIn('await api(`/api/core/pipelines/${state.id}`,"POST",{name,definition})', source)
        self.assertIn('const pipelineTree=railOrderedCorePipelines()', source)
        self.assertIn('data-core-pipeline-id="${Number(p.id)}"', source)
        core_task = source.split("async function submitCoreTask()", 1)[1].split(
            "function openCoreWorkflow", 1
        )[0]
        self.assertNotIn('/api/cards', core_task)
        self.assertNotIn('/api/workers', core_task)
        self.assertIn('start_column_key:state.columnKey||null', core_task)
        self.assertIn('payload:{objective:title,parameters:state.parameters||{}}', core_task)
        self.assertNotIn('start_position_key', core_task)
        self.assertIn('function coreInlineTaskComposer()', source)
        self.assertIn('onfocusout="coreInlineTaskComposerFocusout(event)"', source)
        self.assertIn('if(event.key==="Escape")', source)
        self.assertNotIn('className:"core-task-modal"', source)
        self.assertIn('.cols{display:flex;width:max-content;gap:22px;align-items:stretch;height:100%;padding-right:calc(var(--s6) + 190px)}', styles)
        self.assertNotIn('.core-pipeline-board .cols{padding-right:24px}', styles)
        self.assertIn('.core-position-detail-drawer .db{gap:0;padding-top:14px}', styles)
        self.assertIn('.core-position-detail-drawer .node-route-list .csel', styles)
        self.assertIn('background:var(--control-bg);border-color:var(--control-border)', styles)
        self.assertNotIn('.core-position-detail-drawer.column-color-blue', styles)
        self.assertNotIn('.core-node-route-value', styles)
        self.assertIn('.core-position-detail-drawer .node-worker-copy{padding:var(--detail-space-6) 0 20px}', styles)
        self.assertIn('.core-workflow-drawer .db{gap:0;padding-top:14px}', styles)
        self.assertIn('.core-workflow-drawer .card-detail-head+.core-workflow-fact{padding-top:var(--detail-space-6)}', styles)
        self.assertIn('.core-workflow-drawer .core-workflow-section>.lbl{color:var(--detail-text-primary);font-size:var(--detail-section-size);', styles)
        self.assertIn('.core-workflow-drawer .core-attempt>p{color:var(--detail-text-secondary);font-size:var(--detail-content-size);', styles)
        self.assertIn('.core-workflow-drawer .core-attempt{gap:var(--detail-space-4);padding:0 0 var(--detail-space-5);border:0;border-radius:0;background:transparent}', styles)
        self.assertIn('return employee.name||positionDisplayName(position,run.position_key)||"岗位"', source)
        self.assertNotIn('class="core-attempt-index"', source)
        self.assertIn('kind:"core-employee-run",pipelineId:Number(parts[1]),workflowId:Number(parts[3]),runId:Number(parts[5])', source)
        self.assertIn('function coreEmployeeRunDrawer()', source)
        self.assertIn('function coreContextMarkup(value)', source)
        self.assertIn('function coreContextViewItems()', source)
        self.assertIn('function setCoreContextView(value)', source)
        self.assertIn('_coreContextView="friendly"', source)
        self.assertIn('csel("core_context_view",coreContextViewItems(),_coreContextView,setCoreContextView', source)
        self.assertIn('value:"friendly",label:"概览"', source)
        self.assertNotIn('value:"tree",label:"结构化"', source)
        self.assertNotIn('function coreContextTreeMarkup', source)
        self.assertIn('function copyCoreContextJson()', source)
        self.assertIn('function coreJsonViewerMarkup(value,key,options={})', source)
        self.assertIn('function setCoreJsonViewerMode(id,value)', source)
        self.assertIn('function copyCoreJsonViewer(id)', source)
        self.assertIn('coreJsonViewerMarkup(run.input_json||{},`run-input-', source)
        self.assertIn('coreJsonViewerMarkup(run.output_json||{},`run-output-', source)
        self.assertIn('coreJsonViewerMarkup(workOrder,`trial-input-', source)
        self.assertIn('coreJsonViewerMarkup(employeeInterface.input||{},`validation-input-', source)
        self.assertIn('coreJsonViewerMarkup(employeeInterface.output||{},`validation-output-', source)
        self.assertIn('coreJsonViewerMarkup(context,`human-context-', source)
        self.assertIn('function documentJsonMarkup(text,key)', source)
        self.assertIn('coreJsonViewerMarkup(JSON.parse(text),key', source)
        self.assertNotIn('JSON.stringify(context,null,2)', source)
        self.assertIn('class="core-context-copy"', source)
        self.assertIn('core-context-section-head', source)
        self.assertIn('原始 JSON', source)
        self.assertIn('class="core-context-section-head"', source)
        self.assertIn('coreContextMarkup(payload.context)', source)
        self.assertIn('class="row run-history clickable core-run-overview"', source)
        self.assertIn('coreEmployeeRunHistory(runs,positions,workflow.id)', source)
        self.assertIn('<div class="lbl">工作记录</div>', source)
        self.assertNotIn('<div class="lbl">员工工作记录</div>', source)
        self.assertIn('function coreEmployeeRunProgress(run)', source)
        self.assertIn('drawerKey:selKey', source)
        self.assertIn('s.drawerKey===selKey?captureRightWorkspacePosition():null', source)
        self.assertIn('else s.drawerKey=selKey', source)
        self.assertIn('class="run-progress-heading"', source)
        self.assertIn('class="run-progress-title"', source)
        self.assertIn('class="run-row-time"', source)
        self.assertIn('CORE_EMPLOYEE_PROGRESS_TOOLS', source)
        self.assertIn('function coreEmployeeEventShowsInProgress(event,runState)', source)
        self.assertIn('if(status==="failed")return runState!=="completed"', source)
        self.assertIn('这次运行没有保存关键进展，可在原始记录中查看完整信息。', source)
        self.assertIn('coreEmployeeRunProgress(run)', source)
        self.assertIn('function coreEmployeeCommandDetail(data)', source)
        self.assertIn('output.work_order?.objective', source)
        self.assertIn('result.tool_id||argumentsData.capability_ref', source)
        self.assertIn('artifact.name),coreEmployeeEventText(artifact.path)', source)
        self.assertIn('argumentsData.summary', source)
        self.assertIn('"此步骤没有记录详情"', source)
        self.assertNotIn('return "已读取工作目标、背景信息和验收标准"', source)
        self.assertNotIn('return "已定位完成工作所需的项目说明、员工技能和文件"', source)
        self.assertIn('aria-label="返回任务概览"', source)
        self.assertIn('.core-workflow-drawer .card-run-section .core-run-overview{position:relative;width:calc(100% + 16px);', styles)
        self.assertIn('function coreContextOverviewMarkup(value)', source)
        self.assertIn('function coreContextOverviewValue(value)', source)
        self.assertIn('function coreContextKeyLabel(key)', source)
        self.assertNotIn('function coreContextOverviewMeasure(value)', source)
        self.assertNotIn('function coreContextOverviewIsShort(value)', source)
        self.assertNotIn('function coreContextOverviewArrayIsInline(value)', source)
        self.assertIn('function coreContextOverviewRows(value,path="")', source)
        self.assertIn('function coreContextOverviewPath(path,key)', source)
        self.assertIn('class="core-context-table-wrap"', source)
        self.assertIn('<table class="core-context-table">', source)
        self.assertIn('<th scope="col">字段</th><th scope="col">值</th>', source)
        self.assertNotIn('data-depth', source)
        self.assertNotIn('coreContextOverviewIndent', source)
        self.assertNotIn('function coreContextRows', source)
        self.assertNotIn('function coreContextUrl', source)
        self.assertNotIn('function coreContextFriendlyMarkup', source)
        self.assertNotIn('core-context-semantic', source)
        self.assertNotIn('core-context-group', source)
        self.assertNotIn('core-context-links', source)
        self.assertNotIn('core-context-badge', source)
        self.assertIn('.core-workflow-drawer .core-context-table-wrap,.core-json-viewer .core-context-table-wrap{max-width:100%;', styles)
        self.assertIn('overflow-x:clip;border:1px solid var(--line)', styles)
        self.assertIn('border:1px solid var(--line);border-radius:var(--detail-control-radius)', styles)
        self.assertIn('.core-workflow-drawer .core-context-table,.core-json-viewer .core-context-table{width:100%;', styles)
        self.assertIn('.core-workflow-drawer .core-context-table thead,.core-json-viewer .core-context-table thead{border-bottom:1px solid var(--line);background:var(--rail)}', styles)
        self.assertIn('background:var(--rail)', styles)
        self.assertIn('.core-workflow-drawer .core-context-table tbody tr:hover,.core-json-viewer .core-context-table tbody tr:hover{background:var(--hover)}', styles)
        self.assertNotIn('.core-workflow-drawer .core-context-group{', styles)
        self.assertNotIn('.core-workflow-drawer .core-context-extra{', styles)
        self.assertIn('.core-workflow-drawer .core-context-copy{position:absolute;', styles)
        self.assertIn('.core-workflow-drawer #core_context_view.csel{width:max-content;min-width:0;', styles)
        self.assertIn('.core-json-viewer{display:grid;min-width:0;', styles)
        self.assertIn('.core-json-viewer .csel{width:max-content;min-width:0;', styles)
        self.assertIn('.core-json-copy{position:absolute;', styles)
        self.assertNotIn('core-json-disclosure', styles)
        self.assertIn('.core-run-detail-drawer .run-event-panel{display:flex;', styles)
        self.assertIn('.core-run-detail-drawer .core-run-result-summary{display:grid;grid-template-columns:15px minmax(0,1fr);align-items:start;gap:var(--detail-space-1) var(--detail-space-2);padding:0;border:0;border-radius:0;background:transparent}', styles)
        self.assertIn('.core-run-detail-drawer .core-run-result-summary>div{display:contents}', styles)
        self.assertIn('.core-run-detail-drawer .core-run-result-summary p{grid-column:1 / -1;grid-row:2;', styles)
        self.assertIn('.core-run-detail-drawer .run-progress-heading{display:flex;min-width:0;align-items:center;gap:var(--detail-space-2)}', styles)
        self.assertIn('.core-run-detail-drawer .run-progress-detail{display:block;margin-top:var(--detail-space-1);', styles)
        self.assertIn('.core-run-detail-drawer .core-artifact{position:relative;width:calc(100% + 16px);display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:var(--detail-space-4);margin:0 -8px;padding:var(--detail-space-2) 8px;border:0;border-radius:0;background:transparent;isolation:isolate}', styles)
        self.assertIn('.core-run-detail-drawer .core-artifact+.core-artifact{border-top:0}', styles)
        self.assertIn('.core-run-detail-drawer .core-run-progress-section{margin-top:calc(-1 * var(--detail-space-6));padding-top:var(--detail-space-4);border-top:0}', styles)
        self.assertIn('.core-position-row{display:grid;', styles)

    def test_credentials_are_user_created_ordered_and_flat(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        backend = (root / "app.py").read_text(encoding="utf-8")
        storage = (root / "product_store.py").read_text(encoding="utf-8")

        self.assertIn("function openCredentialDialog(", source)
        credential_dialog = source.split("function openCredentialDialog()", 1)[1].split("async function saveNewCredential", 1)[0]
        self.assertIn("openChildDialog(", credential_dialog)
        self.assertIn('onclick="closeChildDialog()"', credential_dialog)
        self.assertNotIn("openDialog(", credential_dialog)
        self.assertIn("function credentialPointerDown(", source)
        self.assertIn("function saveVaultChanges(", source)
        self.assertIn("'/api/credentials/reorder'", source)
        self.assertIn("'/api/credentials/values'", source)
        self.assertIn("'/api/credential'", source)
        self.assertIn("填写凭据 Key 和对应值", source)
        self.assertIn("{label:'替换',icon:'edit'", source)
        self.assertIn("oncontextmenu=\"event.preventDefault();event.stopPropagation();vaultCredentialMenu", source)
        self.assertIn("openMenu(event.currentTarget,items,{variant:'credentialAction'", source)
        self.assertIn('class="inp mono credential-inline-input" type="${kind===\'text\'?\'text\':\'password\'}"', source)
        self.assertIn('class="credential-file-input" type="file"', source)
        self.assertIn("async function credentialFileSelected(", source)
        self.assertIn('.credential-inline-input{width:100%!important;height:32px!important;padding:0!important;border:0!important', styles)
        self.assertIn('text-align:right!important;box-shadow:none!important', styles)
        self.assertIn('.credential-inline-input::placeholder{', styles)
        self.assertIn('onblur="vaultCredentialBlur(this)"', source)
        self.assertIn('function vaultCredentialBlur(', source)
        self.assertIn('onpointerdown="credentialPagePointerDown(event)"', source)
        self.assertIn('function credentialPagePointerDown(', source)
        self.assertNotIn('<span class="vault-key-icon">', source)
        self.assertNotIn('<small>${esc(usage)}</small>', source)
        self.assertNotIn('>替换</button>', source)
        self.assertNotIn('class="iconbtn vault-more"', source)
        self.assertNotIn('class="inp mono vault-textarea"', source)
        self.assertNotIn('<textarea class="ta mono credential-value-input"', source)
        self.assertNotIn("credential-group", source + backend)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS credential_groups(", storage)
        self.assertNotIn("group_id", source)
        self.assertNotIn("credentialDefinition", source)
        self.assertNotIn("任务凭据", source)
        self.assertIn('CREATE TABLE IF NOT EXISTS credential_entries(', storage)
        self.assertIn('if p == "/api/credentials/reorder":', backend)
        self.assertIn('if p == "/api/credential":', backend)

    def test_second_desktop_instance_never_recovers_live_runs_before_bind(self):
        with mock.patch.object(app.sys, "argv", ["runteams-server"]), \
                mock.patch.object(app.store, "init_product_db"), \
                mock.patch.object(app, "Server", side_effect=OSError("address in use")):
            with self.assertRaisesRegex(OSError, "address in use"):
                app.main()

    def test_core_mcp_entry_never_runs_desktop_recovery_or_scheduler(self):
        with mock.patch.object(
                app.sys, "argv",
                ["runteams-server", "--runteams-core-mcp", "/tmp/core.db", "42", "/tmp/work"]), \
                mock.patch("runteams_core.protocol.main") as protocol_main, \
                mock.patch.object(app.store, "init_product_db") as init_db:
            app.main()

        protocol_main.assert_called_once_with(
            "/tmp/core.db", 42, "/tmp/work",
            credential_resolver=app.app_secrets.resolve)
        init_db.assert_not_called()

    def test_desktop_startup_excludes_retired_card_scheduler(self):
        source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
        main = source.split("def main():", 1)[1]
        self.assertNotIn("store.recover_interrupted_runs()", main)
        self.assertNotIn("store.recover_interrupted_maintenance_jobs()", main)
        self.assertNotIn("DurableScheduler", source)
        self.assertNotIn("\nSCHEDULER =", source)
        self.assertNotIn("TASK_TOOLS", source)
        self.assertIn("store.init_product_db()", main)
        self.assertIn("core_controller().start()", main)
        self.assertIn("AUTOMATION_SCHEDULER.start()", main)

    def test_channel_modal_reuses_warmed_state_without_forced_refresh(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        start = source.index("async function openChannels()")
        end = source.index("function closeChannels()", start)
        body = source[start:end]
        self.assertIn("syncChannelsFromEnvironment(S.environment)", body)
        self.assertIn("channelStateStale()", body)
        self.assertNotIn("capabilities?refresh=1", body)
        self.assertNotIn("refreshModelCatalog(true)", body)
        channel_cards = source.split("function renderChannels(loading)", 1)[1].split(
            "function openChannelLogin", 1
        )[0]
        self.assertNotIn('<div class="channel-state ${ready?\'ready\':\'warn\'}"><span></span>', channel_cards)

    def test_channel_login_detection_survives_terminal_and_modal_switches(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        poll = source.split("async function pollChannelLogin(id){", 1)[1].split(
            "async function removeChannel", 1
        )[0]
        open_channels = source.split("async function openChannels(){", 1)[1].split(
            "function closeChannels", 1
        )[0]

        self.assertIn("c.loginPending=true", source)
        self.assertIn("if(r.requires_login){c.loginPending=true;c.connecting=false", source)
        self.assertIn("refreshOpenChannelStatuses();", open_channels)
        self.assertIn("for(let i=0;i<150&&c.loginPending;i++)", poll)
        self.assertIn("probeChannelLoginState(id)", poll)
        loop_condition = poll.split("for(let i=0;", 1)[1].split("){", 1)[0]
        self.assertNotIn("channel_list", loop_condition)
        self.assertIn('window.addEventListener("focus",()=>{refreshPendingChannelLogins();', source)
        self.assertIn("if(ready){c.connecting=false;c.loginPending=false;}else if(!c.loginPending)c.connecting=false;", source)

    def test_channel_api_cannot_create_hidden_cli_profile_overrides(self):
        source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
        route = source.split('if p == "/api/channels":', 2)[2].split(
            're.match(r"^/api/channel/', 1
        )[0]

        self.assertIn('"name": info["channel_name"]', route)
        self.assertIn('"executable": ""', route)
        self.assertIn('"config_dir": ""', route)
        self.assertNotIn('d.get("executable")', route)
        self.assertNotIn('d.get("config_dir")', route)

    def test_channel_connect_never_launches_a_terminal(self):
        app_source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
        channel_source = (Path(__file__).parents[1] / "model_channels.py").read_text(encoding="utf-8")
        frontend = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        route = app_source.split('re.match(r"^/api/channel/(\\d+)/connect$", p)', 1)[1].split(
            're.match(r"^/api/channel/(\\d+)/remove$", p)', 1
        )[0]

        self.assertIn('"requires_login": bool(', route)
        self.assertNotIn("launch_login", route)
        self.assertNotIn("def launch_login(", channel_source)
        self.assertIn("请在你自己的终端登录", frontend)
        self.assertIn("copyChannelLoginCommand", frontend)
        self.assertIn("checkChannelLogin", frontend)
        self.assertNotIn("已打开终端", frontend)

    def test_removing_channel_updates_environment_status_without_page_refresh(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        remove_body = source.split("async function removeChannel(id)", 1)[1].split(
            "// 拖动重排流水线", 1
        )[0]
        self.assertIn("markEnvironmentChannelDisconnected(id)", remove_body)
        self.assertIn("panels.forEach(normalizeConversationModelConfig);render()", remove_body)
        self.assertIn("refreshEnvironmentAfterChannelChange()", remove_body)
        self.assertIn('row.ready=false;row.status="disabled"', source)

    def test_model_controls_use_cached_catalog_instead_of_flashing_unknown_values(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        self.assertIn('const MODEL_CATALOG_SNAPSHOT_KEY=', source)
        self.assertIn('function loadModelCatalogSnapshot()', source)
        self.assertIn('function saveModelCatalogSnapshot(channels)', source)
        self.assertIn('modelCatalog:MODEL_CATALOG_SNAPSHOT,modelCatalogReady:MODEL_CATALOG_SNAPSHOT.length>0', source)
        self.assertIn('finally{S.modelCatalogReady=true;}', source)
        self.assertIn('if(!S.modelCatalogReady)return modelControlLoading("model")', source)
        self.assertIn('if(!S.modelCatalogReady)return modelControlLoading("effort")', source)
        self.assertIn('.copt .csel.model-control-loading{', styles)

    def test_persistent_runtime_configs_never_silently_fallback_models(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        self.assertIn('function persistentAgentWarningMarkup(channelId,model,detail)', source)
        self.assertIn('该自动化会保留原模型配置，不会自动切换', source)
        self.assertIn('运行时会冻结每名员工的当前发布版本', source)
        self.assertIn('runtime=_coreEmployeeEditor?.runtime||{channel:"codex",model:"",effort:"low"}', source)
        self.assertIn('api(`/api/core/employees/${id}/publish`,"POST",{})', source)
        self.assertNotIn('发布前自查已开始', source)
        self.assertIn('保存草稿</button>', source)
        self.assertNotIn('验证并发布</button>', source)
        self.assertIn('onclick="saveCoreEmployee(${Number(id)||0},true)">发布</button>', source)
        self.assertNotIn('员工已定稿，正在准备发布验证', source)
        self.assertIn('hasStoredRoute=item.channel_id!=null&&!!item.model', source)
        self.assertIn('modelCsel("automation_route",workerModelItems(item.channel_id,item.model),routeValue,automationRouteChanged)', source)
        self.assertIn('function automationHasModels(item)', source)
        self.assertNotIn('_automationEditor.model=effectiveModelValue', source)
        self.assertIn('function workerRouteValue(channelId,model){return channelId!=null?String(channelId)+"::"+(model||"")', source)
        self.assertIn('modelChannelAvailable(c)||String(c.id)===String(channelId)', source)
        self.assertIn('{label:"模型不可用",kind:"blocked"}', source)
        self.assertIn('员工和自动化不会自动换模型', source)
        self.assertIn('.persistent-agent-warning{display:grid;', styles)

    def test_conversation_creation_has_one_endpoint_for_general_and_scoped_modes(self):
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        headers = {"Content-Type": "application/json"}
        try:
            general = {"id": 71, "kind": "general", "messages": [], "context": {}}
            with mock.patch.object(app.store, "get_channel", return_value={"id": 3, "enabled": 1}), \
                    mock.patch.object(app, "_core_pipeline_exists", return_value=True) as pipeline_exists, \
                    mock.patch.object(app.model_channels, "normalize_selection", return_value=("gpt-test", "low")), \
                    mock.patch.object(app.store, "create_chat", return_value=71) as create_chat, \
                    mock.patch.object(app.store, "get_chat", return_value=general):
                connection.request("POST", "/api/conversations", json.dumps({
                    "kind": "general", "channel_id": 3, "model": "gpt-test",
                    "reasoning_effort": "low", "scope_pipeline_id": 9,
                }), headers)
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["session"]["id"], 71)
            create_chat.assert_called_once_with(
                3, "gpt-test", "low", 9, False, context=None)
            pipeline_exists.assert_called_once_with(9)

            for retired in (
                    {"kind": "worker_design", "runtime": {"channel_id": 3},
                     "pipeline_id": 9, "node_id": 4},
                    {"kind": "card_instruction", "runtime": {"channel_id": 3},
                     "pipeline_id": 9, "card_id": 4},
                    {"kind": "skill_design", "runtime": {"channel_id": 3},
                     "skill_id": 4}):
                connection.request("POST", "/api/conversations", json.dumps(retired), headers)
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 400)
                self.assertEqual(payload["error"], "不支持的会话类型")

            core_employee = {"id": 73, "kind": app.employee_sessions.SESSION_KIND,
                             "messages": [], "context": {"target_employee_id": 12}}
            with mock.patch.object(app.employee_sessions, "create_session",
                                   return_value=core_employee) as create_core_employee:
                connection.request("POST", "/api/conversations", json.dumps({
                    "kind": "employee_design", "runtime": {"channel_id": 3},
                    "employee_id": 12,
                }), headers)
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["session"]["id"], 73)
            create_core_employee.assert_called_once_with(
                {"channel_id": 3}, 12, "design")

            connection.request("POST", "/api/agent-sessions", b"{}", headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 404)
            response.read()
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_scoped_conversation_draft_actions_do_not_create_user_messages(self):
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        headers = {"Content-Type": "application/json"}
        applied = {"ok": True, "reply": "已更新岗位「核查员」。", "draft": {"name": "核查员"},
                   "draft_ready": False, "status": "applied", "applied": ["已更新岗位「核查员」"]}
        try:
            core_session = {"id": 7, "kind": app.employee_sessions.SESSION_KIND,
                            "context": {"target_employee_id": 12}}
            with mock.patch.object(app.store, "get_chat", return_value=core_session), \
                    mock.patch.object(app.employee_sessions, "apply_ready_draft", return_value=applied) as apply_draft, \
                    mock.patch.object(app.store, "add_chat_message") as add_message:
                connection.request("POST", "/api/chat/7/draft-action",
                                   json.dumps({"action": "apply", "draft": {"name": "核查员"}}), headers)
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["status"], "applied")
            apply_draft.assert_called_once_with(7, {"name": "核查员"})
            add_message.assert_called_once_with(7, "bot", applied["reply"], applied["applied"])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_retired_workspace_hosting_files_and_ui_are_absent(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        backend = (root / "app.py").read_text(encoding="utf-8")
        self.assertFalse((root / "workspaces.py").exists())
        self.assertFalse((root / "work_locations.py").exists())
        self.assertFalse((root / "store.py").exists())
        self.assertNotIn("RunTeams.ai 托管", source)
        self.assertNotIn("function openWorkspace()", source)
        self.assertNotIn("cardWorkspacePanel", source)
        self.assertNotIn("/api/pipeline/{}/workspace", backend)

    def test_transient_menus_close_when_context_moves_elsewhere(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        menu = source.split("function popMenu(anchor, items, variant, opts){", 1)[1].split(
            "// 自定义下拉", 1
        )[0]
        dialogs = source.split("function openModal(html){", 1)[1].split(
            "function confirmModal", 1
        )[0]

        self.assertIn(
            'document.addEventListener("pointerdown",popMenuOutsidePointer,true)',
            menu,
        )
        self.assertNotIn('document.addEventListener("click",closePop)', menu)
        self.assertIn("function popMenuOwnsTarget(target)", menu)
        self.assertIn("_popAnchor?.contains(target)", menu)
        self.assertIn("_coreColumnGroupEditor?.contains(target)", menu)
        self.assertIn("_coreColumnGroupSortMenu?.contains(target)", menu)
        self.assertIn("_coreWorkflowMoveMenu?.contains(target)", menu)
        self.assertIn("if(_coreColumnGroupEditor)closeCoreColumnGroupEditor()", menu)
        self.assertIn("if(_coreWorkflowMoveMenu)closeCoreWorkflowMoveMenu()", menu)
        self.assertIn("function closeTransientMenus(){closePop();}", menu)
        self.assertIn("closeTransientMenus();const host=document.getElementById", dialogs)
        self.assertIn("closeChildDialog();\n  closeTransientMenus();", dialogs)
        self.assertIn("function replaceChildDialog(opts){closeTransientMenus();", dialogs)
        self.assertIn("function closeModal(){\n  closeChildDialog();\n  closeTransientMenus();", dialogs)
        self.assertIn(
            "function openCorePipelineColumn(columnType,key){closeTransientMenus();",
            source,
        )
        self.assertIn("function toggleCorePipelinePanel(type){closeTransientMenus();", source)
        self.assertIn("function openCoreWorkflow(id){closeTransientMenus();", source)

    def test_route_classifier_accepts_product_pages(self):
        accepted = [
            "/chat/new",
            "/chat/42",
            "/pipelines/new",
            "/pipelines/7",
            "/pipelines/7/",
            "/pipelines/7/workflows/42/runs/99",
            "/pipelines/7/workflows/42/runs/99/",
            "/automations",
            "/design-system",
            "/trash",
            "/extensions",
            "/extensions/local",
            "/extensions/packages",
            "/extensions/package/1",
            "/extensions/package/core/12",
            "/extensions/plugin/1/google-drive",
            "/extensions/skill/2/my%20skill",
            "/skills",
            "/skills/12",
        ]
        for path in accepted:
            with self.subTest(path=path):
                self.assertTrue(app.is_spa_route(path))

    def test_core_tasks_restore_managed_input_materials(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "index.html").read_text(encoding="utf-8")
        styles = (root / "web" / "runteams.css").read_text(encoding="utf-8")
        backend = (root / "core_api.py").read_text(encoding="utf-8")

        self.assertIn("function pickCoreTaskInputs(event)", source)
        self.assertIn("input_tokens:(state.materials||[])", source)
        self.assertIn("function coreWorkflowTaskInputPanel(workflow,payload)", source)
        self.assertIn("文件会复制到任务中，原文件不受影响", source)
        self.assertNotIn("formatBytes(", source)
        self.assertIn("function coreTaskInputSize(item)", source)
        self.assertIn("formatFileSize(coreTaskInputSize(item))", source)
        self.assertNotIn('if(!items.length&&!editable)return ""', source)
        self.assertIn("function coreWorkflowTaskEditorInputs(workflow)", source)
        self.assertIn('id="core_task_edit_inputs"', source)
        self.assertIn("function addCoreWorkflowTaskInputs(event,workflowId)", source)
        self.assertIn("function removeCoreWorkflowTaskInput(event,workflowId,inputId)", source)
        self.assertIn("coreWorkflowTaskInputPanel(workflow,payload)", source)
        self.assertIn(".inline-task-inputs{display:flex;flex-wrap:wrap", styles)
        self.assertIn(".core-task-edit-modal .task-edit-inputs{", styles)
        self.assertIn('class="card-detail-section card-input-section', source)
        self.assertIn('action=items.length?', source)
        self.assertIn('card-input-section${items.length?"":" is-empty"}', source)
        self.assertIn('<span>附件</span>', source)
        self.assertIn('>添加附件</button>', source)
        self.assertIn('class="card-input-item core-artifact core-file-row"', source)
        self.assertIn('class="card-input-main core-artifact-main"', source)
        self.assertIn('class="card-input-actions core-artifact-actions"', source)
        self.assertNotIn(".core-workflow-drawer .core-task-input-section{", styles)
        self.assertIn("任务输入与交付文件共享同一套平铺文件行", styles)
        self.assertIn(".core-workflow-drawer .card-input-item,.core-workflow-drawer .core-artifact{position:relative;width:calc(100% + 16px);min-width:0;min-height:42px;", styles)
        self.assertIn('.core-workflow-drawer .core-file-row[data-removable="true"]{grid-template-columns:minmax(0,1fr) auto auto}', styles)
        self.assertIn(".core-workflow-drawer .card-input-empty{display:flex;align-items:center;gap:10px;padding:11px 12px;border:1px dashed var(--line2);", styles)
        self.assertIn(".core-workflow-drawer .card-input-section+.core-workflow-history{margin-top:var(--detail-space-5)}", styles)
        self.assertIn('r"^/api/core/workflows/(\\d+)/inputs$"', backend)
        self.assertIn("data.get(\"input_tokens\") or []", backend)

    def test_route_classifier_rejects_api_and_unknown_paths(self):
        rejected = ["/api/pipelines", "/chat/nope", "/pipelines/nope", "/skills/nope", "/unknown"]
        for path in rejected:
            with self.subTest(path=path):
                self.assertFalse(app.is_spa_route(path))

    def test_deep_link_serves_app_shell_and_unknown_path_404s(self):
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            connection.request("GET", "/pipelines/1?view=flow")
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn('<div class="app" id="app">', body)
            self.assertIn('class="body boot-body"', body)
            connection.request("GET", "/pipelines/new")
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn('<div class="app" id="app">', body)
            connection.request("GET", "/pipelines/7/workflows/42/runs/99?view=flow")
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn('<div class="app" id="app">', body)
            self.assertIn('class="body boot-body"', body)
            connection.request("GET", "/not-a-product-route")
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 404)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

if __name__ == "__main__":
    unittest.main()
