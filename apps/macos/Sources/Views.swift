import SwiftUI
import AppKit

struct RootView: View {
    @EnvironmentObject private var model: ElephantAppModel
    @AppStorage("elephant.mac.onboardingComplete") private var onboardingComplete = false
    @AppStorage("elephant.mac.sidebarVisible") private var sidebarVisible = true
    private let sidebarWidth: CGFloat = 96

    var body: some View {
        ZStack(alignment: .topLeading) {
            AppBackground()
            HStack(spacing: 0) {
                if sidebarVisible {
                    SidebarView()
                        .frame(width: sidebarWidth)
                        .transition(.move(edge: .leading).combined(with: .opacity))
                }
                DetailView(section: model.selectedSection)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .animation(.easeInOut(duration: 0.18), value: sidebarVisible)
        }
        .sheet(isPresented: $model.showingOnboarding) {
            OnboardingFlow {
                onboardingComplete = true
                model.completeOnboarding()
            }
            .environmentObject(model)
        }
        .onChange(of: model.snapshot.hasElephant) { hasElephant in
            if hasElephant {
                onboardingComplete = true
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .elephantToggleSidebar)) { notification in
            if let visible = notification.object as? Bool {
                sidebarVisible = visible
            } else {
                sidebarVisible.toggle()
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .elephantNewChat)) { _ in
            model.startNewChat()
        }
        .onReceive(NotificationCenter.default.publisher(for: .elephantSelectSection)) { notification in
            guard let rawValue = notification.object as? String,
                  let section = AppSection(rawValue: rawValue) else { return }
            model.selectedSection = section
        }
    }
}

struct SidebarView: View {
    @EnvironmentObject private var model: ElephantAppModel
    private let glassWidth: CGFloat = 76
    private let brandHitSize: CGFloat = 52
    private let iconHitSize: CGFloat = 48
    private let navSpacing: CGFloat = 8
    private let glassVerticalPadding: CGFloat = 14
    private let footerReservedHeight: CGFloat = 144

    var body: some View {
        GeometryReader { proxy in
            let availableNavHeight = max(360, proxy.size.height - footerReservedHeight - 48)
            let navHeight = min(navigationContentHeight, availableNavHeight)
            let needsScrolling = navigationContentHeight > availableNavHeight

            VStack(spacing: 0) {
                Spacer(minLength: 24)

                navigationGlass(height: navHeight, scrolls: needsScrolling)

                Spacer(minLength: 16)

                VStack(spacing: 10) {
                    StatusDot(tint: phaseTint)
                        .help(statusLine)
                    SidebarIconButton(
                        section: .provider,
                        selected: model.selectedSection == .provider
                    ) {
                        model.selectedSection = .provider
                    }
                    SidebarIconButton(
                        section: .settings,
                        selected: model.selectedSection == .settings
                    ) {
                        model.selectedSection = .settings
                    }
                }
                .padding(.bottom, 16)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.clear)
    }

    private var navigationContentHeight: CGFloat {
        let buttonCount = CGFloat(AppSection.primary.count)
        let buttonsHeight = buttonCount * iconHitSize + max(0, buttonCount - 1) * navSpacing
        return glassVerticalPadding * 2 + brandHitSize + 12 + 4 + buttonsHeight
    }

    private func navigationGlass(height: CGFloat, scrolls: Bool) -> some View {
        VStack(spacing: 12) {
            Button {
                model.selectedSection = .home
            } label: {
                BrandMark(size: 34)
                    .frame(width: brandHitSize, height: brandHitSize)
                    .contentShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            .buttonStyle(PressablePlainButtonStyle())
            .help("Home")

            if scrolls {
                ScrollView(.vertical, showsIndicators: false) {
                    navigationButtons
                        .padding(.vertical, 2)
                }
            } else {
                navigationButtons
                    .padding(.vertical, 2)
            }
        }
        .padding(.vertical, glassVerticalPadding)
        .frame(width: glassWidth, height: height, alignment: .top)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(Color(nsColor: .separatorColor).opacity(0.16), lineWidth: 1)
        )
    }

    private var navigationButtons: some View {
        VStack(spacing: navSpacing) {
            ForEach(AppSection.primary) { section in
                SidebarIconButton(
                    section: section,
                    selected: model.selectedSection == section
                ) {
                    model.selectedSection = section
                    if section == .wake {
                        model.focusComposer()
                    }
                }
            }
        }
    }

    private var statusLine: String {
        switch model.corePhase {
        case .ready:
            return model.snapshot.readyForInteraction ? "Elephant ready" : "Warming local model"
        case .starting: return "Starting local core"
        case .failed: return "Local core needs attention"
        case .idle: return "Local core idle"
        }
    }

    private var phaseTint: Color {
        switch model.corePhase {
        case .ready: return model.snapshot.readyForInteraction ? ElephantTheme.green : ElephantTheme.accent
        case .starting: return ElephantTheme.accent
        case .failed: return ElephantTheme.orange
        case .idle: return ElephantTheme.faint
        }
    }
}

struct SidebarCollapseButton: View {
    var symbol: String
    var help: String
    var action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(hovering ? ElephantTheme.ink : ElephantTheme.muted)
                .frame(width: 48, height: 48)
                .background(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(hovering ? Color(nsColor: .controlBackgroundColor).opacity(0.78) : Color.clear)
                )
                .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .buttonStyle(PressablePlainButtonStyle())
        .help(help)
        .accessibilityLabel(help)
        .onHover { hovering = $0 }
    }
}

struct TitlebarSidebarButton: View {
    var help: String
    var action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            Image(systemName: "sidebar.left")
                .font(.system(size: 15, weight: .medium))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(hovering ? ElephantTheme.ink : ElephantTheme.ink.opacity(0.82))
                .frame(width: 30, height: 30)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(hovering ? Color(nsColor: .controlBackgroundColor).opacity(0.78) : Color.clear)
                )
                .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(PressablePlainButtonStyle())
        .help(help)
        .accessibilityLabel(help)
        .onHover { hovering = $0 }
    }
}

struct SidebarIconButton: View {
    var section: AppSection
    var selected: Bool
    var action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            Image(systemName: section.symbol)
                .font(.system(size: 18, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .frame(width: 48, height: 48)
                .foregroundStyle(selected ? .white : ElephantTheme.muted)
                .background(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(background)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .stroke(selected ? ElephantTheme.accent.opacity(0.12) : ElephantTheme.line.opacity(hovering ? 0.70 : 0), lineWidth: 1)
                )
                .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .buttonStyle(PressablePlainButtonStyle())
        .help(section.title)
        .accessibilityLabel(section.title)
        .onHover { hovering = $0 }
    }

    private var background: Color {
        if selected { return ElephantTheme.accent }
        return hovering ? Color(nsColor: .controlBackgroundColor).opacity(0.78) : Color.clear
    }
}

struct DetailView: View {
    var section: AppSection

    var body: some View {
        Group {
            if section == .wake {
                detailContent
                    .padding(.horizontal, 30)
                    .padding(.top, 54)
                    .padding(.bottom, 26)
                    .frame(maxWidth: maxContentWidth)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            } else {
                ScrollView {
                    detailContent
                        .padding(.horizontal, 30)
                        .padding(.top, 54)
                        .padding(.bottom, 26)
                        .frame(maxWidth: maxContentWidth)
                        .frame(maxWidth: .infinity)
                }
            }
        }
        .background(Color.clear)
    }

    @ViewBuilder
    private var detailContent: some View {
        VStack(spacing: 22) {
            switch section {
            case .home:
                HomeView()
            case .wake:
                WakeView()
            case .you:
                YouView()
            case .diary:
                DiaryView()
            case .skills:
                SkillsView()
            case .tools:
                ToolsView()
            case .messaging:
                MessagingView()
            case .herd:
                HerdView()
            case .usage:
                UsageView()
            case .cron:
                CronView()
            case .learn:
                LearnView()
            case .sources:
                SourcesView()
            case .provider:
                ProviderView()
            case .settings:
                SettingsView()
            }
        }
        .frame(maxHeight: section == .wake ? .infinity : nil, alignment: .top)
    }

    private var maxContentWidth: CGFloat {
        1420
    }
}

struct HomeView: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: model.userDisplayName,
                subtitle: homeSubtitle,
                actionTitle: "Chat",
                actionSymbol: "bubble.left.and.bubble.right"
            ) {
                model.selectedSection = .wake
                model.focusComposer()
            }

            CommandCenterPanel(phaseTint: phaseTint, connectionText: connectionText)

            HomeReadinessStrip()
            HomeContinuityPanel()
            HomeKnowledgeOverview()
            PersonalModelMapPanel()
        }
    }

    private var homeSubtitle: String {
        if model.snapshot.hasElephant {
            return "Your local Personal Model with visible memory, questions, and evidence."
        }
        return "Create a local Personal Model, then add sources when context matters."
    }

    private var connectionText: String {
        switch model.corePhase {
        case .ready:
            if model.snapshot.readyForInteraction {
                return model.snapshot.hasElephant ? "Connected to Elephant" : "Ready for first chat"
            }
            return "Warming model"
        case .starting: return "Starting Elephant"
        case .failed: return "Needs attention"
        case .idle: return "Idle"
        }
    }

    private var phaseTint: Color {
        switch model.corePhase {
        case .ready: return model.snapshot.readyForInteraction ? ElephantTheme.green : ElephantTheme.accent
        case .starting: return ElephantTheme.accent
        case .failed: return ElephantTheme.orange
        case .idle: return ElephantTheme.faint
        }
    }
}

struct HomeReadinessStrip: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            LazyVGrid(columns: columns, spacing: 10) {
                HomeReadinessButton(item: providerItem)
                HomeReadinessButton(item: memoryItem)
                HomeReadinessButton(item: messagingItem)
                HomeReadinessButton(item: learnItem)
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var columns: [GridItem] {
        [
            GridItem(.flexible(), spacing: 10),
            GridItem(.flexible(), spacing: 10),
            GridItem(.flexible(), spacing: 10),
            GridItem(.flexible(), spacing: 10)
        ]
    }

    private var providerItem: HomeReadinessItem {
        let hasProvider = !model.snapshot.providerID.isEmpty
        let modelName = model.snapshot.providerModelID.isEmpty ? "choose a model" : model.snapshot.providerModelID
        let status = !hasProvider
            ? "setup"
            : model.snapshot.readyForInteraction
                ? "ready"
                : model.snapshot.providerReady ? "warming" : providerStatusLabel
        return HomeReadinessItem(
            title: "Model",
            detail: hasProvider ? modelName : "provider setup",
            status: status,
            symbol: "cpu",
            tint: providerTint,
            target: .settings
        )
    }

    private var memoryItem: HomeReadinessItem {
        let indexed = model.snapshot.semanticEntries > 0 || model.snapshot.semanticStatus.lowercased().contains("ready")
        let healthy = indexed && model.snapshot.localModelWarm
        return HomeReadinessItem(
            title: "Memory",
            detail: "\(model.snapshot.facts) facts · \(model.snapshot.semanticEntries) evidence",
            status: healthy ? "ready" : "warming",
            symbol: "point.3.connected.trianglepath.dotted",
            tint: healthy ? ElephantTheme.green : ElephantTheme.orange,
            target: .you
        )
    }

    private var messagingItem: HomeReadinessItem {
        let running = model.snapshot.gatewayRunning
        let configured = model.snapshot.gatewayConfigured
        let total = max(model.snapshot.gatewayServices, model.snapshot.gatewayItems.count)
        let tint = running > 0 ? ElephantTheme.green : configured > 0 ? ElephantTheme.green : ElephantTheme.orange
        let status = running > 0 ? "live" : configured > 0 ? "configured" : "setup"
        return HomeReadinessItem(
            title: "Messaging",
            detail: "\(running) live · \(configured)/\(total) configured",
            status: status,
            symbol: "message.badge",
            tint: tint,
            target: .messaging
        )
    }

    private var learnItem: HomeReadinessItem {
        let worker = model.snapshot.workerStatus.isEmpty ? "unknown" : model.snapshot.workerStatus
        let active = model.snapshot.learningItems.filter {
            let status = $0.status.lowercased()
            return !status.contains("completed") && !status.contains("failed") && !status.contains("cancel")
        }.count
        let tint = active > 0 ? ElephantTheme.accent : worker.lowercased().contains("stopped") ? ElephantTheme.orange : ElephantTheme.green
        return HomeReadinessItem(
            title: "Learn",
            detail: active > 0 ? "\(active) active jobs" : worker,
            status: active > 0 ? "running" : worker,
            symbol: "brain.head.profile",
            tint: tint,
            target: .learn
        )
    }

    private var providerStatusLabel: String {
        if model.snapshot.providerStatus == "unknown", !model.snapshot.providerID.isEmpty {
            return "configured"
        }
        return model.snapshot.providerStatus == "unknown" ? "setup" : model.snapshot.providerStatus
    }

    private var providerTint: Color {
        let value = providerStatusLabel.lowercased()
        if value.contains("setup") || value.contains("missing") || model.snapshot.providerID.isEmpty {
            return ElephantTheme.orange
        }
        if !model.snapshot.localModelWarm {
            return ElephantTheme.accent
        }
        if value.contains("unknown") {
            return ElephantTheme.faint
        }
        return ElephantTheme.green
    }
}

private struct HomeReadinessItem {
    var title: String
    var detail: String
    var status: String
    var symbol: String
    var tint: Color
    var target: AppSection
}

private struct HomeReadinessButton: View {
    @EnvironmentObject private var model: ElephantAppModel
    var item: HomeReadinessItem

    var body: some View {
        Button {
            model.selectedSection = item.target
        } label: {
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(item.tint.opacity(0.11))
                    Image(systemName: item.symbol)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(item.tint)
                }
                .frame(width: 38, height: 38)

                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Text(item.title)
                            .font(.callout.weight(.semibold))
                            .foregroundStyle(ElephantTheme.ink)
                        StatusDot(tint: item.tint)
                    }
                    Text(item.detail)
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(1)
                }

                Spacer(minLength: 0)

                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.faint)
            }
            .padding(12)
            .frame(maxWidth: .infinity, minHeight: 64, alignment: .leading)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(item.tint.opacity(0.18), lineWidth: 1)
            )
            .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(PressablePlainButtonStyle())
        .help("\(item.title): \(item.status)")
        .accessibilityLabel("\(item.title), \(item.status)")
    }
}

struct HomeContinuityPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    SectionLabel(
                        title: "Carry into the next reply",
                        subtitle: "The personal context Elephant should keep warm before it answers."
                    )
                    Spacer(minLength: 0)
                    if let question = nextQuestion {
                        Pill(text: question.statusTitle, symbol: "questionmark.bubble", tint: questionTint(question))
                    }
                }

                HStack(alignment: .top, spacing: 0) {
                    HomeContinuityColumn(
                        title: "Alive now",
                        symbol: "waveform.path.ecg",
                        tint: ElephantTheme.orange,
                        text: aliveNow
                    )
                    VerticalHairline()
                    HomeContinuityColumn(
                        title: "How to be with you",
                        symbol: "person.wave.2",
                        tint: ElephantTheme.accent,
                        text: relationshipMode
                    )
                    VerticalHairline()
                    HomeContinuityColumn(
                        title: "Care to remember",
                        symbol: "lock.shield",
                        tint: ElephantTheme.green,
                        text: careBoundary
                    )
                }
                .padding(14)
                .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))

                Divider()

                if let question = nextQuestion {
                    HomeContinuityQuestionRow(question: question)
                } else {
                    EmptyLine(symbol: "questionmark.bubble", text: "No open question is waiting for review.")
                }
            }
        }
    }

    private var aliveNow: String {
        firstProfileValue(["Working on", "Current focus", "Now"])
            ?? firstFactText(lens: "pulse")
            ?? "No current focus yet. Start a chat or diary entry and Elephant will keep the thread visible."
    }

    private var relationshipMode: String {
        firstProfileValue(["Relationship mode", "Communication", "Speaks"])
            ?? firstFactText(lens: "identity", topicContains: ["style", "companion", "language"])
            ?? "Be specific, calm, and easy to correct."
    }

    private var careBoundary: String {
        firstProfileValue(["Safety boundaries", "Care context", "Medication allergies", "Health notes", "Food allergies"])
            ?? firstFactText(lens: "identity", topicContains: ["boundary", "care", "allergy", "health"])
            ?? "No care boundary has been written yet."
    }

    private var nextQuestion: PersonalModelQuestionItem? {
        model.snapshot.questionItems
            .filter { $0.status == "ready" || $0.status == "asked" }
            .sorted { left, right in
                if left.priority == right.priority {
                    return left.createdAt > right.createdAt
                }
                return left.priority > right.priority
            }
            .first
    }

    private func firstProfileValue(_ labels: [String]) -> String? {
        for label in labels {
            if let value = model.snapshot.profileFacts.first(where: { $0.label == label })?.value.trimmingCharacters(in: .whitespacesAndNewlines),
               !value.isEmpty {
                return value
            }
        }
        return nil
    }

    private func firstFactText(lens: String, topicContains needles: [String] = []) -> String? {
        model.snapshot.personalModelFacts
            .filter { fact in
                guard fact.status.lowercased() != "deleted",
                      fact.lens.lowercased().contains(lens) else { return false }
                guard !needles.isEmpty else { return true }
                let topic = fact.topic.lowercased()
                return needles.contains { topic.contains($0) }
            }
            .map { $0.text.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty }
    }

    private func questionTint(_ question: PersonalModelQuestionItem) -> Color {
        question.status == "asked" ? ElephantTheme.orange : ElephantTheme.accent
    }
}

private struct HomeContinuityColumn: View {
    var title: String
    var symbol: String
    var tint: Color
    var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 8) {
                Image(systemName: symbol)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(tint)
                    .frame(width: 18)
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
            }

            Text(text)
                .font(.callout.weight(.medium))
                .foregroundStyle(ElephantTheme.ink)
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .padding(.horizontal, 12)
        .padding(.vertical, 4)
    }
}

private struct HomeContinuityQuestionRow: View {
    @EnvironmentObject private var model: ElephantAppModel
    var question: PersonalModelQuestionItem

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: "questionmark.bubble")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(question.status == "asked" ? ElephantTheme.orange : ElephantTheme.accent)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 4) {
                Text("Next useful question")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                Text(question.text)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(ElephantTheme.ink)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 0)

            Button("Review") {
                model.selectedSection = .you
            }
            .controlSize(.small)
        }
    }
}

private struct VerticalHairline: View {
    var body: some View {
        Rectangle()
            .fill(ElephantTheme.line)
            .frame(width: 1)
            .padding(.vertical, 4)
    }
}

struct HomeKnowledgeOverview: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 18) {
                SectionLabel(
                    title: "What I know so far",
                    subtitle: "Drawn directly from Personal Model claims and profile anchors. Update a claim and this view updates too."
                )

                ProfileFactsTable(facts: profileFacts)

                Divider()

                LazyVGrid(columns: columns, spacing: 12) {
                    HomeLensColumn(
                        title: "Identity",
                        symbol: "person.crop.circle",
                        tint: ElephantTheme.accent,
                        facts: facts(for: "identity"),
                        empty: "No stable identity facts yet."
                    )
                    HomeLensColumn(
                        title: "World",
                        symbol: "globe",
                        tint: ElephantTheme.green,
                        facts: facts(for: "world"),
                        empty: "No people, places, or project facts yet."
                    )
                    HomeLensColumn(
                        title: "Pulse",
                        symbol: "waveform.path.ecg",
                        tint: ElephantTheme.orange,
                        facts: facts(for: "pulse"),
                        empty: "No current-state facts yet."
                    )
                    HomeLensColumn(
                        title: "Journey",
                        symbol: "map",
                        tint: ElephantTheme.accent.opacity(0.82),
                        facts: facts(for: "journey"),
                        empty: "No journey facts yet."
                    )
                }
            }
        }
    }

    private var columns: [GridItem] {
        [
            GridItem(.flexible(), spacing: 12),
            GridItem(.flexible(), spacing: 12),
            GridItem(.flexible(), spacing: 12),
            GridItem(.flexible(), spacing: 12)
        ]
    }

    private var profileFacts: [ProfileFact] {
        if !model.snapshot.profileFacts.isEmpty {
            return model.snapshot.profileFacts.map {
                ProfileFact(label: $0.label, value: $0.value, full: $0.full)
            }
        }
        return ProfileFactCatalog.rows.compactMap { item in
            guard let fact = model.snapshot.personalModelFacts.first(where: { fact in
                fact.status.lowercased() == "active" && fact.topic == item.topic
            }) else { return nil }
            return ProfileFact(label: item.label, value: stripFactPrefix(fact.text), full: item.full)
        }
    }

    private func facts(for lens: String) -> [PersonalModelFact] {
        model.snapshot.personalModelFacts
            .filter { $0.status != "deleted" && $0.lens.lowercased().contains(lens) }
            .prefix(3)
            .map { $0 }
    }

    private func stripFactPrefix(_ text: String) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let range = trimmed.range(of: #"^[^:：]+[：:]\s*"#, options: .regularExpression) else {
            return trimmed.trimmingCharacters(in: CharacterSet(charactersIn: "。．."))
        }
        return String(trimmed[range.upperBound...])
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "。．."))
    }
}

private struct ProfileFactCatalog {
    struct Item {
        var topic: String
        var label: String
        var full: Bool = false
    }

    static let rows: [Item] = [
        Item(topic: "identity.anchor.name.preferred", label: "Name"),
        Item(topic: "identity.anchor.gender.self_description", label: "Gender"),
        Item(topic: "world.places.city.current", label: "City"),
        Item(topic: "identity.anchor.birth.date", label: "Birth date"),
        Item(topic: "identity.style.language.first", label: "Speaks"),
        Item(topic: "pulse.chapter.work.role", label: "Working on", full: true),
        Item(topic: "identity.character.mbti.type", label: "MBTI", full: true),
        Item(topic: "identity.style.hobbies.personal", label: "Hobbies", full: true),
        Item(topic: "identity.style.companion.posture", label: "Relationship mode", full: true),
        Item(topic: "identity.body.allergy.medication", label: "Medication allergies", full: true),
        Item(topic: "identity.body.condition.chronic", label: "Health notes", full: true),
        Item(topic: "identity.body.allergy.food", label: "Food allergies", full: true),
        Item(topic: "identity.body.history.trauma", label: "Care context", full: true),
        Item(topic: "identity.body.boundary.personal", label: "Safety boundaries", full: true)
    ]
}

private struct ProfileFact: Identifiable {
    var id: String { "\(label)-\(value)" }
    var label: String
    var value: String
    var full: Bool
}

private struct ProfileFactRow: Identifiable {
    var id: String { "\(left.id)-\(right?.id ?? "full")" }
    var left: ProfileFact
    var right: ProfileFact?
    var full: Bool = false
}

private struct ProfileFactsTable: View {
    var facts: [ProfileFact]

    var body: some View {
        if facts.isEmpty {
            EmptyLine(symbol: "person.text.rectangle", text: "No structured profile facts yet.")
        } else {
            VStack(spacing: 0) {
                ForEach(rows) { row in
                    HStack(alignment: .top, spacing: 0) {
                        ProfileFactPair(fact: row.left)
                        if let right = row.right, !row.full {
                            Divider()
                                .frame(height: 42)
                            ProfileFactPair(fact: right)
                        }
                    }
                    .padding(.vertical, 9)
                    if row.id != rows.last?.id {
                        Divider()
                    }
                }
            }
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))
        }
    }

    private var rows: [ProfileFactRow] {
        var result: [ProfileFactRow] = []
        var used = Set<String>()

        func take(_ label: String) -> ProfileFact? {
            guard let fact = facts.first(where: { $0.label == label && !used.contains($0.id) }) else { return nil }
            used.insert(fact.id)
            return fact
        }

        func pushPair(_ leftLabel: String, _ rightLabel: String) {
            let left = take(leftLabel)
            let right = take(rightLabel)
            if let left {
                result.append(ProfileFactRow(left: left, right: right))
            } else if let right {
                result.append(ProfileFactRow(left: right, right: nil))
            }
        }

        pushPair("Name", "Gender")
        pushPair("City", "Birth date")
        pushPair("Speaks", "Medication allergies")

        for fact in facts where !used.contains(fact.id) {
            result.append(ProfileFactRow(left: fact, right: nil, full: fact.full))
            used.insert(fact.id)
        }
        return result
    }
}

private struct ProfileFactPair: View {
    var fact: ProfileFact

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(fact.label)
                .font(.caption.weight(.semibold))
                .foregroundStyle(ElephantTheme.muted)
                .frame(width: 118, alignment: .leading)
            Text(fact.value.isEmpty ? "n/a" : fact.value)
                .font(.callout.weight(.medium))
                .foregroundStyle(ElephantTheme.ink)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct HomeLensColumn: View {
    var title: String
    var symbol: String
    var tint: Color
    var facts: [PersonalModelFact]
    var empty: String
    private let cardHeight: CGFloat = 196

    var body: some View {
        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color(nsColor: .controlBackgroundColor))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(tint.opacity(0.20), lineWidth: 1)
                )

            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    Image(systemName: symbol)
                        .foregroundStyle(tint)
                    Text(title)
                        .font(.headline)
                        .foregroundStyle(ElephantTheme.ink)
                    Spacer(minLength: 0)
                    Text("\(facts.count)")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.muted)
                }

                if facts.isEmpty {
                    Text(empty)
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.muted)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                } else {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(facts) { fact in
                            HStack(alignment: .top, spacing: 8) {
                                Circle()
                                    .fill(tint)
                                    .frame(width: 5, height: 5)
                                    .padding(.top, 7)
                                Text(fact.text)
                                    .font(.callout)
                                    .foregroundStyle(ElephantTheme.ink)
                                    .lineLimit(2)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .clipped()
        }
        .frame(maxWidth: .infinity)
        .frame(height: cardHeight)
    }
}

struct CommandCenterPanel: View {
    @EnvironmentObject private var model: ElephantAppModel
    var phaseTint: Color
    var connectionText: String

    var body: some View {
        NativePanel {
            HStack(alignment: .center, spacing: 30) {
                VStack(alignment: .center, spacing: 14) {
                    Button {
                        model.pickUserAvatar()
                    } label: {
                        UserAvatarOrbitView(size: 138, editable: true)
                    }
                    .buttonStyle(PressablePlainButtonStyle())
                    .help("Change profile photo")
                    .accessibilityLabel("Change profile photo")

                    Text(model.userDisplayName)
                        .font(.system(size: 25, weight: .semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                        .help(model.userDisplayName)

                    Text("Personal Model")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.muted)
                        .textCase(.uppercase)

                    HStack(spacing: 8) {
                        StatusDot(tint: phaseTint)
                        Text(connectionText)
                            .font(.callout.weight(.semibold))
                            .foregroundStyle(phaseTint)
                    }

                    Divider()
                        .padding(.top, 4)

                    VStack(spacing: 9) {
                        TodaySignalRow(value: "\(model.snapshot.facts)", label: "Reviewed facts", symbol: "checkmark.seal")
                        TodaySignalRow(value: "\(model.snapshot.waitingQuestions)", label: "Questions waiting", symbol: "questionmark.bubble", tint: ElephantTheme.orange)
                        TodaySignalRow(value: "\(model.snapshot.semanticEntries)", label: "Evidence points", symbol: "doc.text.magnifyingglass", tint: ElephantTheme.green)
                    }
                }
                .frame(width: 250)

                Divider()
                    .frame(height: 250)

                PromptStagePanel(phaseTint: phaseTint)
            }
            .frame(minHeight: 294)
        }
    }
}

struct UserAvatarOrbitView: View {
    @EnvironmentObject private var model: ElephantAppModel
    var size: CGFloat = 138
    var editable = false

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    LinearGradient(
                        colors: [
                            ElephantTheme.accent.opacity(0.11),
                            ElephantTheme.green.opacity(0.09),
                            Color(nsColor: .textBackgroundColor)
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .overlay(Circle().stroke(ElephantTheme.line, lineWidth: 1))

            Circle()
                .trim(from: 0.08, to: 0.82)
                .stroke(ElephantTheme.accent.opacity(0.34), style: StrokeStyle(lineWidth: 2, lineCap: .round))
                .padding(size * 0.13)

            Circle()
                .trim(from: 0.16, to: 0.66)
                .stroke(ElephantTheme.green.opacity(0.34), style: StrokeStyle(lineWidth: 2, lineCap: .round))
                .rotationEffect(.degrees(136))
                .padding(size * 0.25)

            ForEach(0..<6, id: \.self) { index in
                Circle()
                    .fill(index == 2 ? ElephantTheme.orange : ElephantTheme.accent)
                    .frame(width: index == 2 ? 8 : 6, height: index == 2 ? 8 : 6)
                    .offset(x: size * 0.49)
                    .rotationEffect(.degrees(Double(index) * 58 + 12))
                    .opacity(0.72)
            }

            UserAvatarImage(size: size * 0.54, name: model.userDisplayName, url: model.userAvatarURL)

            if editable {
                Image(systemName: "camera.fill")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 28, height: 28)
                    .background(ElephantTheme.accent, in: Circle())
                    .overlay(Circle().stroke(Color(nsColor: .windowBackgroundColor), lineWidth: 2))
                    .offset(x: size * 0.25, y: size * 0.25)
            }
        }
        .frame(width: size, height: size)
    }
}

struct UserAvatarImage: View {
    var size: CGFloat
    var name: String
    var url: URL?

    var body: some View {
        Group {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                ZStack {
                    LinearGradient(
                        colors: [ElephantTheme.accent.opacity(0.16), ElephantTheme.green.opacity(0.14)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                    Text(initials)
                        .font(.system(size: max(18, size * 0.28), weight: .semibold))
                        .foregroundStyle(ElephantTheme.ink)
                }
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .overlay(Circle().stroke(Color(nsColor: .windowBackgroundColor).opacity(0.85), lineWidth: 3))
        .overlay(Circle().stroke(ElephantTheme.line, lineWidth: 1))
        .shadow(color: Color.black.opacity(0.08), radius: 8, y: 4)
    }

    private var image: NSImage? {
        guard let url else { return nil }
        return NSImage(contentsOf: url)
    }

    private var initials: String {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "You" }
        return String(trimmed.prefix(2)).uppercased()
    }
}

struct MemoryOrbitView: View {
    var body: some View {
        ZStack {
            Circle()
                .fill(
                    LinearGradient(
                        colors: [
                            ElephantTheme.accent.opacity(0.12),
                            ElephantTheme.green.opacity(0.10),
                            Color(nsColor: .textBackgroundColor)
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .overlay(Circle().stroke(ElephantTheme.line, lineWidth: 1))

            Circle()
                .trim(from: 0.08, to: 0.82)
                .stroke(ElephantTheme.accent.opacity(0.34), style: StrokeStyle(lineWidth: 2, lineCap: .round))
                .padding(18)

            Circle()
                .trim(from: 0.16, to: 0.66)
                .stroke(ElephantTheme.green.opacity(0.34), style: StrokeStyle(lineWidth: 2, lineCap: .round))
                .rotationEffect(.degrees(136))
                .padding(36)

            ForEach(0..<6, id: \.self) { index in
                Circle()
                    .fill(index == 2 ? ElephantTheme.orange : ElephantTheme.accent)
                    .frame(width: index == 2 ? 8 : 6, height: index == 2 ? 8 : 6)
                    .offset(x: 68)
                    .rotationEffect(.degrees(Double(index) * 58 + 12))
                    .opacity(0.72)
            }

            MemoryCoreGlyph()
        }
        .accessibilityHidden(true)
    }
}

struct MemoryCoreGlyph: View {
    var body: some View {
        ZStack {
            Circle()
                .fill(.ultraThinMaterial)
            Circle()
                .stroke(ElephantTheme.line, lineWidth: 1)
            Image(systemName: "circle.grid.cross")
                .font(.system(size: 30, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(ElephantTheme.ink)
        }
        .frame(width: 72, height: 72)
    }
}

struct PromptStagePanel: View {
    @EnvironmentObject private var model: ElephantAppModel
    var phaseTint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            HStack {
                Pill(text: "Local-first", symbol: "lock.shield", tint: phaseTint)
                Spacer()
                Text(model.snapshot.latestCompletedAt.isEmpty ? "Reflect when ready" : "Last reflect complete")
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
            }

            VStack(alignment: .leading, spacing: 10) {
                Text("Ask, remember, reflect.")
                    .font(.system(size: 34, weight: .semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Text("Elephant keeps working memory visible: what it knows, what it is unsure about, and where the evidence came from.")
                    .font(.body)
                    .foregroundStyle(ElephantTheme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Button {
                model.selectedSection = .wake
                model.focusComposer()
            } label: {
                HStack {
                    Text("Ask your assistant anything...")
                        .font(.headline.weight(.semibold))
                    Spacer()
                    Image(systemName: "arrow.right")
                        .font(.headline.weight(.semibold))
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 14)
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .tint(ElephantTheme.accent)

            HStack(spacing: 12) {
                TodayCommand(title: "Add evidence", symbol: "folder.badge.plus") {
                    Task { await model.pickSources() }
                }
                TodayCommand(title: "Review questions", symbol: "questionmark.bubble") {
                    model.selectedSection = .you
                }
                TodayCommand(title: "Run reflect", symbol: "brain.head.profile") {
                    Task { await model.runReflect(trigger: "home") }
                }
            }
        }
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct TodaySignalRow: View {
    var value: String
    var label: String
    var symbol: String
    var tint: Color = ElephantTheme.accent

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .foregroundStyle(tint)
                .frame(width: 22)
            Text(value)
                .font(.headline.weight(.semibold))
                .foregroundStyle(ElephantTheme.ink)
                .frame(width: 42, alignment: .leading)
            Text(label)
                .font(.callout)
                .foregroundStyle(ElephantTheme.muted)
            Spacer(minLength: 0)
        }
    }
}

struct TodayCommand: View {
    var title: String
    var symbol: String
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .font(.callout.weight(.semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 9)
        }
        .buttonStyle(.bordered)
    }
}

struct ReviewQueuePanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    SectionLabel(title: "Respond Queue", subtitle: "\(model.snapshot.waitingQuestions) open")
                    Spacer()
                    Button {
                        model.selectedSection = .you
                    } label: {
                        Image(systemName: "arrow.right")
                    }
                    .buttonStyle(.borderless)
                }

                if model.snapshot.sampleQuestions.isEmpty {
                    EmptyLine(symbol: "questionmark.bubble", text: "No questions waiting right now.")
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(model.snapshot.sampleQuestions.prefix(3), id: \.self) { question in
                            Text(question)
                                .font(.callout)
                                .foregroundStyle(ElephantTheme.ink)
                                .lineLimit(2)
                                .padding(.vertical, 5)
                        }
                    }
                }
            }
        }
    }
}

struct NextActionsPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                SectionLabel(title: "Next", subtitle: "High-signal actions")
                NextActionRow(symbol: "bubble.left.and.bubble.right", title: "Chat", detail: "Continue the current thread") {
                    model.selectedSection = .wake
                    model.focusComposer()
                }
                NextActionRow(symbol: "folder.badge.plus", title: "Sources", detail: "\(model.stagedSources.count) vaults staged") {
                    model.selectedSection = .sources
                }
                NextActionRow(symbol: "brain.head.profile", title: "Reflect", detail: model.isReflecting ? "Running" : "Update the queue") {
                    Task { await model.runReflect(trigger: "next") }
                }
            }
        }
    }
}

struct NextActionRow: View {
    var symbol: String
    var title: String
    var detail: String
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: symbol)
                    .foregroundStyle(ElephantTheme.accent)
                    .frame(width: 22)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.faint)
            }
            .padding(.vertical, 5)
        }
        .buttonStyle(.plain)
    }
}

struct RuntimeMiniPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                SectionLabel(title: "Quiet System", subtitle: "Details live in Settings")
                SettingsRow(label: "Core", value: model.corePhase.label)
                SettingsRow(label: "Provider", value: model.snapshot.providerStatus)
                SettingsRow(label: "Worker", value: model.snapshot.workerStatus)
            }
        }
        .frame(width: 340)
    }
}

struct WakeView: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "Chat",
                subtitle: model.activeEpisodeID.isEmpty ? "New chat" : "Conversation open",
                actionTitle: model.isReflecting ? "Reflecting" : "Reflect",
                actionSymbol: "brain.head.profile"
            ) {
                Task { await model.runReflect(trigger: "wake") }
            }

            HStack(alignment: .top, spacing: 14) {
                ThreadRailPanel()
                    .frame(width: 286)
                    .frame(maxHeight: .infinity)
                WakeComposerPanel()
                    .frame(maxHeight: .infinity)
            }
            .frame(maxHeight: .infinity)
        }
        .frame(maxHeight: .infinity, alignment: .top)
    }
}

struct ThreadRailPanel: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var deleteCandidate: EpisodeThread?

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    SectionLabel(title: "Threads", subtitle: "Conversation history")
                    Spacer()
                    Button {
                        model.startNewChat()
                    } label: {
                        Image(systemName: "plus")
                    }
                    .buttonStyle(.borderless)
                    .help("New Chat")
                }

                VStack(spacing: 0) {
                    Button {
                        model.startNewChat()
                    } label: {
                        ThreadRow(
                            title: "New Chat",
                            subtitle: model.activeEpisodeID.isEmpty ? "Ready" : "Start another conversation",
                            selected: model.activeEpisodeID.isEmpty
                        )
                    }
                    .buttonStyle(.plain)

                    ForEach(chatThreads.prefix(7)) { thread in
                        HStack(spacing: 4) {
                            Button {
                                model.openEpisodeThread(thread)
                            } label: {
                                ThreadRow(
                                    title: readableTitle(thread.title),
                                    subtitle: thread.subtitle.isEmpty ? "Conversation" : thread.subtitle,
                                    selected: thread.id == model.activeEpisodeID
                                )
                            }
                            .buttonStyle(.plain)
                            .contextMenu {
                                Button("Delete Conversation", role: .destructive) {
                                    deleteCandidate = thread
                                }
                            }

                            Button {
                                deleteCandidate = thread
                            } label: {
                                Image(systemName: "trash")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(ElephantTheme.faint)
                                    .frame(width: 28, height: 28)
                            }
                            .buttonStyle(PressablePlainButtonStyle())
                            .help("Delete Conversation")
                            .accessibilityLabel("Delete \(readableTitle(thread.title))")
                        }
                    }

                    if chatThreads.isEmpty {
                        EmptyLine(symbol: "bubble.left", text: "No saved chats yet.")
                    }
                }

                Spacer(minLength: 0)

                Divider()
                TodaySignalRow(value: "\(model.snapshot.waitingQuestions)", label: "questions", symbol: "questionmark.bubble", tint: ElephantTheme.orange)
                TodaySignalRow(value: "\(model.snapshot.semanticEntries)", label: "evidence", symbol: "doc.text.magnifyingglass", tint: ElephantTheme.green)
            }
            .frame(minHeight: 620, maxHeight: .infinity, alignment: .top)
        }
        .confirmationDialog(
            "Delete \(readableTitle(deleteCandidate?.title ?? "conversation"))?",
            isPresented: Binding(
                get: { deleteCandidate != nil },
                set: { if !$0 { deleteCandidate = nil } }
            )
        ) {
            Button("Delete Conversation", role: .destructive) {
                if let deleteCandidate {
                    model.deleteEpisodeThread(deleteCandidate)
                }
                deleteCandidate = nil
            }
        } message: {
            Text("This removes the conversation from the desktop history. Personal Model facts and evidence are not deleted.")
        }
    }

    private var chatThreads: [EpisodeThread] {
        model.snapshot.episodeThreads.filter { thread in
            let title = thread.title.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            return !model.hiddenEpisodeIDs.contains(thread.id)
                && !title.hasPrefix("trigger:")
                && !title.hasPrefix("job:")
                && !title.contains("reflect run")
        }
    }

    private func readableTitle(_ title: String) -> String {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let meaningfulScalars = trimmed.unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) }
        return meaningfulScalars.count < 2 ? "Untitled chat" : trimmed
    }
}

struct ThreadRow: View {
    var title: String
    var subtitle: String
    var selected: Bool

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: selected ? "bubble.left.and.bubble.right.fill" : "bubble.left")
                .foregroundStyle(selected ? ElephantTheme.accent : ElephantTheme.muted)
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(selected ? ElephantTheme.accent : ElephantTheme.ink)
                    .lineLimit(1)
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 10)
        .background(selected ? ElephantTheme.accent.opacity(0.10) : Color.clear, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .contentShape(Rectangle())
    }
}

struct WakeComposerPanel: View {
    @EnvironmentObject private var model: ElephantAppModel
    @StateObject private var speech = SpeechInputController()
    @FocusState private var focused: Bool

    var body: some View {
        NativePanel {
            VStack(spacing: 0) {
                HStack {
                    Text(model.activeEpisodeID.isEmpty ? "New conversation" : "Conversation")
                        .font(.headline)
                        .foregroundStyle(ElephantTheme.ink)
                    Spacer()
                    Pill(text: providerLabel, symbol: "cpu", tint: providerTint)
                }
                .padding(.bottom, 12)

                ScrollViewReader { proxy in
                    Group {
                        if visibleMessages.isEmpty {
                            ChatEmptyState()
                                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
                                .padding(.horizontal, 28)
                        } else {
                            ScrollView {
                                VStack(alignment: .leading, spacing: 4) {
                                    ForEach(visibleMessages) { message in
                                        MessageBubble(message: message)
                                            .id(message.id)
                                    }
                                }
                                .padding(.vertical, 8)
                                .padding(.horizontal, 24)
                                .frame(maxWidth: .infinity, alignment: .top)
                            }
                        }
                    }
                    .frame(minHeight: 320, maxHeight: .infinity)
                    .onChange(of: model.chatScrollRevision) { _ in
                        if let last = visibleMessages.last {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }

                Divider()

                VStack(alignment: .leading, spacing: 5) {
                    HStack(alignment: .center, spacing: 8) {
                        Button {
                            speech.toggle(startingWith: model.wakeDraft) { text in
                                model.wakeDraft = text
                            }
                        } label: {
                            Image(systemName: speech.isRecording ? "waveform.circle.fill" : "mic")
                                .font(.system(size: 16, weight: .semibold))
                                .frame(width: 32, height: 32)
                                .foregroundStyle(speech.isRecording ? ElephantTheme.accent : ElephantTheme.muted)
                        }
                        .buttonStyle(PressablePlainButtonStyle())
                        .help(speech.isRecording ? "Stop voice input" : "Voice input")

                        TextField("Type a message...", text: $model.wakeDraft, axis: .vertical)
                            .textFieldStyle(.plain)
                            .font(.body)
                            .lineLimit(1...4)
                            .padding(.vertical, 6)
                            .frame(minHeight: 30)
                            .focused($focused)
                            .onSubmit {
                                speech.stop()
                                Task { await model.sendWakeMessage() }
                            }

                        Button {
                            speech.stop()
                            Task { await model.sendWakeMessage() }
                        } label: {
                            Image(systemName: model.isWakeRunning ? "hourglass" : "arrow.up")
                                .font(.system(size: 17, weight: .bold))
                                .frame(width: 34, height: 32)
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.regular)
                        .tint(ElephantTheme.accent)
                        .disabled(model.isWakeRunning || model.wakeDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        .help("Send")
                    }

                    if speech.isRecording || !speech.statusText.isEmpty {
                        Label(speech.statusText, systemImage: speech.isRecording ? "waveform" : "mic")
                            .font(.caption)
                            .foregroundStyle(speech.isRecording ? ElephantTheme.accent : ElephantTheme.muted)
                            .padding(.leading, 42)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 7)
                .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .stroke(focused ? ElephantTheme.accent : ElephantTheme.line, lineWidth: focused ? 2 : 1)
                )
                .padding(.top, 12)
            }
            .frame(minHeight: 620, maxHeight: .infinity)
        }
        .onAppear { focused = true }
        .onChange(of: model.composerFocusToken) { _ in
            focused = true
        }
        .onDisappear {
            speech.stop()
        }
    }

    private var providerTint: Color {
        let value = model.snapshot.providerStatus.lowercased()
        return value == "unknown" || value.contains("setup") || value.contains("missing")
            ? ElephantTheme.orange
            : ElephantTheme.green
    }

    private var providerLabel: String {
        if !model.snapshot.providerModelID.isEmpty {
            return model.snapshot.providerModelID
        }
        return model.snapshot.providerStatus == "unknown" ? "provider setup" : model.snapshot.providerStatus
    }

    private var visibleMessages: [ChatMessage] {
        model.messages.filter { $0.role != .system }
    }
}

struct ChatEmptyState: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(spacing: 18) {
            VStack(spacing: 8) {
                BrandMark(size: 140, framed: false)
                    .accessibilityHidden(true)
                    .padding(.bottom, 0)
                Text("Ask Elephant")
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Text("Short, specific chats become reviewable memory, questions, and evidence.")
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.muted)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 520)
            }
            HStack(spacing: 10) {
                QuickPromptButton(title: "Capture", symbol: "sparkles") {
                    model.wakeDraft = "Remember this:"
                    model.focusComposer()
                }
                QuickPromptButton(title: "Think", symbol: "bubble.left.and.text.bubble.right") {
                    model.wakeDraft = "Help me think through"
                    model.focusComposer()
                }
                QuickPromptButton(title: "Review", symbol: "checklist") {
                    model.wakeDraft = "What should I review from today?"
                    model.focusComposer()
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .center)
    }
}

struct QuickPromptButton: View {
    var title: String
    var symbol: String
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .font(.callout.weight(.semibold))
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .frame(minWidth: 108)
        }
        .buttonStyle(PressablePlainButtonStyle())
        .background(Color(nsColor: .controlBackgroundColor), in: Capsule())
        .overlay(Capsule().stroke(ElephantTheme.line, lineWidth: 1))
    }
}

private struct MarkdownBlock: Identifiable {
    enum Kind {
        case paragraph
        case heading
        case bulletList
        case numberedList
        case code
    }

    var id: Int
    var kind: Kind
    var text: String
    var items: [String] = []
}

struct MarkdownBody: View {
    var text: String
    var font: Font = .body
    var color: Color = ElephantTheme.ink

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            ForEach(blocks) { block in
                switch block.kind {
                case .heading:
                    InlineMarkdownText(text: block.text, font: .headline, color: color)
                case .paragraph:
                    InlineMarkdownText(text: block.text, font: font, color: color)
                case .bulletList:
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(block.items, id: \.self) { item in
                            HStack(alignment: .top, spacing: 6) {
                                Text("•")
                                    .font(font)
                                    .foregroundStyle(color.opacity(0.72))
                                InlineMarkdownText(text: item, font: font, color: color)
                            }
                        }
                    }
                case .numberedList:
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(Array(block.items.enumerated()), id: \.offset) { index, item in
                            HStack(alignment: .top, spacing: 6) {
                                Text("\(index + 1).")
                                    .font(font)
                                    .foregroundStyle(color.opacity(0.72))
                                InlineMarkdownText(text: item, font: font, color: color)
                            }
                        }
                    }
                case .code:
                    Text(block.text)
                        .font(.system(.callout, design: .monospaced))
                        .foregroundStyle(color)
                        .textSelection(.enabled)
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))
                }
            }
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    private var blocks: [MarkdownBlock] {
        var result: [MarkdownBlock] = []
        var paragraph: [String] = []
        var bullets: [String] = []
        var numbers: [String] = []
        var code: [String] = []
        var inCode = false

        func flushParagraph() {
            guard !paragraph.isEmpty else { return }
            result.append(MarkdownBlock(id: result.count, kind: .paragraph, text: paragraph.joined(separator: "\n")))
            paragraph.removeAll()
        }

        func flushBullets() {
            guard !bullets.isEmpty else { return }
            result.append(MarkdownBlock(id: result.count, kind: .bulletList, text: "", items: bullets))
            bullets.removeAll()
        }

        func flushNumbers() {
            guard !numbers.isEmpty else { return }
            result.append(MarkdownBlock(id: result.count, kind: .numberedList, text: "", items: numbers))
            numbers.removeAll()
        }

        func flushCode() {
            guard !code.isEmpty else { return }
            result.append(MarkdownBlock(id: result.count, kind: .code, text: code.joined(separator: "\n")))
            code.removeAll()
        }

        for rawLine in text.components(separatedBy: .newlines) {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("```") {
                if inCode {
                    inCode = false
                    flushCode()
                } else {
                    flushParagraph()
                    flushBullets()
                    flushNumbers()
                    inCode = true
                }
                continue
            }
            if inCode {
                code.append(rawLine)
                continue
            }
            if line.isEmpty {
                flushParagraph()
                flushBullets()
                flushNumbers()
                continue
            }
            if line.hasPrefix("### ") || line.hasPrefix("## ") || line.hasPrefix("# ") {
                flushParagraph()
                flushBullets()
                flushNumbers()
                result.append(MarkdownBlock(id: result.count, kind: .heading, text: line.replacingOccurrences(of: #"^#{1,3}\s+"#, with: "", options: .regularExpression)))
                continue
            }
            if line.hasPrefix("- ") || line.hasPrefix("* ") {
                flushParagraph()
                flushNumbers()
                bullets.append(String(line.dropFirst(2)))
                continue
            }
            if let range = line.range(of: #"^\d+\.\s+"#, options: .regularExpression) {
                flushParagraph()
                flushBullets()
                numbers.append(String(line[range.upperBound...]))
                continue
            }
            flushBullets()
            flushNumbers()
            paragraph.append(rawLine)
        }

        flushParagraph()
        flushBullets()
        flushNumbers()
        flushCode()
        return result.isEmpty ? [MarkdownBlock(id: 0, kind: .paragraph, text: text)] : result
    }
}

struct InlineMarkdownText: View {
    var text: String
    var font: Font
    var color: Color

    var body: some View {
        if let attributed = try? AttributedString(markdown: text) {
            Text(attributed)
                .font(font)
                .foregroundStyle(color)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        } else {
            Text(text)
                .font(font)
                .foregroundStyle(color)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
    }
}

struct MessageBubble: View {
    var message: ChatMessage

    var body: some View {
        Group {
            if message.role == .user {
                HStack(alignment: .top, spacing: 0) {
                    Spacer(minLength: 80)
                    bubbleContent
                }
            } else {
                HStack(alignment: .top, spacing: 0) {
                    bubbleContent
                    Spacer(minLength: 80)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: message.role == .user ? .trailing : .leading)
    }

    private var bubbleContent: some View {
        Group {
            if message.role == .user {
                bubbleCore
            } else {
                bubbleCore
                    .frame(maxWidth: 760, alignment: .leading)
            }
        }
    }

    private var bubbleCore: some View {
        VStack(alignment: .leading, spacing: 3) {
            if !message.text.isEmpty {
                MarkdownBody(text: message.text, font: message.role == .system ? .callout : .body, color: textColor)
                    .transaction { transaction in
                        transaction.animation = nil
                    }
            }
            if !message.toolEvents.isEmpty {
                ToolUseStack(events: message.toolEvents, isLive: message.isStreaming)
                    .padding(.top, message.text.isEmpty ? 0 : 1)
            } else if message.isStreaming && message.text.isEmpty {
                ToolTraceWaitingView()
            }
        }
        .padding(.horizontal, message.role == .user ? 16 : 0)
        .padding(.vertical, message.role == .user ? 11 : 0)
        .background(background, in: RoundedRectangle(cornerRadius: message.role == .user ? 18 : 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: message.role == .user ? 18 : 14, style: .continuous)
                .stroke(message.role == .user ? ElephantTheme.line.opacity(0.65) : Color.clear, lineWidth: 1)
        )
    }

    private var background: Color {
        switch message.role {
        case .user: return ElephantTheme.accent.opacity(0.08)
        case .assistant: return Color.clear
        case .system: return Color(nsColor: .controlBackgroundColor)
        }
    }

    private var textColor: Color {
        ElephantTheme.ink
    }
}

struct ToolUseStack: View {
    var events: [ToolUseEvent]
    var isLive = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "wrench.and.screwdriver")
                    .font(.caption.weight(.semibold))
                Text(events.count == 1 ? "Tool" : "\(events.count) tools")
                    .font(.caption.weight(.semibold))
                if isLive && hasRunningEvent {
                    StatusDot(tint: ElephantTheme.accent)
                    Text("live")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(ElephantTheme.accent)
                }
                Spacer(minLength: 0)
            }
            .foregroundStyle(ElephantTheme.muted)

            ForEach(events.suffix(6)) { event in
                ToolUseEventRow(event: event)
            }
        }
        .padding(8)
        .background(Color(nsColor: .textBackgroundColor).opacity(0.76), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(ElephantTheme.line, lineWidth: 1)
        )
    }

    private var hasRunningEvent: Bool {
        events.contains { event in
            let status = event.status.lowercased()
            return status.contains("running")
                || status.contains("preparing")
                || status.contains("approved")
                || status.contains("requested")
                || status.contains("classified")
        }
    }
}

struct ToolTraceWaitingView: View {
    var body: some View {
        ElephantThinkingMark()
            .padding(.horizontal, 2)
            .padding(.vertical, 2)
            .fixedSize()
            .accessibilityLabel("Assistant is thinking")
    }
}

struct ElephantThinkingMark: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 24.0, paused: reduceMotion)) { timeline in
            let phase = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
            let wave = reduceMotion ? 0.5 : (sin(phase * 4.2) + 1.0) / 2.0
            let breath = reduceMotion ? 1.0 : 0.58 + wave * 0.92
            let opacity = reduceMotion ? 0.72 : 0.28 + wave * 0.72

            Circle()
                .fill(Color.black)
                .frame(width: 8, height: 8)
                .scaleEffect(breath)
                .opacity(opacity)
                .frame(width: 24, height: 24)
        }
    }
}

struct ToolUseEventRow: View {
    var event: ToolUseEvent

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                StatusDot(tint: statusTint)
                Text(event.name)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                    .lineLimit(1)
                Spacer(minLength: 0)
                Text(event.status)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(1)
            }

            if !event.arguments.isEmpty {
                Text(event.arguments)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            if !event.result.isEmpty {
                Text(event.result)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.faint)
                    .lineLimit(2)
            }
        }
    }

    private var statusTint: Color {
        let value = event.status.lowercased()
        if value.contains("fail") || value.contains("error") {
            return ElephantTheme.orange
        }
        if value.contains("plan") || value.contains("start") {
            return ElephantTheme.accent
        }
        return ElephantTheme.green
    }
}

struct YouView: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var selectedLens = "identity"

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "You",
                subtitle: "Personal Model facts and questions stay reviewable.",
                actionTitle: "Reflect",
                actionSymbol: "brain.head.profile"
            ) {
                Task { await model.runReflect(trigger: "manual") }
            }

            Picker("Lens", selection: $selectedLens) {
                Text("Identity").tag("identity")
                Text("World").tag("world")
                Text("Pulse").tag("pulse")
                Text("Journey").tag("journey")
            }
            .pickerStyle(.segmented)
            .frame(width: 430)

            VStack(spacing: 14) {
                PersonalModelSummaryPanel()
                PersonalModelMapPanel()
                QuestionFieldPanel()
                LensPartitionGrid(selectedLens: $selectedLens)
                LensFactsPager(lens: selectedLens)
            }
        }
    }
}

struct PersonalModelSummaryPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            HStack(alignment: .center, spacing: 22) {
                MemoryOrbitView()
                    .frame(width: 104, height: 104)

                VStack(alignment: .leading, spacing: 8) {
                    Text("Personal Model")
                        .font(.title2.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                    Text("Facts are separated from open questions so memory stays reviewable.")
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.muted)
                }

                Spacer(minLength: 0)

                HStack(spacing: 12) {
                    CompactStat(value: "\(model.snapshot.lensCoverage["identity"] ?? 0)", label: "Identity")
                    CompactStat(value: "\(model.snapshot.lensCoverage["world"] ?? 0)", label: "World")
                    CompactStat(value: "\(model.snapshot.lensCoverage["pulse"] ?? 0)", label: "Pulse")
                    CompactStat(value: "\(model.snapshot.lensCoverage["journey"] ?? 0)", label: "Journey")
                }
            }
        }
    }
}

struct PersonalModelMapPanel: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var selectedLens: String?

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                SectionLabel(
                    title: "Personal Model Map",
                    subtitle: "Facts are grouped by lens and dotted topic path."
                )
                PersonalModelMapCanvas(userName: model.userDisplayName, snapshot: model.snapshot, selectedLens: $selectedLens)
                    .frame(height: 700)
                if let selectedLens {
                    LensDetailStrip(lens: selectedLens)
                }
            }
        }
    }
}

struct QuestionFieldPanel: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var filter = "open"
    @State private var page = 0
    private let pageSize = 4

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    SectionLabel(
                        title: "Question Field",
                        subtitle: "Open loops stay separate from facts until you answer, dismiss, or Reflect learns from them."
                    )
                    Spacer()
                    Text("\(openCount) open")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.orange)
                }

                HStack(spacing: 8) {
                    ForEach(filters, id: \.id) { item in
                        Button {
                            filter = item.id
                            page = 0
                        } label: {
                            HStack(spacing: 6) {
                                Text(item.title)
                                Text("\(item.count)")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(filter == item.id ? .white.opacity(0.86) : ElephantTheme.muted)
                            }
                            .padding(.horizontal, 11)
                            .padding(.vertical, 6)
                            .background(filter == item.id ? ElephantTheme.accent : Color(nsColor: .controlBackgroundColor), in: Capsule())
                            .foregroundStyle(filter == item.id ? .white : ElephantTheme.ink)
                        }
                        .buttonStyle(.plain)
                    }
                    Spacer(minLength: 0)
                    if pageCount > 1 {
                        PageStepper(page: currentPage, pageCount: pageCount) { direction in
                            page = min(max(0, currentPage + direction), pageCount - 1)
                        }
                    }
                }

                if visibleQuestions.isEmpty {
                    EmptyLine(symbol: "questionmark.bubble", text: "No Personal Model questions in this state.")
                } else {
                    VStack(spacing: 0) {
                        ForEach(pagedQuestions) { question in
                            QuestionLedgerRow(question: question)
                            if question.id != pagedQuestions.last?.id {
                                Divider()
                            }
                        }
                    }
                    .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))
                }
            }
        }
        .onChange(of: model.snapshot.questionItems) { _ in
            page = min(page, pageCount - 1)
        }
    }

    private var filters: [(id: String, title: String, count: Int)] {
        [
            ("open", "Open", openCount),
            ("ready", "Ready", model.snapshot.waitingQuestions),
            ("asked", "Asked", model.snapshot.askedQuestions),
            ("answered", "Learned", model.snapshot.answeredQuestions),
            ("dismissed", "Dismissed", model.snapshot.dismissedQuestions)
        ]
    }

    private var openCount: Int {
        model.snapshot.waitingQuestions + model.snapshot.askedQuestions
    }

    private var visibleQuestions: [PersonalModelQuestionItem] {
        switch filter {
        case "open":
            return model.snapshot.questionItems.filter { $0.status == "ready" || $0.status == "asked" }
        case "ready", "asked", "answered", "dismissed":
            return model.snapshot.questionItems.filter { $0.status == filter }
        default:
            return model.snapshot.questionItems
        }
    }

    private var pageCount: Int {
        max(1, (visibleQuestions.count + pageSize - 1) / pageSize)
    }

    private var currentPage: Int {
        min(max(0, page), pageCount - 1)
    }

    private var pagedQuestions: [PersonalModelQuestionItem] {
        Array(visibleQuestions.dropFirst(currentPage * pageSize).prefix(pageSize))
    }
}

struct PageStepper: View {
    var page: Int
    var pageCount: Int
    var change: (Int) -> Void

    var body: some View {
        HStack(spacing: 7) {
            Button {
                change(-1)
            } label: {
                Image(systemName: "chevron.left")
            }
            .disabled(page == 0)
            Button {
                change(1)
            } label: {
                Image(systemName: "chevron.right")
            }
            .disabled(page >= pageCount - 1)
            Text("\(page + 1)/\(pageCount)")
                .font(.caption.weight(.semibold))
                .foregroundStyle(ElephantTheme.muted)
                .frame(width: 42, alignment: .trailing)
        }
        .buttonStyle(.borderless)
        .controlSize(.small)
    }
}

struct QuestionLedgerRow: View {
    @EnvironmentObject private var model: ElephantAppModel
    var question: PersonalModelQuestionItem
    @State private var answerDraft = ""

    var body: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    Pill(text: lensText, symbol: "circle.grid.cross", tint: tint)
                    Pill(text: question.source, symbol: "link", tint: ElephantTheme.faint)
                    Pill(text: question.sensitivity, symbol: "lock", tint: ElephantTheme.faint)
                    if question.askedCount > 0 {
                        Pill(text: "\(question.askedCount) asked", symbol: "clock", tint: ElephantTheme.orange)
                    }
                }

                if !question.lastAskedSurface.isEmpty || !question.lastAskedAt.isEmpty {
                    Text([question.lastAskedSurface, question.lastAskedAt].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                }

                if !question.resultingFacts.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Learned facts")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(ElephantTheme.muted)
                        ForEach(question.resultingFacts.prefix(3)) { fact in
                            Text(fact.text)
                                .font(.callout)
                                .foregroundStyle(ElephantTheme.ink)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }

                if question.canAct {
                    HStack(spacing: 8) {
                        Button("Answer in Chat") {
                            model.draftAnswerForQuestion(question)
                        }
                        Button("Surface sooner") {
                            Task { await model.surfaceQuestionSooner(question) }
                        }
                        Button("Dismiss") {
                            Task { await model.dismissQuestion(question) }
                        }
                    }
                    .controlSize(.small)

                    HStack(alignment: .bottom, spacing: 8) {
                        TextField("Answer this question here...", text: $answerDraft, axis: .vertical)
                            .textFieldStyle(.roundedBorder)
                            .lineLimit(1...3)
                        Button("Save Answer") {
                            let draft = answerDraft
                            answerDraft = ""
                            Task { await model.answerQuestion(question, content: draft) }
                        }
                        .disabled(answerDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                    .controlSize(.small)
                }
            }
            .padding(.top, 10)
        } label: {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "questionmark.bubble")
                    .foregroundStyle(tint)
                    .frame(width: 24)
                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 8) {
                        Text(question.statusTitle)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(tint)
                        if question.priority > 0 {
                            Text("priority \(String(format: "%.2f", question.priority))")
                                .font(.caption)
                                .foregroundStyle(ElephantTheme.muted)
                        }
                    }
                    Text(question.text)
                        .font(.callout.weight(.medium))
                        .foregroundStyle(ElephantTheme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .padding(.vertical, 10)
        }
        .padding(.horizontal, 12)
    }

    private var lensText: String {
        if question.subLens.isEmpty {
            return question.lens
        }
        return "\(question.lens) · \(question.subLens)"
    }

    private var tint: Color {
        switch question.status {
        case "ready": return ElephantTheme.accent
        case "asked": return ElephantTheme.orange
        case "answered": return ElephantTheme.green
        case "dismissed": return ElephantTheme.faint
        default: return ElephantTheme.muted
        }
    }
}

struct PersonalModelMapCanvas: View {
    var userName: String
    var snapshot: DashboardSnapshot
    @Binding var selectedLens: String?

    var body: some View {
        GeometryReader { proxy in
            let layout = buildLayout(in: proxy.size)

            ZStack {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(
                        RadialGradient(
                            colors: [ElephantTheme.green.opacity(0.08), ElephantTheme.accent.opacity(0.03), Color.clear],
                            center: .center,
                            startRadius: 28,
                            endRadius: max(proxy.size.width, proxy.size.height) * 0.74
                        )
                    )

                Canvas { context, _ in
                    drawBackgroundRings(in: &context, size: proxy.size)
                    for edge in layout.edges {
                        draw(edge: edge, in: &context)
                    }
                }

                ForEach(layout.nodes) { node in
                    Button {
                        selectedLens = node.targetLens
                    } label: {
                        MindMapNodeView(node: node, selected: selectedLens == node.targetLens)
                    }
                    .buttonStyle(.plain)
                    .position(node.position)
                }
            }
        }
        .accessibilityLabel("Personal Model map")
    }

    private var centerValue: String {
        let trimmed = userName.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty || trimmed == "You" ? "Personal Model" : trimmed
    }

    private func buildLayout(in size: CGSize) -> MindMapLayout {
        let center = CGPoint(x: size.width * 0.50, y: size.height * 0.50)
        var nodes: [MindMapLayoutNode] = [
            MindMapLayoutNode(
                id: "center",
                title: "Personal Model",
                subtitle: "",
                symbol: "person.crop.circle",
                tint: ElephantTheme.ink,
                kind: .center,
                targetLens: "overview",
                position: center,
                width: 150,
                height: 48
            )
        ]
        var edges: [MindMapEdge] = []

        for spec in branchSpecs {
            let facts = facts(for: spec.id)
            let categories = categories(for: facts, lensID: spec.id)
            let lensPoint = CGPoint(x: size.width * spec.lensX, y: size.height * spec.lensY)
            let lensCount = facts.isEmpty ? (snapshot.lensCoverage[spec.id] ?? 0) : facts.count
            let lensNode = MindMapLayoutNode(
                id: "lens-\(spec.id)",
                title: spec.title,
                subtitle: "\(lensCount)",
                symbol: spec.symbol,
                tint: spec.tint,
                kind: .lens,
                targetLens: spec.id,
                position: lensPoint,
                width: 104,
                height: 34
            )
            nodes.append(lensNode)
            edges.append(MindMapEdge(from: center, to: lensPoint, tint: spec.tint, dashed: true))

            let visibleCategories = categories.isEmpty
                ? [MindMapCategory(id: "\(spec.id)-empty", title: "no_facts", count: 0, leaves: [])]
                : Array(categories.prefix(5))
            for categoryLayout in categoryLayouts(for: visibleCategories, spec: spec, size: size) {
                let category = categoryLayout.category
                let categoryY = categoryLayout.categoryY
                let categoryPoint = CGPoint(x: size.width * spec.categoryX, y: categoryY)
                nodes.append(
                    MindMapLayoutNode(
                        id: "category-\(spec.id)-\(category.id)",
                        title: category.title,
                        subtitle: category.count > 0 ? "\(category.count)" : "",
                        symbol: nil,
                        tint: spec.tint,
                        kind: .category,
                        targetLens: spec.id,
                        position: categoryPoint,
                        width: 92,
                        height: 26
                    )
                )
                edges.append(MindMapEdge(from: lensPoint, to: categoryPoint, tint: spec.tint, dashed: false))

                for (leafIndex, leaf) in categoryLayout.leaves.enumerated() {
                    let leafY = categoryLayout.leafYValues[leafIndex]
                    let leafPoint = CGPoint(x: size.width * spec.leafX, y: leafY)
                    nodes.append(
                        MindMapLayoutNode(
                            id: "leaf-\(spec.id)-\(category.id)-\(leaf.id)",
                            title: leaf.title,
                            subtitle: leaf.count > 1 ? "\(leaf.count)" : "",
                            symbol: nil,
                            tint: spec.tint,
                            kind: .leaf,
                            targetLens: spec.id,
                            position: leafPoint,
                            width: 122,
                            height: 24
                        )
                    )
                    edges.append(MindMapEdge(from: categoryPoint, to: leafPoint, tint: spec.tint, dashed: false))
                }
            }
        }

        return MindMapLayout(nodes: nodes, edges: edges)
    }

    private var branchSpecs: [MindMapBranchSpec] {
        [
            MindMapBranchSpec(
                id: "identity",
                title: "Identity",
                symbol: "person.crop.circle",
                tint: ElephantTheme.accent,
                lensX: 0.65,
                lensY: 0.28,
                categoryX: 0.78,
                leafX: 0.91,
                band: 0.05...0.46
            ),
            MindMapBranchSpec(
                id: "world",
                title: "World",
                symbol: "globe",
                tint: ElephantTheme.green,
                lensX: 0.35,
                lensY: 0.28,
                categoryX: 0.22,
                leafX: 0.09,
                band: 0.05...0.46
            ),
            MindMapBranchSpec(
                id: "pulse",
                title: "Pulse",
                symbol: "waveform.path.ecg",
                tint: ElephantTheme.orange,
                lensX: 0.65,
                lensY: 0.72,
                categoryX: 0.78,
                leafX: 0.91,
                band: 0.54...0.95
            ),
            MindMapBranchSpec(
                id: "journey",
                title: "Journey",
                symbol: "map",
                tint: ElephantTheme.accent.opacity(0.82),
                lensX: 0.35,
                lensY: 0.72,
                categoryX: 0.22,
                leafX: 0.09,
                band: 0.54...0.95
            )
        ]
    }

    private func facts(for lensID: String) -> [PersonalModelFact] {
        snapshot.personalModelFacts.filter { fact in
            fact.status.lowercased() != "deleted" && normalizedLens(for: fact) == lensID
        }
    }

    private func categories(for facts: [PersonalModelFact], lensID: String) -> [MindMapCategory] {
        var buckets: [String: [String: Int]] = [:]
        for fact in facts {
            let path = topicPath(for: fact, lensID: lensID)
            let category = path.first ?? "facts"
            let leaf = path.dropFirst().first ?? fallbackLeaf(for: fact)
            buckets[category, default: [:]][leaf, default: 0] += 1
        }
        return buckets.map { key, value in
            let leaves = value.map { leaf, count in
                MindMapLeaf(id: leaf, title: leaf, count: count)
            }
            .sorted { lhs, rhs in
                if lhs.count == rhs.count { return lhs.title < rhs.title }
                return lhs.count > rhs.count
            }
            let count = leaves.reduce(0) { $0 + $1.count }
            return MindMapCategory(id: key, title: key, count: count, leaves: leaves)
        }
        .sorted { lhs, rhs in
            if lhs.count == rhs.count { return lhs.title < rhs.title }
            return lhs.count > rhs.count
        }
    }

    private func normalizedLens(for fact: PersonalModelFact) -> String {
        let raw = "\(fact.lens) \(fact.topic)".lowercased()
        if raw.contains("identity") { return "identity" }
        if raw.contains("world") { return "world" }
        if raw.contains("pulse") { return "pulse" }
        if raw.contains("journey") { return "journey" }
        return "identity"
    }

    private func topicPath(for fact: PersonalModelFact, lensID: String) -> [String] {
        let raw = fact.topic.isEmpty ? fact.lens : fact.topic
        var parts = raw
            .lowercased()
            .split { character in character == "." || character == "/" || character == ":" }
            .map { cleanTopicLabel(String($0)) }
            .filter { !$0.isEmpty }
        while parts.first == lensID || parts.first == "personal_model" {
            parts.removeFirst()
        }
        if parts.isEmpty {
            return ["facts", fallbackLeaf(for: fact)]
        }
        return Array(parts.prefix(3))
    }

    private func fallbackLeaf(for fact: PersonalModelFact) -> String {
        let text = fact.text
            .split { $0.isWhitespace || $0 == "," || $0 == "，" || $0 == "。" || $0 == "." }
            .prefix(2)
            .joined(separator: "_")
        return cleanTopicLabel(text.isEmpty ? "fact" : text)
    }

    private func cleanTopicLabel(_ value: String) -> String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count > 22 else { return trimmed }
        let end = trimmed.index(trimmed.startIndex, offsetBy: 22)
        return String(trimmed[..<end])
    }

    private func categoryLayouts(
        for categories: [MindMapCategory],
        spec: MindMapBranchSpec,
        size: CGSize
    ) -> [(category: MindMapCategory, leaves: [MindMapLeaf], categoryY: CGFloat, leafYValues: [CGFloat])] {
        let groups = categories.map { category in
            (category: category, leaves: Array(category.leaves.prefix(2)))
        }
        let rowCounts = groups.map { max($0.leaves.count, 1) }
        let totalRows = max(rowCounts.reduce(0, +), 1)
        let minY = size.height * spec.band.lowerBound
        let maxY = size.height * spec.band.upperBound
        let step = totalRows > 1 ? (maxY - minY) / CGFloat(totalRows - 1) : 0

        var cursor = 0
        return groups.map { group in
            let rowCount = max(group.leaves.count, 1)
            let values: [CGFloat]
            if totalRows == 1 {
                values = [size.height * (spec.band.lowerBound + spec.band.upperBound) / 2]
            } else {
                values = (0..<rowCount).map { minY + CGFloat(cursor + $0) * step }
            }
            cursor += rowCount
            let categoryY = values.reduce(0, +) / CGFloat(values.count)
            return (group.category, group.leaves, categoryY, group.leaves.isEmpty ? [] : values)
        }
    }

    private func drawBackgroundRings(in context: inout GraphicsContext, size: CGSize) {
        let center = CGPoint(x: size.width * 0.50, y: size.height * 0.50)
        for ring in [0.30, 0.44, 0.58, 0.72] {
            let width = size.width * CGFloat(ring)
            let height = size.height * CGFloat(ring * 0.78)
            let rect = CGRect(x: center.x - width / 2, y: center.y - height / 2, width: width, height: height)
            context.stroke(Path(ellipseIn: rect), with: .color(ElephantTheme.line.opacity(0.14)), lineWidth: 0.8)
        }
        context.fill(
            Path(ellipseIn: CGRect(x: center.x - 64, y: center.y - 64, width: 128, height: 128)),
            with: .color(ElephantTheme.green.opacity(0.035))
        )
    }

    private func draw(edge: MindMapEdge, in context: inout GraphicsContext) {
        var path = Path()
        path.move(to: edge.from)
        let dx = edge.to.x - edge.from.x
        path.addCurve(
            to: edge.to,
            control1: CGPoint(x: edge.from.x + dx * 0.42, y: edge.from.y),
            control2: CGPoint(x: edge.from.x + dx * 0.58, y: edge.to.y)
        )
        context.stroke(
            path,
            with: .color(edge.tint.opacity(edge.dashed ? 0.42 : 0.28)),
            style: StrokeStyle(lineWidth: edge.dashed ? 1.1 : 0.9, lineCap: .round, dash: edge.dashed ? [4, 5] : [])
        )
    }

    private func clamp(_ value: CGFloat, min: CGFloat, max: CGFloat) -> CGFloat {
        Swift.min(Swift.max(value, min), max)
    }
}

private struct MindMapBranchSpec {
    var id: String
    var title: String
    var symbol: String
    var tint: Color
    var lensX: CGFloat
    var lensY: CGFloat
    var categoryX: CGFloat
    var leafX: CGFloat
    var band: ClosedRange<CGFloat>
}

private struct MindMapLeaf: Identifiable {
    var id: String
    var title: String
    var count: Int
}

private struct MindMapCategory: Identifiable {
    var id: String
    var title: String
    var count: Int
    var leaves: [MindMapLeaf]
}

private enum MindMapNodeKind {
    case center
    case lens
    case category
    case leaf
}

private struct MindMapLayoutNode: Identifiable {
    var id: String
    var title: String
    var subtitle: String
    var symbol: String?
    var tint: Color
    var kind: MindMapNodeKind
    var targetLens: String
    var position: CGPoint
    var width: CGFloat
    var height: CGFloat
}

private struct MindMapEdge {
    var from: CGPoint
    var to: CGPoint
    var tint: Color
    var dashed: Bool
}

private struct MindMapLayout {
    var nodes: [MindMapLayoutNode]
    var edges: [MindMapEdge]
}

private struct MindMapNodeView: View {
    var node: MindMapLayoutNode
    var selected: Bool

    var body: some View {
        HStack(spacing: node.kind == .leaf ? 4 : 7) {
            if let symbol = node.symbol {
                Image(systemName: symbol)
                    .font(.system(size: node.kind == .center ? 15 : 13, weight: .semibold))
                    .foregroundStyle(node.kind == .center ? ElephantTheme.ink : node.tint)
            }
            Text(node.title)
                .font(titleFont)
                .foregroundStyle(ElephantTheme.ink)
                .lineLimit(1)
                .truncationMode(.middle)
            if node.kind == .leaf {
                Text("+")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(node.tint)
            } else if !node.subtitle.isEmpty {
                Text(node.subtitle)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, horizontalPadding)
        .frame(width: node.width, height: node.height, alignment: .center)
        .background(background, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .stroke(selected ? node.tint.opacity(0.52) : node.tint.opacity(strokeOpacity), lineWidth: selected ? 1.3 : 1)
        )
        .shadow(color: selected ? node.tint.opacity(0.10) : .clear, radius: 10, y: 5)
    }

    private var titleFont: Font {
        switch node.kind {
        case .center: return .callout.weight(.semibold)
        case .lens: return .caption.weight(.semibold)
        case .category, .leaf: return .caption2.weight(.semibold)
        }
    }

    private var horizontalPadding: CGFloat {
        switch node.kind {
        case .center: return 14
        case .lens: return 10
        case .category: return 8
        case .leaf: return 7
        }
    }

    private var cornerRadius: CGFloat {
        node.kind == .leaf || node.kind == .category ? 7 : 8
    }

    private var strokeOpacity: Double {
        switch node.kind {
        case .center: return 0.16
        case .lens: return 0.30
        case .category, .leaf: return 0.22
        }
    }

    private var background: Color {
        if selected {
            return node.tint.opacity(0.08)
        }
        return Color(nsColor: .textBackgroundColor).opacity(node.kind == .center ? 0.98 : 0.92)
    }
}

struct LensDetailStrip: View {
    @EnvironmentObject private var model: ElephantAppModel
    var lens: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(title)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Spacer()
                Text("\(filteredFacts.count) facts")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
            }
            if filteredFacts.isEmpty {
                EmptyLine(symbol: "circle.grid.cross", text: "No reviewable items in this area yet.")
            } else {
                ForEach(filteredFacts.prefix(3)) { fact in
                    Text(fact.text)
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(2)
                }
            }
        }
        .padding(12)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))
    }

    private var title: String {
        lens == "overview" ? "Model overview" : lens.capitalized
    }

    private var filteredFacts: [PersonalModelFact] {
        if lens == "overview" { return Array(model.snapshot.personalModelFacts.prefix(6)) }
        return model.snapshot.personalModelFacts.filter { $0.lens.lowercased().contains(lens.lowercased()) }
    }
}

struct LensNode: View {
    var title: String
    var value: String
    var symbol: String
    var tint: Color
    var prominent = false
    var selected = false

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .font(.system(size: prominent ? 18 : 15, weight: .semibold))
                .foregroundStyle(prominent ? ElephantTheme.ink : tint)
                .frame(width: prominent ? 30 : 24)
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(prominent ? .headline : .callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                    .lineLimit(1)
                Text(value)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, prominent ? 16 : 12)
        .padding(.vertical, prominent ? 13 : 10)
        .frame(width: prominent ? 184 : 148, alignment: .leading)
        .background(
            selected ? tint.opacity(0.08) : Color(nsColor: .textBackgroundColor).opacity(prominent ? 0.98 : 0.92),
            in: RoundedRectangle(cornerRadius: 8, style: .continuous)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(selected ? tint.opacity(0.48) : prominent ? ElephantTheme.line : tint.opacity(0.26), lineWidth: selected ? 1.4 : 1)
        )
        .shadow(color: selected ? tint.opacity(0.10) : .clear, radius: 10, y: 5)
    }
}

struct LensPartitionGrid: View {
    @EnvironmentObject private var model: ElephantAppModel
    @Binding var selectedLens: String

    var body: some View {
        LazyVGrid(columns: columns, spacing: 14) {
            ForEach(partitions) { item in
                Button {
                    selectedLens = item.id
                } label: {
                    LensPartitionCard(item: item, selected: selectedLens == item.id)
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var columns: [GridItem] {
        [GridItem(.flexible(), spacing: 14), GridItem(.flexible(), spacing: 14)]
    }

    private var partitions: [LensPartition] {
        [
            LensPartition(
                id: "identity",
                title: "Identity",
                value: "\(model.snapshot.lensCoverage["identity"] ?? 0)",
                subtitle: "Stable preferences, roles, and self-knowledge.",
                symbol: "person.crop.circle",
                tint: ElephantTheme.accent
            ),
            LensPartition(
                id: "world",
                title: "World",
                value: "\(model.snapshot.lensCoverage["world"] ?? 0)",
                subtitle: "People, projects, places, and external context.",
                symbol: "globe",
                tint: ElephantTheme.green
            ),
            LensPartition(
                id: "pulse",
                title: "Pulse",
                value: "\(model.snapshot.lensCoverage["pulse"] ?? 0)",
                subtitle: "Current state, open loops, and questions to revisit.",
                symbol: "waveform.path.ecg",
                tint: ElephantTheme.orange
            ),
            LensPartition(
                id: "journey",
                title: "Journey",
                value: "\(model.snapshot.lensCoverage["journey"] ?? 0)",
                subtitle: "Lessons, patterns, and decisions that accumulated over time.",
                symbol: "map",
                tint: ElephantTheme.accent.opacity(0.82)
            )
        ]
    }
}

struct LensPartition: Identifiable {
    var id: String
    var title: String
    var value: String
    var subtitle: String
    var symbol: String
    var tint: Color
}

struct LensPartitionCard: View {
    var item: LensPartition
    var selected = false

    var body: some View {
        NativePanel {
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: item.symbol)
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(item.tint)
                    .frame(width: 28)
                VStack(alignment: .leading, spacing: 5) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(item.title)
                            .font(.headline)
                            .foregroundStyle(ElephantTheme.ink)
                        Spacer(minLength: 8)
                        Text(item.value)
                            .font(.headline.weight(.semibold))
                            .foregroundStyle(ElephantTheme.ink)
                    }
                    Text(item.subtitle)
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(selected ? item.tint.opacity(0.55) : Color.clear, lineWidth: selected ? 2 : 0)
        )
    }
}

struct CompactStat: View {
    var value: String
    var label: String

    var body: some View {
        VStack(spacing: 3) {
            Text(value)
                .font(.title3.weight(.semibold))
                .foregroundStyle(ElephantTheme.ink)
            Text(label)
                .font(.caption)
                .foregroundStyle(ElephantTheme.muted)
        }
        .frame(width: 72)
    }
}

struct SourcesSummaryPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                SectionLabel(title: "Sources", subtitle: "\(model.stagedSources.count) local vaults staged")
                if model.stagedSources.isEmpty {
                    EmptyLine(symbol: "folder", text: "No source vaults staged in this desktop session.")
                } else {
                    ForEach(model.stagedSources) { scan in
                        SourceScanRow(scan: scan) {
                            model.revealSource(scan)
                        }
                    }
                }
            }
        }
    }
}

struct ReviewListPanel: View {
    var title: String
    var empty: String
    var items: [String]
    var symbol: String

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                SectionLabel(title: title, subtitle: "\(items.count) shown")
                if items.isEmpty {
                    EmptyLine(symbol: symbol, text: empty)
                } else {
                    ForEach(items, id: \.self) { item in
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: symbol)
                                .foregroundStyle(ElephantTheme.accent)
                                .frame(width: 20)
                            Text(item)
                                .font(.callout)
                                .foregroundStyle(ElephantTheme.ink)
                                .fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
        }
    }
}

struct LensFactsPager: View {
    @EnvironmentObject private var model: ElephantAppModel
    var lens: String
    @State private var page = 0
    private let pageSize = 4

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    SectionLabel(title: lensTitle, subtitle: "\(facts.count) facts · page \(currentPage + 1) of \(pageCount)")
                    Spacer()
                    HStack(spacing: 8) {
                        Button {
                            page = max(0, currentPage - 1)
                        } label: {
                            Image(systemName: "chevron.left")
                        }
                        .buttonStyle(.borderless)
                        .disabled(currentPage == 0)
                        .help("Previous page")

                        Button {
                            page = min(pageCount - 1, currentPage + 1)
                        } label: {
                            Image(systemName: "chevron.right")
                        }
                        .buttonStyle(.borderless)
                        .disabled(currentPage >= pageCount - 1)
                        .help("Next page")
                    }
                }

                Text(lensDescription)
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.muted)
                    .fixedSize(horizontal: false, vertical: true)

                if shownFacts.isEmpty {
                    EmptyLine(symbol: lensSymbol, text: emptyText)
                } else {
                    ForEach(shownFacts) { fact in
                        FactDisclosureRow(fact: fact)
                        if fact.id != shownFacts.last?.id {
                            Divider()
                        }
                    }
                }

            }
        }
        .onChange(of: lens) { _ in
            page = 0
        }
    }

    private var facts: [PersonalModelFact] {
        model.snapshot.personalModelFacts.filter { fact in
            let normalized = fact.lens.lowercased()
            return normalized == lens || normalized.hasPrefix("\(lens).") || normalized.contains(lens)
        }
    }

    private var currentPage: Int {
        min(max(page, 0), pageCount - 1)
    }

    private var pageCount: Int {
        max(1, (facts.count + pageSize - 1) / pageSize)
    }

    private var shownFacts: [PersonalModelFact] {
        Array(facts.dropFirst(currentPage * pageSize).prefix(pageSize))
    }

    private var lensTitle: String {
        switch lens {
        case "world": return "World"
        case "pulse": return "Pulse"
        case "journey": return "Journey"
        default: return "Identity"
        }
    }

    private var lensDescription: String {
        switch lens {
        case "world": return "People, projects, places, tools, and external context Elephant should remember."
        case "pulse": return "Current state, open loops, blockers, and questions that should stay fresh."
        case "journey": return "Lessons, patterns, and decisions from prior episodes."
        default: return "Durable preferences, roles, values, working style, and self-knowledge."
        }
    }

    private var lensSymbol: String {
        switch lens {
        case "world": return "globe"
        case "pulse": return "waveform.path.ecg"
        case "journey": return "map"
        default: return "person.crop.circle"
        }
    }

    private var emptyText: String {
        "No reviewed \(lensTitle) facts yet. Run Reflect after a few useful conversations or sources."
    }
}

struct PersonalFactListPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                SectionLabel(title: "PM Facts", subtitle: "\(model.snapshot.personalModelFacts.count) reviewable")
                if model.snapshot.personalModelFacts.isEmpty {
                    EmptyLine(symbol: "checkmark.seal", text: "No reviewed Personal Model facts yet.")
                } else {
                    ForEach(model.snapshot.personalModelFacts.prefix(8)) { fact in
                        FactDisclosureRow(fact: fact)
                        if fact.id != model.snapshot.personalModelFacts.prefix(8).last?.id {
                            Divider()
                        }
                    }
                }
            }
        }
    }
}

struct FactDisclosureRow: View {
    @EnvironmentObject private var model: ElephantAppModel
    var fact: PersonalModelFact
    @State private var correction = ""
    @State private var isEditing = false

    var body: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 10) {
                if !fact.detail.isEmpty {
                    Text(fact.detail)
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                        .textSelection(.enabled)
                }
                HStack(spacing: 8) {
                    Pill(text: fact.lens, symbol: "circle.grid.cross", tint: tint)
                    Pill(text: fact.status, symbol: "checkmark.seal", tint: fact.status == "active" ? ElephantTheme.green : ElephantTheme.orange)
                }
                if isEditing {
                    TextField("Correct this fact", text: $correction, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(2...4)
                    HStack {
                        Button("Save Correction") {
                            Task {
                                await model.updatePersonalFact(fact, action: "correct", replacementText: correction)
                                isEditing = false
                            }
                        }
                        .disabled(correction.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        Button("Cancel") {
                            isEditing = false
                            correction = fact.text
                        }
                    }
                    .controlSize(.small)
                } else {
                    HStack(spacing: 8) {
                        Button("Correct") {
                            correction = fact.text
                            isEditing = true
                        }
                        if fact.status.lowercased() == "retired" {
                            Button("Recover") {
                                Task { await model.updatePersonalFact(fact, action: "restore") }
                            }
                        } else {
                            Button("Retire") {
                                Task { await model.updatePersonalFact(fact, action: "forget") }
                            }
                        }
                        Button("Delete") {
                            Task { await model.updatePersonalFact(fact, action: "delete") }
                        }
                        if !model.factActionResult.isEmpty {
                            Text(model.factActionResult)
                                .font(.caption)
                                .foregroundStyle(ElephantTheme.green)
                        }
                    }
                    .controlSize(.small)
                }
            }
            .padding(.top, 6)
        } label: {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "checkmark.seal")
                    .foregroundStyle(tint)
                    .frame(width: 20)
                Text(fact.text)
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.ink)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
        }
        .padding(.vertical, 4)
    }

    private var tint: Color {
        let lens = fact.lens.lowercased()
        if lens.contains("pulse") { return ElephantTheme.orange }
        if lens.contains("world") { return ElephantTheme.green }
        if lens.contains("journey") { return ElephantTheme.accent.opacity(0.82) }
        return ElephantTheme.accent
    }
}

struct SkillAffinityPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 16) {
                SectionLabel(title: "Skills Affinity", subtitle: "\(model.snapshot.skillAffinityRows.count) learned affinities")
                if model.snapshot.skillAffinityRows.isEmpty {
                    EmptyLine(
                        symbol: "wand.and.stars",
                        text: model.snapshot.skillAffinities > 0
                            ? "\(model.snapshot.skillAffinities) affinities detected."
                            : "No skill affinity facts yet."
                    )
                    if !model.snapshot.skillNames.isEmpty {
                        FlowLayout(items: model.snapshot.skillNames)
                    }
                } else {
                    ForEach(model.snapshot.skillAffinityRows) { affinity in
                        VStack(alignment: .leading, spacing: 5) {
                            HStack {
                                Label(affinity.name, systemImage: "wand.and.stars")
                                    .font(.headline)
                                    .foregroundStyle(ElephantTheme.ink)
                                Spacer()
                                Text("\(affinity.count)")
                                    .font(.headline.weight(.semibold))
                                    .foregroundStyle(ElephantTheme.accent)
                            }
                            if !affinity.latestText.isEmpty {
                                Text(affinity.latestText)
                                    .font(.callout)
                                    .foregroundStyle(ElephantTheme.muted)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        .padding(.vertical, 6)
                        if affinity.id != model.snapshot.skillAffinityRows.last?.id {
                            Divider()
                        }
                    }
                }
            }
        }
    }
}

struct DiaryPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 16) {
                SectionLabel(title: "Diary", subtitle: "\(model.snapshot.diaryEntries.count) entries")
                if model.snapshot.diaryEntries.isEmpty {
                    EmptyLine(symbol: "book.closed", text: "No diary entries yet. Run Reflect with diary enabled after there is enough context.")
                } else {
                    ForEach(model.snapshot.diaryEntries) { entry in
                        VStack(alignment: .leading, spacing: 10) {
                            HStack {
                                Label(entry.date.isEmpty ? "Diary entry" : entry.date, systemImage: "book.closed")
                                    .font(.headline)
                                    .foregroundStyle(ElephantTheme.ink)
                                Spacer()
                                if !entry.generatedAt.isEmpty {
                                    Text(entry.generatedAt)
                                        .font(.caption)
                                        .foregroundStyle(ElephantTheme.muted)
                                }
                            }
                            MarkdownBody(text: entry.content, font: .callout, color: ElephantTheme.ink)
                        }
                        .padding(.vertical, 6)
                        if entry.id != model.snapshot.diaryEntries.last?.id {
                            Divider()
                        }
                    }
                }
            }
        }
    }
}

struct DiaryView: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var targetDate = Self.defaultDiaryDate()
    @State private var showsDatePicker = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "Diary",
                subtitle: "Reflective entries written from reviewed episodes.",
                actionTitle: model.isReflecting ? "Writing" : "Write Diary",
                actionSymbol: "book.closed"
            ) {
                writeDiaryForSelectedDate()
            }

            NativePanel {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .top, spacing: 12) {
                        Image(systemName: "calendar.badge.clock")
                            .font(.title3)
                            .foregroundStyle(ElephantTheme.accent)
                            .frame(width: 28, height: 28)
                            .accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 3) {
                            SectionLabel(
                                title: "Write Diary",
                                subtitle: "Pick a day with reviewed episodes. Yesterday is selected by default."
                            )
                            Text(selectedDateDisplay)
                                .font(.caption.weight(.medium))
                                .foregroundStyle(ElephantTheme.faint)
                        }
                        Spacer(minLength: 16)
                        diaryStatus
                    }

                    ViewThatFits(in: .horizontal) {
                        HStack(alignment: .center, spacing: 14) {
                            diaryDateControls
                            Spacer(minLength: 16)
                            writeDiaryButton
                        }

                        VStack(alignment: .leading, spacing: 12) {
                            diaryDateControls
                            writeDiaryButton
                        }
                    }
                }
            }

            DiaryPanel()
        }
    }

    private var diaryDateControls: some View {
        HStack(spacing: 8) {
            Button {
                moveTargetDate(by: -1)
            } label: {
                Image(systemName: "chevron.left")
                    .frame(width: 24, height: 22)
            }
            .buttonStyle(.borderless)
            .help("Previous day")
            .accessibilityLabel("Previous diary day")

            Button {
                showsDatePicker.toggle()
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "calendar")
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.accent)
                        .frame(width: 18)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(compactDateTitle)
                            .font(.callout.weight(.semibold))
                            .foregroundStyle(ElephantTheme.ink)
                        Text(compactDateSubtitle)
                            .font(.caption2)
                            .foregroundStyle(ElephantTheme.muted)
                    }
                    Image(systemName: "chevron.down")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.faint)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .frame(minWidth: 172, alignment: .leading)
                .background(ElephantTheme.panel.opacity(0.72), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(ElephantTheme.line, lineWidth: 1)
                )
            }
            .buttonStyle(PressablePlainButtonStyle())
            .popover(isPresented: $showsDatePicker, arrowEdge: .bottom) {
                VStack(alignment: .leading, spacing: 12) {
                    DatePicker("Diary day", selection: $targetDate, displayedComponents: .date)
                        .datePickerStyle(.graphical)
                        .labelsHidden()
                        .frame(width: 300)
                    HStack(spacing: 8) {
                        Button("Yesterday") {
                            setTargetDate(relativeToTodayBy: -1)
                        }
                        Button("Today") {
                            setTargetDate(relativeToTodayBy: 0)
                        }
                        Spacer()
                        Button("Done") {
                            showsDatePicker = false
                        }
                        .keyboardShortcut(.defaultAction)
                    }
                }
                .padding(14)
            }
            .help("Choose diary day")
                .accessibilityLabel("Diary day")

            Button {
                moveTargetDate(by: 1)
            } label: {
                Image(systemName: "chevron.right")
                    .frame(width: 24, height: 22)
            }
            .buttonStyle(.borderless)
            .help("Next day")
            .accessibilityLabel("Next diary day")

            Divider()
                .frame(height: 24)

            Button("Yesterday") {
                setTargetDate(relativeToTodayBy: -1)
            }
            .buttonStyle(.bordered)
            .help("Select yesterday")

            Button("Today") {
                setTargetDate(relativeToTodayBy: 0)
            }
            .buttonStyle(.bordered)
            .help("Select today")
        }
    }

    private var writeDiaryButton: some View {
        Button {
            writeDiaryForSelectedDate()
        } label: {
            Label(model.isReflecting ? "Writing" : "Write for \(requestDateString)", systemImage: "square.and.pencil")
                .lineLimit(1)
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
        .tint(ElephantTheme.accent)
        .disabled(model.isReflecting)
    }

    @ViewBuilder
    private var diaryStatus: some View {
        if model.isReflecting {
            HStack(spacing: 8) {
                ProgressView()
                    .controlSize(.small)
                Text("Writing diary")
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.muted)
            }
        } else if !model.diaryActionResult.isEmpty {
            Label(model.diaryActionResult, systemImage: "checkmark.circle.fill")
                .font(.callout)
                .foregroundStyle(ElephantTheme.green)
                .lineLimit(2)
                .multilineTextAlignment(.trailing)
        }
    }

    private var requestDateString: String {
        Self.requestDateFormatter.string(from: targetDate)
    }

    private var selectedDateDisplay: String {
        Self.displayDateFormatter.string(from: targetDate)
    }

    private var compactDateTitle: String {
        Self.compactDateFormatter.string(from: targetDate)
    }

    private var compactDateSubtitle: String {
        Self.yearFormatter.string(from: targetDate)
    }

    private func writeDiaryForSelectedDate() {
        let date = requestDateString
        Task { await model.writeDiary(targetDate: date) }
    }

    private func moveTargetDate(by dayDelta: Int) {
        targetDate = Calendar.current.date(byAdding: .day, value: dayDelta, to: targetDate) ?? targetDate
    }

    private func setTargetDate(relativeToTodayBy dayDelta: Int) {
        targetDate = Calendar.current.date(byAdding: .day, value: dayDelta, to: Date()) ?? Date()
    }

    private static func defaultDiaryDate() -> Date {
        Calendar.current.date(byAdding: .day, value: -1, to: Date()) ?? Date()
    }

    private static let requestDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    private static let displayDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .full
        formatter.timeStyle = .none
        return formatter
    }()

    private static let compactDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.setLocalizedDateFormatFromTemplate("EEE, MMM d")
        return formatter
    }()

    private static let yearFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.setLocalizedDateFormatFromTemplate("yyyy")
        return formatter
    }()
}

struct SkillsView: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "Skills",
                subtitle: "What Elephant can do, and when your Personal Model tends to need each skill.",
                actionTitle: "Refresh",
                actionSymbol: "arrow.clockwise"
            ) {
                Task { try? await model.refreshDashboard() }
            }

            HStack(spacing: 12) {
                MetricTile(label: "Installed", value: "\(model.snapshot.skills)", symbol: "wand.and.stars")
                MetricTile(label: "Affinity", value: "\(model.snapshot.skillAffinities)", symbol: "sparkles", tint: ElephantTheme.orange)
                MetricTile(label: "Enabled", value: "\(enabledSkills)", symbol: "checkmark.seal", tint: ElephantTheme.green)
            }

            SkillAffinityPanel()
            SkillLibraryPanel()
        }
    }

    private var enabledSkills: Int {
        let enabled = model.snapshot.skillItems.filter(\.enabled).count
        if enabled > 0 || !model.snapshot.skillItems.isEmpty {
            return enabled
        }
        return model.snapshot.skills
    }
}

struct ToolsView: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "Tools",
                subtitle: "Operator actions Elephant can call from local agent loops.",
                actionTitle: "Refresh",
                actionSymbol: "arrow.clockwise"
            ) {
                Task { try? await model.refreshDashboard() }
            }

            HStack(spacing: 12) {
                MetricTile(label: "Built-in", value: "\(model.snapshot.enabledTools)/\(model.snapshot.tools)", symbol: "wrench.and.screwdriver")
                MetricTile(label: "MCP Servers", value: "\(model.snapshot.mcpServers)", symbol: "server.rack", tint: ElephantTheme.green)
                MetricTile(label: "MCP Tools", value: "\(model.snapshot.mcpTools)", symbol: "point.3.connected.trianglepath.dotted", tint: ElephantTheme.orange)
            }

            ToolsCatalogPanel()
        }
    }
}

struct MessagingView: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "Messaging",
                subtitle: "IM bridges for WeChat, Feishu, Discord, DingDing, and WeCom.",
                actionTitle: "Refresh",
                actionSymbol: "arrow.clockwise"
            ) {
                Task { try? await model.refreshDashboard() }
            }

            HStack(spacing: 12) {
                MetricTile(label: "Services", value: "\(model.snapshot.gatewayServices)", symbol: "message.badge")
                MetricTile(label: "Configured", value: "\(model.snapshot.gatewayConfigured)", symbol: "checkmark.seal", tint: ElephantTheme.green)
                MetricTile(label: "Running", value: "\(model.snapshot.gatewayRunning)", symbol: "bolt.horizontal", tint: ElephantTheme.orange)
            }

            NativePanel {
                VStack(alignment: .leading, spacing: 14) {
                    SectionLabel(title: "IM Bridge Cards", subtitle: "Configure credentials, start bridges, and scan WeChat QR from the desktop app.")
                    if !model.gatewayActionResult.isEmpty {
                        Text(model.gatewayActionResult)
                            .font(.callout)
                            .foregroundStyle(ElephantTheme.green)
                    }
                    if model.snapshot.gatewayItems.isEmpty {
                        EmptyLine(symbol: "message.badge", text: "No messaging adapters were returned by the local runtime.")
                    } else {
                        ForEach(model.snapshot.gatewayItems) { service in
                            GatewayServiceCard(service: service)
                            if service.id != model.snapshot.gatewayItems.last?.id {
                                Divider()
                            }
                        }
                    }
                }
            }
        }
    }
}

struct GatewayServiceCard: View {
    @EnvironmentObject private var model: ElephantAppModel
    var service: GatewayServiceItem
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button {
                expanded.toggle()
            } label: {
                HStack(alignment: .center, spacing: 12) {
                    GatewayServiceLogo(service: service)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(service.title)
                            .font(.headline)
                            .foregroundStyle(ElephantTheme.ink)
                        Text(detailLine)
                            .font(.caption)
                            .foregroundStyle(ElephantTheme.muted)
                    }
                    Spacer(minLength: 0)
                    Pill(text: statusLabel, symbol: "antenna.radiowaves.left.and.right", tint: statusTint)
                    Image(systemName: expanded ? "chevron.up" : "chevron.down")
                        .foregroundStyle(ElephantTheme.faint)
                }
            }
            .buttonStyle(.plain)

            if expanded {
                VStack(alignment: .leading, spacing: 12) {
                    if !service.setupNote.isEmpty {
                        Text(service.setupNote)
                            .font(.callout)
                            .foregroundStyle(ElephantTheme.muted)
                    }
                    SettingsRow(label: "Account", value: service.accountID)
                    SettingsRow(label: "Transport", value: service.transport.isEmpty ? "default" : service.transport)
                    if !service.eventPath.isEmpty {
                        SettingsRow(label: "Event path", value: service.eventPath)
                    }
                    if service.id == "weixin" {
                        WeixinQRPanel()
                    } else if !service.secretFields.isEmpty {
                        GatewaySecretEditor(service: service)
                    }
                    HStack(spacing: 8) {
                        if service.configured {
                            Button(service.running ? "Restart" : "Start") {
                                Task { await model.runGatewayAction(service: service, action: service.running ? "restart" : "start") }
                            }
                            Button("Stop") {
                                Task { await model.runGatewayAction(service: service, action: "stop") }
                            }
                            .disabled(!service.running && !service.starting)
                        } else if service.id == "weixin" {
                            Button("Connect with QR") {
                                Task { await model.startWeixinQR() }
                            }
                        } else {
                            Button("Save Configuration") {
                                Task { await model.configureGatewayService(service) }
                            }
                        }
                    }
                    .controlSize(.small)
                }
                .padding(12)
                .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
        }
        .padding(.vertical, 8)
    }

    private var statusLabel: String {
        service.running ? "running" : service.starting ? "starting" : service.configured ? "configured" : "setup"
    }

    private var statusTint: Color {
        if service.running { return ElephantTheme.green }
        if service.starting { return ElephantTheme.accent }
        if service.configured { return ElephantTheme.green }
        return ElephantTheme.faint
    }

    private var detailLine: String {
        [service.detail, "\(service.accountCount) account(s)"].filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

private struct GatewayServiceLogo: View {
    var service: GatewayServiceItem

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(spec.tint.opacity(0.11))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(spec.tint.opacity(0.22), lineWidth: 1)
                )
            Image(systemName: spec.symbol)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(spec.tint)
            Circle()
                .fill(statusTint)
                .frame(width: 9, height: 9)
                .overlay(Circle().stroke(Color(nsColor: .textBackgroundColor), lineWidth: 1.5))
                .offset(x: 2, y: 2)
        }
        .frame(width: 42, height: 42)
        .accessibilityHidden(true)
    }

    private var spec: GatewayLogoSpec {
        GatewayLogoSpec.forService(service)
    }

    private var statusTint: Color {
        if service.running { return ElephantTheme.green }
        if service.starting { return ElephantTheme.accent }
        if service.configured { return ElephantTheme.green }
        return ElephantTheme.faint
    }
}

private struct GatewayLogoSpec {
    var symbol: String
    var tint: Color

    static func forService(_ service: GatewayServiceItem) -> GatewayLogoSpec {
        let raw = "\(service.id) \(service.title)".lowercased()
        if raw.contains("wechat") || raw.contains("weixin") || raw.contains("微信") {
            return GatewayLogoSpec(symbol: "message.circle.fill", tint: ElephantTheme.green)
        }
        if raw.contains("feishu") || raw.contains("lark") {
            return GatewayLogoSpec(symbol: "paperplane.fill", tint: ElephantTheme.accent)
        }
        if raw.contains("discord") {
            return GatewayLogoSpec(symbol: "gamecontroller.fill", tint: ElephantTheme.accent)
        }
        if raw.contains("ding") {
            return GatewayLogoSpec(symbol: "bell.and.waves.left.and.right.fill", tint: ElephantTheme.orange)
        }
        if raw.contains("wecom") || raw.contains("work") {
            return GatewayLogoSpec(symbol: "building.2.crop.circle.fill", tint: ElephantTheme.green)
        }
        return GatewayLogoSpec(symbol: "message.badge.fill", tint: ElephantTheme.accent)
    }
}

struct GatewaySecretEditor: View {
    @EnvironmentObject private var model: ElephantAppModel
    var service: GatewayServiceItem

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(service.secretFields) { field in
                LabeledContent(field.label) {
                    SecureField(field.hasValue ? "stored locally" : "paste once", text: binding(for: field.key))
                        .textFieldStyle(.roundedBorder)
                }
            }
        }
    }

    private func binding(for key: String) -> Binding<String> {
        Binding(
            get: { model.gatewaySecretDrafts[service.id]?[key] ?? "" },
            set: { value in
                var serviceDraft = model.gatewaySecretDrafts[service.id] ?? [:]
                serviceDraft[key] = value
                model.gatewaySecretDrafts[service.id] = serviceDraft
            }
        )
    }
}

struct WeixinQRPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Button("Start QR") {
                    Task { await model.startWeixinQR() }
                }
                Button("Check Scan") {
                    Task { await model.pollWeixinQR() }
                }
                .disabled(model.gatewayQR.sessionID.isEmpty)
                if !model.gatewayQR.status.isEmpty {
                    Pill(text: model.gatewayQR.status, symbol: "qrcode.viewfinder", tint: qrTint)
                }
            }
            if !model.gatewayQR.matrix.isEmpty {
                HStack(alignment: .center, spacing: 14) {
                    GatewayQRMatrixView(matrix: model.gatewayQR.matrix)
                        .frame(width: 160, height: 160)
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Scan with WeChat")
                            .font(.headline)
                            .foregroundStyle(ElephantTheme.ink)
                        Text(model.gatewayQR.message.isEmpty ? "Scan, confirm on phone, then click Check Scan." : model.gatewayQR.message)
                            .font(.callout)
                            .foregroundStyle(ElephantTheme.muted)
                        if !model.gatewayQR.qrcodeURL.isEmpty {
                            Text(model.gatewayQR.qrcodeURL)
                                .font(.caption)
                                .foregroundStyle(ElephantTheme.accent)
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                    }
                }
            }
        }
    }

    private var qrTint: Color {
        model.gatewayQR.status == "confirmed" ? ElephantTheme.green : ElephantTheme.orange
    }
}

struct GatewayQRMatrixView: View {
    var matrix: [[Int]]

    var body: some View {
        GeometryReader { proxy in
            Canvas { context, size in
                let rows = max(matrix.count, 1)
                let cols = max(matrix.first?.count ?? rows, 1)
                let cell = min(size.width / CGFloat(cols), size.height / CGFloat(rows))
                let origin = CGPoint(
                    x: (size.width - CGFloat(cols) * cell) / 2,
                    y: (size.height - CGFloat(rows) * cell) / 2
                )
                for row in 0..<rows {
                    let values = row < matrix.count ? matrix[row] : []
                    for col in 0..<cols where col < values.count && values[col] != 0 {
                        let rect = CGRect(x: origin.x + CGFloat(col) * cell, y: origin.y + CGFloat(row) * cell, width: cell, height: cell)
                        context.fill(Path(rect), with: .color(ElephantTheme.ink))
                    }
                }
            }
        }
        .padding(10)
        .background(.white, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))
    }
}

struct HerdView: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var showingCreate = false

    private let columns = [
        GridItem(.adaptive(minimum: 330, maximum: 520), spacing: 14, alignment: .top)
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "Herd",
                subtitle: "Manage the local elephants that share this desktop runtime.",
                actionTitle: "New Elephant",
                actionSymbol: "plus"
            ) {
                showingCreate = true
            }

            NativePanel {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .firstTextBaseline) {
                        SectionLabel(title: "Local Elephants", subtitle: "\(model.snapshot.herdItems.count) state(s)")
                        Spacer(minLength: 0)
                        Button {
                            Task { try? await model.refreshDashboard() }
                        } label: {
                            Label("Refresh", systemImage: "arrow.clockwise")
                        }
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                    }

                    if model.snapshot.herdItems.isEmpty {
                        EmptyLine(symbol: "person.3", text: "No local elephant has been created yet. Run onboarding from Settings after provider setup.")
                    } else {
                        LazyVGrid(columns: columns, alignment: .leading, spacing: 14) {
                            ForEach(model.snapshot.herdItems) { item in
                                HerdElephantCard(item: item)
                            }
                        }
                    }
                }
            }
        }
        .sheet(isPresented: $showingCreate) {
            HerdCreateSheet(isPresented: $showingCreate)
                .environmentObject(model)
        }
    }
}

struct HerdCreateSheet: View {
    @EnvironmentObject private var model: ElephantAppModel
    @Binding var isPresented: Bool
    @State private var name = "Elephant"
    @State private var identityText = ""
    @State private var avatarURL: URL?

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .center, spacing: 14) {
                HerdAvatarImage(size: 82, name: name, url: avatarURL)
                VStack(alignment: .leading, spacing: 8) {
                    Text("Create Elephant")
                        .font(.title2.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                    Text("Create a local Elephant with a name and an authored ELEPHANT.md voice file.")
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.muted)
                    HStack(spacing: 8) {
                        Button("Choose Avatar") {
                            avatarURL = OpenPanelBridge.pickAvatarImageURL()
                        }
                        Button("Use Default") {
                            avatarURL = nil
                        }
                        .disabled(avatarURL == nil)
                    }
                    .controlSize(.small)
                }
                Spacer(minLength: 0)
            }

            TextField("Name", text: $name)
                .textFieldStyle(.roundedBorder)

            TextField("ELEPHANT.md", text: $identityText, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(8...14)

            HStack {
                Spacer()
                Button("Cancel") {
                    isPresented = false
                }
                Button("Create Elephant") {
                    Task {
                        await model.createHerdElephant(
                            name: name,
                            identityText: identityText,
                            avatarURL: avatarURL
                        )
                        isPresented = false
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(ElephantTheme.accent)
                .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(22)
        .frame(width: 600)
        .background(ElephantTheme.elevated)
    }
}

struct HerdElephantCard: View {
    @EnvironmentObject private var model: ElephantAppModel
    var item: HerdItem
    @State private var name = ""
    @State private var identityText = ""
    @State private var confirmDelete = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 13) {
                ZStack(alignment: .bottomTrailing) {
                    HerdAvatarImage(size: 64, name: item.title, url: model.herdAvatarURL(for: item))
                    Button {
                        model.pickHerdAvatar(for: item)
                    } label: {
                        Image(systemName: "camera.fill")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(.white)
                            .frame(width: 24, height: 24)
                            .background(ElephantTheme.accent, in: Circle())
                            .overlay(Circle().stroke(Color(nsColor: .textBackgroundColor), lineWidth: 2))
                    }
                    .buttonStyle(PressablePlainButtonStyle())
                    .help("Change Avatar")
                }

                VStack(alignment: .leading, spacing: 3) {
                    Text(item.title)
                        .font(.headline)
                        .foregroundStyle(ElephantTheme.ink)
                    Text([item.subtitle, item.profileID].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(2)
                }
                Spacer(minLength: 0)
            }

            HStack(spacing: 8) {
                Pill(text: item.status.isEmpty ? "ready" : item.status, symbol: "circle.fill", tint: item.current ? ElephantTheme.green : ElephantTheme.accent)
                if item.level > 0 || !item.stage.isEmpty {
                    Pill(text: item.stage.isEmpty ? "level \(item.level)" : item.stage, symbol: "sparkles", tint: ElephantTheme.accent)
                }
                if item.current {
                    Pill(text: "current", symbol: "checkmark", tint: ElephantTheme.green)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Divider()

            TextField("Name", text: $name)
                .textFieldStyle(.roundedBorder)

            TextField("ELEPHANT.md", text: $identityText, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(8...14)

            LazyVGrid(columns: metaColumns, spacing: 10) {
                HerdMeta(label: "Profile", value: item.profileID.isEmpty ? "n/a" : item.profileID)
                HerdMeta(label: "Created", value: item.createdAt.isEmpty ? "n/a" : item.createdAt)
                HerdMeta(label: "Source", value: sourceLabel)
                HerdMeta(label: "Updated", value: item.updatedAt.isEmpty ? "n/a" : item.updatedAt)
            }

            HStack {
                Button("Save Changes") {
                    Task {
                        await model.updateHerdElephant(
                            item,
                            name: name,
                            identityText: identityText
                        )
                    }
                }
                Button("Delete", role: .destructive) {
                    confirmDelete = true
                }
                .disabled(item.current)
                Spacer()
                if item.current {
                    Text("Current elephant is protected.")
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                }
            }
            .controlSize(.small)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Color(nsColor: .textBackgroundColor).opacity(0.78), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(item.current ? ElephantTheme.green.opacity(0.26) : ElephantTheme.line, lineWidth: 1)
        )
        .onAppear {
            name = item.title
            identityText = sanitizedText(item.identityText)
        }
        .confirmationDialog("Delete \(item.title)?", isPresented: $confirmDelete) {
            Button("Delete Elephant", role: .destructive) {
                Task { await model.deleteHerdElephant(item) }
            }
        } message: {
            Text("This removes the local Elephant state. The current Elephant is protected.")
        }
    }

    private func sanitizedText(_ text: String) -> String {
        text
            .replacingOccurrences(of: #"(?s)<!--\s*Internal metadata.*?-->\s*"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var metaColumns: [GridItem] {
        [
            GridItem(.flexible(), spacing: 10, alignment: .leading),
            GridItem(.flexible(), spacing: 10, alignment: .leading)
        ]
    }

    private var sourceLabel: String {
        item.source.isEmpty ? "n/a" : item.source.replacingOccurrences(of: "_", with: " ")
    }
}

struct HerdAvatarImage: View {
    var size: CGFloat
    var name: String
    var url: URL?

    var body: some View {
        Group {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFill()
            } else if let image = BundleAssets.image(named: "favicon.png", subdirectory: "Brand") {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                    .padding(size * 0.08)
            } else {
                Image(systemName: "person.crop.circle")
                    .font(.system(size: size * 0.46, weight: .semibold))
                    .foregroundStyle(ElephantTheme.accent)
            }
        }
        .frame(width: size, height: size)
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.72), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(ElephantTheme.line.opacity(0.7), lineWidth: 1)
        )
    }

    private var image: NSImage? {
        guard let url else { return nil }
        return NSImage(contentsOf: url)
    }
}

struct HerdMeta: View {
    var label: String
    var value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.caption.weight(.semibold))
                .foregroundStyle(ElephantTheme.muted)
            Text(value)
                .font(.caption)
                .foregroundStyle(ElephantTheme.ink)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

enum UsagePeriod: String, CaseIterable, Identifiable {
    case day = "Day"
    case week = "Week"
    case month = "Month"

    var id: String { rawValue }
}

struct UsageView: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var period: UsagePeriod = .day

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "Usage",
                subtitle: "Token usage details from local runtime steps.",
                actionTitle: "Refresh",
                actionSymbol: "arrow.clockwise"
            ) {
                Task { try? await model.refreshDashboard() }
            }

            HStack(spacing: 12) {
                MetricTile(label: "Total Tokens", value: abbreviatedCount(model.snapshot.usageTokens), symbol: "sum")
                MetricTile(label: "Prompt", value: abbreviatedCount(model.snapshot.usagePromptTokens), symbol: "arrow.down.doc", tint: ElephantTheme.accent)
                MetricTile(label: "Completion", value: abbreviatedCount(model.snapshot.usageCompletionTokens), symbol: "arrow.up.doc", tint: ElephantTheme.green)
                MetricTile(label: "Events", value: "\(model.snapshot.usageEvents)", symbol: "waveform.path", tint: ElephantTheme.orange)
            }

            NativePanel {
                VStack(alignment: .leading, spacing: 16) {
                    HStack {
                        SectionLabel(title: "Token Flow", subtitle: "Usage grouped by day, week, or month")
                        Spacer()
                        Picker("Period", selection: $period) {
                            ForEach(UsagePeriod.allCases) { item in
                                Text(item.rawValue).tag(item)
                            }
                        }
                        .pickerStyle(.segmented)
                        .frame(width: 210)
                    }
                    UsageChartView(points: periodPoints, events: model.snapshot.usageItems)
                        .frame(height: 220)
                    UsageTotalsTable(points: periodPoints)
                }
            }

            NativePanel {
                VStack(alignment: .leading, spacing: 14) {
                    SectionLabel(title: "Recent Token Events", subtitle: "\(model.snapshot.usageItems.count) shown")
                    if model.snapshot.usageItems.isEmpty {
                        EmptyLine(symbol: "chart.xyaxis.line", text: "No token usage rows yet.")
                    } else {
                        ForEach(model.snapshot.usageItems.prefix(12)) { item in
                            UsageEventRow(item: item, maxTokens: maxTokenEvent)
                            if item.id != model.snapshot.usageItems.prefix(12).last?.id {
                                Divider()
                            }
                        }
                    }
                }
            }
        }
    }

    private var maxTokenEvent: Int {
        max(model.snapshot.usageItems.map(\.totalTokens).max() ?? 1, 1)
    }

    private var periodPoints: [UsageTrendPoint] {
        UsageAggregation.group(model.snapshot.usageTrend, events: model.snapshot.usageItems, by: period)
    }

    private func abbreviatedCount(_ value: Int) -> String {
        if value >= 1_000_000 { return String(format: "%.1fM", Double(value) / 1_000_000.0) }
        if value >= 1_000 { return String(format: "%.1fK", Double(value) / 1_000.0) }
        return "\(value)"
    }
}

enum UsageAggregation {
    static func group(_ points: [UsageTrendPoint], events: [UsageEventItem], by period: UsagePeriod) -> [UsageTrendPoint] {
        let base = points.isEmpty
            ? events.enumerated().map { index, event in
                UsageTrendPoint(
                    date: event.subtitle.isEmpty ? "\(index + 1)" : String(event.subtitle.prefix(10)),
                    promptTokens: event.promptTokens,
                    completionTokens: event.completionTokens,
                    totalTokens: event.totalTokens
                )
            }
            : points
        guard period != .day else { return Array(base.suffix(30)) }

        var buckets: [String: UsageTrendPoint] = [:]
        for point in base {
            let key = bucketKey(for: point.date, period: period)
            var current = buckets[key] ?? UsageTrendPoint(date: key, promptTokens: 0, completionTokens: 0, totalTokens: 0)
            current.promptTokens += point.promptTokens
            current.completionTokens += point.completionTokens
            current.totalTokens += point.totalTokens
            buckets[key] = current
        }
        return buckets.keys.sorted().compactMap { buckets[$0] }.suffixArray(18)
    }

    private static func bucketKey(for rawDate: String, period: UsagePeriod) -> String {
        guard let date = parseDate(rawDate) else { return rawDate }
        var calendar = Calendar(identifier: .gregorian)
        calendar.firstWeekday = 2
        switch period {
        case .day:
            return rawDate
        case .week:
            let components = calendar.dateComponents([.yearForWeekOfYear, .weekOfYear], from: date)
            let year = components.yearForWeekOfYear ?? calendar.component(.year, from: date)
            let week = components.weekOfYear ?? 1
            return "\(year)-W\(String(format: "%02d", week))"
        case .month:
            let year = calendar.component(.year, from: date)
            let month = calendar.component(.month, from: date)
            return "\(year)-\(String(format: "%02d", month))"
        }
    }

    private static func parseDate(_ value: String) -> Date? {
        let trimmed = String(value.prefix(10))
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.date(from: trimmed)
    }
}

private extension Array {
    func suffixArray(_ maxLength: Int) -> [Element] {
        Array(suffix(maxLength))
    }
}

struct UsageChartView: View {
    var points: [UsageTrendPoint]
    var events: [UsageEventItem]

    var body: some View {
        GeometryReader { proxy in
            Canvas { context, size in
                let rows = points.isEmpty
                    ? Array(events.prefix(12).enumerated()).map { UsageTrendPoint(date: "\($0.offset)", promptTokens: $0.element.promptTokens, completionTokens: $0.element.completionTokens, totalTokens: $0.element.totalTokens) }
                    : points
                let maxTokens = max(rows.map(\.totalTokens).max() ?? 1, 1)
                let barWidth = size.width / CGFloat(max(rows.count, 1))
                for (index, point) in rows.enumerated() {
                    let x = CGFloat(index) * barWidth + barWidth * 0.18
                    let height = size.height * CGFloat(point.totalTokens) / CGFloat(maxTokens)
                    let promptHeight = height * CGFloat(point.promptTokens) / CGFloat(max(point.totalTokens, 1))
                    let completionHeight = max(0, height - promptHeight)
                    let baseY = size.height - height
                    let promptRect = CGRect(x: x, y: baseY + completionHeight, width: barWidth * 0.64, height: promptHeight)
                    let completionRect = CGRect(x: x, y: baseY, width: barWidth * 0.64, height: completionHeight)
                    context.fill(Path(roundedRect: completionRect, cornerSize: CGSize(width: 4, height: 4)), with: .color(ElephantTheme.green.opacity(0.58)))
                    context.fill(Path(roundedRect: promptRect, cornerSize: CGSize(width: 4, height: 4)), with: .color(ElephantTheme.accent.opacity(0.62)))
                }
            }
        }
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

struct UsageTotalsTable: View {
    var points: [UsageTrendPoint]

    var body: some View {
        if points.isEmpty {
            EmptyLine(symbol: "chart.xyaxis.line", text: "No token flow rows yet.")
        } else {
            VStack(spacing: 0) {
                HStack {
                    tableHeader("Period")
                    tableHeader("Tokens")
                    tableHeader("Input")
                    tableHeader("Output")
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                ForEach(Array(points.suffixArray(8).reversed())) { point in
                    HStack {
                        tableCell(point.date, weight: .semibold)
                        tableCell(compact(point.totalTokens))
                        tableCell(compact(point.promptTokens))
                        tableCell(compact(point.completionTokens))
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    if point.id != points.suffixArray(8).first?.id {
                        Divider()
                    }
                }
            }
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))
        }
    }

    private func tableHeader(_ text: String) -> some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .foregroundStyle(ElephantTheme.muted)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func tableCell(_ text: String, weight: Font.Weight = .regular) -> some View {
        Text(text)
            .font(.callout.weight(weight))
            .foregroundStyle(ElephantTheme.ink)
            .lineLimit(1)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func compact(_ value: Int) -> String {
        if value >= 1_000_000 { return String(format: "%.1fM", Double(value) / 1_000_000.0) }
        if value >= 1_000 { return String(format: "%.1fK", Double(value) / 1_000.0) }
        return "\(value)"
    }
}

struct UsageEventRow: View {
    var item: UsageEventItem
    var maxTokens: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(item.title)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Spacer()
                Text("\(item.totalTokens) tokens")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
            }
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule().fill(ElephantTheme.line.opacity(0.28))
                    HStack(spacing: 0) {
                        Rectangle().fill(ElephantTheme.accent.opacity(0.72)).frame(width: segmentWidth(proxy.size.width, item.promptTokens))
                        Rectangle().fill(ElephantTheme.green.opacity(0.72)).frame(width: segmentWidth(proxy.size.width, item.completionTokens))
                    }
                    .clipShape(Capsule())
                }
            }
            .frame(height: 7)
            Text([item.provider, item.subtitle].filter { !$0.isEmpty }.joined(separator: " · "))
                .font(.caption)
                .foregroundStyle(ElephantTheme.muted)
                .lineLimit(1)
        }
        .padding(.vertical, 7)
    }

    private func segmentWidth(_ totalWidth: CGFloat, _ value: Int) -> CGFloat {
        totalWidth * CGFloat(value) / CGFloat(max(maxTokens, 1))
    }
}

struct ProviderView: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "Model Provider",
                subtitle: providerSubtitle,
                actionTitle: "Refresh",
                actionSymbol: "arrow.clockwise"
            ) {
                Task { try? await model.refreshDashboard() }
            }

            HStack(spacing: 12) {
                MetricTile(
                    label: "Provider",
                    value: model.snapshot.providerID.isEmpty ? "Setup" : model.snapshot.providerID,
                    symbol: "cpu",
                    tint: providerTint
                )
                MetricTile(
                    label: "Model",
                    value: model.snapshot.providerModelID.isEmpty ? "Not selected" : model.snapshot.providerModelID,
                    symbol: "sparkles",
                    tint: ElephantTheme.accent
                )
                MetricTile(
                    label: "Embedding",
                    value: model.snapshot.embeddingProviderID.isEmpty ? embeddingStatus : model.snapshot.embeddingProviderID,
                    symbol: "point.3.connected.trianglepath.dotted",
                    tint: model.snapshot.localModelWarm ? ElephantTheme.green : ElephantTheme.accent
                )
            }

            NativePanel {
                ProviderSettingsContent()
            }
        }
    }

    private var providerSubtitle: String {
        model.snapshot.providerModelID.isEmpty
            ? "Choose the provider and model Elephant uses for reasoning."
            : "Elephant is currently using \(model.snapshot.providerModelID)."
    }

    private var providerTint: Color {
        if model.snapshot.providerID.isEmpty || model.snapshot.providerModelID.isEmpty {
            return ElephantTheme.orange
        }
        return ElephantTheme.green
    }

    private var embeddingStatus: String {
        if !model.snapshot.embeddingRuntimeState.isEmpty, !model.snapshot.localModelWarm {
            return model.snapshot.embeddingRuntimeState
        }
        if !model.snapshot.embeddingStatus.isEmpty {
            return model.snapshot.embeddingStatus
        }
        return model.snapshot.semanticStatus.isEmpty ? "unknown" : model.snapshot.semanticStatus
    }
}

enum ScheduleCalendarScope: String, CaseIterable, Identifiable {
    case week = "Week"
    case month = "Month"
    case year = "Year"

    var id: String { rawValue }

    var stepComponent: Calendar.Component {
        switch self {
        case .week: return .weekOfYear
        case .month: return .month
        case .year: return .year
        }
    }
}

struct CronCalendarEvent: Identifiable, Equatable {
    var id: String { job.id }
    var job: CronJobItem
    var date: Date

    var tint: Color {
        if job.status.lowercased() == "paused" { return ElephantTheme.orange }
        if job.isSystem { return ElephantTheme.green }
        return ElephantTheme.accent
    }

    var timeText: String {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.dateStyle = .none
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }

    static func from(_ job: CronJobItem) -> CronCalendarEvent? {
        guard let date = parseDate(job.nextRun) else { return nil }
        return CronCalendarEvent(job: job, date: date)
    }

    private static func parseDate(_ raw: String) -> Date? {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }

        let candidates = [
            text,
            text.replacingOccurrences(
                of: #"(\.\d{3})\d+(?=Z|[+-]\d{2}:?\d{2})"#,
                with: "$1",
                options: .regularExpression
            )
        ]

        for candidate in candidates {
            let fractional = ISO8601DateFormatter()
            fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = fractional.date(from: candidate) { return date }

            let plain = ISO8601DateFormatter()
            plain.formatOptions = [.withInternetDateTime]
            if let date = plain.date(from: candidate) { return date }
        }

        for pattern in ["yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd"] {
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.dateFormat = pattern
            if let date = formatter.date(from: text) { return date }
        }
        return nil
    }
}

struct CronView: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var scope: ScheduleCalendarScope = .month
    @State private var focusedDate = Date()

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "Calendar",
                subtitle: "Reminders from Elephant, agents, and this app in one native calendar.",
                actionTitle: "Refresh",
                actionSymbol: "arrow.clockwise"
            ) {
                Task { try? await model.refreshDashboard() }
            }

            ScheduleCalendarPanel(
                scope: $scope,
                focusedDate: $focusedDate,
                jobs: model.snapshot.cronItems
            )

            ReminderComposerLauncher()

            CalendarJobsPanel()
        }
    }
}

struct ScheduleCalendarPanel: View {
    @Binding var scope: ScheduleCalendarScope
    @Binding var focusedDate: Date
    var jobs: [CronJobItem]

    private var events: [CronCalendarEvent] {
        jobs.compactMap(CronCalendarEvent.from)
    }

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .center, spacing: 12) {
                    Text(title)
                        .font(.title2.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)

                    HStack(spacing: 8) {
                        StatusDot(tint: ElephantTheme.green)
                        Text("\(events.count) dated")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(ElephantTheme.muted)
                    }

                    Spacer(minLength: 12)

                    Picker("Calendar view", selection: $scope) {
                        ForEach(ScheduleCalendarScope.allCases) { item in
                            Text(item.rawValue).tag(item)
                        }
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 260)

                    Spacer(minLength: 12)

                    HStack(spacing: 6) {
                        Button {
                            move(-1)
                        } label: {
                            Image(systemName: "chevron.left")
                                .frame(width: 28, height: 28)
                        }
                        .buttonStyle(PressablePlainButtonStyle())
                        .help("Previous \(scope.rawValue.lowercased())")

                        Button("Today") {
                            focusedDate = Date()
                        }
                        .controlSize(.small)

                        Button {
                            move(1)
                        } label: {
                            Image(systemName: "chevron.right")
                                .frame(width: 28, height: 28)
                        }
                        .buttonStyle(PressablePlainButtonStyle())
                        .help("Next \(scope.rawValue.lowercased())")
                    }
                }

                Divider()

                switch scope {
                case .week:
                    WeekCalendarGrid(focusedDate: focusedDate, events: events)
                case .month:
                    MonthCalendarGrid(focusedDate: focusedDate, events: events)
                case .year:
                    YearCalendarGrid(focusedDate: focusedDate, events: events)
                }
            }
        }
    }

    private var title: String {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        switch scope {
        case .week:
            let interval = Calendar.current.dateInterval(of: .weekOfYear, for: focusedDate)
            formatter.dateFormat = "MMM d"
            let start = interval?.start ?? focusedDate
            let end = Calendar.current.date(byAdding: .day, value: 6, to: start) ?? focusedDate
            return "\(formatter.string(from: start)) - \(formatter.string(from: end))"
        case .month:
            formatter.dateFormat = "MMMM yyyy"
            return formatter.string(from: focusedDate)
        case .year:
            formatter.dateFormat = "yyyy"
            return formatter.string(from: focusedDate)
        }
    }

    private func move(_ delta: Int) {
        focusedDate = Calendar.current.date(byAdding: scope.stepComponent, value: delta, to: focusedDate) ?? focusedDate
    }
}

struct WeekCalendarGrid: View {
    var focusedDate: Date
    var events: [CronCalendarEvent]

    private var days: [Date] {
        let calendar = Calendar.current
        let start = calendar.dateInterval(of: .weekOfYear, for: focusedDate)?.start ?? focusedDate
        return (0..<7).compactMap { calendar.date(byAdding: .day, value: $0, to: start) }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(days, id: \.self) { day in
                WeekDayColumn(
                    day: day,
                    events: events(on: day)
                )
                .frame(maxWidth: .infinity)
                if day != days.last {
                    Divider()
                }
            }
        }
        .frame(minHeight: 420, alignment: .top)
    }

    private func events(on day: Date) -> [CronCalendarEvent] {
        events
            .filter { Calendar.current.isDate($0.date, inSameDayAs: day) }
            .sorted { $0.date < $1.date }
    }
}

struct WeekDayColumn: View {
    var day: Date
    var events: [CronCalendarEvent]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(weekday)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(dayNumber)
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(isToday ? .white : ElephantTheme.ink)
                        .padding(.horizontal, isToday ? 8 : 0)
                        .padding(.vertical, isToday ? 4 : 0)
                        .background(isToday ? ElephantTheme.accent : Color.clear, in: Capsule())
                    if !events.isEmpty {
                        Text("\(events.count)")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(ElephantTheme.muted)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if events.isEmpty {
                Rectangle()
                    .fill(ElephantTheme.line.opacity(0.34))
                    .frame(height: 1)
                    .padding(.top, 4)
                Spacer(minLength: 0)
            } else {
                VStack(alignment: .leading, spacing: 7) {
                    ForEach(events) { event in
                        CalendarEventPill(
                            event: event,
                            compact: false
                        )
                    }
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(isToday ? ElephantTheme.accent.opacity(0.06) : Color.clear)
    }

    private var weekday: String {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.dateFormat = "EEE"
        return formatter.string(from: day)
    }

    private var dayNumber: String {
        "\(Calendar.current.component(.day, from: day))"
    }

    private var isToday: Bool {
        Calendar.current.isDateInToday(day)
    }
}

struct MonthCalendarGrid: View {
    var focusedDate: Date
    var events: [CronCalendarEvent]

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 0), count: 7)

    private var days: [Date] {
        Self.monthGridDates(for: focusedDate)
    }

    var body: some View {
        VStack(spacing: 0) {
            LazyVGrid(columns: columns, spacing: 0) {
                ForEach(Self.weekdaySymbols, id: \.self) { symbol in
                    Text(symbol)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.muted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 9)
                        .padding(.bottom, 8)
                }
            }

            LazyVGrid(columns: columns, spacing: 0) {
                ForEach(days, id: \.self) { day in
                    MonthDayCell(
                        day: day,
                        inFocusedMonth: Calendar.current.isDate(day, equalTo: focusedDate, toGranularity: .month),
                        events: events(on: day)
                    )
                }
            }
        }
    }

    private func events(on day: Date) -> [CronCalendarEvent] {
        events
            .filter { Calendar.current.isDate($0.date, inSameDayAs: day) }
            .sorted { $0.date < $1.date }
    }

    private static var weekdaySymbols: [String] {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        return formatter.shortStandaloneWeekdaySymbols
    }

    static func monthGridDates(for date: Date) -> [Date] {
        let calendar = Calendar.current
        let monthStart = calendar.dateInterval(of: .month, for: date)?.start ?? date
        let monthEnd = calendar.date(byAdding: DateComponents(month: 1, day: -1), to: monthStart) ?? monthStart
        let gridStart = calendar.dateInterval(of: .weekOfMonth, for: monthStart)?.start ?? monthStart
        let gridEnd = calendar.dateInterval(of: .weekOfMonth, for: monthEnd)?.end ?? monthEnd

        var days: [Date] = []
        var cursor = gridStart
        while cursor < gridEnd {
            days.append(cursor)
            cursor = calendar.date(byAdding: .day, value: 1, to: cursor) ?? cursor
        }
        while days.count < 42 {
            guard let next = calendar.date(byAdding: .day, value: 1, to: days.last ?? monthEnd) else { break }
            days.append(next)
        }
        return days
    }
}

struct MonthDayCell: View {
    var day: Date
    var inFocusedMonth: Bool
    var events: [CronCalendarEvent]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("\(Calendar.current.component(.day, from: day))")
                    .font(.callout.weight(isToday ? .bold : .semibold))
                    .foregroundStyle(dayColor)
                    .padding(.horizontal, isToday ? 7 : 0)
                    .padding(.vertical, isToday ? 3 : 0)
                    .background(isToday ? ElephantTheme.accent : Color.clear, in: Capsule())
                Spacer(minLength: 0)
            }

            ForEach(events.prefix(3)) { event in
                CalendarEventPill(
                    event: event,
                    compact: true
                )
            }

            if events.count > 3 {
                Text("+ \(events.count - 3) more")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
            }
            Spacer(minLength: 0)
        }
        .padding(8)
        .frame(minHeight: 92, alignment: .topLeading)
        .background(isToday ? ElephantTheme.accent.opacity(0.05) : Color(nsColor: .textBackgroundColor).opacity(inFocusedMonth ? 0.44 : 0.18))
        .overlay(
            Rectangle()
                .stroke(ElephantTheme.line.opacity(0.72), lineWidth: 0.5)
        )
    }

    private var isToday: Bool {
        Calendar.current.isDateInToday(day)
    }

    private var dayColor: Color {
        if isToday { return .white }
        return inFocusedMonth ? ElephantTheme.ink : ElephantTheme.faint
    }
}

struct YearCalendarGrid: View {
    var focusedDate: Date
    var events: [CronCalendarEvent]

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 16), count: 3)

    var body: some View {
        LazyVGrid(columns: columns, alignment: .leading, spacing: 16) {
            ForEach(monthStarts, id: \.self) { month in
                MiniMonthCalendar(month: month, events: events(in: month))
            }
        }
    }

    private var monthStarts: [Date] {
        let calendar = Calendar.current
        let year = calendar.component(.year, from: focusedDate)
        return (1...12).compactMap { month in
            calendar.date(from: DateComponents(year: year, month: month, day: 1))
        }
    }

    private func events(in month: Date) -> [CronCalendarEvent] {
        events.filter { Calendar.current.isDate($0.date, equalTo: month, toGranularity: .month) }
    }
}

struct MiniMonthCalendar: View {
    var month: Date
    var events: [CronCalendarEvent]

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 4), count: 7)

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(monthTitle)
                    .font(.headline)
                    .foregroundStyle(ElephantTheme.ink)
                Spacer()
                if !events.isEmpty {
                    Pill(text: "\(events.count)", symbol: "calendar", tint: ElephantTheme.accent)
                }
            }

            LazyVGrid(columns: columns, spacing: 6) {
                ForEach(Self.weekdaySymbols, id: \.self) { symbol in
                    Text(symbol)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(ElephantTheme.faint)
                }
                ForEach(MonthCalendarGrid.monthGridDates(for: month), id: \.self) { day in
                    let dayEvents = events(on: day)
                    MiniMonthDay(
                        day: day,
                        inMonth: Calendar.current.isDate(day, equalTo: month, toGranularity: .month),
                        eventCount: dayEvents.count,
                        event: dayEvents.first
                    )
                }
            }
        }
        .padding(12)
        .background(Color(nsColor: .textBackgroundColor).opacity(0.58), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(ElephantTheme.line, lineWidth: 1)
        )
    }

    private var monthTitle: String {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.dateFormat = "MMMM"
        return formatter.string(from: month)
    }

    private func events(on day: Date) -> [CronCalendarEvent] {
        events.filter { Calendar.current.isDate($0.date, inSameDayAs: day) }
    }

    private static var weekdaySymbols: [String] {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        return formatter.veryShortStandaloneWeekdaySymbols
    }
}

struct MiniMonthDay: View {
    var day: Date
    var inMonth: Bool
    var eventCount: Int
    var event: CronCalendarEvent?
    @State private var showingDetail = false

    var body: some View {
        Button {
            if event != nil {
                showingDetail = true
            }
        } label: {
            VStack(spacing: 2) {
                Text("\(Calendar.current.component(.day, from: day))")
                    .font(.caption.weight(isToday || showingDetail ? .bold : .medium))
                    .foregroundStyle(dayColor)
                    .frame(width: 24, height: 20)
                    .background(isToday ? ElephantTheme.accent : showingDetail ? ElephantTheme.accent.opacity(0.14) : Color.clear, in: Capsule())
                Capsule()
                    .fill(eventCount > 0 ? ElephantTheme.accent.opacity(showingDetail ? 0.95 : 0.58) : Color.clear)
                    .frame(width: eventCount > 1 ? 12 : 5, height: 3)
            }
        }
        .buttonStyle(.plain)
        .disabled(eventCount == 0)
        .opacity(inMonth ? 1 : 0.42)
        .popover(isPresented: $showingDetail, arrowEdge: .bottom) {
            if let event {
                CalendarEventPopover(event: event)
            }
        }
    }

    private var isToday: Bool {
        Calendar.current.isDateInToday(day)
    }

    private var dayColor: Color {
        if isToday { return .white }
        return inMonth ? ElephantTheme.ink : ElephantTheme.faint
    }
}

struct CalendarEventPill: View {
    var event: CronCalendarEvent
    var compact: Bool
    @State private var showingDetail = false

    var body: some View {
        Button {
            showingDetail = true
        } label: {
            HStack(spacing: 6) {
                Capsule()
                    .fill(event.tint)
                    .frame(width: compact ? 18 : 26, height: compact ? 3 : 4)
                Text(label)
                    .font(compact ? .caption2.weight(.semibold) : .caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink.opacity(compact ? 0.78 : 0.9))
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: 0)
                if !compact {
                    Text(event.job.status)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(event.tint)
                        .lineLimit(1)
                }
            }
            .padding(.horizontal, compact ? 4 : 6)
            .padding(.vertical, compact ? 2 : 4)
            .background(showingDetail ? event.tint.opacity(0.12) : Color.clear, in: RoundedRectangle(cornerRadius: 5, style: .continuous))
            .contentShape(RoundedRectangle(cornerRadius: 5, style: .continuous))
        }
        .buttonStyle(PressablePlainButtonStyle())
        .help(helpText)
        .popover(isPresented: $showingDetail, arrowEdge: .bottom) {
            CalendarEventPopover(event: event)
        }
    }

    private var label: String {
        "\(event.timeText) \(event.job.title)"
    }

    private var helpText: String {
        [
            event.job.title,
            event.job.schedule,
            event.job.detail,
            event.job.isSystem ? "System reminder" : "User reminder"
        ]
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
    }
}

struct CalendarEventPopover: View {
    @EnvironmentObject private var model: ElephantAppModel
    var event: CronCalendarEvent

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(event.tint.opacity(0.12))
                    Image(systemName: event.job.isSystem ? "gearshape.2" : "calendar.badge.clock")
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(event.tint)
                }
                .frame(width: 42, height: 42)

                VStack(alignment: .leading, spacing: 4) {
                    Text(event.job.title)
                        .font(.headline)
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(2)
                    Text(event.job.isSystem ? "System learning reminder" : "Reminder")
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                }

                Spacer(minLength: 8)
                Pill(text: event.job.status, tint: event.tint)
            }

            VStack(spacing: 0) {
                popoverRow("Next run", formattedDate(event.date))
                Divider()
                popoverRow("When", event.job.schedule.isEmpty ? "n/a" : event.job.schedule)
                Divider()
                popoverRow("Runs", "\(event.job.runCount)")
            }
            .background(ElephantTheme.panel.opacity(0.55), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))

            if !event.job.detail.isEmpty {
                Text(event.job.detail)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(4)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: 8) {
                Button("Run") { Task { await model.runCronJob(event.job) } }
                    .disabled(!event.job.canRunNow)
                Button(event.job.status == "paused" ? "Resume" : "Pause") {
                    Task { await model.setCronJob(event.job, paused: event.job.status != "paused") }
                }
                .disabled(!event.job.canPause)
                Button("Delete") { Task { await model.deleteCronJob(event.job) } }
                    .disabled(!event.job.canDelete)
                Spacer(minLength: 0)
            }
            .controlSize(.small)
        }
        .padding(16)
        .frame(width: 340, alignment: .leading)
    }

    private func popoverRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(label)
                .font(.caption.weight(.semibold))
                .foregroundStyle(ElephantTheme.muted)
                .frame(width: 72, alignment: .leading)
            Text(value)
                .font(.caption)
                .foregroundStyle(ElephantTheme.ink)
                .lineLimit(2)
                .truncationMode(.middle)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
    }

    private func formattedDate(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }
}

struct ReminderComposerLauncher: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var showingComposer = false
    @State private var name = "Daily Elephant reminder"
    @State private var schedule = "daily at 09:00"
    @State private var prompt = "Review current priorities and suggest the next grounded step."

    var body: some View {
        NativePanel {
            HStack(alignment: .center, spacing: 14) {
                ZStack {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(ElephantTheme.accent.opacity(0.10))
                    Image(systemName: "bell.badge")
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(ElephantTheme.accent)
                }
                .frame(width: 42, height: 42)

                SectionLabel(
                    title: "Reminders",
                    subtitle: "Ask Elephant to remind you or do something later."
                )

                Spacer(minLength: 16)

                if !model.cronActionResult.isEmpty {
                    Label(model.cronActionResult, systemImage: "checkmark.circle.fill")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.green)
                        .lineLimit(2)
                }

                Button {
                    showingComposer = true
                } label: {
                    Label("New Reminder", systemImage: "plus")
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(ElephantTheme.accent)
                .popover(isPresented: $showingComposer, arrowEdge: .bottom) {
                    reminderComposer
                }
            }
        }
    }

    private var reminderComposer: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(ElephantTheme.accent.opacity(0.10))
                    Image(systemName: "bell.badge")
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(ElephantTheme.accent)
                }
                .frame(width: 42, height: 42)

                VStack(alignment: .leading, spacing: 4) {
                    Text("New Reminder")
                        .font(.headline)
                        .foregroundStyle(ElephantTheme.ink)
                    Text("Choose when and what Elephant should do.")
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                }
                Spacer(minLength: 0)
            }

            VStack(alignment: .leading, spacing: 10) {
                labeledField("Title") {
                    TextField("Daily Elephant reminder", text: $name)
                        .textFieldStyle(.roundedBorder)
                }
                labeledField("When") {
                    TextField("daily at 09:00", text: $schedule)
                        .textFieldStyle(.roundedBorder)
                }
                labeledField("What should Elephant do?") {
                    TextField("Review priorities and suggest the next grounded step.", text: $prompt, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(3...5)
                }
            }

            HStack(spacing: 8) {
                Button("Cancel") {
                    showingComposer = false
                }
                Spacer(minLength: 0)
                Button {
                    Task {
                        await model.createCronJob(name: name, schedule: schedule, prompt: prompt)
                        await MainActor.run { showingComposer = false }
                    }
                } label: {
                    Label("Create Reminder", systemImage: "plus")
                }
                .buttonStyle(.borderedProminent)
                .tint(ElephantTheme.accent)
                .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(16)
        .frame(width: 420, alignment: .leading)
    }

    private func labeledField<Content: View>(_ label: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label)
                .font(.caption.weight(.semibold))
                .foregroundStyle(ElephantTheme.muted)
            content()
        }
    }
}

struct CalendarJobsPanel: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var page = 0

    private let pageSize = 6

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    SectionLabel(title: "All Reminders", subtitle: "\(jobs.count) reminder(s)")
                    Spacer(minLength: 12)
                    if !jobs.isEmpty {
                        Text("Page \(safePage + 1) of \(pageCount)")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(ElephantTheme.muted)
                        HStack(spacing: 6) {
                            Button {
                                page = max(0, safePage - 1)
                            } label: {
                                Image(systemName: "chevron.left")
                                    .frame(width: 24, height: 22)
                            }
                            .buttonStyle(PressablePlainButtonStyle())
                            .disabled(safePage == 0)
                            .help("Previous reminders page")

                            Button {
                                page = min(pageCount - 1, safePage + 1)
                            } label: {
                                Image(systemName: "chevron.right")
                                    .frame(width: 24, height: 22)
                            }
                            .buttonStyle(PressablePlainButtonStyle())
                            .disabled(safePage >= pageCount - 1)
                            .help("Next reminders page")
                        }
                    }
                }

                if jobs.isEmpty {
                    EmptyLine(symbol: "calendar.badge.clock", text: "No reminders yet.")
                } else {
                    VStack(spacing: 0) {
                        HStack(spacing: 12) {
                            tableHeader("Reminder")
                            tableHeader("When")
                                .frame(width: 220, alignment: .leading)
                            tableHeader("Next")
                                .frame(width: 210, alignment: .leading)
                            Text("")
                                .frame(width: 164)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(ElephantTheme.panel.opacity(0.52))

                        ForEach(pageJobs) { job in
                            CronJobRow(job: job)
                            if job.id != pageJobs.last?.id {
                                Divider()
                            }
                        }
                    }
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))
                }
            }
        }
    }

    private var jobs: [CronJobItem] {
        model.snapshot.cronItems.sorted { lhs, rhs in
            if lhs.isSystem != rhs.isSystem {
                return !lhs.isSystem && rhs.isSystem
            }
            return lhs.title.localizedCaseInsensitiveCompare(rhs.title) == .orderedAscending
        }
    }

    private var pageCount: Int {
        max(Int(ceil(Double(jobs.count) / Double(pageSize))), 1)
    }

    private var safePage: Int {
        min(max(page, 0), pageCount - 1)
    }

    private var pageJobs: [CronJobItem] {
        let start = safePage * pageSize
        return Array(jobs.dropFirst(start).prefix(pageSize))
    }

    private func tableHeader(_ text: String) -> some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .foregroundStyle(ElephantTheme.muted)
            .textCase(.uppercase)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct CronJobSection: View {
    var title: String
    var jobs: [CronJobItem]

    var body: some View {
        if !jobs.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                    .textCase(.uppercase)
                ForEach(jobs) { job in
                    CronJobRow(job: job)
                    if job.id != jobs.last?.id {
                        Divider()
                    }
                }
            }
        }
    }
}

struct CronJobRow: View {
    @EnvironmentObject private var model: ElephantAppModel
    var job: CronJobItem

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: 12) {
                jobIdentity

                VStack(alignment: .leading, spacing: 3) {
                    Text(job.schedule.isEmpty ? "No time set" : job.schedule)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                    Text(job.detail.isEmpty ? "No reminder detail" : job.detail)
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(2)
                }
                .frame(width: 220, alignment: .leading)

                VStack(alignment: .leading, spacing: 3) {
                    Text(job.nextRun.isEmpty ? "Not planned" : job.nextRun)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Text("Last \(job.lastRun.isEmpty ? "not yet" : job.lastRun) · \(job.runCount) run(s)")
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.faint)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                .frame(width: 210, alignment: .leading)

                jobActions
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)

            VStack(alignment: .leading, spacing: 8) {
                jobIdentity
                Text([job.schedule, job.detail].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(3)
                Text("Next \(job.nextRun.isEmpty ? "not planned" : job.nextRun) · Last \(job.lastRun.isEmpty ? "not yet" : job.lastRun) · \(job.runCount) run(s)")
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.faint)
                    .lineLimit(2)
                jobActions
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
        }
    }

    private var jobIdentity: some View {
        HStack(alignment: .top, spacing: 10) {
            StatusDot(tint: statusTint)
                .padding(.top, 5)
            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline, spacing: 7) {
                    Text(job.title)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                    if job.isSystem {
                        Pill(text: "system", symbol: "gearshape", tint: ElephantTheme.green)
                    }
                    Pill(text: job.status, tint: statusTint)
                }
                Text(job.id)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.faint)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var jobActions: some View {
        HStack(spacing: 6) {
            Button("Run") { Task { await model.runCronJob(job) } }
                .disabled(!job.canRunNow)
            Button(job.status == "paused" ? "Resume" : "Pause") {
                Task { await model.setCronJob(job, paused: job.status != "paused") }
            }
            .disabled(!job.canPause)
            Button("Delete") { Task { await model.deleteCronJob(job) } }
                .disabled(!job.canDelete)
        }
        .controlSize(.small)
        .frame(width: 164, alignment: .trailing)
    }

    private var statusTint: Color {
        job.status == "paused" ? ElephantTheme.orange : ElephantTheme.green
    }
}

struct LearnView: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "Learn",
                subtitle: "Background reflect jobs, diary learning, and memory consolidation.",
                actionTitle: model.isReflecting ? "Learning" : "Run Learn",
                actionSymbol: "brain.head.profile"
            ) {
                Task { await model.runReflect(trigger: "learn") }
            }

            HStack(spacing: 12) {
                MetricTile(label: "Questions", value: "\(model.snapshot.waitingQuestions)", symbol: "questionmark.bubble", tint: ElephantTheme.orange)
                MetricTile(label: "Worker", value: model.snapshot.workerStatus, symbol: "gearshape.2", tint: ElephantTheme.accent)
                MetricTile(label: "Jobs", value: "\(model.snapshot.learningItems.count)", symbol: "brain.head.profile", tint: ElephantTheme.green)
            }

            LearnControlsPanel()

            NativePanel {
                VStack(alignment: .leading, spacing: 14) {
                    SectionLabel(title: "Learn History", subtitle: "\(model.snapshot.learningItems.count) job(s)")
                    if model.snapshot.learningItems.isEmpty {
                        EmptyLine(symbol: "brain.head.profile", text: "No learning jobs returned yet.")
                    } else {
                        LearningJobSection(title: "Active", items: Array(model.snapshot.learningItems.filter { !$0.status.lowercased().contains("completed") && !$0.status.lowercased().contains("failed") }.prefix(8)))
                        LearningJobSection(title: "Completed", items: Array(model.snapshot.learningItems.filter { $0.status.lowercased().contains("completed") }.prefix(10)))
                        LearningJobSection(title: "Needs Attention", items: Array(model.snapshot.learningItems.filter { $0.status.lowercased().contains("failed") || $0.status.lowercased().contains("cancel") }.prefix(8)))
                    }
                }
            }
        }
    }
}

struct LearnControlsPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    private let actions = [
        LearnActionSpec(
            id: "reflect",
            title: "Reflect",
            subtitle: "Review conversations, questions, and evidence into memory.",
            symbol: "brain.head.profile",
            tint: ElephantTheme.accent,
            trigger: "manual",
            features: nil
        ),
        LearnActionSpec(
            id: "dream",
            title: "Dream",
            subtitle: "Look for quiet patterns, loose threads, and useful next questions.",
            symbol: "moon.stars",
            tint: ElephantTheme.green,
            trigger: "dream",
            features: "dream"
        ),
        LearnActionSpec(
            id: "diary",
            title: "Diary",
            subtitle: "Write a reflective entry from recent reviewed context.",
            symbol: "book.closed",
            tint: ElephantTheme.orange,
            trigger: "diary",
            features: "diary"
        )
    ]

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top, spacing: 14) {
                    SectionLabel(
                        title: "New Reflect Job",
                        subtitle: "Start a focused background pass when memory needs to catch up."
                    )
                    Spacer(minLength: 12)
                    statusSummary
                }

                LazyVGrid(columns: columns, spacing: 12) {
                    ForEach(actions) { action in
                        LearnActionButton(action: action, disabled: model.isReflecting) {
                            Task { await model.runReflect(trigger: action.trigger, features: action.features) }
                        }
                    }
                }

                HStack(spacing: 10) {
                    Image(systemName: model.isReflecting ? "arrow.triangle.2.circlepath" : "checkmark.circle")
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(model.isReflecting ? ElephantTheme.accent : latestTint)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(model.isReflecting ? "Learning job is running" : "Last completed")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(ElephantTheme.ink)
                        Text(latestCompletedText)
                            .font(.caption)
                            .foregroundStyle(ElephantTheme.muted)
                            .lineLimit(1)
                            .truncationMode(.middle)
                            .textSelection(.enabled)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(ElephantTheme.canvas.opacity(0.74), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line.opacity(0.72), lineWidth: 1))
            }
        }
    }

    private var columns: [GridItem] {
        [
            GridItem(.flexible(), spacing: 12),
            GridItem(.flexible(), spacing: 12),
            GridItem(.flexible(), spacing: 12)
        ]
    }

    @ViewBuilder
    private var statusSummary: some View {
        if model.isReflecting {
            Pill(text: "running", symbol: "arrow.triangle.2.circlepath", tint: ElephantTheme.accent)
        } else {
            Pill(text: latestBadgeText, symbol: latestCompletedDate == nil ? "clock" : "checkmark", tint: latestTint)
        }
    }

    private var latestTint: Color {
        latestCompletedDate == nil ? ElephantTheme.muted : ElephantTheme.green
    }

    private var latestBadgeText: String {
        latestCompletedDate == nil ? "not run yet" : "ready"
    }

    private var latestCompletedText: String {
        guard let date = latestCompletedDate else {
            return "No completed reflect job has been reported yet."
        }
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }

    private var latestCompletedDate: Date? {
        ReflectTimestamp.parse(model.snapshot.latestCompletedAt)
    }
}

private struct LearnActionSpec: Identifiable {
    var id: String
    var title: String
    var subtitle: String
    var symbol: String
    var tint: Color
    var trigger: String
    var features: String?
}

private struct LearnActionButton: View {
    var action: LearnActionSpec
    var disabled: Bool
    var onRun: () -> Void

    var body: some View {
        Button(action: onRun) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: action.symbol)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(action.tint)
                    .frame(width: 28, height: 28)
                    .background(action.tint.opacity(0.10), in: RoundedRectangle(cornerRadius: 7, style: .continuous))

                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 6) {
                        Text(action.title)
                            .font(.callout.weight(.semibold))
                            .foregroundStyle(ElephantTheme.ink)
                        Spacer(minLength: 0)
                        Image(systemName: "plus")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(action.tint)
                    }
                    Text(action.subtitle)
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(12)
            .frame(minHeight: 88, maxHeight: .infinity, alignment: .topLeading)
            .background(action.tint.opacity(disabled ? 0.035 : 0.055), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(action.tint.opacity(disabled ? 0.12 : 0.24), lineWidth: 1)
            )
            .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .opacity(disabled ? 0.54 : 1)
        .help(disabled ? "A learning job is already running." : "Create \(action.title) reflect job")
        .accessibilityLabel("Create \(action.title) reflect job")
    }
}

private enum ReflectTimestamp {
    static func parse(_ raw: String) -> Date? {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }

        let candidates = [
            text,
            text.replacingOccurrences(
                of: #"(\.\d{3})\d+(?=Z|[+-]\d{2}:?\d{2})"#,
                with: "$1",
                options: .regularExpression
            )
        ]

        for candidate in candidates {
            let fractional = ISO8601DateFormatter()
            fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = fractional.date(from: candidate) { return date }

            let plain = ISO8601DateFormatter()
            plain.formatOptions = [.withInternetDateTime]
            if let date = plain.date(from: candidate) { return date }
        }

        for pattern in ["yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd"] {
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.dateFormat = pattern
            if let date = formatter.date(from: text) { return date }
        }
        return nil
    }
}

struct LearningJobSection: View {
    var title: String
    var items: [LearningJobItem]

    var body: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                    .textCase(.uppercase)
                ForEach(items) { item in
                    LearningJobRow(item: item)
                    if item.id != items.last?.id {
                        Divider()
                    }
                }
            }
        }
    }
}

struct LearningJobRow: View {
    var item: LearningJobItem

    var body: some View {
        DisclosureGroup {
            if item.markdown.isEmpty {
                Text("No rendered result returned yet.")
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.muted)
                    .padding(.top, 6)
            } else {
                MarkdownBody(text: item.markdown, font: .callout, color: ElephantTheme.ink)
                    .padding(.top, 6)
            }
        } label: {
            HStack(alignment: .top, spacing: 12) {
                StatusDot(tint: statusTint)
                    .padding(.top, 6)
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.title)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                    Text([item.trigger, item.detail].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(2)
                }
                Spacer()
                Pill(text: item.status, tint: statusTint)
            }
        }
        .padding(.vertical, 7)
    }

    private var statusTint: Color {
        let status = item.status.lowercased()
        if status.contains("completed") { return ElephantTheme.green }
        if status.contains("failed") || status.contains("cancel") { return ElephantTheme.orange }
        return ElephantTheme.accent
    }
}

struct SourcesView: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "Sources",
                subtitle: "Point Elephant at folders, repos, notes, and docs.",
                actionTitle: "Add Source",
                actionSymbol: "folder.badge.plus"
            ) {
                Task { await model.pickSources() }
            }

            NativePanel {
                VStack(alignment: .leading, spacing: 16) {
                    SectionLabel(title: "Knowledge Vaults", subtitle: "\(model.stagedSources.count) staged")

                    if model.stagedSources.isEmpty {
                        EmptyLine(symbol: "folder", text: "No vaults yet. Add one above to start ingesting a folder.")
                    } else {
                        ForEach(model.stagedSources) { scan in
                            SourceScanRow(scan: scan) {
                                model.revealSource(scan)
                            }
                            if scan.id != model.stagedSources.last?.id {
                                Divider()
                            }
                        }
                    }
                }
            }

            HStack(spacing: 12) {
                MetricTile(label: "Scanned", value: "\(model.stagedSources.reduce(0) { $0 + $1.scanned })", symbol: "doc.text.magnifyingglass")
                MetricTile(label: "Admitted", value: "\(model.stagedSources.reduce(0) { $0 + $1.admitted })", symbol: "checkmark.seal", tint: ElephantTheme.green)
                MetricTile(label: "Skipped", value: "\(model.stagedSources.reduce(0) { $0 + $1.skipped })", symbol: "exclamationmark.triangle", tint: ElephantTheme.orange)
            }
        }
    }
}

struct SourceScanRow: View {
    var scan: SourceScan
    var reveal: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                Image(systemName: "folder")
                    .foregroundStyle(ElephantTheme.accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(scan.rootPath)
                        .font(.headline)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Text("\(scan.admitted) admitted of \(scan.scanned) scanned")
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                }
                Spacer(minLength: 0)
                Button("Reveal", action: reveal)
            }

            if !scan.samples.isEmpty {
                FlowLayout(items: scan.samples)
            }
        }
        .padding(.vertical, 7)
    }
}

struct SettingsView: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: "Settings",
                subtitle: "Real local controls that do not need to live in the main sidebar.",
                actionTitle: "Restart Core",
                actionSymbol: "arrow.clockwise"
            ) {
                Task { await model.restartCore() }
            }

            NativePanel {
                VStack(spacing: 0) {
                    ExpandableSettingsRow(
                        symbol: "slider.horizontal.3",
                        title: "Runtime Config",
                        subtitle: model.snapshot.settingsPath.isEmpty ? "global config not resolved" : model.snapshot.settingsPath
                    ) {
                        RuntimeConfigSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "questionmark.bubble",
                        title: "Curiosity",
                        subtitle: "\(model.snapshot.waitingQuestions) open Personal Model questions"
                    ) {
                        CuriositySettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "clock.arrow.circlepath",
                        title: "History",
                        subtitle: "\(model.snapshot.episodes) episodes · \(model.snapshot.loops) loops · \(model.snapshot.steps) steps"
                    ) {
                        HistoryUsageSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "stethoscope",
                        title: "Logs & Diagnostics",
                        subtitle: "\(model.snapshot.logs) local log files"
                    ) {
                        LogsDiagnosticsSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "folder.badge.plus",
                        title: "Sources",
                        subtitle: "\(model.stagedSources.count) vaults staged"
                    ) {
                            SourcesSummaryPanel()
                    }
                    ExpandableSettingsRow(
                        symbol: "terminal",
                        title: "Advanced Runtime",
                        subtitle: model.snapshot.apiURL.isEmpty ? model.corePhase.label : model.snapshot.apiURL
                    ) {
                        RuntimeSettingsContent()
                    }
                }
            }

            if !model.lastError.isEmpty {
                NativePanel {
                    VStack(alignment: .leading, spacing: 8) {
                        SectionLabel(title: "Last Error")
                        Text(model.lastError)
                            .font(.callout)
                            .foregroundStyle(ElephantTheme.orange)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }

    private func abbreviatedCount(_ value: Int) -> String {
        if value >= 1_000_000 {
            return String(format: "%.1fM", Double(value) / 1_000_000.0)
        }
        if value >= 1_000 {
            return String(format: "%.1fK", Double(value) / 1_000.0)
        }
        return "\(value)"
    }

    private var providerSubtitle: String {
        if model.snapshot.providerModelID.isEmpty {
            return model.snapshot.providerID.isEmpty ? "Provider setup needed" : model.snapshot.providerID
        }
        return "\(model.snapshot.providerID) · \(model.snapshot.providerModelID)"
    }
}

struct ExpandableSettingsRow<Content: View>: View {
    var symbol: String
    var title: String
    var subtitle: String
    var content: Content
    @State private var expanded = false

    init(
        symbol: String,
        title: String,
        subtitle: String,
        @ViewBuilder content: () -> Content
    ) {
        self.symbol = symbol
        self.title = title
        self.subtitle = subtitle
        self.content = content()
    }

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            content
                .padding(.leading, 44)
                .padding(.trailing, 4)
                .padding(.bottom, 16)
                .padding(.top, 2)
        } label: {
            HStack(spacing: 18) {
                Image(systemName: symbol)
                    .font(.title3)
                    .foregroundStyle(ElephantTheme.muted)
                    .frame(width: 26)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.headline)
                        .foregroundStyle(ElephantTheme.ink)
                    Text(subtitle)
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .padding(.vertical, 14)
            .contentShape(Rectangle())
        }
        .disclosureGroupStyle(.automatic)
        Divider()
    }
}

struct ProviderSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var providerID = ""
    @State private var baseURL = ""
    @State private var modelID = ""
    @State private var apiKey = ""
    @State private var contextWindow = ""
    @State private var discoveredModels: [String: [ProviderModelOption]] = [:]
    @State private var loadingModels = false
    @State private var loaded = false
    @State private var autoFetchedProviderID = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Pill(text: providerStatusLabel, symbol: "cpu", tint: providerTint)
                if !model.providerTestResult.isEmpty {
                    Text(model.providerTestResult)
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.green)
                }
                Spacer(minLength: 0)
            }

            if model.snapshot.providerOptions.isEmpty {
                LabeledContent("Provider ID") {
                    TextField("openai-compatible", text: $providerID)
                        .textFieldStyle(.roundedBorder)
                }
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    SectionLabel(title: "Provider", subtitle: "Click anywhere on a provider row to switch the draft.")
                    ScrollView {
                        VStack(spacing: 8) {
                            ForEach(providerSections, id: \.title) { section in
                                ProviderSectionBlock(
                                    title: section.title,
                                    options: section.options,
                                    selectedID: providerID
                                ) { option in
                                    providerID = option.id
                                    applyProviderDefaults(onlyWhenEmpty: false)
                                    Task { await loadLiveModels(force: true) }
                                }
                            }
                        }
                    }
                    .frame(maxHeight: 330)
                    .scrollIndicators(.visible)
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    SectionLabel(title: "Model", subtitle: selectedOption?.active == true ? "Active model for the current provider" : "Select a catalog hint, live-discovered model, or type a custom ID.")
                    Spacer()
                    Button {
                        Task { await loadLiveModels() }
                    } label: {
                        Label(loadingModels ? "Fetching" : "Fetch models", systemImage: "arrow.clockwise")
                    }
                    .disabled(providerID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || loadingModels)
                    .controlSize(.small)
                }

                ModelOptionPicker(
                    options: availableModels,
                    selectedID: $modelID,
                    loading: loadingModels,
                    activeModelID: model.snapshot.providerModelID
                )

                LabeledContent("Custom model") {
                    TextField("model id", text: $modelID)
                        .textFieldStyle(.roundedBorder)
                }
            }
            .padding(12)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))

            LabeledContent("Base URL") {
                TextField("optional endpoint", text: $baseURL)
                    .textFieldStyle(.roundedBorder)
            }
            LabeledContent("API Key") {
                SecureField("stored locally", text: $apiKey)
                    .textFieldStyle(.roundedBorder)
            }
            LabeledContent("Context Window") {
                TextField("auto", text: $contextWindow)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 160)
            }

            SettingsRow(label: "Source", value: model.snapshot.providerSource.isEmpty ? "not configured" : model.snapshot.providerSource)
            SettingsRow(label: "Embedding", value: embeddingLine)

            HStack {
                Button("Save Provider") {
                    Task {
                        await model.saveProviderSettings(
                            providerID: providerID,
                            baseURL: baseURL,
                            modelID: modelID,
                            apiKey: apiKey,
                            contextWindow: contextWindow
                        )
                    }
                }
                .disabled(providerID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                Button("Test") {
                    Task { await model.testProvider() }
                }
                .disabled(model.snapshot.providerID.isEmpty && providerID.isEmpty)

                Button("Refresh") {
                    Task { try? await model.refreshDashboard() }
                }
            }
        }
        .onAppear {
            guard !loaded else { return }
            loadFromSnapshot()
            loaded = true
            Task { await loadLiveModelsIfNeeded() }
        }
        .onChange(of: model.snapshot.providerID) { _ in
            loadFromSnapshot()
            Task { await loadLiveModelsIfNeeded() }
        }
    }

    private var selectedOption: ProviderOption? {
        model.snapshot.providerOptions.first(where: { $0.id == providerID })
    }

    private var availableModels: [ProviderModelOption] {
        discoveredModels[providerID] ?? selectedOption?.models ?? []
    }

    private var providerSections: [(title: String, options: [ProviderOption])] {
        let oauth = model.snapshot.providerOptions.filter { option in
            let auth = option.authKind.lowercased()
            return auth.contains("oauth") || ["openai-codex", "qwen-oauth", "claude-code", "anthropic", "copilot"].contains(option.id)
        }
        let api = model.snapshot.providerOptions.filter { option in
            !oauth.contains(where: { $0.id == option.id })
        }
        return [
            ("Connected and OAuth", oauth),
            ("API key and local endpoints", api)
        ].filter { !$0.options.isEmpty }
    }

    private var providerStatusLabel: String {
        if model.snapshot.providerStatus == "unknown", !model.snapshot.providerID.isEmpty {
            return "configured"
        }
        return model.snapshot.providerStatus == "unknown" ? "setup needed" : model.snapshot.providerStatus
    }

    private var providerTint: Color {
        let value = providerStatusLabel.lowercased()
        return value.contains("setup") || value.contains("missing") ? ElephantTheme.orange : ElephantTheme.green
    }

    private var embeddingLine: String {
        let status = model.snapshot.embeddingStatus.isEmpty ? model.snapshot.semanticStatus : model.snapshot.embeddingStatus
        let runtime = model.snapshot.embeddingRuntimeState.trimmingCharacters(in: .whitespacesAndNewlines)
        let suffix = runtime.isEmpty ? status : "\(status) · \(runtime)"
        if model.snapshot.embeddingProviderID.isEmpty {
            return suffix
        }
        return "\(model.snapshot.embeddingProviderID) · \(suffix)"
    }

    private func loadFromSnapshot() {
        providerID = model.snapshot.providerID.isEmpty
            ? (model.snapshot.providerOptions.first?.id ?? "openai-compatible")
            : model.snapshot.providerID
        modelID = model.snapshot.providerModelID
        baseURL = model.snapshot.providerBaseURL
        contextWindow = ""
        apiKey = ""
        applyProviderDefaults(onlyWhenEmpty: true)
    }

    private func applyProviderDefaults(onlyWhenEmpty: Bool = false) {
        guard let option = model.snapshot.providerOptions.first(where: { $0.id == providerID }) else { return }
        if !onlyWhenEmpty || modelID.isEmpty {
            modelID = option.defaultModel.isEmpty ? (option.models.first?.id ?? modelID) : option.defaultModel
        }
        if !onlyWhenEmpty || baseURL.isEmpty {
            baseURL = option.defaultBaseURL
        }
    }

    private func loadLiveModels(force: Bool = false) async {
        loadingModels = true
        let rows = await model.discoverProviderModels(providerID: providerID, baseURL: baseURL, apiKey: apiKey)
        if !rows.isEmpty {
            discoveredModels[providerID] = rows
            if modelID.isEmpty || !rows.contains(where: { $0.id == modelID }) {
                modelID = rows.first?.id ?? modelID
            }
        }
        if force || !rows.isEmpty {
            autoFetchedProviderID = providerID
        }
        loadingModels = false
    }

    private func loadLiveModelsIfNeeded() async {
        let trimmedProviderID = providerID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedProviderID.isEmpty,
              autoFetchedProviderID != trimmedProviderID,
              discoveredModels[trimmedProviderID] == nil else { return }
        await loadLiveModels(force: true)
    }
}

struct ModelOptionPicker: View {
    var options: [ProviderModelOption]
    @Binding var selectedID: String
    var loading: Bool
    var activeModelID: String

    var body: some View {
        if options.isEmpty {
            EmptyLine(
                symbol: loading ? "arrow.clockwise" : "sparkles",
                text: loading ? "Fetching models from the provider..." : "No model list yet. Use Fetch models or type a custom model ID."
            )
        } else {
            LazyVGrid(columns: columns, spacing: 8) {
                ForEach(options.prefix(12)) { option in
                    Button {
                        selectedID = option.id
                    } label: {
                        ModelOptionCard(
                            option: option,
                            selected: selectedID == option.id,
                            active: activeModelID == option.id
                        )
                    }
                    .buttonStyle(PressablePlainButtonStyle())
                }
            }
        }
    }

    private var columns: [GridItem] {
        [
            GridItem(.adaptive(minimum: 220, maximum: 320), spacing: 8, alignment: .topLeading)
        ]
    }
}

struct ModelOptionCard: View {
    var option: ProviderModelOption
    var selected: Bool
    var active: Bool

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: selected ? "checkmark.circle.fill" : "sparkles")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(selected ? ElephantTheme.accent : ElephantTheme.muted)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 4) {
                Text(option.label)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                    .lineLimit(1)
                    .truncationMode(.middle)
                HStack(spacing: 6) {
                    Text(option.source)
                    if active {
                        Text("active")
                    }
                }
                .font(.caption.weight(.semibold))
                .foregroundStyle(active ? ElephantTheme.green : ElephantTheme.muted)
                .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 11)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, minHeight: 58, alignment: .leading)
        .background(selected ? ElephantTheme.accent.opacity(0.10) : Color(nsColor: .textBackgroundColor).opacity(0.76), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(selected ? ElephantTheme.accent.opacity(0.48) : ElephantTheme.line, lineWidth: selected ? 1.3 : 1)
        )
    }
}

struct ProviderSectionBlock: View {
    var title: String
    var options: [ProviderOption]
    var selectedID: String
    var select: (ProviderOption) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(ElephantTheme.muted)
                .textCase(.uppercase)
            ForEach(options) { option in
                Button {
                    select(option)
                } label: {
                    ProviderChoiceCard(option: option, selected: option.id == selectedID)
                }
                .buttonStyle(PressablePlainButtonStyle())
            }
        }
    }
}

struct ProviderChoiceCard: View {
    var option: ProviderOption
    var selected: Bool

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: option.active ? "checkmark.circle.fill" : option.connected ? "bolt.horizontal.circle.fill" : "circle")
                .font(.title3)
                .foregroundStyle(option.active ? ElephantTheme.green : option.connected ? ElephantTheme.accent : ElephantTheme.faint)
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(option.displayName)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                    Text(option.id)
                        .font(.caption.monospaced())
                        .foregroundStyle(ElephantTheme.muted)
                }
                Text(option.summary.isEmpty ? providerSummary : option.summary)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(2)
            }
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 5) {
                HStack(spacing: 5) {
                    if option.active {
                        Pill(text: "active", symbol: "checkmark", tint: ElephantTheme.green)
                    } else if option.connected {
                        Pill(text: "connected", symbol: "bolt.horizontal", tint: ElephantTheme.accent)
                    }
                    if option.storedKeyCount > 0 {
                        Pill(text: "\(option.storedKeyCount) key", symbol: "key", tint: ElephantTheme.green)
                    }
                }
                Text([option.source, option.authKind].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.caption2)
                    .foregroundStyle(ElephantTheme.faint)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(selected ? ElephantTheme.accent.opacity(0.10) : Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(selected ? ElephantTheme.accent.opacity(0.55) : ElephantTheme.line, lineWidth: selected ? 1.4 : 1)
        )
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var providerSummary: String {
        let model = option.defaultModel.isEmpty ? "model not selected" : option.defaultModel
        let endpoint = option.defaultBaseURL.isEmpty ? "default endpoint" : option.defaultBaseURL
        return "\(model) · \(endpoint)"
    }
}

struct ReflectSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SettingsRow(label: "Questions", value: "\(model.snapshot.waitingQuestions) open")
            SettingsRow(label: "Worker", value: model.snapshot.workerStatus)
            SettingsRow(label: "Latest", value: model.snapshot.latestCompletedAt.isEmpty ? "not yet" : model.snapshot.latestCompletedAt)
            Button(model.isReflecting ? "Reflecting..." : "Run Reflect") {
                Task { await model.runReflect(trigger: "settings") }
            }
            .disabled(model.isReflecting)
        }
    }
}

struct RuntimeSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SettingsRow(label: "Core", value: model.corePhase.label)
            SettingsRow(label: "API", value: model.snapshot.apiURL.isEmpty ? "starting" : model.snapshot.apiURL)
            SettingsRow(label: "Database", value: model.snapshot.databasePath.isEmpty ? "not resolved" : model.snapshot.databasePath)
            SettingsRow(label: "Provider", value: model.snapshot.providerStatus)
            SettingsRow(label: "Semantic Index", value: model.snapshot.semanticStatus)
            HStack {
                Button("Reveal Database") {
                    model.revealDatabase()
                }
                .disabled(model.snapshot.databasePath.isEmpty)
                Button("Refresh") {
                    Task { try? await model.refreshDashboard() }
                }
            }
        }
    }
}

struct SkillLibraryPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            OperatorCatalogContent(
                kind: "skills",
                title: "Skill Library",
                subtitle: "Enable only what should be available in normal agent loops.",
                searchPrompt: "Search skills",
                emptySymbol: "wand.and.stars",
                emptyText: model.snapshot.skills > 0 ? "\(model.snapshot.skills) skills detected." : "No skills returned yet.",
                items: model.snapshot.skillItems,
                fallbackNames: model.snapshot.skillNames,
                totalCount: model.snapshot.skills,
                enabledCount: enabledSkills,
                logoSymbol: "puzzlepiece.extension",
                logoTint: ElephantTheme.orange,
                pageSize: 12
            )
        }
    }

    private var enabledSkills: Int {
        let enabled = model.snapshot.skillItems.filter(\.enabled).count
        if enabled > 0 || !model.snapshot.skillItems.isEmpty {
            return enabled
        }
        return model.snapshot.skills
    }
}

struct ToolsCatalogPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            OperatorCatalogContent(
                kind: "tools",
                title: "Tool Library",
                subtitle: "Built-in and MCP actions available to the local runtime.",
                searchPrompt: "Search tools",
                emptySymbol: "wrench.and.screwdriver",
                emptyText: model.snapshot.tools > 0 ? "\(model.snapshot.tools) tools detected." : "No tools returned yet.",
                items: model.snapshot.toolItems,
                fallbackNames: model.snapshot.toolNames,
                totalCount: model.snapshot.tools,
                enabledCount: model.snapshot.enabledTools,
                logoSymbol: "hammer",
                logoTint: ElephantTheme.accent,
                pageSize: 12
            )
        }
    }
}

struct SkillsSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        OperatorCatalogContent(
            kind: "skills",
            title: "Skill Library",
            subtitle: "Enable only what should be available in normal agent loops.",
            searchPrompt: "Search skills",
            emptySymbol: "wand.and.stars",
            emptyText: model.snapshot.skills > 0 ? "\(model.snapshot.skills) skills detected." : "No skills returned yet.",
            items: model.snapshot.skillItems,
            fallbackNames: model.snapshot.skillNames,
            totalCount: model.snapshot.skills,
            enabledCount: model.snapshot.skillItems.filter(\.enabled).count,
            logoSymbol: "puzzlepiece.extension",
            logoTint: ElephantTheme.orange,
            pageSize: 12
        )
    }
}

struct ToolsSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        OperatorCatalogContent(
            kind: "tools",
            title: "Tool Library",
            subtitle: "Built-in and MCP actions available to the local runtime.",
            searchPrompt: "Search tools",
            emptySymbol: "wrench.and.screwdriver",
            emptyText: model.snapshot.tools > 0 ? "\(model.snapshot.tools) tools detected." : "No tools returned yet.",
            items: model.snapshot.toolItems,
            fallbackNames: model.snapshot.toolNames,
            totalCount: model.snapshot.tools,
            enabledCount: model.snapshot.enabledTools,
            logoSymbol: "hammer",
            logoTint: ElephantTheme.accent,
            pageSize: 12
        )
    }
}

private struct OperatorCatalogContent: View {
    var kind: String
    var title: String
    var subtitle: String
    var searchPrompt: String
    var emptySymbol: String
    var emptyText: String
    var items: [OperationItem]
    var fallbackNames: [String]
    var totalCount: Int
    var enabledCount: Int
    var logoSymbol: String
    var logoTint: Color
    var pageSize: Int
    @State private var query = ""
    @State private var page = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 13) {
                OperatorCatalogLogo(symbol: logoSymbol, tint: logoTint)
                SectionLabel(
                    title: title,
                    subtitle: subtitle
                )
                Spacer(minLength: 0)
                HStack(spacing: 8) {
                    Pill(text: "\(enabledCount) enabled", symbol: "checkmark.seal", tint: ElephantTheme.green)
                    Pill(text: "\(totalCount) total", symbol: kind == "tools" ? "wrench.and.screwdriver" : "wand.and.stars", tint: logoTint)
                }
            }

            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                TextField(searchPrompt, text: $query)
                    .textFieldStyle(.plain)
                Spacer(minLength: 8)
                Text("\(filteredCount) shown")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))

            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(items.isEmpty ? "Catalog" : "\(enabledPageItems.count) enabled · \(availablePageItems.count) available on this page")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                    .textCase(.uppercase)
                Spacer(minLength: 0)
                Text("Page \(currentPage + 1) of \(pageCount)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                PageStepper(page: currentPage, pageCount: pageCount) { direction in
                    page = min(max(0, currentPage + direction), pageCount - 1)
                }
            }

            if !items.isEmpty {
                VStack(spacing: 0) {
                    ForEach(pageItems) { item in
                        OperatorCatalogRow(kind: kind, item: item)
                        if item.id != pageItems.last?.id {
                            Divider()
                                .padding(.leading, 64)
                        }
                    }
                }
                .background(Color(nsColor: .controlBackgroundColor).opacity(0.45), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))
            } else if fallbackNames.isEmpty {
                EmptyLine(symbol: emptySymbol, text: emptyText)
            } else {
                OperatorFallbackNameRows(kind: kind, names: pageNames)
            }
        }
        .onChange(of: query) { _ in page = 0 }
    }

    private var normalizedQuery: String {
        query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private var filteredItems: [OperationItem] {
        let sorted = items.sorted { left, right in
            if left.enabled != right.enabled {
                return left.enabled && !right.enabled
            }
            return left.title.localizedCaseInsensitiveCompare(right.title) == .orderedAscending
        }
        guard !normalizedQuery.isEmpty else { return sorted }
        return sorted.filter { item in
            item.title.lowercased().contains(normalizedQuery)
                || item.detail.lowercased().contains(normalizedQuery)
                || item.id.lowercased().contains(normalizedQuery)
        }
    }

    private var filteredNames: [String] {
        guard !normalizedQuery.isEmpty else { return fallbackNames }
        return fallbackNames.filter { $0.lowercased().contains(normalizedQuery) }
    }

    private var filteredCount: Int {
        items.isEmpty ? filteredNames.count : filteredItems.count
    }

    private var pageCount: Int {
        max(1, (filteredCount + pageSize - 1) / pageSize)
    }

    private var currentPage: Int {
        min(max(page, 0), pageCount - 1)
    }

    private var pageItems: [OperationItem] {
        Array(filteredItems.dropFirst(currentPage * pageSize).prefix(pageSize))
    }

    private var pageNames: [String] {
        Array(filteredNames.dropFirst(currentPage * pageSize).prefix(pageSize))
    }

    private var enabledPageItems: [OperationItem] {
        pageItems.filter(\.enabled)
    }

    private var availablePageItems: [OperationItem] {
        pageItems.filter { !$0.enabled }
    }
}

private struct OperatorCatalogLogo: View {
    var symbol: String
    var tint: Color

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(tint.opacity(0.11))
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(tint)
        }
        .frame(width: 42, height: 42)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(tint.opacity(0.22), lineWidth: 1)
        )
    }
}

private struct OperatorCatalogRow: View {
    @EnvironmentObject private var model: ElephantAppModel
    var kind: String
    var item: OperationItem

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            OperatorCatalogLogo(symbol: logo.symbol, tint: logo.tint)

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 7) {
                    Text(item.title)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                    if !item.id.isEmpty, item.id != item.title {
                        Text(item.id)
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(ElephantTheme.faint)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                }
                Text(item.detail.isEmpty ? "No description returned by the local runtime." : item.detail)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 12)

            HStack(spacing: 8) {
                Pill(
                    text: item.enabled ? "enabled" : "available",
                    symbol: item.enabled ? "checkmark" : "circle",
                    tint: item.enabled ? ElephantTheme.green : ElephantTheme.faint
                )
                Button(item.enabled ? "Disable" : "Enable") {
                    Task { await model.setConsoleItem(kind: kind, id: item.id, enabled: !item.enabled) }
                }
                .controlSize(.small)
                .frame(width: 72)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 11)
        .contentShape(Rectangle())
    }

    private var logo: OperatorLogoSpec {
        OperatorLogoSpec.forItem(item, kind: kind)
    }
}

private struct OperatorFallbackNameRows: View {
    var kind: String
    var names: [String]

    var body: some View {
        VStack(spacing: 0) {
            ForEach(names, id: \.self) { name in
                HStack(spacing: 12) {
                    OperatorCatalogLogo(
                        symbol: kind == "tools" ? "wrench.and.screwdriver" : "puzzlepiece.extension",
                        tint: kind == "tools" ? ElephantTheme.accent : ElephantTheme.orange
                    )
                    Text(name)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                if name != names.last {
                    Divider()
                        .padding(.leading, 64)
                }
            }
        }
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.45), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))
    }
}

private struct OperatorLogoSpec {
    var symbol: String
    var tint: Color

    static func forItem(_ item: OperationItem, kind: String) -> OperatorLogoSpec {
        let raw = "\(item.id) \(item.title) \(item.detail)".lowercased()
        if kind == "tools" {
            if raw.contains("browser") || raw.contains("http") || raw.contains("url") {
                return OperatorLogoSpec(symbol: "safari", tint: ElephantTheme.accent)
            }
            if raw.contains("file") || raw.contains("read") || raw.contains("write") || raw.contains("source") {
                return OperatorLogoSpec(symbol: "doc.text.magnifyingglass", tint: ElephantTheme.green)
            }
            if raw.contains("shell") || raw.contains("terminal") || raw.contains("command") {
                return OperatorLogoSpec(symbol: "terminal", tint: ElephantTheme.orange)
            }
            if raw.contains("message") || raw.contains("gateway") || raw.contains("chat") {
                return OperatorLogoSpec(symbol: "message.badge", tint: ElephantTheme.green)
            }
            if raw.contains("calendar") || raw.contains("cron") || raw.contains("schedule") {
                return OperatorLogoSpec(symbol: "calendar.badge.clock", tint: ElephantTheme.orange)
            }
            if raw.contains("memory") || raw.contains("state") || raw.contains("recall") {
                return OperatorLogoSpec(symbol: "point.3.connected.trianglepath.dotted", tint: ElephantTheme.accent)
            }
            return OperatorLogoSpec(symbol: "wrench.and.screwdriver", tint: ElephantTheme.accent)
        }

        if raw.contains("apple") {
            return OperatorLogoSpec(symbol: "apple.logo", tint: ElephantTheme.ink)
        }
        if raw.contains("browser") || raw.contains("web") || raw.contains("site") {
            return OperatorLogoSpec(symbol: "safari", tint: ElephantTheme.accent)
        }
        if raw.contains("github") || raw.contains("code") || raw.contains("terminal") {
            return OperatorLogoSpec(symbol: "chevron.left.forwardslash.chevron.right", tint: ElephantTheme.orange)
        }
        if raw.contains("document") || raw.contains("paper") || raw.contains("doc") || raw.contains("arxiv") {
            return OperatorLogoSpec(symbol: "doc.text", tint: ElephantTheme.green)
        }
        if raw.contains("image") || raw.contains("design") || raw.contains("figma") {
            return OperatorLogoSpec(symbol: "photo.on.rectangle.angled", tint: ElephantTheme.orange)
        }
        if raw.contains("audio") || raw.contains("video") || raw.contains("speech") {
            return OperatorLogoSpec(symbol: "waveform", tint: ElephantTheme.accent)
        }
        if raw.contains("llm") || raw.contains("agent") || raw.contains("model") || raw.contains("research") {
            return OperatorLogoSpec(symbol: "brain.head.profile", tint: ElephantTheme.green)
        }
        return OperatorLogoSpec(symbol: "puzzlepiece.extension", tint: ElephantTheme.orange)
    }
}

struct RuntimeConfigSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var draft = ""
    @State private var loadedPath = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SettingsRow(label: "File", value: model.snapshot.settingsPath.isEmpty ? "not resolved" : model.snapshot.settingsPath)

            if model.snapshot.settingsYaml.isEmpty {
                EmptyLine(symbol: "slider.horizontal.3", text: "The API did not return editable config text yet.")
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Global YAML")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.muted)

                    TextEditor(text: $draft)
                        .font(.system(.callout, design: .monospaced))
                        .foregroundStyle(ElephantTheme.ink)
                        .scrollContentBackground(.hidden)
                        .padding(8)
                        .frame(minHeight: 260)
                        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))
                        .accessibilityLabel("Global runtime configuration YAML")
                }

                HStack(spacing: 8) {
                    Button("Save Config") {
                        Task { await model.saveGlobalConfig(yamlText: draft) }
                    }
                    .disabled(!hasChanges || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    Button("Reset") {
                        draft = model.snapshot.settingsYaml
                    }
                    .disabled(!hasChanges)

                    Button("Refresh") {
                        Task { try? await model.refreshDashboard() }
                    }

                    Spacer(minLength: 0)

                    if !model.configActionResult.isEmpty {
                        Label(model.configActionResult, systemImage: "checkmark.circle.fill")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(ElephantTheme.green)
                    } else if hasChanges {
                        Text("Unsaved")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(ElephantTheme.orange)
                    }
                }
                .controlSize(.small)
            }
        }
        .onAppear {
            syncDraftIfNeeded()
        }
        .onChange(of: model.snapshot.settingsYaml) { _ in
            syncDraftIfNeeded()
        }
    }

    private var hasChanges: Bool {
        draft != model.snapshot.settingsYaml
    }

    private func syncDraftIfNeeded() {
        guard loadedPath != model.snapshot.settingsPath || draft.isEmpty else { return }
        draft = model.snapshot.settingsYaml
        loadedPath = model.snapshot.settingsPath
    }
}

struct OperatorItemGroup: View {
    var title: String
    var kind: String
    var items: [OperationItem]

    var body: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                    .textCase(.uppercase)
                OperatorItemRows(kind: kind, items: items)
            }
        }
    }
}

struct OperatorItemRows: View {
    @EnvironmentObject private var model: ElephantAppModel
    var kind: String
    var items: [OperationItem]

    var body: some View {
        VStack(spacing: 0) {
            ForEach(items) { item in
                HStack(alignment: .top, spacing: 12) {
                    StatusDot(tint: item.enabled ? ElephantTheme.green : ElephantTheme.faint)
                        .padding(.top, 5)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(item.title)
                            .font(.callout.weight(.semibold))
                            .foregroundStyle(ElephantTheme.ink)
                        if !item.detail.isEmpty {
                            Text(item.detail)
                                .font(.caption)
                                .foregroundStyle(ElephantTheme.muted)
                                .lineLimit(2)
                        }
                    }
                    Spacer(minLength: 0)
                    Button(item.enabled ? "Disable" : "Enable") {
                        Task { await model.setConsoleItem(kind: kind, id: item.id, enabled: !item.enabled) }
                    }
                    .controlSize(.small)
                }
                .padding(.vertical, 7)
                if item.id != items.last?.id {
                    Divider()
                }
            }
        }
    }
}

struct MessagingSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SettingsRow(label: "Services", value: "\(model.snapshot.gatewayServices)")
            SettingsRow(label: "Configured", value: "\(model.snapshot.gatewayConfigured)")
            SettingsRow(label: "Running", value: "\(model.snapshot.gatewayRunning)")
            if !model.gatewayActionResult.isEmpty {
                Text(model.gatewayActionResult)
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.green)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !model.snapshot.gatewayItems.isEmpty {
                ForEach(model.snapshot.gatewayItems) { service in
                    GatewayServiceRow(service: service)
                    if service.id != model.snapshot.gatewayItems.last?.id {
                        Divider()
                    }
                }
            } else if model.snapshot.gatewayNames.isEmpty {
                EmptyLine(symbol: "message.badge", text: "No messaging service configured yet.")
            } else {
                FlowLayout(items: model.snapshot.gatewayNames)
            }
        }
    }
}

struct GatewayServiceRow: View {
    @EnvironmentObject private var model: ElephantAppModel
    var service: GatewayServiceItem

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            GatewayServiceLogo(service: service)
            VStack(alignment: .leading, spacing: 3) {
                Text(service.title)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(2)
            }
            Spacer(minLength: 0)
            HStack(spacing: 6) {
                if service.configured {
                    Button(service.running ? "Restart" : "Start") {
                        Task { await model.runGatewayAction(service: service, action: service.running ? "restart" : "start") }
                    }
                    .controlSize(.small)
                    Button("Stop") {
                        Task { await model.runGatewayAction(service: service, action: "stop") }
                    }
                    .controlSize(.small)
                    .disabled(!service.running && !service.starting)
                } else {
                    Text("Configure in secrets")
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.faint)
                }
            }
        }
        .padding(.vertical, 7)
    }

    private var statusTint: Color {
        if service.running { return ElephantTheme.green }
        if service.starting { return ElephantTheme.accent }
        if service.configured { return ElephantTheme.green }
        return ElephantTheme.faint
    }

    private var detail: String {
        let status = service.running ? "running" : service.starting ? "starting" : service.configured ? "configured" : "not configured"
        return [status, service.transport, service.detail].filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

struct JobsSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SettingsRow(label: "Scheduled jobs", value: "\(model.snapshot.cronJobs)")
            if model.snapshot.cronNames.isEmpty {
                EmptyLine(symbol: "calendar.badge.clock", text: "No scheduled jobs yet.")
            } else {
                FlowLayout(items: model.snapshot.cronNames)
            }
        }
    }
}

struct CuriositySettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Picker("How often should Elephant Agent ask?", selection: Binding(
                get: { model.snapshot.questionIntensity },
                set: { value in Task { await model.setCuriosityIntensity(value) } }
            )) {
                Text("Low").tag("low")
                Text("Medium").tag("medium")
                Text("High").tag("high")
            }
            .pickerStyle(.segmented)
            .frame(width: 360)
            SettingsRow(
                label: "Effective cadence",
                value: "\(model.snapshot.questionAskEnabled ? "on" : "off") · idle \(model.snapshot.questionIdleMinutes)m · max \(model.snapshot.questionDailyMax)/day · quiet \(model.snapshot.questionQuietStart):00-\(model.snapshot.questionQuietEnd):00"
            )
            SettingsRow(label: "Open questions", value: "\(model.snapshot.waitingQuestions)")
            if model.snapshot.sampleQuestions.isEmpty {
                EmptyLine(symbol: "questionmark.bubble", text: "No Personal Model questions waiting right now.")
            } else {
                ForEach(model.snapshot.sampleQuestions, id: \.self) { question in
                    SettingsRow(label: "Question", value: question)
                }
            }
        }
    }
}

struct HerdSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SettingsRow(label: "States", value: "\(model.snapshot.states)")
            SettingsRow(label: "Current", value: model.snapshot.elephantName)
            if model.snapshot.stateNames.isEmpty {
                EmptyLine(symbol: "person.3", text: "No local Personal Model state yet.")
            } else {
                FlowLayout(items: model.snapshot.stateNames)
            }
        }
    }
}

struct HistoryUsageSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                MetricTile(label: "Episodes", value: "\(model.snapshot.episodes)", symbol: "rectangle.stack")
                MetricTile(label: "Loops", value: "\(model.snapshot.loops)", symbol: "arrow.triangle.2.circlepath", tint: ElephantTheme.green)
                MetricTile(label: "Steps", value: "\(model.snapshot.steps)", symbol: "point.topleft.down.curvedto.point.bottomright.up", tint: ElephantTheme.orange)
            }

            SettingsRow(label: "Usage events", value: "\(model.snapshot.usageEvents)")
            SettingsRow(label: "Tokens", value: abbreviatedCount(model.snapshot.usageTokens))

            if !model.snapshot.episodeThreads.isEmpty {
                Divider()
                SectionLabel(title: "Recent Conversations", subtitle: "Read-only trace from runtime history")
                ForEach(model.snapshot.episodeThreads.prefix(5)) { thread in
                    HStack(alignment: .top, spacing: 12) {
                        StatusDot(tint: thread.status == "open" ? ElephantTheme.green : ElephantTheme.faint)
                            .padding(.top, 5)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(thread.title)
                                .font(.callout.weight(.semibold))
                                .foregroundStyle(ElephantTheme.ink)
                                .lineLimit(1)
                            Text(thread.subtitle)
                                .font(.caption)
                                .foregroundStyle(ElephantTheme.muted)
                        }
                        Spacer(minLength: 0)
                        Button("Open") {
                            model.openEpisodeThread(thread)
                        }
                        .controlSize(.small)
                    }
                    .padding(.vertical, 7)
                    if thread.id != model.snapshot.episodeThreads.prefix(5).last?.id {
                        Divider()
                    }
                }
            }
        }
    }

    private func abbreviatedCount(_ value: Int) -> String {
        if value >= 1_000_000 {
            return String(format: "%.1fM", Double(value) / 1_000_000.0)
        }
        if value >= 1_000 {
            return String(format: "%.1fK", Double(value) / 1_000.0)
        }
        return "\(value)"
    }
}

struct LogsDiagnosticsSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var selectedLogID = ""
    @State private var page = 0
    private let pageSize = 28

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SettingsRow(label: "Log files", value: "\(model.snapshot.logs)")
            if model.snapshot.logFiles.isEmpty {
                EmptyLine(symbol: "stethoscope", text: "No local log files found in the current state directory.")
            } else {
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(model.snapshot.logFiles) { item in
                            Button {
                                selectedLogID = item.id
                                page = 0
                            } label: {
                                LogFilePickerRow(item: item, selected: item.id == selected.id)
                            }
                            .buttonStyle(PressablePlainButtonStyle())
                        }
                    }
                    .frame(width: 300)

                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            SectionLabel(title: selected.name.isEmpty ? "Log detail" : selected.name, subtitle: selected.detail)
                            Spacer()
                            Button { page = max(0, page - 1) } label: { Image(systemName: "chevron.left") }
                                .buttonStyle(.borderless)
                                .disabled(currentPage == 0)
                            Text("\(currentPage + 1)/\(pageCount)")
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(ElephantTheme.muted)
                            Button { page = min(pageCount - 1, page + 1) } label: { Image(systemName: "chevron.right") }
                                .buttonStyle(.borderless)
                                .disabled(currentPage >= pageCount - 1)
                        }
                        LogTailView(lines: visibleLines)
                            .frame(minHeight: 220)
                    }
                }
            }
        }
        .onAppear {
            if selectedLogID.isEmpty {
                selectedLogID = model.snapshot.logFiles.first?.id ?? ""
            }
        }
    }

    private var selected: LogFileItem {
        model.snapshot.logFiles.first(where: { $0.id == selectedLogID }) ?? model.snapshot.logFiles.first ?? LogFileItem(id: "", name: "", path: "", size: 0, updatedAt: "", tail: [])
    }

    private var pageCount: Int {
        max(1, (selected.tail.count + pageSize - 1) / pageSize)
    }

    private var currentPage: Int {
        min(max(page, 0), pageCount - 1)
    }

    private var visibleLines: [String] {
        Array(selected.tail.dropFirst(currentPage * pageSize).prefix(pageSize))
    }
}

struct LogFilePickerRow: View {
    var item: LogFileItem
    var selected: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Label(item.name, systemImage: "doc.text.magnifyingglass")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(selected ? ElephantTheme.accent : ElephantTheme.ink)
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
            Text(item.path)
                .font(.caption)
                .foregroundStyle(ElephantTheme.muted)
                .lineLimit(1)
                .truncationMode(.middle)
            Text(item.detail)
                .font(.caption2)
                .foregroundStyle(ElephantTheme.faint)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(selected ? ElephantTheme.accent.opacity(0.10) : Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(selected ? ElephantTheme.accent.opacity(0.45) : ElephantTheme.line, lineWidth: 1))
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

struct LogTailView: View {
    var lines: [String]

    var body: some View {
        if lines.isEmpty {
            EmptyLine(symbol: "doc.text", text: "No log tail available.")
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                        Text(line)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(color(for: line))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(10)
            }
            .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))
        }
    }

    private func color(for line: String) -> Color {
        let normalized = line.lowercased()
        if normalized.contains("error") || normalized.contains("traceback") || normalized.contains("exception") {
            return ElephantTheme.orange
        }
        if normalized.contains("warn") {
            return Color.yellow.opacity(0.85)
        }
        if normalized.contains("info") || normalized.contains("ready") || normalized.contains("serving") {
            return ElephantTheme.accent
        }
        return ElephantTheme.ink
    }
}

struct ProviderSettingsPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    SectionLabel(title: "Provider", subtitle: providerSubtitle)
                    Spacer()
                    Pill(text: providerStatusLabel, symbol: "cpu", tint: providerTint)
                }

                SettingsRow(label: "Provider", value: model.snapshot.providerID.isEmpty ? "not configured" : model.snapshot.providerID)
                SettingsRow(label: "Model", value: model.snapshot.providerModelID.isEmpty ? "not selected" : model.snapshot.providerModelID)
                SettingsRow(label: "Source", value: model.snapshot.providerSource.isEmpty ? "unknown" : model.snapshot.providerSource)
                SettingsRow(label: "Embedding", value: embeddingLine)

                HStack {
                    Button("Test Provider") {
                        Task { await model.testProvider() }
                    }
                    .disabled(model.snapshot.providerID.isEmpty)

                    Button("Refresh") {
                        Task { try? await model.refreshDashboard() }
                    }
                }

                if !model.providerTestResult.isEmpty {
                    Text(model.providerTestResult)
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.green)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private var providerStatusLabel: String {
        if model.snapshot.providerStatus == "unknown", !model.snapshot.providerID.isEmpty {
            return "configured"
        }
        return model.snapshot.providerStatus == "unknown" ? "setup needed" : model.snapshot.providerStatus
    }

    private var providerSubtitle: String {
        model.snapshot.providerModelID.isEmpty
            ? "Choose and validate the model Elephant thinks with."
            : "Elephant is using \(model.snapshot.providerModelID)."
    }

    private var providerTint: Color {
        let value = providerStatusLabel.lowercased()
        return value.contains("setup") || value.contains("missing") ? ElephantTheme.orange : ElephantTheme.green
    }

    private var embeddingLine: String {
        let status = model.snapshot.embeddingStatus.isEmpty ? model.snapshot.semanticStatus : model.snapshot.embeddingStatus
        let runtime = model.snapshot.embeddingRuntimeState.trimmingCharacters(in: .whitespacesAndNewlines)
        let suffix = runtime.isEmpty ? status : "\(status) · \(runtime)"
        if model.snapshot.embeddingProviderID.isEmpty {
            return suffix
        }
        return "\(model.snapshot.embeddingProviderID) · \(suffix)"
    }
}

struct ReflectSettingsPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                SectionLabel(title: "Reflect", subtitle: "Background learning jobs")
                SettingsRow(label: "Questions", value: "\(model.snapshot.waitingQuestions) open")
                SettingsRow(label: "Worker", value: model.snapshot.workerStatus)
                SettingsRow(label: "Latest", value: model.snapshot.latestCompletedAt.isEmpty ? "not yet" : model.snapshot.latestCompletedAt)

                Button(model.isReflecting ? "Reflecting..." : "Run Reflect") {
                    Task { await model.runReflect(trigger: "settings") }
                }
                .disabled(model.isReflecting)
            }
        }
    }
}

struct SettingsListRow: View {
    var symbol: String
    var title: String
    var subtitle: String
    var action: (() -> Void)? = nil

    var body: some View {
        Button {
            action?()
        } label: {
            HStack(spacing: 18) {
                Image(systemName: symbol)
                    .font(.title3)
                    .foregroundStyle(ElephantTheme.muted)
                    .frame(width: 26)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.headline)
                        .foregroundStyle(ElephantTheme.ink)
                    Text(subtitle)
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
                if action != nil {
                    Image(systemName: "chevron.right")
                        .foregroundStyle(ElephantTheme.faint)
                }
            }
            .padding(.vertical, 14)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        Divider()
    }
}

struct RuntimeSettingsPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 12) {
                SectionLabel(title: "Runtime", subtitle: "Local shell status")
                SettingsRow(label: "Core", value: model.corePhase.label)
                SettingsRow(label: "API", value: model.snapshot.apiURL.isEmpty ? "starting" : model.snapshot.apiURL)
                SettingsRow(label: "Database", value: model.snapshot.databasePath.isEmpty ? "not resolved" : model.snapshot.databasePath)
                SettingsRow(label: "Provider", value: model.snapshot.providerStatus)
                SettingsRow(label: "Semantic Index", value: model.snapshot.semanticStatus)

                HStack {
                    Button("Reveal Database") {
                        model.revealDatabase()
                    }
                    .disabled(model.snapshot.databasePath.isEmpty)

                    Button("Refresh") {
                        Task { try? await model.refreshDashboard() }
                    }
                }
            }
        }
    }
}

struct SkillsAndJobsPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 16) {
                SectionLabel(title: "Tools and Jobs", subtitle: "Kept out of the main sidebar")

                if model.snapshot.skillNames.isEmpty {
                    EmptyLine(
                        symbol: "wand.and.stars",
                        text: model.snapshot.skills > 0
                            ? "\(model.snapshot.skills) skills detected."
                            : "No skills returned yet."
                    )
                } else {
                    FlowLayout(items: model.snapshot.skillNames)
                }

                Divider()

                if model.snapshot.cronNames.isEmpty {
                    EmptyLine(symbol: "calendar.badge.clock", text: "No scheduled jobs yet.")
                } else {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(model.snapshot.cronNames, id: \.self) { name in
                            Label(name, systemImage: "clock")
                                .font(.callout)
                                .foregroundStyle(ElephantTheme.ink)
                        }
                    }
                }
            }
        }
        .frame(width: 380)
    }
}

struct OnboardingFlow: View {
    @EnvironmentObject private var model: ElephantAppModel
    var onComplete: () -> Void

    var body: some View {
        ZStack {
            AppBackground()
            VStack(spacing: 22) {
                HStack {
                    BrandMark(size: 42)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Set up Elephant")
                            .font(.title.weight(.semibold))
                        Text("Local memory, reviewable facts, visible questions.")
                            .foregroundStyle(ElephantTheme.muted)
                    }
                    Spacer()
                    Button("Later", action: onComplete)
                        .buttonStyle(.borderless)
                }

                HStack(spacing: 8) {
                    SetupStep(index: 0, title: "Identity", active: model.onboardingStep == 0, complete: model.onboardingStep > 0)
                    SetupStep(index: 1, title: "Provider", active: model.onboardingStep == 1, complete: model.onboardingStep > 1)
                    SetupStep(index: 2, title: "Sources", active: model.onboardingStep == 2, complete: model.onboardingStep > 2)
                    SetupStep(index: 3, title: "Review", active: model.onboardingStep >= 3, complete: false)
                }

                NativePanel {
                    ScrollView {
                        switch model.onboardingStep {
                        case 0:
                            CreateElephantStep()
                        case 1:
                            ProviderElephantStep()
                        case 2:
                            SourceElephantStep()
                        default:
                            ReviewElephantStep(onComplete: onComplete)
                        }
                    }
                    .frame(maxHeight: 430)
                }
                .frame(width: 720)
                .frame(minHeight: 410)
            }
            .padding(30)
        }
        .frame(width: 940, height: 640)
    }
}

struct CreateElephantStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionLabel(title: "Create the local Personal Model", subtitle: "This mirrors `elephant init`: identity, language, cadence, and the first user profile facts.")
            HStack(alignment: .top, spacing: 18) {
                UserAvatarPickerCard()
                VStack(spacing: 12) {
                    HStack(spacing: 12) {
                        TextField("Elephant name", text: $model.onboardingName)
                            .textFieldStyle(.roundedBorder)
                        TextField("Your preferred name", text: $model.onboardingPreferredName)
                            .textFieldStyle(.roundedBorder)
                    }
                    TextField("What should Elephant remember and help with?", text: $model.onboardingPurpose, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(2...4)
                }
            }
            HStack(spacing: 12) {
                TextField("Role or occupation", text: $model.onboardingOccupation)
                    .textFieldStyle(.roundedBorder)
                TextField("City or timezone", text: $model.onboardingCity)
                    .textFieldStyle(.roundedBorder)
            }
            HStack(spacing: 12) {
                TextField("Gender", text: $model.onboardingGender)
                    .textFieldStyle(.roundedBorder)
                TextField("Birth date", text: $model.onboardingBirthDate)
                    .textFieldStyle(.roundedBorder)
            }
            HStack(spacing: 12) {
                TextField("MBTI or self-label", text: $model.onboardingMBTI)
                    .textFieldStyle(.roundedBorder)
                TextField("Hobbies", text: $model.onboardingHobbies)
                    .textFieldStyle(.roundedBorder)
            }
            HStack(spacing: 12) {
                TextField("Relationship mode", text: $model.onboardingRelationshipMode)
                    .textFieldStyle(.roundedBorder)
                TextField("Communication preference", text: $model.onboardingCommunicationPreference)
                    .textFieldStyle(.roundedBorder)
            }
            TextField("Boundaries Elephant should respect", text: $model.onboardingSafetyBoundaries, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...3)
            HStack(spacing: 16) {
                Picker("Language", selection: $model.onboardingFirstLanguage) {
                    Text("English").tag("en")
                    Text("中文").tag("zh")
                }
                .pickerStyle(.segmented)
                Picker("Learning", selection: $model.onboardingLearningIntensity) {
                    Text("Low").tag("low")
                    Text("Medium").tag("medium")
                    Text("High").tag("high")
                }
                .pickerStyle(.segmented)
            }
            HStack {
                Spacer()
                Button("Continue") {
                    model.onboardingStep = 1
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(ElephantTheme.accent)
            }
        }
    }
}

struct UserAvatarPickerCard: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(spacing: 10) {
            Button {
                model.pickUserAvatar()
            } label: {
                UserAvatarOrbitView(size: 92, editable: true)
            }
            .buttonStyle(PressablePlainButtonStyle())
            .help("Choose profile photo")

            Text(model.userAvatarURL == nil ? "Choose Photo" : "Change Photo")
                .font(.callout.weight(.semibold))
                .foregroundStyle(ElephantTheme.accent)
            Text("Shown on Home")
                .font(.caption)
                .foregroundStyle(ElephantTheme.muted)
        }
        .frame(width: 126)
        .padding(.vertical, 2)
    }
}

struct ProviderElephantStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            SectionLabel(title: "Configure the model provider", subtitle: "The desktop app stores the same provider profile used by the CLI.")
            HStack(spacing: 12) {
                Picker("Provider", selection: $model.onboardingProviderID) {
                    Text("OpenAI Compatible").tag("openai-compatible")
                    Text("OpenAI").tag("openai")
                    Text("Anthropic").tag("anthropic")
                }
                .pickerStyle(.menu)
                .frame(width: 220)
                TextField("Model ID", text: $model.onboardingModelID)
                    .textFieldStyle(.roundedBorder)
            }
            TextField("Base URL", text: $model.onboardingBaseURL)
                .textFieldStyle(.roundedBorder)
            SecureField("API key or token", text: $model.onboardingAPIKey)
                .textFieldStyle(.roundedBorder)
            TextField("Context window tokens (optional)", text: $model.onboardingContextWindow)
                .textFieldStyle(.roundedBorder)
            HStack {
                EmptyLine(symbol: "lock.shield", text: "Keys are written to Elephant's local encrypted vault when provided.")
                Spacer()
            }
            HStack {
                Button("Back") {
                    model.onboardingStep = 0
                }
                Spacer()
                Button("Create Local Profile") {
                    Task { await model.createElephantFromOnboarding() }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(ElephantTheme.accent)
                .disabled(!providerReady)
            }
        }
        .onAppear {
            if model.onboardingModelID.isEmpty {
                model.onboardingModelID = model.snapshot.providerModelID
            }
            if !model.snapshot.providerID.isEmpty {
                model.onboardingProviderID = model.snapshot.providerID
            }
        }
    }

    private var providerReady: Bool {
        let provider = model.onboardingProviderID.trimmingCharacters(in: .whitespacesAndNewlines)
        let modelID = model.onboardingModelID.trimmingCharacters(in: .whitespacesAndNewlines)
        if provider == "openai-compatible" {
            if model.snapshot.providerID == provider, !model.snapshot.providerModelID.isEmpty {
                return true
            }
            return !model.onboardingBaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !modelID.isEmpty
        }
        return !provider.isEmpty
    }
}

struct SourceElephantStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            SectionLabel(title: "Add useful context", subtitle: "Sources are evidence, not truth.")
            EmptyLine(symbol: "folder", text: "Pick a project, README, notes folder, codebase, or config file.")
            EmptyLine(symbol: "lock.shield", text: "Generated folders, binaries, large files, and secret-like names are skipped.")
            HStack {
                Button("Skip") {
                    model.onboardingStep = 3
                }
                Spacer()
                Button("Choose Sources") {
                    Task { await model.pickSources() }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(ElephantTheme.accent)
            }
        }
    }
}

struct ReviewElephantStep: View {
    @EnvironmentObject private var model: ElephantAppModel
    var onComplete: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            SectionLabel(title: "Review before chat", subtitle: "Elephant should show what it knows and what it still needs.")
            HStack(spacing: 12) {
                MetricTile(label: "Facts", value: "\(model.snapshot.facts)", symbol: "checkmark.seal")
                MetricTile(label: "Questions", value: "\(model.snapshot.waitingQuestions)", symbol: "questionmark.bubble", tint: ElephantTheme.orange)
                MetricTile(label: "Sources", value: "\(model.stagedSources.count)", symbol: "folder", tint: ElephantTheme.green)
            }
            ReviewListPanel(
                title: "First Queue",
                empty: "Nothing to review yet. You can enter Chat and reflect later.",
                items: model.snapshot.sampleQuestions + model.snapshot.sampleFacts,
                symbol: "sparkle.magnifyingglass"
            )
            HStack {
                Button("Run Reflect") {
                    Task { await model.runReflect(trigger: "profile_builder") }
                }
                Spacer()
                Button("Enter Chat") {
                    onComplete()
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(ElephantTheme.accent)
            }
        }
    }
}

struct SetupStep: View {
    var index: Int
    var title: String
    var active: Bool
    var complete: Bool

    var body: some View {
        HStack(spacing: 9) {
            Text(complete ? "OK" : "\(index + 1)")
                .font(.caption.weight(.bold))
                .frame(width: 24, height: 24)
                .background((active || complete ? ElephantTheme.accent : ElephantTheme.line), in: Circle())
                .foregroundStyle(active || complete ? .white : ElephantTheme.muted)
            Text(title)
                .font(.callout.weight(.semibold))
                .foregroundStyle(active ? ElephantTheme.ink : ElephantTheme.muted)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(Color(nsColor: .controlBackgroundColor), in: Capsule())
        .overlay(Capsule().stroke(ElephantTheme.line, lineWidth: 1))
    }
}
