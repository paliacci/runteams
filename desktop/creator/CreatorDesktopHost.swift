import AppKit
import WebKit
import CoreFoundation
import Darwin
import os.log

/// Private app-owned work lifecycle. The platform never receives this nonce.
private final class CreatorOwnerControl: NSObject, URLSessionTaskDelegate {
    let origin: URL
    private let nonce: String
    private var session: URLSession!
    private struct Pending {
        let path: String
        let body: Data
        let done: (Result<[String: Any], Error>) -> Void
    }
    private let lock = NSLock()
    private var queued: [Pending] = []
    private var running = 0
    init(_ value: [String: Any], platform: URL) throws {
        guard Set(value.keys) == ["control", "nonce"],
              let origin = URL(string: value["control"] as? String ?? ""),
              origin.scheme == "http", origin.host == "127.0.0.1", origin.port != nil,
              origin.port != platform.port, origin.user == nil, origin.password == nil,
              origin.query == nil, origin.fragment == nil, origin.path == "" || origin.path == "/",
              let nonce = value["nonce"] as? String, nonce.utf8.count == 43,
              nonce.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") }) else {
            throw CreatorDesktopHost.Failure.invalidBootstrap
        }
        self.origin = origin; self.nonce = nonce
        super.init()
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil; config.httpShouldSetCookies = false; config.urlCache = nil
        config.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        config.timeoutIntervalForRequest = 50; config.timeoutIntervalForResource = 55
        config.httpMaximumConnectionsPerHost = 4
        session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }
    func call(_ path: String, _ payload: [String: Any], _ done: @escaping (Result<[String: Any], Error>) -> Void) {
        guard let body = try? JSONSerialization.data(withJSONObject: payload), body.count <= 20_000 else {
            done(.failure(CreatorDesktopHost.Failure.invalidRequest)); return
        }
        lock.lock()
        guard queued.count < 64 else { lock.unlock(); done(.failure(CreatorDesktopHost.Failure.unavailable)); return }
        queued.append(Pending(path:path,body:body,done:done));lock.unlock();pump()
    }
    private func pump() {
        var starts: [Pending] = []
        lock.lock()
        while running < 4, !queued.isEmpty { starts.append(queued.removeFirst());running += 1 }
        lock.unlock()
        for pending in starts {
            var request = URLRequest(url: origin.appendingPathComponent(pending.path)); request.httpMethod = "POST"
            request.setValue("Bearer " + nonce, forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type"); request.httpBody = pending.body
            session.dataTask(with: request) { data, response, error in
                self.lock.lock();self.running -= 1;self.lock.unlock();self.pump()
                guard error == nil, let response = response as? HTTPURLResponse, response.statusCode == 200,
                      let data = data, data.count <= 131_072,
                      let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    pending.done(.failure(error ?? CreatorDesktopHost.Failure.unavailable)); return
                }
                pending.done(.success(value))
            }.resume()
        }
    }
    func open(_ client: String, _ payload: [String: Any], _ done: @escaping (Result<[String: Any], Error>) -> Void) {
        call("client-register", ["client": client]) { [weak self] result in
            guard case .success(let value) = result, value["active"] as? Bool == true, let self = self else {
                done(.failure(CreatorDesktopHost.Failure.unavailable)); return
            }
            self.call("client-open", ["client":client,"payload":payload], done)
        }
    }
    func retire(_ client: String) { call("client-close", ["client":client]) { _ in } }
    func release(_ id: String) { call("release", ["id":id]) { _ in } }
    func shutdown() { session.finishTasksAndInvalidate() }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

/// Trusted application-window adapter. Bootstrap is read only by the native
/// process; neither the platform document nor a work receives control nonces.
/// Product discovery/provisioning and the complete composer remain separate.
final class CreatorDesktopHost {
    private struct Binding {
        let chat: Int
        let configuration: [String: Any]
    }
    private final class Mounted {
        let chat: Int
        let connection: CreatorCloudWork
        let host: CreatorWebHost
        var pending: (String, CreatorWebHost.ChatFence)?
        init(_ chat: Int, _ connection: CreatorCloudWork, _ host: CreatorWebHost) {
            self.chat = chat; self.connection = connection; self.host = host
        }
    }
    private weak var platform: WKWebView?
    private weak var parent: NSView?
    private let origin: URL
    private var bindings: [String: Binding]
    private let owner: CreatorOwnerControl?
    private var ownerEpoch = UUID().uuidString.lowercased()
    private var mounted: [String: Mounted] = [:]
    private var generation = UUID()
    private var inFlight = 0
    private var closePreparing = false
    enum Failure: Error { case invalidBootstrap, invalidRequest, unavailable, stale }

    convenience init(platform: WKWebView, parent: NSView, origin: URL, bootstrap: URL) throws {
        guard bootstrap.isFileURL else { throw Failure.invalidBootstrap }
        let descriptor = Darwin.open(bootstrap.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else { throw Failure.invalidBootstrap }
        let file = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? file.close() }
        var attributes = stat()
        guard fstat(descriptor, &attributes) == 0, attributes.st_uid == getuid(),
              attributes.st_mode & S_IFMT == S_IFREG, attributes.st_mode & 0o077 == 0,
              attributes.st_size <= 131_072 else { throw Failure.invalidBootstrap }
        let data = try file.read(upToCount: 131_073) ?? Data()
        try self.init(platform:platform,parent:parent,origin:origin,data:data)
    }

    init(platform: WKWebView, parent: NSView, origin: URL, data: Data) throws {
        guard data.count <= 131_072,
              let config = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let configured = URL(string: config["platform_origin"] as? String ?? ""),
              Self.sameOrigin(configured, origin), configured.path == "" || configured.path == "/",
              configured.query == nil, configured.fragment == nil,
              origin.scheme == "http", origin.host == "127.0.0.1", origin.port != nil else { throw Failure.invalidBootstrap }
        let works: [[String: Any]]
        if config["schema"] as? String == "runteams.creator-desktop/2",
           Set(config.keys) == ["schema", "platform_origin", "owner"], let control = config["owner"] as? [String: Any] {
            owner = try CreatorOwnerControl(control, platform: origin); works = []
        } else if config["schema"] as? String == "runteams.creator-desktop/1",
                  Set(config.keys) == ["schema", "platform_origin", "works"],
                  let items = config["works"] as? [[String: Any]], items.count <= 2 {
            owner = nil; works = items
        } else { throw Failure.invalidBootstrap }
        var bindings: [String: Binding] = [:]
        var endpoints = Set<String>()
        for item in works {
            guard Set(item.keys) == ["id", "chat_id", "configuration"],
                  let id = item["id"] as? String, UUID(uuidString: id) != nil, bindings[id] == nil,
                  let chat = Self.integer(item["chat_id"]), chat > 0,
                  let configuration = item["configuration"] as? [String: Any] else { throw Failure.invalidBootstrap }
            // Validate all entries before exposing any mounting capability.
            let connection = try CreatorCloudWork(configuration: configuration); connection.close()
            guard !Self.sameOrigin(connection.origin, origin),
                  let control = URL(string: configuration["control"] as? String ?? ""), !Self.sameOrigin(control, origin),
                  !endpoints.contains(connection.origin.absoluteString), !endpoints.contains(control.absoluteString) else { throw Failure.invalidBootstrap }
            endpoints.insert(connection.origin.absoluteString); endpoints.insert(control.absoluteString)
            bindings[id] = Binding(chat: chat, configuration: configuration)
        }
        self.platform = platform; self.parent = parent; self.origin = origin; self.bindings = bindings
    }
    deinit { owner?.shutdown() }

    private static func integer(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue.rounded() == number.doubleValue,
              abs(number.doubleValue) <= 9_007_199_254_740_991 else { return nil }
        return number.intValue
    }
    private static func sameOrigin(_ a: URL, _ b: URL) -> Bool {
        a.scheme == b.scheme && a.host == b.host && a.port == b.port &&
        a.user == nil && a.password == nil && b.user == nil && b.password == nil
    }
    private func current() -> Bool {
        guard let url = platform?.url else { return false }; return Self.sameOrigin(url, origin)
    }

    func accepts(_ message: WKScriptMessage, controller: WKUserContentController) -> Bool {
        guard let platform = platform, message.webView === platform,
              controller === platform.configuration.userContentController, message.frameInfo.isMainFrame,
              let source = message.frameInfo.request.url, Self.sameOrigin(source, origin), current() else { return false }
        let security = message.frameInfo.securityOrigin
        return security.protocol == origin.scheme && security.host == origin.host && security.port == origin.port
    }

    func reset(retire: Bool = true) {
        precondition(Thread.isMainThread)
        generation = UUID()
        closePreparing = false
        if let owner = owner {
            let previous = ownerEpoch; ownerEpoch = UUID().uuidString.lowercased()
            if retire { owner.retire(previous) }; bindings.removeAll()
        }
        let old = Array(mounted.values); mounted.removeAll()
        for entry in old {
            entry.host.close("platform_detached"); entry.host.container.removeFromSuperview(); entry.connection.close()
        }
    }

    /// Include hidden retained pipeline pages as well as the foreground page.
    /// No mounting/rebinding may race the captured set while quit is checked.
    func prepareClose(_ completion: @escaping (Bool) -> Void) {
        precondition(Thread.isMainThread)
        guard current(), !closePreparing, inFlight == 0 else { completion(false); return }
        closePreparing = true
        let expected = generation
        let entries = Array(mounted.values).filter { $0.host.closedReason == nil }
        var remaining = entries.count, allowed = true
        if entries.isEmpty { completion(true); return }
        for entry in entries {
            entry.host.prepareClose { [weak self] ready in
                remaining -= 1; allowed = allowed && ready
                guard remaining == 0 else { return }
                guard let self = self, self.generation == expected, self.current(), self.closePreparing else {
                    completion(false); return
                }
                if !allowed { self.cancelClosePreparation() }
                completion(allowed)
            }
        }
    }

    func cancelClosePreparation() {
        precondition(Thread.isMainThread)
        closePreparing = false
        for entry in mounted.values { entry.host.cancelClosePreparation() }
    }

    private func rectangle(_ value: Any?) throws -> NSRect {
        guard let parent = parent, let fields = value as? [String: Any], Set(fields.keys) == ["x", "y", "width", "height"] else { throw Failure.invalidRequest }
        var numbers: [String: Double] = [:]
        for key in fields.keys {
            guard let n = fields[key] as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite else { throw Failure.invalidRequest }
            numbers[key] = n.doubleValue
        }
        let x = numbers["x"]!, y = numbers["y"]!, w = numbers["width"]!, h = numbers["height"]!
        guard x >= 0, y >= 0, w >= 1, h >= 1, x+w <= parent.bounds.width, y+h <= parent.bounds.height else { throw Failure.invalidRequest }
        return NSRect(x: x, y: parent.bounds.height-y-h, width: w, height: h)
    }

    /// Called only after accepts verifies the actual sender/controller/frame.
    func handle(_ body: Any, reply: @escaping (Any?, String?) -> Void) {
        precondition(Thread.isMainThread)
        guard current(), inFlight < 4,
              let body = body as? [String: Any], let action = body["action"] as? String,
              let data = try? JSONSerialization.data(withJSONObject: body), data.count <= 20_000 else {
            reply(nil, "creator_platform_unavailable"); return
        }
        // Keep the captured pages displayed while their close checks run.
        // Mounting, rebinding and business actions must still wait for cancel.
        guard !closePreparing || ["status", "theme", "frame", "visibility"].contains(action) else {
            reply(nil, "creator_platform_close_pending"); return
        }
        if action == "status", Set(body.keys) == ["action"] {
            reply(["dynamic": owner != nil, "available": bindings.keys.sorted().map { ["id": $0, "chat_id": bindings[$0]!.chat] as [String: Any] }], nil); return
        }
        if action == "detach", Set(body.keys) == ["action"], let owner = owner {
            let client = ownerEpoch; reset(retire:false)
            let expected = generation; inFlight += 1
            owner.call("client-close", ["client":client]) { [weak self] result in
                DispatchQueue.main.async {
                    guard let self = self else { reply(nil, "creator_platform_closed"); return }
                    self.inFlight -= 1
                    guard self.generation == expected, self.current() else { reply(nil, "creator_platform_stale"); return }
                    var cloudConfirmed = false, nativeConfirmed = false
                    if case .success(let value) = result, value["active"] as? Bool == false,
                       let works = value["works"] as? [[String: Any]] {
                        cloudConfirmed = works.allSatisfy { $0["cloud_session_closed"] as? Bool == true }
                        nativeConfirmed = works.allSatisfy { $0["cloud_session_closed"] as? Bool == true || $0["trial_closed"] as? Bool == true }
                    }
                    reply(["detached":true,"cloud_sessions_closed":cloudConfirmed,"native_sessions_closed":nativeConfirmed], nil)
                }
            }
            return
        }
        if action == "discover" || action == "open" {
            dynamic(body, action: action, reply: reply); return
        }
        guard let id = body["id"] as? String, let binding = bindings[id],
              Self.integer(body["chat_id"]) == binding.chat else { reply(nil, "creator_binding_mismatch"); return }
        do {
            if action == "header-action" {
                guard Set(body.keys) == ["action","id","chat_id","epoch","revision","key"],
                      let epoch = body["epoch"] as? String, let revision = body["revision"] as? String,
                      let key = body["key"] as? String, let entry = mounted[id],
                      entry.host.headerAction(epoch:epoch, revision:revision, id:key) else { throw Failure.invalidRequest }
                reply(["delivered":true],nil); return
            }
            if action == "theme" {
                guard Set(body.keys) == ["action", "id", "chat_id", "theme"],
                      let theme = body["theme"] as? String, let entry = mounted[id] else { throw Failure.invalidRequest }
                try entry.host.setTheme(theme)
                reply(["theme":theme,"id":id], nil); return
            }
            if action == "context-changed" {
                guard Set(body.keys) == ["action", "id", "chat_id"], let entry = mounted[id],
                      entry.pending == nil, entry.host.closedReason == nil else { throw Failure.invalidRequest }
                entry.host.contextChanged()
                reply(["queued": true, "id": id], nil); return
            }
            if action == "visibility" {
                guard Set(body.keys) == ["action", "id", "chat_id", "visible"],
                      let visible = body["visible"] as? NSNumber, CFGetTypeID(visible) == CFBooleanGetTypeID(),
                      let entry = mounted[id] else { throw Failure.invalidRequest }
                entry.host.container.isHidden = !visible.boolValue
                reply(["visible": visible.boolValue, "id": id], nil); return
            }
            if action == "mount" || action == "frame" {
                guard Set(body.keys) == ["action", "id", "chat_id", "frame"] else { throw Failure.invalidRequest }
                let frame = try rectangle(body["frame"])
                if action == "mount", mounted[id] == nil {
                    guard let parent = parent else { throw Failure.unavailable }
                    let connection = try CreatorCloudWork(configuration: binding.configuration)
                    let host = try CreatorWebHost(origin: connection.origin, implemented: connection.methods,
                        authority: connection.authority, service: connection.serve, document: connection.document, failure: { reason in
                            os_log("Creator work closed: %{public}@", type: .error, reason)
                        })
                    let entry = Mounted(binding.chat, connection, host); mounted[id] = entry
                    host.display = { [weak self, weak host] epoch, state, expires, done in
                        guard let self = self, let host = host, self.current(), self.mounted[id]?.host === host,
                              host.closedReason == nil, host.epoch == epoch, let platform = self.platform else { done(false); return }
                        let generation = self.generation
                        platform.callAsyncJavaScript("return window.RunTeamsCreatorWork.applyDisplay(id,epoch,state,expires)",
                            arguments:["id":id,"epoch":epoch,"state":state,"expires":expires], in:nil, in:.page) { result in
                            guard self.generation == generation, self.current(), self.mounted[id]?.host === host,
                                  host.epoch == epoch, host.closedReason == nil,
                                  Date().timeIntervalSince1970 * 1000 < expires,
                                  case .success(let value) = result,
                                  let frame = try? self.rectangle(value) else { done(false); return }
                            host.container.frame = frame; host.webView?.frame = host.container.bounds
                            done(true)
                        }
                    }
                    host.displayInvalidated = { [weak self] epoch, closed in
                        guard let self = self, self.current() else { return }
                        self.platform?.callAsyncJavaScript("window.RunTeamsCreatorWork.clearDisplay(id,epoch,closed)",
                            arguments:["id":id,"epoch":epoch,"closed":closed], in:nil, in:.page) { _ in }
                    }
                    // A late open belongs to its original window until the coordinator
                    // explicitly acknowledges foreground visibility.
                    host.container.isHidden = true
                    host.container.frame = frame; parent.addSubview(host.container)
                    do { try host.open(connection.entry) }
                    catch { mounted.removeValue(forKey: id); host.close(); host.container.removeFromSuperview(); connection.close(); throw error }
                }
                guard let entry = mounted[id], entry.host.closedReason == nil else { throw Failure.unavailable }
                entry.host.container.frame = frame
                entry.host.webView?.frame = entry.host.container.bounds
                reply(["mounted": true, "id": id, "chat_id": binding.chat], nil); return
            }
            if action == "unmount", Set(body.keys) == ["action", "id", "chat_id"] {
                if let entry = mounted.removeValue(forKey: id) {
                    entry.host.close("platform_detached"); entry.host.container.removeFromSuperview(); entry.connection.close()
                }
                if let owner = owner {
                    bindings.removeValue(forKey: id)
                    let expected = generation; inFlight += 1
                    owner.call("release", ["id":id]) { [weak self] result in
                        DispatchQueue.main.async {
                            guard let self = self else { reply(nil, "creator_platform_closed"); return }
                            self.inFlight -= 1
                            guard self.generation == expected, self.current() else { reply(nil, "creator_platform_stale"); return }
                            var response: [String: Any] = ["mounted":false,"id":id,"cloud_session_closed":false,"trial_closed":false]
                            if case .success(let value) = result {
                                response["cloud_session_closed"] = value["cloud_session_closed"] as? Bool == true
                                response["trial_closed"] = value["trial_closed"] as? Bool == true
                            }
                            reply(response, nil)
                        }
                    }
                    return
                }
                reply(["mounted": false, "id": id], nil); return
            }
            guard let entry = mounted[id], let key = body["operation_key"] as? String,
                  !key.isEmpty, key.count <= 128 else { throw Failure.invalidRequest }
            let expected = generation
            inFlight += 1
            let done: (Result<[String: Any], Error>) -> Void = { [weak self, weak entry] result in
                DispatchQueue.main.async {
                    guard let self = self else { reply(nil, "creator_platform_closed"); return }
                    self.inFlight -= 1
                    guard self.generation == expected, self.current(), let entry = entry, self.mounted[id] === entry else { reply(nil, "creator_platform_stale"); return }
                    switch result {
                    case .failure:
                        reply(["state": entry.pending?.0 == key ? "unknown" : "rejected", "message_persisted": false, "agent_started": false], nil)
                    case .success(let receipt):
                        if receipt["state"] as? String == "confirmed" {
                            guard entry.pending?.0 == key, let message = Self.integer(receipt["message_id"]), message > 0,
                                  Self.integer(receipt["chat_id"]) == entry.chat,
                                  let epoch = receipt["business_epoch"] as? String, UUID(uuidString: epoch) != nil else {
                                reply(nil, "creator_receipt_invalid"); return
                            }
                            if let pending = entry.pending { _ = entry.host.releaseChat(pending.1) }; entry.pending = nil
                            reply(["state": "confirmed", "message_persisted": true, "agent_started": false,
                                "creator_message": ["message_id": message, "business_epoch": epoch, "operation_key": key]], nil)
                        } else {
                            if receipt["state"] as? String == "rejected", let pending = entry.pending {
                                _ = entry.host.releaseChat(pending.1); entry.pending = nil
                            }
                            reply(["state": receipt["state"] ?? "unknown", "message_persisted": false, "agent_started": false], nil)
                        }
                    }
                }
            }
            if action == "receipt", Set(body.keys) == ["action", "id", "chat_id", "operation_key"], entry.pending?.0 == key {
                entry.connection.chatReceipt(entry.pending!.1.epoch, key: key, done); return
            }
            let staged = Set(body.keys) == ["action", "id", "chat_id", "operation_key", "input_ref"] ? body["input_ref"] as? String : nil
            let text = Set(body.keys) == ["action", "id", "chat_id", "operation_key", "text"] ? body["text"] as? String : nil
            guard action == "submit", entry.pending == nil,
                  (staged != nil && UUID(uuidString: staged!) != nil) || (text != nil && !text!.isEmpty && text!.count <= 4000) else {
                inFlight -= 1; throw Failure.invalidRequest
            }
            entry.host.prepareChat { [weak self, weak entry] fence in
                guard let self = self, let entry = entry, self.generation == expected, self.mounted[id] === entry, self.current() else {
                    done(.failure(Failure.stale)); return
                }
                switch fence {
                case .failure(let error): done(.failure(error))
                case .success(let fence):
                    guard entry.host.validChatFence(fence) else { done(.failure(Failure.stale)); return }
                    entry.pending = (key, fence)
                    if let staged = staged { entry.connection.submitInput(fence.epoch, key: key, input: staged, done) }
                    else { entry.connection.submitChat(fence.epoch, key: key, text: text!, done) }
                }
            }
        } catch { reply(nil, "creator_platform_request_rejected") }
    }

    private func dynamic(_ body: [String: Any], action: String, reply: @escaping (Any?, String?) -> Void) {
        guard let owner = owner, let chat = Self.integer(body["chat_id"]), chat > 0,
              let workspace = body["workspace_id"] as? String,
              workspace.isEmpty || UUID(uuidString: workspace) != nil else {
            reply(nil, "creator_platform_request_rejected"); return
        }
        let expected = generation, client = ownerEpoch
        let payload: [String: Any]
        if action == "discover", Set(body.keys) == ["action", "workspace_id", "chat_id"] {
            payload = ["workspace_id":workspace,"chat_id":chat]
        } else if action == "open", Set(body.keys) == ["action", "workspace_id", "chat_id", "installation_id", "view", "input", "operation_key", "frame"],
                  let installation = body["installation_id"] as? String, UUID(uuidString: installation) != nil,
                  let view = body["view"] as? String, !view.isEmpty, view.count <= 128,
                  let input = body["input"] as? [String: Any], let key = body["operation_key"] as? String, !key.isEmpty, key.count <= 128,
                  (try? rectangle(body["frame"])) != nil {
            payload = ["workspace_id":workspace,"chat_id":chat,"installation_id":installation,"view":view,"input":input,"operation_key":key]
        } else { reply(nil, "creator_platform_request_rejected"); return }
        inFlight += 1
        let done: (Result<[String: Any], Error>) -> Void = { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self else { reply(nil, "creator_platform_closed"); return }
                self.inFlight -= 1
                guard self.generation == expected, self.current() else {
                    if action == "open", case .success(let value) = result, let id = value["id"] as? String, UUID(uuidString: id) != nil {
                        owner.release(id)
                    }
                    reply(nil, "creator_platform_stale"); return
                }
                guard case .success(let value) = result else { reply(nil, "creator_platform_unknown"); return }
                if action == "discover" {
                    // Only metadata is returned; configurations remain native.
                    guard Set(value.keys) == ["items", "authority", "chat_id"], Self.integer(value["chat_id"]) == chat,
                          ["author-preview", "installed-work", "device-owned-mcp-work"].contains(value["authority"] as? String ?? ""), let items = value["items"] as? [[String: Any]], items.count <= 64,
                          items.allSatisfy({ item in
                              guard Set(item.keys) == ["installation_id", "release_digest", "views"],
                                    let id = item["installation_id"] as? String, UUID(uuidString: id) != nil,
                                    let views = item["views"] as? [[String: Any]], views.count <= 64 else { return false }
                              return views.allSatisfy { Set($0.keys) == ["id", "title", "capabilities"] }
                          }) else {
                        reply(nil, "creator_discovery_invalid"); return
                    }
                    reply(value, nil); return
                }
                guard let id = value["id"] as? String, UUID(uuidString: id) != nil,
                      let state = value["state"] as? String else { reply(nil, "creator_open_invalid"); return }
                guard state == "ready" else {
                    guard ["opening", "unknown", "closing", "closed", "rejected"].contains(state) else { reply(nil, "creator_open_invalid"); return }
                    reply(["state":state,"id":id,"chat_id":chat], nil); return
                }
                do {
                    guard Set(value.keys) == ["state", "id", "chat_id", "configuration"], Self.integer(value["chat_id"]) == chat,
                          let config = value["configuration"] as? [String: Any],
                          let control = URL(string: config["control"] as? String ?? ""),
                          self.bindings[id] != nil || self.bindings.count < 8 else { throw Failure.invalidRequest }
                    let connection = try CreatorCloudWork(configuration: config); defer { connection.close() }
                    let reserved = [self.origin, owner.origin]
                    guard !reserved.contains(where: { Self.sameOrigin($0, connection.origin) || Self.sameOrigin($0, control) }) else { throw Failure.invalidRequest }
                    for (other, binding) in self.bindings where other != id {
                        for key in ["origin", "control"] {
                            guard let endpoint = URL(string: binding.configuration[key] as? String ?? ""),
                                  !Self.sameOrigin(endpoint, connection.origin), !Self.sameOrigin(endpoint, control) else { throw Failure.invalidRequest }
                        }
                    }
                    self.bindings[id] = Binding(chat: chat, configuration: config)
                    self.handle(["action":"mount","id":id,"chat_id":chat,"frame":body["frame"]!], reply: reply)
                } catch {
                    owner.release(id); reply(nil, "creator_open_invalid")
                }
            }
        }
        if action == "discover" { owner.call("discover", payload, done) }
        else { owner.open(client, payload, done) }
    }
}
