import Foundation

public struct CommandResult: Sendable {
    public let stdout: String
    public let stderr: String
    public let exitCode: Int32
}

public protocol CommandRunning: Sendable {
    func run(_ command: [String]) async throws -> CommandResult
}

public struct ProcessRunner: CommandRunning {
    public init() {}

    public func run(_ command: [String]) async throws -> CommandResult {
        try await Task.detached(priority: .utility) {
            let process = Process()
            let stdout = Pipe()
            let stderr = Pipe()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = command
            process.standardOutput = stdout
            process.standardError = stderr
            process.environment = Self.environment()
            try process.run()
            process.waitUntilExit()
            let out = String(data: stdout.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            let err = String(data: stderr.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            return CommandResult(stdout: out, stderr: err, exitCode: process.terminationStatus)
        }.value
    }

    private static func environment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = [
            "\(NSHomeDirectory())/.local/bin",
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            env["PATH"] ?? ""
        ].joined(separator: ":")
        return env
    }
}

public struct CadenceClient: Sendable {
    public let cadencePath: String
    public let runner: CommandRunning

    public init(cadencePath: String = "cadence", runner: CommandRunning = ProcessRunner()) {
        self.cadencePath = cadencePath
        self.runner = runner
    }

    public func overview() async throws -> Overview {
        try await decode(Overview.self, from: [cadencePath, "overview", "--json"])
    }

    public func items(for project: CadenceProject) async throws -> [CadenceItem] {
        let verb = project.backend == .file ? "tasks" : "linear"
        let subcommand = project.backend == .file ? "list" : "issues-list"
        return try await decode([CadenceItem].self, from: [
            cadencePath, "--config", project.config, verb, subcommand
        ])
    }

    public func taskPath(for project: CadenceProject) async -> String? {
        guard project.backend == .file else { return nil }
        let result = try? await runner.run([cadencePath, "--config", project.config, "tasks", "path"])
        guard result?.exitCode == 0 else { return nil }
        let path = result?.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        return path?.isEmpty == false ? path : nil
    }

    public func worktreeMerged(project: CadenceProject, item: CadenceItem) async -> Bool {
        let result = try? await runner.run([
            cadencePath, "--config", project.config, "worktree", "merged", branchName(for: item)
        ])
        return result?.exitCode == 0
    }

    private func decode<T: Decodable>(_ type: T.Type, from command: [String]) async throws -> T {
        let result = try await runner.run(command)
        guard result.exitCode == 0 else {
            throw CadenceClientError.commandFailed(command: command, stderr: result.stderr)
        }
        let data = Data(result.stdout.utf8)
        return try JSONDecoder.cadence.decode(T.self, from: data)
    }
}

public enum CadenceClientError: Error, Equatable {
    case commandFailed(command: [String], stderr: String)
}

public func branchName(for item: CadenceItem) -> String {
    item.identifier.lowercased()
}
