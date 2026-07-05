import Foundation

public enum RelativeTime {
    public static func describe(_ date: Date?, now: Date = Date()) -> String? {
        guard let date else { return nil }
        let seconds = max(0, now.timeIntervalSince(date))
        if seconds < 90 { return "just now" }
        let minutes = seconds / 60
        if minutes < 60 { return "\(Int(minutes))m ago" }
        let hours = minutes / 60
        if hours < 24 { return "\(Int(hours))h ago" }
        return "\(Int(hours / 24))d ago"
    }

    public static func until(_ date: Date?, now: Date = Date()) -> String? {
        guard let date else { return nil }
        let seconds = date.timeIntervalSince(now)
        if seconds < 60 { return "due now" }
        let minutes = seconds / 60
        if minutes < 60 { return "in \(Int(minutes.rounded()))m" }
        return "in \(Int((minutes / 60).rounded()))h"
    }
}
