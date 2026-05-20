import AppKit
import SwiftUI
import UserNotifications
import UniformTypeIdentifiers

extension Notification.Name {
    static let elephantToggleSidebar = Notification.Name("ElephantAgent.ToggleSidebar")
    static let elephantNewChat = Notification.Name("ElephantAgent.NewChat")
    static let elephantSelectSection = Notification.Name("ElephantAgent.SelectSection")
}

struct WindowConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            guard let window = view.window else { return }
            Self.configure(window)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                Self.configure(window)
            }
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {}

    private static func configure(_ window: NSWindow) {
        window.title = "Elephant Agent"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.styleMask.insert(.fullSizeContentView)
        window.toolbar = nil
        window.toolbar?.isVisible = false
        if #available(macOS 11.0, *) {
            window.titlebarSeparatorStyle = .none
        }
        installTitlebarActions(on: window)
        window.isMovableByWindowBackground = true
        window.backgroundColor = .windowBackgroundColor
        window.appearance = NSAppearance(named: .aqua)
        window.minSize = NSSize(width: 980, height: 700)
        window.setFrameAutosaveName("ElephantAgentMainWindow")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private static func installTitlebarActions(on window: NSWindow) {
        let accessoryID = NSUserInterfaceItemIdentifier("ElephantTitlebarActions")
        window.titlebarAccessoryViewControllers
            .filter { $0.view.identifier == accessoryID }
            .forEach { window.removeTitlebarAccessoryViewController(at: window.titlebarAccessoryViewControllers.firstIndex(of: $0) ?? 0) }

        let stack = NSStackView()
        stack.identifier = accessoryID
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 14
        stack.edgeInsets = NSEdgeInsets(top: 0, left: 8, bottom: 0, right: 0)
        stack.translatesAutoresizingMaskIntoConstraints = false

        stack.addArrangedSubview(TitlebarIconButton(
            symbolName: "sidebar.left",
            fallbackSymbolName: "rectangle.split.1x2",
            help: "Show or Hide Sidebar"
        ) {
            NotificationCenter.default.post(name: .elephantToggleSidebar, object: nil)
        })
        stack.addArrangedSubview(TitlebarIconButton(
            symbolName: "plus.bubble",
            fallbackSymbolName: "bubble.left",
            help: "New Chat"
        ) {
            NotificationCenter.default.post(name: .elephantNewChat, object: nil)
        })
        stack.addArrangedSubview(TitlebarIdentityMenuButton())

        let wrapper = NSView(frame: NSRect(x: 0, y: 0, width: 204, height: 26))
        wrapper.identifier = accessoryID
        wrapper.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: wrapper.leadingAnchor),
            stack.centerYAnchor.constraint(equalTo: wrapper.centerYAnchor),
            stack.trailingAnchor.constraint(lessThanOrEqualTo: wrapper.trailingAnchor)
        ])

        let accessory = NSTitlebarAccessoryViewController()
        accessory.view = wrapper
        accessory.layoutAttribute = .left
        window.addTitlebarAccessoryViewController(accessory)
    }
}

private final class TitlebarIconButton: NSButton {
    private let handler: () -> Void

    init(symbolName: String, fallbackSymbolName: String, help: String, handler: @escaping () -> Void) {
        self.handler = handler
        super.init(frame: NSRect(x: 0, y: 0, width: 26, height: 26))
        self.image = Self.symbol(named: symbolName) ?? Self.symbol(named: fallbackSymbolName)
        self.imagePosition = .imageOnly
        self.isBordered = false
        self.bezelStyle = .regularSquare
        self.contentTintColor = .secondaryLabelColor
        self.toolTip = help
        self.setButtonType(.momentaryChange)
        self.target = self
        self.action = #selector(runHandler)
        self.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            widthAnchor.constraint(equalToConstant: 26),
            heightAnchor.constraint(equalToConstant: 26)
        ])
    }

    required init?(coder: NSCoder) {
        nil
    }

    @objc private func runHandler() {
        handler()
    }

    override func mouseDown(with event: NSEvent) {
        isHighlighted = true
        handler()
        isHighlighted = false
    }

    override func performClick(_ sender: Any?) {
        handler()
    }

    override func accessibilityPerformPress() -> Bool {
        handler()
        return true
    }

    private static func symbol(named name: String) -> NSImage? {
        let image = NSImage(systemSymbolName: name, accessibilityDescription: nil)
        return image?.withSymbolConfiguration(.init(pointSize: 16, weight: .regular))
    }
}

private final class TitlebarIdentityMenuButton: NSPopUpButton {
    init() {
        super.init(frame: NSRect(x: 0, y: 0, width: 104, height: 26), pullsDown: true)
        isBordered = false
        controlSize = .small
        font = .systemFont(ofSize: 13, weight: .semibold)
        imagePosition = .imageLeading
        contentTintColor = .labelColor
        toolTip = "Elephant menu"
        addTitleItem()
        menu?.addItem(.separator())
        addMenuItem(title: "Home", section: .home)
        addMenuItem(title: "Chat", section: .wake)
        addMenuItem(title: "Tools", section: .tools)
        addMenuItem(title: "Herd", section: .herd)
        addMenuItem(title: "Provider", section: .provider)
        menu?.addItem(.separator())
        addMenuItem(title: "Settings", section: .settings)
        target = self
        action = #selector(handleSelection)
        translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            widthAnchor.constraint(equalToConstant: 104),
            heightAnchor.constraint(equalToConstant: 26)
        ])
    }

    required init?(coder: NSCoder) {
        nil
    }

    @objc private func handleSelection() {
        guard let rawValue = selectedItem?.representedObject as? String else { return }
        NotificationCenter.default.post(name: .elephantSelectSection, object: rawValue)
    }

    private func addTitleItem() {
        addItem(withTitle: "Elephant")
        item(at: 0)?.image = Self.logoImage()
    }

    private func addMenuItem(title: String, section: AppSection) {
        addItem(withTitle: title)
        lastItem?.representedObject = section.rawValue
    }

    private static func logoImage() -> NSImage? {
        guard let image = BundleAssets.image(named: "favicon.png", subdirectory: "brand")?.copy() as? NSImage else {
            return NSImage(systemSymbolName: "app", accessibilityDescription: nil)
        }
        image.size = NSSize(width: 16, height: 16)
        return image
    }
}

enum OpenPanelBridge {
    static func pickSourceURLs() -> [URL]? {
        let panel = NSOpenPanel()
        panel.title = "Choose local evidence"
        panel.message = "Pick a project, repository, notes folder, Markdown file, text file, or config file."
        panel.prompt = "Add Sources"
        panel.canChooseDirectories = true
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = true
        panel.resolvesAliases = true
        return panel.runModal() == .OK ? panel.urls : nil
    }

    static func pickAvatarImageURL() -> URL? {
        let panel = NSOpenPanel()
        panel.title = "Choose your photo"
        panel.message = "Pick a local image for your Elephant Agent profile."
        panel.prompt = "Use Photo"
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = false
        panel.resolvesAliases = true
        panel.allowedContentTypes = [.image]
        return panel.runModal() == .OK ? panel.urls.first : nil
    }
}

enum UNNotificationBridge {
    static func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    static func notify(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }
}

enum BundleAssets {
    static func image(named name: String, subdirectory: String? = nil) -> NSImage? {
        let parts = split(name)
        if let url = Bundle.main.url(forResource: parts.base, withExtension: parts.ext, subdirectory: subdirectory),
           let image = NSImage(contentsOf: url) {
            return image
        }
        if let repo = repoRoot() {
            let assetURL = repo.appendingPathComponent("apps/site/static/assets")
            let folders = subdirectory.map { [$0] } ?? ["brand", "resources"]
            for folder in folders {
                let url = assetURL.appendingPathComponent(folder).appendingPathComponent(name)
                if let image = NSImage(contentsOf: url) {
                    return image
                }
            }
        }
        return nil
    }

    static func repoRoot() -> URL? {
        let fileManager = FileManager.default
        let env = ProcessInfo.processInfo.environment
        for key in ["ELEPHANT_MAC_REPO_ROOT", "ELEPHANT_REPO_ROOT"] {
            if let value = env[key], !value.isEmpty {
                return URL(fileURLWithPath: value)
            }
        }
        if let resource = Bundle.main.url(forResource: "RepoRoot", withExtension: "txt"),
           let value = try? String(contentsOf: resource).trimmingCharacters(in: .whitespacesAndNewlines),
           !value.isEmpty {
            return URL(fileURLWithPath: value)
        }
        var candidate = URL(fileURLWithPath: fileManager.currentDirectoryPath)
        for _ in 0..<8 {
            if fileManager.fileExists(atPath: candidate.appendingPathComponent("pyproject.toml").path) {
                return candidate
            }
            candidate.deleteLastPathComponent()
        }
        return nil
    }

    private static func split(_ name: String) -> (base: String, ext: String) {
        let url = URL(fileURLWithPath: name)
        return (url.deletingPathExtension().lastPathComponent, url.pathExtension)
    }
}

enum SourceScanner {
    private static let skippedDirectories = Set([
        ".git", "node_modules", "dist", "build", ".next", ".venv", "venv", "__pycache__", ".turbo", ".cache"
    ])
    private static let admittedExtensions = Set([
        "md", "mdx", "txt", "rst", "py", "swift", "ts", "tsx", "js", "jsx", "json", "yaml", "yml", "toml",
        "ini", "env.example", "gitignore", "dockerfile", "sql", "html", "css", "scss", "sh", "rb", "go", "rs"
    ])
    private static let binaryExtensions = Set([
        "png", "jpg", "jpeg", "gif", "webp", "pdf", "zip", "gz", "tar", "sqlite", "db", "dmg", "mp4", "mov"
    ])

    static func scan(urls: [URL]) -> [SourceScan] {
        urls.map { scan(url: $0) }
    }

    private static func scan(url: URL) -> SourceScan {
        let fileManager = FileManager.default
        var scanned = 0
        var admitted = 0
        var skipped = 0
        var samples: [String] = []
        var reasons: [String: Int] = [:]

        func skip(_ reason: String) {
            skipped += 1
            reasons[reason, default: 0] += 1
        }

        func consider(_ file: URL) {
            scanned += 1
            let name = file.lastPathComponent.lowercased()
            let ext = file.pathExtension.lowercased()
            if binaryExtensions.contains(ext) {
                skip("binary")
                return
            }
            if name.contains("secret") || name.contains("credential") || name == ".env" {
                skip("secret-like")
                return
            }
            let values = try? file.resourceValues(forKeys: [.fileSizeKey])
            if (values?.fileSize ?? 0) > 1_000_000 {
                skip("large")
                return
            }
            if admittedExtensions.contains(ext) || admittedExtensions.contains(name) || ext.isEmpty {
                admitted += 1
                if samples.count < 8 {
                    samples.append(file.lastPathComponent)
                }
            } else {
                skip("unsupported")
            }
        }

        var isDirectory: ObjCBool = false
        if fileManager.fileExists(atPath: url.path, isDirectory: &isDirectory), isDirectory.boolValue {
            let enumerator = fileManager.enumerator(
                at: url,
                includingPropertiesForKeys: [.isDirectoryKey, .fileSizeKey],
                options: [.skipsHiddenFiles]
            )
            while let item = enumerator?.nextObject() as? URL, scanned < 1200 {
                let values = try? item.resourceValues(forKeys: [.isDirectoryKey])
                if values?.isDirectory == true {
                    if skippedDirectories.contains(item.lastPathComponent) {
                        enumerator?.skipDescendants()
                        skip("ignored directory")
                    }
                } else {
                    consider(item)
                }
            }
        } else {
            consider(url)
        }

        return SourceScan(
            rootPath: url.path,
            scanned: scanned,
            admitted: admitted,
            skipped: skipped,
            samples: samples,
            skippedReasons: reasons
        )
    }
}
