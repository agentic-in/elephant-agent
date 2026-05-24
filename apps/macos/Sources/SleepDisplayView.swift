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
    @State private var passwordHovering = false
    @State private var unlockHovering = false

    var body: some View {
        GeometryReader { proxy in
            let shortest = min(proxy.size.width, proxy.size.height)
            let clockSize = min(128, max(86, shortest * 0.114))
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
                        VStack(spacing: 5) {
                            Text(dateLine(for: timeline.date))
                                .font(.system(size: 18, weight: .semibold, design: .rounded))
                                .foregroundStyle(.white.opacity(0.80))
                            Text(timeLine(for: timeline.date))
                                .font(.system(size: clockSize, weight: .semibold, design: .rounded))
                                .monospacedDigit()
                                .foregroundStyle(.white.opacity(0.90))
                                .scaleEffect(x: 1.0, y: 1.12, anchor: .center)
                                .padding(.vertical, 5)
                            Text(companionDayLine())
                                .font(.system(size: 15, weight: .semibold, design: .rounded))
                                .foregroundStyle(.white.opacity(0.76))
                                .padding(.top, 1)
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
                                    .font(.subheadline.weight(.medium))
                                    .foregroundStyle(.white.opacity(0.92))
                                    .frame(maxWidth: .infinity)
                                    .accessibilityLabel(model.text(.sleepPasswordPlaceholder))
                                    .accessibilityHint(model.text(.sleepLockSubtitle))
                                    .onSubmit {
                                        model.verifySleepUnlock()
                                    }

                                Button {
                                    model.verifySleepUnlock()
                                } label: {
                                    Image(systemName: "arrow.right")
                                        .font(.system(size: 14, weight: .bold))
                                        .foregroundStyle(.white.opacity(unlockHovering ? 0.98 : 0.86))
                                        .frame(width: 34, height: 34)
                                        .background {
                                            Circle()
                                                .fill(.white.opacity(unlockHovering ? 0.24 : 0.14))
                                        }
                                        .overlay {
                                            Circle()
                                                .stroke(.white.opacity(unlockHovering ? 0.42 : 0.20), lineWidth: 1)
                                        }
                                        .contentShape(Circle())
                                }
                                .buttonStyle(PressablePlainButtonStyle())
                                .help(model.text(.sleepUnlock))
                                .accessibilityLabel(model.text(.sleepUnlock))
                                .onHover { hovering in
                                    withAnimation(.easeOut(duration: 0.14)) {
                                        unlockHovering = hovering
                                    }
                                }
                            }
                            .padding(.leading, 15)
                            .padding(.trailing, 5)
                            .frame(width: min(304, max(232, proxy.size.width * 0.28)), height: 43)
                            .background {
                                Capsule()
                                    .fill(.ultraThinMaterial)
                                    .overlay {
                                        Capsule()
                                            .fill(.white.opacity(passwordFocused ? 0.08 : (passwordHovering ? 0.06 : 0.03)))
                                    }
                            }
                            .overlay {
                                Capsule()
                                    .stroke(
                                        model.sleepUnlockError.isEmpty
                                            ? .white.opacity(passwordFocused ? 0.48 : (passwordHovering ? 0.38 : 0.28))
                                            : ElephantTheme.ember.opacity(0.82),
                                        lineWidth: model.sleepUnlockError.isEmpty ? 1 : 1.4
                                    )
                            }
                            .shadow(color: Color.black.opacity(0.18), radius: 12, y: 6)
                            .contentShape(Capsule())
                            .onTapGesture {
                                passwordFocused = true
                            }
                            .onHover { hovering in
                                withAnimation(.easeOut(duration: 0.16)) {
                                    passwordHovering = hovering
                                }
                            }
                            .animation(.easeOut(duration: 0.16), value: passwordFocused)
                            .animation(.easeOut(duration: 0.16), value: model.sleepUnlockError)

                            ZStack {
                                if !model.sleepUnlockError.isEmpty {
                                    Label(model.sleepUnlockError, systemImage: "exclamationmark.circle.fill")
                                        .font(.caption.weight(.medium))
                                        .foregroundStyle(ElephantTheme.ember)
                                        .labelStyle(.titleAndIcon)
                                        .multilineTextAlignment(.center)
                                        .transition(.opacity.combined(with: .move(edge: .top)))
                                }
                            }
                            .frame(height: 18)
                            .animation(.easeOut(duration: 0.16), value: passwordFocused)
                            .animation(.easeOut(duration: 0.16), value: passwordHovering)
                            .animation(.easeOut(duration: 0.18), value: model.sleepUnlockError)
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
        .accessibilityElement(children: .contain)
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

    private func companionDayLine() -> String {
        let days = companionDayCount()
        switch model.appLanguage {
        case .zh:
            return "Elephant 陪伴你的第 \(days) 天"
        case .fr:
            return "Jour \(days) avec Elephant"
        case .de:
            return "Tag \(days) mit Elephant"
        case .en:
            return "Day \(days) with Elephant"
        }
    }

    private func companionDayCount() -> Int {
        guard let startDate = companionStartDate() else { return 1 }
        let calendar = Calendar.current
        let start = calendar.startOfDay(for: startDate)
        let today = calendar.startOfDay(for: Date())
        let dayDelta = calendar.dateComponents([.day], from: start, to: today).day ?? 0
        return max(1, dayDelta + 1)
    }

    private func companionStartDate() -> Date? {
        let currentStateID = model.snapshot.currentStateID.replacingOccurrences(of: "state:", with: "")
        let current = model.snapshot.herdItems.first { item in
            let itemID = item.id.replacingOccurrences(of: "state:", with: "")
            let elephantID = item.elephantID.replacingOccurrences(of: "state:", with: "")
            return item.current || (!currentStateID.isEmpty && (itemID == currentStateID || elephantID == currentStateID))
        }
        if let date = Self.parseDate(current?.createdAt ?? "") {
            return date
        }
        return model.snapshot.herdItems
            .compactMap { Self.parseDate($0.createdAt) }
            .min()
    }

    private static func parseDate(_ value: String) -> Date? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if let date = ISO8601DateFormatter().date(from: trimmed) {
            return date
        }

        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone.current
        for format in [
            "yyyy-MM-dd'T'HH:mm:ss.SSSXXXXX",
            "yyyy-MM-dd'T'HH:mm:ssXXXXX",
            "yyyy-MM-dd HH:mm:ss",
            "yyyy-MM-dd"
        ] {
            formatter.dateFormat = format
            if let date = formatter.date(from: trimmed) {
                return date
            }
        }
        return nil
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
