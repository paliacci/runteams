import Foundation
import CryptoKit

struct CommunityBootstrap: Decodable {
    struct Input: Decodable { let path: String; let sha256: String?; let link: String? }
    let schema: String
    let dataDirectory: String?
    let version: String
    let pythonVersion: String
    let inputs: [Input]
    static var resources: URL { Bundle.main.resourceURL!.resolvingSymlinksInPath() }
    var coreDirectory: String { Self.resources.appendingPathComponent("core").path }
    var python: String { Self.resources.appendingPathComponent("core/runtime-dependencies/agent-python/bin/python3").path }
    var packageDirectory: String { Self.resources.appendingPathComponent("python-packages").path }
    enum CodingKeys: String, CodingKey {
        case schema, version, inputs
        case dataDirectory = "data_directory", pythonVersion = "python_version"
    }
    static func read() throws -> CommunityBootstrap {
        guard let file = Bundle.main.url(forResource: "bootstrap", withExtension: "json") else { throw Failure.invalid }
        let value = try JSONDecoder().decode(Self.self, from: Data(contentsOf: file))
        guard value.schema == "runteams.community-desktop/3", !value.inputs.isEmpty,
              FileManager.default.isExecutableFile(atPath: value.python) else { throw Failure.invalid }
        let root = Self.resources
        var expected = Set<String>()
        for input in value.inputs {
            guard !input.path.isEmpty, !input.path.hasPrefix("/"),
                  !input.path.split(separator: "/").contains(where: { $0 == ".." || $0 == "." }),
                  expected.insert(input.path).inserted else { throw Failure.invalid }
            let path = root.appendingPathComponent(input.path)
            guard path.resolvingSymlinksInPath().path.hasPrefix(root.path + "/") else { throw Failure.invalid }
            let info = try path.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey])
            if let link = input.link {
                guard input.sha256 == nil, info.isSymbolicLink == true,
                      try FileManager.default.destinationOfSymbolicLink(atPath: path.path) == link else { throw Failure.damaged }
            } else {
                guard let digest = input.sha256, info.isSymbolicLink != true, info.isRegularFile == true else { throw Failure.invalid }
                let hash = SHA256.hash(data: try Data(contentsOf: path)).map { String(format: "%02x", $0) }.joined()
                guard hash == digest else { throw Failure.damaged }
            }
        }
        var actual = Set<String>()
        guard let files = FileManager.default.enumerator(atPath: root.path) else { throw Failure.invalid }
        for case let relative as String in files {
            let path = root.appendingPathComponent(relative)
            if path.lastPathComponent == "__pycache__" { files.skipDescendants(); continue }
            if relative == "bootstrap.json" { continue }
            let info = try path.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
            if info.isRegularFile == true || info.isSymbolicLink == true { actual.insert(relative) }
        }
        guard expected == actual,
              expected.contains("core/runteams_core/community.py"),
              expected.contains("core/contracts/agent-python.lock.json"),
              expected.contains("python-packages/jsonschema/__init__.py") else { throw Failure.damaged }
        return value
    }
    enum Failure: Error { case invalid, damaged }
    static let pythonEntry = "import sys;sys.path.insert(0,sys.argv.pop(1));sys.path.append(sys.argv.pop(1));from runteams_core.community import main;main(sys.argv[1:])"
}

struct CommunityArguments {
    let dataDirectory: String
    let port: Int
    init(_ arguments: [String], bootstrap: CommunityBootstrap) throws {
        var data = bootstrap.dataDirectory ?? ProcessInfo.processInfo.environment["RUNTEAMS_DATA"]
            ?? (NSHomeDirectory() + "/Library/Application Support/RunTeams.ai/community")
        var port = 0
        var index = 0
        while index < arguments.count {
            guard index + 1 < arguments.count else { throw CommunityBootstrap.Failure.invalid }
            switch arguments[index] {
            case "--data-dir": data = arguments[index + 1]
            case "--port": guard let number = Int(arguments[index + 1]), (0...65535).contains(number) else { throw CommunityBootstrap.Failure.invalid }; port = number
            default: throw CommunityBootstrap.Failure.invalid
            }
            index += 2
        }
        self.dataDirectory = URL(fileURLWithPath: (data as NSString).expandingTildeInPath).resolvingSymlinksInPath().path
        self.port = port
    }
}
