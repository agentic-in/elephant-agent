import SwiftUI
import AppKit

@main
struct ElephantAgentMacApp: App {
    @NSApplicationDelegateAdaptor(ElephantAppDelegate.self) private var appDelegate
    @StateObject private var model: ElephantAppModel

    init() {
        let appModel = ElephantAppModel()
        _model = StateObject(wrappedValue: appModel)
        ElephantAppDelegate.model = appModel
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
                .frame(minWidth: 980, minHeight: 700)
                .background(WindowConfigurator())
                .preferredColorScheme(.light)
                .task {
                    await model.launch()
                }
        }
        .commands {
            ElephantCommands(model: model)
        }

        Settings {
            SettingsView()
                .environmentObject(model)
                .frame(width: 760, height: 620)
        }
    }
}

@MainActor
final class ElephantAppDelegate: NSObject, NSApplicationDelegate {
    static weak var model: ElephantAppModel?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.appearance = NSAppearance(named: .aqua)
        UNNotificationBridge.requestPermission()
        if let model = Self.model {
            Task { await model.launch() }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            sender.windows.first { $0.canBecomeMain }?.makeKeyAndOrderFront(nil)
        }
        sender.activate(ignoringOtherApps: true)
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        Self.model?.shutdownSync()
    }
}

struct ElephantCommands: Commands {
    @ObservedObject var model: ElephantAppModel

    var body: some Commands {
        SidebarCommands()

        CommandGroup(after: .newItem) {
            Button("New Chat") {
                model.startNewChat()
            }
            .keyboardShortcut("n")

            Button("Import Sources...") {
                Task { await model.pickSources() }
            }
            .keyboardShortcut("o")

            Button("Run Reflect") {
                Task { await model.runReflect(trigger: "manual") }
            }
            .keyboardShortcut("r", modifiers: [.command, .shift])
        }

        CommandMenu("Navigate") {
            ForEach(AppSection.primary) { section in
                if let shortcut = section.shortcut {
                    Button(section.title) {
                        model.selectedSection = section
                    }
                    .keyboardShortcut(shortcut, modifiers: [.command])
                } else {
                    Button(section.title) {
                        model.selectedSection = section
                    }
                }
            }
            Divider()
            Button(AppSection.provider.title) {
                model.selectedSection = .provider
            }
            Button(AppSection.settings.title) {
                model.selectedSection = .settings
            }
            .keyboardShortcut(",", modifiers: [.command])
        }

        CommandMenu("Actions") {
            Button("Refresh Dashboard") {
                Task { try? await model.refreshDashboard() }
            }
            .keyboardShortcut("r")

            Button("Run Reflect") {
                Task { await model.runReflect(trigger: "manual") }
            }
            .keyboardShortcut("r", modifiers: [.command, .shift])

            Button("Reveal Database") {
                model.revealDatabase()
            }
            .disabled(model.snapshot.databasePath.isEmpty)

            Divider()

            Button("Restart Local Core") {
                Task { await model.restartCore() }
            }
        }
    }
}
