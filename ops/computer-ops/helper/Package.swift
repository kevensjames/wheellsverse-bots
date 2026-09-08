// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "KaiDesktopBridge",
    platforms: [.macOS(.v13)],
    targets: [.executableTarget(name: "KaiDesktopBridge", path: "Sources/KaiDesktopBridge")]
)
