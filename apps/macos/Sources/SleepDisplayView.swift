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

    var body: some View {
        GeometryReader { proxy in
            let shortest = min(proxy.size.width, proxy.size.height)
            let mascotSize = min(520, max(330, shortest * 0.48))

            ZStack {
                AppBackground()
                    .blur(radius: reduceMotion ? 0 : 14)
                    .saturation(1.06)
                    .opacity(0.92)

                Rectangle()
                    .fill(.ultraThinMaterial)
                    .overlay(
                        LinearGradient(
                            colors: [
                                Color.white.opacity(0.30),
                                ElephantTheme.accent.opacity(0.055),
                                ElephantTheme.mint.opacity(0.070),
                                Color.white.opacity(0.24)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .ignoresSafeArea()

                SleepAmbientGlass(paused: reduceMotion)
                    .opacity(0.90)
                    .allowsHitTesting(false)

                VStack(spacing: 18) {
                    ElephantMascotView(
                        mood: .sleeping,
                        size: mascotSize,
                        showsMemoryField: true,
                        animated: true,
                        energy: 1.25
                    )
                    .accessibilityHidden(true)
                    .padding(.bottom, -12)

                    VStack(spacing: 8) {
                        Text("Elephant Agent")
                            .font(.system(size: min(54, max(38, shortest * 0.052)), weight: .semibold, design: .rounded))
                            .foregroundStyle(ElephantTheme.ink)
                        Text("Quietly remembering. Ready when you return.")
                            .font(.system(size: min(20, max(15, shortest * 0.020)), weight: .medium))
                            .foregroundStyle(ElephantTheme.muted)
                    }
                    .padding(.horizontal, 34)
                    .padding(.vertical, 22)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 26, style: .continuous)
                            .stroke(.white.opacity(0.50), lineWidth: 1)
                    )
                    .shadow(color: ElephantTheme.accent.opacity(0.08), radius: 26, y: 12)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(40)
            }
            .contentShape(Rectangle())
            .onTapGesture {
                model.dismissSleepDisplay()
            }
        }
        .ignoresSafeArea()
        .accessibilityLabel("Elephant Agent sleep display")
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
