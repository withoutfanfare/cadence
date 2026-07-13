import AppKit
import CadenceCore
import Foundation
import SwiftUI

@MainActor
final class StatusItemController: NSObject, NSWindowDelegate {
    private let client: CadenceClient
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let state = PanelState()
    private var overview: Overview?
    private var projectCache: [String: CachedProjectData]
    private var timer: Timer?
    private var isRefreshing = false
    private var lastPanelClose = Date.distantPast
    private var actionFeedbackGeneration = 0

    // A floating panel rather than an NSPopover: popovers have no supported
    // user-resize, a panel resizes from any edge for free.
    private lazy var panel: NSPanel = {
        let panel = NSPanel(
            contentRect: NSRect(origin: .zero, size: Self.loadPanelSize() ?? Self.defaultPanelSize),
            styleMask: [.titled, .fullSizeContentView, .nonactivatingPanel, .resizable],
            backing: .buffered,
            defer: false
        )
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        // Translucent window so the glass (blur-behind) background shows through.
        panel.isOpaque = false
        panel.backgroundColor = .clear
        for button in [NSWindow.ButtonType.closeButton, .miniaturizeButton, .zoomButton] {
            panel.standardWindowButton(button)?.isHidden = true
        }
        panel.isMovable = false
        panel.level = .statusBar
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.animationBehavior = .none
        panel.delegate = self
        let actions = PanelActions(
            cadencePath: client.cadencePath,
            runCommand: { [weak self] command, project, title in
                self?.runCommand(command, project: project, title: title)
            },
            openTerminal: { [weak self] command in
                self?.openTerminal(command)
            },
            refresh: { [weak self] in
                self?.refresh()
            },
            quit: {
                NSApplication.shared.terminate(nil)
            }
        )
        panel.contentViewController = NSHostingController(rootView: PanelView(state: state, actions: actions))
        // Assigning contentViewController makes AppKit shrink the window to the
        // SwiftUI view's ideal (minimum) size — re-apply the intended size after it.
        panel.setContentSize(Self.loadPanelSize() ?? Self.defaultPanelSize)
        return panel
    }()

    private static let defaultPanelSize = NSSize(width: 500, height: 600)

    init(client: CadenceClient) {
        self.client = client
        self.projectCache = Self.loadProjectCache()
        super.init()
        statusItem.button?.toolTip = "Cadence"
        statusItem.button?.imagePosition = .imageLeading
        statusItem.button?.target = self
        statusItem.button?.action = #selector(togglePanel)
    }

    func start() {
        setStatus(symbol: "arrow.triangle.2.circlepath", colourHex: MenuModel.grey, count: 0)
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 120, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
    }

    @objc private func togglePanel() {
        if panel.isVisible {
            closePanel()
            return
        }
        // Clicking the status item while the panel is key resigns it first
        // (closing the panel); without this guard the same click would reopen it.
        guard Date().timeIntervalSince(lastPanelClose) > 0.25 else { return }
        positionPanel()
        refresh()
        panel.makeKeyAndOrderFront(nil)
    }

    private func closePanel() {
        savePanelSize()
        lastPanelClose = Date()
        panel.orderOut(nil)
    }

    // v2: the old popover code saved its collapsed size under "panelSize";
    // a fresh key stops that stale value overriding the 500x600 default.
    private static let panelSizeKey = "panelSizeV2"

    private func savePanelSize() {
        UserDefaults.standard.set(NSStringFromSize(panel.frame.size), forKey: Self.panelSizeKey)
    }

    // Save as soon as a drag-resize ends, so the size survives quitting
    // the app while the panel is still open.
    func windowDidEndLiveResize(_ notification: Notification) {
        guard (notification.object as? NSWindow) === panel else { return }
        savePanelSize()
    }

    // Close when the user clicks anywhere outside the panel.
    func windowDidResignKey(_ notification: Notification) {
        guard (notification.object as? NSWindow) === panel else { return }
        closePanel()
    }

    private func positionPanel() {
        guard let button = statusItem.button, let buttonWindow = button.window else { return }
        let buttonFrame = buttonWindow.convertToScreen(button.convert(button.bounds, to: nil))
        let size = panel.frame.size
        let screen = (buttonWindow.screen ?? NSScreen.main)?.visibleFrame ?? .zero
        var x = buttonFrame.midX - size.width / 2
        x = max(screen.minX + 8, min(x, screen.maxX - size.width - 8))
        let y = buttonFrame.minY - 6 - size.height
        panel.setFrame(NSRect(x: x, y: y, width: size.width, height: size.height), display: true)
    }

    private static func loadPanelSize() -> NSSize? {
        guard let stored = UserDefaults.standard.string(forKey: panelSizeKey) else { return nil }
        let size = NSSizeFromString(stored)
        guard size.width >= 320, size.height >= 220 else { return nil }
        return size
    }

    private func refresh() {
        guard !isRefreshing else { return }
        isRefreshing = true
        Task { @MainActor in
            defer { isRefreshing = false }
            do {
                let overview = try await client.overview()
                self.overview = overview
                for project in overview.projects {
                    refreshProject(project)
                }
                renderSnapshot()
            } catch {
                renderError(error)
            }
        }
    }

    private func refreshProject(_ project: CadenceProject) {
        // Single-flight per project: a refresh (timer tick or panel open) while this
        // project's CLI calls are still running must not stack duplicate subprocesses —
        // each pr-open/revised item costs a `worktree merged` probe with a git fetch.
        guard !state.loadingProjects.contains(project.config) else { return }
        state.loadingProjects.insert(project.config)
        Task { @MainActor in
            defer { state.loadingProjects.remove(project.config) }
            var cache = projectCache[project.config] ?? CachedProjectData()
            do {
                let items = try await client.items(for: project)
                cache.items = items
                cache.itemError = nil
                cache.taskPath = await client.taskPath(for: project)
                var cleanable = Set<String>()
                for item in MenuModel.visibleItems(items)
                    where item.stage.name == "pr-open" || item.stage.name == "revised" {
                    if await client.worktreeMerged(project: project, item: item) {
                        cleanable.insert(actionKey(project: project, item: item))
                    }
                }
                cache.cleanableWorktrees = cleanable
            } catch {
                cache.itemError = shortError(error)
            }
            projectCache[project.config] = cache
            saveProjectCache()
            renderSnapshot()
        }
    }

    private func renderSnapshot() {
        guard let overview else { return }
        var itemsByProject: [String: [CadenceItem]] = [:]
        var taskPaths: [String: String] = [:]
        var itemErrors: [String: String] = [:]
        var cleanable = Set<String>()
        for project in overview.projects {
            guard let cache = projectCache[project.config] else { continue }
            itemsByProject[project.config] = cache.items
            if let taskPath = cache.taskPath {
                taskPaths[project.config] = taskPath
            }
            if let error = cache.itemError {
                itemErrors[project.config] = error
            }
            cleanable.formUnion(cache.cleanableWorktrees)
        }
        state.cleanableWorktrees = cleanable
        state.snapshot = MenuModel.build(
            overview: overview,
            itemsByProject: itemsByProject,
            taskPaths: taskPaths,
            itemErrors: itemErrors
        )
        state.errorText = nil
        state.lastRefresh = Date()
        updateStatusIcon()
    }

    private func renderError(_ error: Error) {
        state.errorText = shortError(error)
        setStatus(symbol: "exclamationmark.triangle.fill", colourHex: MenuModel.red, count: 0)
    }

    private func updateStatusIcon() {
        if let feedback = state.feedback {
            setStatus(symbol: feedback.symbol, colourHex: feedback.colourHex, count: 0, useMenuBarIcon: false)
        } else if let snapshot = state.snapshot {
            setStatus(symbol: snapshot.menuBar.symbol, colourHex: snapshot.menuBar.colourHex, count: snapshot.menuBar.count)
        }
    }

    private func runCommand(_ command: [String], project: CadenceProject, title: String) {
        guard !command.isEmpty else { return }
        let title = title.isEmpty ? "Command" : title
        setActionFeedback(.running(title))
        Task { @MainActor in
            let result: CommandResult
            do {
                result = try await client.runner.run(command)
            } catch {
                logAction(command: command, result: nil, error: error, project: project)
                setActionFeedback(.failed(title, shortError(error)))
                refresh()
                return
            }
            logAction(command: command, result: result, error: nil, project: project)
            if result.exitCode == 0 {
                setActionFeedback(.succeeded(title))
            } else {
                setActionFeedback(.failed(title, commandFailureDetail(result)))
            }
            refresh()
        }
    }

    private func setActionFeedback(_ feedback: ActionFeedback) {
        actionFeedbackGeneration += 1
        let generation = actionFeedbackGeneration
        state.feedback = feedback
        statusItem.button?.toolTip = "Cadence - \(feedback.message)"
        updateStatusIcon()
        guard let delay = feedback.autoClearAfter else { return }
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: delay)
            guard actionFeedbackGeneration == generation else { return }
            state.feedback = nil
            statusItem.button?.toolTip = "Cadence"
            updateStatusIcon()
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

    private func setStatus(symbol: String, colourHex: String, count: Int, useMenuBarIcon: Bool = true) {
        let title = count > 0 ? "\(count)" : ""
        statusItem.button?.title = ""
        statusItem.button?.attributedTitle = NSAttributedString(
            string: title,
            attributes: [.foregroundColor: NSColor.labelColor]
        )
        let colour = NSColor(hex: colourHex)
        let menuImage = useMenuBarIcon ? menuBarImage() : nil
        statusItem.button?.image = menuImage ?? symbolImage(symbol, colour: colour)
        statusItem.button?.contentTintColor = menuImage == nil && statusItem.button?.image?.isTemplate == true ? colour : nil
    }

    private func menuBarImage() -> NSImage? {
        guard let url = Bundle.main.url(forResource: "CadenceMenuBarIcon", withExtension: "svg"),
              let image = NSImage(contentsOf: url)
        else { return nil }
        image.size = NSSize(width: 18, height: 18)
        image.isTemplate = true
        return image
    }

    private func symbolImage(_ name: String, colour: NSColor? = nil) -> NSImage? {
        guard let image = NSImage(systemSymbolName: name, accessibilityDescription: "Cadence") else { return nil }
        guard let colour,
              let configured = image.withSymbolConfiguration(NSImage.SymbolConfiguration(hierarchicalColor: colour))
        else {
            image.isTemplate = true
            return image
        }
        configured.isTemplate = false
        return configured
    }

    private func shortError(_ error: Error) -> String {
        if case let CadenceClientError.commandFailed(_, stderr) = error {
            return stderr.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: "\n").last.map(String.init) ?? "command failed"
        }
        return String(describing: error)
    }

    private func commandFailureDetail(_ result: CommandResult) -> String {
        let detail = (result.stderr.isEmpty ? result.stdout : result.stderr)
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .split(separator: "\n")
            .last
            .map(String.init) ?? "exit \(result.exitCode)"
        return detail.count > 90 ? String(detail.prefix(89)) + "..." : detail
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

    private static func loadProjectCache() -> [String: CachedProjectData] {
        guard let url = cacheURL(),
              let data = try? Data(contentsOf: url),
              let cache = try? JSONDecoder.cadence.decode([String: CachedProjectData].self, from: data)
        else {
            return [:]
        }
        return cache
    }

    private func saveProjectCache() {
        guard let url = Self.cacheURL(),
              let data = try? JSONEncoder.cadence.encode(projectCache)
        else {
            return
        }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: url)
    }

    private static func cacheURL() -> URL? {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?
            .appendingPathComponent("com.withoutfanfare.cadence", isDirectory: true)
            .appendingPathComponent("menu-cache.json")
    }
}

private struct CachedProjectData: Codable {
    var items: [CadenceItem] = []
    var taskPath: String?
    var itemError: String?
    var cleanableWorktrees = Set<String>()
}
