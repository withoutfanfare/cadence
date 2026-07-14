import XCTest
@testable import CadenceCore

final class CadenceActionsTests: XCTestCase {
    func testAdvanceBuildForFileTaskUsesTasksUpdate() {
        let project = CadenceProject.fixture(name: "p", config: "/p/cadence/.env", backend: .file, health: .ok)
        let item = CadenceItem.fixture(id: "TASK-1", stage: ItemStage(name: "specced", gate: nil, hold: false, exception: nil, advance: "agent:build"))

        let command = CadenceActions.advanceCommand(cadencePath: "cadence", project: project, item: item)

        XCTAssertEqual(command, [
            "cadence", "--config", "/p/cadence/.env", "tasks", "update", "TASK-1",
            "--add-label", "agent:build",
            "--remove-label", "agent:spec",
            "--remove-label", "agent:revise"
        ])
    }

    func testMarkMergedForLinearIssueUsesStateTypeCompleted() {
        let project = CadenceProject.fixture(name: "p", config: "/p/cadence/.env", backend: .linear, health: .ok)
        let item = CadenceItem.fixture(id: "CAD-1", stage: ItemStage(name: "pr-open", gate: nil, hold: false, exception: nil, advance: "agent:revise"))

        let command = CadenceActions.markMergedCommand(cadencePath: "cadence", project: project, item: item)

        XCTAssertEqual(command, [
            "cadence", "--config", "/p/cadence/.env", "linear", "issue-update", "CAD-1",
            "--remove-label", "agent:pr-open",
            "--remove-label", "agent:revised",
            "--state-type", "completed"
        ])
    }

    func testSetStageTriageClearsAllStatusAndGateLabels() {
        let project = CadenceProject.fixture(name: "p", config: "/p/cadence/.env", backend: .file, health: .ok)
        let item = CadenceItem.fixture(id: "TASK-1", stage: ItemStage(name: "specced", gate: nil, hold: false, exception: nil, advance: nil))

        let command = CadenceActions.setStageCommand(cadencePath: "cadence", project: project, item: item, stage: .triage)

        XCTAssertEqual(command, [
            "cadence", "--config", "/p/cadence/.env", "tasks", "update", "TASK-1",
            "--remove-label", "agent:triaged",
            "--remove-label", "agent:specced",
            "--remove-label", "agent:pr-open",
            "--remove-label", "agent:revised",
            "--remove-label", "agent:spec",
            "--remove-label", "agent:build",
            "--remove-label", "agent:revise"
        ])
    }

    func testHoldAndReleaseUseBackendUpdate() {
        let project = CadenceProject.fixture(name: "p", config: "/p/cadence/.env", backend: .linear, health: .ok)
        let item = CadenceItem.fixture(id: "CAD-1", stage: ItemStage(name: "backlog", gate: nil, hold: false, exception: nil, advance: nil))

        XCTAssertEqual(CadenceActions.holdCommand(cadencePath: "cadence", project: project, item: item), [
            "cadence", "--config", "/p/cadence/.env", "linear", "issue-update", "CAD-1",
            "--add-label", "agent:hold"
        ])
        XCTAssertEqual(CadenceActions.releaseHoldCommand(cadencePath: "cadence", project: project, item: item), [
            "cadence", "--config", "/p/cadence/.env", "linear", "issue-update", "CAD-1",
            "--remove-label", "agent:hold"
        ])
    }

    func testProjectAndWorktreeCommands() {
        let project = CadenceProject.fixture(name: "p", config: "/p/cadence/.env", backend: .file, health: .ok)
        let item = CadenceItem.fixture(id: "TASK-1", stage: ItemStage(name: "revised", gate: nil, hold: false, exception: nil, advance: nil))

        XCTAssertEqual(CadenceActions.projectCommand(cadencePath: "cadence", project: project, args: ["pause"]), [
            "cadence", "--config", "/p/cadence/.env", "pause"
        ])
        XCTAssertEqual(CadenceActions.runStageCommand(cadencePath: "cadence", project: project, stage: "build"), [
            "cadence", "--config", "/p/cadence/.env", "run", "build"
        ])
        XCTAssertEqual(CadenceActions.worktreeRemoveCommand(cadencePath: "cadence", project: project, item: item), [
            "cadence", "--config", "/p/cadence/.env", "worktree", "remove", "task-1", "--if-merged"
        ])
    }

    func testAutonomousCommandTogglesCurrentProjectState() {
        let off = CadenceProject.fixture(name: "p", config: "/p/cadence/.env", backend: .file, health: .ok)
        let on = CadenceProject.fixture(name: "p", config: "/p/cadence/.env", backend: .file, health: .ok, autonomous: true)

        XCTAssertEqual(CadenceActions.autonomousCommand(cadencePath: "cadence", project: off), [
            "cadence", "--config", "/p/cadence/.env", "autonomous", "on"
        ])
        XCTAssertEqual(CadenceActions.autonomousCommand(cadencePath: "cadence", project: on), [
            "cadence", "--config", "/p/cadence/.env", "autonomous", "off"
        ])
    }
}
