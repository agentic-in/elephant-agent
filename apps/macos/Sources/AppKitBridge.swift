import AppKit
import SwiftUI
import UserNotifications
import UniformTypeIdentifiers

extension Notification.Name {
    static let elephantToggleSidebar = Notification.Name("ElephantAgent.ToggleSidebar")
    static let elephantNewChat = Notification.Name("ElephantAgent.NewChat")
    static let elephantEnterSleepDisplay = Notification.Name("ElephantAgent.EnterSleepDisplay")
    static let elephantSelectSection = Notification.Name("ElephantAgent.SelectSection")
}

struct WindowConfigurator: NSViewRepresentable {
    var language: AppLanguage
    var showTitlebarActions = true
    private static let legacyAutosaveName = "ElephantAgentMainWindow"
    private static var configuredWindowIDs = Set<ObjectIdentifier>()
    private static var titlebarLanguageByWindowID: [ObjectIdentifier: AppLanguage] = [:]

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            guard let window = view.window else { return }
            Self.configure(window, language: language, showTitlebarActions: showTitlebarActions)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                Self.configure(window, language: language, showTitlebarActions: showTitlebarActions)
            }
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async {
            guard let window = nsView.window else { return }
            Self.configure(window, language: language, showTitlebarActions: showTitlebarActions)
        }
    }

    private static func configure(_ window: NSWindow, language: AppLanguage, showTitlebarActions: Bool) {
        let windowID = ObjectIdentifier(window)
        if !configuredWindowIDs.contains(windowID) {
            window.title = "Elephant Agent"
            window.titleVisibility = .hidden
            window.titlebarAppearsTransparent = true
            window.styleMask.insert(.fullSizeContentView)
            window.toolbar = nil
            window.toolbar?.isVisible = false
            if #available(macOS 11.0, *) {
                window.titlebarSeparatorStyle = .none
            }
            window.isMovableByWindowBackground = true
            window.backgroundColor = .windowBackgroundColor
            window.appearance = NSAppearance(named: .aqua)
            window.minSize = NSSize(width: 980, height: 700)
            clearLegacyAutosavedFrame()
            centerMainWindow(window)
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            configuredWindowIDs.insert(windowID)
        }

        guard showTitlebarActions else {
            removeTitlebarActions(from: window)
            titlebarLanguageByWindowID.removeValue(forKey: windowID)
            return
        }

        if titlebarLanguageByWindowID[windowID] != language {
            installTitlebarActions(on: window, language: language)
            titlebarLanguageByWindowID[windowID] = language
        }
    }

    private static func clearLegacyAutosavedFrame() {
        UserDefaults.standard.removeObject(forKey: "NSWindow Frame \(legacyAutosaveName)")
    }

    private static func centerMainWindow(_ window: NSWindow) {
        guard let screen = window.screen ?? NSScreen.main else { return }
        let visibleFrame = screen.visibleFrame
        let padding: CGFloat = 48
        let availableWidth = max(window.minSize.width, visibleFrame.width - padding)
        let availableHeight = max(window.minSize.height, visibleFrame.height - padding)
        let width = min(max(window.frame.width, window.minSize.width), availableWidth)
        let height = min(max(window.frame.height, window.minSize.height), availableHeight)
        let centeredFrame = NSRect(
            x: visibleFrame.midX - width / 2,
            y: visibleFrame.midY - height / 2,
            width: width,
            height: height
        )
        window.setFrame(centeredFrame.integral, display: true)
    }

    private static func removeTitlebarActions(from window: NSWindow) {
        let accessoryID = NSUserInterfaceItemIdentifier("ElephantTitlebarActions")
        for controller in window.titlebarAccessoryViewControllers.reversed() where controller.view.identifier == accessoryID {
            if let index = window.titlebarAccessoryViewControllers.firstIndex(of: controller) {
                window.removeTitlebarAccessoryViewController(at: index)
            }
        }
    }

    private static func installTitlebarActions(on window: NSWindow, language: AppLanguage) {
        let accessoryID = NSUserInterfaceItemIdentifier("ElephantTitlebarActions")
        removeTitlebarActions(from: window)

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
            help: AppText.toggleSidebar.text(language)
        ) {
            NotificationCenter.default.post(name: .elephantToggleSidebar, object: nil)
        })
        stack.addArrangedSubview(TitlebarIconButton(
            symbolName: "plus.bubble",
            fallbackSymbolName: "bubble.left",
            help: AppText.newChat.text(language)
        ) {
            NotificationCenter.default.post(name: .elephantNewChat, object: nil)
        })
        stack.addArrangedSubview(TitlebarIconButton(
            symbolName: "moon.zzz",
            fallbackSymbolName: "moon",
            help: AppText.sleepDisplay.text(language)
        ) {
            NotificationCenter.default.post(name: .elephantEnterSleepDisplay, object: nil)
        })
        stack.addArrangedSubview(TitlebarIdentityMenuButton(language: language))

        let wrapper = NSView(frame: NSRect(x: 0, y: 0, width: 244, height: 26))
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
    private var trackingAreaRef: NSTrackingArea?
    private var isHovering = false {
        didSet { updateVisualState() }
    }

    init(symbolName: String, fallbackSymbolName: String, help: String, handler: @escaping () -> Void) {
        self.handler = handler
        super.init(frame: NSRect(x: 0, y: 0, width: 30, height: 30))
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
        self.wantsLayer = true
        self.layer?.cornerRadius = 8
        NSLayoutConstraint.activate([
            widthAnchor.constraint(equalToConstant: 30),
            heightAnchor.constraint(equalToConstant: 30)
        ])
        updateVisualState()
    }

    required init?(coder: NSCoder) {
        nil
    }

    @objc private func runHandler() {
        handler()
    }

    override func mouseDown(with event: NSEvent) {
        isHighlighted = true
        updateVisualState()
        handler()
        isHighlighted = false
        updateVisualState()
    }

    override func performClick(_ sender: Any?) {
        handler()
    }

    override func accessibilityPerformPress() -> Bool {
        handler()
        return true
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingAreaRef {
            removeTrackingArea(trackingAreaRef)
        }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.activeInKeyWindow, .mouseEnteredAndExited, .inVisibleRect],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(area)
        trackingAreaRef = area
    }

    override func mouseEntered(with event: NSEvent) {
        isHovering = true
    }

    override func mouseExited(with event: NSEvent) {
        isHovering = false
    }

    private func updateVisualState() {
        let fill: NSColor
        if isHighlighted {
            fill = NSColor.controlAccentColor.withAlphaComponent(0.16)
            contentTintColor = NSColor.controlAccentColor
        } else if isHovering {
            fill = NSColor.controlAccentColor.withAlphaComponent(0.10)
            contentTintColor = NSColor.labelColor
        } else {
            fill = .clear
            contentTintColor = .secondaryLabelColor
        }
        layer?.backgroundColor = fill.cgColor
    }

    private static func symbol(named name: String) -> NSImage? {
        let image = NSImage(systemSymbolName: name, accessibilityDescription: nil)
        return image?.withSymbolConfiguration(.init(pointSize: 16, weight: .regular))
    }
}

private final class TitlebarIdentityMenuButton: NSPopUpButton {
    init(language: AppLanguage) {
        super.init(frame: NSRect(x: 0, y: 0, width: 104, height: 26), pullsDown: true)
        isBordered = false
        controlSize = .small
        font = .systemFont(ofSize: 13, weight: .semibold)
        imagePosition = .imageLeading
        contentTintColor = .labelColor
        toolTip = AppText.elephantMenu.text(language)
        addTitleItem()
        menu?.addItem(.separator())
        addMenuItem(title: AppSection.home.title(language: language), section: .home)
        addMenuItem(title: AppSection.wake.title(language: language), section: .wake)
        addMenuItem(title: AppSection.diary.title(language: language), section: .diary)
        menu?.addItem(.separator())
        addMenuItem(title: AppSection.settings.title(language: language), section: .settings)
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
    static func pickAvatarImageURL(language: AppLanguage) -> URL? {
        let panel = NSOpenPanel()
        panel.title = AppText.imagePickerTitle.text(language)
        panel.message = AppText.imagePickerMessage.text(language)
        panel.prompt = AppText.imagePickerPrompt.text(language)
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = false
        panel.resolvesAliases = true
        panel.allowedContentTypes = [.image]
        return panel.runModal() == .OK ? panel.urls.first : nil
    }

    static func pickChatImageURLs(language: AppLanguage) -> [URL] {
        let panel = NSOpenPanel()
        panel.title = AppText.chatImagePickerTitle.text(language)
        panel.message = AppText.chatImagePickerMessage.text(language)
        panel.prompt = AppText.chatImagePickerPrompt.text(language)
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = true
        panel.resolvesAliases = true
        panel.allowedContentTypes = [.image]
        return panel.runModal() == .OK ? panel.urls : []
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
