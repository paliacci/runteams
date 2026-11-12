import AppKit
import WebKit
import Darwin

final class LibraryWindowLock {
    private var descriptor: Int32 = -1
    init(directory: String) throws {
        let manager = FileManager.default
        let folder = URL(fileURLWithPath: directory).appendingPathComponent("community-desktop")
        if (try? folder.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) == true { throw CommunityBootstrap.Failure.invalid }
        try manager.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let path = folder.appendingPathComponent("window.lock").path
        descriptor = Darwin.open(path, O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { throw CommunityBootstrap.Failure.invalid }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_uid == getuid(), info.st_mode & S_IFMT == S_IFREG else { throw CommunityBootstrap.Failure.invalid }
        if flock(descriptor, LOCK_EX | LOCK_NB) != 0 {
            var buffer = [UInt8](repeating: 0, count: 4096)
            let count = pread(descriptor, &buffer, buffer.count, 0)
            if count > 0, let object = try? JSONSerialization.jsonObject(with: Data(buffer.prefix(count))) as? [String: Any],
               let pid = object["pid"] as? Int32, let existing = NSRunningApplication(processIdentifier: pid),
               existing.bundleIdentifier == "ai.runteams.community" { existing.activate(options: [.activateIgnoringOtherApps]) }
            throw AlreadyOpen()
        }
        let data = try JSONSerialization.data(withJSONObject: ["schema":"runteams.community-window/1", "pid":getpid()])
        guard ftruncate(descriptor, 0) == 0 else { throw CommunityBootstrap.Failure.invalid }
        let count = data.withUnsafeBytes { Darwin.write(descriptor, $0.baseAddress, $0.count) }
        guard count == data.count else { throw CommunityBootstrap.Failure.invalid }
        fsync(descriptor)
    }
    deinit { if descriptor >= 0 { flock(descriptor, LOCK_UN); Darwin.close(descriptor) } }
    struct AlreadyOpen: Error {}
}

final class CommunityApp: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate, WKScriptMessageHandlerWithReply {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var bootstrap: CommunityBootstrap!
    private var arguments: CommunityArguments!
    private var windowLock: LibraryWindowLock?
    private var process: Process?
    private var ownerPipe: Pipe?
    private var origin: URL?
    private var employeeDesktop: CreatorDesktopHost?
    private var generation = UUID()
    private var pageReady = false
    private var serviceReady = false
    private var checkingClose = false
    private var quitting = false
    private var failurePresented = false
    private var loading: NSView!
    private var downloads: [ObjectIdentifier: WKDownload] = [:]

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            bootstrap = try CommunityBootstrap.read()
            arguments = try CommunityArguments(Array(CommandLine.arguments.dropFirst()), bootstrap: bootstrap)
            windowLock = try LibraryWindowLock(directory: arguments.dataDirectory)
        } catch is LibraryWindowLock.AlreadyOpen { NSApp.terminate(nil); return }
        catch {
            let alert = NSAlert(); alert.messageText = localized("无法打开 RunTeams 本机版","Couldn’t Open RunTeams Local")
            alert.informativeText = localized("无法完成启动。请检查本机资料库和应用安装是否可用。","Check that the local library and the app installation are available.")
            alert.addButton(withTitle: localized("退出","Quit")); alert.runModal(); NSApp.terminate(nil); return
        }
        makeMenu()
        window = NSWindow(contentRect: NSRect(x:0,y:0,width:1120,height:760),
            styleMask:[.titled,.closable,.miniaturizable,.resizable,.fullSizeContentView], backing:.buffered, defer:false)
        window.title = localized("RunTeams 本机版","RunTeams Local"); window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true; window.titlebarSeparatorStyle = .none
        window.minSize = NSSize(width:780,height:560); window.delegate = self
        window.isReleasedWhenClosed = false; window.center()
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.addScriptMessageHandler(self,contentWorld:.page,name:"runteamsCreatorWork")
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.addScriptMessageHandler(self,contentWorld:.page,name:"runteamsLanguage")
        updateLanguageSeed(configuration.userContentController)
        let nativeStyle = "const apply=()=>document.documentElement?.setAttribute('data-native','');if(document.documentElement)apply();else{const o=new MutationObserver(()=>{if(document.documentElement){apply();o.disconnect()}});o.observe(document,{childList:true,subtree:true})}"
        configuration.userContentController.addUserScript(WKUserScript(source:nativeStyle, injectionTime:.atDocumentStart, forMainFrameOnly:true))
        let content = NSView(frame:NSRect(x:0,y:0,width:1120,height:760))
        webView = WKWebView(frame:content.bounds, configuration:configuration)
        webView.navigationDelegate = self; webView.uiDelegate = self
        webView.autoresizingMask = [.width,.height]; content.addSubview(webView); window.contentView = content
        loading = NSView(frame:content.bounds); loading.autoresizingMask = [.width,.height]
        loading.wantsLayer = true; loading.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        let spinner = NSProgressIndicator(); spinner.style = .spinning; spinner.startAnimation(nil)
        let text = NSTextField(labelWithString:localized("正在打开本机资料库…","Opening the local library…")); text.font = .systemFont(ofSize:13); text.textColor = .secondaryLabelColor
        let stack = NSStackView(views:[spinner,text]); stack.orientation = .vertical; stack.spacing = 12; stack.translatesAutoresizingMaskIntoConstraints = false
        loading.addSubview(stack); content.addSubview(loading)
        NSLayoutConstraint.activate([stack.centerXAnchor.constraint(equalTo:loading.centerXAnchor), stack.centerYAnchor.constraint(equalTo:loading.centerYAnchor)])
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true)
        startService()
    }

    private func updateLanguageSeed(_ controller: WKUserContentController) {
        let prefix = "window.runteamsNativeLanguage = "
        let scripts = controller.userScripts.filter { !$0.source.hasPrefix(prefix) }
        controller.removeAllUserScripts()
        controller.addUserScript(WKUserScript(
            source: "\(prefix)'\(languagePreference)'", injectionTime: .atDocumentStart, forMainFrameOnly: true
        ))
        scripts.forEach { controller.addUserScript($0) }
    }

    private var languagePreference: String {
        let saved = UserDefaults.standard.string(forKey:"runteams_language_preference")
        return saved.flatMap { ["system","zh-CN","en"].contains($0) ? $0 : nil } ?? "system"
    }

    private func localized(_ chinese: String, _ english: String) -> String {
        switch languagePreference {
        case "zh-CN": return chinese
        case "en": return english
        default:
            for language in Locale.preferredLanguages {
                switch language.split(separator:"-").first?.lowercased() {
                case "zh": return chinese
                case "en": return english
                default: continue
                }
            }
            return english
        }
    }

    private func makeMenu() {
        let menu = NSMenu(); let appItem = NSMenuItem(); menu.addItem(appItem)
        let app = NSMenu(); appItem.submenu = app
        app.addItem(withTitle:localized("退出 RunTeams 本机版","Quit RunTeams Local"), action:#selector(NSApplication.terminate(_:)), keyEquivalent:"q")
        let fileItem = NSMenuItem(); menu.addItem(fileItem); let file = NSMenu(title:localized("文件","File")); fileItem.submenu = file
        file.addItem(withTitle:localized("关闭窗口","Close Window"), action:#selector(NSWindow.performClose(_:)), keyEquivalent:"w")
        let editItem = NSMenuItem(); menu.addItem(editItem); let edit = NSMenu(title:localized("编辑","Edit")); editItem.submenu = edit
        for (chinese, english, action, key) in [("撤销","Undo","undo:","z"),("剪切","Cut","cut:","x"),("复制","Copy","copy:","c"),("粘贴","Paste","paste:","v"),("全选","Select All","selectAll:","a")] {
            edit.addItem(withTitle:localized(chinese,english), action:Selector(action), keyEquivalent:key)
        }
        NSApp.mainMenu = menu
    }

    private func startService() {
        guard process?.isRunning != true, !quitting else { return }
        serviceReady = false; generation = UUID(); let current = generation
        let child = Process(); let stdout = Pipe(); let input = Pipe(); let stderr = Pipe()
        child.executableURL = URL(fileURLWithPath:bootstrap.python)
        child.arguments = ["-I","-S","-B","-u","-c",CommunityBootstrap.pythonEntry,bootstrap.coreDirectory,bootstrap.packageDirectory,
            "--data-dir",arguments.dataDirectory,"--port",String(origin?.port ?? arguments.port),"--owner-stdin"]
        child.currentDirectoryURL = URL(fileURLWithPath:bootstrap.coreDirectory)
        child.environment = ["PATH":"/usr/bin:/bin:/usr/sbin:/sbin", "HOME":NSHomeDirectory(),
            "TMPDIR":NSTemporaryDirectory(), "LANG":"zh_CN.UTF-8", "PYTHONNOUSERSITE":"1", "PYTHONDONTWRITEBYTECODE":"1",
            "RUNTEAMS_ATTACHMENT_PICKER":Bundle.main.resourceURL!.appendingPathComponent("RunTeamsPicker.app/Contents/MacOS/RunTeamsPicker").path]
        child.standardOutput = stdout; child.standardInput = input; child.standardError = stderr
        ownerPipe = input; process = child
        stderr.fileHandleForReading.readabilityHandler = { handle in _ = handle.availableData }
        child.terminationHandler = { [weak self] _ in DispatchQueue.main.async {
            guard let self = self, self.generation == current else { return }
            stderr.fileHandleForReading.readabilityHandler = nil
            self.serviceReady = false; self.process = nil
            if self.quitting { self.windowLock = nil; NSApp.reply(toApplicationShouldTerminate:true) }
            else { self.presentFailure() }
        }}
        do { try child.run() }
        catch { process = nil; presentFailure(); return }
        DispatchQueue.main.asyncAfter(deadline:.now() + 15) { [weak self] in
            if let self = self, self.generation == current, !self.serviceReady, child.isRunning { child.terminate() }
        }
        DispatchQueue.global(qos:.userInitiated).async { [weak self] in
            do {
                var buffer = Data()
                while !buffer.contains(10) {
                    let next = stdout.fileHandleForReading.availableData
                    guard !next.isEmpty, buffer.count + next.count <= 65536 else { throw CommunityBootstrap.Failure.invalid }
                    buffer.append(next)
                }
                let line = buffer.prefix(while: { $0 != 10 })
                guard let value = try JSONSerialization.jsonObject(with:line) as? [String:Any],
                      value["schema"] as? String == "runteams.local-service/1", value["edition"] as? String == "community",
                      let originText = value["origin"] as? String, let url = CommunityNavigation.origin(originText),
                      value["ui_url"] as? String == originText + "/",
                      (value["capabilities"] as? [String])?.contains("business.ui") == true else { throw CommunityBootstrap.Failure.invalid }
                DispatchQueue.main.async {
                    guard let self = self, self.generation == current, child.isRunning else { return }
                    if let old = self.origin, !CommunityNavigation.sameOrigin(url,old) { child.terminate(); return }
                    self.employeeDesktop?.reset();self.employeeDesktop=nil
                    do {
                        guard let config=value["native_work"] as? [String:Any] else { throw CommunityBootstrap.Failure.invalid }
                        self.employeeDesktop=try CreatorDesktopHost(platform:self.webView,parent:self.webView.superview!,origin:url,data:JSONSerialization.data(withJSONObject:config))
                    } catch { child.terminate();return }
                    self.origin = url; self.serviceReady = true
                    if !self.pageReady { self.webView.load(URLRequest(url:url.appendingPathComponent("/"))) }
                }
                while !stdout.fileHandleForReading.availableData.isEmpty {}
            } catch { DispatchQueue.main.async { if child.isRunning { child.terminate() } } }
        }
    }

    private func presentFailure() {
        guard window != nil, !quitting, !failurePresented else { return }
        failurePresented = true
        let alert = NSAlert(); alert.messageText = localized("本机连接已中断","Local Connection Lost")
        alert.informativeText = localized("已保存的内容仍在本机。重新连接后，请核对之前的保存结果。","Saved content is still on this Mac. After reconnecting, check the result of your last save.")
        alert.addButton(withTitle:localized("重新连接","Reconnect")); alert.addButton(withTitle:localized("退出","Quit"))
        alert.beginSheetModal(for:window) { [weak self] response in
            guard let self = self else { return }; self.failurePresented = false
            if response == .alertFirstButtonReturn {
                if self.process?.isRunning == true { self.webView.load(URLRequest(url:self.origin!)) }
                else { self.startService() }
            } else { NSApp.terminate(nil) }
        }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if window == nil { return .terminateNow }
        if window.attachedSheet != nil || NSApp.modalWindow != nil { return .terminateCancel }
        if quitting || checkingClose { return .terminateLater }
        checkingClose = true
        checkClose(discard:false)
        return .terminateLater
    }
    private func checkClose(discard: Bool) {
        if !downloads.isEmpty { cancelClose(localized("请等待文件保存完成，或取消保存后再退出。","Wait for the file to finish saving, or cancel the save before quitting.")); return }
        if !pageReady { stopOwnedService(); return }
        guard let current = webView.url, let origin = origin, CommunityNavigation.sameOrigin(current,origin) else {
            cancelClose(localized("无法确认页面是否已保存。请稍后重试。","Couldn’t confirm that the page was saved. Try again in a moment.")); return
        }
        webView.evaluateJavaScript("window.RunTeamsLocalDesktop?.checkClose(\(discard ? "true" : "false"))") { [weak self] result, error in
            guard let self = self else { return }
            if result as? String == "ready", error == nil { self.prepareWorkClose(discard: discard) }
            else if result as? String == "dirty", error == nil {
                let alert = NSAlert(); alert.messageText = self.localized("放弃未保存的修改并退出？","Discard Unsaved Changes and Quit?")
                alert.informativeText = self.localized("已保存的内容会保留。","Your saved content will be kept."); alert.addButton(withTitle:self.localized("继续编辑","Keep Editing")); alert.addButton(withTitle:self.localized("放弃修改并退出","Discard and Quit"))
                alert.beginSheetModal(for:self.window) { response in
                    if response == .alertSecondButtonReturn { self.checkClose(discard:true) }
                    else { self.checkingClose = false; NSApp.reply(toApplicationShouldTerminate:false) }
                }
            } else { self.cancelClose(self.localized("请在页面中核对保存结果，再退出。","Check the save status on the page before quitting.")) }
        }
    }
    private func prepareWorkClose(discard: Bool) {
        let finish: (Bool) -> Void = { [weak self] allowed in
            guard let self = self else { return }
            guard allowed else {
                self.cancelClose(self.localized("请处理工作台中的未保存内容或正在执行的操作，再退出。","Resolve unsaved changes or actions still in progress in the workspace before quitting.")); return
            }
            // The platform remains editable until work pages acknowledge. Check
            // its original guard again, and freeze only at the final commit.
            self.webView.evaluateJavaScript("window.RunTeamsLocalDesktop?.prepareClose(\(discard ? "true" : "false"))") { [weak self] result, error in
                guard let self = self else { return }
                if result as? String == "ready", error == nil { self.stopOwnedService() }
                else { self.cancelClose(self.localized("检查期间内容已变更。请处理这些修改后再退出。","Content changed during the check. Resolve those changes before quitting.")) }
            }
        }
        if let host = employeeDesktop { host.prepareClose(finish) }
        else { finish(true) }
    }
    private func cancelClose(_ message: String) {
        employeeDesktop?.cancelClosePreparation()
        checkingClose = false; NSApp.reply(toApplicationShouldTerminate:false)
        let alert = NSAlert(); alert.messageText = localized("暂时无法退出","Can’t Quit Yet"); alert.informativeText = message
        alert.addButton(withTitle:localized("返回","Go Back")); alert.beginSheetModal(for:window)
    }
    private func stopOwnedService() {
        quitting = true; checkingClose = false
        employeeDesktop?.reset();employeeDesktop=nil
        if process?.isRunning == true { try? ownerPipe?.fileHandleForWriting.close() }
        else { windowLock = nil; NSApp.reply(toApplicationShouldTerminate:true) }
    }

    func userContentController(_ controller: WKUserContentController,didReceive message: WKScriptMessage,replyHandler: @escaping (Any?,String?) -> Void) {
        if message.name == "runteamsLanguage" {
            let source = message.frameInfo.securityOrigin
            guard controller === webView.configuration.userContentController, message.webView === webView,
                  message.frameInfo.isMainFrame, let origin,
                  source.protocol == origin.scheme, source.host == origin.host, source.port == origin.port,
                  let language = message.body as? String, ["system","zh-CN","en"].contains(language)
            else { replyHandler(nil,"language_preference_unavailable");return }
            UserDefaults.standard.set(language,forKey:"runteams_language_preference")
            updateLanguageSeed(controller)
            makeMenu()
            window.title = localized("RunTeams 本机版","RunTeams Local")
            replyHandler(true,nil)
            return
        }
        guard message.name=="runteamsCreatorWork",let host=employeeDesktop,host.accepts(message,controller:controller) else { replyHandler(nil,"work_owner_unavailable");return }
        host.handle(message.body,reply:replyHandler)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { pageReady = true; loading?.removeFromSuperview() }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if !pageReady { presentFailure() }
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        pageReady = false
        let alert = NSAlert(); alert.messageText = localized("窗口已停止响应","Window Isn’t Responding"); alert.informativeText = localized("重新打开后可继续使用已保存的资产。未保存的修改将丢失。","Reopen the window to continue using saved assets. Unsaved changes will be lost.")
        alert.addButton(withTitle:localized("重新打开","Reopen")); alert.addButton(withTitle:localized("退出","Quit"))
        alert.beginSheetModal(for:window) { [weak self] response in
            guard let self = self else { return }
            if response == .alertFirstButtonReturn, let origin = self.origin { self.webView.load(URLRequest(url:origin)) }
            else { NSApp.terminate(nil) }
        }
    }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy)->Void) {
        guard let origin = origin, let url = action.request.url else { decisionHandler(.cancel); return }
        let source = action.sourceFrame.securityOrigin
        if action.navigationType == .linkActivated, action.targetFrame == nil, action.sourceFrame.isMainFrame,
           source.protocol == origin.scheme, source.host == origin.host, source.port == origin.port,
           CommunityNavigation.legalLink(url) {
            decisionHandler(.cancel)
            NSWorkspace.shared.open(url)
            return
        }
        guard CommunityNavigation.allows(url,origin:origin,download:action.shouldPerformDownload) else { decisionHandler(.cancel); return }
        decisionHandler(action.shouldPerformDownload ? .download : .allow)
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard action.targetFrame == nil, let origin = origin, let url = action.request.url,
              CommunityNavigation.attachment(url, origin:origin) else { return nil }
        webView.startDownload(using:action.request) { [weak self] download in
            self?.downloads[ObjectIdentifier(download)] = download
            download.delegate = self
        }
        return nil
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?)->Void) {
        guard frame.isMainFrame, let url = frame.request.url, let origin = origin, CommunityNavigation.sameOrigin(url,origin) else { completionHandler(nil); return }
        let panel = NSOpenPanel()
        if parameters.allowsDirectories {
            panel.title = parameters.allowsMultipleSelection ? localized("选择文件夹", "Choose Folders") : localized("选择文件夹", "Choose a Folder")
        } else {
            panel.title = parameters.allowsMultipleSelection ? localized("选择文件", "Choose Files") : localized("选择文件", "Choose a File")
        }
        panel.prompt = localized("选择", "Choose")
        panel.canChooseFiles = !parameters.allowsDirectories
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.beginSheetModal(for:window) { response in completionHandler(response == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool)->Void) {
        guard frame.isMainFrame, let url = frame.request.url, let origin = origin, CommunityNavigation.sameOrigin(url,origin) else { completionHandler(false); return }
        let alert = NSAlert(); alert.messageText = message; alert.addButton(withTitle:localized("取消","Cancel")); alert.addButton(withTitle:localized("确定","OK"))
        alert.beginSheetModal(for:window) { response in completionHandler(response == .alertSecondButtonReturn) }
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { downloads[ObjectIdentifier(download)] = download; download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { downloads[ObjectIdentifier(download)] = download; download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?)->Void) {
        guard let url = webView.url, let origin = origin, CommunityNavigation.sameOrigin(url,origin) else {
            downloads.removeValue(forKey:ObjectIdentifier(download)); completionHandler(nil); return
        }
        DispatchQueue.main.async { [weak self] in
            let panel = NSSavePanel()
            panel.title = self?.localized("保存文件", "Save File") ?? "Save File"
            panel.prompt = self?.localized("保存", "Save") ?? "Save"
            panel.canCreateDirectories = true; panel.isExtensionHidden = false
            panel.directoryURL = FileManager.default.urls(for:.downloadsDirectory, in:.userDomainMask).first
            panel.nameFieldStringValue = (suggestedFilename as NSString).lastPathComponent
            let response = panel.runModal()
            if response != .OK { self?.downloads.removeValue(forKey:ObjectIdentifier(download)) }
            completionHandler(response == .OK ? panel.url : nil)
        }
    }
    func downloadDidFinish(_ download: WKDownload) { downloads.removeValue(forKey:ObjectIdentifier(download)) }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloads.removeValue(forKey:ObjectIdentifier(download))
        if (error as NSError).code == NSURLErrorCancelled { return }
        let alert = NSAlert()
        alert.messageText = localized("下载未完成","Download Didn’t Finish")
        alert.informativeText = localized("请重新下载。保存在所选位置的文件可能不完整。","Download the file again. If a file was saved to the selected location, it may be incomplete.")
        alert.addButton(withTitle:localized("好","OK")); alert.beginSheetModal(for:window)
    }
}

let launchArguments = Array(CommandLine.arguments.dropFirst())
if launchArguments == ["--check-bootstrap"] {
    do { let value = try CommunityBootstrap.read(); print("{\"valid\":true,\"version\":\"\(value.version)\"}") }
    catch { fputs("Native bootstrap validation failed\n",stderr); exit(2) }
} else if launchArguments.first == "--sdk" {
    do { try CommunityBootstrap.read().runSDK(Array(launchArguments.dropFirst())) }
    catch { fputs("Unable to start the bundled RunTeams SDK\n", stderr); exit(2) }
} else {
    let app = NSApplication.shared; app.setActivationPolicy(.regular)
    let delegate = CommunityApp(); app.delegate = delegate
    withExtendedLifetime(delegate) { app.run() }
}
