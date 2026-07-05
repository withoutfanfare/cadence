// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "Cadence",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "Cadence", targets: ["Cadence"]),
        .library(name: "CadenceCore", targets: ["CadenceCore"])
    ],
    targets: [
        .target(name: "CadenceCore"),
        .executableTarget(name: "Cadence", dependencies: ["CadenceCore"]),
        .testTarget(name: "CadenceCoreTests", dependencies: ["CadenceCore"])
    ]
)
