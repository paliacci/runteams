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

let preferenceDomain = Bundle.main.object(forInfoDictionaryKey: "RunTeamsLanguagePreferenceDomain") as? String
let preference = preferenceDomain.flatMap {
    UserDefaults.standard.persistentDomain(forName: $0)?["runteams_language_preference"] as? String
}
let systemLanguages = Locale.preferredLanguages.compactMap { $0.split(separator: "-").first?.lowercased() }
let systemLanguage = systemLanguages.first { $0 == "zh" || $0 == "en" }
let chinese = preference == "zh-CN" || (preference != "en" && systemLanguage == "zh")
func localized(_ zh: String, _ en: String) -> String { chinese ? zh : en }

let panel = NSOpenPanel()
panel.title = localized("选择文件和文件夹", "Choose Files and Folders")
panel.prompt = localized("添加", "Add")
panel.canChooseFiles = true
panel.canChooseDirectories = true
panel.allowsMultipleSelection = !CommandLine.arguments.contains("--single")
if CommandLine.arguments.contains("--files-only") {
    panel.title = panel.allowsMultipleSelection ? localized("选择文件", "Choose Files") : localized("选择文件", "Choose a File")
    panel.canChooseDirectories = false
}
if CommandLine.arguments.contains("--folders-only") {
    panel.title = panel.allowsMultipleSelection ? localized("选择文件夹", "Choose Folders") : localized("选择文件夹", "Choose a Folder")
    panel.canChooseFiles = false
}
if CommandLine.arguments.contains("--work-folder") {
    panel.title = localized("选择工作文件夹", "Choose a Work Folder")
    panel.prompt = localized("选择", "Choose")
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
        FileHandle.standardError.write(Data((localized("无法读取所选项目。请重新选择。", "Couldn’t read the selection. Choose again.") + "\n").utf8))
        exit(1)
    }
}

application.activate(ignoringOtherApps: true)
panel.begin(completionHandler: finish)
application.run()
