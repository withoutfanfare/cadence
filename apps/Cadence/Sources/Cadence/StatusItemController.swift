import AppKit
import CadenceCore
import Foundation

@MainActor
final class StatusItemController: NSObject, NSMenuDelegate {
    private let client: CadenceClient
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let menu = NSMenu()
    private let prURLExpression = try! NSRegularExpression(pattern: #"https://github\.com/[^\s)>"'`]+/pull/\d+"#)
    private var snapshot: MenuSnapshot?
    private var cleanableWorktrees = Set<String>()
    private var timer: Timer?
    private var isRefreshing = false

    init(client: CadenceClient) {
        self.client = client
        super.init()
        menu.delegate = self
        statusItem.menu = menu
        statusItem.button?.toolTip = "Cadence"
        statusItem.button?.imagePosition = .imageLeading
    }

    func start() {
        renderLoading()
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 120, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
    }

    func menuWillOpen(_ menu: NSMenu) {
        refresh()
    }

    private func refresh() {
        guard !isRefreshing else { return }
        isRefreshing = true
        Task { @MainActor in
            defer { isRefreshing = false }
            do {
                let overview = try await client.overview()
                var itemsByProject: [String: [CadenceItem]] = [:]
                var taskPaths: [String: String] = [:]
                var itemErrors: [String: String] = [:]
                var cleanable = Set<String>()

                for project in overview.projects {
                    let items: [CadenceItem]
                    do {
                        items = try await client.items(for: project)
                        itemsByProject[project.config] = items
                    } catch {
                        items = []
                        itemsByProject[project.config] = []
                        itemErrors[project.config] = shortError(error)
                    }

                    if let path = await client.taskPath(for: project) {
                        taskPaths[project.config] = path
                    }

                    for item in MenuModel.visibleItems(items)
                        where item.stage.name == "pr-open" || item.stage.name == "revised" {
                        if await client.worktreeMerged(project: project, item: item) {
                            cleanable.insert(actionKey(project: project, item: item))
                        }
                    }
                }

                cleanableWorktrees = cleanable
                snapshot = MenuModel.build(
                    overview: overview,
                    itemsByProject: itemsByProject,
                    taskPaths: taskPaths,
                    itemErrors: itemErrors
                )
                render()
            } catch {
                renderError(error)
            }
        }
    }

    private func renderLoading() {
        setStatus(symbol: "arrow.triangle.2.circlepath", colourHex: MenuModel.grey, count: 0)
        menu.removeAllItems()
        addDisabled("Loading Cadence...", to: menu)
    }

    private func renderError(_ error: Error) {
        setStatus(symbol: "exclamationmark.triangle.fill", colourHex: MenuModel.red, count: 0)
        menu.removeAllItems()
        addDisabled("Cadence unavailable", to: menu)
        addDisabled(shortError(error), to: menu, colour: .systemRed, font: .monospacedSystemFont(ofSize: 11, weight: .regular))
        menu.addItem(.separator())
        addAction("Refresh Now", to: menu, key: "r", kind: .refresh)
        addAction("Quit Cadence", to: menu, key: "q", kind: .quit)
    }

    private func render() {
        guard let snapshot else { return }
        setStatus(symbol: snapshot.menuBar.symbol, colourHex: snapshot.menuBar.colourHex, count: snapshot.menuBar.count)
        menu.removeAllItems()

        if snapshot.projects.isEmpty {
            addDisabled("No registered projects", to: menu, colour: .secondaryLabelColor)
            addDisabled("Register one:", to: menu, colour: .secondaryLabelColor, font: .systemFont(ofSize: 11))
            addDisabled("cadence schedule register <path>", to: menu, colour: .secondaryLabelColor, font: .monospacedSystemFont(ofSize: 11, weight: .regular))
            menu.addItem(.separator())
            addAction("Refresh Now", to: menu, key: "r", kind: .refresh)
            addAction("Quit Cadence", to: menu, key: "q", kind: .quit)
            return
        }

        for (index, project) in snapshot.projects.enumerated() {
            if index > 0 { menu.addItem(.separator()) }
            renderProject(project)
        }

        if !snapshot.warnings.isEmpty {
            menu.addItem(.separator())
            for warning in snapshot.warnings {
                addDisabled("Warning: \(warning)", to: menu, colour: .systemOrange, font: .systemFont(ofSize: 11))
            }
        }

        menu.addItem(.separator())
        addAction("Refresh Now", to: menu, key: "r", kind: .refresh)
        addAction("Quit Cadence", to: menu, key: "q", kind: .quit)
    }

    private func renderProject(_ project: ProjectMenu) {
        let heading = NSMenuItem(title: projectHeading(project), action: nil, keyEquivalent: "")
        heading.image = symbolImage(project.status.symbol)
        heading.attributedTitle = NSAttributedString(
            string: projectHeading(project),
            attributes: [.foregroundColor: NSColor(hex: project.status.colourHex) ?? .labelColor]
        )
        heading.isEnabled = false
        menu.addItem(heading)
        addDisabled(project.subline, to: menu, colour: .secondaryLabelColor, font: .systemFont(ofSize: 12))
        menu.addItem(.separator())

        if let error = project.taskError {
            addDisabled("task list unavailable: \(error)", to: menu, colour: .systemRed, font: .monospacedSystemFont(ofSize: 11, weight: .regular))
        } else if project.sections.isEmpty {
            addDisabled("Nothing awaiting your move", to: menu, colour: .secondaryLabelColor)
        } else {
            for section in project.sections {
                addDisabled("\(section.title) (\(section.totalCount))", to: menu, font: .systemFont(ofSize: 12))
                for item in section.items {
                    let row = NSMenuItem(title: taskTitle(item), action: nil, keyEquivalent: "")
                    row.submenu = taskSubmenu(project: project, item: item)
                    menu.addItem(row)
                }
                if section.moreCount > 0 {
                    addOpenProjectAction("+\(section.moreCount) more", project: project, to: menu)
                }
            }
        }

        menu.addItem(.separator())
        let stages = NSMenuItem(title: "Stages & controls", action: nil, keyEquivalent: "")
        stages.submenu = stagesMenu(project)
        menu.addItem(stages)
    }

    private func taskSubmenu(project: ProjectMenu, item: CadenceItem) -> NSMenu {
        let submenu = NSMenu()
        if item.stage.name == "pr-open" || item.stage.name == "revised" {
            addAction("Set as merged", to: submenu, kind: .command(CadenceActions.markMergedCommand(cadencePath: client.cadencePath, project: project.project, item: item), project.project))
        }
        if cleanableWorktrees.contains(actionKey(project: project.project, item: item)) {
            addAction("Clean up worktree", to: submenu, kind: .command(CadenceActions.worktreeRemoveCommand(cadencePath: client.cadencePath, project: project.project, item: item), project.project))
        }
        if item.stage.advance != nil {
            addAction("Advance to \(advanceTitle(item.stage.advance))", to: submenu, kind: .command(CadenceActions.advanceCommand(cadencePath: client.cadencePath, project: project.project, item: item), project.project))
        }

        let setStage = NSMenuItem(title: "Set stage", action: nil, keyEquivalent: "")
        let stageSubmenu = NSMenu()
        for stage in CadenceActions.SetStage.allCases {
            addAction(stage.title, to: stageSubmenu, kind: .command(CadenceActions.setStageCommand(cadencePath: client.cadencePath, project: project.project, item: item, stage: stage), project.project))
        }
        setStage.submenu = stageSubmenu
        submenu.addItem(setStage)

        if item.stage.hold {
            addAction("Release hold", to: submenu, kind: .command(CadenceActions.releaseHoldCommand(cadencePath: client.cadencePath, project: project.project, item: item), project.project))
        } else {
            addAction("Hold", to: submenu, kind: .command(CadenceActions.holdCommand(cadencePath: client.cadencePath, project: project.project, item: item), project.project))
        }

        if let url = pullRequestURL(in: item) {
            addAction("Open PR", to: submenu, kind: .openURL(url))
        }
        if project.project.backend == .file, let path = project.taskPath {
            addAction("Open tasks.md", to: submenu, kind: .openURL(URL(fileURLWithPath: path)))
        } else if let value = item.url, let url = URL(string: value) {
            addAction("Open in Linear", to: submenu, kind: .openURL(url))
        }
        return submenu
    }

    private func stagesMenu(_ project: ProjectMenu) -> NSMenu {
        let submenu = NSMenu()
        for stage in project.stages {
            let name = stage.name.padding(toLength: 8, withPad: " ", startingAt: 0)
            addDisabled("\(name) \(stage.detail)", to: submenu, font: .monospacedSystemFont(ofSize: 12, weight: .regular))
        }
        addDisabled("Autonomous  \(project.project.autonomous ? "on" : "off")", to: submenu, colour: .secondaryLabelColor, font: .monospacedSystemFont(ofSize: 12, weight: .regular))
        submenu.addItem(.separator())
        if project.project.paused {
            addAction("Resume project", to: submenu, kind: .command(CadenceActions.projectCommand(cadencePath: client.cadencePath, project: project.project, args: ["resume"]), project.project))
        } else {
            addAction("Pause project", to: submenu, kind: .command(CadenceActions.projectCommand(cadencePath: client.cadencePath, project: project.project, args: ["pause"]), project.project))
        }
        for stage in MenuModel.workStages {
            addAction("Run \(stage) now", to: submenu, kind: .terminal(CadenceActions.runStageCommand(cadencePath: client.cadencePath, project: project.project, stage: stage)))
        }
        addAction("View logs", to: submenu, kind: .terminal(CadenceActions.projectCommand(cadencePath: client.cadencePath, project: project.project, args: ["logs"])))
        addOpenProjectAction(project.project.backend == .file ? "Open tasks.md" : "Open board", project: project, to: submenu)
        return submenu
    }

    private func addOpenProjectAction(_ title: String, project: ProjectMenu, to target: NSMenu) {
        if project.project.backend == .file, let path = project.taskPath {
            addAction(title, to: target, kind: .openURL(URL(fileURLWithPath: path)))
        } else if let url = URL(string: project.boardURL) {
            addAction(title, to: target, kind: .openURL(url))
        }
    }

    @discardableResult
    private func addAction(_ title: String, to target: NSMenu, key: String = "", kind: MenuAction.Kind) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: #selector(performMenuAction(_:)), keyEquivalent: key)
        item.target = self
        item.representedObject = MenuAction(kind)
        target.addItem(item)
        return item
    }

    @discardableResult
    private func addDisabled(_ title: String, to target: NSMenu, colour: NSColor = .labelColor, font: NSFont = .systemFont(ofSize: NSFont.systemFontSize)) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.isEnabled = false
        item.attributedTitle = NSAttributedString(string: title, attributes: [.foregroundColor: colour, .font: font])
        target.addItem(item)
        return item
    }

    @objc private func performMenuAction(_ sender: NSMenuItem) {
        guard let action = sender.representedObject as? MenuAction else { return }
        switch action.kind {
        case let .command(command, project):
            runCommand(command, project: project)
        case let .terminal(command):
            openTerminal(command)
        case let .openURL(url):
            NSWorkspace.shared.open(url)
        case .refresh:
            refresh()
        case .quit:
            NSApplication.shared.terminate(nil)
        }
    }

    private func runCommand(_ command: [String], project: CadenceProject) {
        guard !command.isEmpty else { return }
        Task { @MainActor in
            let result: CommandResult
            do {
                result = try await client.runner.run(command)
            } catch {
                logAction(command: command, result: nil, error: error, project: project)
                refresh()
                return
            }
            logAction(command: command, result: result, error: nil, project: project)
            refresh()
        }
    }

    private func openTerminal(_ command: [String]) {
        let shellCommand = command.map(shellQuote).joined(separator: " ")
        let script = """
        tell application "Terminal"
          activate
          do script \(appleScriptQuote(shellCommand))
        end tell
        """
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        try? process.run()
    }

    private func logAction(command: [String], result: CommandResult?, error: Error?, project: CadenceProject) {
        let dir = URL(fileURLWithPath: project.stateDir).appendingPathComponent("logs", isDirectory: true)
        let file = dir.appendingPathComponent("cadence-app.log")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var line = "[\(ISO8601DateFormatter().string(from: Date()))] \(command.map(shellQuote).joined(separator: " "))"
        if let result {
            line += " exit=\(result.exitCode)"
            let detail = (result.stderr.isEmpty ? result.stdout : result.stderr).trimmingCharacters(in: .whitespacesAndNewlines)
            if !detail.isEmpty { line += " \(detail.prefix(500))" }
        }
        if let error {
            line += " error=\(shortError(error))"
        }
        line += "\n"
        if let data = line.data(using: .utf8) {
            if FileManager.default.fileExists(atPath: file.path),
               let handle = try? FileHandle(forWritingTo: file) {
                _ = try? handle.seekToEnd()
                try? handle.write(contentsOf: data)
                try? handle.close()
            } else {
                try? data.write(to: file)
            }
        }
    }

    private func setStatus(symbol: String, colourHex: String, count: Int) {
        statusItem.button?.title = count > 0 ? "\(count)" : ""
        statusItem.button?.image = symbolImage(symbol)
        statusItem.button?.contentTintColor = NSColor(hex: colourHex)
    }

    private func symbolImage(_ name: String) -> NSImage? {
        let image = NSImage(systemSymbolName: name, accessibilityDescription: "Cadence")
        image?.isTemplate = true
        return image
    }

    private func projectHeading(_ project: ProjectMenu) -> String {
        var title = project.project.name
        if let team = project.project.teamName {
            title += " - \(team)"
        }
        if project.project.backend == .file {
            title += " - file"
        }
        return title
    }

    private func taskTitle(_ item: CadenceItem) -> String {
        var title = item.title.replacingOccurrences(of: "|", with: "/")
        if title.count > 49 {
            title = String(title.prefix(48)) + "..."
        }
        var bits: [String] = []
        if let gate = item.stage.gate { bits.append("\(gate) queued") }
        if item.stage.hold { bits.append("on hold") }
        let marker = bits.isEmpty ? "" : " - " + bits.joined(separator: ", ")
        return "\(item.identifier)  \(title)\(marker)"
    }

    private func pullRequestURL(in item: CadenceItem) -> URL? {
        let text = [item.description, item.body].compactMap { $0 }.joined(separator: "\n")
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        guard let match = prURLExpression.firstMatch(in: text, range: range),
              let swiftRange = Range(match.range, in: text)
        else { return nil }
        return URL(string: String(text[swiftRange]))
    }

    private func advanceTitle(_ label: String?) -> String {
        switch label {
        case "agent:spec": return "Spec"
        case "agent:build": return "Build"
        case "agent:revise": return "Revise"
        default: return label ?? "next stage"
        }
    }

    private func shortError(_ error: Error) -> String {
        if case let CadenceClientError.commandFailed(_, stderr) = error {
            return stderr.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: "\n").last.map(String.init) ?? "command failed"
        }
        return String(describing: error)
    }

    private func actionKey(project: CadenceProject, item: CadenceItem) -> String {
        "\(project.config)\u{1f}\(item.identifier)"
    }

    private func shellQuote(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    private func appleScriptQuote(_ value: String) -> String {
        "\"" + value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
            + "\""
    }
}

private final class MenuAction: NSObject {
    enum Kind {
        case command([String], CadenceProject)
        case terminal([String])
        case openURL(URL)
        case refresh
        case quit
    }

    let kind: Kind

    init(_ kind: Kind) {
        self.kind = kind
    }
}

private extension NSColor {
    convenience init?(hex: String) {
        let value = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        guard value.count == 6, let intValue = Int(value, radix: 16) else { return nil }
        self.init(
            calibratedRed: CGFloat((intValue >> 16) & 0xff) / 255,
            green: CGFloat((intValue >> 8) & 0xff) / 255,
            blue: CGFloat(intValue & 0xff) / 255,
            alpha: 1
        )
    }
}
