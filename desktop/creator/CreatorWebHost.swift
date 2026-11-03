import AppKit
import WebKit
import CoreFoundation

/// A work-only native surface. The application supplies verified, currently
/// authorized assets at a dedicated origin and a bounded asynchronous service.
/// This component never installs platform/account/file/chat message handlers.
/// It is not an entitlement service, a business executor, or a source verifier.
final class CreatorWebHost: NSObject, WKScriptMessageHandlerWithReply, WKNavigationDelegate, WKUIDelegate {
    typealias Authority = (@escaping (Result<Bool, Error>) -> Void) -> Void
    typealias Service = (String, [String: Any], String, Int, @escaping (Result<Any, Error>) -> Void) -> Void
    typealias Document = (String, @escaping (Result<Bool, Error>) -> Void) -> Void
    // Display changes are acknowledged by the trusted platform after layout.
    // They never enter the business sequence or Chat fence.
    typealias Display = (String, [String: Any], Double, @escaping (Bool) -> Void) -> Void
    var display: Display?
    var displayInvalidated: ((String, Bool) -> Void)?
    private var displayState: [String: Any] = ["mode":"panel", "viewId":NSNull(), "header":NSNull()]
    private var displayPending: (String, (Any?, String?) -> Void)?
    private let displayEventName = "__runteamsEvent_" + UUID().uuidString.replacingOccurrences(of:"-",with:"")
    static let methods: Set<String> = ["view.open", "context.read", "context.update", "context.select", "draft.set", "draft.discard", "operation.invoke", "mcp.tools.call", "mcp.preview.enable", "mcp.preview.select"]
    let container = NSView()
    private(set) var webView: WKWebView?
    private(set) var epoch = UUID().uuidString
    private(set) var closedReason: String?
    private(set) var rejected: [String: Int] = [:]
    private let origin: URL
    private let implemented: Set<String>
    private let authority: Authority
    private let service: Service
    private let document: Document
    private let failure: (String) -> Void
    private let workQueue = DispatchQueue(label: "ai.runteams.creator.ui." + UUID().uuidString)
    private var sequence = 0
    private var interval = ProcessInfo.processInfo.systemUptime
    private var count = 0
    private var pending: [UUID: (Any?, String?) -> Void] = [:]
    private var finishing: Set<UUID> = []
    // Timeouts end the reply, not the underlying service. Keep physical slots
    // occupied until its callback returns so a stuck service cannot grow queues.
    private var outstanding: Set<UUID> = []
    private var dispatched: Set<UUID> = []
    private var watchdog: Timer?
    private var lastHeartbeat = ProcessInfo.processInfo.systemUptime
    private var lastHeartbeatTick = ProcessInfo.processInfo.systemUptime
    private var heartbeatPending = false
    private let deadline: TimeInterval
    private let channel = UUID().uuidString
    private let counterName = "__runteamsIssued_" + UUID().uuidString.replacingOccurrences(of: "-", with: "")
    private var documentUnknown = false
    private var closeCheck: UUID?
    private var closePrepared = false
    private var theme = "light"
    private let environmentName = "__runteamsDisplay_" + UUID().uuidString.replacingOccurrences(of: "-", with: "")

    /// Called only by the trusted platform. No page-to-native mutation API.
    func setTheme(_ value: String) throws {
        precondition(Thread.isMainThread)
        guard ["light", "dark"].contains(value), closedReason == nil else { throw HostError.invalidConfiguration }
        theme = value
        webView?.evaluateJavaScript("window['\(environmentName)']?.('\(value)'); true") { _, _ in }
    }
    struct ChatFence {
        fileprivate let token: UUID
        let epoch: String
        let issued: Int
        let receivedBefore: Int
    }
    private final class Submission {
        let token = UUID()
        let epoch: String
        let beganAt: TimeInterval
        let receivedBefore: Int
        var boundary: Int?
        var checking = false
        var ready = false
        var completion: ((Result<ChatFence, Error>) -> Void)?
        init(_ epoch: String, _ receivedBefore: Int, _ completion: @escaping (Result<ChatFence, Error>) -> Void) {
            self.epoch = epoch; self.completion = completion
            self.receivedBefore = receivedBefore
            self.beganAt = ProcessInfo.processInfo.systemUptime
        }
    }
    private var submission: Submission?

    init(origin: URL, implemented: Set<String> = [], requestDeadline: TimeInterval = 10,
         authority: @escaping Authority, service: @escaping Service,
         document: @escaping Document = { _, done in done(.success(true)) },
         failure: @escaping (String) -> Void) throws {
        guard Thread.isMainThread, Self.methods.isSuperset(of: implemented),
              origin.user == nil, origin.password == nil, origin.query == nil, origin.fragment == nil,
              origin.path == "" || origin.path == "/", origin.host != nil,
              origin.scheme == "https" || (origin.scheme == "http" && origin.host == "127.0.0.1"),
              requestDeadline >= 0.1, requestDeadline <= 30 else { throw HostError.invalidConfiguration }
        self.origin = origin; self.implemented = implemented; self.authority = authority
        self.service = service; self.failure = failure; self.deadline = requestDeadline
        self.document = document
        super.init()
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        // WKProcessPool has no isolation effect on current macOS. Independent
        // stores/views must be fault-tested on every supported target system.
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "runteamsCreator")
        configuration.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "runteamsDisplay")
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = self; view.uiDelegate = self
        view.autoresizingMask = [.width, .height]
        container.addSubview(view); self.webView = view
        // A platform timer and separate web processes remain responsive when an
        // author renderer is stuck. The watchdog never waits synchronously on JS.
        let timer = Timer(timeInterval: 0.25, repeats: true) { [weak self] _ in self?.heartbeat() }
        watchdog = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    enum HostError: Error { case invalidConfiguration, invalidEntry, submissionUnavailable, submissionUnknown, staleSubmission }

    /// Trusted Chat input only. Read the immutable injected call counter in the
    /// renderer, then drain every accepted request through that boundary. This
    /// also covers posts queued in WebKit but not received by native/Python yet.
    /// The returned lease keeps later page calls refused until explicit release.
    func prepareChat(_ done: @escaping (Result<ChatFence, Error>) -> Void) {
        precondition(Thread.isMainThread)
        guard closedReason == nil, !documentUnknown, submission == nil, let view = webView else {
            done(.failure(HostError.submissionUnavailable)); return
        }
        let state = Submission(epoch, sequence, done); submission = state
        view.evaluateJavaScript("this['\(counterName)']()") { [weak self, weak state] value, error in
            guard let self = self, let state = state, self.submission === state else { return }
            guard self.epoch == state.epoch, self.closedReason == nil, error == nil,
                  let text = value as? String else { self.failSubmission(HostError.staleSubmission); return }
            let parts = text.split(separator: ":", omittingEmptySubsequences: false)
            guard parts.count == 2, String(parts[0]) == state.epoch, let issued = Int(parts[1]),
                  issued >= 0, issued <= 9_007_199_254_740_991 else {
                self.failSubmission(HostError.submissionUnknown); return
            }
            // Requests accepted before the counter callback must drain too,
            // even if they were posted after the renderer's counter read.
            state.boundary = max(issued, self.sequence)
            self.advanceSubmission()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + deadline) { [weak self, weak state] in
            guard let self = self, let state = state, self.submission === state else { return }
            // A held lease cannot silently expire and allow author writes while
            // a trusted message commit may still have an unknown outcome.
            self.documentUnknown = true; self.failSubmission(HostError.submissionUnknown)
            self.close("ui_submission_unknown")
        }
    }

    func validChatFence(_ fence: ChatFence) -> Bool {
        precondition(Thread.isMainThread)
        guard let state = submission else { return false }
        return closedReason == nil && !documentUnknown && state.ready && state.token == fence.token &&
            state.epoch == epoch && fence.epoch == epoch && state.boundary == fence.issued &&
            ProcessInfo.processInfo.systemUptime - state.beganAt < deadline
    }

    @discardableResult func releaseChat(_ fence: ChatFence) -> Bool {
        precondition(Thread.isMainThread)
        guard validChatFence(fence) else { return false }
        submission = nil; return true
    }

    /// An invalidation hint only. The author must read current authorized data;
    /// this supplies no business state, credentials, success or write permission.
    func contextChanged() {
        precondition(Thread.isMainThread)
        guard closedReason == nil, !documentUnknown, submission == nil, let view = webView else { return }
        view.evaluateJavaScript("window.dispatchEvent(new Event('runteams:context-changed')); true") { _, _ in }
    }

    private func failSubmission(_ error: Error) {
        let callback = submission?.completion; submission = nil
        callback?(.failure(error))
    }

    private func advanceSubmission() {
        guard let state = submission, !state.ready, !state.checking, let boundary = state.boundary else { return }
        guard closedReason == nil, epoch == state.epoch, !documentUnknown else {
            failSubmission(HostError.submissionUnknown); return
        }
        guard sequence >= boundary, pending.isEmpty, outstanding.isEmpty else { return }
        state.checking = true
        workQueue.async { [weak self, weak state] in
            guard let self = self, let state = state else { return }
            self.authority { [weak self, weak state] allowed in
                DispatchQueue.main.async {
                    guard let self = self, let state = state, self.submission === state else { return }
                    guard self.epoch == state.epoch, self.closedReason == nil, !self.documentUnknown else {
                        self.failSubmission(HostError.staleSubmission); return
                    }
                    guard self.authorized(allowed) else { return }
                    state.ready = true
                    let callback = state.completion; state.completion = nil
                    callback?(.success(ChatFence(token: state.token, epoch: state.epoch, issued: boundary, receivedBefore: state.receivedBefore)))
                }
            }
        }
    }

    func open(_ entry: URL) throws {
        precondition(Thread.isMainThread)
        guard closedReason == nil, owns(entry), let view = webView else { throw HostError.invalidEntry }
        view.frame = container.bounds
        view.load(URLRequest(url: entry, cachePolicy: .reloadIgnoringLocalAndRemoteCacheData, timeoutInterval: 10))
    }

    /// Graceful application quit uses the standard MCP teardown barrier. Forced
    /// revocation/crash cleanup still uses close(), independently of author JS.
    func prepareClose(_ completion: @escaping (Bool) -> Void) {
        precondition(Thread.isMainThread)
        guard implemented.contains("mcp.tools.call") else { completion(true); return }
        guard closedReason == nil, let view = webView, let url = view.url, owns(url),
              closeCheck == nil, pending.isEmpty, outstanding.isEmpty, submission == nil else {
            completion(false); return
        }
        let captured = epoch, ticket = UUID()
        closeCheck = ticket
        var finished = false
        let finish: (Bool) -> Void = { [weak self] allowed in
            guard !finished else { return }; finished = true
            if self?.closeCheck == ticket { self?.closeCheck = nil }
            completion(allowed)
        }
        // Covers original per-operation consent/execution and the parent's
        // bounded SDK request. A deadline never means cleanup may be resent.
        DispatchQueue.main.asyncAfter(deadline: .now() + 120) { finish(false) }
        view.callAsyncJavaScript("return await window.runteamsMCPClose.prepare()", arguments: [:], in: nil, in: .page) { [weak self] result in
            guard let self = self, !finished, self.closeCheck == ticket,
                  self.epoch == captured, self.closedReason == nil,
                  self.pending.isEmpty, self.outstanding.isEmpty, self.submission == nil,
                  case .success(let value) = result, value as? String == "ready" else {
                finish(false); return
            }
            self.closePrepared = true
            finish(true)
        }
    }

    func cancelClosePreparation() {
        precondition(Thread.isMainThread)
        closePrepared = false
        guard implemented.contains("mcp.tools.call"), closedReason == nil,
              let view = webView, let url = view.url, owns(url) else { return }
        view.evaluateJavaScript("window.runteamsMCPClose?.cancel()") { _, _ in }
    }

    /// Call on logout, changed installation/release, revoked access or teardown.
    /// No author JS needs to cooperate to remove its visible/native bridge state.
    func close(_ reason: String = "closed") {
        precondition(Thread.isMainThread)
        guard closedReason == nil else { return }
        closedReason = reason
        invalidateDisplay()
        epoch = UUID().uuidString
        failSubmission(HostError.staleSubmission)
        watchdog?.invalidate(); watchdog = nil
        let callbacks = Array(pending.values); pending.removeAll(); finishing.removeAll()
        for callback in callbacks { callback(nil, "ui_view_closed") }
        if let view = webView {
            view.configuration.userContentController.removeScriptMessageHandler(forName: "runteamsCreator", contentWorld: .page)
            view.configuration.userContentController.removeScriptMessageHandler(forName: "runteamsDisplay", contentWorld: .page)
            view.configuration.userContentController.removeAllUserScripts()
            view.navigationDelegate = nil; view.uiDelegate = nil; view.stopLoading(); view.removeFromSuperview()
        }
        webView = nil
        failure(reason)
    }

    private func invalidateDisplay() {
        let reply = displayPending?.1; displayPending = nil
        reply?(nil, "ui_display_closed")
        displayInvalidated?(epoch, closedReason != nil)
        displayState = ["mode":"panel", "viewId":NSNull(), "header":NSNull()]
    }

    private func displayEvent(_ event: [String: Any]) {
        guard closedReason == nil, let view = webView else { return }
        view.callAsyncJavaScript("window[name](epoch,event)", arguments:["name":displayEventName,"epoch":epoch,"event":event], in:nil, in:.page) { _ in }
    }

    func headerAction(epoch: String, revision: String, id: String) -> Bool {
        precondition(Thread.isMainThread)
        guard self.epoch == epoch, closedReason == nil, displayPending == nil,
              let header = displayState["header"] as? [String: Any], header["revision"] as? String == revision,
              let actions = header["actions"] as? [[String: Any]],
              actions.contains(where: { $0["id"] as? String == id && $0["disabled"] as? Bool == false }) else { return false }
        displayEvent(["action":["revision":revision,"id":id]]); return true
    }

    private func receiveDisplay(_ value: Any?, _ reply: @escaping (Any?, String?) -> Void) {
        guard let display = display, let request = value as? [String: Any], Set(request.keys) == ["method","params"],
              let method = request["method"] as? String, let params = request["params"] as? [String: Any],
              let ticket = params["ticket"] as? String, UUID(uuidString:ticket) != nil else { reply(nil,"ui_display_invalid"); return }
        if method == "cancel", Set(params.keys) == ["ticket"] {
            // If presentation cannot be confirmed, remove the view. Never leave
            // a late mutation live while the client reports its previous state.
            if displayPending?.0 == ticket { close("ui_display_cancelled") }
            reply(["cancelled":true],nil); return
        }
        guard displayPending == nil else { reply(nil,"ui_display_busy"); return }
        var next = displayState
        if method == "present", Set(params.keys) == ["ticket","mode","viewId"],
           let mode = params["mode"] as? String, ["panel","full"].contains(mode) {
            if mode == "full" {
                guard let id = params["viewId"] as? String,
                      id.range(of:"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",options:.regularExpression) != nil else { reply(nil,"ui_display_invalid"); return }
            } else if !(params["viewId"] is NSNull) { reply(nil,"ui_display_invalid"); return }
            next["mode"] = mode; next["viewId"] = params["viewId"]
        } else if method == "header", Set(params.keys) == ["ticket","text","actions"],
                  let text = params["text"] as? String, text.count <= 256,
                  let actions = params["actions"] as? [[String: Any]], actions.count <= 8 {
            var ids = Set<String>()
            for action in actions {
                guard Set(action.keys) == ["id","label","disabled"],
                      let id = action["id"] as? String, id.range(of:"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", options:.regularExpression) != nil,
                      ids.insert(id).inserted, let label = action["label"] as? String,
                      !label.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty, label.count <= 80,
                      let disabled = action["disabled"] as? NSNumber, CFGetTypeID(disabled) == CFBooleanGetTypeID() else { reply(nil,"ui_display_invalid"); return }
            }
            next["header"] = ["revision":ticket,"text":text,"actions":actions]
        } else { reply(nil,"ui_display_invalid"); return }
        let captured = epoch
        displayPending = (ticket,reply)
        let expires = Date().timeIntervalSince1970 * 1000 + 2000
        DispatchQueue.main.asyncAfter(deadline:.now()+2) { [weak self] in
            guard let self = self, self.epoch == captured, self.displayPending?.0 == ticket else { return }
            self.close("ui_display_timeout")
        }
        display(captured,next,expires) { [weak self] applied in
            guard let self = self, self.epoch == captured, self.closedReason == nil, self.displayPending?.0 == ticket else { return }
            guard applied, Date().timeIntervalSince1970 * 1000 < expires else { self.close("ui_display_unavailable"); return }
            self.displayPending = nil; self.displayState = next
            let presentation: [String: Any] = ["mode":next["mode"]!,"viewId":next["viewId"]!]
            self.displayEvent(["presentation":presentation])
            reply(presentation,nil)
        }
    }

    private func reject(_ reason: String, _ reply: (Any?, String?) -> Void) {
        rejected[reason, default: 0] += 1; reply(nil, reason); advanceSubmission()
    }

    private func owns(_ url: URL) -> Bool {
        url.scheme == origin.scheme && url.host == origin.host && url.port == origin.port &&
        url.user == nil && url.password == nil && url.path.hasPrefix("/views/") &&
        !url.path.contains("/../") && !url.path.contains("\\")
    }

    private func rotateDocument() {
        invalidateDisplay()
        failSubmission(HostError.staleSubmission)
        epoch = UUID().uuidString; sequence = 0; heartbeatPending = false
        documentUnknown = false
        closeCheck = nil; closePrepared = false
        lastHeartbeat = ProcessInfo.processInfo.systemUptime
        let callbacks = Array(pending.values); pending.removeAll(); finishing.removeAll()
        for reply in callbacks { reply(nil, "ui_stale_epoch") }
        guard let controller = webView?.configuration.userContentController else { return }
        controller.removeAllUserScripts()
        let methodJSON = String(data: try! JSONSerialization.data(withJSONObject: implemented.sorted()), encoding: .utf8)!
        // These nonces identify this document, never grant platform permission.
        controller.addUserScript(WKUserScript(source: """
        (() => {
          let sequence = 0;
          const docChannel = '\(channel)', docEpoch = '\(epoch)';
          const methods = Object.freeze(\(methodJSON));
          const handler = window.webkit.messageHandlers.runteamsCreator;
          const post = handler.postMessage.bind(handler);
          const call = (method, params = {}) => post({
            channel: docChannel, epoch: docEpoch, request: {schema:'runteams.ui-context/2',id:++sequence,method,params}
          });
          // Keep the envelope binding lexical: author code cannot extract a
          // channel literal from call.toString() and bypass the issued counter.
          // Sender/frame/origin and cloud permissions remain mandatory.
          Object.defineProperty(window, '\(counterName)', {value:()=>docEpoch+':'+sequence,writable:false,configurable:false});
          Object.defineProperty(window, 'runteamsUI', {value:Object.freeze({methods,call}),writable:false,configurable:false});
          let display = Object.freeze({theme:'\(theme)',presentation:Object.freeze({mode:'panel',viewId:null})});
          const listeners = new Set();
          Object.defineProperty(window, '\(environmentName)', {value:theme=>{
            if (!['light','dark'].includes(theme) || display.theme === theme) return;
            display = Object.freeze({...display,theme});
            for (const listener of listeners) {try {listener();} catch {}}
          },writable:false,configurable:false});
          const actionListeners = new Set();
          Object.defineProperty(window, '\(displayEventName)', {value:(epoch,event)=>{
            if (epoch !== docEpoch) return;
            if (event.presentation) {
              display = Object.freeze({...display,presentation:Object.freeze(event.presentation)});
              for (const listener of listeners) {try {listener();} catch {}}
            } else if (event.action) {
              for (const listener of actionListeners) {try {listener(event.action);} catch {}}
            }
          },writable:false,configurable:false});
          Object.defineProperty(window, 'runteamsHost', {value:Object.freeze({
            version:'0.1.0',kind:'platform',getSnapshot:()=>display,
            capabilities:Object.freeze(\(display == nil ? "[]" : "['presentation','drawer-header']")),
            request(method, params = {}) {
              return window.webkit.messageHandlers.runteamsDisplay.postMessage({channel:docChannel,epoch:docEpoch,request:{method,params}});
            },
            onAction(listener) { actionListeners.add(listener); return ()=>actionListeners.delete(listener); },
            subscribe(listener) {
              if (typeof listener !== 'function') throw new TypeError('listener');
              listeners.add(listener); return ()=>listeners.delete(listener);
            }
          }),writable:false,configurable:false});
        })();
        """, injectionTime: .atDocumentStart, forMainFrameOnly: true))
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        // Actual WebKit identity comes first, before any author-supplied field.
        guard closedReason == nil, let view = webView, message.webView === view,
              controller === view.configuration.userContentController,
              ["runteamsCreator", "runteamsDisplay"].contains(message.name), message.frameInfo.isMainFrame,
              let frameURL = message.frameInfo.request.url, owns(frameURL),
              let current = view.url, owns(current),
              message.frameInfo.securityOrigin.protocol == origin.scheme,
              message.frameInfo.securityOrigin.host == origin.host,
              message.frameInfo.securityOrigin.port == (origin.port ?? (origin.scheme == "https" ? 443 : 80)) else {
            reject("ui_sender_denied", replyHandler); return
        }
        guard !closePrepared else { replyHandler(nil, "ui_close_prepared"); return }
        let now = ProcessInfo.processInfo.systemUptime
        if now - interval >= 1 { interval = now; count = 0 }
        count += 1
        guard count <= 64 else { replyHandler(nil, "ui_rate_limit"); close("ui_rate_limit"); return }
        // JSON depth/node/encoded-byte limits precede service work. WebKit still
        // performs its own structured clone; this is not a universal OS quota.
        var nodes = 0; var size = 0
        guard Self.bounded(message.body, depth: 0, nodes: &nodes, size: &size, limit: 20_000),
              let bytes = try? JSONSerialization.data(withJSONObject: message.body), bytes.count <= 20_000 else {
            replyHandler(nil, "ui_message_budget"); close("ui_message_budget"); return
        }
        guard let envelope = message.body as? [String: Any], Set(envelope.keys) == ["channel", "epoch", "request"],
              envelope["channel"] as? String == channel, envelope["epoch"] as? String == epoch else {
            reject("ui_stale_epoch", replyHandler); return
        }
        if message.name == "runteamsDisplay" {
            receiveDisplay(envelope["request"], replyHandler); return
        }
        guard let request = envelope["request"] as? [String: Any],
              Set(request.keys) == ["schema", "id", "method", "params"],
              request["schema"] as? String == "runteams.ui-context/2",
              let id = request["id"] as? NSNumber, CFGetTypeID(id) != CFBooleanGetTypeID(),
              id.doubleValue.isFinite, id.doubleValue.rounded() == id.doubleValue,
              id.doubleValue == Double(sequence + 1), id.doubleValue <= 9_007_199_254_740_991,
              let method = request["method"] as? String, let params = request["params"] as? [String: Any] else {
            reject("ui_envelope_invalid", replyHandler); return
        }
        sequence += 1  // A valid sequence with a refused method doesn't deadlock future calls.
        if let boundary = submission?.boundary, sequence > boundary {
            reject("ui_chat_pending", replyHandler); return
        }
        guard implemented.contains(method) else { reject("ui_method_unavailable", replyHandler); return }
        guard pending.count < 4, outstanding.count < 4 else { reject("ui_busy", replyHandler); return }
        let key = UUID(); let capturedEpoch = epoch; pending[key] = replyHandler; outstanding.insert(key)
        // MCP tool calls include the host's one-operation consent (45s) and
        // managed tool execution (65s). Keep the ordinary document deadline;
        // a slow confirmation must not orphan an otherwise valid MCP reply.
        let callDeadline = method == "mcp.tools.call" ? 115.0 : deadline
        DispatchQueue.main.asyncAfter(deadline: .now() + callDeadline) { [weak self] in
            guard let self = self, let reply = self.pending.removeValue(forKey: key) else { return }
            self.finishing.remove(key)
            self.documentUnknown = true
            reply(nil, "ui_request_unknown") // A timeout never implies an effect failed or may be repeated.
            self.advanceSubmission()
        }
        // Both network authority and service entry run outside the UI thread.
        workQueue.async { [weak self] in
            guard let self = self else { return }
            self.authority { [weak self] allowed in
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    guard self.pending[key] != nil, self.epoch == capturedEpoch, self.closedReason == nil else {
                        self.outstanding.remove(key); self.dispatched.remove(key); self.advanceSubmission(); return
                    }
                    guard !self.dispatched.contains(key) else { return }; self.dispatched.insert(key)
                    guard self.authorized(allowed) else { return }
                    self.workQueue.async {
                        self.service(method, params, capturedEpoch, id.intValue) { [weak self] result in
                            DispatchQueue.main.async { self?.finish(key, epoch: capturedEpoch, result: result) }
                        }
                    }
                }
            }
        }
    }

    private func finish(_ key: UUID, epoch expected: String, result: Result<Any, Error>) {
        guard epoch == expected, closedReason == nil, pending[key] != nil else {
            outstanding.remove(key); dispatched.remove(key); advanceSubmission(); return
        }
        guard !finishing.contains(key) else { return }
        finishing.insert(key)
        // A service that was authorized when started may finish after revocation.
        // Recheck before disclosing its reply; effect authorization/atomicity is
        // still the cloud service's responsibility, not a page/host assertion.
        workQueue.async { [weak self] in
            guard let self = self else { return }
            self.authority { [weak self] allowed in
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    guard self.epoch == expected, self.closedReason == nil, self.pending[key] != nil else {
                        self.outstanding.remove(key); self.dispatched.remove(key); self.advanceSubmission(); return
                    }
                    guard self.authorized(allowed) else { return }
                    self.deliver(key, result: result)
                }
            }
        }
    }

    private func deliver(_ key: UUID, result: Result<Any, Error>) {
        guard let reply = pending.removeValue(forKey: key) else { return }
        finishing.remove(key); outstanding.remove(key); dispatched.remove(key)
        switch result {
        case .failure:
            documentUnknown = true; reply(nil, "ui_request_unknown") // A lost service reply may follow a committed effect.
        case .success(let value):
            var nodes = 0; var size = 0
            guard Self.bounded(value, depth: 0, nodes: &nodes, size: &size, limit: 131_072),
                  let bytes = try? JSONSerialization.data(withJSONObject: value, options: .fragmentsAllowed), bytes.count <= 131_072 else {
                documentUnknown = true; reply(nil, "ui_response_budget"); advanceSubmission(); return
            }
            reply(value, nil)
        }
        advanceSubmission()
    }

    private func authorized(_ result: Result<Bool, Error>) -> Bool {
        switch result {
        case .success(true): return true
        case .success(false): close("ui_access_denied"); return false
        case .failure: close("ui_authority_unavailable"); return false
        }
    }

    private static func bounded(_ value: Any, depth: Int, nodes: inout Int, size: inout Int, limit: Int) -> Bool {
        nodes += 1; size += 2
        guard depth <= 16, nodes <= 4096, size <= limit else { return false }
        if let object = value as? [String: Any] {
            for (key, child) in object {
                size += key.utf8.count + 3
                guard size <= limit, bounded(child, depth: depth + 1, nodes: &nodes, size: &size, limit: limit) else { return false }
            }
            return true
        }
        if let array = value as? [Any] {
            for child in array { if !bounded(child, depth: depth + 1, nodes: &nodes, size: &size, limit: limit) { return false } }
            return true
        }
        if let string = value as? String { size += string.utf8.count; return size <= limit }
        size += 32
        return size <= limit && (value is NSNull || value is NSNumber)
    }

    private func heartbeat() {
        guard closedReason == nil, let view = webView else { return }
        let now = ProcessInfo.processInfo.systemUptime
        // Deferred AppKit termination and sleep can suspend the native loop,
        // including WebKit replies. Allow a fresh response window on resume;
        // that host pause is not evidence that the author renderer has hung.
        if now - lastHeartbeatTick >= 3 { lastHeartbeat = now }
        lastHeartbeatTick = now
        guard now - lastHeartbeat < 3 else { close("ui_unresponsive"); return }
        guard !heartbeatPending else { return }
        heartbeatPending = true
        let expected = epoch
        view.evaluateJavaScript("0") { [weak self] _, _ in
            guard let self = self, self.epoch == expected, self.closedReason == nil else { return }
            self.heartbeatPending = false; self.lastHeartbeat = ProcessInfo.processInfo.systemUptime
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // A theme change can race document-start injection during navigation.
        try? setTheme(theme)
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        // Only the platform MCP Apps parent may mount the opaque resource frame.
        // Its sandbox and main-frame-only native handler remain mandatory.
        if self.webView === webView, closedReason == nil,
           implemented.contains("mcp.tools.call"), action.targetFrame?.isMainFrame == false,
           let resource = action.request.url, owns(resource), resource.path == "/views/mcp-app.html",
           let current = webView.url, owns(current), current.path == "/views/mcp-host.html" {
            decisionHandler(.allow); return
        }
        guard self.webView === webView, closedReason == nil, action.targetFrame?.isMainFrame == true,
              let url = action.request.url, owns(url) else { decisionHandler(.cancel); return }
        // Hash-only transitions keep the current document; full navigation gets
        // a fresh nonce and cannot receive old outstanding replies.
        let hashOnly = webView.url != url && webView.url?.absoluteString.components(separatedBy: "#").first == url.absoluteString.components(separatedBy: "#").first
        if !hashOnly {
            rotateDocument()
            let expected = epoch
            var resolved = false
            workQueue.async { [weak self] in
                guard let self = self else { decisionHandler(.cancel); return }
                self.document(expected) { [weak self] result in
                    DispatchQueue.main.async {
                        guard !resolved else { return }; resolved = true
                        guard let self = self, self.epoch == expected, self.closedReason == nil else {
                            decisionHandler(.cancel); return
                        }
                        decisionHandler(self.authorized(result) ? .allow : .cancel)
                    }
                }
            }
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if self.webView === webView, closedReason == nil, !response.isForMainFrame,
           implemented.contains("mcp.tools.call"), let url = response.response.url,
           owns(url), url.path == "/views/mcp-app.html", response.response.mimeType == "text/html",
           (response.response as? HTTPURLResponse)?.statusCode == 200 {
            decisionHandler(.allow); return
        }
        guard self.webView === webView, closedReason == nil, response.isForMainFrame,
              let url = response.response.url, owns(url),
              ["text/html", "application/xhtml+xml"].contains(response.response.mimeType ?? ""),
              (response.response as? HTTPURLResponse)?.statusCode == 200 else {
            decisionHandler(.cancel); close("ui_document_unavailable"); return
        }
        decisionHandler(.allow)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { close("ui_process_terminated") }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? { nil }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) { completionHandler(nil) }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) { completionHandler() }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) { completionHandler(false) }
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) { completionHandler(nil) }
    @available(macOS 12.0, *)
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                 initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
                 decisionHandler: @escaping (WKPermissionDecision) -> Void) { decisionHandler(.deny) }
}
