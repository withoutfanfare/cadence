import Foundation
import XCTest
@testable import CadenceCore

final class RelativeTimeTests: XCTestCase {
    func testRelativeTimeMatchesSwiftBarSemantics() {
        let now = Date(timeIntervalSince1970: 1_750_000_000)
        XCTAssertEqual(RelativeTime.describe(now.addingTimeInterval(-30), now: now), "just now")
        XCTAssertEqual(RelativeTime.describe(now.addingTimeInterval(-30 * 60), now: now), "30m ago")
        XCTAssertEqual(RelativeTime.describe(now.addingTimeInterval(-3 * 60 * 60), now: now), "3h ago")
        XCTAssertEqual(RelativeTime.describe(now.addingTimeInterval(-2 * 24 * 60 * 60), now: now), "2d ago")
        XCTAssertNil(RelativeTime.describe(nil, now: now))
    }

    func testFutureTimeMatchesSwiftBarSemantics() {
        let now = Date(timeIntervalSince1970: 1_750_000_000)
        XCTAssertEqual(RelativeTime.until(now.addingTimeInterval(8 * 60), now: now), "in 8m")
        XCTAssertEqual(RelativeTime.until(now.addingTimeInterval(2 * 60 * 60), now: now), "in 2h")
        XCTAssertEqual(RelativeTime.until(now.addingTimeInterval(20), now: now), "due now")
        XCTAssertNil(RelativeTime.until(nil, now: now))
    }
}
