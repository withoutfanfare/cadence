import Foundation

public enum CadenceActions {
    private static let gates = ["agent:spec", "agent:build", "agent:revise"]

    public enum SetStage: CaseIterable {
        case triage
        case spec
        case build
        case revise

        public var title: String {
            switch self {
            case .triage: return "Triage"
            case .spec: return "Spec"
            case .build: return "Build"
            case .revise: return "Revise"
            }
        }
    }

    public static func advanceCommand(cadencePath: String, project: CadenceProject, item: CadenceItem) -> [String] {
        guard let advance = item.stage.advance else { return [] }
        return updateCommand(
            cadencePath: cadencePath,
            project: project,
            item: item,
            add: [advance],
            remove: gates.filter { $0 != advance },
            closeTo: nil
        )
    }

    public static func markMergedCommand(cadencePath: String, project: CadenceProject, item: CadenceItem) -> [String] {
        updateCommand(
            cadencePath: cadencePath,
            project: project,
            item: item,
            add: [],
            remove: ["agent:pr-open", "agent:revised"],
            closeTo: "completed"
        )
    }

    public static func setStageCommand(cadencePath: String, project: CadenceProject, item: CadenceItem, stage: SetStage) -> [String] {
        switch stage {
        case .triage:
            return updateCommand(cadencePath: cadencePath, project: project, item: item, add: [], remove: ["agent:triaged"] + gates, closeTo: nil)
        case .spec:
            return updateCommand(cadencePath: cadencePath, project: project, item: item, add: ["agent:spec"], remove: ["agent:build", "agent:revise"], closeTo: nil)
        case .build:
            return updateCommand(cadencePath: cadencePath, project: project, item: item, add: ["agent:build"], remove: ["agent:spec", "agent:revise"], closeTo: nil)
        case .revise:
            return updateCommand(cadencePath: cadencePath, project: project, item: item, add: ["agent:revise"], remove: ["agent:spec", "agent:build"], closeTo: nil)
        }
    }

    public static func holdCommand(cadencePath: String, project: CadenceProject, item: CadenceItem) -> [String] {
        updateCommand(cadencePath: cadencePath, project: project, item: item, add: ["agent:hold"], remove: [], closeTo: nil)
    }

    public static func releaseHoldCommand(cadencePath: String, project: CadenceProject, item: CadenceItem) -> [String] {
        updateCommand(cadencePath: cadencePath, project: project, item: item, add: [], remove: ["agent:hold"], closeTo: nil)
    }

    public static func runStageCommand(cadencePath: String, project: CadenceProject, stage: String) -> [String] {
        projectCommand(cadencePath: cadencePath, project: project, args: ["run", stage])
    }

    public static func worktreeRemoveCommand(cadencePath: String, project: CadenceProject, item: CadenceItem) -> [String] {
        projectCommand(cadencePath: cadencePath, project: project, args: ["worktree", "remove", branchName(for: item)])
    }

    public static func updateCommand(
        cadencePath: String,
        project: CadenceProject,
        item: CadenceItem,
        add: [String],
        remove: [String],
        closeTo: String?
    ) -> [String] {
        var command = [cadencePath, "--config", project.config]
        command += project.backend == .file ? ["tasks", "update", item.identifier] : ["linear", "issue-update", item.identifier]
        for label in add { command += ["--add-label", label] }
        for label in remove { command += ["--remove-label", label] }
        if let closeTo {
            command += project.backend == .file ? ["--status", closeTo] : ["--state-type", closeTo]
        }
        return command
    }

    public static func projectCommand(cadencePath: String, project: CadenceProject, args: [String]) -> [String] {
        [cadencePath, "--config", project.config] + args
    }
}
