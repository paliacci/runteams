import Foundation

/// Native-only connection to the application-owned CreatorNativeBridge. Author
/// documents receive no URL, nonce, session, account token or host credential.
/// Its methods are current wired capabilities, not the whole protocol catalog.
final class CreatorCloudWork: NSObject, URLSessionTaskDelegate {
    let origin: URL
    let entry: URL
    let methods: Set<String>
    private let control: URL
    private let nonce: String
    private var session: URLSession!

    enum TransportError: Error { case invalidConfiguration, unavailable, invalidReply }

    init(configuration: [String: Any]) throws {
        guard Set(configuration.keys) == ["origin", "control", "nonce", "entry", "methods"],
              let origin = URL(string: configuration["origin"] as? String ?? ""),
              let control = URL(string: configuration["control"] as? String ?? ""),
              let nonce = configuration["nonce"] as? String, nonce.utf8.count == 43,
              nonce.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") }),
              let path = configuration["entry"] as? String, path.hasPrefix("views/"),
              !path.contains(".."), !path.contains("\\"), !path.contains("?"), !path.contains("#"),
              let methods = configuration["methods"] as? [String],
              Set(["context.read", "context.update", "context.select", "draft.set", "draft.discard", "operation.invoke", "mcp.tools.call", "mcp.preview.enable", "mcp.preview.select"]).isSuperset(of: methods),
              Self.loopback(origin), Self.loopback(control), origin.port != control.port else {
            throw TransportError.invalidConfiguration
        }
        self.origin = origin; self.control = control; self.nonce = nonce
        self.entry = origin.appendingPathComponent(path); self.methods = Set(methods)
        super.init()
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil; config.httpShouldSetCookies = false
        config.urlCache = nil; config.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        config.timeoutIntervalForRequest = 10
        config.timeoutIntervalForResource = self.methods.contains("mcp.tools.call") ? 120 : 12
        config.httpMaximumConnectionsPerHost = 4
        session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }

    private static func loopback(_ url: URL) -> Bool {
        url.scheme == "http" && url.host == "127.0.0.1" && url.port != nil &&
        url.user == nil && url.password == nil && url.query == nil && url.fragment == nil &&
        (url.path == "" || url.path == "/")
    }

    func close() { session.invalidateAndCancel() }

    func authority(_ done: @escaping (Result<Bool, Error>) -> Void) {
        check("authority", payload: nil, done)
    }

    func document(_ epoch: String, _ done: @escaping (Result<Bool, Error>) -> Void) {
        check("document", payload: ["document":epoch], done)
    }

    private func check(_ path: String, payload: [String: Any]?, _ done: @escaping (Result<Bool, Error>) -> Void) {
        request(path, payload: payload) { result in
            switch result {
            case .failure(let error): done(.failure(error))
            case .success(let reply):
                if reply.0 == 403 { done(.success(false)); return }
                guard reply.0 == 200, let allowed = reply.1["authorized"] as? Bool, allowed else {
                    done(.failure(TransportError.unavailable)); return
                }
                done(.success(true))
            }
        }
    }

    func serve(_ method: String, _ params: [String: Any], _ epoch: String, _ requestID: Int,
               _ done: @escaping (Result<Any, Error>) -> Void) {
        guard methods.contains(method) else { done(.failure(TransportError.invalidConfiguration)); return }
        request("message", payload: ["document":epoch,"method":method,"params":params]) { result in
            switch result {
            case .failure(let error): done(.failure(error))
            case .success(let reply):
                guard reply.0 == 200, reply.1["schema"] as? String == "runteams.ui-context/2",
                      reply.1["ok"] is Bool else { done(.failure(TransportError.unavailable)); return }
                // Cloud calls are serialized independently: local denials/busy
                // frames consume native sequence IDs without reaching cloud.
                // Preserve the requesting document's response identity.
                var frame = reply.1; frame["id"] = requestID
                done(.success(frame))
            }
        }
    }

    /// Trusted composer transport. These are not negotiated author methods.
    func submitChat(_ epoch: String, key: String, text: String, _ done: @escaping (Result<[String: Any], Error>) -> Void) {
        chatRequest("chat-submit", ["document":epoch,"operation_key":key,"text":text], done)
    }

    func submitInput(_ epoch: String, key: String, input: String, _ done: @escaping (Result<[String: Any], Error>) -> Void) {
        chatRequest("chat-submit", ["document":epoch,"operation_key":key,"input_ref":input], done)
    }

    func chatReceipt(_ epoch: String, key: String, _ done: @escaping (Result<[String: Any], Error>) -> Void) {
        chatRequest("chat-receipt", ["document":epoch,"operation_key":key], done)
    }

    private func chatRequest(_ path: String, _ payload: [String: Any], _ done: @escaping (Result<[String: Any], Error>) -> Void) {
        request(path, payload: payload) { result in
            switch result {
            case .failure(let error): done(.failure(error))
            case .success(let reply):
                guard reply.0 == 200, let state = reply.1["state"] as? String,
                      ["confirmed", "rejected", "unknown"].contains(state), reply.1["agent_started"] as? Bool == false,
                      reply.1["message_persisted"] as? Bool == (state == "confirmed") else {
                    done(.failure(TransportError.unavailable)); return
                }
                done(.success(reply.1))
            }
        }
    }

    private func request(_ path: String, payload: [String: Any]?,
                         _ done: @escaping (Result<(Int, [String: Any]), Error>) -> Void) {
        var request = URLRequest(url: control.appendingPathComponent(path))
        if ["mcp.tools.call", "mcp.preview.enable"].contains(payload?["method"] as? String ?? "") { request.timeoutInterval = 115 }
        request.httpMethod = payload == nil ? "GET" : "POST"
        request.setValue("Bearer " + nonce, forHTTPHeaderField: "Authorization")
        if let payload = payload {
            guard let body = try? JSONSerialization.data(withJSONObject: payload), body.count <= 20_000 else {
                done(.failure(TransportError.invalidConfiguration)); return
            }
            request.setValue("application/json", forHTTPHeaderField: "Content-Type"); request.httpBody = body
        }
        session.dataTask(with: request) { data, response, error in
            guard error == nil, let data = data, data.count <= 131_072,
                  let response = response as? HTTPURLResponse,
                  let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                done(.failure(error ?? TransportError.invalidReply)); return
            }
            done(.success((response.statusCode, value)))
        }.resume()
    }

    // A redirected localhost request must never carry the native control nonce.
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
