import AppKit
import AVFoundation
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
            let brandTitleSize = min(34, max(27, shortest * 0.030))
            let brandSloganSize = min(17, max(14, shortest * 0.014))

            ZStack {
                SleepVideoBackdrop(paused: reduceMotion)
                    .saturation(1.08)
                    .brightness(-0.04)
                    .ignoresSafeArea()

                LinearGradient(
                    colors: [
                        Color.black.opacity(0.30),
                        ElephantTheme.accent.opacity(0.10),
                        Color.black.opacity(0.38)
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()

                Color.black.opacity(0.08)
                    .ignoresSafeArea()

                SleepAmbientGlass(paused: reduceMotion)
                    .opacity(0.56)
                    .allowsHitTesting(false)

                VStack {
                    Spacer()
                    HStack(alignment: .bottom) {
                        VStack(alignment: .leading, spacing: 7) {
                            Text(model.text(.sleepBrandTitle))
                                .font(.system(size: brandTitleSize, weight: .semibold, design: .rounded))
                                .foregroundStyle(.white.opacity(0.92))
                            Text(model.text(.sleepBrandSlogan))
                                .font(.system(size: brandSloganSize, weight: .medium, design: .rounded))
                                .foregroundStyle(.white.opacity(0.72))
                                .lineLimit(2)
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 34)
                    .padding(.bottom, 28)
                }
                .allowsHitTesting(false)

                VStack(spacing: 0) {
                    TimelineView(.periodic(from: Date(), by: 1.0)) { timeline in
                        VStack(spacing: 4) {
                            Text(dateLine(for: timeline.date))
                                .font(.system(size: 18, weight: .semibold, design: .rounded))
                                .foregroundStyle(.white.opacity(0.80))
                            Text(timeLine(for: timeline.date))
                                .font(.system(size: clockSize, weight: .thin, design: .rounded))
                                .monospacedDigit()
                                .foregroundStyle(.white.opacity(0.86))
                        }
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
                                    .font(.callout.weight(.medium))
                                    .foregroundStyle(.white.opacity(0.92))
                                    .onSubmit {
                                        model.verifySleepUnlock()
                                    }

                                Button {
                                    model.verifySleepUnlock()
                                } label: {
                                    Image(systemName: "arrow.right.circle.fill")
                                        .font(.system(size: 22, weight: .semibold))
                                        .foregroundStyle(.white.opacity(0.92))
                                        .frame(width: 34, height: 34)
                                        .contentShape(Circle())
                                }
                                .buttonStyle(.plain)
                                .help(model.text(.sleepUnlock))
                                .accessibilityLabel(model.text(.sleepUnlock))
                            }
                            .padding(.leading, 15)
                            .padding(.trailing, 6)
                            .frame(width: min(380, proxy.size.width * 0.46), height: 46)
                            .background(.ultraThinMaterial, in: Capsule())
                            .overlay(Capsule().stroke(model.sleepUnlockError.isEmpty ? .white.opacity(0.30) : ElephantTheme.ember.opacity(0.82), lineWidth: model.sleepUnlockError.isEmpty ? 1 : 1.4))
                            .shadow(color: Color.black.opacity(0.18), radius: 12, y: 6)

                            Label(
                                model.sleepUnlockError.isEmpty ? model.text(.sleepLockSubtitle) : model.sleepUnlockError,
                                systemImage: model.sleepUnlockError.isEmpty ? "lock.fill" : "exclamationmark.circle.fill"
                            )
                            .font(.caption.weight(.medium))
                            .foregroundStyle(model.sleepUnlockError.isEmpty ? .white.opacity(0.68) : ElephantTheme.ember)
                            .labelStyle(.titleAndIcon)
                            .multilineTextAlignment(.center)
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

    private func timeLine(for date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: model.appLanguage.localeIdentifier)
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }

    private func dateLine(for date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: model.appLanguage.localeIdentifier)
        formatter.setLocalizedDateFormatFromTemplate("MMMMdEEEE")
        return formatter.string(from: date)
    }
}

struct SleepVideoBackdrop: View {
    var paused: Bool

    var body: some View {
        if let bundledURL = Bundle.main.url(forResource: "baby-el", withExtension: "mp4") {
            LoopingVideoBackground(url: bundledURL, paused: paused)
        } else {
            AppBackground()
                .blur(radius: paused ? 0 : 20)
                .saturation(1.14)
                .opacity(0.96)
        }
    }
}

private struct LoopingVideoBackground: NSViewRepresentable {
    var url: URL
    var paused: Bool

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> VideoLayerView {
        let view = VideoLayerView()
        let item = AVPlayerItem(url: url)
        let player = AVQueuePlayer(playerItem: item)
        let looper = AVPlayerLooper(player: player, templateItem: item)
        player.isMuted = true
        player.actionAtItemEnd = .none
        player.play()
        view.playerLayer.player = player
        context.coordinator.player = player
        context.coordinator.looper = looper
        return view
    }

    func updateNSView(_ nsView: VideoLayerView, context: Context) {
        if paused {
            context.coordinator.player?.pause()
        } else {
            context.coordinator.player?.play()
        }
    }

    static func dismantleNSView(_ nsView: VideoLayerView, coordinator: Coordinator) {
        coordinator.player?.pause()
        nsView.playerLayer.player = nil
    }

    final class Coordinator {
        var player: AVQueuePlayer?
        var looper: AVPlayerLooper?
    }
}

private final class VideoLayerView: NSView {
    let playerLayer = AVPlayerLayer()

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        playerLayer.videoGravity = .resizeAspectFill
        layer?.addSublayer(playerLayer)
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        wantsLayer = true
        playerLayer.videoGravity = .resizeAspectFill
        layer?.addSublayer(playerLayer)
    }

    override func layout() {
        super.layout()
        playerLayer.frame = bounds
    }
}

struct SleepAmbientGlass: View {
    var paused: Bool

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: paused)) { timeline in
            SleepAmbientCanvas(phase: paused ? 0 : timeline.date.timeIntervalSinceReferenceDate)
                .blur(radius: 18)
        }
    }
}

private struct SleepAmbientCanvas: View {
    var phase: TimeInterval
    private let palette = [ElephantTheme.accent, ElephantTheme.mint, ElephantTheme.ember, ElephantTheme.green]

    var body: some View {
        Canvas { context, size in
            drawOrbs(context: &context, size: size)
            drawWaveLines(context: &context, size: size)
        }
    }

    private func drawOrbs(context: inout GraphicsContext, size: CGSize) {
        for index in 0..<7 {
            let speed = 0.020 + Double(index) * 0.004
            let offset = Double(index) * 0.19
            let progress = CGFloat((phase * speed + offset).truncatingRemainder(dividingBy: 1))
            let x = size.width * (0.10 + 0.80 * progress)
            let wave = CGFloat((sin(phase * 0.18 + Double(index)) + 1.0) / 2.0)
            let y = size.height * (0.18 + 0.64 * wave)
            let radius = min(size.width, size.height) * (0.10 + CGFloat(index % 3) * 0.035)
            let rect = CGRect(x: x - radius, y: y - radius, width: radius * 2, height: radius * 2)
            context.fill(
                Path(ellipseIn: rect),
                with: .color(palette[index % palette.count].opacity(0.045))
            )
        }
    }

    private func drawWaveLines(context: inout GraphicsContext, size: CGSize) {
        for index in 0..<4 {
            let y = size.height * (0.24 + CGFloat(index) * 0.17)
            let indexPhase = Double(index)
            var path = Path()
            path.move(to: CGPoint(x: -120, y: y))
            path.addCurve(
                to: CGPoint(x: size.width + 120, y: y + CGFloat(sin(phase * 0.22 + indexPhase)) * 22),
                control1: CGPoint(x: size.width * 0.25, y: y - 74 + CGFloat(cos(phase * 0.21 + indexPhase)) * 20),
                control2: CGPoint(x: size.width * 0.70, y: y + 74 + CGFloat(sin(phase * 0.17 + indexPhase)) * 20)
            )
            context.stroke(
                path,
                with: .color(.white.opacity(0.18)),
                style: StrokeStyle(lineWidth: 1.1, lineCap: .round)
            )
        }
    }
}
