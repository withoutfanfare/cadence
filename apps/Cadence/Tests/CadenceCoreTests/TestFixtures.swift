import Foundation
@testable import CadenceCore

extension CadenceProject {
    static func fixture(
        name: String = "project",
        config: String,
        backend: Backend,
        health: Health = .ok,
        stages: [String: StageRun?] = [:],
        schedule: [String: Date?] = [:],
        lastActivity: String? = nil
    ) -> CadenceProject {
        CadenceProject(
            name: name,
            project: "/repo/\(name)",
            config: config,
            stateDir: "/state/\(name)",
            teamName: nil,
            backend: backend,
            scheduled: true,
            autonomous: false,
            paused: health == .paused,
            health: health,
            stages: stages,
            schedule: schedule,
            lastActivity: lastActivity
        )
    }
}

extension CadenceItem {
    static func fixture(
        id: String,
        title: String? = nil,
        status: String? = "open",
        stateType: String? = nil,
        url: String? = nil,
        description: String? = nil,
        labels: [String] = [],
        stage: ItemStage
    ) -> CadenceItem {
        CadenceItem(
            identifier: id,
            title: title ?? "Task \(id)",
            status: status,
            stateType: stateType,
            url: url,
            description: description,
            body: nil,
            labels: labels,
            stage: stage
        )
    }
}
