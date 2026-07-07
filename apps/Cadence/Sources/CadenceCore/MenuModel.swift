import Foundation

public struct MenuSnapshot: Sendable {
    public let menuBar: StatusBadge
    public let projects: [ProjectMenu]
    public let warnings: [String]
}

public struct StatusBadge: Sendable, Equatable {
    public let symbol: String
    public let colourHex: String
    public let count: Int
}

public struct ProjectMenu: Sendable, Identifiable {
    public var id: String { project.config }
    public let project: CadenceProject
    public let status: StatusBadge
    public let subline: String
    public let sections: [TaskSection]
    public let stages: [StageControl]
    public let taskPath: String?
    public let taskError: String?
    public let boardURL: String?
}

public struct TaskSection: Sendable {
    public let key: String
    public let title: String
    public let items: [CadenceItem]
    public let totalCount: Int
    public let moreCount: Int
}

public struct StageControl: Sendable, Equatable {
    public let name: String
    public let detail: String
}

public enum MenuModel {
    public static let red = "#d0021b"
    public static let amber = "#e0a000"
    public static let green = "#34c759"
    public static let grey = "#8e8e93"

    public static let workStages = ["triage", "spec", "build", "revise"]

    private static let badgeKeys = Set(["needs-human", "needs-attention", "pr-open", "revised"])
    private static let sectionTitles = [
        ("needs-human", "Needs a human decision"),
        ("needs-attention", "Run failed · needs attention"),
        ("pr-open", "PR open · review or merge"),
        ("revised", "Revised · re-review"),
        ("specced", "Specced · grant build"),
        ("triaged", "Triaged · grant spec"),
        ("backlog", "Open · backlog")
    ]
    private static let closed = Set(["done", "completed", "cancelled", "canceled", "closed"])

    public static func build(
        overview: Overview,
        itemsByProject: [String: [CadenceItem]],
        taskPaths: [String: String],
        now: Date = Date(),
        itemErrors: [String: String] = [:]
    ) -> MenuSnapshot {
        let projects = overview.projects.map { project in
            let items = itemsByProject[project.config] ?? []
            let visible = visibleItems(items)
            let grouped = Dictionary(grouping: visible, by: sectionKey)
            let waiting = visible.filter { badgeKeys.contains(sectionKey($0)) }.count
            let sections = sectionTitles.compactMap { key, title -> TaskSection? in
                let sectionItems = grouped[key] ?? []
                guard !sectionItems.isEmpty else { return nil }
                return TaskSection(
                    key: key,
                    title: title,
                    items: Array(sectionItems.prefix(12)),
                    totalCount: sectionItems.count,
                    moreCount: max(0, sectionItems.count - 12)
                )
            }
            return ProjectMenu(
                project: project,
                status: projectStatus(project, waiting: waiting),
                subline: subline(project, waiting: waiting, now: now),
                sections: sections,
                stages: stageControls(project, now: now),
                taskPath: taskPaths[project.config],
                taskError: itemErrors[project.config],
                boardURL: project.boardURL ?? workspaceURL(from: items)
            )
        }

        let count = projects.reduce(0) { $0 + $1.status.count }
        let failed = overview.projects.contains { $0.health == .failed }
        let paused = overview.projects.contains { $0.paused }
        let menuBar: StatusBadge
        if failed {
            menuBar = StatusBadge(symbol: "exclamationmark.triangle.fill", colourHex: red, count: count)
        } else if count > 0 {
            menuBar = StatusBadge(symbol: "arrow.right.circle.fill", colourHex: amber, count: count)
        } else if paused {
            menuBar = StatusBadge(symbol: "pause.circle.fill", colourHex: grey, count: 0)
        } else {
            menuBar = StatusBadge(symbol: "circle.fill", colourHex: green, count: 0)
        }
        return MenuSnapshot(menuBar: menuBar, projects: projects, warnings: overview.warnings)
    }

    public static func visibleItems(_ items: [CadenceItem]) -> [CadenceItem] {
        items.filter { !isClosed($0) && $0.stage.exception != "superseded" }
    }

    public static func sectionKey(_ item: CadenceItem) -> String {
        item.stage.exception ?? item.stage.name
    }

    private static func isClosed(_ item: CadenceItem) -> Bool {
        let status = item.status?.lowercased()
        let stateType = item.stateType?.lowercased()
        return (status.map(closed.contains) ?? false) || (stateType.map(closed.contains) ?? false)
    }

    private static func projectStatus(_ project: CadenceProject, waiting: Int) -> StatusBadge {
        if project.health == .failed {
            return StatusBadge(symbol: "exclamationmark.triangle.fill", colourHex: red, count: waiting)
        }
        if waiting > 0 {
            return StatusBadge(symbol: "arrow.right.circle.fill", colourHex: amber, count: waiting)
        }
        if project.health == .paused {
            return StatusBadge(symbol: "pause.circle.fill", colourHex: grey, count: 0)
        }
        if project.health == .ok {
            return StatusBadge(symbol: "circle.fill", colourHex: green, count: 0)
        }
        return StatusBadge(symbol: "circle", colourHex: grey, count: 0)
    }

    private static func subline(_ project: CadenceProject, waiting: Int, now: Date) -> String {
        var bits: [String] = []
        if waiting > 0 { bits.append("\(waiting) awaiting you") }
        switch project.health {
        case .failed:
            bits.append(contentsOf: ["last run failed", "check logs"])
        case .paused:
            bits.append("paused")
        case .idle:
            if waiting == 0 { bits.append("nothing waiting") }
        case .ok:
            bits.append("active")
        }
        if let relative = RelativeTime.describe(lastActiveDate(project), now: now) {
            bits.append(relative)
        }
        if !project.scheduled { bits.append("not scheduled") }
        return bits.joined(separator: " · ")
    }

    private static func lastActiveDate(_ project: CadenceProject) -> Date? {
        var dates = project.stages.values.compactMap { $0?.ts }
        if let activityDate = activityDate(project.lastActivity) {
            dates.append(activityDate)
        }
        return dates.max()
    }

    private static func activityDate(_ value: String?) -> Date? {
        guard let value,
              let open = value.firstIndex(of: "["),
              let close = value[open...].firstIndex(of: "]")
        else { return nil }
        let stamp = String(value[value.index(after: open)..<close])
        return ISO8601DateFormatter().date(from: stamp)
    }

    private static func stageControls(_ project: CadenceProject, now: Date) -> [StageControl] {
        workStages.map { name in
            var detail = "idle"
            if let run = project.stages[name] ?? nil {
                detail = run.result
                if let relative = RelativeTime.describe(run.ts, now: now) {
                    detail += " · \(relative)"
                }
            }
            if let next = project.schedule[name] ?? nil,
               let until = RelativeTime.until(next, now: now) {
                detail += " · next \(until)"
            }
            return StageControl(name: name, detail: detail)
        }
    }

    private static func workspaceURL(from items: [CadenceItem]) -> String? {
        for item in items {
            guard let value = item.url,
                  let url = URL(string: value),
                  url.host == "linear.app",
                  let workspace = url.path.split(separator: "/").first
            else {
                continue
            }
            return "https://linear.app/\(workspace)/"
        }
        // ponytail: no workspace derivable (empty queue) — omit "Open board" rather
        // than open the generic linear.app home. Better source: a board URL in
        // `cadence overview --json`, if the engine ever exposes one.
        return nil
    }
}
