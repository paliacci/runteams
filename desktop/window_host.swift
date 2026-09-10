import AppKit
import WebKit

class WindowDragView: NSView {
    override func mouseDown(with event: NSEvent) {
        window?.performDrag(with: event)
    }
}

final class HeaderDragRegionView: WindowDragView {
    private var headerRect: NSRect?
    private var excludedRects: [NSRect] = []

    override func hitTest(_ point: NSPoint) -> NSView? {
        guard let headerRect, headerRect.contains(point) else { return nil }
        guard !excludedRects.contains(where: { $0.contains(point) }) else { return nil }
        return self
    }

    func updateRegions(from body: Any) {
        guard let payload = body as? [String: Any] else {
            headerRect = nil
            excludedRects = []
            return
        }
        headerRect = nativeRect(from: payload["header"])
        excludedRects = (payload["excluded"] as? [Any] ?? []).compactMap(nativeRect)
    }

    private func nativeRect(from value: Any?) -> NSRect? {
        guard let rect = value as? [String: Any],
              let x = (rect["x"] as? NSNumber)?.doubleValue,
              let y = (rect["y"] as? NSNumber)?.doubleValue,
              let width = (rect["width"] as? NSNumber)?.doubleValue,
              let height = (rect["height"] as? NSNumber)?.doubleValue else { return nil }
        return NSRect(x: x, y: bounds.height - y - height, width: width, height: height)
    }
}

final class RunTeamsAppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var headerDragView: HeaderDragRegionView!
    private var localHosts = Set(["127.0.0.1", "localhost"])

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()

        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.userContentController.addUserScript(WKUserScript(
            source: "document.documentElement.classList.add('runteams-native-macos')",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: false
        ))
        configuration.userContentController.add(self, name: "runteamsWindowDragRegions")
        configuration.userContentController.addUserScript(WKUserScript(
            source: """
            (() => {
              let scheduled = false;
              let previous = "";
              const rect = element => {
                const value = element.getBoundingClientRect();
                return {x:value.x, y:value.y, width:value.width, height:value.height};
              };
              const sync = () => {
                scheduled = false;
                const header = document.querySelector('.vhead');
                const payload = header ? {
                  header: rect(header),
                  excluded: Array.from(header.querySelectorAll('button,input,a,select,textarea,[role="button"],[onclick]')).map(rect)
                } : {header:null, excluded:[]};
                const serialized = JSON.stringify(payload);
                if (serialized === previous) return;
                previous = serialized;
                window.webkit.messageHandlers.runteamsWindowDragRegions.postMessage(payload);
              };
              const schedule = () => {
                if (scheduled) return;
                scheduled = true;
                requestAnimationFrame(sync);
              };
              new MutationObserver(schedule).observe(document.documentElement, {subtree:true, childList:true, attributes:true});
              window.addEventListener('resize', schedule);
              window.addEventListener('scroll', schedule, true);
              schedule();
            })();
            """,
            injectionTime: .atDocumentEnd,
            forMainFrameOnly: true
        ))

        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsMagnification = false
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = NSColor(calibratedWhite: 0.075, alpha: 1)
        }

        let style: NSWindow.StyleMask = [
            .titled, .closable, .miniaturizable, .resizable, .fullSizeContentView,
        ]
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1440, height: 900),
            styleMask: style,
            backing: .buffered,
            defer: false
        )
        window.delegate = self
        window.title = "RunTeams.ai"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.titlebarSeparatorStyle = .none
        window.isMovableByWindowBackground = true
        window.tabbingMode = .disallowed
        window.minSize = NSSize(width: 960, height: 640)
        window.backgroundColor = NSColor(calibratedWhite: 0.075, alpha: 1)
        let rootView = NSView()
        rootView.wantsLayer = true
        rootView.layer?.backgroundColor = NSColor(calibratedWhite: 0.075, alpha: 1).cgColor
        webView.translatesAutoresizingMaskIntoConstraints = false
        rootView.addSubview(webView)
        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: rootView.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: rootView.trailingAnchor),
            webView.topAnchor.constraint(equalTo: rootView.topAnchor),
            webView.bottomAnchor.constraint(equalTo: rootView.bottomAnchor),
        ])

        // WebKit does not honor -webkit-app-region. Keep a native drag target
        // after the sidebar and search controls in the titlebar.
        let dragView = WindowDragView()
        dragView.translatesAutoresizingMaskIntoConstraints = false
        rootView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.leadingAnchor.constraint(equalTo: rootView.leadingAnchor, constant: 158),
            dragView.topAnchor.constraint(equalTo: rootView.topAnchor),
            dragView.widthAnchor.constraint(equalToConstant: 150),
            dragView.heightAnchor.constraint(equalToConstant: 32),
        ])
        headerDragView = HeaderDragRegionView()
        headerDragView.translatesAutoresizingMaskIntoConstraints = false
        rootView.addSubview(headerDragView)
        NSLayoutConstraint.activate([
            headerDragView.leadingAnchor.constraint(equalTo: rootView.leadingAnchor),
            headerDragView.trailingAnchor.constraint(equalTo: rootView.trailingAnchor),
            headerDragView.topAnchor.constraint(equalTo: rootView.topAnchor),
            headerDragView.bottomAnchor.constraint(equalTo: rootView.bottomAnchor),
        ])
        window.contentView = rootView
        window.isReleasedWhenClosed = false

        let frameName = "RunTeamsMainWindow"
        if !window.setFrameUsingName(frameName) {
            window.center()
        }
        window.setFrameAutosaveName(frameName)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        let rawURL = CommandLine.arguments.dropFirst().first ?? "http://127.0.0.1:8791"
        guard let url = URL(string: rawURL) else {
            NSApp.terminate(nil)
            return
        }
        webView.load(URLRequest(url: url))
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        webView.reload()
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "runteamsWindowDragRegions", message.frameInfo.isMainFrame else { return }
        headerDragView.updateRegions(from: message.body)
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        let isWebLink = url.scheme == "http" || url.scheme == "https"
        let isLocal = localHosts.contains(url.host ?? "")
        if isWebLink && !isLocal {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        if navigationAction.targetFrame == nil {
            if isLocal {
                webView.load(navigationAction.request)
            } else {
                NSWorkspace.shared.open(url)
            }
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = navigationAction.request.url {
            if localHosts.contains(url.host ?? "") {
                webView.load(navigationAction.request)
            } else {
                NSWorkspace.shared.open(url)
            }
        }
        return nil
    }

    func webView(
        _ webView: WKWebView,
        runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping ([URL]?) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.beginSheetModal(for: window) { response in
            completionHandler(response == .OK ? panel.urls : nil)
        }
    }

    private func installMenu() {
        let mainMenu = NSMenu()

        let appItem = NSMenuItem()
        mainMenu.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于 RunTeams.ai", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出 RunTeams.ai", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu

        let editItem = NSMenuItem()
        mainMenu.addItem(editItem)
        let editMenu = NSMenu(title: "编辑")
        editMenu.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "重做", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu

        let windowItem = NSMenuItem()
        mainMenu.addItem(windowItem)
        let windowMenu = NSMenu(title: "窗口")
        windowMenu.addItem(withTitle: "最小化", action: #selector(NSWindow.miniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "关闭", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windowItem.submenu = windowMenu

        NSApp.mainMenu = mainMenu
    }
}

let application = NSApplication.shared
let delegate = RunTeamsAppDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
