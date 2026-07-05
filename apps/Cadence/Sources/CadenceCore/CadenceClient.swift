import Foundation
import Darwin

public struct CommandResult: Sendable {
    public let stdout: String
    public let stderr: String
    public let exitCode: Int32
}

public protocol CommandRunning: Sendable {
    func run(_ command: [String]) async throws -> CommandResult
}

public struct ProcessRunner: CommandRunning {
    private let timeout: TimeInterval

    public init(timeout: TimeInterval = 30) {
        self.timeout = timeout
    }

    public func run(_ command: [String]) async throws -> CommandResult {
        try await Task.detached(priority: .utility) {
            let process = Process()
            let token = UUID().uuidString
            let stdoutURL = FileManager.default.temporaryDirectory.appendingPathComponent("cadence-\(token).out")
            let stderrURL = FileManager.default.temporaryDirectory.appendingPathComponent("cadence-\(token).err")
            FileManager.default.createFile(atPath: stdoutURL.path, contents: nil)
            FileManager.default.createFile(atPath: stderrURL.path, contents: nil)
            let stdout = try FileHandle(forWritingTo: stdoutURL)
            let stderr = try FileHandle(forWritingTo: stderrURL)
            defer {
                try? stdout.close()
                try? stderr.close()
                try? FileManager.default.removeItem(at: stdoutURL)
                try? FileManager.default.removeItem(at: stderrURL)
            }
            func output(_ url: URL, handle: FileHandle) -> String {
                try? handle.close()
                return (try? String(contentsOf: url, encoding: .utf8)) ?? ""
            }
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = command
            process.standardOutput = stdout
            process.standardError = stderr
            process.environment = Self.environment()
            try process.run()
            let deadline = Date().addingTimeInterval(timeout)
            while process.isRunning {
                if Date() >= deadline {
                    process.terminate()
                    for _ in 0..<10 where process.isRunning {
                        usleep(100_000)
                    }
                    if process.isRunning {
                        kill(process.processIdentifier, SIGKILL)
                    }
                    process.waitUntilExit()
                    let out = output(stdoutURL, handle: stdout)
                    let err = output(stderrURL, handle: stderr)
                    let message = "timed out after \(Self.describe(timeout))"
                    return CommandResult(
                        stdout: out,
                        stderr: err.isEmpty ? message : "\(err.trimmingCharacters(in: .whitespacesAndNewlines))\n\(message)",
                        exitCode: 124
                    )
                }
                usleep(50_000)
            }
            let out = output(stdoutURL, handle: stdout)
            let err = output(stderrURL, handle: stderr)
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

    private static func describe(_ timeout: TimeInterval) -> String {
        timeout >= 1 ? "\(Int(timeout))s" : String(format: "%.1fs", timeout)
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
