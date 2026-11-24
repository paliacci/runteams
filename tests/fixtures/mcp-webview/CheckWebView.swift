import AppKit

@main
struct CheckWebView {
    static func fail(_ reason: String) -> Never {
        FileHandle.standardError.write(Data((reason + "\n").utf8))
        exit(1)
    }

    static func main() throws {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let origin = URL(string: CommandLine.arguments[1])!
        let marker = UUID().uuidString
        let host = try CreatorWebHost(origin: origin, implemented: ["mcp.tools.call"],
            authority: { reply in reply(.success(true)) },
            service: { method, params, _, _, reply in
                guard method == "mcp.tools.call" else { fail("Unexpected native method") }
                switch params["name"] as? String {
                case "read_marker":
                    reply(.success(["ok": true, "result": ["content": [], "structuredContent": ["marker": marker]]]))
                case "confirm_marker":
                    guard let arguments = params["arguments"] as? [String: String],
                          arguments["marker"] == marker else { fail("Incorrect round-trip value") }
                    print("MCP app received the native WebView reply")
                    exit(0)
                default:
                    fail("Unexpected MCP tool")
                }
            }, failure: { fail($0) })
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 480, height: 320),
                              styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = host.container
        try host.open(origin.appendingPathComponent("views/mcp-host.html"))
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { fail("Timed out waiting for the MCP WebView reply") }
        withExtendedLifetime((window, host)) { app.run() }
    }
}
