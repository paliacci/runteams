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
            let alert = NSAlert(); alert.messageText = "无法打开本机版"
            alert.informativeText = "安装包中的运行文件不完整或已损坏，请重新安装本机版。"
            alert.addButton(withTitle: "退出"); alert.runModal(); NSApp.terminate(nil); return
        }
        makeMenu()
        window = NSWindow(contentRect: NSRect(x:0,y:0,width:1120,height:760),
            styleMask:[.titled,.closable,.miniaturizable,.resizable,.fullSizeContentView], backing:.buffered, defer:false)
        window.title = "RunTeams 本机版"; window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true; window.titlebarSeparatorStyle = .none
        window.minSize = NSSize(width:780,height:560); window.delegate = self
        window.isReleasedWhenClosed = false; window.center()
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.addScriptMessageHandler(self,contentWorld:.page,name:"runteamsCreatorWork")
        configuration.websiteDataStore = .nonPersistent()
        let nativeStyle = "const apply=()=>document.documentElement?.setAttribute('data-native','');if(document.documentElement)apply();else{const o=new MutationObserver(()=>{if(document.documentElement){apply();o.disconnect()}});o.observe(document,{childList:true,subtree:true})}"
        configuration.userContentController.addUserScript(WKUserScript(source:nativeStyle, injectionTime:.atDocumentStart, forMainFrameOnly:true))
        let content = NSView(frame:NSRect(x:0,y:0,width:1120,height:760))
        webView = WKWebView(frame:content.bounds, configuration:configuration)
        webView.navigationDelegate = self; webView.uiDelegate = self
        webView.autoresizingMask = [.width,.height]; content.addSubview(webView); window.contentView = content
        loading = NSView(frame:content.bounds); loading.autoresizingMask = [.width,.height]
        loading.wantsLayer = true; loading.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        let spinner = NSProgressIndicator(); spinner.style = .spinning; spinner.startAnimation(nil)
        let text = NSTextField(labelWithString:"正在打开本机资料库…"); text.font = .systemFont(ofSize:13); text.textColor = .secondaryLabelColor
        let stack = NSStackView(views:[spinner,text]); stack.orientation = .vertical; stack.spacing = 12; stack.translatesAutoresizingMaskIntoConstraints = false
        loading.addSubview(stack); content.addSubview(loading)
        NSLayoutConstraint.activate([stack.centerXAnchor.constraint(equalTo:loading.centerXAnchor), stack.centerYAnchor.constraint(equalTo:loading.centerYAnchor)])
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true)
        startService()
    }

    private func makeMenu() {
        let menu = NSMenu(); let appItem = NSMenuItem(); menu.addItem(appItem)
        let app = NSMenu(); appItem.submenu = app
        app.addItem(withTitle:"退出 RunTeams 本机版", action:#selector(NSApplication.terminate(_:)), keyEquivalent:"q")
        let fileItem = NSMenuItem(); menu.addItem(fileItem); let file = NSMenu(title:"文件"); fileItem.submenu = file
        file.addItem(withTitle:"关闭窗口", action:#selector(NSWindow.performClose(_:)), keyEquivalent:"w")
        let editItem = NSMenuItem(); menu.addItem(editItem); let edit = NSMenu(title:"编辑"); editItem.submenu = edit
        for (name, action, key) in [("撤销","undo:","z"),("剪切","cut:","x"),("复制","copy:","c"),("粘贴","paste:","v"),("全选","selectAll:","a")] {
            edit.addItem(withTitle:name, action:Selector(action), keyEquivalent:key)
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
        let alert = NSAlert(); alert.messageText = "本机服务连接已中断"
        alert.informativeText = "已保存的内容仍在本机。重试连接会保留当前页面，请继续确认原来的保存操作。"
        alert.addButton(withTitle:"重试连接"); alert.addButton(withTitle:"退出")
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
        if !downloads.isEmpty { cancelClose("文件仍在保存，请完成或取消保存后再退出。"); return }
        if !pageReady { stopOwnedService(); return }
        guard let current = webView.url, let origin = origin, CommunityNavigation.sameOrigin(current,origin) else {
            cancelClose("无法确认页面的保存状态，请稍后重试。"); return
        }
        webView.evaluateJavaScript("window.RunTeamsLocalDesktop?.checkClose(\(discard ? "true" : "false"))") { [weak self] result, error in
            guard let self = self else { return }
            if result as? String == "ready", error == nil { self.prepareWorkClose(discard: discard) }
            else if result as? String == "dirty", error == nil {
                let alert = NSAlert(); alert.messageText = "放弃未保存的修改并退出？"
                alert.informativeText = "已经保存的内容不会受影响。"; alert.addButton(withTitle:"继续编辑"); alert.addButton(withTitle:"放弃修改并退出")
                alert.beginSheetModal(for:self.window) { response in
                    if response == .alertSecondButtonReturn { self.checkClose(discard:true) }
                    else { self.checkingClose = false; NSApp.reply(toApplicationShouldTerminate:false) }
                }
            } else { self.cancelClose("保存尚未结束或结果未确认，请先在页面中确认保存结果。") }
        }
    }
    private func prepareWorkClose(discard: Bool) {
        let finish: (Bool) -> Void = { [weak self] allowed in
            guard let self = self else { return }
            guard allowed else {
                self.cancelClose("工作台尚未确认关闭，请先处理未保存内容或正在执行的操作。"); return
            }
            // The platform remains editable until work pages acknowledge. Check
            // its original guard again, and freeze only at the final commit.
            self.webView.evaluateJavaScript("window.RunTeamsLocalDesktop?.prepareClose(\(discard ? "true" : "false"))") { [weak self] result, error in
                guard let self = self else { return }
                if result as? String == "ready", error == nil { self.stopOwnedService() }
                else { self.cancelClose("关闭检查期间内容发生变化，请处理后再退出。") }
            }
        }
        if let host = employeeDesktop { host.prepareClose(finish) }
        else { finish(true) }
    }
    private func cancelClose(_ message: String) {
        employeeDesktop?.cancelClosePreparation()
        checkingClose = false; NSApp.reply(toApplicationShouldTerminate:false)
        let alert = NSAlert(); alert.messageText = "暂时无法退出"; alert.informativeText = message
        alert.addButton(withTitle:"继续处理"); alert.beginSheetModal(for:window)
    }
    private func stopOwnedService() {
        quitting = true; checkingClose = false
        employeeDesktop?.reset();employeeDesktop=nil
        if process?.isRunning == true { try? ownerPipe?.fileHandleForWriting.close() }
        else { windowLock = nil; NSApp.reply(toApplicationShouldTerminate:true) }
    }

    func userContentController(_ controller: WKUserContentController,didReceive message: WKScriptMessage,replyHandler: @escaping (Any?,String?) -> Void) {
        guard message.name=="runteamsCreatorWork",let host=employeeDesktop,host.accepts(message,controller:controller) else { replyHandler(nil,"work_owner_unavailable");return }
        host.handle(message.body,reply:replyHandler)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { pageReady = true; loading?.removeFromSuperview() }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if !pageReady { presentFailure() }
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        pageReady = false
        let alert = NSAlert(); alert.messageText = "界面已停止响应"; alert.informativeText = "重新打开会恢复已保存的资产，未保存的页面内容无法恢复。"
        alert.addButton(withTitle:"重新打开"); alert.addButton(withTitle:"退出")
        alert.beginSheetModal(for:window) { [weak self] response in
            guard let self = self else { return }
            if response == .alertFirstButtonReturn, let origin = self.origin { self.webView.load(URLRequest(url:origin)) }
            else { NSApp.terminate(nil) }
        }
    }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy)->Void) {
        guard let origin = origin, let url = action.request.url,
              CommunityNavigation.allows(url,origin:origin,download:action.shouldPerformDownload) else { decisionHandler(.cancel); return }
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
        panel.canChooseFiles = !parameters.allowsDirectories
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.beginSheetModal(for:window) { response in completionHandler(response == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool)->Void) {
        guard frame.isMainFrame, let url = frame.request.url, let origin = origin, CommunityNavigation.sameOrigin(url,origin) else { completionHandler(false); return }
        let alert = NSAlert(); alert.messageText = message; alert.addButton(withTitle:"取消"); alert.addButton(withTitle:"确定")
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
        let alert = NSAlert(); alert.messageText = "文件未保存"; alert.informativeText = "已保存的内容保持不变，请重新下载。"
        alert.addButton(withTitle:"返回"); alert.beginSheetModal(for:window)
    }
}

if Array(CommandLine.arguments.dropFirst()) == ["--check-bootstrap"] {
    do { let value = try CommunityBootstrap.read(); print("{\"valid\":true,\"version\":\"\(value.version)\"}") }
    catch { fputs("Native bootstrap validation failed\n",stderr); exit(2) }
} else {
    let app = NSApplication.shared; app.setActivationPolicy(.regular)
    let delegate = CommunityApp(); app.delegate = delegate
    withExtendedLifetime(delegate) { app.run() }
}
