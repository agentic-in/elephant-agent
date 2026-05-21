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
            .help(AppSection.home.title(language: model.appLanguage))

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
                        TodayCommand(title: model.text(.reviewQuestions), symbol: "questionmark.bubble") {
                            model.selectedSection = .you
                        }
                        TodayCommand(title: model.text(.reflect), symbol: "brain.head.profile") {
                            Task { await model.runReflect(trigger: "home") }
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
                        PersonalGraphDetailStrip(selection: selectedNode)
                    } else {
                        EmptyLine(symbol: "heart.fill", text: model.text(.mapClickHint))
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
                    .help(model.text(.changeProfilePhoto))
                    .accessibilityLabel(model.text(.changeProfilePhoto))

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
                title: AppSection.wake.title(language: model.appLanguage),
                subtitle: model.activeEpisodeID.isEmpty ? model.text(.newChat) : model.text(.conversationOpen),
                actionTitle: model.isReflecting ? model.text(.reflecting) : model.text(.reflect),
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
    @StateObject private var speech = SpeechInputController()
    @FocusState private var focused: Bool

    var body: some View {
        NativePanel {
            VStack(spacing: 0) {
                HStack {
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
                            ScrollView {
                                LazyVStack(alignment: .leading, spacing: 4) {
                                    ForEach(visibleMessages) { message in
                                        MessageBubble(message: message)
                                            .equatable()
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
                title: AppSection.you.title(language: model.appLanguage),
                subtitle: model.text(.youPageSubtitle),
                actionTitle: model.text(.reflect),
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
                HomeKnowledgeOverview()
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
    @State private var selectedNode: PersonalGraphSelection?

    var body: some View {
        NativePanel {
            VStack(alignment: .leading, spacing: 14) {
                SectionLabel(
                    title: "Personal Model Map",
                    subtitle: "A live graph of memory nodes. Colors separate lenses; click any dot for detail."
                )
                PersonalModelDotMapCanvas(userName: model.userDisplayName, snapshot: model.snapshot, selectedNode: $selectedNode)
                    .frame(height: 700)
                if let selectedNode {
                    PersonalGraphDetailStrip(selection: selectedNode)
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

struct PersonalModelDotMapCanvas: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var userName: String
    var snapshot: DashboardSnapshot
    @Binding var selectedNode: PersonalGraphSelection?

    var body: some View {
        GeometryReader { proxy in
            TimelineView(.animation(minimumInterval: 1.0 / 60.0, paused: reduceMotion)) { timeline in
                let seconds = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                let layout = buildLayout(in: proxy.size, seconds: seconds)

                ZStack {
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(
                            RadialGradient(
                                colors: [ElephantTheme.green.opacity(0.07), ElephantTheme.accent.opacity(0.035), Color.clear],
                                center: .center,
                                startRadius: 28,
                                endRadius: max(proxy.size.width, proxy.size.height) * 0.76
                            )
                        )

                    Canvas { context, _ in
                        drawBackgroundField(in: &context, size: proxy.size, seconds: seconds)
                        for edge in layout.edges {
                            draw(edge: edge, in: &context, seconds: seconds)
                        }
                    }

                    ForEach(layout.nodes) { node in
                        Button {
                            selectedNode = node.selection
                        } label: {
                            PersonalDotMapNodeView(node: node, selected: selectedNode?.id == node.selection.id)
                        }
                        .buttonStyle(.plain)
                        .position(node.position)
                        .help(node.selection.title)
                        .accessibilityLabel(node.selection.accessibilityLabel)
                    }
                }
            }
        }
        .accessibilityLabel("Personal Model map")
    }

    private var centerValue: String {
        let trimmed = userName.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty || trimmed == "You" ? "Personal Model" : trimmed
    }

    private func buildLayout(in size: CGSize, seconds: TimeInterval) -> PersonalDotMapLayout {
        let centerBase = CGPoint(x: size.width * 0.50, y: size.height * 0.50)
        let center = drifting(centerBase, id: "center", radius: 3, seconds: seconds)
        let graphRadius = min(size.width, size.height) * 0.38
        var nodes: [PersonalDotMapNode] = [
            PersonalDotMapNode(
                id: "center",
                tint: Color(red: 0.94, green: 0.18, blue: 0.34),
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
                    detail: "All reviewable Personal Model facts currently visible to the app.",
                    facts: Array(snapshot.personalModelFacts.prefix(5)).map(\.text)
                )
            )
        ]
        var edges: [PersonalDotMapEdge] = []

        for spec in branchSpecs {
            let facts = facts(for: spec.id)
            let categories = categories(for: facts, lensID: spec.id)
            let lensCount = facts.isEmpty ? (snapshot.lensCoverage[spec.id] ?? 0) : facts.count
            let lensBase = point(from: centerBase, angle: spec.angle, radius: graphRadius * 0.52)
            let lensPoint = drifting(lensBase, id: "lens-\(spec.id)", radius: 5, seconds: seconds)
            let lensNode = PersonalDotMapNode(
                id: "lens-\(spec.id)",
                tint: spec.tint,
                kind: .lens,
                position: lensPoint,
                radius: min(15, 10 + CGFloat(lensCount) * 0.18),
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
            edges.append(PersonalDotMapEdge(from: center, to: lensPoint, tint: spec.tint, strength: 0.44))

            let visibleCategories = categories.isEmpty
                ? [PersonalDotMapCategory(id: "\(spec.id)-empty", title: "No facts yet", count: 0, facts: [])]
                : categories
            for (categoryIndex, category) in visibleCategories.enumerated() {
                let categoryAngle = fanAngle(base: spec.angle, index: categoryIndex, count: visibleCategories.count, spread: .pi * 0.82)
                let categoryRadius = graphRadius * (0.30 + ringOffset(index: categoryIndex) * 0.055)
                let categoryBase = bounded(point(from: lensBase, angle: categoryAngle, radius: categoryRadius), in: size, margin: 30)
                let categoryPoint = drifting(categoryBase, id: "category-\(spec.id)-\(category.id)", radius: 8, seconds: seconds)
                nodes.append(
                    PersonalDotMapNode(
                        id: "category-\(spec.id)-\(category.id)",
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
                edges.append(PersonalDotMapEdge(from: lensPoint, to: categoryPoint, tint: spec.tint, strength: 0.30))

                let visibleFacts = category.facts
                for (factIndex, fact) in visibleFacts.enumerated() {
                    let factAngle = factOrbitAngle(index: factIndex, count: visibleFacts.count, seed: fact.id)
                    let factBase = bounded(
                        point(from: categoryBase, angle: factAngle, radius: factOrbitRadius(index: factIndex, total: visibleFacts.count)),
                        in: size,
                        margin: 24
                    )
                    let factPoint = drifting(factBase, id: "fact-\(fact.id)", radius: 9, seconds: seconds)
                    nodes.append(
                        PersonalDotMapNode(
                            id: "fact-\(fact.id)",
                            tint: spec.tint,
                            kind: .fact,
                            position: factPoint,
                            radius: 4.8 + CGFloat(fact.id.count % 4) * 0.35,
                            selection: PersonalGraphSelection(
                                id: "fact-\(fact.id)",
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
                    edges.append(PersonalDotMapEdge(from: categoryPoint, to: factPoint, tint: spec.tint, strength: 0.22))
                }
            }
        }

        return PersonalDotMapLayout(nodes: nodes, edges: edges)
    }

    private var branchSpecs: [PersonalDotMapBranchSpec] {
        [
            PersonalDotMapBranchSpec(
                id: "identity",
                title: "Identity",
                description: "Stable preferences, identity anchors, names, profile links, and self-description.",
                tint: ElephantTheme.accent,
                angle: -.pi * 0.22
            ),
            PersonalDotMapBranchSpec(
                id: "world",
                title: "World",
                description: "People, projects, places, organizations, and external context.",
                tint: ElephantTheme.green,
                angle: -.pi * 0.78
            ),
            PersonalDotMapBranchSpec(
                id: "pulse",
                title: "Pulse",
                description: "Current state, open loops, live needs, blockers, and questions to revisit.",
                tint: ElephantTheme.orange,
                angle: .pi * 0.22
            ),
            PersonalDotMapBranchSpec(
                id: "journey",
                title: "Journey",
                description: "Long-term direction, milestones, narratives, and evolving goals.",
                tint: ElephantTheme.accent.opacity(0.82),
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
        for ring in [0.30, 0.44, 0.58, 0.72] {
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
        let ring = CGFloat(index / 12)
        let base = total > 8 ? CGFloat(28) : CGFloat(22)
        return base + ring * 18 + CGFloat(index % 3) * 2.5
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
    var from: CGPoint
    var to: CGPoint
    var tint: Color
    var strength: Double
}

private struct PersonalDotMapLayout {
    var nodes: [PersonalDotMapNode]
    var edges: [PersonalDotMapEdge]
}

private struct PersonalDotMapNodeView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var node: PersonalDotMapNode
    var selected: Bool
    @State private var hovering = false

    var body: some View {
        Group {
            if node.kind == .center {
                BeatingPersonalModelHeart(
                    tint: node.tint,
                    selected: selected,
                    hovering: hovering,
                    reduceMotion: reduceMotion,
                    size: max(40, node.radius * 2 + 12)
                )
            } else {
                ZStack {
                    Circle()
                        .fill(fill)
                        .frame(width: node.radius * 2, height: node.radius * 2)
                    Circle()
                        .stroke(node.tint.opacity(selected ? 0.78 : hovering ? 0.44 : 0.16), lineWidth: selected ? 2.2 : 1)
                        .frame(width: node.radius * 2 + ringInset, height: node.radius * 2 + ringInset)
                    if selected {
                        Circle()
                            .stroke(node.tint.opacity(0.18), lineWidth: 5)
                            .frame(width: node.radius * 2 + 18, height: node.radius * 2 + 18)
                    }
                }
                .scaleEffect(selected ? 1.20 : hovering ? 1.12 : 1.0)
            }
        }
        .frame(width: hitSize, height: hitSize)
        .contentShape(Circle())
        .shadow(color: node.tint.opacity(selected ? 0.18 : hovering ? 0.10 : 0.04), radius: selected ? 14 : 7, y: 4)
        .animation(.spring(response: 0.24, dampingFraction: 0.78), value: selected)
        .animation(.easeOut(duration: 0.12), value: hovering)
        .onHover { hovering = $0 }
    }

    private var hitSize: CGFloat {
        if node.kind == .center {
            return max(52, node.radius * 2 + 24)
        }
        return max(26, node.radius * 2 + 18)
    }

    private var ringInset: CGFloat {
        selected ? 8 : hovering ? 5 : 3
    }

    private var fill: Color {
        switch node.kind {
        case .center:
            return node.tint.opacity(0.82)
        case .lens:
            return node.tint.opacity(0.92)
        case .category:
            return node.tint.opacity(0.62)
        case .fact:
            return node.tint.opacity(0.82)
        }
    }
}

private struct BeatingPersonalModelHeart: View {
    var tint: Color
    var selected: Bool
    var hovering: Bool
    var reduceMotion: Bool
    var size: CGFloat

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 60.0, paused: reduceMotion)) { timeline in
            let seconds = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
            let beat = heartbeat(at: seconds)
            let scale = reduceMotion ? 1.0 : 1.0 + beat * 0.115 + (hovering ? 0.035 : 0)
            let aura = reduceMotion ? 0.18 : 0.12 + beat * 0.18

            ZStack {
                Circle()
                    .fill(
                        RadialGradient(
                            colors: [
                                tint.opacity(0.20 + aura * 0.20),
                                ElephantTheme.ember.opacity(0.10),
                                Color.clear
                            ],
                            center: .center,
                            startRadius: 2,
                            endRadius: size * 0.78
                        )
                    )
                    .frame(width: size * 1.32, height: size * 1.32)

                Circle()
                    .stroke(tint.opacity(0.16 + aura), lineWidth: selected ? 2.0 : 1.2)
                    .frame(width: size * (1.02 + beat * 0.16), height: size * (1.02 + beat * 0.16))

                Image(systemName: "heart.fill")
                    .font(.system(size: size * 0.58, weight: .bold))
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(tint)
                    .scaleEffect(scale)
                    .shadow(color: tint.opacity(0.28 + aura * 0.30), radius: 12 + beat * 8, y: 4)
            }
            .frame(width: size * 1.36, height: size * 1.36)
        }
    }

    private func heartbeat(at seconds: TimeInterval) -> CGFloat {
        let cycle = seconds.truncatingRemainder(dividingBy: 1.18)
        let first = pulse(cycle, center: 0.10, width: 0.050)
        let second = pulse(cycle, center: 0.28, width: 0.075) * 0.74
        return CGFloat(min(1.0, first + second))
    }

    private func pulse(_ value: TimeInterval, center: TimeInterval, width: TimeInterval) -> Double {
        let distance = (value - center) / width
        return exp(-(distance * distance))
    }
}

struct PersonalGraphDetailStrip: View {
    var selection: PersonalGraphSelection

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
                Text("\(selection.count) facts")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ElephantTheme.muted)
            }
            if !selection.detail.isEmpty {
                Text(selection.detail)
                    .font(.caption)
                    .foregroundStyle(ElephantTheme.muted)
                    .lineLimit(2)
            }
            if selection.facts.isEmpty {
                EmptyLine(symbol: "circle.grid.cross", text: "No reviewable items in this area yet.")
            } else {
                ForEach(Array(selection.facts.prefix(3).enumerated()), id: \.offset) { _, fact in
                    Text(fact)
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
        "No reviewed \(lensTitle) facts yet. Run Reflect after a few useful conversations."
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
                title: AppSection.skills.title(language: model.appLanguage),
                subtitle: model.text(.skillsPageSubtitle),
                actionTitle: model.text(.refresh),
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
                title: AppSection.tools.title(language: model.appLanguage),
                subtitle: model.text(.toolsPageSubtitle),
                actionTitle: model.text(.refresh),
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
                title: AppSection.messaging.title(language: model.appLanguage),
                subtitle: model.text(.messagingPageSubtitle),
                actionTitle: model.text(.refresh),
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
                    .help(model.text(.changeImage))
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
                title: AppSection.usage.title(language: model.appLanguage),
                subtitle: model.text(.usagePageSubtitle),
                actionTitle: model.text(.refresh),
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
                title: AppSection.learn.title(language: model.appLanguage),
                subtitle: model.text(.learnPageSubtitle),
                actionTitle: model.isReflecting ? model.text(.learning) : model.text(.runLearn),
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

struct SettingsView: View {
    @EnvironmentObject private var model: ElephantAppModel

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
                        subtitle: "\(model.text(.languageSettingsSubtitle))\(model.appLanguage.nativeName)"
                    ) {
                        LanguageSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "slider.horizontal.3",
                        title: model.text(.runtimeConfig),
                        subtitle: model.snapshot.settingsPath.isEmpty ? model.text(.runtimeConfigMissing) : model.snapshot.settingsPath
                    ) {
                        RuntimeConfigSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "questionmark.bubble",
                        title: model.text(.curiosity),
                        subtitle: "\(model.snapshot.waitingQuestions) \(model.text(.curiositySubtitle))"
                    ) {
                        CuriositySettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "clock.arrow.circlepath",
                        title: model.text(.history),
                        subtitle: "\(model.snapshot.episodes) episodes · \(model.snapshot.loops) loops · \(model.snapshot.steps) steps"
                    ) {
                        HistoryUsageSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "moon.zzz",
                        title: model.text(.sleepDisplay),
                        subtitle: String(format: model.text(.sleepDisplaySubtitle), "\(model.sleepIdleMinutes)")
                    ) {
                        SleepDisplaySettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "stethoscope",
                        title: model.text(.logsDiagnostics),
                        subtitle: "\(model.snapshot.logs) \(model.text(.logsDiagnosticsSubtitle))"
                    ) {
                        LogsDiagnosticsSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "exclamationmark.triangle",
                        title: model.text(.resetData),
                        subtitle: model.text(.resetDataSubtitle)
                    ) {
                        ResetDataSettingsContent()
                    }
                    ExpandableSettingsRow(
                        symbol: "terminal",
                        title: model.text(.advancedRuntime),
                        subtitle: model.snapshot.apiURL.isEmpty ? model.corePhase.label : model.snapshot.apiURL
                    ) {
                        RuntimeSettingsContent()
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
    @State private var expanded = false
    @State private var hovering = false

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
                content
                    .padding(.leading, 60)
                    .padding(.trailing, 12)
                    .padding(.bottom, 16)
                    .padding(.top, 8)
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
        if expanded { return ElephantTheme.accent.opacity(0.14) }
        if hovering { return ElephantTheme.accent.opacity(0.08) }
        return ElephantTheme.faint.opacity(0.10)
    }

    private var rowBackground: Color {
        if expanded { return ElephantTheme.accent.opacity(0.075) }
        if hovering { return Color(nsColor: .controlBackgroundColor).opacity(0.58) }
        return Color.clear
    }

    private var rowBorder: Color {
        if expanded { return ElephantTheme.accent.opacity(0.25) }
        if hovering { return ElephantTheme.line.opacity(0.74) }
        return Color.clear
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
            SettingsRow(label: model.text(.languageSettingsTitle), value: model.appLanguage.nativeName)
        }
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
    @State private var showingProviderConfig = false

    var body: some View {
        ZStack {
            providerFactoryContent
                .blur(radius: showingProviderConfig ? 7 : 0)
                .saturation(showingProviderConfig ? 0.82 : 1)
                .allowsHitTesting(!showingProviderConfig)

            if showingProviderConfig, let option = selectedOption {
                ProviderConfigurationModalBackdrop {
                    showingProviderConfig = false
                }

                ProviderConfigurationModal(option: option) {
                    showingProviderConfig = false
                } content: {
                    providerConfigurationForm
                }
                .transition(.scale(scale: 0.97).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.34, dampingFraction: 0.88), value: showingProviderConfig)
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
                VStack(alignment: .leading, spacing: 10) {
                    SectionLabel(title: "Provider factory", subtitle: "\(model.snapshot.providerOptions.count) providers from the runtime catalog. Click a logo card to configure it.")
                    ProviderFactoryGrid(
                        options: model.snapshot.providerOptions,
                        selectedID: providerID,
                        activeID: model.snapshot.providerID
                    ) { option in
                        selectProvider(option, openConfig: true)
                    }
                }
            }
        }
    }

    private var providerConfigurationForm: some View {
        VStack(alignment: .leading, spacing: 14) {
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
    }

    private var selectedOption: ProviderOption? {
        model.snapshot.providerOptions.first(where: { $0.id == providerID })
    }

    private var availableModels: [ProviderModelOption] {
        discoveredModels[providerID] ?? selectedOption?.models ?? []
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

    private func selectProvider(_ option: ProviderOption, openConfig: Bool) {
        providerID = option.id
        applyProviderDefaults(onlyWhenEmpty: false)
        showingProviderConfig = openConfig
        Task { await loadLiveModels(force: true) }
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
                .help("Close")
                .accessibilityLabel("Close provider configuration")
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

struct ProviderFactoryGrid: View {
    var options: [ProviderOption]
    var selectedID: String
    var activeID: String
    var select: (ProviderOption) -> Void

    var body: some View {
        VStack(spacing: 10) {
            ForEach(providerRows.indices, id: \.self) { rowIndex in
                HStack(spacing: 10) {
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
                        .help("Configure \(option.displayName)")
                        .accessibilityLabel("Configure \(option.displayName)")
                        .frame(maxWidth: .infinity)
                    }
                    ForEach(0..<max(0, 4 - providerRows[rowIndex].count), id: \.self) { _ in
                        Color.clear
                            .frame(maxWidth: .infinity)
                    }
                }
            }
        }
    }

    private var providerRows: [[ProviderOption]] {
        stride(from: 0, to: options.count, by: 4).map { index in
            Array(options[index..<min(index + 4, options.count)])
        }
    }
}

struct ProviderSearchField: View {
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
                .help("Clear search")
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
    var options: [ProviderOption]
    var selectedID: String
    var activeID: String
    var select: (ProviderOption) -> Void

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 0) {
                if options.isEmpty {
                    EmptyLine(symbol: "magnifyingglass", text: "No provider matches this search.")
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
                        .help("Configure \(option.displayName)")
                        .accessibilityLabel("Configure \(option.displayName)")
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
        .background(background, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(borderColor, style: borderStroke)
        )
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
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
        return option.authKind.isEmpty ? "provider setup" : option.authKind
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
            return "In use"
        }
        if option.connected {
            return "Connected"
        }
        if option.storedKeyCount > 0 {
            return "\(option.storedKeyCount) key"
        }
        return "Use"
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
        URL(string: "https://unpkg.com/@lobehub/icons-static-png@latest/light/\(slug)\(suffix).png")
    }

    private var suffix: String {
        colorSlugs.contains(slug) ? "-color" : ""
    }

    private var slug: String {
        let id = providerID.lowercased()
        if let alias = aliases[id] {
            return alias
        }
        let display = displayName.lowercased()
        if display.contains("claude code") { return "claudecode" }
        if display.contains("claude") { return "claude" }
        if display.contains("codex") || display.contains("openai") { return "openai" }
        if display.contains("copilot") { return "githubcopilot" }
        if display.contains("gemini cli") { return "geminicli" }
        if display.contains("gemini") || display.contains("google") { return "gemini" }
        if display.contains("groq") { return "groq" }
        if display.contains("kilo") { return "kilocode" }
        if display.contains("kimi") || display.contains("moonshot") { return "moonshot" }
        if display.contains("qwen") || display.contains("dashscope") || display.contains("alibaba") { return "qwen" }
        if display.contains("xiaomi") { return "xiaomimimo" }
        return id.replacingOccurrences(of: "-", with: "")
    }

    private var aliases: [String: String] {
        [
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
            "xiaomi": "xiaomimimo",
            "zai": "zai"
        ]
    }

    private var colorSlugs: Set<String> {
        [
            "alibaba",
            "claude",
            "claudecode",
            "deepseek",
            "fireworks",
            "gemini",
            "geminicli",
            "google",
            "huggingface",
            "minimax",
            "mistral",
            "qwen",
            "together",
            "vllm",
            "xiaomimimo",
            "zhipu"
        ]
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

struct SleepDisplaySettingsContent: View {
    @EnvironmentObject private var model: ElephantAppModel
    @State private var password = ""
    @State private var confirmation = ""
    @State private var result = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Stepper(
                value: Binding(
                    get: { model.sleepIdleMinutes },
                    set: { model.updateSleepIdleMinutes($0) }
                ),
                in: 1...120,
                step: 1
            ) {
                SettingsRow(label: model.text(.sleepAutoSleep), value: "\(model.sleepIdleMinutes) min")
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
            HStack {
                Button(model.text(.resetLockPassword)) {
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
                }
                .disabled(password.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && confirmation.isEmpty)

                Button(role: .destructive) {
                    model.clearAppLockPassword()
                    password = ""
                    confirmation = ""
                    result = model.text(.lockPasswordCleared)
                } label: {
                    Text(model.text(.clearLockPassword))
                }
            }
            if !result.isEmpty {
                Text(result)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(result == model.text(.lockPasswordSaved) || result == model.text(.lockPasswordCleared) ? ElephantTheme.green : ElephantTheme.orange)
            }
            Divider()
            HStack {
                Button(model.text(.enterSleepDisplay)) {
                    model.beginSleepDisplay(reason: "manual")
                }
                Button(model.text(.resetSleepTimer)) {
                    model.updateSleepIdleMinutes(10)
                }
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
                label: "Scope",
                value: "Chats, Personal Model, provider keys, config, jobs, and local app state"
            )
            SettingsRow(label: "After reset", value: "The setup flow opens again")

            if !model.resetDataResult.isEmpty {
                Text(model.resetDataResult)
                    .font(.callout)
                    .foregroundStyle(ElephantTheme.green)
            }

            Button(role: .destructive) {
                showingResetPopover = true
            } label: {
                Label(model.isResettingData ? "Resetting..." : "Reset All Data", systemImage: "trash")
            }
            .disabled(model.isResettingData)
            .popover(isPresented: $showingResetPopover, arrowEdge: .bottom) {
                VStack(alignment: .leading, spacing: 14) {
                    SectionLabel(
                        title: "Reset Elephant Agent?",
                        subtitle: "This cannot be undone."
                    )
                    VStack(alignment: .leading, spacing: 8) {
                        EmptyLine(symbol: "message", text: "Chat history and episode records will be deleted.")
                        EmptyLine(symbol: "person.crop.circle", text: "Personal Model facts, questions, profile photo, and herd data will be deleted.")
                        EmptyLine(symbol: "key", text: "Provider keys, gateway secrets, global config, and jobs will be deleted.")
                    }
                    HStack {
                        Button("Cancel") {
                            showingResetPopover = false
                        }
                        Spacer()
                        Button(role: .destructive) {
                            showingResetPopover = false
                            Task { await model.resetAllData() }
                        } label: {
                            Label("Reset All Data", systemImage: "trash")
                        }
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
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var onComplete: () -> Void
    @State private var transitionForward = true
    private let learnStep = 15
    private let readyStep = 16
    private let totalSteps = 17

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
            OnboardingProviderSecretStep()
        case 15:
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
        case 14: return model.text(.startSetup)
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
        case 14:
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
            OnboardingPhase(id: "model", title: .phaseModel, symbol: "cpu", range: 13...14),
            OnboardingPhase(id: "ready", title: .phaseReady, symbol: "checkmark.seal", range: 15...16)
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
        case 14:
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
                        OnboardingField(title: model.text(.birthDate), placeholder: "YYYY-MM-DD", text: $model.onboardingBirthDate)
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
            OnboardingField(
                title: model.text(.hobbies),
                placeholder: model.text(.hobbiesPlaceholder),
                text: $model.onboardingHobbies,
                suggestions: [model.text(.hobbiesSuggestionOne), model.text(.hobbiesSuggestionTwo), model.text(.hobbiesSuggestionThree)]
            )
            OnboardingField(title: model.text(.longTermDirection), placeholder: model.text(.longTermDirectionPlaceholder), text: $model.onboardingDream, lines: 3...4)
        }
    }
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
    @State private var discoveredModels: [String: [ProviderModelOption]] = [:]
    @State private var loadingModels = false
    @State private var loaded = false
    @State private var autoFetchedProviderID = ""
    @State private var providerSearch = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            OnboardingStepHeader(
                title: model.text(.providerTitle),
                subtitle: model.text(.providerSubtitle),
                symbol: "cpu"
            )
            if model.snapshot.providerOptions.isEmpty {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 7) {
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
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(width: 220)
                    OnboardingField(title: model.text(.modelID), placeholder: "gpt-4.1 / claude-3.7-sonnet", text: $model.onboardingModelID)
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
                        selectProvider(option, fetch: true)
                    }
                    .frame(height: 158)
                }
            }

            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    SectionLabel(title: model.text(.modelSection), subtitle: selectedOption?.active == true ? model.text(.activeModelSubtitle) : model.text(.modelPickerSubtitle))
                    Spacer(minLength: 0)
                    Button {
                        Task { await loadLiveModels(force: true) }
                    } label: {
                        Label(loadingModels ? model.text(.fetching) : model.text(.fetch), systemImage: "arrow.clockwise")
                    }
                    .disabled(model.onboardingProviderID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || loadingModels)
                    .controlSize(.small)
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
        }
        .onAppear {
            guard !loaded else { return }
            loadFromSnapshot()
            loaded = true
            Task { await loadLiveModelsIfNeeded() }
        }
        .onChange(of: model.onboardingProviderID) { _ in
            applyProviderDefaults(onlyWhenEmpty: false)
            Task { await loadLiveModelsIfNeeded() }
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

    private var availableModels: [ProviderModelOption] {
        discoveredModels[model.onboardingProviderID] ?? selectedOption?.models ?? []
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

    private func selectProvider(_ option: ProviderOption, fetch: Bool) {
        model.onboardingProviderID = option.id
        applyProviderDefaults(onlyWhenEmpty: false)
        if fetch {
            Task { await loadLiveModels(force: true) }
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
        if force || !rows.isEmpty {
            autoFetchedProviderID = providerID
        }
        loadingModels = false
    }

    private func loadLiveModelsIfNeeded() async {
        let providerID = model.onboardingProviderID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !providerID.isEmpty,
              autoFetchedProviderID != providerID,
              discoveredModels[providerID] == nil else { return }
        await loadLiveModels(force: true)
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
