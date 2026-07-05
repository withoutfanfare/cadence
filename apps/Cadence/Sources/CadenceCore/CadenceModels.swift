import Foundation

public extension JSONDecoder {
    static var cadence: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
}

public struct Overview: Decodable, Sendable {
    public let registry: String
    public let projects: [CadenceProject]
    public let warnings: [String]
}

public struct CadenceProject: Decodable, Sendable, Identifiable {
    public var id: String { config }
    public let name: String
    public let project: String
    public let config: String
    public let stateDir: String
    public let teamName: String?
    public let backend: Backend
    public let scheduled: Bool
    public let autonomous: Bool
    public let paused: Bool
    public let health: Health
    public let stages: [String: StageRun?]
    public let schedule: [String: Date?]
    public let lastActivity: String?

    enum CodingKeys: String, CodingKey {
        case name, project, config, backend, scheduled, autonomous, paused, health, stages, schedule
        case stateDir = "state_dir"
        case teamName = "team_name"
        case lastActivity = "last_activity"
    }
}

public enum Backend: String, Decodable, Sendable {
    case file
    case linear
}

public enum Health: String, Decodable, Sendable {
    case failed
    case paused
    case ok
    case idle
}

public struct StageRun: Decodable, Sendable {
    public let ts: Date?
    public let errors: Int
    public let result: String
}

public struct CadenceItem: Decodable, Sendable, Identifiable {
    public var id: String { identifier }
    public let identifier: String
    public let title: String
    public let status: String?
    public let stateType: String?
    public let url: String?
    public let description: String?
    public let body: String?
    public let labels: [String]
    public let stage: ItemStage

    enum CodingKeys: String, CodingKey {
        case identifier, title, status, url, description, body, labels, stage
        case stateType = "state_type"
    }
}

public struct ItemStage: Decodable, Sendable {
    public let name: String
    public let gate: String?
    public let hold: Bool
    public let exception: String?
    public let advance: String?
}
