import AppKit
import Foundation

// A trusted paste/drop in the local composer asks only for file URLs.
// This mode never opens a chooser, reads file bytes, or returns clipboard text.
if CommandLine.arguments.contains("--clipboard") || CommandLine.arguments.contains("--drop") {
    let board = CommandLine.arguments.contains("--drop") ? NSPasteboard(name: .drag) : NSPasteboard.general
    let urls = board.readObjects(forClasses: [NSURL.self],
        options: [.urlReadingFileURLsOnly: true]) as? [URL] ?? []
    let data = try JSONSerialization.data(withJSONObject: ["paths": urls.map { $0.path }])
    FileHandle.standardOutput.write(data)
    exit(0)
}

let application = NSApplication.shared
// Run as a normal, identifiable helper app while the panel is open. This keeps
// the native chooser visible to accessibility/UI automation as well as users.
application.setActivationPolicy(.regular)

let panel = NSOpenPanel()
panel.title = "选择文件和文件夹"
panel.prompt = "添加"
panel.message = "可同时选择文件或文件夹"
panel.canChooseFiles = true
panel.canChooseDirectories = true
panel.allowsMultipleSelection = !CommandLine.arguments.contains("--single")
if CommandLine.arguments.contains("--files-only") {
    panel.title = "选择文件"
    panel.message = "请选择你要使用的文件"
    panel.canChooseDirectories = false
}
if CommandLine.arguments.contains("--folders-only") {
    panel.title = "选择文件夹"
    panel.message = "请选择你要使用的文件夹"
    panel.canChooseFiles = false
}
panel.resolvesAliases = true
panel.treatsFilePackagesAsDirectories = false

func finish(_ response: NSApplication.ModalResponse) {
    let payload: [String: Any] = response == .OK
        ? ["cancelled": false, "paths": panel.urls.map { $0.path }]
        : ["cancelled": true, "paths": []]
    do {
        let data = try JSONSerialization.data(withJSONObject: payload, options: [])
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
        application.terminate(nil)
    } catch {
        FileHandle.standardError.write(Data("无法生成选择结果\n".utf8))
        exit(1)
    }
}

application.activate(ignoringOtherApps: true)
panel.begin(completionHandler: finish)
application.run()
