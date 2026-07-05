import Foundation
import XCTest
@testable import CadenceCore

final class CadenceClientTests: XCTestCase {
    func testDecodesOverviewProjectShapeUsedBySwiftBar() throws {
        let json = """
        {
          "registry": "/Users/me/.cadence/projects.json",
          "projects": [{
            "name": "notes",
            "project": "/repo/notes",
            "config": "/repo/notes/cadence/.env",
            "state_dir": "/Users/me/.cadence/projects/notes",
            "team_name": "Product",
            "backend": "file",
            "scheduled": true,
            "autonomous": false,
            "paused": false,
            "health": "ok",
            "stages": { "triage": { "ts": "2026-07-05T10:00:00Z", "errors": 0, "result": "ok" } },
            "schedule": { "triage": "2026-07-05T10:10:00Z" },
            "last_activity": "[2026-07-05T10:00:00Z] triage - ok"
          }],
          "warnings": []
        }
        """.data(using: .utf8)!

        let overview = try JSONDecoder.cadence.decode(Overview.self, from: json)
        XCTAssertEqual(overview.projects.count, 1)
        XCTAssertEqual(overview.projects[0].name, "notes")
        XCTAssertEqual(overview.projects[0].backend, .file)
        XCTAssertEqual(overview.projects[0].health, .ok)
        XCTAssertEqual(overview.projects[0].stages["triage"]??.result, "ok")
    }

    func testDecodesTaskStageShapeUsedByMenuActions() throws {
        let json = """
        [{
          "identifier": "TASK-1",
          "title": "Ship native app",
          "status": "open",
          "url": "https://linear.app/example/issue/TASK-1",
          "labels": ["agent:specced"],
          "stage": { "name": "specced", "gate": null, "hold": false, "exception": null, "advance": "agent:build" }
        }]
        """.data(using: .utf8)!

        let items = try JSONDecoder.cadence.decode([CadenceItem].self, from: json)
        XCTAssertEqual(items[0].identifier, "TASK-1")
        XCTAssertEqual(items[0].stage.name, "specced")
        XCTAssertEqual(items[0].stage.advance, "agent:build")
    }

    func testOverviewShellsOutToCadenceJson() async throws {
        let runner = FakeRunner(output: #"{"registry":"/r","projects":[],"warnings":[]}"#)
        let client = CadenceClient(cadencePath: "/usr/local/bin/cadence", runner: runner)

        let overview = try await client.overview()

        XCTAssertTrue(overview.projects.isEmpty)
        let commands = await runner.commands
        XCTAssertEqual(commands, [["/usr/local/bin/cadence", "overview", "--json"]])
    }

    func testItemsUseProjectConfigAndBackend() async throws {
        let runner = FakeRunner(output: "[]")
        let client = CadenceClient(cadencePath: "cadence", runner: runner)
        let project = CadenceProject.fixture(config: "/p/cadence/.env", backend: .file)

        _ = try await client.items(for: project)

        let commands = await runner.commands
        XCTAssertEqual(commands, [["cadence", "--config", "/p/cadence/.env", "tasks", "list"]])
    }
}

private actor FakeRunner: CommandRunning {
    var commands: [[String]] = []
    let output: String

    init(output: String) {
        self.output = output
    }

    func run(_ command: [String]) async throws -> CommandResult {
        commands.append(command)
        return CommandResult(stdout: output, stderr: "", exitCode: 0)
    }
}
