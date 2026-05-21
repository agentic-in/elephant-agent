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
            .allowsHitTesting(!model.showingOnboarding)
            .accessibilityHidden(model.isSleepDisplayPresented || model.showingOnboarding)
            .animation(.easeInOut(duration: 0.18), value: sidebarVisible)

            if model.isSleepDisplayPresented {
                SleepDisplayView()
                    .environmentObject(model)
                    .transition(.opacity.combined(with: .scale(scale: 1.015)))
                    .zIndex(20)
            }

            if model.showingOnboarding {
                OnboardingFlow {
                    onboardingComplete = true
                    model.completeOnboarding()
                }
                .environmentObject(model)
                .transition(.opacity)
                .zIndex(40)
            }
        }
        .background(AppActivityMonitor {
            model.registerUserActivity()
        })
        .environment(\.locale, Locale(identifier: model.appLanguage.localeIdentifier))
        .animation(.spring(response: 0.42, dampingFraction: 0.86), value: model.isSleepDisplayPresented)
        .animation(.easeInOut(duration: 0.24), value: model.showingOnboarding)
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
        .onReceive(NotificationCenter.default.publisher(for: .elephantEnterSleepDisplay)) { _ in
            model.beginSleepDisplay(reason: "manual")
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
                        language: model.appLanguage,
                        selected: model.selectedSection == .provider
                    ) {
                        model.selectedSection = .provider
                    }
                    SidebarIconButton(
                        section: .settings,
                        language: model.appLanguage,
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
        return glassVerticalPadding * 2 + buttonsHeight + 4
    }

    private func navigationGlass(height: CGFloat, scrolls: Bool) -> some View {
        VStack(spacing: navSpacing) {
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
                    language: model.appLanguage,
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
    var language: AppLanguage
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
        .help(section.title(language: language))
        .accessibilityLabel(section.title(language: language))
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
                actionTitle: AppSection.wake.title(language: model.appLanguage),
                actionSymbol: "bubble.left.and.bubble.right"
            ) {
                model.selectedSection = .wake
                model.focusComposer()
            }

            HomeFirstLookPanel(phaseTint: phaseTint, connectionText: connectionText)

            HomeReadinessStrip()
            HomeContinuityPanel()
        }
    }

    private var homeSubtitle: String {
        if model.snapshot.hasElephant {
            return model.text(.homeReadySubtitle)
        }
        return model.text(.homeSetupSubtitle)
    }

    private var connectionText: String {
        switch model.corePhase {
        case .ready:
            if model.snapshot.readyForInteraction {
                return model.snapshot.hasElephant ? model.text(.connectedToElephant) : model.text(.readyForFirstChat)
            }
            return model.text(.warmingModel)
        case .starting: return model.text(.startingElephant)
        case .failed: return model.text(.needsAttention)
        case .idle: return model.text(.idle)
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

struct HomeFirstLookPanel: View {
    @EnvironmentObject private var model: ElephantAppModel
    var phaseTint: Color
    var connectionText: String
    @State private var selectedNode: PersonalGraphSelection?

    var body: some View {
        NativePanel {
            HStack(alignment: .top, spacing: 22) {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .center, spacing: 14) {
                        Button {
                            model.pickUserAvatar()
                        } label: {
                            UserAvatarOrbitView(size: 122, editable: true)
                        }
                        .buttonStyle(PressablePlainButtonStyle())
                        .help(model.text(.changeProfilePhoto))
                        .accessibilityLabel(model.text(.changeProfilePhoto))

                        VStack(alignment: .leading, spacing: 6) {
                            Text(model.userDisplayName)
                                .font(.title2.weight(.semibold))
                                .foregroundStyle(ElephantTheme.ink)
                                .lineLimit(1)
                            HStack(spacing: 8) {
                                StatusDot(tint: phaseTint)
                                Text(connectionText)
                                    .font(.callout.weight(.semibold))
                                    .foregroundStyle(phaseTint)
                                    .lineLimit(2)
                            }
                        }
                    }

                    VStack(alignment: .leading, spacing: 9) {
                        Text(model.text(.homeHeroTitle))
                            .font(.system(size: 26, weight: .semibold))
                            .foregroundStyle(ElephantTheme.ink)
                        Text(model.text(.homeHeroSubtitle))
                            .font(.callout)
                            .foregroundStyle(ElephantTheme.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    Button {
                        model.selectedSection = .wake
                        model.focusComposer()
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "bubble.left.and.bubble.right.fill")
                            Text(AppSection.wake.title(language: model.appLanguage))
                            Spacer(minLength: 0)
                            Image(systemName: "arrow.right")
                        }
                        .font(.headline.weight(.semibold))
                        .padding(.horizontal, 16)
                        .padding(.vertical, 13)
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .tint(ElephantTheme.accent)

                    VStack(spacing: 9) {
                        TodaySignalRow(value: "\(model.snapshot.facts)", label: model.text(.reviewedFactsLabel), symbol: "checkmark.seal")
                        TodaySignalRow(value: "\(model.snapshot.waitingQuestions)", label: model.text(.questionsWaitingLabel), symbol: "questionmark.bubble", tint: ElephantTheme.orange)
                        TodaySignalRow(value: "\(model.snapshot.semanticEntries)", label: model.text(.evidencePointsLabel), symbol: "doc.text.magnifyingglass", tint: ElephantTheme.green)
                    }
                    .padding(.top, 2)

                    HStack(spacing: 10) {
                        TodayCommand(title: model.text(.reviewQuestions), symbol: "person.crop.circle") {
                            model.selectedSection = .you
                        }
                        TodayCommand(title: AppSection.diary.title(language: model.appLanguage), symbol: "book.closed") {
                            model.selectedSection = .diary
                        }
                    }
                }
                .frame(width: 334, alignment: .topLeading)

                Divider()
                    .frame(height: 438)

                VStack(alignment: .leading, spacing: 12) {
                    HStack(alignment: .firstTextBaseline) {
                        SectionLabel(
                            title: model.text(.personalModelMapTitle),
                            subtitle: model.text(.homeMapSubtitle)
                        )
                        Spacer(minLength: 0)
                        Pill(
                            text: String(
                                format: model.text(.mapNodeCountFormat),
                                "\(model.snapshot.personalModelFacts.filter { $0.status.lowercased() != "deleted" }.count)"
                            ),
                            symbol: "point.3.connected.trianglepath.dotted",
                            tint: ElephantTheme.accent
                        )
                    }

                    PersonalModelDotMapCanvas(userName: model.userDisplayName, snapshot: model.snapshot, selectedNode: $selectedNode)
                        .frame(height: 360)

                    if let selectedNode {
                        PersonalGraphDetailStrip(selection: selectedNode, language: model.appLanguage)
                    } else {
                        EmptyLine(symbol: "circle.hexagongrid", text: model.text(.mapClickHint))
                    }
                }
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
            .frame(minHeight: 438, alignment: .top)
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
        let modelName = model.snapshot.providerModelID.isEmpty ? model.text(.chooseModel) : model.snapshot.providerModelID
        let status = !hasProvider
            ? model.text(.statusSetup)
            : model.snapshot.readyForInteraction
                ? model.text(.ready)
                : model.snapshot.providerReady ? model.text(.statusWarming) : localizedStatus(providerStatusLabel)
        return HomeReadinessItem(
            title: model.text(.homeReadinessModel),
            detail: hasProvider ? modelName : model.text(.providerSetup),
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
            title: model.text(.homeReadinessMemory),
            detail: String(
                format: model.text(.memorySummaryFormat),
                "\(model.snapshot.facts)",
                "\(model.snapshot.semanticEntries)"
            ),
            status: healthy ? model.text(.ready) : model.text(.statusWarming),
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
        let status = running > 0 ? model.text(.statusLive) : configured > 0 ? model.text(.statusConfigured) : model.text(.statusSetup)
        return HomeReadinessItem(
            title: model.text(.homeReadinessMessaging),
            detail: String(
                format: model.text(.messagingSummaryFormat),
                "\(running)",
                "\(configured)",
                "\(total)"
            ),
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
        let activeJobs = String(format: model.text(.activeJobsFormat), "\(active)")
        let workerLabel = localizedStatus(worker)
        return HomeReadinessItem(
            title: model.text(.homeReadinessLearn),
            detail: active > 0 ? activeJobs : workerLabel,
            status: active > 0 ? model.text(.statusRunning) : workerLabel,
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

    private func localizedStatus(_ rawStatus: String) -> String {
        let value = rawStatus.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalized = value.lowercased()
        if value.isEmpty || normalized == "unknown" {
            return model.text(.statusUnknown)
        }
        if normalized.contains("setup") || normalized.contains("missing") || normalized.contains("needed") {
            return model.text(.statusSetup)
        }
        if normalized.contains("configured") {
            return model.text(.statusConfigured)
        }
        if normalized.contains("ready") {
            return model.text(.ready)
        }
        if normalized.contains("running") || normalized.contains("active") {
            return model.text(.statusRunning)
        }
        if normalized.contains("warming") || normalized.contains("warm") || normalized.contains("starting") {
            return model.text(.statusWarming)
        }
        if normalized.contains("stopped") || normalized.contains("stop") {
            return model.text(.statusStopped)
        }
        if normalized.contains("idle") {
            return model.text(.idle)
        }
        return value
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
    @State private var hovering = false

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
                    .foregroundStyle(hovering ? item.tint : ElephantTheme.faint)
                    .opacity(hovering ? 1 : 0.62)
            }
            .padding(12)
            .frame(maxWidth: .infinity, minHeight: 64, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(Color(nsColor: .controlBackgroundColor).opacity(hovering ? 0.92 : 1))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(item.tint.opacity(hovering ? 0.34 : 0.18), lineWidth: 1)
            )
            .shadow(color: item.tint.opacity(hovering ? 0.10 : 0), radius: 10, y: 5)
            .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(PressablePlainButtonStyle())
        .onHover { hovering = $0 }
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
                        title: localizedYouText(
                            model.appLanguage,
                            en: "Carry into the next reply",
                            zh: "下次回复会用到",
                            fr: "À garder pour la prochaine réponse",
                            de: "In die nächste Antwort mitnehmen"
                        ),
                        subtitle: localizedYouText(
                            model.appLanguage,
                            en: "The personal context Elephant should keep warm before it answers.",
                            zh: "这些上下文会帮助 Elephant 接上话题。",
                            fr: "Le contexte personnel qu'Elephant doit garder prêt avant de répondre.",
                            de: "Persönlicher Kontext, den Elephant vor der Antwort bereithalten soll."
                        )
                    )
                    Spacer(minLength: 0)
                    if let question = nextQuestion {
                        Pill(text: question.statusTitle, symbol: "questionmark.bubble", tint: questionTint(question))
                    }
                }

                HStack(alignment: .top, spacing: 0) {
                    HomeContinuityColumn(
                        title: localizedYouText(model.appLanguage, en: "Alive now", zh: "当前重点", fr: "En ce moment", de: "Gerade aktiv"),
                        symbol: "waveform.path.ecg",
                        tint: ElephantTheme.orange,
                        text: aliveNow
                    )
                    VerticalHairline()
                    HomeContinuityColumn(
                        title: localizedYouText(model.appLanguage, en: "How to be with you", zh: "相处偏好", fr: "Comment être avec vous", de: "Wie mit dir sein"),
                        symbol: "person.wave.2",
                        tint: ElephantTheme.accent,
                        text: relationshipMode
                    )
                    VerticalHairline()
                    HomeContinuityColumn(
                        title: localizedYouText(model.appLanguage, en: "Care to remember", zh: "注意事项", fr: "Soin à retenir", de: "Wichtige Fürsorge"),
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
                    EmptyLine(
                        symbol: "questionmark.bubble",
                        text: localizedYouText(
                            model.appLanguage,
                            en: "No open question is waiting for review.",
                            zh: "现在没有待回看的问题。",
                            fr: "Aucune question ouverte n'attend une revue.",
                            de: "Keine offene Frage wartet auf Prüfung."
                        )
                    )
                }
            }
        }
    }

    private var aliveNow: String {
        firstProfileValue(["Working on", "Current focus", "Now"])
            ?? firstFactText(lens: "pulse")
            ?? localizedYouText(
                model.appLanguage,
                en: "No current focus yet. Start a chat or diary entry and Elephant will keep the thread visible.",
                zh: "还没有当前重点。聊一聊或写篇日记后，这里会自动整理线索。",
                fr: "Aucun focus actuel. Lancez un chat ou un journal, et Elephant gardera le fil visible.",
                de: "Noch kein aktueller Fokus. Starte Chat oder Tagebuch, dann hält Elephant den Faden sichtbar."
            )
    }

    private var relationshipMode: String {
        firstProfileValue(["Relationship mode", "Communication", "Speaks"])
            ?? firstFactText(lens: "identity", topicContains: ["style", "companion", "language"])
            ?? localizedYouText(
                model.appLanguage,
                en: "Be specific, calm, and easy to correct.",
                zh: "说具体一点，语气放轻，也方便你随时纠正。",
                fr: "Être précis, calme et facile à corriger.",
                de: "Konkret, ruhig und leicht korrigierbar sein."
            )
    }

    private var careBoundary: String {
        firstProfileValue(["Safety boundaries", "Care context", "Medication allergies", "Health notes", "Food allergies"])
            ?? firstFactText(lens: "identity", topicContains: ["boundary", "care", "allergy", "health"])
            ?? localizedYouText(
                model.appLanguage,
                en: "No care boundary has been written yet.",
                zh: "还没记录需要特别注意的边界。",
                fr: "Aucune limite de soin n'a encore été écrite.",
                de: "Noch keine Fürsorgegrenze notiert."
            )
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
                Text(localizedYouText(model.appLanguage, en: "Next useful question", zh: "接下来可以问", fr: "Prochaine question utile", de: "Nächste nützliche Frage"))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                Text(question.text)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(ElephantTheme.ink)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 0)

            Button(localizedYouText(model.appLanguage, en: "Review", zh: "回看", fr: "Revoir", de: "Prüfen")) {
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
                    title: localizedYouText(
                        model.appLanguage,
                        en: "Memory shape",
                        zh: "记忆结构",
                        fr: "Structure mémoire",
                        de: "Erinnerungsstruktur"
                    ),
                    subtitle: localizedYouText(
                        model.appLanguage,
                        en: "A private overview, not a profile page. Choose a shelf only when you want detail.",
                        zh: "这里不是资料页，只显示记忆结构；需要细节时再点开。",
                        fr: "Un aperçu privé, pas une page de profil. Ouvrez un espace seulement si vous voulez le détail.",
                        de: "Eine private Übersicht, keine Profilseite. Details erst öffnen, wenn du sie brauchst."
                    )
                )

                LazyVGrid(columns: columns, spacing: 12) {
                    HomeLensColumn(
                        title: localizedLensTitle("identity", language: model.appLanguage),
                        symbol: "person.crop.circle",
                        tint: PersonalModelMapPalette.identity,
                        facts: facts(for: "identity"),
                        language: model.appLanguage,
                        summary: localizedYouText(
                            model.appLanguage,
                            en: "How Elephant should recognize your stable preferences and boundaries.",
                            zh: "Elephant 如何理解你的稳定偏好和边界。",
                            fr: "Comment Elephant reconnaît vos préférences et limites stables.",
                            de: "Wie Elephant stabile Vorlieben und Grenzen erkennt."
                        ),
                        empty: localizedYouText(
                            model.appLanguage,
                            en: "No stable identity memories yet.",
                            zh: "还没有稳定的身份记忆。",
                            fr: "Pas encore de souvenirs d'identité stables.",
                            de: "Noch keine stabilen Identitätserinnerungen."
                        )
                    )
                    HomeLensColumn(
                        title: localizedLensTitle("world", language: model.appLanguage),
                        symbol: "globe",
                        tint: PersonalModelMapPalette.world,
                        facts: facts(for: "world"),
                        language: model.appLanguage,
                        summary: localizedYouText(
                            model.appLanguage,
                            en: "People, projects, places, and context that may matter later.",
                            zh: "之后可能有用的人、项目、地点和语境。",
                            fr: "Personnes, projets, lieux et contexte qui peuvent compter plus tard.",
                            de: "Menschen, Projekte, Orte und Kontext, die später zählen können."
                        ),
                        empty: localizedYouText(
                            model.appLanguage,
                            en: "No people, places, or project memories yet.",
                            zh: "还没有关于人、地点或项目的记忆。",
                            fr: "Pas encore de souvenirs sur les personnes, lieux ou projets.",
                            de: "Noch keine Erinnerungen zu Menschen, Orten oder Projekten."
                        )
                    )
                    HomeLensColumn(
                        title: localizedLensTitle("pulse", language: model.appLanguage),
                        symbol: "waveform.path.ecg",
                        tint: PersonalModelMapPalette.pulse,
                        facts: facts(for: "pulse"),
                        language: model.appLanguage,
                        summary: localizedYouText(
                            model.appLanguage,
                            en: "Current threads that should stay fresh without becoming identity.",
                            zh: "需要保持新鲜、但不该变成身份标签的近况。",
                            fr: "Fils actuels à garder frais sans devenir une identité.",
                            de: "Aktuelle Fäden, die frisch bleiben sollen, ohne Identität zu werden."
                        ),
                        empty: localizedYouText(
                            model.appLanguage,
                            en: "No current-state memories yet.",
                            zh: "还没有关于近况的记忆。",
                            fr: "Pas encore de souvenirs sur l'état actuel.",
                            de: "Noch keine Erinnerungen zum aktuellen Zustand."
                        )
                    )
                    HomeLensColumn(
                        title: localizedLensTitle("journey", language: model.appLanguage),
                        symbol: "map",
                        tint: PersonalModelMapPalette.journey,
                        facts: facts(for: "journey"),
                        language: model.appLanguage,
                        summary: localizedYouText(
                            model.appLanguage,
                            en: "Longer arcs, decisions, and patterns that accumulate over time.",
                            zh: "长期积累下来的方向、决定和模式。",
                            fr: "Arcs longs, décisions et motifs qui s'accumulent.",
                            de: "Längere Bögen, Entscheidungen und Muster über die Zeit."
                        ),
                        empty: localizedYouText(
                            model.appLanguage,
                            en: "No journey memories yet.",
                            zh: "还没有关于长期旅程的记忆。",
                            fr: "Pas encore de souvenirs de parcours.",
                            de: "Noch keine Erinnerungen zum Weg."
                        )
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

private struct ProfileMemorySnapshot: View {
    var facts: [ProfileFact]
    var language: AppLanguage

    var body: some View {
        if facts.isEmpty {
            EmptyLine(
                symbol: "sparkles",
                text: localizedYouText(
                    language,
                    en: "No personal memories yet. Start a few specific conversations and Reflect will surface them here.",
                    zh: "还没有个人记忆。先聊几段具体的事，Reflect 会把有用线索放到这里。",
                    fr: "Pas encore de souvenirs personnels. Lancez quelques conversations précises et Reflect les fera remonter ici.",
                    de: "Noch keine persönlichen Erinnerungen. Nach einigen konkreten Gesprächen zeigt Reflect sie hier."
                )
            )
        } else {
            LazyVGrid(columns: columns, spacing: 10) {
                ForEach(Array(facts.prefix(8))) { fact in
                    ProfileMemoryChip(fact: fact, language: language)
                }
            }
        }
    }

    private var columns: [GridItem] {
        [
            GridItem(.adaptive(minimum: 230), spacing: 10)
        ]
    }
}

private struct ProfileMemoryChip: View {
    var fact: ProfileFact
    var language: AppLanguage

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(tint.opacity(0.12))
                Image(systemName: symbol)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(tint)
            }
            .frame(width: 36, height: 36)

            VStack(alignment: .leading, spacing: 4) {
                Text(localizedProfileLabel(fact.label, language: language))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(1)
                Text(fact.value.isEmpty ? fallbackValue : fact.value)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(ElephantTheme.ink)
                    .lineLimit(fact.full ? 3 : 2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .frame(maxWidth: .infinity, minHeight: 76, alignment: .topLeading)
        .background(tint.opacity(0.055), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(tint.opacity(0.22), lineWidth: 1)
        )
    }

    private var fallbackValue: String {
        localizedYouText(language, en: "Not set", zh: "未设置", fr: "Non défini", de: "Nicht festgelegt")
    }

    private var symbol: String {
        let key = fact.label.lowercased()
        if key.contains("name") { return "person.crop.circle" }
        if key.contains("gender") { return "person.2" }
        if key.contains("city") { return "location" }
        if key.contains("birth") { return "calendar" }
        if key.contains("speak") || key.contains("language") { return "character.bubble" }
        if key.contains("work") { return "briefcase" }
        if key.contains("hobbies") { return "sparkles" }
        if key.contains("health") || key.contains("allerg") || key.contains("medication") { return "cross.case" }
        if key.contains("boundary") || key.contains("safety") || key.contains("care") { return "hand.raised" }
        return "smallcircle.filled.circle"
    }

    private var tint: Color {
        let key = fact.label.lowercased()
        if key.contains("city") || key.contains("work") { return ElephantTheme.green }
        if key.contains("health") || key.contains("allerg") || key.contains("boundary") || key.contains("safety") { return ElephantTheme.orange }
        return ElephantTheme.accent
    }
}

private func localizedProfileLabel(_ label: String, language: AppLanguage) -> String {
    switch label.lowercased() {
    case "name":
        return localizedYouText(language, en: "Name", zh: "称呼", fr: "Nom", de: "Name")
    case "gender":
        return localizedYouText(language, en: "Gender", zh: "性别", fr: "Genre", de: "Geschlecht")
    case "city":
        return localizedYouText(language, en: "City", zh: "城市", fr: "Ville", de: "Stadt")
    case "birth date":
        return localizedYouText(language, en: "Birth date", zh: "生日", fr: "Date de naissance", de: "Geburtstag")
    case "speaks":
        return localizedYouText(language, en: "Speaks", zh: "语言", fr: "Langue", de: "Sprache")
    case "working on":
        return localizedYouText(language, en: "Working on", zh: "正在做", fr: "Travaille sur", de: "Arbeitet an")
    case "hobbies":
        return localizedYouText(language, en: "Hobbies", zh: "兴趣", fr: "Centres d'intérêt", de: "Interessen")
    case "relationship mode":
        return localizedYouText(language, en: "Relationship mode", zh: "相处方式", fr: "Mode relationnel", de: "Beziehungsmodus")
    case "medication allergies":
        return localizedYouText(language, en: "Medication allergies", zh: "药物过敏", fr: "Allergies médicamenteuses", de: "Medikamentenallergien")
    case "health notes":
        return localizedYouText(language, en: "Health notes", zh: "健康备注", fr: "Notes santé", de: "Gesundheitshinweise")
    case "food allergies":
        return localizedYouText(language, en: "Food allergies", zh: "食物过敏", fr: "Allergies alimentaires", de: "Lebensmittelallergien")
    case "care context":
        return localizedYouText(language, en: "Care context", zh: "照顾语境", fr: "Contexte de soin", de: "Fürsorgekontext")
    case "safety boundaries":
        return localizedYouText(language, en: "Safety boundaries", zh: "安全边界", fr: "Limites de sécurité", de: "Sicherheitsgrenzen")
    default:
        return label
    }
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
    var language: AppLanguage
    var summary: String
    var empty: String
    private let cardHeight: CGFloat = 142

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

                VStack(alignment: .leading, spacing: 8) {
                    Text(facts.isEmpty ? empty : summary)
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(3)
                        .fixedSize(horizontal: false, vertical: true)
                    if !facts.isEmpty {
                        Text(localizedYouText(
                            language,
                            en: "Click below to inspect details.",
                            zh: "需要细节时，在下方点开查看。",
                            fr: "Ouvrez ci-dessous pour voir les détails.",
                            de: "Unten öffnen, um Details zu prüfen."
                        ))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(tint)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
            .padding(14)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .clipped()
        }
        .frame(maxWidth: .infinity)
        .frame(height: cardHeight)
    }
}

private func friendlyMemoryPreview(_ text: String, language: AppLanguage) -> String {
    let lines = text
        .components(separatedBy: .newlines)
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }

    let cleaned = lines.compactMap { friendlyMemoryLine($0, language: language) }
    if !cleaned.isEmpty {
        return cleaned.prefix(2).joined(separator: language == .zh ? "；" : " · ")
    }
    return text.trimmingCharacters(in: .whitespacesAndNewlines)
}

private func friendlyMemoryLine(_ line: String, language: AppLanguage) -> String? {
    let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return nil }

    guard let separator = trimmed.firstIndex(where: { $0 == ":" || $0 == "：" }) else {
        return trimmed
    }

    let key = String(trimmed[..<separator])
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .lowercased()
        .replacingOccurrences(of: "_", with: " ")
    let value = String(trimmed[trimmed.index(after: separator)...])
        .trimmingCharacters(in: .whitespacesAndNewlines)
    guard !value.isEmpty else { return nil }

    if key.contains("personal logo") { return nil }
    if key.contains("preferred name") {
        return localizedYouText(language, en: "Prefers \(value)", zh: "称呼是 \(value)", fr: "Préfère \(value)", de: "Bevorzugt \(value)")
    }
    if key.contains("current work") {
        return localizedYouText(language, en: "Working on \(value)", zh: "正在做 \(value)", fr: "Travaille sur \(value)", de: "Arbeitet an \(value)")
    }
    if key.contains("current city") {
        return localizedYouText(language, en: "Based around \(value)", zh: "当前城市或时区是 \(value)", fr: "Basé autour de \(value)", de: "Rund um \(value)")
    }
    if key.contains("personal hobbies") {
        return localizedYouText(language, en: "Interested in \(value)", zh: "兴趣包括 \(value)", fr: "S'intéresse à \(value)", de: "Interessiert an \(value)")
    }
    if key.contains("first language") {
        let languageName = value.lowercased() == "zh" ? localizedYouText(language, en: "Chinese", zh: "中文", fr: "chinois", de: "Chinesisch") : value
        return localizedYouText(language, en: "First language is \(languageName)", zh: "第一语言是 \(languageName)", fr: "Première langue : \(languageName)", de: "Erste Sprache ist \(languageName)")
    }
    if key.contains("decision compass") {
        return localizedYouText(language, en: "Decisions favor \(value)", zh: "决策时看重 \(value)", fr: "Les décisions privilégient \(value)", de: "Entscheidungen bevorzugen \(value)")
    }
    if key.contains("inner landscape") {
        return localizedYouText(language, en: "Inner state: \(value)", zh: "内在状态：\(value)", fr: "État intérieur : \(value)", de: "Innerer Zustand: \(value)")
    }
    if key.contains("pressure pattern") {
        return localizedYouText(language, en: "Under pressure: \(value)", zh: "有压力时会 \(value)", fr: "Sous pression : \(value)", de: "Unter Druck: \(value)")
    }
    if key.contains("recovery style") {
        return localizedYouText(language, en: "Recovers through \(value)", zh: "恢复状态主要靠 \(value)", fr: "Récupère par \(value)", de: "Erholt sich durch \(value)")
    }
    if key.contains("value anchor") {
        return localizedYouText(language, en: "Values \(value)", zh: "重视 \(value)", fr: "Valorise \(value)", de: "Schätzt \(value)")
    }
    if key.contains("boundary") || key.contains("safety") || key.contains("private safety note") {
        return localizedYouText(language, en: "Care boundary: \(value)", zh: "需要注意的边界：\(value)", fr: "Limite de soin : \(value)", de: "Sorgfaltsgrenze: \(value)")
    }
    if key.contains("blog") || value.hasPrefix("http") {
        return localizedYouText(language, en: "Homepage: \(value)", zh: "个人主页：\(value)", fr: "Page personnelle : \(value)", de: "Homepage: \(value)")
    }
    return value
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
                    .help(model.text(.changeProfilePhoto))
                    .accessibilityLabel(model.text(.changeProfilePhoto))

                    Text(model.userDisplayName)
                        .font(.system(size: 25, weight: .semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                        .help(model.userDisplayName)

                    Text(model.text(.personalModelMapTitle))
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
                        TodaySignalRow(value: "\(model.snapshot.facts)", label: model.text(.reviewedFactsLabel), symbol: "checkmark.seal")
                        TodaySignalRow(value: "\(model.snapshot.waitingQuestions)", label: model.text(.questionsWaitingLabel), symbol: "questionmark.bubble", tint: ElephantTheme.orange)
                        TodaySignalRow(value: "\(model.snapshot.semanticEntries)", label: model.text(.evidencePointsLabel), symbol: "doc.text.magnifyingglass", tint: ElephantTheme.green)
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
    @State private var hovering = false

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

            UserAvatarImage(size: size * 0.68, name: model.userDisplayName, url: model.userAvatarURL)

            if editable && hovering {
                Image(systemName: "camera.fill")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 28, height: 28)
                    .background(ElephantTheme.accent, in: Circle())
                    .overlay(Circle().stroke(Color(nsColor: .windowBackgroundColor), lineWidth: 2))
                    .offset(x: size * 0.25, y: size * 0.25)
                    .transition(.opacity.combined(with: .scale(scale: 0.86)))
            }
        }
        .frame(width: size, height: size)
        .contentShape(Circle())
        .onHover { hovering = $0 }
        .animation(.easeOut(duration: 0.14), value: hovering)
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
                Text(model.snapshot.latestCompletedAt.isEmpty ? localizedYouText(model.appLanguage, en: "Reflect when ready", zh: "准备好后整理记忆", fr: "Reflect quand prêt", de: "Reflect, wenn bereit") : localizedYouText(model.appLanguage, en: "Last reflect complete", zh: "上次整理已完成", fr: "Dernier Reflect terminé", de: "Letzter Reflect abgeschlossen"))
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
            }

            VStack(alignment: .leading, spacing: 10) {
                Text(model.text(.homeHeroTitle))
                    .font(.system(size: 34, weight: .semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Text(model.text(.homeHeroSubtitle))
                    .font(.body)
                    .foregroundStyle(ElephantTheme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Button {
                model.selectedSection = .wake
                model.focusComposer()
            } label: {
                HStack {
                    Text(model.text(.typeMessagePlaceholder))
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
                TodayCommand(title: model.text(.reviewQuestions), symbol: "person.crop.circle") {
                    model.selectedSection = .you
                }
                TodayCommand(title: AppSection.diary.title(language: model.appLanguage), symbol: "book.closed") {
                    model.selectedSection = .diary
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
                    SectionLabel(
                        title: localizedYouText(model.appLanguage, en: "Respond Queue", zh: "待回答的问题", fr: "File de réponse", de: "Antwort-Warteschlange"),
                        subtitle: localizedFormat(model.appLanguage, en: "%d open", zh: "%d 个待回答", fr: "%d ouvertes", de: "%d offen", model.snapshot.waitingQuestions)
                    )
                    Spacer()
                    Button {
                        model.selectedSection = .you
                    } label: {
                        Image(systemName: "arrow.right")
                    }
                    .buttonStyle(.borderless)
                }

                if model.snapshot.sampleQuestions.isEmpty {
                    EmptyLine(symbol: "questionmark.bubble", text: localizedYouText(model.appLanguage, en: "No questions waiting right now.", zh: "现在没有待回答的问题。", fr: "Aucune question en attente.", de: "Gerade keine wartenden Fragen."))
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
                SectionLabel(title: localizedYouText(model.appLanguage, en: "Next", zh: "下一步", fr: "Suivant", de: "Nächstes"), subtitle: localizedYouText(model.appLanguage, en: "High-signal actions", zh: "现在最值得做", fr: "Actions les plus utiles", de: "Wichtige Aktionen"))
                NextActionRow(symbol: "bubble.left.and.bubble.right", title: AppSection.wake.title(language: model.appLanguage), detail: localizedYouText(model.appLanguage, en: "Continue the current thread", zh: "继续当前对话", fr: "Continuer le fil actuel", de: "Aktuellen Thread fortsetzen")) {
                    model.selectedSection = .wake
                    model.focusComposer()
                }
                NextActionRow(symbol: "brain.head.profile", title: model.text(.reflect), detail: model.isReflecting ? model.text(.statusRunning) : localizedYouText(model.appLanguage, en: "Update the queue", zh: "更新队列", fr: "Mettre la file à jour", de: "Warteschlange aktualisieren")) {
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
                SectionLabel(title: localizedYouText(model.appLanguage, en: "Quiet System", zh: "后台状态", fr: "Système discret", de: "Ruhiges System"), subtitle: localizedYouText(model.appLanguage, en: "Details live in Settings", zh: "更多细节在设置里", fr: "Détails dans Réglages", de: "Details in Einstellungen"))
                SettingsRow(label: localizedYouText(model.appLanguage, en: "Core", zh: "核心", fr: "Noyau", de: "Kern"), value: model.corePhase.label)
                SettingsRow(label: model.text(.providerTitle), value: localizedRuntimeStatus(model.snapshot.providerStatus, language: model.appLanguage))
                SettingsRow(label: localizedYouText(model.appLanguage, en: "Worker", zh: "Worker", fr: "Worker", de: "Worker"), value: localizedRuntimeStatus(model.snapshot.workerStatus, language: model.appLanguage))
            }
        }
        .frame(width: 340)
    }
}

struct WakeView: View {
    @EnvironmentObject private var model: ElephantAppModel
    @AppStorage("elephant.mac.chatHistoryVisible") private var chatHistoryVisible = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: AppSection.wake.title(language: model.appLanguage),
                subtitle: model.activeEpisodeID.isEmpty ? model.text(.newChat) : model.text(.conversationOpen),
                actionTitle: model.isReflecting ? model.text(.reflecting) : model.text(.reflect),
                actionSymbol: "brain.head.profile"
            ) {
                Task { await model.runReflect(trigger: "wake") }
            }

            HStack(alignment: .top, spacing: 14) {
                if chatHistoryVisible {
                    ThreadRailPanel()
                        .frame(width: 286)
                        .frame(maxHeight: .infinity)
                        .transition(.move(edge: .leading).combined(with: .opacity))
                }
                WakeComposerPanel(historyVisible: $chatHistoryVisible)
                    .frame(maxHeight: .infinity)
            }
            .frame(maxHeight: .infinity)
            .animation(.easeInOut(duration: 0.18), value: chatHistoryVisible)
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
                    SectionLabel(title: model.text(.threads), subtitle: model.text(.conversationHistory))
                    Spacer()
                    Button {
                        model.startNewChat()
                    } label: {
                        Image(systemName: "plus")
                    }
                    .buttonStyle(.borderless)
                    .help(model.text(.newChat))
                }

                VStack(spacing: 0) {
                    Button {
                        model.startNewChat()
                    } label: {
                        ThreadRow(
                            title: model.text(.newChat),
                            subtitle: model.activeEpisodeID.isEmpty ? model.text(.ready) : model.text(.startAnotherConversation),
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
                                    subtitle: thread.subtitle.isEmpty ? model.text(.conversation) : thread.subtitle,
                                    selected: thread.id == model.activeEpisodeID
                                )
                            }
                            .buttonStyle(.plain)
                            .contextMenu {
                                Button(model.text(.deleteConversation), role: .destructive) {
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
                            .help(model.text(.deleteConversation))
                            .accessibilityLabel("\(model.text(.deleteConversation)): \(readableTitle(thread.title))")
                        }
                    }

                    if chatThreads.isEmpty {
                        EmptyLine(symbol: "bubble.left", text: model.text(.noSavedChatsYet))
                    }
                }

                Spacer(minLength: 0)

                Divider()
                TodaySignalRow(value: "\(model.snapshot.waitingQuestions)", label: model.text(.questionsShort), symbol: "questionmark.bubble", tint: ElephantTheme.orange)
                TodaySignalRow(value: "\(model.snapshot.semanticEntries)", label: model.text(.evidenceShort), symbol: "doc.text.magnifyingglass", tint: ElephantTheme.green)
            }
            .frame(minHeight: 620, maxHeight: .infinity, alignment: .top)
        }
        .confirmationDialog(
            String(format: model.text(.deleteConversationPrompt), readableTitle(deleteCandidate?.title ?? model.text(.conversation))),
            isPresented: Binding(
                get: { deleteCandidate != nil },
                set: { if !$0 { deleteCandidate = nil } }
            )
        ) {
            Button(model.text(.deleteConversation), role: .destructive) {
                if let deleteCandidate {
                    model.deleteEpisodeThread(deleteCandidate)
                }
                deleteCandidate = nil
            }
        } message: {
            Text(model.text(.deleteConversationMessage))
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
        return meaningfulScalars.count < 2 ? model.text(.untitledChat) : trimmed
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
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Binding var historyVisible: Bool
    @StateObject private var speech = SpeechInputController()
    @FocusState private var focused: Bool
    @State private var lastScrollTargetID: UUID?
    private let chatBottomSpacerID = "chat-active-response-spacer"

    var body: some View {
        NativePanel {
            VStack(spacing: 0) {
                HStack {
                    Button {
                        historyVisible.toggle()
                    } label: {
                        Image(systemName: "sidebar.leading")
                            .font(.system(size: 14, weight: .semibold))
                            .frame(width: 28, height: 28)
                    }
                    .buttonStyle(PressablePlainButtonStyle())
                    .help(model.text(historyVisible ? .hideChatHistory : .showChatHistory))
                    .accessibilityLabel(model.text(historyVisible ? .hideChatHistory : .showChatHistory))

                    Text(model.activeEpisodeID.isEmpty ? model.text(.newConversation) : model.text(.conversation))
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
                            GeometryReader { geometry in
                                ScrollView {
                                    LazyVStack(alignment: .leading, spacing: 4) {
                                        ForEach(visibleMessages) { message in
                                            MessageBubble(message: message)
                                                .equatable()
                                                .id(message.id)
                                        }
                                        Color.clear
                                            .frame(height: responseRunway(in: geometry.size.height))
                                            .id(chatBottomSpacerID)
                                    }
                                    .padding(.vertical, 8)
                                    .padding(.horizontal, 24)
                                    .frame(maxWidth: .infinity, alignment: .top)
                                }
                            }
                        }
                    }
                    .frame(minHeight: 320, maxHeight: .infinity)
                    .onChange(of: model.chatScrollRevision) { _ in
                        let targetID = visibleMessages.last?.id
                        let targetChanged = targetID != nil && targetID != lastScrollTargetID
                        scrollToTranscriptBottom(proxy: proxy, animated: targetChanged || !model.isWakeRunning)
                        lastScrollTargetID = targetID
                    }
                    .onChange(of: model.isWakeRunning) { running in
                        guard !running else { return }
                        scrollToTranscriptBottom(proxy: proxy, animated: true)
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
                        .help(speech.isRecording ? model.text(.stopVoiceInput) : model.text(.voiceInput))

                        TextField(model.text(.typeMessagePlaceholder), text: $model.wakeDraft, axis: .vertical)
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
                        .help(model.text(.send))
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
        return model.snapshot.providerStatus == "unknown" ? model.text(.providerSetup) : model.snapshot.providerStatus
    }

    private var visibleMessages: [ChatMessage] {
        model.messages.filter { $0.role != .system }
    }

    private func responseRunway(in transcriptHeight: CGFloat) -> CGFloat {
        guard model.isWakeRunning else { return 14 }
        return min(max(transcriptHeight * 0.20, 88), 168)
    }

    private func scrollToTranscriptBottom(proxy: ScrollViewProxy, animated: Bool) {
        let action = {
            proxy.scrollTo(chatBottomSpacerID, anchor: .bottom)
        }
        guard animated && !reduceMotion else {
            action()
            return
        }
        withAnimation(.easeOut(duration: 0.16), action)
    }
}

struct ChatEmptyState: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(spacing: 18) {
            VStack(spacing: 8) {
                ElephantMascotView(
                    mood: model.wakeDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? .idle : .listening,
                    size: 356,
                    showsMemoryField: true,
                    energy: 1.55
                )
                    .accessibilityHidden(true)
                    .padding(.bottom, -8)
                Text(model.text(.askElephant))
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Text(model.text(.chatEmptySubtitle))
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.muted)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 520)
            }
            HStack(spacing: 10) {
                QuickPromptButton(title: model.text(.quickCapture), symbol: "sparkles") {
                    model.wakeDraft = model.text(.quickCaptureDraft)
                    model.focusComposer()
                }
                QuickPromptButton(title: model.text(.quickThink), symbol: "bubble.left.and.text.bubble.right") {
                    model.wakeDraft = model.text(.quickThinkDraft)
                    model.focusComposer()
                }
                QuickPromptButton(title: model.text(.quickReview), symbol: "checklist") {
                    model.wakeDraft = model.text(.quickReviewDraft)
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
        case taskList
        case quote
        case table
        case rule
        case code
    }

    var id: Int
    var kind: Kind
    var text: String
    var items: [String] = []
    var table: MarkdownTable?
}

private struct MarkdownTable: Equatable {
    var headers: [String]
    var rows: [[String]]
}

private struct MarkdownTaskItem: Identifiable, Equatable {
    var id: String { "\(checked)-\(text)" }
    var checked: Bool
    var text: String
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
                case .taskList:
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(taskItems(from: block.items)) { item in
                            HStack(alignment: .top, spacing: 7) {
                                Image(systemName: item.checked ? "checkmark.square.fill" : "square")
                                    .font(.callout.weight(.semibold))
                                    .foregroundStyle(item.checked ? ElephantTheme.accent : color.opacity(0.56))
                                    .frame(width: 18)
                                InlineMarkdownText(text: item.text, font: font, color: color)
                            }
                        }
                    }
                case .quote:
                    InlineMarkdownText(text: block.text, font: font, color: color.opacity(0.86))
                        .padding(.leading, 10)
                        .overlay(alignment: .leading) {
                            RoundedRectangle(cornerRadius: 2, style: .continuous)
                                .fill(ElephantTheme.accent.opacity(0.40))
                                .frame(width: 3)
                        }
                case .table:
                    if let table = block.table {
                        MarkdownTableView(table: table, font: font, color: color)
                    }
                case .rule:
                    Rectangle()
                        .fill(ElephantTheme.line.opacity(0.78))
                        .frame(height: 1)
                        .padding(.vertical, 5)
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

    private func taskItems(from values: [String]) -> [MarkdownTaskItem] {
        values.map { value in
            let checked = value.hasPrefix("[x] ") || value.hasPrefix("[X] ")
            let text = value.replacingOccurrences(of: #"^\[[ xX]\]\s+"#, with: "", options: .regularExpression)
            return MarkdownTaskItem(checked: checked, text: text)
        }
    }

    private var blocks: [MarkdownBlock] {
        var result: [MarkdownBlock] = []
        var paragraph: [String] = []
        var bullets: [String] = []
        var numbers: [String] = []
        var tasks: [String] = []
        var quotes: [String] = []
        var code: [String] = []
        var inCode = false

        func flushInlineBlocks() {
            flushParagraph()
            flushBullets()
            flushNumbers()
            flushTasks()
            flushQuotes()
        }

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

        func flushTasks() {
            guard !tasks.isEmpty else { return }
            result.append(MarkdownBlock(id: result.count, kind: .taskList, text: "", items: tasks))
            tasks.removeAll()
        }

        func flushQuotes() {
            guard !quotes.isEmpty else { return }
            result.append(MarkdownBlock(id: result.count, kind: .quote, text: quotes.joined(separator: "\n")))
            quotes.removeAll()
        }

        func flushCode() {
            guard !code.isEmpty else { return }
            result.append(MarkdownBlock(id: result.count, kind: .code, text: code.joined(separator: "\n")))
            code.removeAll()
        }

        let lines = text.components(separatedBy: .newlines)
        var index = 0
        while index < lines.count {
            let rawLine = lines[index]
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("```") {
                if inCode {
                    inCode = false
                    flushCode()
                } else {
                    flushInlineBlocks()
                    inCode = true
                }
                index += 1
                continue
            }
            if inCode {
                code.append(rawLine)
                index += 1
                continue
            }
            if line.isEmpty {
                flushInlineBlocks()
                index += 1
                continue
            }
            if isMarkdownRule(line) {
                flushInlineBlocks()
                result.append(MarkdownBlock(id: result.count, kind: .rule, text: ""))
                index += 1
                continue
            }
            if let table = parseTable(startingAt: index, lines: lines) {
                flushInlineBlocks()
                result.append(MarkdownBlock(id: result.count, kind: .table, text: "", table: table.value))
                index = table.nextIndex
                continue
            }
            if line.hasPrefix("### ") || line.hasPrefix("## ") || line.hasPrefix("# ") {
                flushInlineBlocks()
                result.append(MarkdownBlock(id: result.count, kind: .heading, text: line.replacingOccurrences(of: #"^#{1,3}\s+"#, with: "", options: .regularExpression)))
                index += 1
                continue
            }
            if line.hasPrefix(">") {
                flushParagraph()
                flushBullets()
                flushNumbers()
                flushTasks()
                quotes.append(line.replacingOccurrences(of: #"^>\s?"#, with: "", options: .regularExpression))
                index += 1
                continue
            }
            if let range = line.range(of: #"^[-*]\s+\[[ xX]\]\s+"#, options: .regularExpression) {
                flushParagraph()
                flushBullets()
                flushNumbers()
                flushQuotes()
                let checkedPrefix = line.range(of: #"^[-*]\s+\[[xX]\]"#, options: .regularExpression) == nil ? "[ ] " : "[x] "
                tasks.append(checkedPrefix + String(line[range.upperBound...]))
                index += 1
                continue
            }
            if line.hasPrefix("- ") || line.hasPrefix("* ") {
                flushParagraph()
                flushNumbers()
                flushTasks()
                flushQuotes()
                bullets.append(String(line.dropFirst(2)))
                index += 1
                continue
            }
            if let range = line.range(of: #"^\d+\.\s+"#, options: .regularExpression) {
                flushParagraph()
                flushBullets()
                flushTasks()
                flushQuotes()
                numbers.append(String(line[range.upperBound...]))
                index += 1
                continue
            }
            flushBullets()
            flushNumbers()
            flushTasks()
            flushQuotes()
            paragraph.append(rawLine)
            index += 1
        }

        flushInlineBlocks()
        flushCode()
        return result.isEmpty ? [MarkdownBlock(id: 0, kind: .paragraph, text: text)] : result
    }

    private func isMarkdownRule(_ line: String) -> Bool {
        line.range(of: #"^(\*\s*){3,}$|^(-\s*){3,}$|^(_\s*){3,}$"#, options: .regularExpression) != nil
    }

    private func parseTable(startingAt index: Int, lines: [String]) -> (value: MarkdownTable, nextIndex: Int)? {
        guard index + 1 < lines.count else { return nil }
        let headerLine = lines[index].trimmingCharacters(in: .whitespaces)
        let separatorLine = lines[index + 1].trimmingCharacters(in: .whitespaces)
        guard headerLine.contains("|"), isMarkdownTableSeparator(separatorLine) else { return nil }
        let headers = splitMarkdownTableRow(headerLine)
        guard headers.count > 1 else { return nil }
        var rows: [[String]] = []
        var cursor = index + 2
        while cursor < lines.count {
            let candidate = lines[cursor].trimmingCharacters(in: .whitespaces)
            guard candidate.contains("|"), !candidate.isEmpty else { break }
            let row = splitMarkdownTableRow(candidate)
            guard !row.isEmpty else { break }
            rows.append(row)
            cursor += 1
        }
        return (MarkdownTable(headers: headers, rows: rows), cursor)
    }

    private func isMarkdownTableSeparator(_ line: String) -> Bool {
        let cells = splitMarkdownTableRow(line)
        guard cells.count > 1 else { return false }
        return cells.allSatisfy { cell in
            cell.range(of: #"^:?-{3,}:?$"#, options: .regularExpression) != nil
        }
    }

    private func splitMarkdownTableRow(_ line: String) -> [String] {
        var trimmed = line.trimmingCharacters(in: .whitespaces)
        if trimmed.hasPrefix("|") { trimmed.removeFirst() }
        if trimmed.hasSuffix("|") { trimmed.removeLast() }
        return trimmed.split(separator: "|", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
    }
}

private struct MarkdownTableView: View {
    var table: MarkdownTable
    var font: Font
    var color: Color

    var body: some View {
        ScrollView(.horizontal, showsIndicators: true) {
            VStack(alignment: .leading, spacing: 0) {
                markdownRow(table.headers, header: true)
                ForEach(Array(table.rows.enumerated()), id: \.offset) { index, row in
                    markdownRow(normalized(row), header: false)
                        .background(index.isMultiple(of: 2) ? Color.clear : ElephantTheme.line.opacity(0.08))
                }
            }
            .fixedSize(horizontal: true, vertical: false)
            .background(Color(nsColor: .textBackgroundColor).opacity(0.46))
            .overlay(Rectangle().stroke(ElephantTheme.line.opacity(0.78), lineWidth: 1))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func markdownRow(_ values: [String], header: Bool) -> some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(normalized(values).enumerated()), id: \.offset) { index, value in
                MarkdownTableCell(
                    value: displayValue(value, at: index, header: header),
                    font: header ? .callout.weight(.semibold) : font,
                    color: header ? color : color.opacity(0.94),
                    width: columnWidth(at: index),
                    header: header
                )
                    .overlay(alignment: .trailing) {
                        if index < columnCount - 1 {
                            Rectangle()
                                .fill(ElephantTheme.line.opacity(0.64))
                                .frame(width: 1)
                        }
                    }
            }
        }
        .background(header ? Color(nsColor: .controlBackgroundColor).opacity(0.72) : Color.clear)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(ElephantTheme.line.opacity(header ? 0.72 : 0.34))
                .frame(height: 1)
        }
    }

    private func normalized(_ values: [String]) -> [String] {
        let count = columnCount
        if values.count >= count { return values }
        return values + Array(repeating: "", count: count - values.count)
    }

    private var columnCount: Int {
        max(table.headers.count, table.rows.map(\.count).max() ?? 0)
    }

    private func displayValue(_ value: String, at index: Int, header: Bool) -> String {
        if header && value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && isIndexColumn(index) {
            return "#"
        }
        return value
    }

    private func columnWidth(at index: Int) -> CGFloat {
        if isIndexColumn(index) {
            return 46
        }
        let header = normalizedHeader(at: index)
        if header.contains("result")
            || header.contains("output")
            || header.contains("return")
            || header.contains("detail")
            || header.contains("结果")
            || header.contains("返回")
            || header.contains("详情")
            || header.contains("résultat")
            || header.contains("ergebnis") {
            return 420
        }
        if header.contains("query")
            || header.contains("mode")
            || header.contains("查询")
            || header.contains("模式") {
            return 300
        }
        let maxLength = maxContentLength(at: index)
        if maxLength > 80 {
            return 360
        }
        if maxLength > 40 {
            return 300
        }
        if maxLength > 20 {
            return 240
        }
        if header.count <= 3 {
            return 150
        }
        return 210
    }

    private func isIndexColumn(_ index: Int) -> Bool {
        guard index == 0 else {
            return false
        }
        let header = normalizedHeader(at: index)
        let headerLooksLikeIndex = header.isEmpty || ["#", "no", "number", "index", "序号", "编号"].contains(header)
        guard headerLooksLikeIndex else { return false }
        return table.rows.allSatisfy { row in
            guard let value = row.first.map(normalizedTableText), !value.isEmpty else {
                return true
            }
            return Int(value) != nil
        }
    }

    private func normalizedHeader(at index: Int) -> String {
        guard index < table.headers.count else { return "" }
        return normalizedTableText(table.headers[index]).lowercased()
    }

    private func normalizedTableText(_ value: String) -> String {
        value
            .replacingOccurrences(of: "\u{00A0}", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func maxContentLength(at index: Int) -> Int {
        let headerLength = index < table.headers.count ? normalizedTableText(table.headers[index]).count : 0
        let rowLength = table.rows
            .map { row in index < row.count ? normalizedTableText(row[index]).count : 0 }
            .max() ?? 0
        return max(headerLength, rowLength)
    }
}

private struct MarkdownTableCell: View {
    var value: String
    var font: Font
    var color: Color
    var width: CGFloat
    var header: Bool

    var body: some View {
        InlineMarkdownText(text: value, font: font, color: color)
            .padding(.horizontal, header ? 12 : 10)
            .padding(.vertical, header ? 9 : 8)
        .frame(width: width, alignment: .leading)
        .frame(minHeight: header ? 38 : 36, alignment: .topLeading)
    }
}

struct InlineMarkdownText: View {
    var text: String
    var font: Font
    var color: Color
    var fixedHorizontal = false
    var lineLimit: Int?

    var body: some View {
        if let attributed = try? AttributedString(markdown: text) {
            Text(attributed)
                .font(font)
                .foregroundStyle(color)
                .lineLimit(lineLimit)
                .fixedSize(horizontal: fixedHorizontal, vertical: true)
                .textSelection(.enabled)
        } else {
            Text(text)
                .font(font)
                .foregroundStyle(color)
                .lineLimit(lineLimit)
                .fixedSize(horizontal: fixedHorizontal, vertical: true)
                .textSelection(.enabled)
        }
    }
}

struct MessageBubble: View, Equatable {
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
                MarkdownBody(
                    text: message.text,
                    font: message.role == .system ? .callout : .body,
                    color: textColor
                )
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
    @EnvironmentObject private var model: ElephantAppModel
    var events: [ToolUseEvent]
    var isLive = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "wrench.and.screwdriver")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(ElephantTheme.accent)
                    .frame(width: 16, height: 16)
                    .background(ElephantTheme.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 4, style: .continuous))
                Text(model.text(.toolActivity))
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink.opacity(0.72))
                Text("\(events.count)")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                    .padding(.horizontal, 4)
                    .padding(.vertical, 1)
                    .background(Color(nsColor: .controlBackgroundColor).opacity(0.74), in: Capsule())
                if isLive && hasRunningEvent {
                    Circle()
                        .fill(ElephantTheme.accent)
                        .frame(width: 5, height: 5)
                    Text(model.text(.live))
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(ElephantTheme.accent)
                }
                Spacer(minLength: 0)
            }

            ForEach(events.suffix(5)) { event in
                ToolUseEventRow(event: event)
            }
        }
        .padding(6)
        .frame(maxWidth: 480, alignment: .leading)
        .background(Color(nsColor: .textBackgroundColor).opacity(0.66), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(ElephantTheme.line.opacity(0.72), lineWidth: 1)
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
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        ElephantThinkingMark()
            .padding(.horizontal, 2)
            .padding(.vertical, 2)
            .fixedSize()
            .accessibilityLabel(model.text(.assistantThinking))
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
    @EnvironmentObject private var model: ElephantAppModel
    var event: ToolUseEvent
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            header

            if expanded && hasDetails {
                VStack(alignment: .leading, spacing: 5) {
                    if !argumentsText.isEmpty {
                        ToolUseDetailBlock(title: model.text(.toolInput), text: argumentsText, tint: ElephantTheme.accent)
                    }
                    if !resultText.isEmpty {
                        ToolUseDetailBlock(title: model.text(.toolResult), text: resultText, tint: ElephantTheme.green)
                    }
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(.horizontal, 6)
        .padding(.vertical, 4)
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.30), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .stroke(ElephantTheme.line.opacity(0.34), lineWidth: 1)
        )
        .animation(.easeInOut(duration: 0.16), value: expanded)
    }

    @ViewBuilder
    private var header: some View {
        if hasDetails {
            Button {
                expanded.toggle()
            } label: {
                headerContent
            }
            .buttonStyle(PressablePlainButtonStyle())
            .help(expanded ? model.text(.hideToolDetails) : model.text(.showToolDetails))
            .accessibilityLabel("\(displayName), \(statusText), \(expanded ? model.text(.hideToolDetails) : model.text(.showToolDetails))")
        } else {
            headerContent
        }
    }

    private var headerContent: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(statusTint)
                .frame(width: 5, height: 5)
            Text(displayName)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(ElephantTheme.ink)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: 0)
            Text(statusText)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(statusTint)
                .lineLimit(1)
                .padding(.horizontal, 5)
                .padding(.vertical, 1)
                .background(statusTint.opacity(0.10), in: Capsule())
            if hasDetails {
                Image(systemName: "chevron.right")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(ElephantTheme.faint)
                    .rotationEffect(.degrees(expanded ? 90 : 0))
                    .frame(width: 10)
            }
        }
        .contentShape(Rectangle())
    }

    private var displayName: String {
        let value = event.name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return model.text(.toolFallback) }
        if value.hasPrefix("tool.") {
            return String(value.dropFirst("tool.".count))
        }
        return value
    }

    private var statusText: String {
        let value = event.status.trimmingCharacters(in: .whitespacesAndNewlines)
        return localizedToolStatus(value.isEmpty ? "completed" : value, language: model.appLanguage)
    }

    private var argumentsText: String {
        event.arguments.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var resultText: String {
        event.result.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var hasDetails: Bool {
        !argumentsText.isEmpty || !resultText.isEmpty
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

private struct ToolUseDetailBlock: View {
    var title: String
    var text: String
    var tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title.uppercased())
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(tint)
            Text(text)
                .font(.caption2.monospaced())
                .foregroundStyle(ElephantTheme.muted)
                .lineLimit(8)
                .truncationMode(.tail)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 7)
        .padding(.vertical, 5)
        .background(tint.opacity(0.055), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .stroke(tint.opacity(0.16), lineWidth: 1)
        )
    }
}

struct YouView: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var selectedLens: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: AppSection.you.title(language: model.appLanguage),
                subtitle: model.text(.youPageSubtitle),
                actionTitle: model.text(.reflect),
                actionSymbol: "brain.head.profile"
            ) {
                Task { await model.runReflect(trigger: "manual") }
            }

            VStack(spacing: 14) {
                PersonalModelMapPanel()
                VStack(alignment: .leading, spacing: 10) {
                    SectionLabel(
                        title: localizedYouText(
                            model.appLanguage,
                            en: "Browse what Elephant carries forward",
                            zh: "看看 Elephant 会带走什么",
                            fr: "Parcourir ce qu'Elephant garde",
                            de: "Durchsehen, was Elephant mitnimmt"
                        ),
                        subtitle: localizedYouText(
                            model.appLanguage,
                            en: "Choose an area to inspect. The selected shelf opens below.",
                            zh: "选择一个区域查看，下面会展开对应的记忆。",
                            fr: "Choisissez une zone à inspecter. L'espace sélectionné s'ouvre dessous.",
                            de: "Wähle einen Bereich. Die ausgewählte Ablage öffnet sich darunter."
                        )
                    )
                    LensPartitionGrid(selectedLens: activeLensBinding)
                }
                LensFactsPager(lens: activeLens)
                QuestionFieldPanel()
            }
        }
    }

    private var activeLens: String {
        selectedLens ?? defaultLens
    }

    private var activeLensBinding: Binding<String?> {
        Binding(
            get: { selectedLens ?? defaultLens },
            set: { selectedLens = $0 }
        )
    }

    private var defaultLens: String {
        ["identity", "world", "pulse", "journey"]
            .max { left, right in
                (model.snapshot.lensCoverage[left] ?? 0) < (model.snapshot.lensCoverage[right] ?? 0)
            } ?? "identity"
    }
}

private func localizedYouText(_ language: AppLanguage, en: String, zh: String, fr: String, de: String) -> String {
    switch language {
    case .zh: return zh
    case .fr: return fr
    case .de: return de
    case .en: return en
    }
}

private func localizedFormat(_ language: AppLanguage, en: String, zh: String, fr: String, de: String, _ arguments: CVarArg...) -> String {
    String(format: localizedYouText(language, en: en, zh: zh, fr: fr, de: de), arguments: arguments)
}

private enum MacLocalDateTime {
    static func formatted(_ raw: String, language: AppLanguage, fallback: String = "n/a") -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return fallback }
        guard let date = parse(trimmed) else { return trimmed }
        return formatted(date, language: language)
    }

    static func formattedRange(_ raw: String, language: AppLanguage) -> String {
        let parts = raw.components(separatedBy: " → ")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        guard !parts.isEmpty else { return "" }
        return parts.map { formatted($0, language: language, fallback: "") }
            .filter { !$0.isEmpty }
            .joined(separator: " → ")
    }

    static func formatted(_ date: Date, language: AppLanguage) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar.current
        formatter.locale = Locale(identifier: language.localeIdentifier)
        formatter.timeZone = TimeZone.current
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return formatter.string(from: date)
    }

    static func time(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar.current
        formatter.locale = Locale.current
        formatter.timeZone = TimeZone.current
        formatter.dateFormat = "HH:mm:ss"
        return formatter.string(from: date)
    }

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
            formatter.calendar = Calendar.current
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.timeZone = TimeZone.current
            formatter.dateFormat = pattern
            if let date = formatter.date(from: text) { return date }
        }
        return nil
    }
}

private func localizedLensTitle(_ lens: String, language: AppLanguage) -> String {
    switch lens {
    case "world":
        return localizedYouText(language, en: "World", zh: "世界", fr: "Monde", de: "Welt")
    case "pulse":
        return localizedYouText(language, en: "Pulse", zh: "近况", fr: "Présent", de: "Puls")
    case "journey":
        return localizedYouText(language, en: "Journey", zh: "旅程", fr: "Parcours", de: "Weg")
    default:
        return localizedYouText(language, en: "Identity", zh: "身份", fr: "Identité", de: "Identität")
    }
}

private func localizedToolStatus(_ rawValue: String, language: AppLanguage) -> String {
    let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    if value.contains("fail") || value.contains("error") {
        return localizedYouText(language, en: "fail", zh: "失败", fr: "échec", de: "Fehler")
    }
    if value.contains("run") || value.contains("start") || value.contains("prepar") || value.contains("request") || value.contains("classif") {
        return localizedYouText(language, en: "run", zh: "运行", fr: "actif", de: "läuft")
    }
    if value.contains("cancel") || value.contains("stop") {
        return localizedYouText(language, en: "stop", zh: "停止", fr: "arrêt", de: "Stopp")
    }
    return localizedYouText(language, en: "done", zh: "完成", fr: "fait", de: "fertig")
}

private func localizedRuntimeStatus(_ rawValue: String, language: AppLanguage) -> String {
    let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    if value.contains("schedule") {
        return localizedYouText(language, en: "scheduled", zh: "已计划", fr: "planifié", de: "geplant")
    }
    if value.contains("pause") {
        return localizedYouText(language, en: "paused", zh: "已暂停", fr: "en pause", de: "pausiert")
    }
    if value.contains("ready") {
        return localizedYouText(language, en: "ready", zh: "就绪", fr: "prêt", de: "bereit")
    }
    if value.contains("complete") || value.contains("done") {
        return localizedYouText(language, en: "completed", zh: "已完成", fr: "terminé", de: "abgeschlossen")
    }
    if value.contains("fail") || value.contains("error") || value.contains("cancel") {
        return localizedYouText(language, en: "needs attention", zh: "需要处理", fr: "à vérifier", de: "prüfen")
    }
    if value.contains("run") || value.contains("active") || value.contains("start") {
        return localizedYouText(language, en: "running", zh: "运行中", fr: "en cours", de: "läuft")
    }
    return rawValue.isEmpty ? localizedYouText(language, en: "unknown", zh: "未知", fr: "inconnu", de: "unbekannt") : rawValue
}

private func localizedProviderState(_ rawValue: String, language: AppLanguage) -> String {
    let raw = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
    let value = raw.lowercased()
    if value.isEmpty || value == "unknown" {
        return localizedYouText(language, en: "setup", zh: "待设置", fr: "à configurer", de: "einrichten")
    }
    if value.contains("in use") || value.contains("active") {
        return localizedYouText(language, en: "In use", zh: "使用中", fr: "actif", de: "aktiv")
    }
    if value.contains("connected") || value.contains("configured") {
        return localizedYouText(language, en: "Connected", zh: "已连接", fr: "connecté", de: "verbunden")
    }
    if value == "use" || value.contains("setup") || value.contains("missing") || value.contains("needed") {
        return localizedYouText(language, en: "Use", zh: "使用", fr: "Utiliser", de: "Nutzen")
    }
    return raw
}

private func localizedEmbeddingState(_ rawValue: String, language: AppLanguage) -> String {
    let raw = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
    let value = raw.lowercased()
    if value.isEmpty || value == "unknown" {
        return localizedYouText(language, en: "unknown", zh: "未知", fr: "inconnu", de: "unbekannt")
    }
    if value.contains("fail") || value.contains("error") {
        return localizedYouText(language, en: "failed", zh: "失败", fr: "échec", de: "fehlgeschlagen")
    }
    if value.contains("missing") || value.contains("not found") {
        return localizedYouText(language, en: "missing", zh: "未安装", fr: "manquant", de: "fehlt")
    }
    if value.contains("download") {
        return localizedYouText(language, en: "downloading", zh: "下载中", fr: "téléchargement", de: "lädt herunter")
    }
    if value.contains("wait") {
        return localizedYouText(language, en: "waiting", zh: "等待中", fr: "en attente", de: "wartet")
    }
    if value.contains("ready") || value.contains("loaded") || value.contains("external") {
        return localizedYouText(language, en: "ready", zh: "就绪", fr: "prêt", de: "bereit")
    }
    return raw
}

struct PersonalModelSummaryPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            HStack(alignment: .center, spacing: 22) {
                MemoryOrbitView()
                    .frame(width: 104, height: 104)

                VStack(alignment: .leading, spacing: 8) {
                    Text(localizedYouText(
                        model.appLanguage,
                        en: "What Elephant remembers",
                        zh: "Elephant 记住的你",
                        fr: "Ce qu'Elephant retient",
                        de: "Was Elephant behält"
                    ))
                        .font(.title2.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                    Text(localizedYouText(
                        model.appLanguage,
                        en: "Every memory should earn its place. Correct what is off; keep what helps.",
                        zh: "每条记忆都应该有用。偏了就改掉，有帮助才留下。",
                        fr: "Chaque souvenir doit mériter sa place. Corrigez ce qui dévie, gardez ce qui aide.",
                        de: "Jede Erinnerung muss ihren Platz verdienen. Falsches korrigieren, Hilfreiches behalten."
                    ))
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.muted)
                }

                Spacer(minLength: 0)

                HStack(spacing: 12) {
                    CompactStat(value: "\(model.snapshot.lensCoverage["identity"] ?? 0)", label: localizedLensTitle("identity", language: model.appLanguage))
                    CompactStat(value: "\(model.snapshot.lensCoverage["world"] ?? 0)", label: localizedLensTitle("world", language: model.appLanguage))
                    CompactStat(value: "\(model.snapshot.lensCoverage["pulse"] ?? 0)", label: localizedLensTitle("pulse", language: model.appLanguage))
                    CompactStat(value: "\(model.snapshot.lensCoverage["journey"] ?? 0)", label: localizedLensTitle("journey", language: model.appLanguage))
                }
            }
        }
    }
}

struct PersonalModelMapPanel: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var selectedNode: PersonalGraphSelection?

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                SectionLabel(
                    title: localizedYouText(
                        model.appLanguage,
                        en: "Memory Map",
                        zh: "记忆地图",
                        fr: "Carte mémoire",
                        de: "Erinnerungskarte"
                    ),
                    subtitle: localizedYouText(
                        model.appLanguage,
                        en: "Click any dot to inspect the memory behind it.",
                        zh: "点击任意圆点，查看它背后的记忆。",
                        fr: "Cliquez sur un point pour inspecter le souvenir derrière lui.",
                        de: "Klicke auf einen Punkt, um die Erinnerung dahinter zu prüfen."
                    )
                )
                PersonalModelDotMapCanvas(userName: model.userDisplayName, snapshot: model.snapshot, selectedNode: $selectedNode, animated: true)
                    .frame(height: 500)
                if let selectedNode {
                    PersonalGraphDetailStrip(selection: selectedNode, language: model.appLanguage)
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
                        title: localizedYouText(
                            model.appLanguage,
                            en: "Questions worth asking",
                            zh: "值得确认的问题",
                            fr: "Questions qui valent la peine",
                            de: "Fragen, die sich lohnen"
                        ),
                        subtitle: localizedYouText(
                            model.appLanguage,
                            en: "Elephant should ask only when the answer changes how it helps.",
                            zh: "只有答案会改变帮助方式时，Elephant 才应该问。",
                            fr: "Elephant ne devrait demander que si la réponse change son aide.",
                            de: "Elephant sollte nur fragen, wenn die Antwort seine Hilfe verändert."
                        )
                    )
                    Spacer()
                    Text(openCountLabel)
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
                    EmptyLine(
                        symbol: "questionmark.bubble",
                        text: localizedYouText(
                            model.appLanguage,
                            en: "No questions need your attention right now.",
                            zh: "现在没有需要你确认的问题。",
                            fr: "Aucune question ne demande votre attention pour l'instant.",
                            de: "Gerade braucht keine Frage deine Aufmerksamkeit."
                        )
                    )
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
            ("open", localizedFilterTitle("open"), openCount),
            ("ready", localizedFilterTitle("ready"), model.snapshot.waitingQuestions),
            ("asked", localizedFilterTitle("asked"), model.snapshot.askedQuestions),
            ("answered", localizedFilterTitle("answered"), model.snapshot.answeredQuestions),
            ("dismissed", localizedFilterTitle("dismissed"), model.snapshot.dismissedQuestions)
        ]
    }

    private var openCountLabel: String {
        localizedYouText(
            model.appLanguage,
            en: "\(openCount) open",
            zh: "\(openCount) 个待确认",
            fr: "\(openCount) ouvertes",
            de: "\(openCount) offen"
        )
    }

    private var openCount: Int {
        model.snapshot.waitingQuestions + model.snapshot.askedQuestions
    }

    private func localizedFilterTitle(_ id: String) -> String {
        switch id {
        case "ready":
            return localizedYouText(model.appLanguage, en: "Ready", zh: "可回答", fr: "Prêtes", de: "Bereit")
        case "asked":
            return localizedYouText(model.appLanguage, en: "Asked", zh: "已问过", fr: "Posées", de: "Gefragt")
        case "answered":
            return localizedYouText(model.appLanguage, en: "Learned", zh: "已学到", fr: "Apprises", de: "Gelernt")
        case "dismissed":
            return localizedYouText(model.appLanguage, en: "Dismissed", zh: "已忽略", fr: "Ignorées", de: "Verworfen")
        default:
            return localizedYouText(model.appLanguage, en: "Open", zh: "待确认", fr: "Ouvertes", de: "Offen")
        }
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
                    Text([question.lastAskedSurface, MacLocalDateTime.formatted(question.lastAskedAt, language: model.appLanguage, fallback: "")].filter { !$0.isEmpty }.joined(separator: " · "))
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

struct PersonalGraphSelection: Identifiable, Equatable {
    var id: String
    var title: String
    var subtitle: String
    var lens: String
    var kind: String
    var count: Int
    var detail: String
    var facts: [String]

    var accessibilityLabel: String {
        [title, subtitle, kind, "\(count)"].filter { !$0.isEmpty }.joined(separator: ", ")
    }
}

private enum PersonalModelMapPalette {
    static let identity = ElephantTheme.accent
    static let world = ElephantTheme.green
    static let pulse = Color(red: 0.90, green: 0.65, blue: 0.14)
    static let journey = Color(red: 0.86, green: 0.24, blue: 0.24)
}

struct PersonalModelDotMapCanvas: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var userName: String
    var snapshot: DashboardSnapshot
    @Binding var selectedNode: PersonalGraphSelection?
    var animated = true

    var body: some View {
        GeometryReader { proxy in
            if animated && !reduceMotion {
                TimelineView(.animation(minimumInterval: 1.0 / 24.0)) { timeline in
                    mapContent(size: proxy.size, seconds: timeline.date.timeIntervalSinceReferenceDate)
                }
            } else {
                mapContent(size: proxy.size, seconds: 0)
            }
        }
        .accessibilityLabel("Personal Model map")
    }

    @ViewBuilder
    private func mapContent(size: CGSize, seconds: TimeInterval) -> some View {
        let layout = buildLayout(in: size, seconds: seconds)

        ZStack {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(
                    RadialGradient(
                        colors: [ElephantTheme.green.opacity(0.07), ElephantTheme.accent.opacity(0.035), Color.clear],
                        center: .center,
                        startRadius: 28,
                        endRadius: max(size.width, size.height) * 0.76
                    )
                )

            Canvas { context, _ in
                drawBackgroundField(in: &context, size: size, seconds: seconds)
                for edge in layout.edges {
                    draw(edge: edge, in: &context, seconds: seconds)
                }
                for node in layout.nodes {
                    draw(node: node, selected: selectedNode?.id == node.selection.id, in: &context, seconds: seconds)
                }
            }

            Rectangle()
                .fill(Color.clear)
                .contentShape(Rectangle())
                .gesture(
                    SpatialTapGesture()
                        .onEnded { value in
                            if let selection = nearestSelection(to: value.location, in: layout) {
                                selectedNode = selection
                            }
                        }
                )
                .accessibilityLabel("Personal Model map")
                .help("Click a dot to inspect memory.")
        }
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private var centerValue: String {
        let trimmed = userName.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty || trimmed == "You" ? "Personal Model" : trimmed
    }

    private func buildLayout(in size: CGSize, seconds: TimeInterval) -> PersonalDotMapLayout {
        let centerBase = CGPoint(x: size.width * 0.50, y: size.height * 0.50)
        let center = drifting(centerBase, id: "center", radius: 3, seconds: seconds)
        let graphRadius = min(size.width, size.height) * (size.width > size.height * 1.45 ? 0.48 : 0.43)
        var nodes: [PersonalDotMapNode] = [
            PersonalDotMapNode(
                id: "center",
                tint: ElephantTheme.accent,
                kind: .center,
                position: center,
                radius: 18,
                selection: PersonalGraphSelection(
                    id: "overview",
                    title: centerValue,
                    subtitle: "Personal Model",
                    lens: "overview",
                    kind: "overview",
                    count: snapshot.personalModelFacts.count,
                    detail: "A private map of how Elephant organizes memory. Open a branch when you want detail.",
                    facts: []
                )
            )
        ]
        var edges: [PersonalDotMapEdge] = []

        for spec in branchSpecs {
            let facts = facts(for: spec.id)
            let categories = categories(for: facts, lensID: spec.id)
            let lensCount = facts.isEmpty ? (snapshot.lensCoverage[spec.id] ?? 0) : facts.count
            let lensBase = point(from: centerBase, angle: spec.angle, radius: graphRadius * 0.66)
            let lensRadius = min(15, 10 + CGFloat(lensCount) * 0.18)
            let lensPoint = drifting(lensBase, id: "lens-\(spec.id)", radius: 4, seconds: seconds)
            let lensNode = PersonalDotMapNode(
                id: "lens-\(spec.id)",
                tint: spec.tint,
                kind: .lens,
                position: lensPoint,
                radius: lensRadius,
                selection: PersonalGraphSelection(
                    id: "lens-\(spec.id)",
                    title: spec.title,
                    subtitle: "\(lensCount) facts",
                    lens: spec.id,
                    kind: "lens",
                    count: lensCount,
                    detail: spec.description,
                    facts: Array(facts.prefix(5)).map(\.text)
                )
            )
            nodes.append(lensNode)
            edges.append(
                PersonalDotMapEdge(
                    fromID: "center",
                    toID: lensNode.id,
                    from: center,
                    to: lensPoint,
                    tint: spec.tint,
                    strength: 0.44
                )
            )

            let visibleCategories = categories.isEmpty
                ? [PersonalDotMapCategory(id: "\(spec.id)-empty", title: "No facts yet", count: 0, facts: [])]
                : categories
            for (categoryIndex, category) in visibleCategories.enumerated() {
                let categoryAngle = fanAngle(base: spec.angle, index: categoryIndex, count: visibleCategories.count, spread: .pi * 1.08)
                let densityBoost = min(0.16, CGFloat(category.count) * 0.012)
                let categoryRadius = graphRadius * (0.46 + ringOffset(index: categoryIndex) * 0.10 + densityBoost)
                let categoryBase = bounded(point(from: lensBase, angle: categoryAngle, radius: categoryRadius), in: size, margin: 42)
                let categoryPoint = drifting(categoryBase, id: "category-\(spec.id)-\(category.id)", radius: 5, seconds: seconds)
                let categoryNodeID = "category-\(spec.id)-\(category.id)"
                nodes.append(
                    PersonalDotMapNode(
                        id: categoryNodeID,
                        tint: spec.tint,
                        kind: .category,
                        position: categoryPoint,
                        radius: min(12, 6.5 + CGFloat(category.count) * 0.22),
                        selection: PersonalGraphSelection(
                            id: "category-\(spec.id)-\(category.id)",
                            title: category.title,
                            subtitle: "\(category.count) facts",
                            lens: spec.id,
                            kind: "topic",
                            count: category.count,
                            detail: "Topic cluster inside \(spec.title).",
                            facts: Array(category.facts.prefix(5)).map(\.text)
                        )
                    )
                )
                edges.append(
                    PersonalDotMapEdge(
                        fromID: lensNode.id,
                        toID: categoryNodeID,
                        from: lensPoint,
                        to: categoryPoint,
                        tint: spec.tint,
                        strength: 0.30
                    )
                )

                let visibleFacts = category.facts
                for (factIndex, fact) in visibleFacts.enumerated() {
                    let factAngle = factOrbitAngle(index: factIndex, count: visibleFacts.count, seed: fact.id)
                    let factBase = bounded(
                        point(from: categoryBase, angle: factAngle, radius: factOrbitRadius(index: factIndex, total: visibleFacts.count)),
                        in: size,
                        margin: 34
                    )
                    let factPoint = drifting(
                        factBase,
                        id: "fact-\(fact.id)",
                        radius: factDriftRadius(total: visibleFacts.count),
                        seconds: seconds
                    )
                    let factNodeID = "fact-\(fact.id)"
                    let factRadius = 4.8 + CGFloat(fact.id.count % 4) * 0.35
                    nodes.append(
                        PersonalDotMapNode(
                            id: factNodeID,
                            tint: spec.tint,
                            kind: .fact,
                            position: factPoint,
                            radius: factRadius,
                            selection: PersonalGraphSelection(
                                id: factNodeID,
                                title: fact.topic.isEmpty ? category.title : fact.topic,
                                subtitle: spec.title,
                                lens: spec.id,
                                kind: "fact",
                                count: 1,
                                detail: fact.detail.isEmpty ? fact.status : fact.detail,
                                facts: [fact.text]
                            )
                        )
                    )
                    edges.append(
                        PersonalDotMapEdge(
                            fromID: categoryNodeID,
                            toID: factNodeID,
                            from: categoryPoint,
                            to: factPoint,
                            tint: spec.tint,
                            strength: 0.22
                        )
                    )
                }
            }
        }

        return resolvedLayout(nodes: nodes, edges: edges, in: size)
    }

    private var branchSpecs: [PersonalDotMapBranchSpec] {
        [
            PersonalDotMapBranchSpec(
                id: "identity",
                title: "Identity",
                description: "Stable preferences, identity anchors, names, profile links, and self-description.",
                tint: PersonalModelMapPalette.identity,
                angle: -.pi * 0.22
            ),
            PersonalDotMapBranchSpec(
                id: "world",
                title: "World",
                description: "People, projects, places, organizations, and external context.",
                tint: PersonalModelMapPalette.world,
                angle: -.pi * 0.78
            ),
            PersonalDotMapBranchSpec(
                id: "pulse",
                title: "Pulse",
                description: "Current state, open loops, live needs, blockers, and questions to revisit.",
                tint: PersonalModelMapPalette.pulse,
                angle: .pi * 0.22
            ),
            PersonalDotMapBranchSpec(
                id: "journey",
                title: "Journey",
                description: "Long-term direction, milestones, narratives, and evolving goals.",
                tint: PersonalModelMapPalette.journey,
                angle: .pi * 0.78
            )
        ]
    }

    private func facts(for lensID: String) -> [PersonalModelFact] {
        snapshot.personalModelFacts.filter { fact in
            fact.status.lowercased() != "deleted" && normalizedLens(for: fact) == lensID
        }
    }

    private func categories(for facts: [PersonalModelFact], lensID: String) -> [PersonalDotMapCategory] {
        var buckets: [String: [PersonalModelFact]] = [:]
        for fact in facts {
            let path = topicPath(for: fact, lensID: lensID)
            let category = path.first ?? "facts"
            buckets[category, default: []].append(fact)
        }
        return buckets.map { key, value in
            PersonalDotMapCategory(id: key, title: key, count: value.count, facts: value)
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
            return ["facts"]
        }
        return Array(parts.prefix(3))
    }

    private func cleanTopicLabel(_ value: String) -> String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count > 22 else { return trimmed }
        let end = trimmed.index(trimmed.startIndex, offsetBy: 22)
        return String(trimmed[..<end])
    }

    private func drawBackgroundField(in context: inout GraphicsContext, size: CGSize, seconds: TimeInterval) {
        let center = CGPoint(x: size.width * 0.50, y: size.height * 0.50)
        for ring in [0.34, 0.50, 0.66, 0.82] {
            let width = size.width * CGFloat(ring)
            let height = size.height * CGFloat(ring * 0.78)
            let rect = CGRect(x: center.x - width / 2, y: center.y - height / 2, width: width, height: height)
            context.stroke(Path(ellipseIn: rect), with: .color(ElephantTheme.line.opacity(0.10)), lineWidth: 0.7)
        }
        for index in 0..<36 {
            let x = size.width * CGFloat(unit("field-x-\(index)"))
            let y = size.height * CGFloat(unit("field-y-\(index)"))
            let pulse = 0.04 + 0.04 * sin(seconds * 0.65 + Double(index) * 0.37)
            let rect = CGRect(x: x - 1, y: y - 1, width: 2, height: 2)
            context.fill(Path(ellipseIn: rect), with: .color(ElephantTheme.accent.opacity(pulse)))
        }
        context.fill(
            Path(ellipseIn: CGRect(x: center.x - 64, y: center.y - 64, width: 128, height: 128)),
            with: .color(ElephantTheme.green.opacity(0.035))
        )
    }

    private func draw(edge: PersonalDotMapEdge, in context: inout GraphicsContext, seconds: TimeInterval) {
        var path = Path()
        path.move(to: edge.from)
        let dx = edge.to.x - edge.from.x
        let pulse = 0.018 * (0.5 + 0.5 * sin(seconds * 0.9 + Double(edge.from.x + edge.to.y) * 0.01))
        path.addCurve(
            to: edge.to,
            control1: CGPoint(x: edge.from.x + dx * 0.42, y: edge.from.y),
            control2: CGPoint(x: edge.from.x + dx * 0.58, y: edge.to.y)
        )
        context.stroke(
            path,
            with: .color(edge.tint.opacity(edge.strength + pulse)),
            style: StrokeStyle(lineWidth: edge.strength > 0.35 ? 1.05 : 0.8, lineCap: .round)
        )
    }

    private func draw(node: PersonalDotMapNode, selected: Bool, in context: inout GraphicsContext, seconds: TimeInterval) {
        let fillOpacity: Double
        let strokeOpacity: Double
        switch node.kind {
        case .center:
            fillOpacity = 0.90
            strokeOpacity = 0.34
        case .lens:
            fillOpacity = 0.90
            strokeOpacity = 0.28
        case .category:
            fillOpacity = 0.62
            strokeOpacity = 0.20
        case .fact:
            fillOpacity = 0.82
            strokeOpacity = 0.16
        }

        let breath = node.kind == .center && animated && !reduceMotion ? breathing(at: seconds) : 0
        let selectedPulse = selected && animated && !reduceMotion ? 0.5 + 0.5 * sin(seconds * 2.2) : 0
        let radius = (selected ? node.radius * 1.14 : node.radius) * (1.0 + breath * 0.025)
        if node.kind == .center {
            drawMemoryCore(at: node.position, radius: radius, tint: node.tint, selected: selected, breath: breath, selectedPulse: selectedPulse, seconds: seconds, in: &context)
            return
        }
        let rect = CGRect(
            x: node.position.x - radius,
            y: node.position.y - radius,
            width: radius * 2,
            height: radius * 2
        )
        if selected {
            let aura = rect.insetBy(dx: -11 - selectedPulse * 4, dy: -11 - selectedPulse * 4)
            context.fill(Path(ellipseIn: aura), with: .color(node.tint.opacity(0.11 + selectedPulse * 0.035)))
            context.stroke(Path(ellipseIn: aura), with: .color(node.tint.opacity(0.18 + selectedPulse * 0.08)), lineWidth: 1.2)
        }
        context.fill(Path(ellipseIn: rect), with: .color(node.tint.opacity(fillOpacity)))
        context.stroke(Path(ellipseIn: rect.insetBy(dx: -3, dy: -3)), with: .color(node.tint.opacity(selected ? 0.74 : strokeOpacity)), lineWidth: selected ? 2.0 : 1.0)
    }

    private func drawMemoryCore(
        at position: CGPoint,
        radius: CGFloat,
        tint: Color,
        selected: Bool,
        breath: CGFloat,
        selectedPulse: CGFloat,
        seconds: TimeInterval,
        in context: inout GraphicsContext
    ) {
        let outerRadius = radius * (2.18 + breath * 0.09)
        let outerRect = CGRect(
            x: position.x - outerRadius,
            y: position.y - outerRadius,
            width: outerRadius * 2,
            height: outerRadius * 2
        )
        context.fill(Path(ellipseIn: outerRect), with: .color(ElephantTheme.mint.opacity(0.055 + breath * 0.018)))
        context.stroke(Path(ellipseIn: outerRect.insetBy(dx: 9, dy: 9)), with: .color(tint.opacity(0.095 + breath * 0.025)), lineWidth: 0.9)

        if selected {
            let selectedRect = outerRect.insetBy(dx: -6 - selectedPulse * 5, dy: -6 - selectedPulse * 5)
            context.stroke(Path(ellipseIn: selectedRect), with: .color(tint.opacity(0.18 + selectedPulse * 0.08)), lineWidth: 1.4)
        }

        let orbitRadius = radius * 1.45
        let orbitRect = CGRect(
            x: position.x - orbitRadius,
            y: position.y - orbitRadius,
            width: orbitRadius * 2,
            height: orbitRadius * 2
        )
        context.stroke(Path(ellipseIn: orbitRect), with: .color(tint.opacity(0.16)), lineWidth: 1.0)

        let rotation = CGFloat(seconds * 0.42)
        for index in 0..<3 {
            let angle = rotation + CGFloat(index) * (.pi * 2 / 3)
            let dot = CGPoint(
                x: position.x + cos(angle) * orbitRadius,
                y: position.y + sin(angle) * orbitRadius
            )
            let satelliteRadius = max(1.8, radius * 0.11)
            let satelliteRect = CGRect(
                x: dot.x - satelliteRadius,
                y: dot.y - satelliteRadius,
                width: satelliteRadius * 2,
                height: satelliteRadius * 2
            )
            context.fill(Path(ellipseIn: satelliteRect), with: .color(tint.opacity(index == 0 ? 0.82 : 0.48)))
        }

        let bodyRadius = radius * 1.10
        let bodyRect = CGRect(
            x: position.x - bodyRadius,
            y: position.y - bodyRadius,
            width: bodyRadius * 2,
            height: bodyRadius * 2
        )
        context.fill(Path(ellipseIn: bodyRect), with: .color(ElephantTheme.elevated.opacity(0.96)))
        context.stroke(Path(ellipseIn: bodyRect), with: .color(tint.opacity(0.26)), lineWidth: 1.2)

        let seedRadius = max(1.7, radius * 0.095)
        let seedOrbit = radius * 0.37
        context.fill(
            Path(ellipseIn: CGRect(x: position.x - seedRadius * 1.12, y: position.y - seedRadius * 1.12, width: seedRadius * 2.24, height: seedRadius * 2.24)),
            with: .color(ElephantTheme.ink.opacity(0.82))
        )
        for index in 0..<6 {
            let angle = CGFloat(index) * (.pi / 3) - .pi / 6
            let dot = CGPoint(
                x: position.x + cos(angle) * seedOrbit,
                y: position.y + sin(angle) * seedOrbit
            )
            let dotRect = CGRect(
                x: dot.x - seedRadius,
                y: dot.y - seedRadius,
                width: seedRadius * 2,
                height: seedRadius * 2
            )
            context.fill(Path(ellipseIn: dotRect), with: .color(tint.opacity(0.70)))
            context.stroke(Path(ellipseIn: dotRect.insetBy(dx: -1.6, dy: -1.6)), with: .color(tint.opacity(0.12)), lineWidth: 0.8)
        }
    }

    private func breathing(at seconds: TimeInterval) -> CGFloat {
        CGFloat(0.5 + 0.5 * sin(seconds * 0.72))
    }

    private func nearestSelection(to point: CGPoint, in layout: PersonalDotMapLayout) -> PersonalGraphSelection? {
        layout.nodes
            .map { node -> (node: PersonalDotMapNode, distance: CGFloat) in
                let dx = node.position.x - point.x
                let dy = node.position.y - point.y
                return (node, sqrt(dx * dx + dy * dy))
            }
            .filter { item in
                item.distance <= max(34, item.node.radius + 16)
            }
            .min { lhs, rhs in
                lhs.distance < rhs.distance
            }?
            .node
            .selection
    }

    private func point(from origin: CGPoint, angle: CGFloat, radius: CGFloat) -> CGPoint {
        CGPoint(
            x: origin.x + cos(angle) * radius,
            y: origin.y + sin(angle) * radius
        )
    }

    private func fanAngle(base: CGFloat, index: Int, count: Int, spread: CGFloat) -> CGFloat {
        guard count > 1 else { return base }
        let centered = CGFloat(index) / CGFloat(count - 1) - 0.5
        let wobble = signedUnit("category-angle-\(index)-\(count)") * 0.10
        return base + centered * spread + wobble
    }

    private func factOrbitAngle(index: Int, count: Int, seed: String) -> CGFloat {
        guard count > 0 else { return 0 }
        let goldenAngle = CGFloat.pi * (3 - sqrt(5))
        let base = CGFloat(index) * goldenAngle
        return base + signedUnit("fact-angle-\(seed)") * 0.18
    }

    private func factOrbitRadius(index: Int, total: Int) -> CGFloat {
        let ring = CGFloat(index / 8)
        let base: CGFloat
        if total > 14 {
            base = 52
        } else if total > 8 {
            base = 44
        } else {
            base = 34
        }
        return base + ring * 31 + CGFloat(index % 4) * 5
    }

    private func factDriftRadius(total: Int) -> CGFloat {
        total > 8 ? 5 : 6
    }

    private func resolvedLayout(nodes: [PersonalDotMapNode], edges: [PersonalDotMapEdge], in size: CGSize) -> PersonalDotMapLayout {
        let resolvedNodes = resolveCollisions(nodes, in: size)
        var positions: [String: CGPoint] = [:]
        for node in resolvedNodes {
            positions[node.id] = node.position
        }
        let resolvedEdges = edges.map { edge in
            PersonalDotMapEdge(
                fromID: edge.fromID,
                toID: edge.toID,
                from: positions[edge.fromID] ?? edge.from,
                to: positions[edge.toID] ?? edge.to,
                tint: edge.tint,
                strength: edge.strength
            )
        }
        return PersonalDotMapLayout(nodes: resolvedNodes, edges: resolvedEdges)
    }

    private func resolveCollisions(_ nodes: [PersonalDotMapNode], in size: CGSize) -> [PersonalDotMapNode] {
        guard nodes.count > 1 else { return nodes }
        var resolved = nodes
        for _ in 0..<16 {
            var offsets = Array(repeating: CGSize.zero, count: resolved.count)
            var moved = false
            for lhsIndex in 0..<resolved.count {
                for rhsIndex in (lhsIndex + 1)..<resolved.count {
                    let lhs = resolved[lhsIndex]
                    let rhs = resolved[rhsIndex]
                    let minimumDistance = collisionDistance(lhs, rhs)
                    let dx = lhs.position.x - rhs.position.x
                    let dy = lhs.position.y - rhs.position.y
                    let distance = max(0.1, sqrt(dx * dx + dy * dy))
                    let overlap = minimumDistance - distance
                    guard overlap > 0 else { continue }

                    let direction: CGPoint
                    if distance <= 0.2 {
                        let angle = CGFloat(unit("collision-\(lhs.id)-\(rhs.id)")) * .pi * 2
                        direction = CGPoint(x: cos(angle), y: sin(angle))
                    } else {
                        direction = CGPoint(x: dx / distance, y: dy / distance)
                    }
                    let lhsMobility = collisionMobility(lhs.kind)
                    let rhsMobility = collisionMobility(rhs.kind)
                    let totalMobility = lhsMobility + rhsMobility
                    guard totalMobility > 0 else { continue }

                    let push = overlap * 0.58
                    offsets[lhsIndex].width += direction.x * push * (lhsMobility / totalMobility)
                    offsets[lhsIndex].height += direction.y * push * (lhsMobility / totalMobility)
                    offsets[rhsIndex].width -= direction.x * push * (rhsMobility / totalMobility)
                    offsets[rhsIndex].height -= direction.y * push * (rhsMobility / totalMobility)
                    moved = true
                }
            }
            if !moved { break }
            for index in resolved.indices {
                let mobility = collisionMobility(resolved[index].kind)
                guard mobility > 0 else { continue }
                let anchor = nodes[index].position
                var position = CGPoint(
                    x: resolved[index].position.x + offsets[index].width,
                    y: resolved[index].position.y + offsets[index].height
                )
                let anchorPull = max(0.02, 0.08 - mobility * 0.035)
                position.x += (anchor.x - position.x) * anchorPull
                position.y += (anchor.y - position.y) * anchorPull
                resolved[index].position = bounded(position, in: size, margin: boundaryMargin(for: resolved[index]))
            }
        }
        return resolved
    }

    private func collisionDistance(_ lhs: PersonalDotMapNode, _ rhs: PersonalDotMapNode) -> CGFloat {
        visualRadius(for: lhs) + visualRadius(for: rhs) + collisionPadding(lhs.kind, rhs.kind)
    }

    private func visualRadius(for node: PersonalDotMapNode) -> CGFloat {
        switch node.kind {
        case .center:
            return node.radius * 2.32
        case .lens:
            return node.radius + 8
        case .category:
            return node.radius + 7
        case .fact:
            return node.radius + 5
        }
    }

    private func collisionPadding(_ lhs: PersonalDotMapNodeKind, _ rhs: PersonalDotMapNodeKind) -> CGFloat {
        switch (lhs, rhs) {
        case (.fact, .fact):
            return 7
        case (.category, .fact), (.fact, .category):
            return 9
        default:
            return 12
        }
    }

    private func collisionMobility(_ kind: PersonalDotMapNodeKind) -> CGFloat {
        switch kind {
        case .center:
            return 0
        case .lens:
            return 0.22
        case .category:
            return 0.58
        case .fact:
            return 1
        }
    }

    private func boundaryMargin(for node: PersonalDotMapNode) -> CGFloat {
        visualRadius(for: node) + 10
    }

    private func ringOffset(index: Int) -> CGFloat {
        CGFloat(index % 4)
    }

    private func bounded(_ point: CGPoint, in size: CGSize, margin: CGFloat) -> CGPoint {
        CGPoint(
            x: clamp(point.x, min: margin, max: max(margin, size.width - margin)),
            y: clamp(point.y, min: margin, max: max(margin, size.height - margin))
        )
    }

    private func drifting(_ point: CGPoint, id: String, radius: CGFloat, seconds: TimeInterval) -> CGPoint {
        guard !reduceMotion else { return point }
        let phase = unit(id) * .pi * 2
        let speed = 0.22 + unit("speed-\(id)") * 0.18
        return CGPoint(
            x: point.x + CGFloat(sin(seconds * speed + phase)) * radius,
            y: point.y + CGFloat(cos(seconds * (speed * 0.82) + phase * 0.7)) * radius
        )
    }

    private func unit(_ value: String) -> Double {
        var hash: UInt64 = 1469598103934665603
        for scalar in value.unicodeScalars {
            hash ^= UInt64(scalar.value)
            hash &*= 1099511628211
        }
        return Double(hash % 10_000) / 10_000.0
    }

    private func signedUnit(_ value: String) -> CGFloat {
        CGFloat(unit(value) * 2.0 - 1.0)
    }

    private func clamp(_ value: CGFloat, min: CGFloat, max: CGFloat) -> CGFloat {
        Swift.min(Swift.max(value, min), max)
    }
}

private struct PersonalDotMapBranchSpec {
    var id: String
    var title: String
    var description: String
    var tint: Color
    var angle: CGFloat
}

private struct PersonalDotMapCategory: Identifiable {
    var id: String
    var title: String
    var count: Int
    var facts: [PersonalModelFact]
}

private enum PersonalDotMapNodeKind {
    case center
    case lens
    case category
    case fact
}

private struct PersonalDotMapNode: Identifiable {
    var id: String
    var tint: Color
    var kind: PersonalDotMapNodeKind
    var position: CGPoint
    var radius: CGFloat
    var selection: PersonalGraphSelection
}

private struct PersonalDotMapEdge {
    var fromID: String
    var toID: String
    var from: CGPoint
    var to: CGPoint
    var tint: Color
    var strength: Double
}

private struct PersonalDotMapLayout {
    var nodes: [PersonalDotMapNode]
    var edges: [PersonalDotMapEdge]
}

struct PersonalGraphDetailStrip: View {
    var selection: PersonalGraphSelection
    var language: AppLanguage

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(selection.title)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Pill(text: selection.kind, symbol: "circle.fill", tint: tint)
                Spacer()
                Text(countLabel)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
            }
            if !detailText.isEmpty {
                Text(detailText)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(2)
            }
            if selection.lens == "overview" {
                Text(localizedYouText(
                    language,
                    en: "No personal profile fields are shown here. Select a branch only when you need to inspect memory.",
                    zh: "这里不展示个人资料字段；需要检查记忆时，再选择具体分支。",
                    fr: "Aucun champ de profil personnel n'est affiché ici. Sélectionnez une branche seulement si nécessaire.",
                    de: "Hier werden keine Profilfelder angezeigt. Wähle einen Zweig nur, wenn du Erinnerungen prüfen willst."
                ))
                .font(.callout)
                .foregroundStyle(ElephantTheme.muted)
                .fixedSize(horizontal: false, vertical: true)
            } else if selection.facts.isEmpty {
                EmptyLine(
                    symbol: "circle.grid.cross",
                    text: localizedYouText(
                        language,
                        en: "No reviewable memories in this area yet.",
                        zh: "这个区域还没有可回看的记忆。",
                        fr: "Pas encore de souvenirs vérifiables dans cette zone.",
                        de: "In diesem Bereich gibt es noch keine prüfbaren Erinnerungen."
                    )
                )
            } else {
                ForEach(Array(selection.facts.prefix(3).enumerated()), id: \.offset) { _, fact in
                    Text(friendlyMemoryPreview(fact, language: language))
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

    private var countLabel: String {
        localizedYouText(
            language,
            en: "\(selection.count) memories",
            zh: "\(selection.count) 条记忆",
            fr: "\(selection.count) souvenirs",
            de: "\(selection.count) Erinnerungen"
        )
    }

    private var detailText: String {
        if selection.lens == "overview" {
            return localizedYouText(
                language,
                en: "A private map of how Elephant organizes memory.",
                zh: "Elephant 如何组织记忆的一张私有地图。",
                fr: "Une carte privée de l'organisation de la mémoire par Elephant.",
                de: "Eine private Karte, wie Elephant Erinnerung organisiert."
            )
        }
        return selection.detail
    }

    private var tint: Color {
        switch selection.lens {
        case "world": return ElephantTheme.green
        case "pulse": return ElephantTheme.orange
        case "journey": return ElephantTheme.accent.opacity(0.82)
        default: return ElephantTheme.accent
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
                tint: PersonalModelMapPalette.identity,
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
                tint: PersonalModelMapPalette.world,
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
                tint: PersonalModelMapPalette.pulse,
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
                tint: PersonalModelMapPalette.journey,
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
    @Binding var selectedLens: String?

    var body: some View {
        LazyVGrid(columns: columns, spacing: 14) {
            ForEach(partitions) { item in
                Button {
                    selectedLens = item.id
                } label: {
                    LensPartitionCard(item: item, selected: selectedLens == item.id)
                }
                .buttonStyle(.plain)
                .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .help(item.helpText)
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
                title: localizedLensTitle("identity", language: model.appLanguage),
                value: "\(model.snapshot.lensCoverage["identity"] ?? 0)",
                subtitle: localizedYouText(
                    model.appLanguage,
                    en: "Stable preferences, roles, and self-knowledge.",
                    zh: "稳定偏好、角色和自我理解。",
                    fr: "Préférences stables, rôles et connaissance de soi.",
                    de: "Stabile Vorlieben, Rollen und Selbstwissen."
                ),
                symbol: "person.crop.circle",
                tint: PersonalModelMapPalette.identity,
                helpText: localizedYouText(model.appLanguage, en: "Show identity memories", zh: "查看身份记忆", fr: "Afficher les souvenirs d'identité", de: "Identitätserinnerungen anzeigen")
            ),
            LensPartition(
                id: "world",
                title: localizedLensTitle("world", language: model.appLanguage),
                value: "\(model.snapshot.lensCoverage["world"] ?? 0)",
                subtitle: localizedYouText(
                    model.appLanguage,
                    en: "People, projects, places, and external context.",
                    zh: "人、项目、地点和外部语境。",
                    fr: "Personnes, projets, lieux et contexte externe.",
                    de: "Menschen, Projekte, Orte und äußerer Kontext."
                ),
                symbol: "globe",
                tint: PersonalModelMapPalette.world,
                helpText: localizedYouText(model.appLanguage, en: "Show world memories", zh: "查看世界记忆", fr: "Afficher les souvenirs du monde", de: "Welterinnerungen anzeigen")
            ),
            LensPartition(
                id: "pulse",
                title: localizedLensTitle("pulse", language: model.appLanguage),
                value: "\(model.snapshot.lensCoverage["pulse"] ?? 0)",
                subtitle: localizedYouText(
                    model.appLanguage,
                    en: "Current state, open loops, and questions to revisit.",
                    zh: "最近状态、未完事项和需要回看的问题。",
                    fr: "État actuel, boucles ouvertes et questions à revoir.",
                    de: "Aktueller Zustand, offene Fäden und spätere Fragen."
                ),
                symbol: "waveform.path.ecg",
                tint: PersonalModelMapPalette.pulse,
                helpText: localizedYouText(model.appLanguage, en: "Show current-state memories", zh: "查看近况记忆", fr: "Afficher les souvenirs du présent", de: "Aktuelle Erinnerungen anzeigen")
            ),
            LensPartition(
                id: "journey",
                title: localizedLensTitle("journey", language: model.appLanguage),
                value: "\(model.snapshot.lensCoverage["journey"] ?? 0)",
                subtitle: localizedYouText(
                    model.appLanguage,
                    en: "Lessons, patterns, and decisions that accumulated over time.",
                    zh: "长期积累的经验、模式和关键决定。",
                    fr: "Leçons, motifs et décisions accumulés avec le temps.",
                    de: "Lehren, Muster und Entscheidungen über die Zeit."
                ),
                symbol: "map",
                tint: PersonalModelMapPalette.journey,
                helpText: localizedYouText(model.appLanguage, en: "Show journey memories", zh: "查看旅程记忆", fr: "Afficher les souvenirs de parcours", de: "Wegerinnerungen anzeigen")
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
    var helpText: String
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
                    SectionLabel(title: lensTitle, subtitle: pagerSubtitle)
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
        localizedLensTitle(lens, language: model.appLanguage)
    }

    private var pagerSubtitle: String {
        localizedYouText(
            model.appLanguage,
            en: "\(facts.count) memories · page \(currentPage + 1) of \(pageCount)",
            zh: "\(facts.count) 条记忆 · 第 \(currentPage + 1)/\(pageCount) 页",
            fr: "\(facts.count) souvenirs · page \(currentPage + 1) sur \(pageCount)",
            de: "\(facts.count) Erinnerungen · Seite \(currentPage + 1) von \(pageCount)"
        )
    }

    private var lensDescription: String {
        switch lens {
        case "world":
            return localizedYouText(
                model.appLanguage,
                en: "People, projects, places, tools, and external context Elephant should remember.",
                zh: "Elephant 应该记住的人、项目、地点、工具和外部语境。",
                fr: "Personnes, projets, lieux, outils et contexte externe qu'Elephant devrait retenir.",
                de: "Menschen, Projekte, Orte, Tools und äußerer Kontext, die Elephant behalten sollte."
            )
        case "pulse":
            return localizedYouText(
                model.appLanguage,
                en: "Current state, open loops, blockers, and questions that should stay fresh.",
                zh: "最近状态、未完成的事、阻塞点，以及需要保持新鲜的问题。",
                fr: "État actuel, boucles ouvertes, blocages et questions à garder fraîches.",
                de: "Aktueller Zustand, offene Fäden, Blocker und Fragen, die frisch bleiben sollten."
            )
        case "journey":
            return localizedYouText(
                model.appLanguage,
                en: "Lessons, patterns, and decisions from prior episodes.",
                zh: "从过去经历里沉淀下来的经验、模式和决定。",
                fr: "Leçons, motifs et décisions issus des épisodes passés.",
                de: "Lehren, Muster und Entscheidungen aus früheren Episoden."
            )
        default:
            return localizedYouText(
                model.appLanguage,
                en: "Durable preferences, roles, values, working style, and self-knowledge.",
                zh: "稳定偏好、角色、价值观、工作方式和自我理解。",
                fr: "Préférences durables, rôles, valeurs, style de travail et connaissance de soi.",
                de: "Dauerhafte Vorlieben, Rollen, Werte, Arbeitsstil und Selbstwissen."
            )
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
        localizedYouText(
            model.appLanguage,
            en: "No \(lensTitle.lowercased()) memories yet. Run Reflect after a few useful conversations.",
            zh: "还没有\(lensTitle)记忆。聊几段具体的事，再运行 Reflect。",
            fr: "Pas encore de souvenirs \(lensTitle.lowercased()). Lancez Reflect après quelques conversations utiles.",
            de: "Noch keine \(lensTitle.lowercased())-Erinnerungen. Starte Reflect nach ein paar nützlichen Gesprächen."
        )
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
        if lens.contains("pulse") { return PersonalModelMapPalette.pulse }
        if lens.contains("world") { return PersonalModelMapPalette.world }
        if lens.contains("journey") { return PersonalModelMapPalette.journey }
        return PersonalModelMapPalette.identity
    }
}

struct SkillAffinityPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 16) {
                SectionLabel(
                    title: localizedYouText(model.appLanguage, en: "Skills for You", zh: "适合你的技能", fr: "Skills pour vous", de: "Skills für dich"),
                    subtitle: localizedFormat(model.appLanguage, en: "%d learned matches", zh: "%d 条已学习线索", fr: "%d correspondances apprises", de: "%d gelernte Treffer", model.snapshot.skillAffinityRows.count)
                )
                if model.snapshot.skillAffinityRows.isEmpty {
                    EmptyLine(
                        symbol: "wand.and.stars",
                        text: model.snapshot.skillAffinities > 0
                            ? localizedFormat(model.appLanguage, en: "%d matched skills found.", zh: "已经找到 %d 个适合你的技能。", fr: "%d skills adaptés trouvés.", de: "%d passende Skills gefunden.", model.snapshot.skillAffinities)
                            : localizedYouText(model.appLanguage, en: "No matched skills yet.", zh: "还没看出哪些技能适合你。", fr: "Aucun skill adapté pour l'instant.", de: "Noch keine passenden Skills.")
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
                SectionLabel(
                    title: localizedYouText(model.appLanguage, en: "Diary", zh: "日记", fr: "Journal", de: "Tagebuch"),
                    subtitle: localizedFormat(model.appLanguage, en: "%d entries", zh: "%d 篇", fr: "%d entrées", de: "%d Einträge", model.snapshot.diaryEntries.count)
                )
                if model.snapshot.diaryEntries.isEmpty {
                    EmptyLine(
                        symbol: "book.closed",
                        text: localizedYouText(
                            model.appLanguage,
                            en: "No diary entries yet. Run Reflect with diary enabled after there is enough context.",
                            zh: "还没有日记。等上下文足够后，可以运行带日记的 Reflect。",
                            fr: "Aucune entrée pour l'instant. Lancez Reflect avec le journal quand il y a assez de contexte.",
                            de: "Noch keine Tagebucheinträge. Starte Reflect mit Tagebuch, sobald genug Kontext da ist."
                        )
                    )
                } else {
                    ForEach(model.snapshot.diaryEntries) { entry in
                        VStack(alignment: .leading, spacing: 10) {
                            HStack {
                                Label(entry.date.isEmpty ? localizedYouText(model.appLanguage, en: "Diary entry", zh: "日记", fr: "Entrée de journal", de: "Tagebucheintrag") : entry.date, systemImage: "book.closed")
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
                title: AppSection.diary.title(language: model.appLanguage),
                subtitle: model.text(.diaryPageSubtitle),
                actionTitle: model.isReflecting ? model.text(.writing) : model.text(.writeDiary),
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
                                title: model.text(.writeDiary),
                                subtitle: localizedYouText(
                                    model.appLanguage,
                                    en: "Pick a day with reviewed episodes. Yesterday is selected by default.",
                                    zh: "选择有已回看 episodes 的日期。默认选昨天。",
                                    fr: "Choisissez un jour avec des épisodes revus. Hier est sélectionné par défaut.",
                                    de: "Wähle einen Tag mit geprüften Episoden. Gestern ist vorausgewählt."
                                )
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
                    DatePicker(localizedYouText(model.appLanguage, en: "Diary day", zh: "日记日期", fr: "Jour du journal", de: "Tagebuchtag"), selection: $targetDate, displayedComponents: .date)
                        .datePickerStyle(.graphical)
                        .labelsHidden()
                        .frame(width: 300)
                    HStack(spacing: 8) {
                        Button(localizedYouText(model.appLanguage, en: "Yesterday", zh: "昨天", fr: "Hier", de: "Gestern")) {
                            setTargetDate(relativeToTodayBy: -1)
                        }
                        Button(localizedYouText(model.appLanguage, en: "Today", zh: "今天", fr: "Aujourd'hui", de: "Heute")) {
                            setTargetDate(relativeToTodayBy: 0)
                        }
                        Spacer()
                        Button(localizedYouText(model.appLanguage, en: "Done", zh: "完成", fr: "Terminé", de: "Fertig")) {
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

            Button(localizedYouText(model.appLanguage, en: "Yesterday", zh: "昨天", fr: "Hier", de: "Gestern")) {
                setTargetDate(relativeToTodayBy: -1)
            }
            .buttonStyle(.bordered)
            .help("Select yesterday")

            Button(localizedYouText(model.appLanguage, en: "Today", zh: "今天", fr: "Aujourd'hui", de: "Heute")) {
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
            Label(
                model.isReflecting
                    ? model.text(.writing)
                    : localizedFormat(model.appLanguage, en: "Write for %@", zh: "写 %@", fr: "Écrire pour %@", de: "Schreiben für %@", requestDateString),
                systemImage: "square.and.pencil"
            )
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
                Text(localizedYouText(model.appLanguage, en: "Writing diary", zh: "正在写日记", fr: "Écriture du journal", de: "Tagebuch wird geschrieben"))
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
                title: AppSection.skills.title(language: model.appLanguage),
                subtitle: model.text(.skillsPageSubtitle),
                actionTitle: model.text(.refresh),
                actionSymbol: "arrow.clockwise"
            ) {
                Task { try? await model.refreshDashboard() }
            }

            HStack(spacing: 12) {
                MetricTile(label: localizedYouText(model.appLanguage, en: "Installed", zh: "已安装", fr: "Installés", de: "Installiert"), value: "\(model.snapshot.skills)", symbol: "wand.and.stars")
                MetricTile(label: localizedYouText(model.appLanguage, en: "For you", zh: "适合你的技能", fr: "Pour vous", de: "Für dich"), value: "\(model.snapshot.skillAffinities)", symbol: "sparkles", tint: ElephantTheme.orange)
                MetricTile(label: localizedYouText(model.appLanguage, en: "Enabled", zh: "已启用", fr: "Activés", de: "Aktiviert"), value: "\(enabledSkills)", symbol: "checkmark.seal", tint: ElephantTheme.green)
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
                title: AppSection.tools.title(language: model.appLanguage),
                subtitle: model.text(.toolsPageSubtitle),
                actionTitle: model.text(.refresh),
                actionSymbol: "arrow.clockwise"
            ) {
                Task { try? await model.refreshDashboard() }
            }

            HStack(spacing: 12) {
                MetricTile(label: localizedYouText(model.appLanguage, en: "Built-in", zh: "内置", fr: "Intégrés", de: "Eingebaut"), value: "\(model.snapshot.enabledTools)/\(model.snapshot.tools)", symbol: "wrench.and.screwdriver")
                MetricTile(label: localizedYouText(model.appLanguage, en: "MCP Servers", zh: "MCP 服务", fr: "Serveurs MCP", de: "MCP-Server"), value: "\(model.snapshot.mcpServers)", symbol: "server.rack", tint: ElephantTheme.green)
                MetricTile(label: localizedYouText(model.appLanguage, en: "MCP Tools", zh: "MCP 工具", fr: "Outils MCP", de: "MCP-Tools"), value: "\(model.snapshot.mcpTools)", symbol: "point.3.connected.trianglepath.dotted", tint: ElephantTheme.orange)
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
                title: AppSection.messaging.title(language: model.appLanguage),
                subtitle: model.text(.messagingPageSubtitle),
                actionTitle: model.text(.refresh),
                actionSymbol: "arrow.clockwise"
            ) {
                Task { try? await model.refreshDashboard() }
            }

            HStack(spacing: 12) {
                MetricTile(label: localizedYouText(model.appLanguage, en: "Services", zh: "服务", fr: "Services", de: "Dienste"), value: "\(model.snapshot.gatewayServices)", symbol: "message.badge")
                MetricTile(label: localizedYouText(model.appLanguage, en: "Configured", zh: "已配置", fr: "Configurés", de: "Konfiguriert"), value: "\(model.snapshot.gatewayConfigured)", symbol: "checkmark.seal", tint: ElephantTheme.green)
                MetricTile(label: localizedYouText(model.appLanguage, en: "Running", zh: "运行中", fr: "Actifs", de: "Läuft"), value: "\(model.snapshot.gatewayRunning)", symbol: "bolt.horizontal", tint: ElephantTheme.orange)
            }

            NativePanel {
                VStack(alignment: .leading, spacing: 14) {
                    SectionLabel(
                        title: localizedYouText(model.appLanguage, en: "IM Bridge Cards", zh: "消息渠道", fr: "Cartes de passerelles IM", de: "IM-Brückenkarten"),
                        subtitle: localizedYouText(
                            model.appLanguage,
                            en: "Configure credentials, start bridges, and scan WeChat QR from the desktop app.",
                            zh: "在这里连接微信、飞书、Discord 等账号。",
                            fr: "Configurez les identifiants, lancez les passerelles et scannez le QR WeChat depuis l'app.",
                            de: "Zugangsdaten konfigurieren, Brücken starten und WeChat-QR in der Desktop-App scannen."
                        )
                    )
                    if !model.gatewayActionResult.isEmpty {
                        Text(model.gatewayActionResult)
                            .font(.callout)
                            .foregroundStyle(ElephantTheme.green)
                    }
                    if model.snapshot.gatewayItems.isEmpty {
                        EmptyLine(
                            symbol: "message.badge",
                            text: localizedYouText(model.appLanguage, en: "No messaging adapters were returned by the local runtime.", zh: "本地运行时还没有返回可用的消息渠道。", fr: "Aucun adaptateur de messagerie retourné par le runtime local.", de: "Keine Nachrichtenadapter von der lokalen Runtime.")
                        )
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
                    SettingsRow(label: localizedYouText(model.appLanguage, en: "Account", zh: "账号", fr: "Compte", de: "Konto"), value: service.accountID)
                    SettingsRow(label: localizedYouText(model.appLanguage, en: "Transport", zh: "传输", fr: "Transport", de: "Transport"), value: service.transport.isEmpty ? localizedYouText(model.appLanguage, en: "default", zh: "默认", fr: "défaut", de: "Standard") : service.transport)
                    if !service.eventPath.isEmpty {
                        SettingsRow(label: localizedYouText(model.appLanguage, en: "Event path", zh: "事件路径", fr: "Chemin d'événements", de: "Ereignispfad"), value: service.eventPath)
                    }
                    if service.id == "weixin" {
                        WeixinQRPanel()
                    } else if !service.secretFields.isEmpty {
                        GatewaySecretEditor(service: service)
                    }
                    HStack(spacing: 8) {
                        if service.configured {
                            Button(service.running ? localizedYouText(model.appLanguage, en: "Restart", zh: "重启", fr: "Redémarrer", de: "Neu starten") : localizedYouText(model.appLanguage, en: "Start", zh: "启动", fr: "Démarrer", de: "Starten")) {
                                Task { await model.runGatewayAction(service: service, action: service.running ? "restart" : "start") }
                            }
                            Button(localizedYouText(model.appLanguage, en: "Stop", zh: "停止", fr: "Arrêter", de: "Stoppen")) {
                                Task { await model.runGatewayAction(service: service, action: "stop") }
                            }
                            .disabled(!service.running && !service.starting)
                        } else if service.id == "weixin" {
                            Button(localizedYouText(model.appLanguage, en: "Connect with QR", zh: "扫码连接", fr: "Connecter par QR", de: "Per QR verbinden")) {
                                Task { await model.startWeixinQR() }
                            }
                        } else {
                            Button(localizedYouText(model.appLanguage, en: "Save Configuration", zh: "保存配置", fr: "Enregistrer la configuration", de: "Konfiguration speichern")) {
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
        if service.running { return model.text(.statusRunning) }
        if service.starting { return localizedYouText(model.appLanguage, en: "starting", zh: "启动中", fr: "démarrage", de: "startet") }
        if service.configured { return model.text(.statusConfigured) }
        return model.text(.statusSetup)
    }

    private var statusTint: Color {
        if service.running { return ElephantTheme.green }
        if service.starting { return ElephantTheme.accent }
        if service.configured { return ElephantTheme.green }
        return ElephantTheme.faint
    }

    private var detailLine: String {
        [
            service.detail,
            localizedFormat(model.appLanguage, en: "%d account(s)", zh: "%d 个账号", fr: "%d compte(s)", de: "%d Konto(s)", service.accountCount)
        ].filter { !$0.isEmpty }.joined(separator: " · ")
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
                title: AppSection.herd.title(language: model.appLanguage),
                subtitle: model.text(.herdPageSubtitle),
                actionTitle: model.text(.newElephant),
                actionSymbol: "plus"
            ) {
                showingCreate = true
            }

            NativePanel {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .firstTextBaseline) {
                        SectionLabel(
                            title: localizedYouText(model.appLanguage, en: "Local Elephants", zh: "本机 Elephants", fr: "Elephants locaux", de: "Lokale Elephants"),
                            subtitle: localizedFormat(model.appLanguage, en: "%d state(s)", zh: "%d 个状态", fr: "%d état(s)", de: "%d Status", model.snapshot.herdItems.count)
                        )
                        Spacer(minLength: 0)
                        Button {
                            Task { try? await model.refreshDashboard() }
                        } label: {
                            Label(model.text(.refresh), systemImage: "arrow.clockwise")
                        }
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                    }

                    if model.snapshot.herdItems.isEmpty {
                        EmptyLine(
                            symbol: "person.3",
                            text: localizedYouText(
                                model.appLanguage,
                                en: "No local elephant has been created yet. Run onboarding from Settings after provider setup.",
                                zh: "还没有创建本机 Elephant。先配好模型，再从设置里重新初始化。",
                                fr: "Aucun elephant local créé. Lancez l'onboarding depuis Réglages après le provider.",
                                de: "Noch kein lokaler Elephant. Starte Onboarding nach Provider-Setup in den Einstellungen."
                            )
                        )
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
    @State private var showingSource = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .center, spacing: 14) {
                HerdAvatarImage(size: 82, name: name, url: avatarURL)
                VStack(alignment: .leading, spacing: 8) {
                    Text(localizedYouText(model.appLanguage, en: "Create Elephant", zh: "创建 Elephant", fr: "Créer Elephant", de: "Elephant erstellen"))
                        .font(.title2.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                    Text(localizedYouText(model.appLanguage, en: "Create a local Elephant with a name and an authored ELEPHANT.md voice file.", zh: "给这个本机 Elephant 起个名字，并写好 ELEPHANT.md。", fr: "Créez un Elephant local avec un nom et un fichier vocal ELEPHANT.md.", de: "Erstelle einen lokalen Elephant mit Name und ELEPHANT.md-Stimme."))
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.muted)
                    HStack(spacing: 8) {
                        Button(model.text(.chooseAvatar)) {
                            avatarURL = OpenPanelBridge.pickAvatarImageURL(language: model.appLanguage)
                        }
                        Button(model.text(.useDefault)) {
                            avatarURL = nil
                        }
                        .disabled(avatarURL == nil)
                    }
                    .controlSize(.small)
                }
                Spacer(minLength: 0)
            }

            TextField(localizedYouText(model.appLanguage, en: "Name", zh: "名称", fr: "Nom", de: "Name"), text: $name)
                .textFieldStyle(.roundedBorder)

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("ELEPHANT.md")
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                    Spacer()
                    Button(showingSource ? localizedYouText(model.appLanguage, en: "Preview", zh: "预览", fr: "Aperçu", de: "Vorschau") : localizedYouText(model.appLanguage, en: "Edit", zh: "编辑", fr: "Modifier", de: "Bearbeiten")) {
                        showingSource.toggle()
                    }
                    .controlSize(.small)
                }
                if showingSource {
                    TextField("ELEPHANT.md", text: $identityText, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(8...14)
                } else {
                    MarkdownBody(text: identityText, font: .callout, color: ElephantTheme.ink)
                        .padding(12)
                        .frame(maxWidth: .infinity, minHeight: 180, alignment: .topLeading)
                        .background(Color(nsColor: .controlBackgroundColor).opacity(0.58), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line.opacity(0.72), lineWidth: 1))
                }
            }

            HStack {
                Spacer()
                Button(localizedYouText(model.appLanguage, en: "Cancel", zh: "取消", fr: "Annuler", de: "Abbrechen")) {
                    isPresented = false
                }
                Button(localizedYouText(model.appLanguage, en: "Create Elephant", zh: "创建 Elephant", fr: "Créer Elephant", de: "Elephant erstellen")) {
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
        .onAppear {
            if identityText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                identityText = model.appLanguage.defaultElephantMarkdown(name: name)
            }
        }
        .onChange(of: name) { newValue in
            let defaults = AppLanguage.allCases.map { $0.defaultElephantMarkdown(name: "Elephant").trimmingCharacters(in: .whitespacesAndNewlines) }
            if identityText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || defaults.contains(identityText.trimmingCharacters(in: .whitespacesAndNewlines)) {
                identityText = model.appLanguage.defaultElephantMarkdown(name: newValue)
            }
        }
    }
}

struct HerdElephantCard: View {
    @EnvironmentObject private var model: ElephantAppModel
    var item: HerdItem
    @State private var name = ""
    @State private var identityText = ""
    @State private var editingIdentity = false
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
                    .help(model.text(.changeImage))
                }

                VStack(alignment: .leading, spacing: 3) {
                    Text(item.title)
                        .font(.headline)
                        .foregroundStyle(ElephantTheme.ink)
                    Text(item.subtitle)
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(2)
                }
                Spacer(minLength: 0)
            }

            HStack(spacing: 8) {
                Pill(text: item.status.isEmpty ? model.text(.ready) : item.status, symbol: "circle.fill", tint: item.current ? ElephantTheme.green : ElephantTheme.accent)
                if item.level > 0 || !item.stage.isEmpty {
                    Pill(text: item.stage.isEmpty ? localizedFormat(model.appLanguage, en: "level %d", zh: "%d 级", fr: "niveau %d", de: "Level %d", item.level) : item.stage, symbol: "sparkles", tint: ElephantTheme.accent)
                }
                if item.current {
                    Pill(text: model.text(.phaseStatusCurrent), symbol: "checkmark", tint: ElephantTheme.green)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Divider()

            TextField(localizedYouText(model.appLanguage, en: "Name", zh: "名称", fr: "Nom", de: "Name"), text: $name)
                .textFieldStyle(.roundedBorder)

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("ELEPHANT.md")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.muted)
                    Spacer()
                    Button(editingIdentity ? localizedYouText(model.appLanguage, en: "Preview", zh: "预览", fr: "Aperçu", de: "Vorschau") : localizedYouText(model.appLanguage, en: "Edit", zh: "编辑", fr: "Modifier", de: "Bearbeiten")) {
                        editingIdentity.toggle()
                    }
                    .controlSize(.small)
                }
                if editingIdentity {
                    TextField("ELEPHANT.md", text: $identityText, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(8...14)
                } else {
                    MarkdownBody(text: identityText, font: .callout, color: ElephantTheme.ink)
                        .padding(12)
                        .frame(maxWidth: .infinity, minHeight: 190, alignment: .topLeading)
                        .background(Color(nsColor: .controlBackgroundColor).opacity(0.52), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line.opacity(0.72), lineWidth: 1))
                }
            }

            LazyVGrid(columns: metaColumns, spacing: 10) {
                HerdMeta(label: localizedYouText(model.appLanguage, en: "Created", zh: "创建时间", fr: "Créé", de: "Erstellt"), value: MacLocalDateTime.formatted(item.createdAt, language: model.appLanguage))
                HerdMeta(label: localizedYouText(model.appLanguage, en: "Updated", zh: "更新时间", fr: "Mis à jour", de: "Aktualisiert"), value: MacLocalDateTime.formatted(item.updatedAt, language: model.appLanguage))
            }

            HStack {
                Button(localizedYouText(model.appLanguage, en: "Save Changes", zh: "保存修改", fr: "Enregistrer", de: "Änderungen speichern")) {
                    Task {
                        await model.updateHerdElephant(
                            item,
                            name: name,
                            identityText: identityText
                        )
                    }
                }
                Button(localizedYouText(model.appLanguage, en: "Delete", zh: "删除", fr: "Supprimer", de: "Löschen"), role: .destructive) {
                    confirmDelete = true
                }
                .disabled(item.current)
                Spacer()
                if item.current {
                    Text(localizedYouText(model.appLanguage, en: "Current elephant is protected.", zh: "当前使用中的 Elephant 不能删除。", fr: "L'Elephant actuel est protégé.", de: "Der aktuelle Elephant ist geschützt."))
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
            let renderedText = sanitizedText(item.identityText)
            identityText = renderedText.isEmpty || isLegacyDefaultIdentity(renderedText)
                ? model.appLanguage.defaultElephantMarkdown(name: item.title)
                : renderedText
        }
        .confirmationDialog(
            localizedFormat(model.appLanguage, en: "Delete %@?", zh: "删除 %@？", fr: "Supprimer %@ ?", de: "%@ löschen?", item.title),
            isPresented: $confirmDelete
        ) {
            Button(localizedYouText(model.appLanguage, en: "Delete Elephant", zh: "删除 Elephant", fr: "Supprimer Elephant", de: "Elephant löschen"), role: .destructive) {
                Task { await model.deleteHerdElephant(item) }
            }
        } message: {
            Text(localizedYouText(model.appLanguage, en: "This removes the local Elephant state. The current Elephant is protected.", zh: "这会删除本地 Elephant 状态。当前 Elephant 受保护。", fr: "Cela supprime l'état local d'Elephant. L'Elephant actuel est protégé.", de: "Das entfernt den lokalen Elephant-Status. Der aktuelle Elephant ist geschützt."))
        }
    }

    private func sanitizedText(_ text: String) -> String {
        text
            .replacingOccurrences(of: #"(?s)<!--\s*Internal metadata.*?-->\s*"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func isLegacyDefaultIdentity(_ text: String) -> Bool {
        let normalized = text.lowercased()
        return normalized.contains("be warm, precise, curious, and direct")
            || normalized.contains("温暖、精准、好奇、直接")
            || normalized.contains("être chaleureux, précis, curieux et direct")
            || normalized.contains("warm, präzise, neugierig und direkt")
    }

    private var metaColumns: [GridItem] {
        [
            GridItem(.flexible(), spacing: 10, alignment: .leading),
            GridItem(.flexible(), spacing: 10, alignment: .leading)
        ]
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

    func title(language: AppLanguage) -> String {
        switch self {
        case .day:
            return localizedYouText(language, en: "Day", zh: "日", fr: "Jour", de: "Tag")
        case .week:
            return localizedYouText(language, en: "Week", zh: "周", fr: "Semaine", de: "Woche")
        case .month:
            return localizedYouText(language, en: "Month", zh: "月", fr: "Mois", de: "Monat")
        }
    }
}

struct UsageView: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var period: UsagePeriod = .day

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: AppSection.usage.title(language: model.appLanguage),
                subtitle: model.text(.usagePageSubtitle),
                actionTitle: model.text(.refresh),
                actionSymbol: "arrow.clockwise"
            ) {
                Task { try? await model.refreshDashboard() }
            }

            HStack(spacing: 12) {
                MetricTile(label: localizedYouText(model.appLanguage, en: "Total Tokens", zh: "Token 总量", fr: "Tokens totaux", de: "Tokens gesamt"), value: abbreviatedCount(model.snapshot.usageTokens), symbol: "sum")
                MetricTile(label: localizedYouText(model.appLanguage, en: "Prompt", zh: "输入", fr: "Prompt", de: "Prompt"), value: abbreviatedCount(model.snapshot.usagePromptTokens), symbol: "arrow.down.doc", tint: ElephantTheme.accent)
                MetricTile(label: localizedYouText(model.appLanguage, en: "Completion", zh: "输出", fr: "Réponse", de: "Antwort"), value: abbreviatedCount(model.snapshot.usageCompletionTokens), symbol: "arrow.up.doc", tint: ElephantTheme.green)
                MetricTile(label: localizedYouText(model.appLanguage, en: "Events", zh: "事件", fr: "Événements", de: "Ereignisse"), value: "\(model.snapshot.usageEvents)", symbol: "waveform.path", tint: ElephantTheme.orange)
            }

            NativePanel {
                VStack(alignment: .leading, spacing: 16) {
                    HStack {
                        SectionLabel(
                            title: localizedYouText(model.appLanguage, en: "Token Flow", zh: "Token 用量", fr: "Flux de tokens", de: "Token-Fluss"),
                            subtitle: localizedYouText(model.appLanguage, en: "Usage grouped by day, week, or month", zh: "按日、周或月查看用量。", fr: "Usage groupé par jour, semaine ou mois.", de: "Nutzung nach Tag, Woche oder Monat gruppiert.")
                        )
                        Spacer()
                        Picker(localizedYouText(model.appLanguage, en: "Period", zh: "周期", fr: "Période", de: "Zeitraum"), selection: $period) {
                            ForEach(UsagePeriod.allCases) { item in
                                Text(item.title(language: model.appLanguage)).tag(item)
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
                    SectionLabel(
                        title: localizedYouText(model.appLanguage, en: "Recent Token Events", zh: "最近用量记录", fr: "Événements token récents", de: "Letzte Token-Ereignisse"),
                        subtitle: localizedFormat(model.appLanguage, en: "%d shown", zh: "显示 %d 条", fr: "%d affichés", de: "%d gezeigt", model.snapshot.usageItems.count)
                    )
                    if model.snapshot.usageItems.isEmpty {
                        EmptyLine(symbol: "chart.xyaxis.line", text: localizedYouText(model.appLanguage, en: "No token usage rows yet.", zh: "还没有模型用量记录。", fr: "Aucune ligne d'usage token.", de: "Noch keine Token-Nutzungszeilen."))
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
    @EnvironmentObject private var model: ElephantAppModel
    var points: [UsageTrendPoint]

    var body: some View {
        if points.isEmpty {
            EmptyLine(symbol: "chart.xyaxis.line", text: localizedYouText(model.appLanguage, en: "No token flow rows yet.", zh: "还没有可汇总的用量。", fr: "Aucune ligne de flux token.", de: "Noch keine Token-Flusszeilen."))
        } else {
            VStack(spacing: 0) {
                HStack {
                    tableHeader(localizedYouText(model.appLanguage, en: "Period", zh: "周期", fr: "Période", de: "Zeitraum"))
                    tableHeader(localizedYouText(model.appLanguage, en: "Tokens", zh: "Tokens", fr: "Tokens", de: "Tokens"))
                    tableHeader(localizedYouText(model.appLanguage, en: "Input", zh: "输入", fr: "Entrée", de: "Eingabe"))
                    tableHeader(localizedYouText(model.appLanguage, en: "Output", zh: "输出", fr: "Sortie", de: "Ausgabe"))
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
    @EnvironmentObject private var model: ElephantAppModel
    var item: UsageEventItem
    var maxTokens: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(item.title)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Spacer()
                Text(localizedFormat(model.appLanguage, en: "%d tokens", zh: "%d tokens", fr: "%d tokens", de: "%d Tokens", item.totalTokens))
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
            Text([item.provider, MacLocalDateTime.formatted(item.subtitle, language: model.appLanguage, fallback: "")].filter { !$0.isEmpty }.joined(separator: " · "))
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
                title: model.text(.providerTitle),
                subtitle: providerSubtitle,
                actionTitle: model.text(.refresh),
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

    func title(language: AppLanguage) -> String {
        switch self {
        case .week:
            return localizedYouText(language, en: "Week", zh: "周", fr: "Semaine", de: "Woche")
        case .month:
            return localizedYouText(language, en: "Month", zh: "月", fr: "Mois", de: "Monat")
        case .year:
            return localizedYouText(language, en: "Year", zh: "年", fr: "Année", de: "Jahr")
        }
    }

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
        MacLocalDateTime.time(date)
    }

    static func from(_ job: CronJobItem) -> CronCalendarEvent? {
        guard let date = MacLocalDateTime.parse(job.nextRun) else { return nil }
        return CronCalendarEvent(job: job, date: date)
    }
}

struct CronView: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var scope: ScheduleCalendarScope = .month
    @State private var focusedDate = Date()

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: AppSection.cron.title(language: model.appLanguage),
                subtitle: model.text(.calendarPageSubtitle),
                actionTitle: model.text(.refresh),
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
    @EnvironmentObject private var model: ElephantAppModel
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
                        Text(localizedFormat(model.appLanguage, en: "%d dated", zh: "%d 条有日期", fr: "%d datés", de: "%d datiert", events.count))
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(ElephantTheme.muted)
                    }

                    Spacer(minLength: 12)

                    Picker(localizedYouText(model.appLanguage, en: "Calendar view", zh: "日历视图", fr: "Vue calendrier", de: "Kalenderansicht"), selection: $scope) {
                        ForEach(ScheduleCalendarScope.allCases) { item in
                            Text(item.title(language: model.appLanguage)).tag(item)
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
                        .help(localizedFormat(model.appLanguage, en: "Previous %@", zh: "上一个%@", fr: "%@ précédent", de: "Vorherige %@", scope.title(language: model.appLanguage)))

                        Button(localizedYouText(model.appLanguage, en: "Today", zh: "今天", fr: "Aujourd'hui", de: "Heute")) {
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
                        .help(localizedFormat(model.appLanguage, en: "Next %@", zh: "下一个%@", fr: "%@ suivant", de: "Nächste %@", scope.title(language: model.appLanguage)))
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
        formatter.locale = Locale(identifier: model.appLanguage.localeIdentifier)
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
                    Text(event.job.isSystem ? localizedYouText(model.appLanguage, en: "System evolution reminder", zh: "系统自我进化提醒", fr: "Rappel système d'évolution", de: "System-Evolutionserinnerung") : localizedYouText(model.appLanguage, en: "Reminder", zh: "提醒", fr: "Rappel", de: "Erinnerung"))
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                }

                Spacer(minLength: 8)
                Pill(text: localizedRuntimeStatus(event.job.status, language: model.appLanguage), tint: event.tint)
            }

            VStack(spacing: 0) {
                popoverRow(localizedYouText(model.appLanguage, en: "Next run", zh: "下次运行", fr: "Prochaine exécution", de: "Nächster Lauf"), MacLocalDateTime.formatted(event.date, language: model.appLanguage))
                Divider()
                popoverRow(localizedYouText(model.appLanguage, en: "When", zh: "时间", fr: "Quand", de: "Wann"), event.job.schedule.isEmpty ? "n/a" : event.job.schedule)
                Divider()
                popoverRow(localizedYouText(model.appLanguage, en: "Runs", zh: "运行次数", fr: "Exécutions", de: "Läufe"), "\(event.job.runCount)")
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
                Button(localizedYouText(model.appLanguage, en: "Run", zh: "运行", fr: "Lancer", de: "Starten")) { Task { await model.runCronJob(event.job) } }
                    .disabled(!event.job.canRunNow)
                Button(event.job.status == "paused" ? localizedYouText(model.appLanguage, en: "Resume", zh: "恢复", fr: "Reprendre", de: "Fortsetzen") : localizedYouText(model.appLanguage, en: "Pause", zh: "暂停", fr: "Pause", de: "Pausieren")) {
                    Task { await model.setCronJob(event.job, paused: event.job.status != "paused") }
                }
                .disabled(!event.job.canPause)
                Button(localizedYouText(model.appLanguage, en: "Delete", zh: "删除", fr: "Supprimer", de: "Löschen")) { Task { await model.deleteCronJob(event.job) } }
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
                    title: localizedYouText(model.appLanguage, en: "Reminders", zh: "提醒", fr: "Rappels", de: "Erinnerungen"),
                    subtitle: localizedYouText(model.appLanguage, en: "Ask Elephant to remind you or do something later.", zh: "让 Elephant 到点提醒你，或稍后接着做。", fr: "Demandez à Elephant de vous rappeler ou de faire quelque chose plus tard.", de: "Bitte Elephant, dich später zu erinnern oder etwas zu erledigen.")
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
                    Label(localizedYouText(model.appLanguage, en: "New Reminder", zh: "新提醒", fr: "Nouveau rappel", de: "Neue Erinnerung"), systemImage: "plus")
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(ElephantTheme.accent)
                .popover(isPresented: $showingComposer, arrowEdge: .bottom) {
                    reminderComposer
                }
            }
        }
        .onAppear {
            if name == "Daily Elephant reminder" {
                name = localizedYouText(model.appLanguage, en: "Daily Elephant reminder", zh: "每日提醒", fr: "Rappel quotidien Elephant", de: "Tägliche Elephant-Erinnerung")
            }
            if prompt == "Review current priorities and suggest the next grounded step." {
                prompt = localizedYouText(model.appLanguage, en: "Review current priorities and suggest the next grounded step.", zh: "回看今天的重点，给我一个下一步建议。", fr: "Revoir les priorités et proposer la prochaine étape.", de: "Prioritäten prüfen und den nächsten Schritt vorschlagen.")
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
                    Text(localizedYouText(model.appLanguage, en: "New Reminder", zh: "新提醒", fr: "Nouveau rappel", de: "Neue Erinnerung"))
                        .font(.headline)
                        .foregroundStyle(ElephantTheme.ink)
                    Text(localizedYouText(model.appLanguage, en: "Choose when and what Elephant should do.", zh: "写清楚什么时候提醒，以及要做什么。", fr: "Choisissez quand et ce qu'Elephant doit faire.", de: "Wähle, wann und was Elephant tun soll."))
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                }
                Spacer(minLength: 0)
            }

            VStack(alignment: .leading, spacing: 10) {
                labeledField(localizedYouText(model.appLanguage, en: "Title", zh: "标题", fr: "Titre", de: "Titel")) {
                    TextField(localizedYouText(model.appLanguage, en: "Daily Elephant reminder", zh: "每日提醒", fr: "Rappel quotidien Elephant", de: "Tägliche Elephant-Erinnerung"), text: $name)
                        .textFieldStyle(.roundedBorder)
                }
                labeledField(localizedYouText(model.appLanguage, en: "When", zh: "时间", fr: "Quand", de: "Wann")) {
                    TextField(localizedYouText(model.appLanguage, en: "daily at 09:00", zh: "每天 09:00", fr: "tous les jours à 09:00", de: "täglich um 09:00"), text: $schedule)
                        .textFieldStyle(.roundedBorder)
                }
                labeledField(localizedYouText(model.appLanguage, en: "What should Elephant do?", zh: "要提醒什么？", fr: "Que doit faire Elephant ?", de: "Was soll Elephant tun?")) {
                    TextField(localizedYouText(model.appLanguage, en: "Review priorities and suggest the next grounded step.", zh: "回看今天的重点，给我一个下一步建议。", fr: "Revoir les priorités et proposer la prochaine étape.", de: "Prioritäten prüfen und den nächsten Schritt vorschlagen."), text: $prompt, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(3...5)
                }
            }

            HStack(spacing: 8) {
                Button(localizedYouText(model.appLanguage, en: "Cancel", zh: "取消", fr: "Annuler", de: "Abbrechen")) {
                    showingComposer = false
                }
                Spacer(minLength: 0)
                Button {
                    Task {
                        await model.createCronJob(name: name, schedule: schedule, prompt: prompt)
                        await MainActor.run { showingComposer = false }
                    }
                } label: {
                    Label(localizedYouText(model.appLanguage, en: "Create Reminder", zh: "保存提醒", fr: "Créer le rappel", de: "Erinnerung erstellen"), systemImage: "plus")
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
                    SectionLabel(
                        title: localizedYouText(model.appLanguage, en: "All Reminders", zh: "所有提醒", fr: "Tous les rappels", de: "Alle Erinnerungen"),
                        subtitle: localizedFormat(model.appLanguage, en: "%d reminder(s)", zh: "%d 条提醒", fr: "%d rappel(s)", de: "%d Erinnerung(en)", jobs.count)
                    )
                    Spacer(minLength: 12)
                    if !jobs.isEmpty {
                        Text(localizedFormat(model.appLanguage, en: "Page %d of %d", zh: "第 %d / %d 页", fr: "Page %d sur %d", de: "Seite %d von %d", safePage + 1, pageCount))
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
                    EmptyLine(symbol: "calendar.badge.clock", text: localizedYouText(model.appLanguage, en: "No reminders yet.", zh: "还没有提醒。", fr: "Aucun rappel pour l'instant.", de: "Noch keine Erinnerungen."))
                } else {
                    VStack(spacing: 0) {
                        HStack(spacing: 12) {
                            tableHeader(localizedYouText(model.appLanguage, en: "Reminder", zh: "提醒", fr: "Rappel", de: "Erinnerung"))
                            tableHeader(localizedYouText(model.appLanguage, en: "When", zh: "时间", fr: "Quand", de: "Wann"))
                                .frame(width: 220, alignment: .leading)
                            tableHeader(localizedYouText(model.appLanguage, en: "Next", zh: "下次", fr: "Prochain", de: "Nächste"))
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
                    Text(job.schedule.isEmpty ? localizedYouText(model.appLanguage, en: "No time set", zh: "还没设置时间", fr: "Aucun horaire", de: "Keine Zeit gesetzt") : job.schedule)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                    Text(job.detail.isEmpty ? localizedYouText(model.appLanguage, en: "No reminder detail", zh: "没有说明", fr: "Aucun détail de rappel", de: "Kein Erinnerungsdetail") : job.detail)
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(2)
                }
                .frame(width: 220, alignment: .leading)

                VStack(alignment: .leading, spacing: 3) {
                    Text(nextRunText)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Text(lastRunLine)
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
                Text(nextRunLine)
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
                        Pill(text: localizedYouText(model.appLanguage, en: "system", zh: "系统", fr: "système", de: "System"), symbol: "gearshape", tint: ElephantTheme.green)
                    }
                    Pill(text: localizedRuntimeStatus(job.status, language: model.appLanguage), tint: statusTint)
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
            Button(localizedYouText(model.appLanguage, en: "Run", zh: "运行", fr: "Lancer", de: "Starten")) { Task { await model.runCronJob(job) } }
                .disabled(!job.canRunNow)
            Button(job.status == "paused" ? localizedYouText(model.appLanguage, en: "Resume", zh: "恢复", fr: "Reprendre", de: "Fortsetzen") : localizedYouText(model.appLanguage, en: "Pause", zh: "暂停", fr: "Pause", de: "Pausieren")) {
                Task { await model.setCronJob(job, paused: job.status != "paused") }
            }
            .disabled(!job.canPause)
            Button(localizedYouText(model.appLanguage, en: "Delete", zh: "删除", fr: "Supprimer", de: "Löschen")) { Task { await model.deleteCronJob(job) } }
                .disabled(!job.canDelete)
        }
        .controlSize(.small)
        .frame(width: 164, alignment: .trailing)
    }

    private var statusTint: Color {
        job.status == "paused" ? ElephantTheme.orange : ElephantTheme.green
    }

    private var lastRunLine: String {
        localizedFormat(
            model.appLanguage,
            en: "Last %@ · %d run(s)",
            zh: "上次：%@ · 已运行 %d 次",
            fr: "Dernier %@ · %d exécution(s)",
            de: "Zuletzt %@ · %d Lauf/Läufe",
            lastRunText,
            job.runCount
        )
    }

    private var nextRunLine: String {
        localizedFormat(
            model.appLanguage,
            en: "Next %@ · Last %@ · %d run(s)",
            zh: "下次：%@ · 上次：%@ · 已运行 %d 次",
            fr: "Prochain %@ · Dernier %@ · %d exécution(s)",
            de: "Nächste %@ · Zuletzt %@ · %d Lauf/Läufe",
            nextRunText.lowercased(),
            lastRunText.lowercased(),
            job.runCount
        )
    }

    private var nextRunText: String {
        job.nextRun.isEmpty
            ? localizedYouText(model.appLanguage, en: "Not planned", zh: "暂无计划", fr: "Non planifié", de: "Nicht geplant")
            : MacLocalDateTime.formatted(job.nextRun, language: model.appLanguage)
    }

    private var lastRunText: String {
        job.lastRun.isEmpty
            ? localizedYouText(model.appLanguage, en: "not yet", zh: "还没有", fr: "pas encore", de: "noch nicht")
            : MacLocalDateTime.formatted(job.lastRun, language: model.appLanguage)
    }
}

struct LearnView: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: AppSection.learn.title(language: model.appLanguage),
                subtitle: model.text(.learnPageSubtitle),
                actionTitle: model.isReflecting ? model.text(.learning) : model.text(.runLearn),
                actionSymbol: "brain.head.profile"
            ) {
                Task { await model.runReflect(trigger: "learn") }
            }

            HStack(spacing: 12) {
                MetricTile(label: localizedYouText(model.appLanguage, en: "Questions", zh: "问题", fr: "Questions", de: "Fragen"), value: "\(model.snapshot.waitingQuestions)", symbol: "questionmark.bubble", tint: ElephantTheme.orange)
                MetricTile(label: localizedYouText(model.appLanguage, en: "Worker", zh: "Worker", fr: "Worker", de: "Worker"), value: localizedRuntimeStatus(model.snapshot.workerStatus, language: model.appLanguage), symbol: "gearshape.2", tint: ElephantTheme.accent)
                MetricTile(label: localizedYouText(model.appLanguage, en: "Jobs", zh: "任务", fr: "Tâches", de: "Jobs"), value: "\(model.snapshot.learningItems.count)", symbol: "brain.head.profile", tint: ElephantTheme.green)
            }

            LearnControlsPanel()

            NativePanel {
                VStack(alignment: .leading, spacing: 14) {
                    SectionLabel(
                        title: localizedYouText(model.appLanguage, en: "Evolution History", zh: "自我进化历史", fr: "Historique d'évolution", de: "Evolutionsverlauf"),
                        subtitle: localizedFormat(model.appLanguage, en: "%d job(s)", zh: "%d 个任务", fr: "%d tâche(s)", de: "%d Job(s)", model.snapshot.learningItems.count)
                    )
                    if model.snapshot.learningItems.isEmpty {
                        EmptyLine(symbol: "brain.head.profile", text: localizedYouText(model.appLanguage, en: "No evolution jobs returned yet.", zh: "还没有自我进化任务。", fr: "Aucune tâche d'évolution retournée.", de: "Noch keine Evolutionsjobs zurückgegeben."))
                    } else {
                        LearningJobSection(title: localizedYouText(model.appLanguage, en: "Active", zh: "进行中", fr: "Actifs", de: "Aktiv"), items: Array(model.snapshot.learningItems.filter { !$0.status.lowercased().contains("completed") && !$0.status.lowercased().contains("failed") }.prefix(8)))
                        LearningJobSection(title: localizedYouText(model.appLanguage, en: "Completed", zh: "已完成", fr: "Terminés", de: "Abgeschlossen"), items: Array(model.snapshot.learningItems.filter { $0.status.lowercased().contains("completed") }.prefix(10)))
                        LearningJobSection(title: localizedYouText(model.appLanguage, en: "Needs Attention", zh: "需要处理", fr: "À vérifier", de: "Prüfen"), items: Array(model.snapshot.learningItems.filter { $0.status.lowercased().contains("failed") || $0.status.lowercased().contains("cancel") }.prefix(8)))
                    }
                }
            }
        }
        .task {
            while !Task.isCancelled {
                try? await model.refreshDashboard()
                try? await Task.sleep(nanoseconds: 3_000_000_000)
            }
        }
    }
}

struct LearnControlsPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    private var actions: [LearnActionSpec] {
        [
        LearnActionSpec(
            id: "reflect",
            title: model.text(.reflect),
            subtitle: localizedYouText(model.appLanguage, en: "Review conversations, questions, and evidence into memory.", zh: "把最近的对话、问题和证据整理成记忆。", fr: "Réviser conversations, questions et preuves vers la mémoire.", de: "Gespräche, Fragen und Belege ins Gedächtnis übernehmen."),
            symbol: "brain.head.profile",
            tint: ElephantTheme.accent,
            trigger: "manual",
            features: nil
        ),
        LearnActionSpec(
            id: "dream",
            title: localizedYouText(model.appLanguage, en: "Dream", zh: "Dream", fr: "Dream", de: "Dream"),
            subtitle: localizedYouText(model.appLanguage, en: "Look for quiet patterns, loose threads, and useful next questions.", zh: "找出安静的模式、未完的线索，以及下一步该问什么。", fr: "Repérer les motifs discrets, fils ouverts et prochaines questions utiles.", de: "Leise Muster, lose Fäden und nützliche nächste Fragen finden."),
            symbol: "moon.stars",
            tint: ElephantTheme.green,
            trigger: "dream",
            features: "dream"
        ),
        LearnActionSpec(
            id: "diary",
            title: localizedYouText(model.appLanguage, en: "Diary", zh: "日记", fr: "Journal", de: "Tagebuch"),
            subtitle: localizedYouText(model.appLanguage, en: "Write a reflective entry from recent reviewed context.", zh: "用最近回看过的内容写一篇日记。", fr: "Écrire une entrée réflexive depuis le contexte récemment revu.", de: "Einen reflektierten Eintrag aus zuletzt geprüftem Kontext schreiben."),
            symbol: "book.closed",
            tint: ElephantTheme.orange,
            trigger: "diary",
            features: "diary"
        )
        ]
    }

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top, spacing: 14) {
                    SectionLabel(
                        title: localizedYouText(model.appLanguage, en: "New Evolution Job", zh: "新建自我进化任务", fr: "Nouveau job d'évolution", de: "Neuer Evolutionsjob"),
                        subtitle: localizedYouText(model.appLanguage, en: "Start a focused background pass when memory needs to catch up.", zh: "让后台把近期内容整理进记忆。", fr: "Lancez un passage en arrière-plan quand la mémoire doit rattraper.", de: "Starte einen fokussierten Hintergrundlauf, wenn das Gedächtnis aufholen soll.")
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
                        Text(model.isReflecting ? localizedYouText(model.appLanguage, en: "Evolution job is running", zh: "正在自我进化", fr: "Tâche d'évolution en cours", de: "Evolutionsjob läuft") : localizedYouText(model.appLanguage, en: "Last completed", zh: "上次完成", fr: "Dernière fin", de: "Zuletzt abgeschlossen"))
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
            Pill(text: model.text(.statusRunning), symbol: "arrow.triangle.2.circlepath", tint: ElephantTheme.accent)
        } else {
            Pill(text: latestBadgeText, symbol: latestCompletedDate == nil ? "clock" : "checkmark", tint: latestTint)
        }
    }

    private var latestTint: Color {
        latestCompletedDate == nil ? ElephantTheme.muted : ElephantTheme.green
    }

    private var latestBadgeText: String {
        latestCompletedDate == nil
            ? localizedYouText(model.appLanguage, en: "not run yet", zh: "还没运行过", fr: "pas encore lancé", de: "noch nicht gelaufen")
            : model.text(.ready)
    }

    private var latestCompletedText: String {
        guard let date = latestCompletedDate else {
            return localizedYouText(model.appLanguage, en: "No completed evolution job has been reported yet.", zh: "还没有完成过的自我进化任务。", fr: "Aucun job d'évolution terminé n'a été signalé.", de: "Noch kein abgeschlossener Evolutionsjob gemeldet.")
        }
        return MacLocalDateTime.formatted(date, language: model.appLanguage)
    }

    private var latestCompletedDate: Date? {
        MacLocalDateTime.parse(model.snapshot.latestCompletedAt)
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
    @EnvironmentObject private var model: ElephantAppModel
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
        .help(disabled ? localizedYouText(model.appLanguage, en: "An evolution job is already running.", zh: "已经有自我进化任务在运行。", fr: "Une tâche d'évolution est déjà en cours.", de: "Ein Evolutionsjob läuft bereits.") : localizedFormat(model.appLanguage, en: "Create %@ evolution job", zh: "开始 %@", fr: "Créer le job d'évolution %@", de: "%@ Evolutionsjob erstellen", action.title))
        .accessibilityLabel(localizedFormat(model.appLanguage, en: "Create %@ evolution job", zh: "开始 %@", fr: "Créer le job d'évolution %@", de: "%@ Evolutionsjob erstellen", action.title))
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
    @EnvironmentObject private var model: ElephantAppModel
    var item: LearningJobItem

    var body: some View {
        DisclosureGroup {
            if item.markdown.isEmpty {
                Text(localizedYouText(model.appLanguage, en: "No rendered result returned yet.", zh: "还没有可显示的结果。", fr: "Aucun résultat rendu pour l'instant.", de: "Noch kein gerendertes Ergebnis."))
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
                    Text([item.trigger, formattedDetail].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(2)
                }
                Spacer()
                Pill(text: localizedRuntimeStatus(item.status, language: model.appLanguage), tint: statusTint)
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

    private var formattedDetail: String {
        MacLocalDateTime.formattedRange(item.detail, language: model.appLanguage)
    }
}

private enum SettingsPane: Hashable {
    case language
    case memoryEngine
    case curiosity
    case history
    case sleep
    case logs
    case reset
    case runtime
    case systemConfig
}

struct SettingsView: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var expandedPane: SettingsPane? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(
                title: model.text(.settingsTitle),
                subtitle: model.text(.settingsSubtitle)
            )

            NativePanel {
                VStack(spacing: 0) {
                    SettingsControlStrip()
                        .padding(.horizontal, 12)
                        .padding(.top, 10)
                        .padding(.bottom, 12)
                    Divider()
                        .padding(.leading, 58)
                    ExpandableSettingsRow(
                        symbol: "globe",
                        title: model.text(.languageSettingsTitle),
                        subtitle: "\(model.text(.languageSettingsSubtitle))\(model.appLanguage.nativeName)",
                        expanded: paneBinding(.language)
                    ) {
                        LanguageSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "questionmark.bubble",
                        title: model.text(.curiosity),
                        subtitle: "\(model.snapshot.waitingQuestions) \(model.text(.curiositySubtitle))",
                        expanded: paneBinding(.curiosity)
                    ) {
                        CuriositySettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "memorychip",
                        title: localizedYouText(
                            model.appLanguage,
                            en: "Memory Engine",
                            zh: "记忆引擎",
                            fr: "Moteur mémoire",
                            de: "Memory Engine"
                        ),
                        subtitle: memoryEngineSubtitle,
                        expanded: paneBinding(.memoryEngine)
                    ) {
                        MemoryEngineSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "clock.arrow.circlepath",
                        title: model.text(.history),
                        subtitle: "\(model.snapshot.episodes) episodes · \(model.snapshot.loops) loops · \(model.snapshot.steps) steps",
                        expanded: paneBinding(.history)
                    ) {
                        HistoryUsageSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "moon.zzz",
                        title: model.text(.sleepDisplay),
                        subtitle: String(format: model.text(.sleepDisplaySubtitle), "\(model.sleepIdleMinutes)"),
                        expanded: paneBinding(.sleep)
                    ) {
                        SleepDisplaySettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "stethoscope",
                        title: model.text(.logsDiagnostics),
                        subtitle: "\(model.snapshot.logs) \(model.text(.logsDiagnosticsSubtitle))",
                        expanded: paneBinding(.logs)
                    ) {
                        LogsDiagnosticsSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "exclamationmark.triangle",
                        title: model.text(.resetData),
                        subtitle: model.text(.resetDataSubtitle),
                        expanded: paneBinding(.reset)
                    ) {
                        ResetDataSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "terminal",
                        title: model.text(.advancedRuntime),
                        subtitle: model.snapshot.apiURL.isEmpty ? model.corePhase.label : model.snapshot.apiURL,
                        expanded: paneBinding(.runtime)
                    ) {
                        RuntimeSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "slider.horizontal.3",
                        title: model.text(.runtimeConfig),
                        subtitle: model.snapshot.settingsPath.isEmpty ? model.text(.runtimeConfigMissing) : model.snapshot.settingsPath,
                        expanded: paneBinding(.systemConfig)
                    ) {
                        RuntimeConfigSettingsContent()
                    }
                }
            }

        if !model.lastError.isEmpty {
            NativePanel {
                VStack(alignment: .leading, spacing: 8) {
                        SectionLabel(title: model.text(.lastError))
                        Text(model.lastError)
                            .font(.callout)
                            .foregroundStyle(ElephantTheme.orange)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .frame(maxWidth: 1120, alignment: .topLeading)
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
            return model.snapshot.providerID.isEmpty ? model.text(.providerSetupNeeded) : model.snapshot.providerID
        }
        return "\(model.snapshot.providerID) · \(model.snapshot.providerModelID)"
    }

    private var memoryEngineSubtitle: String {
        let status = model.snapshot.embeddingStatus.isEmpty ? model.snapshot.semanticStatus : model.snapshot.embeddingStatus
        let source: String
        switch model.snapshot.embeddingBootstrapSource.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "modelscope":
            source = "ModelScope"
        case "huggingface":
            source = "HuggingFace"
        default:
            source = model.appLanguage.defaultEmbeddingModelSource == "modelscope" ? "ModelScope" : "HuggingFace"
        }
        return "\(source) · \(localizedEmbeddingState(status, language: model.appLanguage))"
    }

    private func paneBinding(_ pane: SettingsPane) -> Binding<Bool> {
        Binding(
            get: { expandedPane == pane },
            set: { isExpanded in
                expandedPane = isExpanded ? pane : nil
            }
        )
    }
}

struct SettingsControlStrip: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var hoveringRestart = false

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(statusTint.opacity(0.12))
                Image(systemName: statusSymbol)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(statusTint)
            }
            .frame(width: 34, height: 34)

            VStack(alignment: .leading, spacing: 3) {
                Text(model.text(.advancedRuntime))
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Text(runtimeLine)
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            Spacer(minLength: 0)

            Button {
                Task { await model.restartCore() }
            } label: {
                Label(model.text(.restartCore), systemImage: "arrow.clockwise")
                    .font(.callout.weight(.semibold))
                    .labelStyle(.titleAndIcon)
                    .padding(.horizontal, 12)
                    .frame(height: 34)
                    .background(
                        Capsule(style: .continuous)
                            .fill(hoveringRestart ? ElephantTheme.accent.opacity(0.14) : ElephantTheme.accent.opacity(0.08))
                    )
                    .overlay(
                        Capsule(style: .continuous)
                            .stroke(hoveringRestart ? ElephantTheme.accent.opacity(0.34) : ElephantTheme.accent.opacity(0.18), lineWidth: 1)
                    )
                    .contentShape(Capsule(style: .continuous))
            }
            .buttonStyle(PressablePlainButtonStyle())
            .foregroundStyle(ElephantTheme.accent)
            .onHover { hoveringRestart = $0 }
            .help(model.text(.restartCore))
        }
        .frame(maxWidth: .infinity, minHeight: 46, alignment: .center)
    }

    private var runtimeLine: String {
        if !model.snapshot.apiURL.isEmpty {
            return model.snapshot.apiURL
        }
        return model.corePhase.label
    }

    private var statusSymbol: String {
        switch model.corePhase {
        case .ready:
            return "checkmark.seal.fill"
        case .starting:
            return "arrow.triangle.2.circlepath"
        case .failed:
            return "exclamationmark.triangle.fill"
        case .idle:
            return "power"
        }
    }

    private var statusTint: Color {
        switch model.corePhase {
        case .ready:
            return ElephantTheme.green
        case .starting:
            return ElephantTheme.accent
        case .failed:
            return ElephantTheme.orange
        case .idle:
            return ElephantTheme.faint
        }
    }
}

struct ExpandableSettingsRow<Content: View>: View {
    var symbol: String
    var title: String
    var subtitle: String
    var content: Content
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Binding private var expanded: Bool
    @State private var hovering = false

    init(
        symbol: String,
        title: String,
        subtitle: String,
        expanded: Binding<Bool>,
        @ViewBuilder content: () -> Content
    ) {
        self.symbol = symbol
        self.title = title
        self.subtitle = subtitle
        self._expanded = expanded
        self.content = content()
    }

    var body: some View {
        VStack(spacing: 0) {
            Button {
                toggleExpanded()
            } label: {
                HStack(spacing: 14) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(iconBackground)
                        Image(systemName: symbol)
                            .font(.callout.weight(.semibold))
                            .foregroundStyle(iconColor)
                    }
                    .frame(width: 34, height: 34)

                    VStack(alignment: .leading, spacing: 3) {
                        Text(title)
                            .font(.headline.weight(.semibold))
                            .foregroundStyle(ElephantTheme.ink)
                        Text(subtitle)
                            .font(.callout)
                            .foregroundStyle(ElephantTheme.muted)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }

                    Spacer(minLength: 0)

                    ZStack {
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(expanded ? ElephantTheme.accent.opacity(0.14) : hovering ? ElephantTheme.accent.opacity(0.08) : Color.clear)
                        Image(systemName: "chevron.down")
                            .font(.callout.weight(.semibold))
                            .foregroundStyle(expanded || hovering ? ElephantTheme.accent : ElephantTheme.faint)
                            .rotationEffect(.degrees(expanded ? 0 : -90))
                    }
                    .frame(width: 32, height: 32)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .frame(maxWidth: .infinity, minHeight: 62, alignment: .leading)
                .background(rowBackground, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(rowBorder, lineWidth: expanded ? 1.2 : 1)
                )
                .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(PressablePlainButtonStyle())
            .onHover { hovering = $0 }
            .help("\(title): \(subtitle)")
            .accessibilityLabel("\(title), \(subtitle)")

            if expanded {
                HStack(alignment: .top, spacing: 0) {
                    RoundedRectangle(cornerRadius: 2, style: .continuous)
                        .fill(ElephantTheme.accent.opacity(0.16))
                        .frame(width: 3)
                        .padding(.top, 13)
                        .padding(.trailing, 47)
                    content
                        .padding(.top, 14)
                        .padding(.bottom, 18)
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 12)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }

            Divider()
                .padding(.leading, 58)
        }
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.18), value: expanded)
        .animation(.easeOut(duration: 0.14), value: hovering)
    }

    private func toggleExpanded() {
        if reduceMotion {
            expanded.toggle()
        } else {
            withAnimation(.easeInOut(duration: 0.18)) {
                expanded.toggle()
            }
        }
    }

    private var iconColor: Color {
        if expanded || hovering { return ElephantTheme.accent }
        return ElephantTheme.muted
    }

    private var iconBackground: Color {
        if expanded { return ElephantTheme.accent.opacity(0.10) }
        if hovering { return ElephantTheme.accent.opacity(0.08) }
        return ElephantTheme.faint.opacity(0.10)
    }

    private var rowBackground: Color {
        if expanded { return Color(nsColor: .controlBackgroundColor).opacity(0.66) }
        if hovering { return Color(nsColor: .controlBackgroundColor).opacity(0.58) }
        return Color.clear
    }

    private var rowBorder: Color {
        if expanded { return ElephantTheme.accent.opacity(0.16) }
        if hovering { return ElephantTheme.line.opacity(0.74) }
        return Color.clear
    }
}

enum SettingsActionKind {
    case primary
    case secondary
    case destructive
}

struct SettingsActionBar<Leading: View, Actions: View>: View {
    var leading: Leading
    var actions: Actions

    init(@ViewBuilder actions: () -> Actions) where Leading == EmptyView {
        self.leading = EmptyView()
        self.actions = actions()
    }

    init(@ViewBuilder leading: () -> Leading, @ViewBuilder actions: () -> Actions) {
        self.leading = leading()
        self.actions = actions()
    }

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            leading
            Spacer(minLength: 16)
            actions
        }
        .frame(maxWidth: .infinity, minHeight: 38, alignment: .trailing)
        .padding(.top, 10)
    }
}

private struct SettingsActionButtonModifier: ViewModifier {
    var kind: SettingsActionKind

    @ViewBuilder
    func body(content: Content) -> some View {
        content
            .font(.callout.weight(kind == .primary ? .semibold : .medium))
            .labelStyle(.titleAndIcon)
            .buttonStyle(PressablePlainButtonStyle())
            .foregroundStyle(foreground)
            .padding(.horizontal, 12)
            .frame(minWidth: kind == .secondary ? 86 : 104, minHeight: 34)
            .background(fill, in: RoundedRectangle(cornerRadius: 7, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .stroke(stroke, lineWidth: 1)
            )
            .contentShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
    }

    private var foreground: Color {
        switch kind {
        case .primary:
            return ElephantTheme.accent
        case .secondary:
            return ElephantTheme.ink.opacity(0.88)
        case .destructive:
            return ElephantTheme.orange
        }
    }

    private var fill: Color {
        switch kind {
        case .primary:
            return ElephantTheme.accent.opacity(0.10)
        case .secondary:
            return Color(nsColor: .controlBackgroundColor).opacity(0.72)
        case .destructive:
            return ElephantTheme.orange.opacity(0.08)
        }
    }

    private var stroke: Color {
        switch kind {
        case .primary:
            return ElephantTheme.accent.opacity(0.30)
        case .secondary:
            return ElephantTheme.line.opacity(0.78)
        case .destructive:
            return ElephantTheme.orange.opacity(0.30)
        }
    }
}

extension View {
    func settingsActionButton(_ kind: SettingsActionKind = .secondary) -> some View {
        modifier(SettingsActionButtonModifier(kind: kind))
    }
}

struct LanguageSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel

    private var languageBinding: Binding<AppLanguage> {
        Binding(
            get: { model.appLanguage },
            set: { model.setAppLanguage($0) }
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(model.text(.languageSettingsDescription))
                .font(.callout)
                .foregroundStyle(ElephantTheme.muted)
                .fixedSize(horizontal: false, vertical: true)
            Picker("", selection: languageBinding) {
                ForEach(AppLanguage.allCases) { language in
                    Text(language.nativeName).tag(language)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 360)
            SettingsRow(
                label: localizedYouText(model.appLanguage, en: "Current", zh: "当前", fr: "Actuelle", de: "Aktuell"),
                value: model.appLanguage.nativeName
            )
        }
    }
}

struct MemoryEngineSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var embeddingSource = ""
    @State private var loaded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 16) {
                SectionLabel(
                    title: localizedYouText(
                        model.appLanguage,
                        en: "Local Memory Model",
                        zh: "本地记忆模型",
                        fr: "Modèle mémoire local",
                        de: "Lokales Speichermodell"
                    ),
                    subtitle: localizedYouText(
                        model.appLanguage,
                        en: "Semantic recall uses this local model. Setup picks the best source for your language.",
                        zh: "语义回忆会使用这个本地模型；初始化会按语言自动选择默认来源。",
                        fr: "Le rappel sémantique utilise ce modèle local. La configuration choisit la source adaptée à votre langue.",
                        de: "Semantische Erinnerung nutzt dieses lokale Modell. Die Einrichtung wählt die passende Quelle für deine Sprache."
                    )
                )
                Spacer()
                Pill(text: embeddingSourceLabel(model.snapshot.embeddingBootstrapSource), symbol: "arrow.down.circle", tint: embeddingTint)
            }

            HStack(alignment: .center, spacing: 14) {
                Text(modelSourceLabel)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                    .frame(width: 106, alignment: .leading)
                Picker("", selection: $embeddingSource) {
                    Text("HuggingFace").tag("huggingface")
                    Text("ModelScope").tag("modelscope")
                }
                .labelsHidden()
                .pickerStyle(.segmented)
                .frame(width: 300)
            }

            VStack(spacing: 0) {
                SettingsRow(label: localizedYouText(model.appLanguage, en: "Status", zh: "状态", fr: "Statut", de: "Status"), value: embeddingLine)
                SettingsRow(label: localizedYouText(model.appLanguage, en: "Active source", zh: "当前来源", fr: "Source active", de: "Aktive Quelle"), value: embeddingSourceLabel(model.snapshot.embeddingBootstrapSource))
                SettingsRow(label: localizedYouText(model.appLanguage, en: "Setup default", zh: "初始化默认", fr: "Défaut de configuration", de: "Setup-Standard"), value: embeddingSourceLabel(model.appLanguage.defaultEmbeddingModelSource))
                if !model.snapshot.embeddingModelRoot.isEmpty {
                    SettingsRow(label: localizedYouText(model.appLanguage, en: "Model path", zh: "模型路径", fr: "Chemin du modèle", de: "Modellpfad"), value: model.snapshot.embeddingModelRoot)
                }
                if !model.snapshot.embeddingModelSourceURL.isEmpty {
                    SettingsRow(label: localizedYouText(model.appLanguage, en: "Source URL", zh: "来源地址", fr: "URL source", de: "Quell-URL"), value: model.snapshot.embeddingModelSourceURL)
                }
            }

            if !runtimeSummary.isEmpty {
                Text(runtimeSummary)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !model.embeddingActionResult.isEmpty {
                Text(model.embeddingActionResult)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.green)
                    .fixedSize(horizontal: false, vertical: true)
            }

            SettingsActionBar {
                Button {
                    Task { try? await model.refreshDashboard() }
                } label: {
                    Label(localizedYouText(model.appLanguage, en: "Refresh", zh: "刷新", fr: "Actualiser", de: "Aktualisieren"), systemImage: "arrow.clockwise")
                }
                .settingsActionButton()

                Button {
                    Task { await model.saveLocalEmbeddingSettings(source: embeddingSource, forceDownload: true) }
                } label: {
                    Label(localizedYouText(model.appLanguage, en: "Re-download", zh: "重新下载", fr: "Télécharger à nouveau", de: "Neu laden"), systemImage: "arrow.down.circle")
                }
                .settingsActionButton()

                Button {
                    Task { await model.saveLocalEmbeddingSettings(source: embeddingSource, forceDownload: false) }
                } label: {
                    Label(localizedYouText(model.appLanguage, en: "Apply Source", zh: "应用来源", fr: "Appliquer la source", de: "Quelle anwenden"), systemImage: "checkmark.circle")
                }
                .settingsActionButton(.primary)
            }
        }
        .onAppear {
            guard !loaded else { return }
            loadFromSnapshot()
            loaded = true
        }
        .onChange(of: model.snapshot.embeddingBootstrapSource) { _ in
            loadFromSnapshot()
        }
        .onChange(of: model.appLanguage) { _ in
            if model.snapshot.embeddingBootstrapSource.isEmpty {
                loadFromSnapshot()
            }
        }
    }

    private var modelSourceLabel: String {
        localizedYouText(
            model.appLanguage,
            en: "Model source",
            zh: "模型来源",
            fr: "Source du modèle",
            de: "Modellquelle"
        )
    }

    private var embeddingLine: String {
        let status = model.snapshot.embeddingStatus.isEmpty ? model.snapshot.semanticStatus : model.snapshot.embeddingStatus
        let runtime = model.snapshot.embeddingRuntimeState.trimmingCharacters(in: .whitespacesAndNewlines)
        let localizedStatus = localizedEmbeddingState(status, language: model.appLanguage)
        let localizedRuntime = runtime.isEmpty ? "" : localizedEmbeddingState(runtime, language: model.appLanguage)
        let suffix = localizedRuntime.isEmpty ? localizedStatus : "\(localizedStatus) · \(localizedRuntime)"
        if model.snapshot.embeddingProviderID.isEmpty {
            return suffix
        }
        return "\(model.snapshot.embeddingProviderID) · \(suffix)"
    }

    private var runtimeSummary: String {
        let raw = model.snapshot.embeddingRuntimeSummary.trimmingCharacters(in: .whitespacesAndNewlines)
        guard model.appLanguage == .zh else { return raw }
        let status = "\(model.snapshot.embeddingStatus) \(model.snapshot.embeddingRuntimeState) \(raw)".lowercased()
        if status.contains("download") {
            let root = model.snapshot.embeddingModelRoot.trimmingCharacters(in: .whitespacesAndNewlines)
            if root.isEmpty {
                return "依赖已就绪，正在等待本地记忆模型下载完成。"
            }
            return "依赖已就绪，正在等待本地记忆模型下载完成：\(root)"
        }
        if status.contains("ready") || status.contains("loaded") || status.contains("external") {
            return "本地记忆模型已就绪，语义回忆可以使用。"
        }
        if status.contains("missing") || status.contains("not found") {
            return "还没有可用的本地记忆模型，可以重新下载。"
        }
        return raw
    }

    private var embeddingTint: Color {
        let status = embeddingLine.lowercased()
        if status.contains("failed") || status.contains("missing") || status.contains("失败") || status.contains("未安装") {
            return ElephantTheme.orange
        }
        if status.contains("ready") || status.contains("loaded") || status.contains("external") || status.contains("就绪") {
            return ElephantTheme.green
        }
        return ElephantTheme.accent
    }

    private func embeddingSourceLabel(_ source: String) -> String {
        switch source.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "modelscope":
            return "ModelScope"
        case "huggingface":
            return "HuggingFace"
        default:
            return model.appLanguage.defaultEmbeddingModelSource == "modelscope" ? "ModelScope" : "HuggingFace"
        }
    }

    private func loadFromSnapshot() {
        embeddingSource = model.snapshot.embeddingBootstrapSource.isEmpty
            ? model.appLanguage.defaultEmbeddingModelSource
            : model.snapshot.embeddingBootstrapSource
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
    @State private var showingProviderConfig = false
    @State private var providerSearch = ""
    @State private var providerPage = 0

    private let providerPageSize = 16

    var body: some View {
        providerFactoryContent
            .animation(.spring(response: 0.36, dampingFraction: 0.86), value: showingProviderConfig)
        .onAppear {
            guard !loaded else { return }
            loadFromSnapshot()
            loaded = true
        }
        .onChange(of: model.snapshot.providerID) { _ in
            loadFromSnapshot()
        }
    }

    private var providerFactoryContent: some View {
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
                providerConfigurationForm
            } else {
                VStack(alignment: .leading, spacing: 12) {
                    SectionLabel(
                        title: model.text(.providerFactory),
                        subtitle: providerFactorySubtitle
                    )
                    ProviderSearchField(text: $providerSearch, placeholder: model.text(.providerSearchPlaceholder))

                    ZStack(alignment: .topTrailing) {
                        ProviderFactoryGrid(
                            options: pagedProviderOptions,
                            selectedID: providerID,
                            activeID: model.snapshot.providerID,
                            columnsCount: 4,
                            emptyText: localizedYouText(model.appLanguage, en: "No provider matches this search.", zh: "没有找到匹配的服务。", fr: "Aucun provider ne correspond.", de: "Kein passender Provider.")
                        ) { option in
                            selectProvider(option, openConfig: true)
                        }
                        .frame(maxWidth: .infinity)

                        if showingProviderConfig, let option = selectedOption {
                            ProviderConfigurationDropCard(option: option) {
                                showingProviderConfig = false
                            } content: {
                                providerConfigurationForm
                            }
                            .frame(maxWidth: 620)
                            .padding(.top, 8)
                            .padding(.trailing, 8)
                            .transition(.scale(scale: 0.96, anchor: .topTrailing).combined(with: .opacity))
                            .zIndex(2)
                        }
                    }

                    if providerPageCount > 1 {
                        HStack {
                            Text(localizedFormat(model.appLanguage, en: "%d-%d of %d providers", zh: "第 %d-%d 个 / 共 %d 个", fr: "%d-%d sur %d providers", de: "%d-%d von %d Providern", providerRangeStart, providerRangeEnd, filteredProviderOptions.count))
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(ElephantTheme.muted)
                            Spacer()
                            PageStepper(page: currentProviderPage, pageCount: providerPageCount) { direction in
                                providerPage = min(max(0, currentProviderPage + direction), providerPageCount - 1)
                            }
                        }
                    }
                }
            }
        }
        .onChange(of: providerSearch) { _ in
            providerPage = 0
        }
    }

    private var providerConfigurationForm: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    SectionLabel(title: model.text(.modelSection), subtitle: selectedOption?.active == true ? model.text(.activeModelSubtitle) : model.text(.modelPickerSubtitle))
                    Spacer()
                    Button {
                        Task { await loadLiveModels() }
                    } label: {
                        Label(
                            loadingModels
                                ? model.text(.fetching)
                                : localizedYouText(model.appLanguage, en: "Fetch models", zh: "刷新模型列表", fr: "Charger les modèles", de: "Modelle laden"),
                            systemImage: "arrow.clockwise"
                        )
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

                LabeledContent(model.text(.customModelID)) {
                    TextField(model.text(.modelID), text: $modelID)
                        .textFieldStyle(.roundedBorder)
                }
            }
            .padding(12)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))

            LabeledContent("Base URL") {
                TextField(localizedYouText(model.appLanguage, en: "optional endpoint", zh: "可选接口地址", fr: "endpoint optionnel", de: "optionaler Endpoint"), text: $baseURL)
                    .textFieldStyle(.roundedBorder)
            }
            LabeledContent(model.text(.apiKey)) {
                SecureField(localizedYouText(model.appLanguage, en: "stored locally", zh: "只保存在本机", fr: "stocké localement", de: "lokal gespeichert"), text: $apiKey)
                    .textFieldStyle(.roundedBorder)
            }
            LabeledContent(model.text(.contextWindowTokens)) {
                TextField(localizedYouText(model.appLanguage, en: "auto", zh: "自动", fr: "auto", de: "auto"), text: $contextWindow)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 160)
            }

            SettingsRow(
                label: localizedYouText(model.appLanguage, en: "Source", zh: "来源", fr: "Source", de: "Quelle"),
                value: model.snapshot.providerSource.isEmpty
                    ? localizedYouText(model.appLanguage, en: "not configured", zh: "尚未配置", fr: "non configuré", de: "nicht konfiguriert")
                    : model.snapshot.providerSource
            )

            HStack {
                Button(localizedYouText(model.appLanguage, en: "Save Provider", zh: "保存模型服务", fr: "Enregistrer le provider", de: "Provider speichern")) {
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

                Button(localizedYouText(model.appLanguage, en: "Test", zh: "测试", fr: "Tester", de: "Testen")) {
                    Task { await model.testProvider() }
                }
                .disabled(model.snapshot.providerID.isEmpty && providerID.isEmpty)

                Button(model.text(.refresh)) {
                    Task { try? await model.refreshDashboard() }
                }
            }
        }
    }

    private var selectedOption: ProviderOption? {
        model.snapshot.providerOptions.first(where: { $0.id == providerID })
    }

    private var availableModels: [ProviderModelOption] {
        discoveredModels[providerID] ?? selectedOption?.models ?? []
    }

    private var filteredProviderOptions: [ProviderOption] {
        let needle = providerSearch.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return model.snapshot.providerOptions
            .filter { option in
                guard !needle.isEmpty else { return true }
                return providerSearchText(option).contains(needle)
            }
            .sorted { left, right in
                let leftRank = providerSortRank(left)
                let rightRank = providerSortRank(right)
                if leftRank != rightRank { return leftRank < rightRank }
                return left.displayName.localizedCaseInsensitiveCompare(right.displayName) == .orderedAscending
            }
    }

    private var providerPageCount: Int {
        max(1, (filteredProviderOptions.count + providerPageSize - 1) / providerPageSize)
    }

    private var currentProviderPage: Int {
        min(max(providerPage, 0), providerPageCount - 1)
    }

    private var pagedProviderOptions: [ProviderOption] {
        Array(filteredProviderOptions.dropFirst(currentProviderPage * providerPageSize).prefix(providerPageSize))
    }

    private var providerRangeStart: Int {
        guard !filteredProviderOptions.isEmpty else { return 0 }
        return currentProviderPage * providerPageSize + 1
    }

    private var providerRangeEnd: Int {
        min(filteredProviderOptions.count, (currentProviderPage + 1) * providerPageSize)
    }

    private var providerFactorySubtitle: String {
        localizedFormat(
            model.appLanguage,
            en: "%d of %d providers · connected first",
            zh: "显示 %d / %d 个，已连接优先",
            fr: "%d sur %d providers · connectés d'abord",
            de: "%d von %d Providern · verbundene zuerst",
            filteredProviderOptions.count,
            model.snapshot.providerOptions.count
        )
    }

    private var providerStatusLabel: String {
        if model.snapshot.providerStatus == "unknown", !model.snapshot.providerID.isEmpty {
            return localizedProviderState("configured", language: model.appLanguage)
        }
        return localizedProviderState(
            model.snapshot.providerStatus == "unknown" ? "setup needed" : model.snapshot.providerStatus,
            language: model.appLanguage
        )
    }

    private var providerTint: Color {
        let value = model.snapshot.providerStatus.lowercased()
        return model.snapshot.providerID.isEmpty || value == "unknown" || value.contains("setup") || value.contains("missing")
            ? ElephantTheme.orange
            : ElephantTheme.green
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

    private func selectProvider(_ option: ProviderOption, openConfig: Bool) {
        providerID = option.id
        applyProviderDefaults(onlyWhenEmpty: false)
        showingProviderConfig = openConfig
    }

    private func loadLiveModels(force: Bool = false) async {
        guard !providerID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        loadingModels = true
        let rows = await model.discoverProviderModels(providerID: providerID, baseURL: baseURL, apiKey: apiKey)
        if !rows.isEmpty {
            discoveredModels[providerID] = rows
            if modelID.isEmpty || !rows.contains(where: { $0.id == modelID }) {
                modelID = rows.first?.id ?? modelID
            }
        }
        loadingModels = false
    }

    private func providerSearchText(_ option: ProviderOption) -> String {
        [
            option.displayName,
            option.id,
            option.defaultModel,
            option.defaultBaseURL,
            option.status,
            option.source,
            option.authKind,
            option.summary,
            option.models.map(\.id).joined(separator: " ")
        ]
        .joined(separator: " ")
        .lowercased()
    }

    private func providerSortRank(_ option: ProviderOption) -> Int {
        if option.id == model.snapshot.providerID || option.active { return 0 }
        if option.connected { return 1 }
        if option.storedKeyCount > 0 { return 2 }
        if option.id == providerID { return 3 }
        return 4
    }
}

struct ProviderConfigurationModalBackdrop: View {
    var dismiss: () -> Void

    var body: some View {
        Rectangle()
            .fill(.ultraThinMaterial)
            .overlay(Color(nsColor: .windowBackgroundColor).opacity(0.28))
            .contentShape(Rectangle())
            .onTapGesture(perform: dismiss)
            .accessibilityHidden(true)
    }
}

struct ProviderConfigurationModal<Content: View>: View {
    @EnvironmentObject private var model: ElephantAppModel
    var option: ProviderOption
    var close: () -> Void
    var content: Content

    init(option: ProviderOption, close: @escaping () -> Void, @ViewBuilder content: () -> Content) {
        self.option = option
        self.close = close
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center, spacing: 12) {
                ProviderLogoMark(option: option, size: 44)
                VStack(alignment: .leading, spacing: 3) {
                    Text(option.displayName)
                        .font(.headline)
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                    Text(option.id)
                        .font(.caption.monospaced())
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
                ProviderStatePill(option: option)
                Button(action: close) {
                    Image(systemName: "xmark")
                        .font(.callout.weight(.semibold))
                        .frame(width: 28, height: 28)
                        .contentShape(Circle())
                }
                .buttonStyle(PressablePlainButtonStyle())
                .foregroundStyle(ElephantTheme.muted)
                .help(localizedYouText(model.appLanguage, en: "Close", zh: "关闭", fr: "Fermer", de: "Schließen"))
                .accessibilityLabel(localizedYouText(model.appLanguage, en: "Close provider configuration", zh: "关闭模型服务设置", fr: "Fermer la configuration du provider", de: "Provider-Konfiguration schließen"))
            }
            Divider()
            ScrollView {
                content
                    .padding(.vertical, 2)
            }
            .frame(maxHeight: 560)
        }
        .padding(18)
        .frame(width: 680, alignment: .topLeading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(ElephantTheme.line.opacity(0.80), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.16), radius: 30, y: 18)
        .padding(.horizontal, 32)
    }
}

struct ProviderConfigurationDropCard<Content: View>: View {
    @EnvironmentObject private var model: ElephantAppModel
    var option: ProviderOption
    var close: () -> Void
    var content: Content

    init(option: ProviderOption, close: @escaping () -> Void, @ViewBuilder content: () -> Content) {
        self.option = option
        self.close = close
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center, spacing: 12) {
                ProviderLogoMark(option: option, size: 40)
                VStack(alignment: .leading, spacing: 3) {
                    Text(option.displayName)
                        .font(.headline)
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                    Text(option.id)
                        .font(.caption.monospaced())
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
                ProviderStatePill(option: option)
                Button(action: close) {
                    Image(systemName: "chevron.up")
                        .font(.callout.weight(.semibold))
                        .frame(width: 30, height: 30)
                        .contentShape(Circle())
                }
                .buttonStyle(PressablePlainButtonStyle())
                .foregroundStyle(ElephantTheme.muted)
                .help(localizedYouText(model.appLanguage, en: "Collapse", zh: "收起", fr: "Réduire", de: "Einklappen"))
                .accessibilityLabel(localizedYouText(model.appLanguage, en: "Collapse provider configuration", zh: "收起模型服务设置", fr: "Réduire la configuration du provider", de: "Provider-Konfiguration einklappen"))
            }
            Divider()
            ScrollView {
                content
                    .padding(.vertical, 2)
            }
            .frame(maxHeight: 520)
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(ElephantTheme.accent.opacity(0.28), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.12), radius: 20, y: 10)
    }
}

struct ProviderFactoryGrid: View {
    @EnvironmentObject private var model: ElephantAppModel
    var options: [ProviderOption]
    var selectedID: String
    var activeID: String
    var columnsCount: Int = 4
    var emptyText: String = "No provider matches this search."
    var select: (ProviderOption) -> Void

    var body: some View {
        VStack(spacing: 0) {
            if options.isEmpty {
                EmptyLine(symbol: "magnifyingglass", text: emptyText)
                    .padding(.vertical, 28)
                    .frame(maxWidth: .infinity)
            } else {
                VStack(spacing: 12) {
                    ForEach(providerRows.indices, id: \.self) { rowIndex in
                        HStack(spacing: 12) {
                            ForEach(providerRows[rowIndex]) { option in
                                Button {
                                    select(option)
                                } label: {
                                    ProviderFactoryCard(
                                        option: option,
                                        selected: option.id == selectedID,
                                        active: option.id == activeID
                                    )
                                }
                                .buttonStyle(PressablePlainButtonStyle())
                                .help(localizedFormat(model.appLanguage, en: "Configure %@", zh: "配置 %@", fr: "Configurer %@", de: "%@ konfigurieren", option.displayName))
                                .accessibilityLabel(localizedFormat(model.appLanguage, en: "Configure %@", zh: "配置 %@", fr: "Configurer %@", de: "%@ konfigurieren", option.displayName))
                                .frame(maxWidth: .infinity)
                            }
                            ForEach(0..<max(0, max(1, columnsCount) - providerRows[rowIndex].count), id: \.self) { _ in
                                Color.clear
                                    .frame(maxWidth: .infinity)
                            }
                        }
                    }
                }
                .padding(12)
            }
        }
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.50), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(ElephantTheme.line.opacity(0.72), lineWidth: 1)
        )
    }

    private var providerRows: [[ProviderOption]] {
        let width = max(1, columnsCount)
        return stride(from: 0, to: options.count, by: width).map { index in
            Array(options[index..<min(index + width, options.count)])
        }
    }
}

struct ProviderSearchField: View {
    @EnvironmentObject private var model: ElephantAppModel
    @Binding var text: String
    var placeholder: String
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.callout.weight(.semibold))
                .foregroundStyle(focused ? ElephantTheme.accent : ElephantTheme.muted)
            TextField(placeholder, text: $text)
                .textFieldStyle(.plain)
                .font(.callout)
                .focused($focused)
            if !text.isEmpty {
                Button {
                    text = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.faint)
                }
                .buttonStyle(.plain)
                .help(localizedYouText(model.appLanguage, en: "Clear search", zh: "清空搜索", fr: "Effacer la recherche", de: "Suche löschen"))
            }
        }
        .padding(.horizontal, 10)
        .frame(maxWidth: .infinity, minHeight: 34)
        .background(
            focused ? ElephantTheme.accent.opacity(0.08) : Color(nsColor: .controlBackgroundColor).opacity(0.72),
            in: RoundedRectangle(cornerRadius: 8, style: .continuous)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(focused ? ElephantTheme.accent.opacity(0.60) : ElephantTheme.line.opacity(0.72), lineWidth: 1)
        )
    }
}

struct ProviderFactoryList: View {
    @EnvironmentObject private var model: ElephantAppModel
    var options: [ProviderOption]
    var selectedID: String
    var activeID: String
    var select: (ProviderOption) -> Void

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 0) {
                if options.isEmpty {
                    EmptyLine(symbol: "magnifyingglass", text: localizedYouText(model.appLanguage, en: "No provider matches this search.", zh: "没有找到匹配的服务。", fr: "Aucun provider ne correspond.", de: "Kein passender Provider."))
                        .padding(.vertical, 20)
                } else {
                    ForEach(options) { option in
                        Button {
                            select(option)
                        } label: {
                            ProviderFactoryListRow(
                                option: option,
                                selected: option.id == selectedID,
                                active: option.id == activeID
                            )
                        }
                        .buttonStyle(PressablePlainButtonStyle())
                        .help(localizedFormat(model.appLanguage, en: "Configure %@", zh: "配置 %@", fr: "Configurer %@", de: "%@ konfigurieren", option.displayName))
                        .accessibilityLabel(localizedFormat(model.appLanguage, en: "Configure %@", zh: "配置 %@", fr: "Configurer %@", de: "%@ konfigurieren", option.displayName))
                        if option.id != options.last?.id {
                            Divider()
                                .padding(.leading, 54)
                        }
                    }
                }
            }
        }
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.54), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line.opacity(0.72), lineWidth: 1))
    }
}

struct ProviderFactoryListRow: View {
    var option: ProviderOption
    var selected: Bool
    var active: Bool

    var body: some View {
        HStack(spacing: 12) {
            ProviderLogoMark(option: option, size: 34)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 7) {
                    Text(option.displayName)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                    if isConnected {
                        Circle()
                            .fill(active ? ElephantTheme.accent : ElephantTheme.green)
                            .frame(width: 6, height: 6)
                    }
                }
                HStack(spacing: 8) {
                    Text(option.id)
                        .font(.caption.monospaced())
                    if !detailLine.isEmpty {
                        Text(detailLine)
                            .font(.caption)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                }
                .foregroundStyle(ElephantTheme.muted)
            }
            Spacer(minLength: 0)
            ProviderStatePill(option: resolvedOption)
            Image(systemName: selected ? "checkmark.circle.fill" : "chevron.right")
                .font(.callout.weight(.semibold))
                .foregroundStyle(selected ? ElephantTheme.accent : ElephantTheme.faint)
                .frame(width: 18)
        }
        .padding(.horizontal, 11)
        .padding(.vertical, 9)
        .frame(maxWidth: .infinity, minHeight: 54, alignment: .leading)
        .background(selected ? ElephantTheme.accent.opacity(0.09) : Color.clear)
        .contentShape(Rectangle())
    }

    private var isConnected: Bool {
        active || option.active || option.connected || option.storedKeyCount > 0
    }

    private var resolvedOption: ProviderOption {
        var copy = option
        if active {
            copy.active = true
            copy.connected = true
        }
        return copy
    }

    private var detailLine: String {
        if !option.defaultModel.isEmpty {
            return option.defaultModel
        }
        if !option.source.isEmpty {
            return option.source
        }
        return option.authKind
    }
}

struct ProviderFactoryCard: View {
    @EnvironmentObject private var model: ElephantAppModel
    var option: ProviderOption
    var selected: Bool
    var active: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center, spacing: 10) {
                ProviderLogoMark(option: option, size: 42)
                Spacer(minLength: 0)
                ProviderStatePill(option: resolvedOption)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(option.displayName)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                    .lineLimit(1)
                Text(option.id)
                    .font(.caption.monospaced())
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            Spacer(minLength: 0)
            Text(detailLine)
                .font(.caption)
                .foregroundStyle(ElephantTheme.muted)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, minHeight: 132, alignment: .topLeading)
        .background(background, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(borderColor, style: borderStroke)
        )
        .contentShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private var resolvedOption: ProviderOption {
        var copy = option
        if active {
            copy.active = true
            copy.connected = true
        }
        return copy
    }

    private var detailLine: String {
        if !option.defaultModel.isEmpty {
            return option.defaultModel
        }
        if !option.summary.isEmpty {
            return option.summary
        }
        return option.authKind.isEmpty ? model.text(.providerSetup) : option.authKind
    }

    private var background: Color {
        if active {
            return ElephantTheme.accent.opacity(0.09)
        }
        if selected {
            return ElephantTheme.accent.opacity(0.07)
        }
        if option.connected {
            return ElephantTheme.green.opacity(0.06)
        }
        return Color(nsColor: .controlBackgroundColor).opacity(0.82)
    }

    private var borderColor: Color {
        if active {
            return ElephantTheme.accent.opacity(0.72)
        }
        if option.connected {
            return ElephantTheme.green.opacity(0.66)
        }
        if selected {
            return ElephantTheme.accent.opacity(0.48)
        }
        return ElephantTheme.line
    }

    private var borderStroke: StrokeStyle {
        if active {
            return StrokeStyle(lineWidth: 2)
        }
        if option.connected {
            return StrokeStyle(lineWidth: 1.6, dash: [5, 4])
        }
        return StrokeStyle(lineWidth: selected ? 1.4 : 1)
    }
}

struct ProviderStatePill: View {
    @EnvironmentObject private var model: ElephantAppModel
    var option: ProviderOption

    var body: some View {
        Text(label)
            .font(.caption2.weight(.bold))
            .foregroundStyle(tint)
            .lineLimit(1)
            .padding(.horizontal, 7)
            .padding(.vertical, 4)
            .background(tint.opacity(0.10), in: Capsule())
            .overlay(Capsule().stroke(tint.opacity(0.22), lineWidth: 1))
    }

    private var label: String {
        if option.active {
            return localizedProviderState("In use", language: model.appLanguage)
        }
        if option.connected {
            return localizedProviderState("Connected", language: model.appLanguage)
        }
        if option.storedKeyCount > 0 {
            return localizedFormat(model.appLanguage, en: "%d key", zh: "%d 个密钥", fr: "%d clé", de: "%d Key", option.storedKeyCount)
        }
        return localizedProviderState("Use", language: model.appLanguage)
    }

    private var tint: Color {
        if option.active {
            return ElephantTheme.accent
        }
        if option.connected || option.storedKeyCount > 0 {
            return ElephantTheme.green
        }
        return ElephantTheme.muted
    }
}

struct ProviderLogoMark: View {
    var option: ProviderOption
    var size: CGFloat = 42

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color(nsColor: .textBackgroundColor).opacity(0.86))
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(ElephantTheme.line, lineWidth: 1)
            if let url = logoAsset.url {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFit()
                            .padding(size * 0.19)
                    default:
                        fallback
                    }
                }
            } else {
                fallback
            }
        }
        .frame(width: size, height: size)
    }

    private var fallback: some View {
        Text(initials)
            .font(.system(size: size * 0.34, weight: .bold, design: .rounded))
            .foregroundStyle(ElephantTheme.accent)
            .lineLimit(1)
    }

    private var initials: String {
        let words = option.displayName
            .split(whereSeparator: { !$0.isLetter && !$0.isNumber })
            .prefix(2)
        let letters = words.compactMap { $0.first }.map { String($0) }.joined()
        return letters.isEmpty ? String(option.id.prefix(2)).uppercased() : letters.uppercased()
    }

    private var logoAsset: ProviderLogoAsset {
        ProviderLogoAsset(providerID: option.id, displayName: option.displayName)
    }
}

struct ProviderLogoAsset {
    var providerID: String
    var displayName: String

    var url: URL? {
        LobeHubIconAsset(slug: slug).url
    }

    private var slug: String {
        let id = providerID.lowercased()
        if let alias = aliases[id] {
            return alias
        }
        let display = displayName.lowercased()
        if display.contains("baidu") || display.contains("qianfan") || display.contains("wenxin") { return "baidu" }
        if display.contains("cerebras") { return "cerebras" }
        if display.contains("claude code") { return "claudecode" }
        if display.contains("claude") { return "claude" }
        if display.contains("cohere") { return "cohere" }
        if display.contains("codex") || display.contains("openai") { return "openai" }
        if display.contains("copilot") { return "githubcopilot" }
        if display.contains("doubao") { return "doubao" }
        if display.contains("gemini cli") { return "geminicli" }
        if display.contains("gemini") || display.contains("google") { return "gemini" }
        if display.contains("groq") { return "groq" }
        if display.contains("hunyuan") { return "hunyuan" }
        if display.contains("kilo") { return "kilocode" }
        if display.contains("kimi") || display.contains("moonshot") { return "moonshot" }
        if display.contains("modelscope") { return "modelscope" }
        if display.contains("nvidia") { return "nvidia" }
        if display.contains("perplexity") { return "perplexity" }
        if display.contains("qwen") || display.contains("dashscope") || display.contains("alibaba") { return "qwen" }
        if display.contains("silicon") { return "siliconcloud" }
        if display.contains("stepfun") || display.contains("step") { return "stepfun" }
        if display.contains("tokenhub") { return "tencentcloud" }
        if display.contains("tencent") { return "tencent" }
        if display.contains("volcengine") || display.contains("ark") { return "volcengine" }
        if display.contains("xiaomi") { return "xiaomimimo" }
        return id.replacingOccurrences(of: "-", with: "")
    }

    private var aliases: [String: String] {
        [
            "baidu-qianfan": "baidu",
            "claude-code": "claudecode",
            "copilot": "githubcopilot",
            "copilot-acp": "githubcopilot",
            "google-gemini-cli": "geminicli",
            "kilocode": "kilocode",
            "minimax-cn": "minimax",
            "moonshot-cn": "moonshot",
            "opencode-go": "opencode",
            "opencode-zen": "opencode",
            "openai-compatible": "openai",
            "openai-codex": "openai",
            "qwen-oauth": "qwen",
            "siliconflow": "siliconcloud",
            "tencent-hunyuan": "hunyuan",
            "tencent-tokenhub": "tencentcloud",
            "volcengine": "doubao",
            "xiaomi": "xiaomimimo",
            "zai": "zai"
        ]
    }
}

private struct LobeHubIconAsset {
    var slug: String

    var url: URL? {
        URL(string: "https://unpkg.com/@lobehub/icons-static-png@latest/light/\(slug)\(suffix).png")
    }

    private var colorSlugs: Set<String> {
        [
            "alibaba",
            "baidu",
            "cerebras",
            "claude",
            "claudecode",
            "cohere",
            "crewai",
            "deepseek",
            "dify",
            "doubao",
            "fireworks",
            "figma",
            "gemini",
            "geminicli",
            "github",
            "google",
            "huggingface",
            "hunyuan",
            "langchain",
            "langgraph",
            "llamaindex",
            "mcp",
            "minimax",
            "mistral",
            "modelscope",
            "nvidia",
            "perplexity",
            "qwen",
            "siliconcloud",
            "stepfun",
            "tencent",
            "tencentcloud",
            "together",
            "vllm",
            "volcengine",
            "xiaomimimo",
            "zhipu"
        ]
    }

    private var suffix: String {
        colorSlugs.contains(slug) ? "-color" : ""
    }
}

struct ModelOptionPicker: View {
    @EnvironmentObject private var model: ElephantAppModel
    var options: [ProviderModelOption]
    @Binding var selectedID: String
    var loading: Bool
    var activeModelID: String

    var body: some View {
        if options.isEmpty {
            EmptyLine(
                symbol: loading ? "arrow.clockwise" : "sparkles",
                text: loading
                    ? localizedYouText(model.appLanguage, en: "Fetching models from the provider...", zh: "正在从模型服务拉取列表...", fr: "Chargement des modèles depuis le provider...", de: "Modelle werden vom Provider geladen...")
                    : localizedYouText(model.appLanguage, en: "No model list yet. Use Fetch models or type a custom model ID.", zh: "还没有模型列表。可以刷新模型列表，或手动填写模型 ID。", fr: "Aucune liste de modèles. Chargez les modèles ou saisissez un ID personnalisé.", de: "Noch keine Modellliste. Modelle laden oder eigene Modell-ID eingeben.")
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
    @EnvironmentObject private var model: ElephantAppModel
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
                        Text(localizedProviderState("active", language: model.appLanguage))
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
    @EnvironmentObject private var model: ElephantAppModel
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
                        Pill(text: localizedProviderState("active", language: model.appLanguage), symbol: "checkmark", tint: ElephantTheme.green)
                    } else if option.connected {
                        Pill(text: localizedProviderState("connected", language: model.appLanguage), symbol: "bolt.horizontal", tint: ElephantTheme.accent)
                    }
                    if option.storedKeyCount > 0 {
                        Pill(text: localizedFormat(model.appLanguage, en: "%d key", zh: "%d 个密钥", fr: "%d clé", de: "%d Key", option.storedKeyCount), symbol: "key", tint: ElephantTheme.green)
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
        let modelName = option.defaultModel.isEmpty
            ? localizedYouText(model.appLanguage, en: "model not selected", zh: "未选择模型", fr: "modèle non choisi", de: "Modell nicht gewählt")
            : option.defaultModel
        let endpoint = option.defaultBaseURL.isEmpty
            ? localizedYouText(model.appLanguage, en: "default endpoint", zh: "默认接口", fr: "endpoint par défaut", de: "Standard-Endpoint")
            : option.defaultBaseURL
        return "\(modelName) · \(endpoint)"
    }
}

struct ReflectSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SettingsRow(label: "Questions", value: "\(model.snapshot.waitingQuestions) open")
            SettingsRow(label: "Worker", value: model.snapshot.workerStatus)
            SettingsRow(label: "Latest", value: model.snapshot.latestCompletedAt.isEmpty ? "not yet" : MacLocalDateTime.formatted(model.snapshot.latestCompletedAt, language: model.appLanguage))
            SettingsActionBar {
                Button(model.isReflecting ? "Reflecting..." : "Run Reflect") {
                    Task { await model.runReflect(trigger: "settings") }
                }
                .settingsActionButton(.primary)
                .disabled(model.isReflecting)
            }
        }
    }
}

struct RuntimeSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SettingsRow(label: localizedYouText(model.appLanguage, en: "Core", zh: "核心", fr: "Noyau", de: "Kern"), value: model.corePhase.label)
            SettingsRow(label: "API", value: model.snapshot.apiURL.isEmpty ? localizedYouText(model.appLanguage, en: "starting", zh: "启动中", fr: "démarrage", de: "startet") : model.snapshot.apiURL)
            SettingsRow(label: localizedYouText(model.appLanguage, en: "Database", zh: "数据库", fr: "Base de données", de: "Datenbank"), value: model.snapshot.databasePath.isEmpty ? localizedYouText(model.appLanguage, en: "not resolved", zh: "尚未定位", fr: "non résolue", de: "nicht aufgelöst") : model.snapshot.databasePath)
            SettingsRow(label: localizedYouText(model.appLanguage, en: "Provider", zh: "模型服务", fr: "Provider", de: "Provider"), value: localizedRuntimeStatus(model.snapshot.providerStatus, language: model.appLanguage))
            SettingsRow(label: localizedYouText(model.appLanguage, en: "Semantic index", zh: "语义索引", fr: "Index sémantique", de: "Semantischer Index"), value: localizedRuntimeStatus(model.snapshot.semanticStatus, language: model.appLanguage))
            SettingsActionBar {
                Button {
                    Task { try? await model.refreshDashboard() }
                } label: {
                    Label(model.text(.refresh), systemImage: "arrow.clockwise")
                }
                .settingsActionButton()

                Button {
                    model.revealDatabase()
                } label: {
                    Label(model.text(.revealDatabase), systemImage: "externaldrive")
                }
                .settingsActionButton(.primary)
                .disabled(model.snapshot.databasePath.isEmpty)
            }
        }
    }
}

struct SleepDisplaySettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var password = ""
    @State private var confirmation = ""
    @State private var result = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SettingsFieldRow(
                label: model.text(.sleepAutoSleep),
                value: String(
                    format: localizedYouText(model.appLanguage, en: "%@ min", zh: "%@ 分钟", fr: "%@ min", de: "%@ Min."),
                    "\(model.sleepIdleMinutes)"
                )
            ) {
                Stepper(
                    "",
                    value: Binding(
                        get: { model.sleepIdleMinutes },
                        set: { model.updateSleepIdleMinutes($0) }
                    ),
                    in: 1...120,
                    step: 1
                )
                .labelsHidden()
                .frame(width: 72)
            }
            SettingsRow(label: model.text(.sleepWake), value: model.hasAppLockPassword ? model.text(.sleepPasswordRequired) : model.text(.sleepNoPassword))
            Divider()
            SectionLabel(
                title: model.text(.resetLockPassword),
                subtitle: model.text(.lockPasswordSubtitle)
            )
            HStack(spacing: 10) {
                SecureField(model.text(.lockPassword), text: $password)
                    .textFieldStyle(.roundedBorder)
                SecureField(model.text(.lockPasswordConfirm), text: $confirmation)
                    .textFieldStyle(.roundedBorder)
            }
            SettingsActionBar {
                Button(role: .destructive) {
                    model.clearAppLockPassword()
                    password = ""
                    confirmation = ""
                    result = model.text(.lockPasswordCleared)
                } label: {
                    Label(model.text(.clearLockPassword), systemImage: "trash")
                }
                .settingsActionButton(.destructive)

                Button {
                    let trimmed = password.trimmingCharacters(in: .whitespacesAndNewlines)
                    if trimmed.count >= 6 && trimmed == confirmation {
                        _ = model.setAppLockPassword(trimmed)
                        password = ""
                        confirmation = ""
                        result = model.text(.lockPasswordSaved)
                    } else if trimmed.count < 6 {
                        result = model.text(.lockPasswordRequirement)
                    } else {
                        result = model.text(.lockPasswordMismatch)
                    }
                } label: {
                    Label(model.text(.resetLockPassword), systemImage: "key")
                }
                .settingsActionButton(.primary)
                .disabled(password.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && confirmation.isEmpty)
            }
            if !result.isEmpty {
                Text(result)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(result == model.text(.lockPasswordSaved) || result == model.text(.lockPasswordCleared) ? ElephantTheme.green : ElephantTheme.orange)
            }
            Divider()
            SettingsActionBar {
                Button {
                    model.updateSleepIdleMinutes(10)
                } label: {
                    Label(model.text(.resetSleepTimer), systemImage: "timer")
                }
                .settingsActionButton()

                Button {
                    model.beginSleepDisplay(reason: "manual")
                } label: {
                    Label(model.text(.enterSleepDisplay), systemImage: "moon.zzz")
                }
                .settingsActionButton(.primary)
            }
        }
    }
}

struct ResetDataSettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var showingResetPopover = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SettingsRow(
                label: localizedYouText(model.appLanguage, en: "What resets", zh: "会清除", fr: "Éléments effacés", de: "Wird gelöscht"),
                value: localizedYouText(
                    model.appLanguage,
                    en: "Chats, Personal Model, provider keys, config, jobs, and local app state",
                    zh: "聊天、Personal Model、模型密钥、配置、任务和本机应用状态",
                    fr: "Conversations, Personal Model, clés provider, configuration, tâches et état local",
                    de: "Chats, Personal Model, Provider-Schlüssel, Konfiguration, Jobs und lokaler App-Zustand"
                )
            )
            SettingsRow(
                label: localizedYouText(model.appLanguage, en: "After reset", zh: "之后", fr: "Après", de: "Danach"),
                value: localizedYouText(
                    model.appLanguage,
                    en: "Setup opens again so you can start clean.",
                    zh: "会重新打开初始化流程，你可以从干净状态开始。",
                    fr: "La configuration se rouvre pour repartir de zéro.",
                    de: "Die Einrichtung öffnet sich erneut, damit du sauber starten kannst."
                )
            )

            if !model.resetDataResult.isEmpty {
                Text(model.resetDataResult)
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.green)
            }

            SettingsActionBar {
                Button(role: .destructive) {
                    showingResetPopover = true
                } label: {
                    Label(
                        model.isResettingData
                            ? localizedYouText(model.appLanguage, en: "Resetting...", zh: "正在重置…", fr: "Réinitialisation…", de: "Wird zurückgesetzt…")
                            : localizedYouText(model.appLanguage, en: "Reset all data", zh: "重置所有数据", fr: "Tout réinitialiser", de: "Alle Daten zurücksetzen"),
                        systemImage: "trash"
                    )
                }
                .settingsActionButton(.destructive)
                .disabled(model.isResettingData)
            }
            .popover(isPresented: $showingResetPopover, arrowEdge: .bottom) {
                VStack(alignment: .leading, spacing: 14) {
                    SectionLabel(
                        title: localizedYouText(model.appLanguage, en: "Reset Elephant Agent?", zh: "确定重置 Elephant Agent？", fr: "Réinitialiser Elephant Agent ?", de: "Elephant Agent zurücksetzen?"),
                        subtitle: localizedYouText(model.appLanguage, en: "This cannot be undone.", zh: "这个操作无法撤销。", fr: "Cette action est irréversible.", de: "Das kann nicht rückgängig gemacht werden.")
                    )
                    VStack(alignment: .leading, spacing: 8) {
                        EmptyLine(symbol: "message", text: localizedYouText(model.appLanguage, en: "Chat history and episodes will be deleted.", zh: "聊天历史和会话记录会被删除。", fr: "L'historique et les épisodes seront supprimés.", de: "Chatverlauf und Episoden werden gelöscht."))
                        EmptyLine(symbol: "person.crop.circle", text: localizedYouText(model.appLanguage, en: "Personal Model facts and questions will be deleted.", zh: "Personal Model 事实和问题会被删除。", fr: "Les faits et questions du Personal Model seront supprimés.", de: "Personal-Model-Fakten und Fragen werden gelöscht."))
                        EmptyLine(symbol: "key", text: localizedYouText(model.appLanguage, en: "Provider keys, config, and jobs will be deleted.", zh: "模型密钥、配置和任务会被删除。", fr: "Les clés provider, la configuration et les tâches seront supprimées.", de: "Provider-Schlüssel, Konfiguration und Jobs werden gelöscht."))
                    }
                    SettingsActionBar {
                        Button(localizedYouText(model.appLanguage, en: "Cancel", zh: "取消", fr: "Annuler", de: "Abbrechen")) {
                            showingResetPopover = false
                        }
                        .settingsActionButton()

                        Button(role: .destructive) {
                            showingResetPopover = false
                            Task { await model.resetAllData() }
                        } label: {
                            Label(localizedYouText(model.appLanguage, en: "Reset all data", zh: "重置所有数据", fr: "Tout réinitialiser", de: "Alle Daten zurücksetzen"), systemImage: "trash")
                        }
                        .settingsActionButton(.destructive)
                        .disabled(model.isResettingData)
                    }
                }
                .padding(16)
                .frame(width: 390)
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
                title: localizedYouText(model.appLanguage, en: "Skill Library", zh: "技能库", fr: "Bibliothèque de skills", de: "Skill-Bibliothek"),
                subtitle: localizedYouText(model.appLanguage, en: "Enable only what normal agent loops should use.", zh: "只打开日常对话里真的会用到的技能。", fr: "Activez seulement ce que les boucles agent normales doivent utiliser.", de: "Aktiviere nur, was normale Agent-Loops nutzen sollen."),
                searchPrompt: localizedYouText(model.appLanguage, en: "Search skills", zh: "搜索技能", fr: "Rechercher des skills", de: "Skills suchen"),
                emptySymbol: "wand.and.stars",
                emptyText: model.snapshot.skills > 0
                    ? localizedFormat(model.appLanguage, en: "%d skills detected.", zh: "已经识别出 %d 个技能。", fr: "%d skills détectés.", de: "%d Skills erkannt.", model.snapshot.skills)
                    : localizedYouText(model.appLanguage, en: "No skills returned yet.", zh: "本地运行时还没有返回技能列表。", fr: "Aucun skill retourné.", de: "Noch keine Skills zurückgegeben."),
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
                title: localizedYouText(model.appLanguage, en: "Tool Library", zh: "工具库", fr: "Bibliothèque d'outils", de: "Tool-Bibliothek"),
                subtitle: localizedYouText(model.appLanguage, en: "Built-in and MCP actions available to the local runtime.", zh: "本地运行时可以调用的内置工具和 MCP 工具。", fr: "Actions intégrées et MCP disponibles dans le runtime local.", de: "Eingebaute und MCP-Aktionen der lokalen Runtime."),
                searchPrompt: localizedYouText(model.appLanguage, en: "Search tools", zh: "搜索工具", fr: "Rechercher des outils", de: "Tools suchen"),
                emptySymbol: "wrench.and.screwdriver",
                emptyText: model.snapshot.tools > 0
                    ? localizedFormat(model.appLanguage, en: "%d tools detected.", zh: "已经识别出 %d 个工具。", fr: "%d outils détectés.", de: "%d Tools erkannt.", model.snapshot.tools)
                    : localizedYouText(model.appLanguage, en: "No tools returned yet.", zh: "本地运行时还没有返回工具列表。", fr: "Aucun outil retourné.", de: "Noch keine Tools zurückgegeben."),
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
            title: localizedYouText(model.appLanguage, en: "Skill Library", zh: "技能库", fr: "Bibliothèque de skills", de: "Skill-Bibliothek"),
            subtitle: localizedYouText(model.appLanguage, en: "Enable only what normal agent loops should use.", zh: "只打开日常对话里真的会用到的技能。", fr: "Activez seulement ce que les boucles agent normales doivent utiliser.", de: "Aktiviere nur, was normale Agent-Loops nutzen sollen."),
            searchPrompt: localizedYouText(model.appLanguage, en: "Search skills", zh: "搜索技能", fr: "Rechercher des skills", de: "Skills suchen"),
            emptySymbol: "wand.and.stars",
            emptyText: model.snapshot.skills > 0
                ? localizedFormat(model.appLanguage, en: "%d skills detected.", zh: "已经识别出 %d 个技能。", fr: "%d skills détectés.", de: "%d Skills erkannt.", model.snapshot.skills)
                : localizedYouText(model.appLanguage, en: "No skills returned yet.", zh: "本地运行时还没有返回技能列表。", fr: "Aucun skill retourné.", de: "Noch keine Skills zurückgegeben."),
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
            title: localizedYouText(model.appLanguage, en: "Tool Library", zh: "工具库", fr: "Bibliothèque d'outils", de: "Tool-Bibliothek"),
            subtitle: localizedYouText(model.appLanguage, en: "Built-in and MCP actions available to the local runtime.", zh: "本地运行时可以调用的内置工具和 MCP 工具。", fr: "Actions intégrées et MCP disponibles dans le runtime local.", de: "Eingebaute und MCP-Aktionen der lokalen Runtime."),
            searchPrompt: localizedYouText(model.appLanguage, en: "Search tools", zh: "搜索工具", fr: "Rechercher des outils", de: "Tools suchen"),
            emptySymbol: "wrench.and.screwdriver",
            emptyText: model.snapshot.tools > 0
                ? localizedFormat(model.appLanguage, en: "%d tools detected.", zh: "已经识别出 %d 个工具。", fr: "%d outils détectés.", de: "%d Tools erkannt.", model.snapshot.tools)
                : localizedYouText(model.appLanguage, en: "No tools returned yet.", zh: "本地运行时还没有返回工具列表。", fr: "Aucun outil retourné.", de: "Noch keine Tools zurückgegeben."),
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
    @EnvironmentObject private var model: ElephantAppModel
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
                    Pill(
                        text: localizedFormat(model.appLanguage, en: "%d enabled", zh: "%d 已启用", fr: "%d activés", de: "%d aktiv", enabledCount),
                        symbol: "checkmark.seal",
                        tint: ElephantTheme.green
                    )
                    Pill(
                        text: localizedFormat(model.appLanguage, en: "%d total", zh: "%d 总计", fr: "%d au total", de: "%d gesamt", totalCount),
                        symbol: kind == "tools" ? "wrench.and.screwdriver" : "wand.and.stars",
                        tint: logoTint
                    )
                }
            }

            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                TextField(searchPrompt, text: $query)
                    .textFieldStyle(.plain)
                Spacer(minLength: 8)
                Text(localizedFormat(model.appLanguage, en: "%d shown", zh: "显示 %d 个", fr: "%d affichés", de: "%d gezeigt", filteredCount))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line, lineWidth: 1))

            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(
                    items.isEmpty
                        ? localizedYouText(model.appLanguage, en: "Catalog", zh: "目录", fr: "Catalogue", de: "Katalog")
                        : localizedFormat(
                            model.appLanguage,
                            en: "%d enabled · %d available on this page",
                            zh: "本页已启用 %d 个 · 还可启用 %d 个",
                            fr: "%d activés · %d disponibles sur cette page",
                            de: "%d aktiv · %d auf dieser Seite verfügbar",
                            enabledPageItems.count,
                            availablePageItems.count
                        )
                )
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                    .textCase(.uppercase)
                Spacer(minLength: 0)
                Text(localizedFormat(model.appLanguage, en: "Page %d of %d", zh: "第 %d / %d 页", fr: "Page %d sur %d", de: "Seite %d von %d", currentPage + 1, pageCount))
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
    var brandSlug: String? = nil

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(tint.opacity(0.11))
            if let url = brandURL {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFit()
                            .padding(8)
                    default:
                        fallbackIcon
                    }
                }
            } else {
                fallbackIcon
            }
        }
        .frame(width: 42, height: 42)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(tint.opacity(0.22), lineWidth: 1)
        )
    }

    private var fallbackIcon: some View {
        Image(systemName: symbol)
            .font(.system(size: 18, weight: .semibold))
            .foregroundStyle(tint)
    }

    private var brandURL: URL? {
        guard let brandSlug, !brandSlug.isEmpty else { return nil }
        return LobeHubIconAsset(slug: brandSlug).url
    }
}

private struct OperatorCatalogRow: View {
    @EnvironmentObject private var model: ElephantAppModel
    var kind: String
    var item: OperationItem

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            OperatorCatalogLogo(symbol: logo.symbol, tint: logo.tint, brandSlug: logo.brandSlug)

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
                Text(
                    item.detail.isEmpty
                        ? localizedYouText(model.appLanguage, en: "No description returned by the local runtime.", zh: "本地运行时没有提供说明。", fr: "Aucune description retournée par le runtime local.", de: "Keine Beschreibung von der lokalen Runtime.")
                        : item.detail
                )
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 12)

            HStack(spacing: 8) {
                Pill(
                    text: item.enabled
                        ? localizedYouText(model.appLanguage, en: "enabled", zh: "已启用", fr: "activé", de: "aktiv")
                        : localizedYouText(model.appLanguage, en: "available", zh: "可启用", fr: "disponible", de: "verfügbar"),
                    symbol: item.enabled ? "checkmark" : "circle",
                    tint: item.enabled ? ElephantTheme.green : ElephantTheme.faint
                )
                Button(
                    item.enabled
                        ? localizedYouText(model.appLanguage, en: "Disable", zh: "停用", fr: "Désactiver", de: "Deaktivieren")
                        : localizedYouText(model.appLanguage, en: "Enable", zh: "启用", fr: "Activer", de: "Aktivieren")
                ) {
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
                let logo = OperatorLogoSpec.forText(name, kind: kind)
                HStack(spacing: 12) {
                    OperatorCatalogLogo(
                        symbol: logo.symbol,
                        tint: logo.tint,
                        brandSlug: logo.brandSlug
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
    var brandSlug: String? = nil

    static func forItem(_ item: OperationItem, kind: String) -> OperatorLogoSpec {
        let raw = "\(item.id) \(item.title) \(item.detail)".lowercased()
        return forText(raw, kind: kind)
    }

    static func forText(_ text: String, kind: String) -> OperatorLogoSpec {
        let raw = text.lowercased()
        if let brandSlug = brandSlug(for: raw) {
            return OperatorLogoSpec(
                symbol: kind == "tools" ? "wrench.and.screwdriver" : "sparkles",
                tint: kind == "tools" ? ElephantTheme.accent : ElephantTheme.orange,
                brandSlug: brandSlug
            )
        }
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

    private static func brandSlug(for raw: String) -> String? {
        if raw.contains("openai") || raw.contains("chatgpt") || raw.contains("codex") { return "openai" }
        if raw.contains("anthropic") || raw.contains("claude") { return "claude" }
        if raw.contains("gemini") || raw.contains("google ai") || raw.contains("ai studio") { return "gemini" }
        if raw.contains("deepseek") { return "deepseek" }
        if raw.contains("qwen") || raw.contains("dashscope") || raw.contains("alibaba") { return "qwen" }
        if raw.contains("kimi") || raw.contains("moonshot") { return "moonshot" }
        if raw.contains("minimax") { return "minimax" }
        if raw.contains("mistral") { return "mistral" }
        if raw.contains("groq") { return "groq" }
        if raw.contains("xai") || raw.contains("grok") { return "xai" }
        if raw.contains("cohere") { return "cohere" }
        if raw.contains("perplexity") { return "perplexity" }
        if raw.contains("cerebras") { return "cerebras" }
        if raw.contains("nvidia") || raw.contains("nim") || raw.contains("nemotron") { return "nvidia" }
        if raw.contains("siliconflow") || raw.contains("silicon cloud") { return "siliconcloud" }
        if raw.contains("doubao") || raw.contains("volcengine") { return "doubao" }
        if raw.contains("tokenhub") { return "tencentcloud" }
        if raw.contains("hunyuan") || raw.contains("tencent") { return "hunyuan" }
        if raw.contains("qianfan") || raw.contains("wenxin") || raw.contains("baidu") { return "baidu" }
        if raw.contains("stepfun") { return "stepfun" }
        if raw.contains("modelscope") { return "modelscope" }
        if raw.contains("hugging") || raw.contains("transformers") { return "huggingface" }
        if raw.contains("ollama") { return "ollama" }
        if raw.contains("vllm") { return "vllm" }
        if raw.contains("figma") { return "figma" }
        if raw.contains("github") || raw.contains("gh-") || raw.contains("gh_") { return "github" }
        if raw.contains("notion") { return "notion" }
        if raw.contains("langchain") { return "langchain" }
        if raw.contains("langgraph") { return "langgraph" }
        if raw.contains("llamaindex") || raw.contains("llama index") { return "llamaindex" }
        if raw.contains("crewai") || raw.contains("crew ai") { return "crewai" }
        if raw.contains("dify") { return "dify" }
        if raw.contains("mcp") { return "mcp" }
        return nil
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

                SettingsActionBar {
                    if !model.configActionResult.isEmpty {
                        Label(model.configActionResult, systemImage: "checkmark.circle.fill")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(ElephantTheme.green)
                    } else if hasChanges {
                        Text("Unsaved")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(ElephantTheme.orange)
                    }
                } actions: {
                    Button("Refresh") {
                        Task { try? await model.refreshDashboard() }
                    }
                    .settingsActionButton()

                    Button("Reset") {
                        draft = model.snapshot.settingsYaml
                    }
                    .settingsActionButton()
                    .disabled(!hasChanges)

                    Button("Save Config") {
                        Task { await model.saveGlobalConfig(yamlText: draft) }
                    }
                    .settingsActionButton(.primary)
                    .disabled(!hasChanges || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
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
                    Button(
                        item.enabled
                            ? localizedYouText(model.appLanguage, en: "Disable", zh: "停用", fr: "Désactiver", de: "Deaktivieren")
                            : localizedYouText(model.appLanguage, en: "Enable", zh: "启用", fr: "Activer", de: "Aktivieren")
                    ) {
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
            HStack(alignment: .center, spacing: 18) {
                Text(localizedYouText(model.appLanguage, en: "Ask rhythm", zh: "提问节奏", fr: "Rythme", de: "Fragerhythmus"))
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.muted)
                    .frame(width: 148, alignment: .leading)
                Picker("", selection: Binding(
                    get: { model.snapshot.questionIntensity },
                    set: { value in Task { await model.setCuriosityIntensity(value) } }
                )) {
                    Text(localizedYouText(model.appLanguage, en: "Low", zh: "低", fr: "Bas", de: "Niedrig")).tag("low")
                    Text(localizedYouText(model.appLanguage, en: "Medium", zh: "适中", fr: "Moyen", de: "Mittel")).tag("medium")
                    Text(localizedYouText(model.appLanguage, en: "High", zh: "高", fr: "Élevé", de: "Hoch")).tag("high")
                }
                .labelsHidden()
                .pickerStyle(.segmented)
                .frame(width: 300)
            }
            SettingsRow(
                label: localizedYouText(model.appLanguage, en: "Cadence", zh: "生效规则", fr: "Cadence", de: "Takt"),
                value: curiosityCadence
            )
            SettingsRow(label: localizedYouText(model.appLanguage, en: "Open questions", zh: "待回答问题", fr: "Questions ouvertes", de: "Offene Fragen"), value: "\(model.snapshot.waitingQuestions)")
            if model.snapshot.sampleQuestions.isEmpty {
                EmptyLine(symbol: "questionmark.bubble", text: localizedYouText(model.appLanguage, en: "No Personal Model questions are waiting right now.", zh: "现在没有待回答的 Personal Model 问题。", fr: "Aucune question Personal Model n'attend pour le moment.", de: "Gerade warten keine Personal-Model-Fragen."))
            } else {
                ForEach(model.snapshot.sampleQuestions, id: \.self) { question in
                    SettingsRow(label: localizedYouText(model.appLanguage, en: "Question", zh: "问题", fr: "Question", de: "Frage"), value: question)
                }
            }
        }
    }

    private var curiosityCadence: String {
        let enabled = model.snapshot.questionAskEnabled
            ? localizedYouText(model.appLanguage, en: "on", zh: "开启", fr: "actif", de: "an")
            : localizedYouText(model.appLanguage, en: "off", zh: "关闭", fr: "inactif", de: "aus")
        return "\(enabled) · idle \(model.snapshot.questionIdleMinutes)m · max \(model.snapshot.questionDailyMax)/day · quiet \(model.snapshot.questionQuietStart):00-\(model.snapshot.questionQuietEnd):00"
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
                MetricTile(label: localizedYouText(model.appLanguage, en: "Episodes", zh: "会话", fr: "Épisodes", de: "Episoden"), value: "\(model.snapshot.episodes)", symbol: "rectangle.stack")
                MetricTile(label: localizedYouText(model.appLanguage, en: "Loops", zh: "循环", fr: "Boucles", de: "Loops"), value: "\(model.snapshot.loops)", symbol: "arrow.triangle.2.circlepath", tint: ElephantTheme.green)
                MetricTile(label: localizedYouText(model.appLanguage, en: "Steps", zh: "步骤", fr: "Étapes", de: "Schritte"), value: "\(model.snapshot.steps)", symbol: "point.topleft.down.curvedto.point.bottomright.up", tint: ElephantTheme.orange)
            }

            SettingsRow(label: localizedYouText(model.appLanguage, en: "Usage events", zh: "使用事件", fr: "Événements", de: "Nutzungsereignisse"), value: "\(model.snapshot.usageEvents)")
            SettingsRow(label: "Tokens", value: abbreviatedCount(model.snapshot.usageTokens))

            if !model.snapshot.episodeThreads.isEmpty {
                Divider()
                SectionLabel(
                    title: localizedYouText(model.appLanguage, en: "Recent Conversations", zh: "最近对话", fr: "Conversations récentes", de: "Letzte Unterhaltungen"),
                    subtitle: localizedYouText(model.appLanguage, en: "Jump back into the traces that shaped Elephant.", zh: "回到那些正在塑造 Elephant 的对话。", fr: "Revenir aux traces qui façonnent Elephant.", de: "Zurück zu den Spuren, die Elephant prägen.")
                )
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
                        Button {
                            model.openEpisodeThread(thread)
                        } label: {
                            Label(localizedYouText(model.appLanguage, en: "Open", zh: "打开", fr: "Ouvrir", de: "Öffnen"), systemImage: "arrow.up.right")
                        }
                        .settingsActionButton()
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
            SettingsRow(label: localizedYouText(model.appLanguage, en: "Log files", zh: "日志文件", fr: "Fichiers log", de: "Logdateien"), value: "\(model.snapshot.logs)")
            if model.snapshot.logFiles.isEmpty {
                EmptyLine(symbol: "stethoscope", text: localizedYouText(model.appLanguage, en: "No local log files were found.", zh: "当前没有找到本地日志。", fr: "Aucun fichier log local trouvé.", de: "Keine lokalen Logdateien gefunden."))
            } else {
                HStack(alignment: .top, spacing: 16) {
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
                    .frame(width: 330)

                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            SectionLabel(
                                title: selected.name.isEmpty ? localizedYouText(model.appLanguage, en: "Log detail", zh: "日志详情", fr: "Détail du log", de: "Logdetails") : selected.name,
                                subtitle: selected.detail
                            )
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
                    .frame(maxWidth: .infinity, alignment: .topLeading)
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
    @EnvironmentObject private var model: ElephantAppModel
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
            Text(logDetail)
                .font(.caption2)
                .foregroundStyle(ElephantTheme.faint)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(selected ? ElephantTheme.accent.opacity(0.10) : Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(selected ? ElephantTheme.accent.opacity(0.45) : ElephantTheme.line, lineWidth: 1))
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var logDetail: String {
        [
            item.size > 0 ? "\(item.size) bytes" : "",
            MacLocalDateTime.formatted(item.updatedAt, language: model.appLanguage, fallback: "")
        ]
        .filter { !$0.isEmpty }
        .joined(separator: " · ")
    }
}

struct LogTailView: View {
    var lines: [String]

    var body: some View {
        if lines.isEmpty {
            EmptyLine(symbol: "doc.text", text: "No log preview available.")
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
                SettingsRow(label: "Embedding source", value: embeddingSourceLabel)

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

    private var embeddingSourceLabel: String {
        switch model.snapshot.embeddingBootstrapSource.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "modelscope":
            return "ModelScope"
        case "huggingface":
            return "HuggingFace"
        default:
            return model.appLanguage.defaultEmbeddingModelSource == "modelscope" ? "ModelScope" : "HuggingFace"
        }
    }
}

struct ReflectSettingsPanel: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                SectionLabel(title: "Reflect", subtitle: localizedYouText(model.appLanguage, en: "Background evolution jobs", zh: "后台自我进化任务", fr: "Jobs d'évolution en arrière-plan", de: "Hintergrund-Evolutionsjobs"))
                SettingsRow(label: "Questions", value: "\(model.snapshot.waitingQuestions) open")
                SettingsRow(label: "Worker", value: model.snapshot.workerStatus)
                SettingsRow(label: "Latest", value: model.snapshot.latestCompletedAt.isEmpty ? "not yet" : MacLocalDateTime.formatted(model.snapshot.latestCompletedAt, language: model.appLanguage))

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
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var onComplete: () -> Void
    @State private var transitionForward = true
    private let learnStep = 16
    private let readyStep = 17
    private let totalSteps = 18

    var body: some View {
        ZStack {
            OnboardingBackdrop()
            VStack(spacing: 18) {
                VStack(spacing: 10) {
                    BrandMark(size: 112, framed: false)
                        .shadow(color: ElephantTheme.accent.opacity(0.10), radius: 22, y: 10)
                    Text(model.text(.setupTitle))
                        .font(.system(size: 28, weight: .semibold))
                        .foregroundStyle(ElephantTheme.ink)
                    Text(model.text(.setupSubtitle))
                        .font(.callout)
                        .foregroundStyle(ElephantTheme.muted)
                }

                VStack(spacing: 0) {
                    ZStack(alignment: .topLeading) {
                        stepContent
                            .id(model.onboardingStep)
                            .transition(stepTransition)
                    }
                    .clipped()
                    .animation(stepAnimation, value: model.onboardingStep)
                        .padding(.horizontal, 40)
                        .padding(.top, 32)
                        .padding(.bottom, 20)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    Divider()
                    footer
                }
                .frame(width: 680, height: 486)
                .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(Color.white.opacity(0.42), lineWidth: 1)
                )
                .shadow(color: Color.black.opacity(0.18), radius: 34, y: 22)

                OnboardingPhaseRail(
                    phases: phases,
                    activeStep: min(model.onboardingStep, readyStep),
                    language: model.appLanguage,
                    canNavigate: model.onboardingStep < learnStep
                ) { phase in
                    selectPhaseIfAllowed(phase)
                }
                .frame(width: 680)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding(.vertical, 24)
            .padding(.horizontal, 28)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onExitCommand {
            goBackIfPossible()
        }
    }

    @ViewBuilder
    private var stepContent: some View {
        switch model.onboardingStep {
        case 0:
            OnboardingLanguageStep()
        case 1:
            OnboardingIdentityStep()
        case 2:
            OnboardingLockPasswordStep()
        case 3:
            OnboardingWorkStep()
        case 4:
            OnboardingInterestsStep()
        case 5:
            OnboardingLinksStep()
        case 6:
            OnboardingHealthNotesStep()
        case 7:
            OnboardingSurveySingleStep(kind: .innerLandscape)
        case 8:
            OnboardingSurveySingleStep(kind: .valueAnchor)
        case 9:
            OnboardingSurveySingleStep(kind: .pressurePattern)
        case 10:
            OnboardingSurveySingleStep(kind: .recoveryStyle)
        case 11:
            OnboardingSurveySingleStep(kind: .decisionCompass)
        case 12:
            OnboardingElephantStep()
        case 13:
            OnboardingProviderModelStep()
        case 14:
            OnboardingModelSelectionStep()
        case 15:
            OnboardingProviderSecretStep()
        case 16:
            OnboardingLearningStep()
        default:
            OnboardingCelebrationStep()
        }
    }

    private var footer: some View {
        HStack(spacing: 12) {
            if model.onboardingStep > 0 && model.onboardingStep < learnStep {
                Button {
                    goBackIfPossible()
                } label: {
                    Label(model.text(.back), systemImage: "chevron.left")
                }
                .controlSize(.large)
                .keyboardShortcut(.cancelAction)
            } else {
                Spacer().frame(width: 96)
            }

            Spacer()

            VStack(spacing: 2) {
                Label(currentPhase.title.text(model.appLanguage), systemImage: currentPhase.symbol)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                    .labelStyle(.titleAndIcon)
                    .lineLimit(1)
                if let nextRequirement {
                    Label(nextRequirement, systemImage: "exclamationmark.circle.fill")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(ElephantTheme.orange)
                        .labelStyle(.titleAndIcon)
                        .lineLimit(1)
                        .minimumScaleFactor(0.78)
                } else {
                    Text("\(min(model.onboardingStep + 1, totalSteps))/\(totalSteps)")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(ElephantTheme.faint)
                        .monospacedDigit()
                }
            }
            .frame(minWidth: 190)

            if model.onboardingStep < learnStep {
                Button {
                    advanceIfPossible()
                } label: {
                    Label(nextTitle, systemImage: "chevron.right")
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(ElephantTheme.accent)
                .disabled(nextDisabled)
                .help(nextRequirement ?? nextTitle)
                .accessibilityHint(nextRequirement ?? nextTitle)
                .keyboardShortcut(.defaultAction)
            } else if model.onboardingStep == readyStep {
                Button {
                    onComplete()
                } label: {
                    Label(model.text(.enterElephant), systemImage: "arrow.right.circle.fill")
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(ElephantTheme.accent)
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(.horizontal, 30)
        .padding(.vertical, 18)
        .background(Color(nsColor: .windowBackgroundColor).opacity(0.40))
    }

    private func goBackIfPossible() {
        guard model.onboardingStep > 0 && model.onboardingStep < learnStep else { return }
        transitionForward = false
        withAnimation(stepAnimation) {
            model.onboardingStep = max(0, model.onboardingStep - 1)
        }
    }

    private func advanceIfPossible() {
        guard model.onboardingStep < learnStep, !nextDisabled else { return }
        if model.onboardingStep == 2 {
            _ = model.persistOnboardingLockPassword()
        }
        transitionForward = true
        withAnimation(stepAnimation) {
            model.onboardingStep = min(learnStep, model.onboardingStep + 1)
        }
    }

    private func selectPhaseIfAllowed(_ phase: OnboardingPhase) {
        guard model.onboardingStep < learnStep,
              phase.range.lowerBound <= model.onboardingStep
        else { return }
        transitionForward = phase.range.lowerBound >= model.onboardingStep
        withAnimation(stepAnimation) {
            model.onboardingStep = phase.range.lowerBound
        }
    }

    private var stepTransition: AnyTransition {
        guard !reduceMotion else { return .opacity }
        let insertionX: CGFloat = transitionForward ? 34 : -34
        let removalX: CGFloat = transitionForward ? -28 : 28
        return .asymmetric(
            insertion: .offset(x: insertionX, y: 0)
                .combined(with: .opacity)
                .combined(with: .scale(scale: 0.985, anchor: .center)),
            removal: .offset(x: removalX, y: 0)
                .combined(with: .opacity)
                .combined(with: .scale(scale: 0.992, anchor: .center))
        )
    }

    private var stepAnimation: Animation {
        reduceMotion
            ? .easeInOut(duration: 0.16)
            : .spring(response: 0.42, dampingFraction: 0.86, blendDuration: 0.06)
    }

    private var nextTitle: String {
        switch model.onboardingStep {
        case 0: return model.text(.continueAction)
        case 15: return model.text(.startSetup)
        default: return model.text(.next)
        }
    }

    private var nextRequirement: String? {
        guard nextDisabled else { return nil }
        switch model.onboardingStep {
        case 1:
            return model.text(.requirementPreferredName)
        case 2:
            if model.onboardingLockPassword.trimmingCharacters(in: .whitespacesAndNewlines).count < 6 {
                return model.text(.lockPasswordRequirement)
            }
            return model.text(.lockPasswordMismatch)
        case 7, 8, 9, 10, 11:
            return model.text(.requirementSurveyChoice)
        case 12:
            return model.text(.requirementElephantIdentity)
        case 13:
            return model.text(.providerTitle)
        case 14:
            return model.text(.selectModel)
        case 15:
            return model.text(.requirementProviderDetails)
        default:
            return nil
        }
    }

    private var currentPhase: OnboardingPhase {
        phases.first { $0.range.contains(min(model.onboardingStep, readyStep)) } ?? phases[0]
    }

    private var phases: [OnboardingPhase] {
        [
            OnboardingPhase(id: "language", title: .phaseLanguage, symbol: "globe", range: 0...0),
            OnboardingPhase(id: "profile", title: .phaseProfile, symbol: "person.crop.square", range: 1...6),
            OnboardingPhase(id: "patterns", title: .phasePattern, symbol: "checklist", range: 7...11),
            OnboardingPhase(id: "elephant", title: .phaseElephant, symbol: "sparkles", range: 12...12),
            OnboardingPhase(id: "model", title: .phaseModel, symbol: "cpu", range: 13...15),
            OnboardingPhase(id: "ready", title: .phaseReady, symbol: "checkmark.seal", range: 16...17)
        ]
    }

    private var nextDisabled: Bool {
        switch model.onboardingStep {
        case 1:
            return model.onboardingPreferredName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case 2:
            return !model.onboardingLockPasswordIsValid
        case 7:
            return model.onboardingInnerLandscape.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case 8:
            return model.onboardingValueAnchor.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case 9:
            return model.onboardingPressurePattern.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case 10:
            return model.onboardingRecoveryStyle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case 11:
            return model.onboardingDecisionCompass.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case 12:
            return model.onboardingName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || model.onboardingPurpose.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case 13:
            return model.onboardingProviderID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case 14:
            return model.onboardingModelID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case 15:
            return !providerReady
        default:
            return false
        }
    }

    private var providerReady: Bool {
        let provider = model.onboardingProviderID.trimmingCharacters(in: .whitespacesAndNewlines)
        let modelID = model.onboardingModelID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !provider.isEmpty, !modelID.isEmpty else { return false }
        if provider == "openai-compatible" {
            if model.snapshot.providerID == provider, !model.snapshot.providerModelID.isEmpty {
                return true
            }
            return !model.onboardingBaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        return true
    }
}

struct OnboardingBackdrop: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        AppBackground()
            .overlay(MosaicMemoryField(paused: reduceMotion).opacity(0.72).blendMode(.plusLighter))
            .overlay(MemoryCurrentField(paused: reduceMotion).opacity(0.68))
            .overlay(
                LinearGradient(
                    colors: [
                        ElephantTheme.accent.opacity(0.20),
                        ElephantTheme.mint.opacity(0.18),
                        ElephantTheme.ember.opacity(0.14),
                        Color.clear
                    ],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
                .blendMode(.softLight)
            )
    }
}

struct OnboardingProgressDots: View {
    var count: Int
    var active: Int

    var body: some View {
        HStack(spacing: 7) {
            ForEach(0..<count, id: \.self) { index in
                Capsule()
                    .fill(index == active ? ElephantTheme.ink.opacity(0.64) : index < active ? ElephantTheme.accent.opacity(0.52) : ElephantTheme.line.opacity(0.34))
                    .frame(width: index == active ? 18 : 6, height: 6)
            }
        }
        .animation(.easeInOut(duration: 0.18), value: active)
    }
}

struct OnboardingPhase: Identifiable {
    var id: String
    var title: AppText
    var symbol: String
    var range: ClosedRange<Int>
}

struct OnboardingPhaseRail: View {
    var phases: [OnboardingPhase]
    var activeStep: Int
    var language: AppLanguage
    var canNavigate: Bool
    var onSelect: (OnboardingPhase) -> Void

    var body: some View {
        HStack(spacing: 8) {
            ForEach(phases) { phase in
                OnboardingPhaseRailItem(
                    phase: phase,
                    state: state(for: phase),
                    language: language,
                    isSelectable: canNavigate && phase.range.lowerBound <= activeStep
                ) {
                    onSelect(phase)
                }
            }
        }
        .padding(.horizontal, 6)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(AppText.phaseProgressLabel.text(language))
    }

    private func state(for phase: OnboardingPhase) -> OnboardingPhaseRailItem.State {
        if activeStep > phase.range.upperBound { return .complete }
        if phase.range.contains(activeStep) { return .active }
        return .upcoming
    }
}

struct OnboardingPhaseRailItem: View {
    enum State {
        case complete
        case active
        case upcoming
    }

    var phase: OnboardingPhase
    var state: State
    var language: AppLanguage
    var isSelectable: Bool
    var onSelect: () -> Void

    var body: some View {
        Button {
            guard isSelectable else { return }
            onSelect()
        } label: {
            content
        }
        .buttonStyle(PressablePlainButtonStyle())
        .disabled(!isSelectable)
        .help(accessibilityLabel)
        .accessibilityLabel(accessibilityLabel)
        .accessibilityHint(accessibilityHint)
        .accessibilityRemoveTraits(.isSelected)
    }

    private var content: some View {
        HStack(spacing: 6) {
            Image(systemName: iconName)
                .font(.caption.weight(.semibold))
                .foregroundStyle(iconColor)
                .frame(width: 14)
            Text(phase.title.text(language))
                .font(.caption2.weight(.semibold))
                .foregroundStyle(textColor)
                .lineLimit(1)
                .minimumScaleFactor(0.82)
        }
        .padding(.horizontal, 10)
        .frame(maxWidth: .infinity, minHeight: 30)
        .background(background, in: Capsule())
        .overlay(Capsule().stroke(borderColor, lineWidth: 1))
        .contentShape(Capsule())
    }

    private var accessibilityLabel: String {
        "\(phase.title.text(language)), \(stateText)"
    }

    private var accessibilityHint: String {
        isSelectable
            ? AppText.phaseJumpHint.text(language)
            : AppText.phaseLockedHint.text(language)
    }

    private var stateText: String {
        switch state {
        case .complete: return AppText.phaseStatusComplete.text(language)
        case .active: return AppText.phaseStatusCurrent.text(language)
        case .upcoming: return AppText.phaseStatusUpcoming.text(language)
        }
    }

    private var iconName: String {
        switch state {
        case .complete: return "checkmark"
        case .active, .upcoming: return phase.symbol
        }
    }

    private var iconColor: Color {
        switch state {
        case .complete: return ElephantTheme.green
        case .active: return ElephantTheme.accent
        case .upcoming: return ElephantTheme.faint
        }
    }

    private var textColor: Color {
        switch state {
        case .complete: return ElephantTheme.ink.opacity(0.72)
        case .active: return ElephantTheme.ink
        case .upcoming: return ElephantTheme.muted
        }
    }

    private var background: Color {
        switch state {
        case .complete: return ElephantTheme.green.opacity(0.10)
        case .active: return ElephantTheme.accent.opacity(0.13)
        case .upcoming: return Color(nsColor: .controlBackgroundColor).opacity(0.52)
        }
    }

    private var borderColor: Color {
        switch state {
        case .complete: return ElephantTheme.green.opacity(0.22)
        case .active: return ElephantTheme.accent.opacity(0.32)
        case .upcoming: return ElephantTheme.line.opacity(0.42)
        }
    }
}

struct OnboardingStepHeader: View {
    var title: String
    var subtitle: String
    var symbol: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: symbol)
                .font(.title3.weight(.semibold))
                .foregroundStyle(ElephantTheme.accent)
                .frame(width: 34, height: 34)
                .background(ElephantTheme.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(alignment: .leading, spacing: 5) {
                Text(title)
                    .font(.system(size: 21, weight: .semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Text(subtitle)
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
    }
}

struct OnboardingField: View {
    var title: String
    var placeholder: String
    @Binding var text: String
    var lines: ClosedRange<Int> = 1...1
    var secure = false
    var suggestions: [String] = []
    @FocusState private var focused: Bool
    @State private var hovering = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(focused ? ElephantTheme.accent : ElephantTheme.muted)
                Spacer(minLength: 0)
                if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.green)
                        .transition(.opacity.combined(with: .scale))
                }
            }
            Group {
                if secure {
                    SecureField(placeholder, text: $text)
                        .focused($focused)
                } else {
                    TextField(placeholder, text: $text, axis: lines.upperBound > 1 ? .vertical : .horizontal)
                        .lineLimit(lines)
                        .focused($focused)
                }
            }
            .textFieldStyle(.plain)
            .font(.callout)
            .foregroundStyle(ElephantTheme.ink)
            .padding(.horizontal, 12)
            .padding(.vertical, lines.upperBound > 1 ? 11 : 9)
            .frame(minHeight: lines.upperBound > 1 ? 78 : 38, alignment: .topLeading)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(fieldFill)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(fieldStroke, lineWidth: focused ? 1.4 : 1)
            )
            .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .onHover { hovering = $0 }
            .animation(.easeOut(duration: 0.16), value: focused)
            .animation(.easeOut(duration: 0.16), value: hovering)

            if !suggestions.isEmpty {
                OnboardingSuggestionChips(suggestions: suggestions, selection: $text)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var fieldFill: Color {
        if focused {
            return ElephantTheme.accent.opacity(0.09)
        }
        if hovering {
            return Color(nsColor: .controlBackgroundColor).opacity(0.92)
        }
        return Color(nsColor: .controlBackgroundColor).opacity(0.72)
    }

    private var fieldStroke: Color {
        if focused {
            return ElephantTheme.accent.opacity(0.72)
        }
        if hovering {
            return ElephantTheme.accent.opacity(0.32)
        }
        return ElephantTheme.line.opacity(0.76)
    }
}

struct OnboardingSuggestionChips: View {
    var suggestions: [String]
    @Binding var selection: String

    private let columns = [
        GridItem(.adaptive(minimum: 116), spacing: 8)
    ]

    var body: some View {
        LazyVGrid(columns: columns, alignment: .leading, spacing: 8) {
            ForEach(suggestions, id: \.self) { suggestion in
                Button {
                    selection = suggestion
                } label: {
                    HStack(spacing: 6) {
                        Text(suggestion)
                            .font(.caption.weight(.semibold))
                            .lineLimit(1)
                            .minimumScaleFactor(0.82)
                        Spacer(minLength: 0)
                        if selection == suggestion {
                            Image(systemName: "checkmark.circle.fill")
                                .font(.caption2.weight(.semibold))
                        }
                    }
                    .foregroundStyle(selection == suggestion ? ElephantTheme.accent : ElephantTheme.ink)
                    .padding(.horizontal, 10)
                    .frame(maxWidth: .infinity, minHeight: 28)
                    .background(
                        selection == suggestion
                            ? ElephantTheme.accent.opacity(0.14)
                            : Color(nsColor: .controlBackgroundColor).opacity(0.58),
                        in: Capsule()
                    )
                    .overlay(
                        Capsule()
                            .stroke(selection == suggestion ? ElephantTheme.accent.opacity(0.48) : ElephantTheme.line.opacity(0.58), lineWidth: 1)
                    )
                    .contentShape(Capsule())
                }
                .buttonStyle(PressablePlainButtonStyle())
                .help(suggestion)
                .accessibilityLabel(suggestion)
            }
        }
    }
}

struct OnboardingMenuField: View {
    var title: String
    var placeholder: String
    var options: [String]
    @Binding var selection: String
    @State private var hovering = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                Spacer(minLength: 0)
                if !selection.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.green)
                }
            }
            Menu {
                Button(placeholder) {
                    selection = ""
                }
                Divider()
                ForEach(options, id: \.self) { option in
                    Button(option) {
                        selection = option
                    }
                }
            } label: {
                HStack(spacing: 10) {
                    Text(selection.isEmpty ? placeholder : selection)
                        .font(.callout)
                        .foregroundStyle(selection.isEmpty ? ElephantTheme.faint : ElephantTheme.ink)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.muted)
                }
                .padding(.horizontal, 12)
                .frame(maxWidth: .infinity, minHeight: 38)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(
                            hovering
                                ? ElephantTheme.accent.opacity(0.08)
                                : Color(nsColor: .controlBackgroundColor).opacity(0.72)
                        )
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(hovering ? ElephantTheme.accent.opacity(0.46) : ElephantTheme.line.opacity(0.76), lineWidth: 1)
                )
                .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(PressablePlainButtonStyle())
            .onHover { hovering = $0 }
            .help(selection.isEmpty ? placeholder : "\(title): \(selection)")
            .accessibilityLabel("\(title), \(selection.isEmpty ? placeholder : selection)")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct OnboardingDateField: View {
    var title: String
    var placeholder: String
    @Binding var text: String
    var language: AppLanguage
    @State private var selectedDate = Self.defaultDate
    @State private var hovering = false

    private var hasValue: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                Text(hasValue ? text : placeholder)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(hasValue ? ElephantTheme.ink.opacity(0.68) : ElephantTheme.faint)
                    .lineLimit(1)
                Spacer(minLength: 0)
                if hasValue {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.green)
                }
            }

            HStack(spacing: 8) {
                DatePicker(
                    "",
                    selection: Binding(
                        get: { selectedDate },
                        set: { date in
                            selectedDate = Calendar(identifier: .gregorian).startOfDay(for: date)
                            text = Self.storageFormatter.string(from: selectedDate)
                        }
                    ),
                    in: Self.minimumDate...Date(),
                    displayedComponents: .date
                )
                .datePickerStyle(.compact)
                .labelsHidden()
                .environment(\.locale, Locale(identifier: language.localeIdentifier))
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityLabel(title)

                if hasValue {
                    Button {
                        text = ""
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.callout.weight(.semibold))
                    }
                    .buttonStyle(.borderless)
                    .foregroundStyle(ElephantTheme.faint)
                    .help(clearTitle)
                    .accessibilityLabel(clearTitle)
                }
            }
            .padding(.horizontal, 12)
            .frame(maxWidth: .infinity, minHeight: 38, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(hovering ? ElephantTheme.accent.opacity(0.08) : Color(nsColor: .controlBackgroundColor).opacity(0.72))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(hovering ? ElephantTheme.accent.opacity(0.46) : ElephantTheme.line.opacity(0.76), lineWidth: 1)
            )
            .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .onHover { hovering = $0 }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .onAppear {
            syncSelectedDate()
        }
        .onChange(of: text) { _ in
            syncSelectedDate()
        }
    }

    private var clearTitle: String {
        localizedYouText(language, en: "Clear birth date", zh: "清除生日", fr: "Effacer la date de naissance", de: "Geburtsdatum löschen")
    }

    private func syncSelectedDate() {
        guard let parsed = Self.parseDate(text) else { return }
        selectedDate = parsed
    }

    private static var defaultDate: Date {
        var components = DateComponents()
        components.calendar = Calendar(identifier: .gregorian)
        components.year = 1990
        components.month = 1
        components.day = 1
        return components.date ?? Date()
    }

    private static var minimumDate: Date {
        var components = DateComponents()
        components.calendar = Calendar(identifier: .gregorian)
        components.year = 1900
        components.month = 1
        components.day = 1
        return components.date ?? Date(timeIntervalSince1970: 0)
    }

    private static let storageFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy/MM/dd"
        return formatter
    }()

    private static let inputFormatters: [DateFormatter] = {
        ["yyyy/MM/dd", "yyyy-MM-dd", "yyyy.M.d", "yyyy/M/d"].map { pattern in
            let formatter = DateFormatter()
            formatter.calendar = Calendar(identifier: .gregorian)
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.dateFormat = pattern
            return formatter
        }
    }()

    private static func parseDate(_ value: String) -> Date? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        for formatter in inputFormatters {
            if let date = formatter.date(from: trimmed) {
                return Calendar(identifier: .gregorian).startOfDay(for: date)
            }
        }
        return nil
    }
}

struct OnboardingHobbyOption: Identifiable {
    var value: String
    var label: String
    var detail: String
    var id: String { value }
}

struct OnboardingMultiSelectMenuField: View {
    var title: String
    var placeholder: String
    var options: [OnboardingHobbyOption]
    @Binding var selection: String
    var language: AppLanguage
    @State private var hovering = false

    private var selectedValues: [String] {
        let parts = selection.components(separatedBy: CharacterSet(charactersIn: ",，、"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && $0 != "skip" && $0 != "暂时留空" }
        let knownValues = Set(options.map(\.value))
        let known = options.map(\.value).filter { parts.contains($0) }
        let unknown = parts.filter { !knownValues.contains($0) && !known.contains($0) }
        return known + unknown
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                Spacer(minLength: 0)
                if !selectedValues.isEmpty {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.green)
                }
            }

            Menu {
                Button(clearSelectionTitle) {
                    selection = ""
                }
                .disabled(selectedValues.isEmpty)
                Divider()
                ForEach(options) { option in
                    Button {
                        toggle(option)
                    } label: {
                        Label(option.label, systemImage: selectedValues.contains(option.value) ? "checkmark.circle.fill" : "circle")
                    }
                    .help(option.detail)
                }
            } label: {
                HStack(spacing: 10) {
                    Text(selectionSummary)
                        .font(.callout)
                        .foregroundStyle(selectedValues.isEmpty ? ElephantTheme.faint : ElephantTheme.ink)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    Text(selectedCountText)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(selectedValues.isEmpty ? ElephantTheme.faint : ElephantTheme.accent)
                        .lineLimit(1)
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.muted)
                }
                .padding(.horizontal, 12)
                .frame(maxWidth: .infinity, minHeight: 38)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(hovering ? ElephantTheme.accent.opacity(0.08) : Color(nsColor: .controlBackgroundColor).opacity(0.72))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(hovering ? ElephantTheme.accent.opacity(0.46) : ElephantTheme.line.opacity(0.76), lineWidth: 1)
                )
                .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(PressablePlainButtonStyle())
            .onHover { hovering = $0 }
            .help(selectedValues.isEmpty ? placeholder : selectedLabels.joined(separator: delimiter))
            .accessibilityLabel("\(title), \(selectionSummary)")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var delimiter: String {
        language == .zh ? "、" : ", "
    }

    private var selectedLabels: [String] {
        selectedValues.map { value in
            options.first(where: { $0.value == value })?.label ?? value
        }
    }

    private var selectionSummary: String {
        let labels = selectedLabels
        guard !labels.isEmpty else { return placeholder }
        if labels.count <= 3 {
            return labels.joined(separator: delimiter)
        }
        let visible = labels.prefix(2).joined(separator: delimiter)
        return "\(visible) +\(labels.count - 2)"
    }

    private var selectedCountText: String {
        selectedValues.isEmpty
            ? localizedYouText(language, en: "Optional", zh: "可选", fr: "Optionnel", de: "Optional")
            : localizedFormat(language, en: "%d selected", zh: "已选 %d 项", fr: "%d sélectionnés", de: "%d ausgewählt", selectedValues.count)
    }

    private var clearSelectionTitle: String {
        localizedYouText(language, en: "Leave blank", zh: "暂时留空", fr: "Laisser vide", de: "Leer lassen")
    }

    private func toggle(_ option: OnboardingHobbyOption) {
        var values = selectedValues
        if let index = values.firstIndex(of: option.value) {
            values.remove(at: index)
        } else {
            values.append(option.value)
        }
        selection = joinedSelection(values)
    }

    private func joinedSelection(_ values: [String]) -> String {
        let valueSet = Set(values)
        let known = options.map(\.value).filter { valueSet.contains($0) }
        let knownSet = Set(known)
        let unknown = values.filter { !knownSet.contains($0) }
        return (known + unknown).joined(separator: delimiter)
    }
}

struct OnboardingChoiceButton: View {
    var title: String
    var subtitle: String? = nil
    var symbol: String
    var selected: Bool
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: symbol)
                    .font(.headline)
                    .foregroundStyle(selected ? .white : ElephantTheme.accent)
                    .frame(width: 26)
                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(selected ? .white : ElephantTheme.ink)
                        .lineLimit(2)
                    if let subtitle {
                        Text(subtitle)
                            .font(.caption)
                            .foregroundStyle(selected ? .white.opacity(0.78) : ElephantTheme.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
                if selected {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.white)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, minHeight: 82, alignment: .topLeading)
            .background(selected ? ElephantTheme.accent : Color(nsColor: .controlBackgroundColor).opacity(0.74), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(selected ? ElephantTheme.accent.opacity(0.34) : ElephantTheme.line.opacity(0.74), lineWidth: 1)
            )
            .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(PressablePlainButtonStyle())
    }
}

struct OnboardingLanguageOptionButton: View {
    var title: String
    var subtitle: String
    var symbol: String
    var selected: Bool
    var height: CGFloat = 52
    var action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: symbol)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(selected ? .white : ElephantTheme.accent)
                    .frame(width: 24)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(selected ? .white : ElephantTheme.ink)
                        .lineLimit(1)
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(selected ? .white.opacity(0.78) : ElephantTheme.muted)
                        .lineLimit(1)
                        .minimumScaleFactor(0.86)
                }
                Spacer(minLength: 0)
                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(selected ? .white : ElephantTheme.faint)
            }
            .padding(.horizontal, 14)
            .frame(maxWidth: .infinity, minHeight: height, maxHeight: height, alignment: .center)
            .background(background, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(selected ? ElephantTheme.accent.opacity(0.34) : ElephantTheme.line.opacity(hovering ? 0.82 : 0.64), lineWidth: 1)
            )
            .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(PressablePlainButtonStyle())
        .onHover { hovering = $0 }
    }

    private var background: Color {
        if selected { return ElephantTheme.accent }
        return hovering ? Color(nsColor: .controlBackgroundColor).opacity(0.90) : Color(nsColor: .controlBackgroundColor).opacity(0.74)
    }
}

struct OnboardingLanguageStep: View {
    @EnvironmentObject private var model: ElephantAppModel
    private let optionHeight: CGFloat = 52
    private let optionSpacing: CGFloat = 10
    private let visibleOptionCount = 4

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            OnboardingStepHeader(
                title: model.text(.languageTitle),
                subtitle: model.text(.languageSubtitle),
                symbol: "globe"
            )
            Spacer(minLength: 0)
            HStack(alignment: .top, spacing: 18) {
                OnboardingLanguageSignal(language: model.appLanguage)
                    .frame(width: 246, height: languageListHeight)

                ScrollView(.vertical, showsIndicators: AppLanguage.allCases.count > visibleOptionCount) {
                    LazyVStack(spacing: optionSpacing) {
                        ForEach(AppLanguage.allCases) { language in
                            OnboardingLanguageOptionButton(
                                title: language.nativeName,
                                subtitle: language.languageCardSubtitle,
                                symbol: language.symbol,
                                selected: model.appLanguage == language,
                                height: optionHeight
                            ) {
                                model.setAppLanguage(language)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity)
                .frame(height: languageListHeight)
            }
            Spacer(minLength: 0)
        }
    }

    private var languageListHeight: CGFloat {
        optionHeight * CGFloat(visibleOptionCount) + optionSpacing * CGFloat(visibleOptionCount - 1)
    }
}

struct OnboardingLanguageSignal: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var language: AppLanguage

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 60.0, paused: reduceMotion)) { timeline in
            ZStack {
                Canvas { context, size in
                    let seconds = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                    let center = CGPoint(x: size.width * 0.50, y: size.height * 0.50)
                    let radius = min(size.width, size.height) * 0.32
                    let palette = [
                        ElephantTheme.accent,
                        ElephantTheme.mint,
                        ElephantTheme.ember
                    ]
                    for index in 0..<3 {
                        let phase = CGFloat(seconds * (0.35 + Double(index) * 0.06))
                        let inset = CGFloat(index) * 18 + sin(phase) * 5
                        let rect = CGRect(
                            x: center.x - radius + inset / 2,
                            y: center.y - radius + inset / 2,
                            width: radius * 2 - inset,
                            height: radius * 2 - inset
                        )
                        context.stroke(
                            Path(ellipseIn: rect),
                            with: .color(palette[index].opacity(0.22)),
                            style: StrokeStyle(lineWidth: 2, lineCap: .round, dash: [26, 18], dashPhase: CGFloat(seconds * 22 + Double(index) * 17))
                        )
                    }
                    for index in 0..<7 {
                        let angle = seconds * 0.34 + Double(index) * .pi * 2 / 7
                        let point = CGPoint(
                            x: center.x + CGFloat(cos(angle)) * (radius + 17),
                            y: center.y + CGFloat(sin(angle)) * (radius + 17)
                        )
                        let dot = CGRect(x: point.x - 3.5, y: point.y - 3.5, width: 7, height: 7)
                        context.fill(Path(ellipseIn: dot), with: .color(palette[index % palette.count].opacity(0.78)))
                    }
                }
                VStack(spacing: 8) {
                    Text(primaryGreeting)
                        .font(.system(size: 42, weight: .semibold, design: .rounded))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                        .minimumScaleFactor(0.72)
                    Text(secondaryGreeting)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(1)
                        .minimumScaleFactor(0.78)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(
                LinearGradient(
                    colors: [
                        ElephantTheme.accent.opacity(language == .zh || language == .fr ? 0.08 : 0.13),
                        ElephantTheme.mint.opacity(language == .zh || language == .de ? 0.13 : 0.08),
                        Color(nsColor: .controlBackgroundColor).opacity(0.55)
                    ],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                ),
                in: RoundedRectangle(cornerRadius: 8, style: .continuous)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(ElephantTheme.accent.opacity(0.16), lineWidth: 1)
            )
        }
    }

    private var primaryGreeting: String {
        language.greeting
    }

    private var secondaryGreeting: String {
        AppText.languageSignalSubtitle.text(language)
    }
}

struct OnboardingIdentityStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    private let mbtiOptions = [
        "INTJ", "INTP", "ENTJ", "ENTP",
        "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ",
        "ISTP", "ISFP", "ESTP", "ESFP"
    ]
    private var genderOptions: [String] {
        [model.text(.female), model.text(.male), model.text(.nonBinary)]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            OnboardingStepHeader(
                title: model.text(.identityTitle),
                subtitle: model.text(.identitySubtitle),
                symbol: "person.crop.square"
            )
            HStack(alignment: .top, spacing: 22) {
                OnboardingLogoPicker()
                    .frame(width: 176)
                    .frame(minHeight: 222)
                VStack(spacing: 12) {
                    OnboardingField(title: model.text(.preferredName), placeholder: model.text(.preferredNamePlaceholder), text: $model.onboardingPreferredName)
                    HStack(spacing: 12) {
                        OnboardingMenuField(
                            title: model.text(.gender),
                            placeholder: model.text(.notSet),
                            options: genderOptions,
                            selection: $model.onboardingGender
                        )
                        OnboardingDateField(
                            title: model.text(.birthDate),
                            placeholder: model.text(.notSet),
                            text: $model.onboardingBirthDate,
                            language: model.appLanguage
                        )
                    }
                    OnboardingMenuField(
                        title: "MBTI",
                        placeholder: model.text(.notSet),
                        options: mbtiOptions,
                        selection: $model.onboardingMBTI
                    )
                }
                .frame(maxWidth: .infinity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
    }
}

struct OnboardingLockPasswordStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            OnboardingStepHeader(
                title: model.text(.lockPasswordTitle),
                subtitle: model.text(.lockPasswordSubtitle),
                symbol: "lock.shield"
            )

            HStack(alignment: .center, spacing: 24) {
                VStack(spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: [
                                        ElephantTheme.accent.opacity(0.12),
                                        ElephantTheme.mint.opacity(0.14),
                                        Color(nsColor: .textBackgroundColor).opacity(0.78)
                                    ],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                            .frame(width: 154, height: 154)
                            .overlay(Circle().stroke(ElephantTheme.line.opacity(0.70), lineWidth: 1))

                        UserAvatarImage(size: 92, name: model.userDisplayName, url: model.userAvatarURL)

                        Image(systemName: "lock.fill")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(.white)
                            .frame(width: 36, height: 36)
                            .background(ElephantTheme.ink.opacity(0.84), in: Circle())
                            .overlay(Circle().stroke(Color(nsColor: .windowBackgroundColor), lineWidth: 2))
                            .offset(x: 52, y: 52)
                    }

                    Text(model.userDisplayName)
                        .font(.headline.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                        .lineLimit(1)
                }
                .frame(width: 190)

                VStack(alignment: .leading, spacing: 14) {
                    OnboardingField(
                        title: model.text(.lockPassword),
                        placeholder: model.text(.lockPasswordRequirement),
                        text: $model.onboardingLockPassword,
                        secure: true
                    )
                    OnboardingField(
                        title: model.text(.lockPasswordConfirm),
                        placeholder: model.text(.lockPasswordConfirm),
                        text: $model.onboardingLockPasswordConfirmation,
                        secure: true
                    )

                    HStack(spacing: 8) {
                        Image(systemName: model.onboardingLockPasswordIsValid ? "checkmark.circle.fill" : "info.circle")
                            .foregroundStyle(model.onboardingLockPasswordIsValid ? ElephantTheme.green : ElephantTheme.muted)
                        Text(lockStatus)
                            .font(.callout.weight(.medium))
                            .foregroundStyle(model.onboardingLockPasswordIsValid ? ElephantTheme.green : ElephantTheme.muted)
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color(nsColor: .controlBackgroundColor).opacity(0.58), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line.opacity(0.70), lineWidth: 1))
                }
                .frame(maxWidth: .infinity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
    }

    private var lockStatus: String {
        if model.onboardingLockPasswordIsValid {
            return model.text(.lockPasswordSet)
        }
        if model.onboardingLockPassword.trimmingCharacters(in: .whitespacesAndNewlines).count < 6 {
            return model.text(.lockPasswordRequirement)
        }
        return model.text(.lockPasswordMismatch)
    }
}

struct OnboardingElephantStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            OnboardingStepHeader(
                title: model.text(.elephantVibeTitle),
                subtitle: model.text(.elephantVibeSubtitle),
                symbol: "sparkles"
            )
            OnboardingField(title: model.text(.elephantName), placeholder: "Elephant", text: $model.onboardingName)
            OnboardingField(
                title: model.text(.defaultVibe),
                placeholder: model.text(.defaultVibePlaceholder),
                text: $model.onboardingPurpose,
                lines: 3...5,
                suggestions: [model.text(.vibeSuggestionOne), model.text(.vibeSuggestionTwo), model.text(.vibeSuggestionThree)]
            )
            VStack(alignment: .leading, spacing: 8) {
                Text("ELEPHANT.md")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
                Text(model.onboardingElephantMarkdown)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(ElephantTheme.ink.opacity(0.78))
                    .lineLimit(6)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(12)
            .background(Color(nsColor: .controlBackgroundColor).opacity(0.58), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line.opacity(0.72), lineWidth: 1))
        }
    }
}

struct OnboardingWorkStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            OnboardingStepHeader(
                title: model.text(.workTitle),
                subtitle: model.text(.workSubtitle),
                symbol: "location.magnifyingglass"
            )
            OnboardingField(title: model.text(.currentWork), placeholder: model.text(.currentWorkPlaceholder), text: $model.onboardingOccupation)
            HStack(alignment: .top, spacing: 12) {
                OnboardingField(title: model.text(.school), placeholder: model.text(.optional), text: $model.onboardingSchool)
                OnboardingField(
                    title: model.text(.cityTimezone),
                    placeholder: model.text(.cityTimezonePlaceholder),
                    text: $model.onboardingCity,
                    suggestions: ["Asia/Shanghai", "America/Los_Angeles", "Europe/London"]
                )
            }
        }
    }
}

struct OnboardingInterestsStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            OnboardingStepHeader(
                title: model.text(.interestsTitle),
                subtitle: model.text(.interestsSubtitle),
                symbol: "sparkles"
            )
            OnboardingMultiSelectMenuField(
                title: model.text(.hobbies),
                placeholder: model.text(.hobbiesPlaceholder),
                options: onboardingHobbyOptions(for: model.appLanguage),
                selection: $model.onboardingHobbies,
                language: model.appLanguage
            )
            OnboardingField(title: model.text(.longTermDirection), placeholder: model.text(.longTermDirectionPlaceholder), text: $model.onboardingDream, lines: 3...4)
        }
    }
}

private func onboardingHobbyOptions(for language: AppLanguage) -> [OnboardingHobbyOption] {
    if language == .zh {
        return [
            OnboardingHobbyOption(value: "阅读", label: "阅读", detail: "书、文章、研究，或长期好奇的问题"),
            OnboardingHobbyOption(value: "音乐", label: "音乐", detail: "听歌、演奏、收藏、演出"),
            OnboardingHobbyOption(value: "影视/动画", label: "影视/动画", detail: "电影、剧集、动画、纪录片"),
            OnboardingHobbyOption(value: "游戏", label: "游戏", detail: "电子游戏、桌游、解谜、好玩的系统"),
            OnboardingHobbyOption(value: "运动/身体活动", label: "运动/身体活动", detail: "健身、跑步、攀岩、跳舞、散步"),
            OnboardingHobbyOption(value: "美食/做饭", label: "美食/做饭", detail: "吃饭、做饭、烘焙、咖啡、探店"),
            OnboardingHobbyOption(value: "旅行/城市漫步", label: "旅行/城市漫步", detail: "探索地方、路线、街区和旅程"),
            OnboardingHobbyOption(value: "艺术/设计", label: "艺术/设计", detail: "绘画、摄影、审美、把东西做漂亮"),
            OnboardingHobbyOption(value: "写作", label: "写作", detail: "日记、文章、小说、笔记、脚本"),
            OnboardingHobbyOption(value: "技术/创造", label: "技术/创造", detail: "写代码、小工具、设备、搭系统")
        ]
    }
    return [
        OnboardingHobbyOption(value: "reading", label: "Reading", detail: "Books, essays, research, or long-form curiosity"),
        OnboardingHobbyOption(value: "music", label: "Music", detail: "Listening, playing, collecting, or live shows"),
        OnboardingHobbyOption(value: "films and shows", label: "Films / shows", detail: "Movies, series, anime, documentaries"),
        OnboardingHobbyOption(value: "games", label: "Games", detail: "Video games, board games, puzzles, or playful systems"),
        OnboardingHobbyOption(value: "sports and movement", label: "Sports / movement", detail: "Gym, running, climbing, dancing, walking"),
        OnboardingHobbyOption(value: "food and cooking", label: "Food / cooking", detail: "Eating, cooking, baking, coffee, restaurants"),
        OnboardingHobbyOption(value: "travel and city walks", label: "Travel / city walks", detail: "Exploring places, routes, neighborhoods, trips"),
        OnboardingHobbyOption(value: "art and design", label: "Art / design", detail: "Drawing, photography, visual taste, making things beautiful"),
        OnboardingHobbyOption(value: "writing", label: "Writing", detail: "Journaling, essays, fiction, notes, scripts"),
        OnboardingHobbyOption(value: "technology and making", label: "Technology / making", detail: "Coding, gadgets, tools, building small systems")
    ]
}

struct OnboardingLinksStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            OnboardingStepHeader(
                title: model.text(.linksTitle),
                subtitle: model.text(.linksSubtitle),
                symbol: "link.circle"
            )
            VStack(spacing: 10) {
                OnboardingLinkField(
                    title: "Blog",
                    subtitle: model.text(.blogLinkHint),
                    symbol: "globe",
                    placeholder: "https://",
                    text: $model.onboardingBlogURL
                )
                OnboardingLinkField(
                    title: "LinkedIn",
                    subtitle: model.text(.linkedInLinkHint),
                    symbol: "person.text.rectangle",
                    placeholder: "https://linkedin.com/in/...",
                    text: $model.onboardingLinkedInURL
                )
                OnboardingLinkField(
                    title: "Twitter / X",
                    subtitle: model.text(.twitterLinkHint),
                    symbol: "quote.bubble",
                    placeholder: "https://x.com/...",
                    text: $model.onboardingTwitterURL
                )
            }
        }
    }
}

struct OnboardingLinkField: View {
    var title: String
    var subtitle: String
    var symbol: String
    var placeholder: String
    @Binding var text: String
    @FocusState private var focused: Bool
    @State private var hovering = false

    private var hasValue: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(hasValue ? ElephantTheme.accent.opacity(0.14) : ElephantTheme.faint.opacity(0.10))
                Image(systemName: symbol)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(hasValue ? ElephantTheme.accent : ElephantTheme.muted)
            }
            .frame(width: 42, height: 42)

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 8) {
                    Text(title)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                }
                TextField(placeholder, text: $text)
                    .textFieldStyle(.plain)
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.ink)
                    .focused($focused)
            }

            Image(systemName: hasValue ? "checkmark.circle.fill" : "circle")
                .font(.callout.weight(.semibold))
                .foregroundStyle(hasValue ? ElephantTheme.green : ElephantTheme.faint.opacity(0.58))
        }
        .padding(12)
        .frame(maxWidth: .infinity, minHeight: 70, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(focused || hovering ? ElephantTheme.accent.opacity(0.07) : Color(nsColor: .controlBackgroundColor).opacity(0.66))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(focused ? ElephantTheme.accent.opacity(0.70) : hovering ? ElephantTheme.accent.opacity(0.30) : ElephantTheme.line.opacity(0.72), lineWidth: focused ? 1.4 : 1)
        )
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .onHover { hovering = $0 }
        .onTapGesture { focused = true }
        .help(hasValue ? "\(title): \(text)" : subtitle)
        .accessibilityLabel("\(title), \(subtitle)")
        .animation(.easeOut(duration: 0.16), value: focused)
        .animation(.easeOut(duration: 0.16), value: hovering)
        .animation(.easeOut(duration: 0.16), value: hasValue)
    }
}

struct OnboardingHealthNotesStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            OnboardingStepHeader(
                title: model.text(.careTitle),
                subtitle: model.text(.careSubtitle),
                symbol: "heart.text.square"
            )
            HStack(alignment: .top, spacing: 12) {
                OnboardingCareField(
                    title: model.text(.boundaries),
                    placeholder: model.text(.boundariesPlaceholder),
                    symbol: "hand.raised",
                    tint: ElephantTheme.orange,
                    text: $model.onboardingSafetyBoundaries,
                    lines: 2...3,
                    minHeight: 136
                )
                OnboardingCareField(
                    title: model.text(.healthSafetyNote),
                    placeholder: model.text(.healthSafetyPlaceholder),
                    symbol: "cross.case",
                    tint: ElephantTheme.accent,
                    text: $model.onboardingPrivateSafetyNote,
                    lines: 2...3,
                    minHeight: 136
                )
            }
            HStack(alignment: .top, spacing: 12) {
                OnboardingCareField(
                    title: model.text(.foodAllergies),
                    placeholder: model.text(.leaveEmptyIfNone),
                    symbol: "fork.knife",
                    tint: ElephantTheme.green,
                    text: $model.onboardingFoodAllergies,
                    minHeight: 108
                )
                OnboardingCareField(
                    title: model.text(.medicationAllergies),
                    placeholder: model.text(.leaveEmptyIfNone),
                    symbol: "pills",
                    tint: ElephantTheme.green,
                    text: $model.onboardingMedicationAllergies,
                    minHeight: 108
                )
            }
        }
    }
}

struct OnboardingCareField: View {
    var title: String
    var placeholder: String
    var symbol: String
    var tint: Color
    @Binding var text: String
    var lines: ClosedRange<Int> = 1...2
    var minHeight: CGFloat = 118
    @FocusState private var focused: Bool
    @State private var hovering = false

    private var hasValue: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(tint.opacity(hasValue ? 0.16 : 0.10))
                    Image(systemName: symbol)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(tint)
                        .accessibilityHidden(true)
                }
                .frame(width: 34, height: 34)

                Text(title)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                    .lineLimit(1)

                Spacer(minLength: 0)

                Image(systemName: hasValue ? "checkmark.circle.fill" : "circle")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(hasValue ? ElephantTheme.green : ElephantTheme.faint.opacity(0.58))
                    .accessibilityHidden(true)
            }

            TextField(placeholder, text: $text, axis: lines.upperBound > 1 ? .vertical : .horizontal)
                .textFieldStyle(.plain)
                .font(.callout)
                .foregroundStyle(ElephantTheme.ink)
                .lineLimit(lines)
                .focused($focused)
                .accessibilityLabel(title)
        }
        .padding(12)
        .frame(maxWidth: .infinity, minHeight: minHeight, alignment: .topLeading)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(focused || hovering ? tint.opacity(0.07) : Color(nsColor: .controlBackgroundColor).opacity(0.66))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(focused ? tint.opacity(0.66) : hovering ? tint.opacity(0.30) : ElephantTheme.line.opacity(0.72), lineWidth: focused ? 1.4 : 1)
        )
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .onTapGesture { focused = true }
        .onHover { hovering = $0 }
        .help(hasValue ? "\(title): \(text)" : placeholder)
        .animation(.easeOut(duration: 0.16), value: focused)
        .animation(.easeOut(duration: 0.16), value: hovering)
        .animation(.easeOut(duration: 0.16), value: hasValue)
    }
}

enum OnboardingSurveyKind {
    case innerLandscape
    case valueAnchor
    case pressurePattern
    case recoveryStyle
    case decisionCompass
}

struct OnboardingSurveySingleStep: View {
    @EnvironmentObject private var model: ElephantAppModel
    var kind: OnboardingSurveyKind

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            OnboardingStepHeader(
                title: model.text(.surveyTitle),
                subtitle: model.text(.surveySubtitle),
                symbol: "checklist"
            )
            SurveyQuestionBlock(
                title: title,
                prompt: prompt,
                options: options,
                selection: binding
            )
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var binding: Binding<String> {
        switch kind {
        case .innerLandscape: return $model.onboardingInnerLandscape
        case .valueAnchor: return $model.onboardingValueAnchor
        case .pressurePattern: return $model.onboardingPressurePattern
        case .recoveryStyle: return $model.onboardingRecoveryStyle
        case .decisionCompass: return $model.onboardingDecisionCompass
        }
    }

    private var title: String {
        switch kind {
        case .innerLandscape: return model.text(.innerLandscapeTitle)
        case .valueAnchor: return model.text(.valueAnchorTitle)
        case .pressurePattern: return model.text(.pressurePatternTitle)
        case .recoveryStyle: return model.text(.recoveryStyleTitle)
        case .decisionCompass: return model.text(.decisionCompassTitle)
        }
    }

    private var prompt: String {
        switch kind {
        case .innerLandscape: return model.text(.innerLandscapePrompt)
        case .valueAnchor: return model.text(.valueAnchorPrompt)
        case .pressurePattern: return model.text(.pressurePatternPrompt)
        case .recoveryStyle: return model.text(.recoveryStylePrompt)
        case .decisionCompass: return model.text(.decisionCompassPrompt)
        }
    }

    private var options: [String] {
        model.appLanguage.surveyOptions[kind] ?? AppLanguage.en.surveyOptions[kind] ?? []
    }
}

struct OnboardingLogoPicker: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var hovering = false

    var body: some View {
        Button {
            model.pickUserAvatar()
        } label: {
            VStack(spacing: 12) {
                UserAvatarOrbitView(size: 96, editable: true)
                    .padding(.top, 4)
                VStack(spacing: 4) {
                    Text(model.text(.personalLogo))
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                    Label(model.userAvatarURL == nil ? model.text(.chooseImage) : model.text(.changeImage), systemImage: "photo.on.rectangle.angled")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.accent)
                        .labelStyle(.titleAndIcon)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, minHeight: 222)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(hovering ? ElephantTheme.accent.opacity(0.08) : Color(nsColor: .controlBackgroundColor).opacity(0.46))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(hovering ? ElephantTheme.accent.opacity(0.46) : ElephantTheme.line.opacity(0.72), lineWidth: 1)
            )
            .shadow(color: ElephantTheme.accent.opacity(hovering ? 0.10 : 0), radius: 12, y: 6)
            .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(PressablePlainButtonStyle())
        .onHover { hovering = $0 }
        .help(model.text(.personalLogo))
        .accessibilityLabel(model.text(.personalLogo))
    }
}

struct SurveyQuestionBlock: View {
    var title: String
    var prompt: String
    var options: [String]
    @Binding var selection: String

    var body: some View {
        GeometryReader { proxy in
            let headerHeight: CGFloat = 58
            let verticalSpacing: CGFloat = 12
            let gridSpacing: CGFloat = 12
            let rowCount = CGFloat(max(1, (options.count + 1) / 2))
            let availableGridHeight = max(210, proxy.size.height - headerHeight - verticalSpacing)
            let cardHeight = max(96, (availableGridHeight - gridSpacing * (rowCount - 1)) / rowCount)
            VStack(alignment: .leading, spacing: verticalSpacing) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.ink)
                    Text(prompt)
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(height: headerHeight, alignment: .topLeading)

                LazyVGrid(columns: [GridItem(.flexible(), spacing: gridSpacing), GridItem(.flexible(), spacing: gridSpacing)], spacing: gridSpacing) {
                    ForEach(options, id: \.self) { option in
                        Button {
                            selection = option
                        } label: {
                            SurveyOptionCard(
                                title: option,
                                selected: selection == option,
                                height: cardHeight
                            )
                        }
                        .buttonStyle(PressablePlainButtonStyle())
                        .help(option)
                        .accessibilityLabel(option)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct SurveyOptionCard: View {
    var title: String
    var selected: Bool
    var height: CGFloat
    @State private var hovering = false

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                .font(.title3.weight(.semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(selected ? .white : hovering ? ElephantTheme.accent : ElephantTheme.faint)
                .frame(width: 26, height: 26)

            Text(title)
                .font(.callout.weight(.semibold))
                .foregroundStyle(selected ? .white : ElephantTheme.ink)
                .lineLimit(2)
                .minimumScaleFactor(0.76)
                .multilineTextAlignment(.leading)

            Spacer(minLength: 0)
        }
        .padding(.horizontal, 18)
        .frame(maxWidth: .infinity, minHeight: height, maxHeight: height, alignment: .center)
        .background(cardBackground)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(borderColor, lineWidth: selected ? 1.5 : 1)
        )
        .shadow(color: shadowColor, radius: selected ? 14 : hovering ? 10 : 0, y: selected ? 7 : 4)
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .onHover { hovering = $0 }
        .animation(.easeOut(duration: 0.16), value: hovering)
        .animation(.easeOut(duration: 0.16), value: selected)
    }

    @ViewBuilder
    private var cardBackground: some View {
        RoundedRectangle(cornerRadius: 8, style: .continuous)
            .fill(Color(nsColor: .controlBackgroundColor).opacity(hovering ? 0.88 : 0.72))
        if selected {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            ElephantTheme.accent,
                            ElephantTheme.green.opacity(0.86)
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
        }
    }

    private var borderColor: Color {
        if selected { return Color.white.opacity(0.42) }
        if hovering { return ElephantTheme.accent.opacity(0.46) }
        return ElephantTheme.line.opacity(0.72)
    }

    private var shadowColor: Color {
        if selected { return ElephantTheme.accent.opacity(0.18) }
        if hovering { return ElephantTheme.accent.opacity(0.10) }
        return .clear
    }
}

struct OnboardingProviderModelStep: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var loaded = false
    @State private var providerSearch = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            OnboardingStepHeader(
                title: model.text(.providerTitle),
                subtitle: model.text(.providerSubtitle),
                symbol: "cpu"
            )
            if model.snapshot.providerOptions.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Provider")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ElephantTheme.muted)
                    Picker("", selection: $model.onboardingProviderID) {
                        Text("OpenAI Compatible").tag("openai-compatible")
                        Text("OpenAI").tag("openai")
                        Text("Anthropic").tag("anthropic")
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(maxWidth: 320, alignment: .leading)
                }
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    SectionLabel(title: model.text(.providerFactory), subtitle: "\(filteredProviders.count)/\(model.snapshot.providerOptions.count) \(model.text(.providerFactorySubtitle))")
                    ProviderSearchField(
                        text: $providerSearch,
                        placeholder: model.text(.providerSearchPlaceholder)
                    )
                    ProviderFactoryList(
                        options: filteredProviders,
                        selectedID: model.onboardingProviderID,
                        activeID: model.snapshot.providerID
                    ) { option in
                        selectProvider(option)
                    }
                    .frame(height: 190)
                }
            }
        }
        .onAppear {
            guard !loaded else { return }
            loadFromSnapshot()
            loaded = true
        }
        .onChange(of: model.onboardingProviderID) { _ in
            applyProviderDefaults(onlyWhenEmpty: false)
        }
    }

    private var selectedOption: ProviderOption? {
        model.snapshot.providerOptions.first(where: { $0.id == model.onboardingProviderID })
    }

    private var filteredProviders: [ProviderOption] {
        let needle = providerSearch.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return model.snapshot.providerOptions
            .filter { option in
                guard !needle.isEmpty else { return true }
                return providerSearchText(option).contains(needle)
            }
            .sorted { left, right in
                let leftRank = providerSortRank(left)
                let rightRank = providerSortRank(right)
                if leftRank != rightRank {
                    return leftRank < rightRank
                }
                return left.displayName.localizedCaseInsensitiveCompare(right.displayName) == .orderedAscending
            }
    }

    private func providerSearchText(_ option: ProviderOption) -> String {
        [
            option.displayName,
            option.id,
            option.defaultModel,
            option.defaultBaseURL,
            option.status,
            option.source,
            option.authKind,
            option.summary,
            option.models.map(\.id).joined(separator: " ")
        ]
        .joined(separator: " ")
        .lowercased()
    }

    private func providerSortRank(_ option: ProviderOption) -> Int {
        if option.id == model.snapshot.providerID || option.active { return 0 }
        if option.connected { return 1 }
        if option.storedKeyCount > 0 { return 2 }
        if option.id == model.onboardingProviderID { return 3 }
        return 4
    }

    private func loadFromSnapshot() {
        model.onboardingProviderID = model.snapshot.providerID.isEmpty
            ? (model.snapshot.providerOptions.first?.id ?? model.onboardingProviderID)
            : model.snapshot.providerID
        model.onboardingModelID = model.snapshot.providerModelID
        model.onboardingBaseURL = model.snapshot.providerBaseURL
        applyProviderDefaults(onlyWhenEmpty: true)
    }

    private func applyProviderDefaults(onlyWhenEmpty: Bool) {
        guard let option = selectedOption else { return }
        if !onlyWhenEmpty || model.onboardingModelID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            model.onboardingModelID = option.defaultModel.isEmpty ? (option.models.first?.id ?? model.onboardingModelID) : option.defaultModel
        }
        if !onlyWhenEmpty || model.onboardingBaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            model.onboardingBaseURL = option.defaultBaseURL
        }
    }

    private func selectProvider(_ option: ProviderOption) {
        model.onboardingProviderID = option.id
        applyProviderDefaults(onlyWhenEmpty: false)
    }
}

struct OnboardingModelSelectionStep: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var discoveredModels: [String: [ProviderModelOption]] = [:]
    @State private var loadingModels = false
    @State private var loaded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            OnboardingStepHeader(
                title: model.text(.modelSection),
                subtitle: selectedOption?.active == true ? model.text(.activeModelSubtitle) : model.text(.modelPickerSubtitle),
                symbol: "square.stack.3d.up"
            )

            if let option = selectedOption {
                ProviderOnboardingSummary(option: option, modelID: model.onboardingModelID)
            }

            HStack {
                SectionLabel(title: model.text(.modelList), subtitle: model.text(.modelPickerSubtitle))
                Spacer(minLength: 0)
                Button {
                    Task { await loadLiveModels(force: true) }
                } label: {
                    Label(loadingModels ? model.text(.fetching) : model.text(.fetch), systemImage: "arrow.clockwise")
                }
                .disabled(model.onboardingProviderID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || loadingModels)
                .controlSize(.small)
            }

            if availableModels.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: loadingModels ? "arrow.triangle.2.circlepath" : "sparkle.magnifyingglass")
                        .font(.system(size: 30, weight: .semibold))
                        .foregroundStyle(ElephantTheme.accent)
                    Text(loadingModels ? model.text(.fetching) : model.text(.selectModel))
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(ElephantTheme.muted)
                }
                .frame(maxWidth: .infinity, minHeight: 96)
                .background(Color(nsColor: .controlBackgroundColor).opacity(0.48), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line.opacity(0.70), lineWidth: 1))
            } else {
                OnboardingModelChoiceList(
                    options: availableModels,
                    selection: $model.onboardingModelID
                )
                .frame(height: 96)
            }

            HStack(alignment: .top, spacing: 12) {
                OnboardingMenuField(
                    title: model.text(.modelList),
                    placeholder: loadingModels ? model.text(.fetching) : model.text(.selectModel),
                    options: availableModels.map(\.id),
                    selection: $model.onboardingModelID
                )
                OnboardingField(title: model.text(.customModelID), placeholder: "gpt-5.4 / claude-sonnet-4-5", text: $model.onboardingModelID)
            }
        }
        .onAppear {
            guard !loaded else { return }
            loaded = true
            applyProviderDefaults(onlyWhenEmpty: true)
            Task { await loadLiveModelsIfNeeded() }
        }
        .onChange(of: model.onboardingProviderID) { _ in
            applyProviderDefaults(onlyWhenEmpty: false)
            Task { await loadLiveModelsIfNeeded() }
        }
    }

    private func loadLiveModels(force: Bool = false) async {
        let providerID = model.onboardingProviderID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !providerID.isEmpty else { return }
        loadingModels = true
        let rows = await model.discoverProviderModels(providerID: providerID, baseURL: model.onboardingBaseURL, apiKey: model.onboardingAPIKey)
        if !rows.isEmpty {
            discoveredModels[providerID] = rows
            if model.onboardingModelID.isEmpty || !rows.contains(where: { $0.id == model.onboardingModelID }) {
                model.onboardingModelID = rows.first?.id ?? model.onboardingModelID
            }
        }
        loadingModels = false
    }

    private func loadLiveModelsIfNeeded() async {
        let providerID = model.onboardingProviderID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !providerID.isEmpty,
              discoveredModels[providerID] == nil else { return }
        await loadLiveModels(force: false)
    }

    private var selectedOption: ProviderOption? {
        model.snapshot.providerOptions.first(where: { $0.id == model.onboardingProviderID })
    }

    private var availableModels: [ProviderModelOption] {
        discoveredModels[model.onboardingProviderID] ?? selectedOption?.models ?? []
    }

    private func applyProviderDefaults(onlyWhenEmpty: Bool) {
        guard let option = selectedOption else { return }
        if !onlyWhenEmpty || model.onboardingModelID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            model.onboardingModelID = option.defaultModel.isEmpty ? (option.models.first?.id ?? model.onboardingModelID) : option.defaultModel
        }
        if !onlyWhenEmpty || model.onboardingBaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            model.onboardingBaseURL = option.defaultBaseURL
        }
    }
}

struct ProviderOnboardingSummary: View {
    var option: ProviderOption
    var modelID: String

    var body: some View {
        HStack(spacing: 12) {
            ProviderLogoMark(option: option, size: 38)
            VStack(alignment: .leading, spacing: 3) {
                Text(option.displayName)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Text(modelID.isEmpty ? option.id : "\(option.id) · \(modelID)")
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            Spacer(minLength: 0)
            ProviderStatePill(option: option)
        }
        .padding(12)
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.58), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line.opacity(0.72), lineWidth: 1))
    }
}

struct OnboardingModelChoiceList: View {
    var options: [ProviderModelOption]
    @Binding var selection: String

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 7) {
                ForEach(Array(options.prefix(24))) { option in
                    Button {
                        selection = option.id
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: selection == option.id ? "checkmark.circle.fill" : "circle")
                                .font(.callout.weight(.semibold))
                                .foregroundStyle(selection == option.id ? ElephantTheme.accent : ElephantTheme.faint)
                                .frame(width: 22)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(option.label.isEmpty ? option.id : option.label)
                                    .font(.callout.weight(.semibold))
                                    .foregroundStyle(ElephantTheme.ink)
                                    .lineLimit(1)
                                    .truncationMode(.middle)
                                Text("\(option.id) · \(option.source)")
                                    .font(.caption2.monospaced())
                                    .foregroundStyle(ElephantTheme.muted)
                                    .lineLimit(1)
                                    .truncationMode(.middle)
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.horizontal, 12)
                        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(selection == option.id ? ElephantTheme.accent.opacity(0.10) : Color(nsColor: .controlBackgroundColor).opacity(0.56))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .stroke(selection == option.id ? ElephantTheme.accent.opacity(0.42) : ElephantTheme.line.opacity(0.56), lineWidth: 1)
                        )
                        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    }
                    .buttonStyle(PressablePlainButtonStyle())
                    .help(option.id)
                }
            }
            .padding(4)
        }
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.32), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line.opacity(0.54), lineWidth: 1))
    }
}

struct OnboardingProviderSecretStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            OnboardingStepHeader(
                title: model.text(.endpointTitle),
                subtitle: model.text(.endpointSubtitle),
                symbol: "key"
            )
            if let option = selectedOption {
                HStack(spacing: 12) {
                    ProviderLogoMark(option: option, size: 38)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(option.displayName)
                            .font(.callout.weight(.semibold))
                            .foregroundStyle(ElephantTheme.ink)
                        Text(model.onboardingModelID.isEmpty ? option.id : "\(option.id) · \(model.onboardingModelID)")
                            .font(.caption)
                            .foregroundStyle(ElephantTheme.muted)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    Spacer(minLength: 0)
                    ProviderStatePill(option: option)
                }
                .padding(12)
                .background(Color(nsColor: .controlBackgroundColor).opacity(0.58), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(ElephantTheme.line.opacity(0.72), lineWidth: 1))
            }
            HStack(alignment: .top, spacing: 12) {
                OnboardingField(title: "Base URL", placeholder: "https://api.openai.com/v1", text: $model.onboardingBaseURL)
                OnboardingField(title: model.text(.contextWindowTokens), placeholder: model.text(.optional), text: $model.onboardingContextWindow)
            }
            OnboardingField(title: model.text(.apiKey), placeholder: model.text(.apiKeyPlaceholder), text: $model.onboardingAPIKey, secure: true)
            HStack(spacing: 10) {
                Image(systemName: providerReady ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                    .foregroundStyle(providerReady ? ElephantTheme.green : ElephantTheme.orange)
                Text(providerReady ? model.text(.providerReady) : model.text(.providerNeedsDetails))
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(12)
            .background(Color(nsColor: .controlBackgroundColor).opacity(0.58), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
    }

    private var providerReady: Bool {
        let provider = model.onboardingProviderID.trimmingCharacters(in: .whitespacesAndNewlines)
        let modelID = model.onboardingModelID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !provider.isEmpty, !modelID.isEmpty else { return false }
        if provider == "openai-compatible" {
            if model.snapshot.providerID == provider, !model.snapshot.providerModelID.isEmpty {
                return true
            }
            return !model.onboardingBaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        return true
    }

    private var selectedOption: ProviderOption? {
        model.snapshot.providerOptions.first(where: { $0.id == model.onboardingProviderID })
    }
}

struct OnboardingLearningStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 10)
            OnboardingLearningAnimation()
                .frame(width: 168, height: 168)
            VStack(spacing: 8) {
                Text(model.text(.learningTitle))
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Text(model.onboardingFinalizationStatus.isEmpty ? model.text(.learningPreparing) : model.onboardingFinalizationStatus)
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.muted)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 420)
            }
            if model.onboardingFinalizationFailed {
                VStack(spacing: 10) {
                    Text(model.lastError)
                        .font(.caption)
                        .foregroundStyle(ElephantTheme.orange)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 520)
                    Button {
                        Task { await model.startOnboardingFinalization() }
                    } label: {
                        Label(model.text(.tryAgain), systemImage: "arrow.clockwise")
                    }
                }
            } else {
                ProgressView()
                    .controlSize(.small)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, minHeight: 350)
        .task {
            await model.startOnboardingFinalization()
        }
    }
}

struct OnboardingLearningAnimation: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 60.0, paused: reduceMotion)) { timeline in
            Canvas { context, size in
                let seconds = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                let center = CGPoint(x: size.width / 2, y: size.height / 2)
                let radius = min(size.width, size.height) * 0.34
                let palette = [ElephantTheme.accent, ElephantTheme.green, ElephantTheme.ember]

                for index in 0..<3 {
                    let inset = CGFloat(index) * 18
                    let rect = CGRect(x: center.x - radius + inset / 2, y: center.y - radius + inset / 2, width: (radius * 2) - inset, height: (radius * 2) - inset)
                    context.stroke(
                        Path(ellipseIn: rect),
                        with: .color(palette[index].opacity(0.26)),
                        style: StrokeStyle(lineWidth: 2, lineCap: .round, dash: [22, 16], dashPhase: CGFloat(seconds * 18 + Double(index) * 12))
                    )
                }

                for index in 0..<6 {
                    let angle = seconds * 0.42 + Double(index) * .pi / 3
                    let point = CGPoint(
                        x: center.x + CGFloat(cos(angle)) * (radius + 8),
                        y: center.y + CGFloat(sin(angle)) * (radius + 8)
                    )
                    let rect = CGRect(x: point.x - 4, y: point.y - 4, width: 8, height: 8)
                    context.fill(Path(ellipseIn: rect), with: .color(palette[index % palette.count].opacity(0.78)))
                }

                let iconRect = CGRect(x: center.x - 30, y: center.y - 30, width: 60, height: 60)
                context.fill(Path(roundedRect: iconRect, cornerRadius: 8), with: .color(ElephantTheme.accent.opacity(0.10)))
                context.stroke(Path(roundedRect: iconRect, cornerRadius: 8), with: .color(ElephantTheme.accent.opacity(0.22)), lineWidth: 1)
            }
            .overlay {
                Image(systemName: "brain.head.profile")
                    .font(.system(size: 34, weight: .semibold))
                    .foregroundStyle(ElephantTheme.accent)
            }
        }
    }
}

struct OnboardingCelebrationStep: View {
    @EnvironmentObject private var model: ElephantAppModel

    var body: some View {
        VStack(spacing: 22) {
            Spacer(minLength: 12)
            OnboardingCelebrationAnimation()
                .frame(width: 190, height: 170)
            VStack(spacing: 8) {
                Text(model.text(.celebrationTitle))
                    .font(.system(size: 26, weight: .semibold))
                    .foregroundStyle(ElephantTheme.ink)
                Text(model.text(.celebrationSubtitle))
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.muted)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 520)
            }
            HStack(spacing: 12) {
                Pill(text: "\(model.snapshot.facts)", symbol: "checkmark.seal", tint: ElephantTheme.green)
                Pill(text: "\(model.snapshot.waitingQuestions)", symbol: "questionmark.bubble", tint: ElephantTheme.orange)
                if !model.onboardingInitReflectJobID.isEmpty {
                    Pill(text: "init", symbol: "brain.head.profile", tint: ElephantTheme.accent)
                }
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, minHeight: 350)
    }
}

struct OnboardingCelebrationAnimation: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 60.0, paused: reduceMotion)) { timeline in
            Canvas { context, size in
                let seconds = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                let palette = [ElephantTheme.accent, ElephantTheme.green, ElephantTheme.ember, ElephantTheme.mint]
                let center = CGPoint(x: size.width / 2, y: size.height / 2 + 8)

                for index in 0..<26 {
                    let angle = Double(index) / 26.0 * Double.pi * 2
                    let pulse = 0.72 + 0.18 * sin(seconds * 1.7 + Double(index))
                    let distance = CGFloat(42 + Double(index % 5) * 10) * CGFloat(pulse)
                    let point = CGPoint(x: center.x + CGFloat(cos(angle)) * distance, y: center.y + CGFloat(sin(angle)) * distance)
                    let rect = CGRect(x: point.x - 2.5, y: point.y - 2.5, width: 5, height: 5)
                    context.fill(Path(roundedRect: rect, cornerRadius: 1.5), with: .color(palette[index % palette.count].opacity(0.82)))
                }

                let circleRect = CGRect(x: center.x - 42, y: center.y - 42, width: 84, height: 84)
                context.fill(Path(ellipseIn: circleRect), with: .color(ElephantTheme.green.opacity(0.12)))
                context.stroke(Path(ellipseIn: circleRect), with: .color(ElephantTheme.green.opacity(0.32)), lineWidth: 2)
            }
            .overlay {
                Image(systemName: "checkmark.seal.fill")
                    .font(.system(size: 64, weight: .semibold))
                    .foregroundStyle(ElephantTheme.green)
                    .shadow(color: ElephantTheme.green.opacity(0.22), radius: 18, y: 8)
            }
        }
    }
}
