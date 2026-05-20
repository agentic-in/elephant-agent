// swift-tools-version: 5.7

import PackageDescription

let package = Package(
    name: "ElephantAgentMac",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "ElephantAgentMac", targets: ["ElephantAgentMac"])
    ],
    targets: [
        .executableTarget(
            name: "ElephantAgentMac",
            path: "Sources"
        )
    ]
)
