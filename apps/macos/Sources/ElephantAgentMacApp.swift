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
                .frame(minWidth: 980, idealWidth: 1420, maxWidth: .infinity, minHeight: 700, idealHeight: 900, maxHeight: .infinity)
                .background(WindowConfigurator(
                    language: model.appLanguage,
                    showTitlebarActions: !model.showingOnboarding && !model.isSleepDisplayPresented
                ))
                .preferredColorScheme(.light)
                .task {
                    await model.launch()
                }
        }
        .defaultSize(width: 1420, height: 900)
        .windowResizability(.contentMinSize)
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
            Button(model.text(.newChat)) {
                model.startNewChat()
            }
            .keyboardShortcut("n")

            Button(model.text(.reflect)) {
                Task { await model.runReflect(trigger: "manual") }
            }
            .keyboardShortcut("r", modifiers: [.command, .shift])
        }

        CommandMenu(Text(model.text(.menuNavigate))) {
            ForEach(AppSection.primary) { section in
                if let shortcut = section.shortcut {
                    Button(section.title(language: model.appLanguage)) {
                        model.selectedSection = section
                    }
                    .keyboardShortcut(shortcut, modifiers: [.command])
                } else {
                    Button(section.title(language: model.appLanguage)) {
                        model.selectedSection = section
                    }
                }
            }
            Divider()
            Button(AppSection.provider.title(language: model.appLanguage)) {
                model.selectedSection = .provider
            }
            Button(AppSection.settings.title(language: model.appLanguage)) {
                model.selectedSection = .settings
            }
        }

        CommandMenu(Text(model.text(.menuActions))) {
            Button(model.text(.refresh)) {
                Task { try? await model.refreshDashboard() }
            }
            .keyboardShortcut("r")

            Button(model.text(.reflect)) {
                Task { await model.runReflect(trigger: "manual") }
            }
            .keyboardShortcut("r", modifiers: [.command, .shift])

            Button(model.text(.sleepDisplay)) {
                model.beginSleepDisplay(reason: "manual")
            }
            .keyboardShortcut("s", modifiers: [.command, .shift])

            Button(model.text(.revealDatabase)) {
                model.revealDatabase()
            }
            .disabled(model.snapshot.databasePath.isEmpty)

            Divider()

            Button(model.text(.restartCore)) {
                Task { await model.restartCore() }
            }
        }
    }
}
