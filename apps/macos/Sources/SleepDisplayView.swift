import AppKit
import SwiftUI

struct AppActivityMonitor: NSViewRepresentable {
    var onActivity: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onActivity: onActivity)
    }

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        context.coordinator.install()
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        context.coordinator.onActivity = onActivity
    }

    static func dismantleNSView(_ nsView: NSView, coordinator: Coordinator) {
        coordinator.remove()
    }

    final class Coordinator {
        var onActivity: () -> Void
        private var monitors: [Any] = []
        private var lastSent = Date.distantPast

        init(onActivity: @escaping () -> Void) {
            self.onActivity = onActivity
        }

        func install() {
            guard monitors.isEmpty else { return }
            let mask: NSEvent.EventTypeMask = [
                .keyDown,
                .leftMouseDown,
                .rightMouseDown,
                .otherMouseDown,
                .mouseMoved,
                .leftMouseDragged,
                .rightMouseDragged,
                .otherMouseDragged,
                .scrollWheel
            ]
            if let monitor = NSEvent.addLocalMonitorForEvents(matching: mask, handler: { [weak self] event in
                self?.sendActivity()
                return event
            }) {
                monitors.append(monitor)
            }
        }

        func remove() {
            monitors.forEach { NSEvent.removeMonitor($0) }
            monitors.removeAll()
        }

        private func sendActivity() {
            let now = Date()
            guard now.timeIntervalSince(lastSent) > 0.20 else { return }
            lastSent = now
            onActivity()
        }

        deinit {
            remove()
        }
    }
}

struct SleepDisplayView: View {
    @EnvironmentObject private var model: ElephantAppModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @FocusState private var passwordFocused: Bool

    var body: some View {
        GeometryReader { proxy in
            let shortest = min(proxy.size.width, proxy.size.height)
            let clockSize = min(92, max(64, shortest * 0.082))
            let avatarSize = min(132, max(94, shortest * 0.13))

            ZStack {
                AppBackground()
                    .blur(radius: reduceMotion ? 0 : 20)
                    .saturation(1.14)
                    .brightness(-0.05)
                    .opacity(0.96)

                LinearGradient(
                    colors: [
                        Color.black.opacity(0.18),
                        ElephantTheme.accent.opacity(0.16),
                        Color.black.opacity(0.22)
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()

                Rectangle()
                    .fill(.thinMaterial)
                    .overlay(
                        Color.white.opacity(0.10)
                    )
                    .ignoresSafeArea()

                SleepAmbientGlass(paused: reduceMotion)
                    .opacity(0.74)
                    .allowsHitTesting(false)

                VStack(spacing: 0) {
                    VStack(spacing: 4) {
                        Text(dateLine)
                            .font(.system(size: 18, weight: .semibold, design: .rounded))
                            .foregroundStyle(.white.opacity(0.80))
                        Text(timeLine)
                            .font(.system(size: clockSize, weight: .thin, design: .rounded))
                            .monospacedDigit()
                            .foregroundStyle(.white.opacity(0.86))
                    }
                    .padding(.top, max(42, proxy.size.height * 0.07))

                    Spacer()

                    VStack(spacing: 13) {
                        UserAvatarImage(size: avatarSize, name: model.userDisplayName, url: model.userAvatarURL)
                            .shadow(color: .black.opacity(0.20), radius: 18, y: 8)

                        Text(model.userDisplayName)
                            .font(.system(size: 22, weight: .semibold, design: .rounded))
                            .foregroundStyle(.white.opacity(0.92))
                            .lineLimit(1)

                        if model.hasAppLockPassword {
                            HStack(spacing: 8) {
                                SecureField(model.text(.sleepPasswordPlaceholder), text: $model.sleepUnlockPassword)
                                    .textFieldStyle(.plain)
                                    .focused($passwordFocused)
                                    .onSubmit {
                                        model.verifySleepUnlock()
                                    }

                                Button {
                                    model.verifySleepUnlock()
                                } label: {
                                    Image(systemName: "arrow.right.circle.fill")
                                        .font(.system(size: 22, weight: .semibold))
                                        .foregroundStyle(.white.opacity(0.92))
                                }
                                .buttonStyle(.plain)
                                .help(model.text(.sleepUnlock))
                            }
                            .padding(.horizontal, 13)
                            .frame(width: min(360, proxy.size.width * 0.42), height: 42)
                            .background(.ultraThinMaterial, in: Capsule())
                            .overlay(Capsule().stroke(.white.opacity(0.26), lineWidth: 1))

                            Text(model.sleepUnlockError.isEmpty ? model.text(.sleepLockSubtitle) : model.sleepUnlockError)
                                .font(.caption.weight(.medium))
                                .foregroundStyle(model.sleepUnlockError.isEmpty ? .white.opacity(0.66) : ElephantTheme.ember)
                        } else {
                            Button {
                                model.dismissSleepDisplay()
                            } label: {
                                Text(model.text(.sleepNoPassword))
                                    .font(.callout.weight(.semibold))
                                    .padding(.horizontal, 18)
                                    .padding(.vertical, 9)
                            }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.large)
                            .tint(ElephantTheme.accent)
                        }
                    }
                    .padding(.bottom, max(46, proxy.size.height * 0.10))
                }
                .padding(.horizontal, 34)
            }
            .onAppear {
                passwordFocused = true
            }
        }
        .ignoresSafeArea()
        .accessibilityLabel("Elephant Agent sleep display")
    }

    private var timeLine: String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: model.appLanguage.localeIdentifier)
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: Date())
    }

    private var dateLine: String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: model.appLanguage.localeIdentifier)
        formatter.setLocalizedDateFormatFromTemplate("MMMMdEEEE")
        return formatter.string(from: Date())
    }
}

private struct SleepAmbientGlass: View {
    var paused: Bool

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: paused)) { timeline in
            Canvas { context, size in
                let phase = paused ? 0 : timeline.date.timeIntervalSinceReferenceDate
                let palette = [ElephantTheme.accent, ElephantTheme.mint, ElephantTheme.ember, ElephantTheme.green]

                for index in 0..<7 {
                    let progress = CGFloat((phase * (0.020 + Double(index) * 0.004) + Double(index) * 0.19).truncatingRemainder(dividingBy: 1))
                    let x = size.width * (0.10 + 0.80 * progress)
                    let y = size.height * (0.18 + 0.64 * CGFloat((sin(phase * 0.18 + Double(index)) + 1.0) / 2.0))
                    let radius = min(size.width, size.height) * (0.10 + CGFloat(index % 3) * 0.035)
                    let rect = CGRect(x: x - radius, y: y - radius, width: radius * 2, height: radius * 2)
                    context.fill(
                        Path(ellipseIn: rect),
                        with: .color(palette[index % palette.count].opacity(0.045))
                    )
                }

                for index in 0..<4 {
                    let y = size.height * (0.24 + CGFloat(index) * 0.17)
                    var path = Path()
                    path.move(to: CGPoint(x: -120, y: y))
                    path.addCurve(
                        to: CGPoint(x: size.width + 120, y: y + CGFloat(sin(phase * 0.22 + Double(index))) * 22),
                        control1: CGPoint(x: size.width * 0.25, y: y - 74 + CGFloat(cos(phase * 0.21 + Double(index))) * 20),
                        control2: CGPoint(x: size.width * 0.70, y: y + 74 + CGFloat(sin(phase * 0.17 + Double(index))) * 20)
                    )
                    context.stroke(
                        path,
                        with: .color(.white.opacity(0.18)),
                        style: StrokeStyle(lineWidth: 1.1, lineCap: .round)
                    )
                }
            }
            .blur(radius: 18)
        }
    }
}
