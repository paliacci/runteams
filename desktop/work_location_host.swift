import AppKit
import Foundation

func writeJSON(_ payload: [String: Any]) throws {
    let data = try JSONSerialization.data(withJSONObject: payload, options: [])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

func fail(_ message: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(code)
}

func resolveBookmark(_ path: String) throws -> (URL, Bool) {
    let data = try Data(contentsOf: URL(fileURLWithPath: path))
    var stale = false
    do {
        let url = try URL(
            resolvingBookmarkData: data,
            options: [.withSecurityScope],
            relativeTo: nil,
            bookmarkDataIsStale: &stale
        )
        return (url, stale)
    } catch {
        // Development/ad-hoc builds can produce a regular bookmark even when
        // withSecurityScope was requested. It still represents explicit user
        // selection; production signed builds resolve through the scoped path.
        stale = false
        let url = try URL(
            resolvingBookmarkData: data,
            options: [],
            relativeTo: nil,
            bookmarkDataIsStale: &stale
        )
        return (url, stale)
    }
}

let arguments = Array(CommandLine.arguments.dropFirst())
guard let command = arguments.first else { fail("缺少工作位置命令") }

if command == "pick" {
    let application = NSApplication.shared
    application.setActivationPolicy(.accessory)
    let panel = NSOpenPanel()
    panel.title = "选择 AI 员工的工作文件夹"
    panel.prompt = "选择"
    panel.message = "以后这名 AI 员工会直接在所选位置处理文件"
    panel.canChooseFiles = false
    panel.canChooseDirectories = true
    panel.allowsMultipleSelection = false
    panel.resolvesAliases = true
    application.activate(ignoringOtherApps: true)
    guard panel.runModal() == .OK, let url = panel.url else {
        try? writeJSON(["cancelled": true])
        exit(0)
    }
    do {
        let bookmark = try url.bookmarkData(
            options: [.withSecurityScope],
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        )
        try writeJSON([
            "cancelled": false,
            "path": url.path,
            "display_name": url.lastPathComponent,
            "bookmark": bookmark.base64EncodedString()
        ])
    } catch {
        fail("无法保存这个文件夹的持久授权：\(error.localizedDescription)")
    }
    exit(0)
}

guard arguments.count >= 2 else { fail("缺少工作位置授权文件") }
let bookmarkPath = arguments[1]

if command == "resolve" {
    do {
        let (url, stale) = try resolveBookmark(bookmarkPath)
        let allowed = url.startAccessingSecurityScopedResource()
        defer { if allowed { url.stopAccessingSecurityScopedResource() } }
        guard allowed || FileManager.default.isReadableFile(atPath: url.path) else {
            fail("工作文件夹授权已失效")
        }
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            fail("工作文件夹已不存在")
        }
        try writeJSON(["path": url.path, "stale": stale])
    } catch {
        fail("无法恢复工作文件夹授权：\(error.localizedDescription)")
    }
    exit(0)
}

if command == "list" {
    do {
        let (url, stale) = try resolveBookmark(bookmarkPath)
        guard !stale else { fail("工作文件夹授权已过期，请重新选择") }
        let allowed = url.startAccessingSecurityScopedResource()
        defer { if allowed { url.stopAccessingSecurityScopedResource() } }
        guard allowed || FileManager.default.isReadableFile(atPath: url.path) else {
            fail("工作文件夹授权已失效，请重新选择")
        }
        let keys: [URLResourceKey] = [.isRegularFileKey, .isSymbolicLinkKey]
        guard let enumerator = FileManager.default.enumerator(
            at: url, includingPropertiesForKeys: keys,
            options: [.skipsHiddenFiles, .skipsPackageDescendants]
        ) else { fail("无法读取工作文件夹") }
        var files: [String] = []
        for case let child as URL in enumerator {
            let values = try child.resourceValues(forKeys: Set(keys))
            if values.isSymbolicLink == true {
                enumerator.skipDescendants()
                continue
            }
            if values.isRegularFile == true {
                let rootPath = url.standardizedFileURL.path
                let childPath = child.standardizedFileURL.path
                if childPath.hasPrefix(rootPath + "/") {
                    files.append(String(childPath.dropFirst(rootPath.count + 1)))
                    if files.count >= 10000 { break }
                }
            }
        }
        try writeJSON(["files": files])
    } catch {
        fail("无法列出工作文件夹内容：\(error.localizedDescription)")
    }
    exit(0)
}

if command == "copy-out" {
    guard arguments.count >= 4 else { fail("缺少交付文件参数") }
    let relative = arguments[2]
    let destination = arguments[3]
    let components = NSString(string: relative).pathComponents
    guard !NSString(string: relative).isAbsolutePath,
          !components.contains(".."), !components.contains("."), !relative.isEmpty else {
        fail("交付文件路径无效")
    }
    do {
        let (url, stale) = try resolveBookmark(bookmarkPath)
        guard !stale else { fail("工作文件夹授权已过期，请重新选择") }
        let allowed = url.startAccessingSecurityScopedResource()
        defer { if allowed { url.stopAccessingSecurityScopedResource() } }
        guard allowed || FileManager.default.isReadableFile(atPath: url.path) else {
            fail("工作文件夹授权已失效，请重新选择")
        }
        let root = url.resolvingSymlinksInPath().standardizedFileURL
        let source = url.appendingPathComponent(relative).resolvingSymlinksInPath().standardizedFileURL
        guard source.path.hasPrefix(root.path + "/") else { fail("交付文件超出工作文件夹") }
        let values = try source.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true else {
            fail("交付文件不存在或是符号链接")
        }
        let target = URL(fileURLWithPath: destination)
        if FileManager.default.fileExists(atPath: target.path) {
            try FileManager.default.removeItem(at: target)
        }
        try FileManager.default.copyItem(at: source, to: target)
        try writeJSON(["ok": true])
    } catch {
        fail("无法复制交付文件：\(error.localizedDescription)")
    }
    exit(0)
}

if command == "run" {
    guard let separator = arguments.firstIndex(of: "--"), separator + 1 < arguments.count else {
        fail("缺少要运行的 Agent 命令")
    }
    let childArguments = Array(arguments[(separator + 1)...])
    do {
        let (url, stale) = try resolveBookmark(bookmarkPath)
        guard !stale else { fail("工作文件夹授权已过期，请重新选择") }
        let allowed = url.startAccessingSecurityScopedResource()
        defer { if allowed { url.stopAccessingSecurityScopedResource() } }
        guard allowed || FileManager.default.isReadableFile(atPath: url.path) else {
            fail("工作文件夹授权已失效，请重新选择")
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: childArguments[0])
        process.arguments = Array(childArguments.dropFirst())
        process.currentDirectoryURL = url
        process.environment = ProcessInfo.processInfo.environment
        process.standardInput = FileHandle.standardInput
        process.standardOutput = FileHandle.standardOutput
        process.standardError = FileHandle.standardError
        try process.run()
        process.waitUntilExit()
        exit(process.terminationStatus)
    } catch {
        fail("无法在指定工作文件夹启动 Agent：\(error.localizedDescription)")
    }
}

fail("不支持的工作位置命令")
