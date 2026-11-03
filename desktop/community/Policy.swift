import Foundation

struct CommunityNavigation {
    static func origin(_ value: String) -> URL? {
        guard let url = URL(string: value), url.scheme == "http", url.host == "127.0.0.1",
              let port = url.port, (1...65535).contains(port), url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil, url.path.isEmpty || url.path == "/" else { return nil }
        return url
    }
    static func sameOrigin(_ url: URL, _ origin: URL) -> Bool {
        url.scheme == origin.scheme && url.host == origin.host && url.port == origin.port && url.user == nil && url.password == nil
    }
    static func attachment(_ url: URL, origin: URL) -> Bool {
        sameOrigin(url, origin) && url.query == nil && url.fragment == nil
            && url.path.range(of: "^/api/chat/[1-9][0-9]*/attachment/[a-f0-9]{24}$", options: .regularExpression) != nil
    }
    static func allows(_ url: URL, origin: URL, download: Bool = false) -> Bool {
        if sameOrigin(url, origin) { return true }
        if download && url.scheme == "blob", let inner = URL(string: String(url.absoluteString.dropFirst(5))) {
            return sameOrigin(inner, origin)
        }
        return false
    }
}
