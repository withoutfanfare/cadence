import Foundation
import XCTest
@testable import CadenceCore

final class MenuModelTests: XCTestCase {
    func testFailedOutranksWaitingWorkInMenuBar() {
        let failed = CadenceProject.fixture(name: "bad", config: "/bad", backend: .file, health: .failed)
        let waiting = CadenceProject.fixture(name: "wait", config: "/wait", backend: .file, health: .ok)
        let item = CadenceItem.fixture(id: "TASK-1", stage: ItemStage(name: "pr-open", gate: nil, hold: false, exception: nil, advance: "agent:revise"))

        let snapshot = MenuModel.build(
            overview: Overview(registry: "/r", projects: [failed, waiting], warnings: []),
            itemsByProject: ["/bad": [], "/wait": [item]],
            taskPaths: [:],
            now: Date(timeIntervalSince1970: 0)
        )

        XCTAssertEqual(snapshot.menuBar.symbol, "exclamationmark.triangle.fill")
        XCTAssertEqual(snapshot.menuBar.colourHex, "#d0021b")
        XCTAssertEqual(snapshot.menuBar.count, 1)
    }

    func testWaitingWorkIsAmberNotRed() {
        let project = CadenceProject.fixture(name: "wait", config: "/wait", backend: .file, health: .ok)
        let item = CadenceItem.fixture(id: "TASK-1", stage: ItemStage(name: "revised", gate: nil, hold: false, exception: nil, advance: "agent:revise"))

        let snapshot = MenuModel.build(
            overview: Overview(registry: "/r", projects: [project], warnings: []),
            itemsByProject: ["/wait": [item]],
            taskPaths: [:],
            now: Date(timeIntervalSince1970: 0)
        )

        XCTAssertEqual(snapshot.projects[0].status.symbol, "arrow.right.circle.fill")
        XCTAssertEqual(snapshot.projects[0].status.colourHex, "#e0a000")
        XCTAssertEqual(snapshot.projects[0].sections.map(\.key), ["revised"])
    }

    func testClosedAndSupersededItemsAreHidden() {
        let project = CadenceProject.fixture(name: "p", config: "/p", backend: .file, health: .ok)
        let closed = CadenceItem.fixture(id: "TASK-1", status: "completed", stage: ItemStage(name: "pr-open", gate: nil, hold: false, exception: nil, advance: nil))
        let superseded = CadenceItem.fixture(id: "TASK-2", stage: ItemStage(name: "triaged", gate: nil, hold: false, exception: "superseded", advance: nil))

        let snapshot = MenuModel.build(
            overview: Overview(registry: "/r", projects: [project], warnings: []),
            itemsByProject: ["/p": [closed, superseded]],
            taskPaths: [:],
            now: Date(timeIntervalSince1970: 0)
        )

        XCTAssertEqual(snapshot.menuBar.count, 0)
        XCTAssertTrue(snapshot.projects[0].sections.isEmpty)
    }

    func testSectionCapsAtTwelveAndReportsMore() {
        let project = CadenceProject.fixture(name: "p", config: "/p", backend: .file, health: .ok)
        let items = (1...13).map {
            CadenceItem.fixture(id: "TASK-\($0)", stage: ItemStage(name: "backlog", gate: nil, hold: false, exception: nil, advance: "agent:spec"))
        }

        let snapshot = MenuModel.build(
            overview: Overview(registry: "/r", projects: [project], warnings: []),
            itemsByProject: ["/p": items],
            taskPaths: [:],
            now: Date(timeIntervalSince1970: 0)
        )

        XCTAssertEqual(snapshot.projects[0].sections[0].items.count, 12)
        XCTAssertEqual(snapshot.projects[0].sections[0].totalCount, 13)
        XCTAssertEqual(snapshot.projects[0].sections[0].moreCount, 1)
    }

    func testNeedsAttentionCountsTowardBadge() {
        let project = CadenceProject.fixture(name: "p", config: "/p", backend: .file, health: .ok)
        let item = CadenceItem.fixture(id: "TASK-1", stage: ItemStage(name: "build", gate: nil, hold: false, exception: "needs-attention", advance: nil))

        let snapshot = MenuModel.build(
            overview: Overview(registry: "/r", projects: [project], warnings: []),
            itemsByProject: ["/p": [item]],
            taskPaths: [:],
            now: Date(timeIntervalSince1970: 0)
        )

        XCTAssertEqual(snapshot.menuBar.count, 1)
        XCTAssertEqual(snapshot.projects[0].status.count, 1)
    }

    func testBoardURLDerivedFromItemOrOmitted() {
        let project = CadenceProject.fixture(name: "p", config: "/p", backend: .linear, health: .ok)
        let item = CadenceItem.fixture(
            id: "CAD-1",
            url: "https://linear.app/acme/issue/CAD-1/fix-thing",
            stage: ItemStage(name: "triaged", gate: nil, hold: false, exception: nil, advance: "agent:spec")
        )

        let withItems = MenuModel.build(
            overview: Overview(registry: "/r", projects: [project], warnings: []),
            itemsByProject: ["/p": [item]],
            taskPaths: [:],
            now: Date(timeIntervalSince1970: 0)
        )
        let empty = MenuModel.build(
            overview: Overview(registry: "/r", projects: [project], warnings: []),
            itemsByProject: ["/p": []],
            taskPaths: [:],
            now: Date(timeIntervalSince1970: 0)
        )

        XCTAssertEqual(withItems.projects[0].boardURL, "https://linear.app/acme/")
        XCTAssertNil(empty.projects[0].boardURL)
    }

    func testBoardURLPrefersOverviewValueForEmptyQueues() {
        let project = CadenceProject.fixture(
            name: "p",
            config: "/p",
            backend: .linear,
            health: .ok,
            boardURL: "https://linear.app/acme/"
        )

        let snapshot = MenuModel.build(
            overview: Overview(registry: "/r", projects: [project], warnings: []),
            itemsByProject: ["/p": []],
            taskPaths: [:],
            now: Date(timeIntervalSince1970: 0)
        )

        XCTAssertEqual(snapshot.projects[0].boardURL, "https://linear.app/acme/")
    }

    func testStageControlsIncludeRelativeLastRunAndNextRun() {
        let now = Date(timeIntervalSince1970: 1_750_000_000)
        let project = CadenceProject.fixture(
            name: "p",
            config: "/p",
            backend: .file,
            health: .ok,
            stages: ["triage": StageRun(ts: now.addingTimeInterval(-120), errors: 0, result: "ok")],
            schedule: ["triage": now.addingTimeInterval(600)]
        )

        let snapshot = MenuModel.build(
            overview: Overview(registry: "/r", projects: [project], warnings: []),
            itemsByProject: ["/p": []],
            taskPaths: [:],
            now: now
        )

        XCTAssertEqual(snapshot.projects[0].stages.first, StageControl(name: "triage", detail: "ok · 2m ago · next in 10m"))
    }
}
