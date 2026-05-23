import SwiftUI
import AppKit

enum ElephantTheme {
    static let ink = Color(nsColor: .labelColor)
    static let muted = Color(nsColor: .secondaryLabelColor)
    static let faint = Color(nsColor: .tertiaryLabelColor)
    static let line = Color(nsColor: .separatorColor).opacity(0.62)
    static let canvas = Color(nsColor: .windowBackgroundColor)
    static let panel = Color(nsColor: .controlBackgroundColor)
    static let elevated = Color(nsColor: .textBackgroundColor)
    static let accent = Color(red: 0.18, green: 0.40, blue: 0.88)
    static let green = Color(red: 0.20, green: 0.70, blue: 0.40)
    static let orange = Color(red: 0.86, green: 0.42, blue: 0.12)
    static let mint = Color(red: 0.53, green: 0.82, blue: 0.70)
    static let ember = Color(red: 0.95, green: 0.54, blue: 0.28)
    static let gold = Color(red: 0.88, green: 0.66, blue: 0.24)
}

struct AppBackground: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ElephantTheme.canvas
            .overlay(MosaicMemoryField(paused: reduceMotion).opacity(0.78))
            .ignoresSafeArea()
    }
}

struct MosaicMemoryField: View {
    var paused = false
    private let cellSize: CGFloat = 104

    var body: some View {
        TimelineView(.animation(minimumInterval: 6.0, paused: paused)) { timeline in
            Canvas { context, size in
                let seconds = paused ? 0 : timeline.date.timeIntervalSinceReferenceDate
                let cols = Int(size.width / cellSize) + 3
                let rows = Int(size.height / cellSize) + 3
                let palette = [
                    ElephantTheme.accent,
                    ElephantTheme.green,
                    ElephantTheme.ember,
                    Color(red: 0.60, green: 0.72, blue: 0.95),
                    Color(red: 0.78, green: 0.86, blue: 0.82)
                ]

                for row in 0..<rows {
                    for col in 0..<cols {
                        let wave = sin(seconds * 0.32 + Double(row) * 0.74 + Double(col) * 0.58)
                        let slow = cos(seconds * 0.16 + Double(row - col) * 0.33)
                        let alpha = 0.030 + max(0, wave * slow) * 0.090
                        let color = palette[(row * 3 + col) % palette.count].opacity(alpha)
                        let rect = CGRect(
                            x: CGFloat(col) * cellSize - cellSize,
                            y: CGFloat(row) * cellSize - cellSize,
                            width: cellSize + 1,
                            height: cellSize + 1
                        )
                        context.fill(Path(rect), with: .color(color))
                    }
                }

                for row in 0..<rows {
                    let y = CGFloat(row) * cellSize - cellSize
                    var path = Path()
                    path.move(to: CGPoint(x: 0, y: y))
                    path.addLine(to: CGPoint(x: size.width, y: y + CGFloat(sin(seconds * 0.12 + Double(row))) * 3))
                    context.stroke(path, with: .color(ElephantTheme.accent.opacity(0.035)), lineWidth: 0.7)
                }
            }
        }
    }
}

struct MemoryCurrentField: View {
    var paused = false

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.5, paused: paused)) { timeline in
            Canvas { context, size in
                let seconds = paused ? 0 : timeline.date.timeIntervalSinceReferenceDate
                let palette = [ElephantTheme.accent, ElephantTheme.mint, ElephantTheme.ember]

                for index in 0..<5 {
                    let phase = seconds / (8.0 + Double(index)) + Double(index) * 0.72
                    let yBase = size.height * (0.18 + CGFloat(index) * 0.16)
                    var path = Path()
                    path.move(to: CGPoint(x: -80, y: yBase + CGFloat(sin(phase)) * 20))
                    path.addCurve(
                        to: CGPoint(x: size.width + 80, y: yBase + CGFloat(cos(phase * 0.7)) * 24),
                        control1: CGPoint(x: size.width * 0.28, y: yBase - 90 + CGFloat(sin(phase * 1.4)) * 26),
                        control2: CGPoint(x: size.width * 0.72, y: yBase + 90 + CGFloat(cos(phase * 1.2)) * 26)
                    )
                    context.stroke(
                        path,
                        with: .color(palette[index % palette.count].opacity(0.075)),
                        style: StrokeStyle(lineWidth: index == 0 ? 2.0 : 1.4, lineCap: .round)
                    )

                    let t = CGFloat((seconds * 0.045 + Double(index) * 0.19).truncatingRemainder(dividingBy: 1))
                    let particleX = size.width * t
                    let particleY = yBase + CGFloat(sin(phase + Double(t) * 2.4)) * 34
                    let particle = CGRect(x: particleX, y: particleY, width: 4.5, height: 4.5)
                    context.fill(Path(ellipseIn: particle), with: .color(palette[(index + 1) % palette.count].opacity(0.16)))
                }
            }
        }
    }
}

struct AnimatedDotGrid: View {
    var spacing: CGFloat = 30
    var paused = false

    var body: some View {
        Canvas { context, size in
            let dotColor = Color(red: 0.45, green: 0.49, blue: 0.56)
            for x in stride(from: -spacing, through: size.width + spacing, by: spacing) {
                for y in stride(from: -spacing, through: size.height + spacing, by: spacing) {
                    let wave = 0.10 + 0.05 * sin(Double(x + y) / 92.0)
                    let rect = CGRect(x: x, y: y, width: 2.0, height: 2.0)
                    context.fill(Path(ellipseIn: rect), with: .color(dotColor.opacity(wave)))
                }
            }
        }
    }
}

struct BrandMark: View {
    var size: CGFloat = 30
    var framed = true

    var body: some View {
        Group {
            if let image = BundleAssets.image(named: "elephant-logo.png", subdirectory: "Brand") {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
            } else {
                Image(systemName: "circle.hexagongrid")
                    .font(.system(size: size * 0.50, weight: .semibold))
                    .foregroundStyle(ElephantTheme.accent)
            }
        }
        .frame(width: size, height: size)
        .padding(framed ? size * 0.15 : 0)
        .background {
            if framed {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(.regularMaterial)
            }
        }
        .overlay {
            if framed {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(ElephantTheme.line, lineWidth: 1)
            }
        }
    }
}

struct PressablePlainButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.965 : 1.0)
            .opacity(configuration.isPressed ? 0.78 : 1.0)
            .animation(.easeOut(duration: 0.10), value: configuration.isPressed)
    }
}

struct StatusDot: View {
    var tint: Color

    var body: some View {
        Circle()
            .fill(tint)
            .frame(width: 8, height: 8)
    }
}

struct PageHeader: View {
    var title: String
    var subtitle: String
    var actionTitle: String? = nil
    var actionSymbol: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Text(subtitle)
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.muted)
            }
            Spacer(minLength: 16)
            if let actionTitle, let actionSymbol, let action {
                Button(action: action) {
                    Label(actionTitle, systemImage: actionSymbol)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(ElephantTheme.accent)
            }
        }
    }
}

struct NativePanel<Content: View>: View {
    var content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .background(ElephantTheme.elevated.opacity(0.92), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(ElephantTheme.line, lineWidth: 1)
            )
            .shadow(color: Color.black.opacity(0.025), radius: 10, y: 4)
    }
}

struct SectionLabel: View {
    var title: String
    var subtitle: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.headline)
                .foregroundStyle(ElephantTheme.ink)
            if let subtitle {
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
            }
        }
    }
}

struct MetricTile: View {
    var label: String
    var value: String
    var symbol: String
    var tint: Color = ElephantTheme.accent

    var body: some View {
        NativePanel {
            HStack(spacing: 14) {
                Image(systemName: symbol)
                    .font(.title3)
                    .foregroundStyle(tint)
                    .frame(width: 26)
                VStack(alignment: .leading, spacing: 2) {
                    Text(value)
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                        .minimumScaleFactor(0.72)
                    Text(label)
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
        }
    }
}

struct Pill: View {
    var text: String
    var symbol: String? = nil
    var tint: Color = ElephantTheme.accent

    var body: some View {
        HStack(spacing: 6) {
            if let symbol {
                Image(systemName: symbol)
                    .font(.caption.weight(.semibold))
            }
            Text(text)
                .font(.caption.weight(.semibold))
                .lineLimit(1)
        }
        .foregroundStyle(tint)
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(tint.opacity(0.10), in: Capsule())
        .overlay(Capsule().stroke(tint.opacity(0.22), lineWidth: 1))
    }
}

struct EmptyLine: View {
    var symbol: String
    var text: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .foregroundStyle(ElephantTheme.faint)
                .frame(width: 20)
            Text(text)
                .font(.callout)
                .foregroundStyle(ElephantTheme.muted)
            Spacer(minLength: 0)
        }
        .padding(.vertical, 6)
    }
}

struct ProviderLogoView: View {
    var providerID: String
    var displayName: String = ""
    var size: CGFloat = 32

    var body: some View {
        Group {
            if isMotherProvider {
                BrandMark(size: size, framed: false)
            } else if let image = BundleAssets.image(named: "\(providerIconKey).png", subdirectory: "ProviderIcons") {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
            } else {
                Image(systemName: fallbackSymbol)
                    .font(.system(size: size * 0.48, weight: .semibold))
                    .foregroundStyle(fallbackTint)
            }
        }
        .frame(width: size, height: size)
        .padding(size * 0.10)
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.76), in: RoundedRectangle(cornerRadius: min(10, size * 0.24), style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: min(10, size * 0.24), style: .continuous)
                .stroke(ElephantTheme.line.opacity(0.72), lineWidth: 1)
        )
        .accessibilityLabel(providerTitle)
    }

    private var providerIconKey: String {
        let normalized = normalizedProvider
        if normalized.contains("copilot") { return "copilot" }
        if normalized.contains("gemini") { return "gemini-cli" }
        if normalized.contains("claude") { return "claude" }
        if normalized.contains("cursor") { return "cursor" }
        if normalized.contains("hermes") { return "hermes" }
        if normalized.contains("openclaw") { return "openclaw" }
        if normalized.contains("opencode") { return "opencode" }
        if normalized.contains("kimi") || normalized.contains("moonshot") { return "kimi" }
        if normalized == "pi" || normalized.contains("inflection") { return "pi" }
        if normalized.contains("codex") || normalized.contains("openai") { return "codex" }
        return normalized.isEmpty ? "agent" : normalized
    }

    private var normalizedProvider: String {
        let raw = providerID.isEmpty ? displayName : providerID
        return raw
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .replacingOccurrences(of: "_", with: "-")
    }

    private var isMotherProvider: Bool {
        let normalized = normalizedProvider
        let title = displayName.lowercased()
        return normalized.contains("mother-elephant")
            || normalized == "mother"
            || title.contains("mother elephant")
            || title == "elephant agent"
    }

    private var providerTitle: String {
        if !displayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return displayName
        }
        if normalizedProvider.contains("copilot") { return "GitHub Copilot" }
        if normalizedProvider.contains("gemini") { return "Gemini" }
        if normalizedProvider.contains("claude") { return "Claude Code" }
        if normalizedProvider.contains("cursor") { return "Cursor" }
        if normalizedProvider.contains("hermes") { return "Hermes" }
        if normalizedProvider.contains("openclaw") { return "OpenClaw" }
        if normalizedProvider.contains("opencode") { return "OpenCode" }
        if normalizedProvider.contains("kimi") || normalizedProvider.contains("moonshot") { return "Kimi" }
        if normalizedProvider.contains("codex") || normalizedProvider.contains("openai") { return "Codex" }
        return providerID.isEmpty ? "Local agent" : providerID
    }

    private var fallbackSymbol: String {
        if normalizedProvider.contains("copilot") { return "chevron.left.forwardslash.chevron.right" }
        if normalizedProvider.contains("gemini") { return "sparkle" }
        if normalizedProvider.contains("claude") { return "sparkles.rectangle.stack" }
        if normalizedProvider.contains("cursor") { return "cursorarrow" }
        if normalizedProvider.contains("hermes") { return "figure.walk.motion" }
        if normalizedProvider.contains("openclaw") { return "hand.raised" }
        if normalizedProvider.contains("opencode") { return "chevron.left.forwardslash.chevron.right" }
        if normalizedProvider.contains("kimi") || normalizedProvider.contains("moonshot") { return "moon.stars" }
        if normalizedProvider.contains("codex") || normalizedProvider.contains("openai") { return "terminal" }
        return "terminal"
    }

    private var fallbackTint: Color {
        if normalizedProvider.contains("copilot") { return ElephantTheme.green }
        if normalizedProvider.contains("gemini") { return ElephantTheme.accent }
        if normalizedProvider.contains("claude") { return ElephantTheme.ember }
        if normalizedProvider.contains("cursor") { return ElephantTheme.ink }
        if normalizedProvider.contains("hermes") { return ElephantTheme.orange }
        if normalizedProvider.contains("openclaw") { return ElephantTheme.ember }
        if normalizedProvider.contains("kimi") || normalizedProvider.contains("moonshot") { return ElephantTheme.green }
        return ElephantTheme.accent
    }
}

struct SurfaceActionButton: View {
    var title: String
    var subtitle: String? = nil
    var symbol: String
    var tint: Color = ElephantTheme.accent
    var isProminent = false
    var isDisabled = false
    var action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button {
            guard !isDisabled else { return }
            action()
        } label: {
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(iconFill)
                    Image(systemName: symbol)
                        .font(.system(size: 15, weight: .semibold))
                        .symbolRenderingMode(.hierarchical)
                        .foregroundStyle(iconTint)
                }
                .frame(width: 38, height: 38)

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(titleColor)
                        .lineLimit(1)
                        .minimumScaleFactor(0.82)
                    if let subtitle {
                        Text(subtitle)
                            .font(.caption)
                            .foregroundStyle(isDisabled ? ElephantTheme.faint : ElephantTheme.muted)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                Spacer(minLength: 0)

                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(isDisabled ? ElephantTheme.faint : tint)
                    .opacity(hovering && !isDisabled ? 1 : 0.58)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, subtitle == nil ? 9 : 11)
            .frame(maxWidth: .infinity, minHeight: subtitle == nil ? 54 : 66, alignment: .leading)
            .background(background, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(borderColor, lineWidth: 1)
            )
            .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(PressablePlainButtonStyle())
        .disabled(isDisabled)
        .opacity(isDisabled ? 0.62 : 1)
        .onHover { hovering = $0 }
        .help(subtitle.map { "\(title): \($0)" } ?? title)
        .accessibilityLabel(subtitle.map { "\(title), \($0)" } ?? title)
    }

    private var iconFill: Color {
        if isProminent { return Color.white.opacity(0.18) }
        return tint.opacity(hovering && !isDisabled ? 0.16 : 0.10)
    }

    private var iconTint: Color {
        if isDisabled { return ElephantTheme.faint }
        return isProminent ? .white : tint
    }

    private var titleColor: Color {
        if isDisabled { return ElephantTheme.faint }
        return isProminent ? .white : ElephantTheme.ink
    }

    private var background: Color {
        if isProminent {
            return hovering && !isDisabled ? tint.opacity(0.92) : tint
        }
        return hovering && !isDisabled
            ? Color(nsColor: .controlBackgroundColor).opacity(0.96)
            : Color(nsColor: .controlBackgroundColor).opacity(0.78)
    }

    private var borderColor: Color {
        if isProminent { return Color.white.opacity(0.24) }
        return tint.opacity(hovering && !isDisabled ? 0.34 : 0.18)
    }
}

struct SettingsRow: View {
    var label: String
    var value: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 18) {
            Text(label)
                .font(.callout)
                .foregroundStyle(ElephantTheme.muted)
                .frame(width: 148, alignment: .leading)
            Text(value)
                .font(.callout)
                .foregroundStyle(ElephantTheme.ink)
                .textSelection(.enabled)
                .lineLimit(3)
                .truncationMode(.middle)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 7)
    }
}

struct SettingsFieldRow<Accessory: View>: View {
    var label: String
    var value: String
    var accessory: Accessory

    init(
        label: String,
        value: String,
        @ViewBuilder accessory: () -> Accessory
    ) {
        self.label = label
        self.value = value
        self.accessory = accessory()
    }

    var body: some View {
        HStack(alignment: .center, spacing: 18) {
            Text(label)
                .font(.callout)
                .foregroundStyle(ElephantTheme.muted)
                .frame(width: 148, alignment: .leading)
            Text(value)
                .font(.callout)
                .foregroundStyle(ElephantTheme.ink)
                .textSelection(.enabled)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: 0)
            accessory
        }
        .padding(.vertical, 7)
    }
}

struct FlowLayout: View {
    var items: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(rows, id: \.self) { row in
                HStack(spacing: 8) {
                    ForEach(row, id: \.self) { item in
                        Pill(text: item)
                    }
                }
            }
        }
    }

    private var rows: [[String]] {
        var result: [[String]] = []
        var current: [String] = []
        var width = 0
        for item in items.prefix(12) {
            let next = min(max(item.count * 8 + 34, 84), 210)
            if width + next > 420, !current.isEmpty {
                result.append(current)
                current = [item]
                width = next
            } else {
                current.append(item)
                width += next
            }
        }
        if !current.isEmpty {
            result.append(current)
        }
        return result
    }
}
