import AppKit
import CadenceCore
import SwiftUI

@MainActor
final class PanelState: ObservableObject {
    @Published var snapshot: MenuSnapshot?
    @Published var loadingProjects: Set<String> = []
    @Published var cleanableWorktrees: Set<String> = []
    @Published var feedback: ActionFeedback?
    @Published var errorText: String?
    @Published var showingHelp = false
    @Published var expandedTask: String?
    @Published var expandedProjects: Set<String> = Set(UserDefaults.standard.stringArray(forKey: "expandedProjects") ?? []) {
        didSet { UserDefaults.standard.set(Array(expandedProjects), forKey: "expandedProjects") }
    }
    @Published var lastRefresh: Date?
}

struct PanelActions {
    let cadencePath: String
    let runCommand: ([String], CadenceProject, String) -> Void
    let openTerminal: ([String]) -> Void
    let refresh: () -> Void
    let quit: () -> Void
}

struct ActionFeedback {
    let message: String
    let symbol: String
    let colourHex: String
    let autoClearAfter: UInt64?

    static func running(_ title: String) -> ActionFeedback {
        ActionFeedback(message: "\(title) started", symbol: "hourglass", colourHex: MenuModel.amber, autoClearAfter: nil)
    }

    static func succeeded(_ title: String) -> ActionFeedback {
        ActionFeedback(message: "\(title) completed", symbol: "checkmark.circle.fill", colourHex: MenuModel.green, autoClearAfter: 8_000_000_000)
    }

    static func failed(_ title: String, _ detail: String) -> ActionFeedback {
        ActionFeedback(message: "\(title) failed: \(detail)", symbol: "xmark.circle.fill", colourHex: MenuModel.red, autoClearAfter: 12_000_000_000)
    }
}

func actionKey(project: CadenceProject, item: CadenceItem) -> String {
    "\(project.config)\u{1f}\(item.identifier)"
}

/// Slate palette — blue-leaning greys for the panel chrome, laid over glass.
enum PanelPalette {
    /// Translucent slate tint over the blur; low enough for the glass to read.
    /// Hues sit between slate and neutral grey — cool, but not blue/indigo.
    static func tint(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? colour("#0a0c11").opacity(0.5) : colour("#f3f4f6").opacity(0.4)
    }

    static func card(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? colour("#0a0c11").opacity(0.6) : colour("#d1d5db").opacity(0.55)
    }
}

/// Frosted blur of the content behind the window (the "glass").
private struct GlassBackground: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .hudWindow
        view.blendingMode = .behindWindow
        view.state = .active
        return view
    }

    func updateNSView(_ view: NSVisualEffectView, context: Context) {}
}

struct PanelView: View {
    @ObservedObject var state: PanelState
    @Environment(\.colorScheme) private var scheme
    let actions: PanelActions

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()

            if state.showingHelp {
                helpContent
            } else {
                if let feedback = state.feedback {
                    HStack(spacing: 6) {
                        Image(systemName: feedback.symbol)
                            .foregroundColor(colour(feedback.colourHex))
                        Text(feedback.message)
                            .font(.callout)
                            .foregroundColor(.secondary)
                            .lineLimit(2)
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    Divider()
                }

                Group {
                    if let error = state.errorText {
                        errorContent(error)
                    } else if let snapshot = state.snapshot {
                        mainContent(snapshot)
                    } else {
                        VStack {
                            Spacer()
                            ProgressView()
                            Text("Loading Cadence...")
                                .font(.caption)
                                .foregroundColor(.secondary)
                                .padding(.top, 6)
                            Spacer()
                        }
                        .frame(height: 120)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            }

            Divider()
            HStack {
                Button(state.showingHelp ? "Back to Cadence" : "Refresh Now") {
                    if state.showingHelp {
                        state.showingHelp = false
                    } else {
                        actions.refresh()
                    }
                }
                Spacer()
                Button("Quit Cadence") { actions.quit() }
            }
            .controlSize(.small)
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
        }
        // Flexible bounds make the panel user-resizable; the window size itself
        // is set and remembered by StatusItemController.
        .frame(minWidth: 320, maxWidth: .infinity, minHeight: 220, maxHeight: .infinity)
        .background(GlassBackground().overlay(PanelPalette.tint(scheme)))
        // The window's title bar is hidden, so reclaim its reserved strip for the header.
        .ignoresSafeArea(.container, edges: .top)
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text("Cadence")
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(.primary)
            Text(state.showingHelp ? "How it works" : summary)
                .font(.caption)
                .foregroundColor(.secondary)
                .lineLimit(1)
            Spacer(minLength: 8)
            if !state.showingHelp, let projects = state.snapshot?.projects, !projects.isEmpty {
                Button("Expand all") { state.expandedProjects = Set(projects.map(\.id)) }
                Button("Collapse all") { state.expandedProjects = [] }
            }
        }
        .font(.caption)
        .buttonStyle(.plain)
        .foregroundColor(.secondary)
        .padding(.horizontal, 14)
        .padding(.top, 10)
        .padding(.bottom, 7)
    }

    private var summary: String {
        guard let snapshot = state.snapshot else { return "" }
        var bits: [String] = []
        if snapshot.menuBar.count > 0 { bits.append("\(snapshot.menuBar.count) awaiting") }
        bits.append("\(snapshot.projects.count) project\(snapshot.projects.count == 1 ? "" : "s")")
        if let refreshed = RelativeTime.describe(state.lastRefresh) {
            bits.append("refreshed \(refreshed)")
        }
        return bits.joined(separator: " · ")
    }

    private var helpContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Cadence is a human-gated agent loop. Agents do the work, but you decide when each task moves forward.")
                    .font(.callout)
                    .fixedSize(horizontal: false, vertical: true)

                helpSection(
                    "The workflow",
                    systemImage: "arrow.triangle.2.circlepath",
                    text: "Tasks move through triage → spec → build → revise. Cadence runs only the stage you have authorised, then waits for your next decision."
                )
                helpSection(
                    "Using the menu-bar app",
                    systemImage: "menubar.rectangle",
                    text: "Left-click the Cadence icon for the detailed project panel. Right-click for overall status. Expand a project or task to see its controls, open its board or task file, and act on work awaiting you."
                )
                helpSection(
                    "Status colours",
                    systemImage: "circle.lefthalf.filled",
                    text: "Green is running and healthy. Grey is paused or idle. Amber means a human decision is waiting. Red means a run failed and needs attention."
                )
                helpSection(
                    "Project controls",
                    systemImage: "pause.circle",
                    text: "Pause stops scheduled and manual runs for that project. Autonomous mode lets Cadence select ready, unblocked work and grant its next gate. “Run now” opens the selected stage command in Terminal so the live action stays visible."
                )
                helpSection(
                    "Safety boundaries",
                    systemImage: "hand.raised",
                    text: "The app uses the Cadence CLI as its source of truth. It can apply a gate only from your click, creates draft pull requests, and never marks a pull request ready or merges it for you."
                )
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func helpSection(_ title: String, systemImage: String, text: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Label(title, systemImage: systemImage)
                .font(.headline)
            Text(text)
                .font(.callout)
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func errorContent(_ error: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Label("Cadence unavailable", systemImage: "exclamationmark.triangle.fill")
                .foregroundColor(.orange)
            Text(error)
                .font(.system(size: 11, design: .monospaced))
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
    }

    @ViewBuilder
    private func mainContent(_ snapshot: MenuSnapshot) -> some View {
        if snapshot.projects.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text("No registered projects").foregroundColor(.secondary)
                Text("Register one:").font(.caption).foregroundColor(.secondary)
                Text("cadence schedule register <path>")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(.secondary)
                    .textSelection(.enabled)
                ForEach(Array(snapshot.warnings.enumerated()), id: \.offset) { _, warning in
                    Label(warning, systemImage: "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundColor(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(snapshot.projects) { project in
                        ProjectPanelSection(project: project, state: state, actions: actions)
                    }
                    if !snapshot.warnings.isEmpty {
                        VStack(alignment: .leading, spacing: 2) {
                            // Enumerated offsets keep duplicate warning strings distinct rows.
                            ForEach(Array(snapshot.warnings.enumerated()), id: \.offset) { _, warning in
                                Label(warning, systemImage: "exclamationmark.triangle")
                                    .font(.caption)
                                    .foregroundColor(.orange)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

private func colour(_ hex: String) -> Color {
    Color(nsColor: NSColor(hex: hex) ?? .labelColor)
}

/// Config and task content feed these links, so only allow `https` — anything
/// else (`file:`, custom schemes) could launch arbitrary URL handlers.
func httpsURL(_ string: String) -> URL? {
    guard let url = URL(string: string),
          url.scheme?.lowercased() == "https",
          url.host?.lowercased() == "linear.app"
    else { return nil }
    return url
}

private struct ProjectPanelSection: View {
    let project: ProjectMenu
    @ObservedObject var state: PanelState
    @Environment(\.colorScheme) private var scheme
    let actions: PanelActions

    @State private var controlsShown = false

    private var isExpanded: Bool { state.expandedProjects.contains(project.id) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button {
                withAnimation(.easeInOut(duration: 0.12)) {
                    if isExpanded {
                        state.expandedProjects.remove(project.id)
                    } else {
                        state.expandedProjects.insert(project.id)
                    }
                }
            } label: {
                header.contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityValue(isExpanded ? "Expanded" : "Collapsed")

            if isExpanded {
                projectBody
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(PanelPalette.card(scheme), in: RoundedRectangle(cornerRadius: 8))
    }

    @ViewBuilder
    private var projectBody: some View {
        VStack(alignment: .leading, spacing: 8) {
            if state.loadingProjects.contains(project.project.config) {
                Text(project.sections.isEmpty ? "Updating task list..." : "Updating in background...")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            if let error = project.taskError {
                Text("task list unavailable: \(error)")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if project.sections.isEmpty && project.taskError == nil && !state.loadingProjects.contains(project.project.config) {
                Text("Nothing awaiting your move")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            ForEach(project.sections, id: \.key) { section in
                VStack(alignment: .leading, spacing: 3) {
                    Text("\(section.title)  ·  \(section.totalCount)")
                        .font(.caption.weight(.medium))
                        .foregroundColor(.secondary)
                    VStack(alignment: .leading, spacing: 1) {
                        ForEach(section.items, id: \.identifier) { item in
                            TaskRow(project: project, item: item, state: state, actions: actions)
                        }
                    }
                    if section.moreCount > 0 {
                        openProjectButton("+\(section.moreCount) more")
                    }
                }
            }

            controlsSection
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Image(systemName: "chevron.right")
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundColor(.secondary)
                    .rotationEffect(.degrees(isExpanded ? 90 : 0))
                Circle()
                    .fill(colour(project.status.colourHex))
                    .frame(width: 8, height: 8)
                Text(projectName)
                    .font(.system(size: 13, weight: .semibold))
                Spacer(minLength: 0)
                Text(statusWord)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            Text(project.subline)
                .font(.caption)
                .foregroundColor(.secondary)
                .lineLimit(1)
                .truncationMode(.tail)
        }
    }

    private var projectName: String {
        var title = project.project.name
        if let team = project.project.teamName { title += " · \(team)" }
        if project.project.backend == .file { title += " · file" }
        return title
    }

    private var statusWord: String {
        if project.status.count > 0 { return "\(project.status.count) awaiting" }
        switch project.project.health {
        case .failed: return "failed"
        case .paused: return "paused"
        case .idle: return "idle"
        case .ok: return "active"
        }
    }

    private var controlsSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button {
                withAnimation(.easeInOut(duration: 0.12)) { controlsShown.toggle() }
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: controlsShown ? "chevron.down" : "chevron.right")
                        .font(.system(size: 8, weight: .semibold))
                    Text("Stages & controls")
                        .font(.caption.weight(.medium))
                }
                .foregroundColor(.secondary)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityValue(controlsShown ? "Expanded" : "Collapsed")

            if controlsShown {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(project.stages, id: \.name) { stage in
                        Text("\(stage.name)\(String(repeating: " ", count: max(0, 8 - stage.name.count))) \(stage.detail)")
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(.primary.opacity(0.8))
                            .lineLimit(1)
                            .truncationMode(.tail)
                    }
                    HStack(spacing: 6) {
                        Circle()
                            .fill(colour(project.project.autonomous ? MenuModel.green : MenuModel.grey))
                            .frame(width: 7, height: 7)
                        Text("Autonomous mode")
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityValue(project.project.autonomous ? "On" : "Off")

                    FlowButtons {
                        if project.project.paused {
                            Button("Resume project") {
                                actions.runCommand(CadenceActions.projectCommand(cadencePath: actions.cadencePath, project: project.project, args: ["resume"]), project.project, "Resume project")
                            }
                        } else {
                            Button("Pause project") {
                                actions.runCommand(CadenceActions.projectCommand(cadencePath: actions.cadencePath, project: project.project, args: ["pause"]), project.project, "Pause project")
                            }
                        }
                        Button(project.project.autonomous ? "Turn autonomous off" : "Turn autonomous on") {
                            actions.runCommand(
                                CadenceActions.autonomousCommand(cadencePath: actions.cadencePath, project: project.project),
                                project.project,
                                project.project.autonomous ? "Turn autonomous mode off" : "Turn autonomous mode on"
                            )
                        }
                        Button("View logs") {
                            actions.openTerminal(CadenceActions.projectCommand(cadencePath: actions.cadencePath, project: project.project, args: ["logs"]))
                        }
                        openProjectButton(project.project.backend == .file ? "Open tasks.md" : "Open board")
                    }
                    FlowButtons {
                        ForEach(MenuModel.workStages, id: \.self) { stage in
                            Button("Run \(stage)") {
                                actions.openTerminal(CadenceActions.runStageCommand(cadencePath: actions.cadencePath, project: project.project, stage: stage))
                            }
                        }
                    }
                }
                .padding(.top, 2)
            }
        }
    }

    @ViewBuilder
    private func openProjectButton(_ title: String) -> some View {
        if project.project.backend == .file, let path = project.taskPath {
            Button(title) { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }
                .buttonStyle(.bordered)
                .controlSize(.small)
        } else if let board = project.boardURL, let url = httpsURL(board) {
            Button(title) { NSWorkspace.shared.open(url) }
                .buttonStyle(.bordered)
                .controlSize(.small)
        }
    }
}

/// A small-button row that wraps to the next line when the panel is too
/// narrow (long labels, large accessibility text), so no action ever clips.
private struct FlowButtons<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        FlowLayout(spacing: 4) { content }
            .buttonStyle(.bordered)
            .controlSize(.small)
    }
}

/// Lays children out on one line, wrapping to the next line only when the width runs out.
private struct FlowLayout: Layout {
    var spacing: CGFloat = 4

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, widest: CGFloat = 0
        for subview in subviews {
            let childProposal = fittedProposal(for: subview, maxWidth: maxWidth)
            let size = subview.sizeThatFits(childProposal)
            if x > 0, x + size.width > maxWidth {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            widest = max(widest, x - spacing)
        }
        return CGSize(width: maxWidth == .infinity ? widest : maxWidth, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, rowHeight: CGFloat = 0
        for subview in subviews {
            let childProposal = fittedProposal(for: subview, maxWidth: bounds.width)
            let size = subview.sizeThatFits(childProposal)
            if x > bounds.minX, x + size.width > bounds.maxX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), proposal: childProposal)
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }

    private func fittedProposal(for subview: LayoutSubview, maxWidth: CGFloat) -> ProposedViewSize {
        subview.sizeThatFits(.unspecified).width > maxWidth
            ? ProposedViewSize(width: maxWidth, height: nil)
            : .unspecified
    }
}

private struct TaskRow: View {
    let project: ProjectMenu
    let item: CadenceItem
    @ObservedObject var state: PanelState
    let actions: PanelActions

    @State private var hovering = false
    @State private var confirmingCleanup = false

    private var key: String { actionKey(project: project.project, item: item) }
    private var isExpanded: Bool { state.expandedTask == key }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeInOut(duration: 0.12)) {
                    state.expandedTask = isExpanded ? nil : key
                }
            } label: {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 8, weight: .semibold))
                        .foregroundColor(.secondary)
                        .rotationEffect(.degrees(isExpanded ? 90 : 0))
                    Text(item.identifier)
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundColor(.secondary)
                    Text(taskTitle)
                        .font(.system(size: 12))
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Spacer(minLength: 0)
                }
                .padding(.vertical, 4)
                .padding(.horizontal, 6)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityValue(isExpanded ? "Expanded" : "Collapsed")
            .background(
                RoundedRectangle(cornerRadius: 5)
                    .fill(Color.primary.opacity(hovering || isExpanded ? 0.06 : 0))
            )
            .onHover { hovering = $0 }

            if isExpanded {
                FlowLayout(spacing: 4) {
                    ForEach(CadenceActions.SetStage.allCases, id: \.self) { stage in
                        Button(stage.title) {
                            actions.runCommand(
                                CadenceActions.setStageCommand(cadencePath: actions.cadencePath, project: project.project, item: item, stage: stage),
                                project.project,
                                "Set stage \(stage.title)"
                            )
                        }
                    }
                    if item.stage.advance != nil {
                        Button("Advance to \(advanceTitle)") {
                            actions.runCommand(
                                CadenceActions.advanceCommand(cadencePath: actions.cadencePath, project: project.project, item: item),
                                project.project,
                                "Advance to \(advanceTitle)"
                            )
                        }
                    }
                    Button(item.stage.hold ? "Release hold" : "Hold") {
                        let command = item.stage.hold
                            ? CadenceActions.releaseHoldCommand(cadencePath: actions.cadencePath, project: project.project, item: item)
                            : CadenceActions.holdCommand(cadencePath: actions.cadencePath, project: project.project, item: item)
                        actions.runCommand(command, project.project, item.stage.hold ? "Release hold" : "Hold")
                    }
                    if item.stage.name == "pr-open" || item.stage.name == "revised" {
                        Button("Set as merged") {
                            actions.runCommand(
                                CadenceActions.markMergedCommand(cadencePath: actions.cadencePath, project: project.project, item: item),
                                project.project,
                                "Set as merged"
                            )
                        }
                    }
                    if state.cleanableWorktrees.contains(key) {
                        Button("Clean up worktree") { confirmingCleanup = true }
                    }
                    if let url = pullRequestURL {
                        Button("Open PR") { NSWorkspace.shared.open(url) }
                    }
                    if project.project.backend == .file, let path = project.taskPath {
                        Button("Open tasks.md") { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }
                    } else if let value = item.url, let url = httpsURL(value) {
                        Button("Open in Linear") { NSWorkspace.shared.open(url) }
                    }
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .padding(.leading, 20)
                .padding(.trailing, 6)
                .padding(.vertical, 6)
            }
        }
        .confirmationDialog("Clean up worktree?", isPresented: $confirmingCleanup, titleVisibility: .visible) {
            Button("Clean Up", role: .destructive) {
                actions.runCommand(
                    CadenceActions.worktreeRemoveCommand(cadencePath: actions.cadencePath, project: project.project, item: item),
                    project.project,
                    "Clean up worktree"
                )
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This removes the merged task worktree and its local branch.")
        }
    }

    private var taskTitle: String {
        var title = item.title.replacingOccurrences(of: "|", with: "/")
        var bits: [String] = []
        if let gate = item.stage.gate { bits.append("\(gate) queued") }
        if item.stage.hold { bits.append("on hold") }
        if !bits.isEmpty { title += " — " + bits.joined(separator: ", ") }
        return title
    }

    private var advanceTitle: String {
        switch item.stage.advance {
        case "agent:spec": return "Spec"
        case "agent:build": return "Build"
        case "agent:revise": return "Revise"
        default: return item.stage.advance ?? "next stage"
        }
    }

    private var pullRequestURL: URL? {
        let text = [item.description, item.body].compactMap { $0 }.joined(separator: "\n")
        guard let expression = try? NSRegularExpression(pattern: #"https://github\.com/[^\s)>"'`]+/pull/\d+"#) else { return nil }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        guard let match = expression.firstMatch(in: text, range: range),
              let swiftRange = Range(match.range, in: text)
        else { return nil }
        return URL(string: String(text[swiftRange]))
    }
}

extension NSColor {
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
