import AppKit
import Foundation
import SwiftUI

enum AppSection: String, CaseIterable, Identifiable {
    case home
    case wake
    case you
    case diary
    case skills
    case tools
    case messaging
    case herd
    case usage
    case cron
    case learn
    case provider
    case settings

    var id: String { rawValue }

    static let primary: [AppSection] = [
        .home,
        .wake,
        .you,
        .diary,
        .skills,
        .tools,
        .messaging,
        .herd,
        .usage,
        .cron,
        .learn
    ]

    var title: String {
        switch self {
        case .home: return "Home"
        case .wake: return "Chat"
        case .you: return "You"
        case .diary: return "Diary"
        case .skills: return "Skills"
        case .tools: return "Tools"
        case .messaging: return "Messaging"
        case .herd: return "Herd"
        case .usage: return "Usage"
        case .cron: return "Calendar"
        case .learn: return "Learn"
        case .provider: return "Provider"
        case .settings: return "Settings"
        }
    }

    var subtitle: String {
        switch self {
        case .home: return "Today"
        case .wake: return "Talk"
        case .you: return "Model"
        case .diary: return "Journal"
        case .skills: return "Affinity"
        case .tools: return "Actions"
        case .messaging: return "IM"
        case .herd: return "Elephants"
        case .usage: return "Tokens"
        case .cron: return "Reminders"
        case .learn: return "Reflect"
        case .provider: return "Model"
        case .settings: return "System"
        }
    }

    var symbol: String {
        switch self {
        case .home: return "house"
        case .wake: return "bubble.left.and.bubble.right"
        case .you: return "person.crop.circle"
        case .diary: return "book.closed"
        case .skills: return "wand.and.stars"
        case .tools: return "wrench.and.screwdriver"
        case .messaging: return "message.badge"
        case .herd: return "person.3"
        case .usage: return "chart.xyaxis.line"
        case .cron: return "calendar"
        case .learn: return "brain.head.profile"
        case .provider: return "cpu"
        case .settings: return "gearshape"
        }
    }

    var shortcut: KeyEquivalent? {
        switch self {
        case .home: return "1"
        case .wake: return "2"
        case .you: return "3"
        case .diary: return "4"
        case .skills: return "5"
        case .tools: return nil
        case .messaging: return "6"
        case .herd: return "7"
        case .usage: return "8"
        case .cron: return "9"
        case .learn: return "0"
        case .provider, .settings: return nil
        }
    }
}

enum CorePhase: Equatable {
    case idle
    case starting
    case ready
    case failed(String)

    var label: String {
        switch self {
        case .idle: return "idle"
        case .starting: return "starting"
        case .ready: return "ready"
        case .failed: return "needs attention"
        }
    }
}

struct ToolUseEvent: Identifiable, Equatable {
    var id = UUID()
    var invocationID: String = ""
    var name: String
    var status: String
    var arguments: String
    var result: String
}

struct ChatMessage: Identifiable, Equatable {
    enum Role {
        case user
        case assistant
        case system
    }

    var id = UUID()
    var role: Role
    var text: String
    var date = Date()
    var toolEvents: [ToolUseEvent] = []
    var isStreaming = false
}

struct PersonalModelFact: Identifiable, Equatable {
    var id: String
    var text: String
    var lens: String
    var topic: String
    var status: String
    var detail: String
}

struct ProfileAnchorFact: Identifiable, Equatable {
    var id: String { "\(label):\(value)" }
    var label: String
    var value: String
    var full: Bool
}

struct SkillAffinity: Identifiable, Equatable {
    var id: String
    var name: String
    var count: Int
    var latestText: String
}

struct DiaryEntry: Identifiable, Equatable {
    var id: String
    var date: String
    var content: String
    var generatedAt: String
}

struct ProviderOption: Identifiable, Equatable {
    var id: String
    var displayName: String
    var defaultModel: String
    var defaultBaseURL: String
    var status: String
    var source: String
    var authKind: String
    var summary: String
    var connected: Bool
    var active: Bool
    var storedKeyCount: Int
    var models: [ProviderModelOption]
}

struct ProviderModelOption: Identifiable, Equatable {
    var id: String
    var label: String
    var source: String
}

struct OperationItem: Identifiable, Equatable {
    var id: String
    var title: String
    var detail: String
    var enabled: Bool
}

struct GatewayServiceItem: Identifiable, Equatable {
    var id: String
    var title: String
    var detail: String
    var configured: Bool
    var running: Bool
    var starting: Bool
    var accountID: String
    var transport: String
    var accountCount: Int
    var eventPath: String
    var setupNote: String
    var secretFields: [GatewaySecretField]
}

struct GatewaySecretField: Identifiable, Equatable {
    var id: String { key }
    var key: String
    var label: String
    var hasValue: Bool
}

struct EpisodeThread: Identifiable, Equatable {
    var id: String
    var title: String
    var subtitle: String
    var summary: String
    var status: String
    var messages: [ChatMessage]
}

struct HerdItem: Identifiable, Equatable {
    var id: String
    var elephantID: String
    var title: String
    var subtitle: String
    var profileID: String
    var current: Bool
    var status: String
    var stage: String
    var level: Int
    var progressPercent: Double
    var scoreToNextLevel: Int
    var summary: String
    var identityText: String
    var createdAt: String
    var updatedAt: String
    var source: String
}

struct CronJobItem: Identifiable, Equatable {
    var id: String
    var title: String
    var detail: String
    var schedule: String
    var status: String
    var nextRun: String
    var lastRun: String
    var runCount: Int
    var isSystem: Bool
    var systemKind: String
    var canRunNow: Bool
    var canPause: Bool
    var canDelete: Bool
}

struct UsageEventItem: Identifiable, Equatable {
    var id: String
    var title: String
    var subtitle: String
    var provider: String
    var model: String
    var promptTokens: Int
    var completionTokens: Int
    var totalTokens: Int
}

struct UsageTrendPoint: Identifiable, Equatable {
    var id: String { date }
    var date: String
    var promptTokens: Int
    var completionTokens: Int
    var totalTokens: Int
}

struct LearningJobItem: Identifiable, Equatable {
    var id: String
    var title: String
    var detail: String
    var status: String
    var trigger: String
    var markdown: String
}

struct PersonalModelQuestionItem: Identifiable, Equatable {
    var id: String
    var text: String
    var status: String
    var lens: String
    var subLens: String
    var source: String
    var sensitivity: String
    var priority: Double
    var askedCount: Int
    var lastAskedSurface: String
    var lastAskedAt: String
    var createdAt: String
    var resultingFacts: [PersonalModelFact]

    var statusTitle: String {
        switch status {
        case "ready": return "Ready"
        case "asked": return "Asked"
        case "answered": return "Learned"
        case "dismissed": return "Dismissed"
        default: return status.isEmpty ? "Question" : status.capitalized
        }
    }

    var canAct: Bool {
        status == "ready" || status == "asked"
    }
}

struct LogFileItem: Identifiable, Equatable {
    var id: String
    var name: String
    var path: String
    var size: Int
    var updatedAt: String
    var tail: [String]

    var detail: String {
        [size > 0 ? "\(size) bytes" : "", updatedAt].filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

struct GatewayQRState: Equatable {
    var sessionID = ""
    var status = ""
    var message = ""
    var qrcodeURL = ""
    var matrix: [[Int]] = []
}

struct DashboardSnapshot: Equatable {
    var databasePath = ""
    var apiURL = ""
    var providerStatus = "unknown"
    var providerID = ""
    var providerModelID = ""
    var providerBaseURL = ""
    var providerSource = ""
    var providerOptions: [ProviderOption] = []
    var embeddingStatus = ""
    var embeddingProviderID = ""
    var embeddingRuntimeStatus = ""
    var embeddingRuntimeState = ""
    var embeddingRuntimeSummary = ""
    var embeddingReady = false
    var semanticStatus = "unknown"
    var workerStatus = "unknown"
    var currentPersonalModelID = ""
    var currentStateID = ""
    var elephantName = "Elephant"
    var states = 0
    var episodes = 0
    var loops = 0
    var steps = 0
    var semanticEntries = 0
    var facts = 0
    var waitingQuestions = 0
    var skills = 0
    var skillAffinities = 0
    var tools = 0
    var enabledTools = 0
    var mcpServers = 0
    var mcpTools = 0
    var gatewayServices = 0
    var gatewayConfigured = 0
    var gatewayRunning = 0
    var usageEvents = 0
    var usageTokens = 0
    var usagePromptTokens = 0
    var usageCompletionTokens = 0
    var logs = 0
    var cronJobs = 0
    var latestCompletedAt = ""
    var settingsPath = ""
    var settingsYaml = ""
    var askedQuestions = 0
    var answeredQuestions = 0
    var dismissedQuestions = 0
    var questionIntensity = "medium"
    var questionAskEnabled = true
    var questionIdleMinutes = 180
    var questionDailyMax = 8
    var questionQuietStart = 23
    var questionQuietEnd = 7
    var lensCoverage: [String: Int] = [:]
    var sampleQuestions: [String] = []
    var questionItems: [PersonalModelQuestionItem] = []
    var sampleFacts: [String] = []
    var personalModelFacts: [PersonalModelFact] = []
    var profileFacts: [ProfileAnchorFact] = []
    var skillAffinityRows: [SkillAffinity] = []
    var diaryEntries: [DiaryEntry] = []
    var skillNames: [String] = []
    var skillItems: [OperationItem] = []
    var toolNames: [String] = []
    var toolItems: [OperationItem] = []
    var gatewayNames: [String] = []
    var gatewayItems: [GatewayServiceItem] = []
    var logItems: [OperationItem] = []
    var logFiles: [LogFileItem] = []
    var episodeThreads: [EpisodeThread] = []
    var cronNames: [String] = []
    var cronItems: [CronJobItem] = []
    var usageItems: [UsageEventItem] = []
    var usageTrend: [UsageTrendPoint] = []
    var learningItems: [LearningJobItem] = []
    var stateNames: [String] = []
    var herdItems: [HerdItem] = []

    static let empty = DashboardSnapshot()

    var hasElephant: Bool { states > 0 || !currentStateID.isEmpty }

    var providerReady: Bool {
        guard !providerID.isEmpty, !providerModelID.isEmpty else { return false }
        let value = providerStatus.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return !value.contains("missing") && !value.contains("setup") && !value.contains("failed")
    }

    var localModelWarm: Bool {
        if embeddingReady { return true }
        let runtime = embeddingRuntimeState.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return runtime == "loaded" || runtime == "external"
    }

    var readyForInteraction: Bool {
        providerReady && localModelWarm
    }
}

@MainActor
final class ElephantAppModel: ObservableObject {
    @Published var selectedSection: AppSection = .home
    @Published var corePhase: CorePhase = .idle
    @Published var snapshot: DashboardSnapshot = .empty
    @Published var messages: [ChatMessage] = [
        ChatMessage(role: .system, text: "Start a short conversation. Elephant will keep useful facts and open questions reviewable.")
    ]
    @Published var chatScrollRevision = 0
    @Published var wakeDraft = ""
    @Published var onboardingName = "Elephant"
    @Published var onboardingPurpose = "Be warm, precise, curious, and direct. Protect continuity, ask useful questions, and keep the user's Personal Model correctable."
    @Published var onboardingPreferredName = ""
    @Published var onboardingOccupation = ""
    @Published var onboardingSchool = ""
    @Published var onboardingCity = ""
    @Published var onboardingGender = ""
    @Published var onboardingBirthDate = ""
    @Published var onboardingMBTI = ""
    @Published var onboardingHobbies = ""
    @Published var onboardingDream = ""
    @Published var onboardingCreativeHobby = ""
    @Published var onboardingMediaHobby = ""
    @Published var onboardingMovementHobby = ""
    @Published var onboardingSafetyBoundaries = ""
    @Published var onboardingFoodAllergies = ""
    @Published var onboardingMedicationAllergies = ""
    @Published var onboardingChronicConditions = ""
    @Published var onboardingPrivateSafetyNote = ""
    @Published var onboardingFirstLanguage = "en"
    @Published var onboardingBlogURL = ""
    @Published var onboardingLinkedInURL = ""
    @Published var onboardingTwitterURL = ""
    @Published var onboardingInnerLandscape = ""
    @Published var onboardingValueAnchor = ""
    @Published var onboardingPressurePattern = ""
    @Published var onboardingRecoveryStyle = ""
    @Published var onboardingDecisionCompass = ""
    @Published var onboardingProviderID = "openai-compatible"
    @Published var onboardingBaseURL = ""
    @Published var onboardingModelID = ""
    @Published var onboardingAPIKey = ""
    @Published var onboardingContextWindow = ""
    @Published var onboardingStep = 0
    @Published var onboardingFinalizationStarted = false
    @Published var onboardingFinalizationComplete = false
    @Published var onboardingFinalizationFailed = false
    @Published var onboardingFinalizationStatus = ""
    @Published var onboardingInitReflectJobID = ""
    @Published var showingOnboarding = false
    @Published var showingCommandPalette = false
    @Published var lastError = ""
    @Published var providerTestResult = ""
    @Published var gatewayActionResult = ""
    @Published var gatewaySecretDrafts: [String: [String: String]] = [:]
    @Published var gatewayQR = GatewayQRState()
    @Published var cronActionResult = ""
    @Published var diaryActionResult = ""
    @Published var factActionResult = ""
    @Published var configActionResult = ""
    @Published var isReflecting = false
    @Published var isWakeRunning = false
    @Published var activeEpisodeID = ""
    @Published var composerFocusToken = UUID()
    @Published var userAvatarPath = UserDefaults.standard.string(forKey: ElephantAppModel.userAvatarPathKey) ?? ""
    @Published var herdAvatarPaths: [String: String] = UserDefaults.standard.dictionary(forKey: ElephantAppModel.herdAvatarPathsKey) as? [String: String] ?? [:]
    @Published var hiddenEpisodeIDs: Set<String> = Set(UserDefaults.standard.stringArray(forKey: ElephantAppModel.hiddenEpisodeIDsKey) ?? [])
    @Published var isSleepDisplayPresented = false
    @Published var sleepDisplayReason = "manual"
    @Published var sleepIdleMinutes = ElephantAppModel.persistedSleepIdleMinutes()
    @Published var lastInteractionDate = Date()
    @Published var isResettingData = false
    @Published var resetDataResult = ""

    private let runner = CoreRunner()
    private var client = APIClient(baseURL: nil)
    private var readinessPollTask: Task<Void, Never>?
    private var sleepIdleMonitorTask: Task<Void, Never>?
    private var onboardingCreatedStateID = ""
    private static let onboardingCompleteKey = "elephant.mac.onboardingComplete"
    private static let userAvatarPathKey = "elephant.mac.userAvatarImagePath"
    private static let herdAvatarPathsKey = "elephant.mac.herdAvatarImagePaths"
    private static let hiddenEpisodeIDsKey = "elephant.mac.hiddenEpisodeIDs"
    private static let sleepIdleMinutesKey = "elephant.mac.sleepIdleMinutes"
    private static let defaultSleepIdleMinutes = 10

    var userDisplayName: String {
        if let name = snapshot.profileFacts.first(where: { $0.label == "Name" })?.value,
           !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return name
        }
        let preferred = onboardingPreferredName.trimmingCharacters(in: .whitespacesAndNewlines)
        if !preferred.isEmpty { return preferred }
        return "You"
    }

    var userAvatarURL: URL? {
        let path = userAvatarPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !path.isEmpty else { return nil }
        return URL(fileURLWithPath: path)
    }

    var onboardingElephantMarkdown: String {
        let name = onboardingName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? "Elephant"
            : onboardingName.trimmingCharacters(in: .whitespacesAndNewlines)
        let vibe = onboardingPurpose.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? "Be warm, precise, curious, and direct."
            : onboardingPurpose.trimmingCharacters(in: .whitespacesAndNewlines)
        return """
        # \(name)

        ## Vibe

        \(vibe)
        """
    }

    func launch() async {
        startSleepIdleMonitorIfNeeded()
        guard corePhase != .ready && corePhase != .starting else { return }
        corePhase = .starting
        do {
            let runtime = try await runner.start()
            client = APIClient(baseURL: runtime.baseURL)
            snapshot.apiURL = runtime.baseURL.absoluteString
            snapshot.databasePath = runtime.databasePath.path
            try await refreshDashboard()
            corePhase = .ready
            startReadinessPollingIfNeeded()
            if !snapshot.hasElephant || snapshot.providerID.isEmpty {
                showingOnboarding = true
            }
        } catch {
            corePhase = .failed(error.localizedDescription)
            lastError = error.localizedDescription
        }
    }

    func refreshDashboard() async throws {
        var next = try await client.fetchSnapshot()
        if next.apiURL.isEmpty {
            next.apiURL = client.baseURL?.absoluteString ?? ""
        }
        if next.databasePath.isEmpty {
            next.databasePath = runner.databasePath?.path ?? ""
        }
        next.episodeThreads.removeAll { hiddenEpisodeIDs.contains($0.id) }
        snapshot = next
        if snapshot.readyForInteraction {
            readinessPollTask?.cancel()
            readinessPollTask = nil
        } else if corePhase == .ready {
            startReadinessPollingIfNeeded()
        }
    }

    private func startReadinessPollingIfNeeded() {
        guard corePhase == .ready, !snapshot.readyForInteraction else {
            readinessPollTask?.cancel()
            readinessPollTask = nil
            return
        }
        guard readinessPollTask == nil else { return }
        readinessPollTask = Task { [weak self] in
            for _ in 0..<45 {
                guard let self else { return }
                if Task.isCancelled { return }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                if Task.isCancelled { return }
                do {
                    try await self.refreshDashboard()
                } catch {
                    self.lastError = error.localizedDescription
                }
                if self.snapshot.readyForInteraction {
                    return
                }
            }
            self?.readinessPollTask = nil
        }
    }

    func restartCore() async {
        corePhase = .starting
        runner.stop()
        do {
            let runtime = try await runner.start()
            client = APIClient(baseURL: runtime.baseURL)
            snapshot.apiURL = runtime.baseURL.absoluteString
            snapshot.databasePath = runtime.databasePath.path
            try await refreshDashboard()
            corePhase = .ready
            startReadinessPollingIfNeeded()
        } catch {
            corePhase = .failed(error.localizedDescription)
            lastError = error.localizedDescription
        }
    }

    func resetAllData() async {
        guard !isResettingData else { return }
        isResettingData = true
        resetDataResult = ""
        lastError = ""
        corePhase = .starting
        readinessPollTask?.cancel()
        readinessPollTask = nil
        do {
            let runtime = try await runner.resetLocalData()
            try resetLocalMacStateForFreshInstall()
            resetOnboardingDrafts()
            client = APIClient(baseURL: runtime.baseURL)
            snapshot = .empty
            snapshot.apiURL = runtime.baseURL.absoluteString
            snapshot.databasePath = runtime.databasePath.path
            activeEpisodeID = ""
            messages = [
                ChatMessage(role: .system, text: "Set up Elephant to start a new local conversation.")
            ]
            chatScrollRevision += 1
            try await refreshDashboard()
            corePhase = .ready
            selectedSection = .home
            showingOnboarding = true
            resetDataResult = "Reset complete. Set up Elephant again."
        } catch {
            corePhase = .failed(error.localizedDescription)
            lastError = error.localizedDescription
        }
        isResettingData = false
    }

    private var onboardingCareSummary: String {
        let rows: [(String, String)] = [
            ("boundaries", onboardingSafetyBoundaries),
            ("food_allergies", onboardingFoodAllergies),
            ("medication_allergies", onboardingMedicationAllergies),
            ("chronic_conditions", onboardingChronicConditions),
            ("private_safety_note", onboardingPrivateSafetyNote)
        ]
        return rows.compactMap { key, value in
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : "\(key): \(trimmed)"
        }
        .joined(separator: "; ")
    }

    @discardableResult
    private func createElephantProfileFromOnboarding() async throws -> String {
        if client.baseURL == nil {
            _ = try await runner.start()
            client = APIClient(baseURL: runner.baseURL)
        }
        let canReuseCurrentProvider = onboardingProviderID == snapshot.providerID
            && (onboardingModelID.isEmpty || onboardingModelID == snapshot.providerModelID)
            && onboardingBaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && onboardingAPIKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        if !canReuseCurrentProvider {
            try await client.configureProvider(
                providerID: onboardingProviderID,
                baseURL: onboardingBaseURL,
                modelID: onboardingModelID,
                apiKey: onboardingAPIKey,
                contextWindow: onboardingContextWindow
            )
        }
        let stateID: String
        if onboardingCreatedStateID.isEmpty {
            stateID = try await client.createElephant(name: onboardingName, identityText: onboardingElephantMarkdown)
            onboardingCreatedStateID = stateID
        } else {
            stateID = onboardingCreatedStateID
        }
        try await client.updateUserProfile(
            stateID: stateID,
            preferredName: onboardingPreferredName,
            occupation: onboardingOccupation,
            school: onboardingSchool,
            city: onboardingCity,
            gender: onboardingGender,
            birthDate: onboardingBirthDate,
            mbti: onboardingMBTI,
            hobbies: onboardingHobbies,
            dream: onboardingDream,
            creativeHobby: onboardingCreativeHobby,
            mediaHobby: onboardingMediaHobby,
            movementHobby: onboardingMovementHobby,
            safetyBoundaries: onboardingCareSummary,
            firstLanguage: onboardingFirstLanguage,
            blogURL: onboardingBlogURL,
            linkedInURL: onboardingLinkedInURL,
            twitterURL: onboardingTwitterURL,
            personalLogoPath: userAvatarPath,
            innerLandscape: onboardingInnerLandscape,
            valueAnchor: onboardingValueAnchor,
            pressurePattern: onboardingPressurePattern,
            recoveryStyle: onboardingRecoveryStyle,
            decisionCompass: onboardingDecisionCompass
        )
        return stateID
    }

    func createElephantFromOnboarding() async {
        do {
            _ = try await createElephantProfileFromOnboarding()
            try await refreshDashboard()
            onboardingStep = max(onboardingStep, 1)
        } catch {
            lastError = error.localizedDescription
        }
    }

    func startOnboardingFinalization() async {
        guard !onboardingFinalizationStarted else { return }
        onboardingFinalizationStarted = true
        onboardingFinalizationComplete = false
        onboardingFinalizationFailed = false
        onboardingFinalizationStatus = "Creating your local Personal Model"
        onboardingInitReflectJobID = ""
        lastError = ""
        do {
            let stateID = try await createElephantProfileFromOnboarding()
            onboardingFinalizationStatus = "Opening the first local episode"
            try await refreshDashboard()
            let resolvedStateID = snapshot.currentStateID.isEmpty ? stateID : snapshot.currentStateID
            let episodeID = try await client.ensureWakeEpisode(
                personalModelID: snapshot.currentPersonalModelID,
                elephantID: resolvedStateID,
                activeEpisodeID: ""
            )
            activeEpisodeID = episodeID
            onboardingFinalizationStatus = "Starting the first learning pass"
            let jobID = try await client.runReflect(trigger: "init_profile")
            onboardingInitReflectJobID = jobID
            try await pollOnboardingInitReflectJob(jobID: jobID)
        } catch {
            onboardingFinalizationFailed = true
            onboardingFinalizationStarted = false
            onboardingFinalizationStatus = "Setup needs attention"
            lastError = error.localizedDescription
        }
    }

    private func pollOnboardingInitReflectJob(jobID: String) async throws {
        let maxAttempts = 120
        for attempt in 0..<maxAttempts {
            if Task.isCancelled { return }
            onboardingFinalizationStatus = attempt < 2 ? "Learning from your setup answers" : "Finishing the first reflection"
            try await refreshDashboard()
            if let job = onboardingInitReflectJob(jobID: jobID) {
                let status = job.status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                if status.contains("completed") || status.contains("succeeded") || status == "success" {
                    onboardingFinalizationStatus = "Everything is ready"
                    onboardingFinalizationComplete = true
                    onboardingStep = 17
                    return
                }
                if status.contains("failed") || status.contains("cancel") || status.contains("error") {
                    throw APIClientError.badStatus(job.detail.isEmpty ? "The init learning job did not complete." : job.detail)
                }
            }
            try await Task.sleep(nanoseconds: 2_000_000_000)
        }
        throw APIClientError.badStatus("The init learning job is still running. You can enter Elephant and review the learning queue later.")
    }

    private func onboardingInitReflectJob(jobID: String) -> LearningJobItem? {
        if !jobID.isEmpty {
            return snapshot.learningItems.first { $0.id == jobID }
        }
        return snapshot.learningItems.first {
            let trigger = $0.trigger.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            return trigger == "init" || trigger.contains("init")
        }
    }

    func completeOnboarding() {
        showingOnboarding = false
        selectedSection = .wake
    }

    func startNewChat() {
        activeEpisodeID = ""
        messages = [
            ChatMessage(role: .system, text: "New conversation ready. Keep it short and review what Elephant learns.")
        ]
        selectedSection = .wake
        focusComposer()
    }

    func openEpisodeThread(_ thread: EpisodeThread) {
        activeEpisodeID = thread.id
        if thread.messages.isEmpty {
            messages = [
                ChatMessage(role: .system, text: thread.summary.isEmpty ? "This conversation has no rendered messages yet." : thread.summary)
            ]
        } else {
            messages = thread.messages
        }
        selectedSection = .wake
        focusComposer()
    }

    func deleteEpisodeThread(_ thread: EpisodeThread) {
        hiddenEpisodeIDs.insert(thread.id)
        UserDefaults.standard.set(Array(hiddenEpisodeIDs), forKey: Self.hiddenEpisodeIDsKey)
        snapshot.episodeThreads.removeAll { $0.id == thread.id }
        if activeEpisodeID == thread.id {
            startNewChat()
        }
    }

    func beginSleepDisplay(reason: String = "manual") {
        sleepDisplayReason = reason
        isSleepDisplayPresented = true
    }

    func dismissSleepDisplay() {
        guard isSleepDisplayPresented else {
            lastInteractionDate = Date()
            return
        }
        isSleepDisplayPresented = false
        lastInteractionDate = Date()
    }

    func registerUserActivity() {
        if isSleepDisplayPresented {
            dismissSleepDisplay()
            return
        }
        let now = Date()
        if now.timeIntervalSince(lastInteractionDate) > 0.35 {
            lastInteractionDate = now
        }
    }

    func updateSleepIdleMinutes(_ value: Int) {
        let clamped = min(120, max(1, value))
        sleepIdleMinutes = clamped
        UserDefaults.standard.set(clamped, forKey: Self.sleepIdleMinutesKey)
        lastInteractionDate = Date()
    }

    func pickUserAvatar() {
        guard let url = OpenPanelBridge.pickAvatarImageURL() else { return }
        do {
            let destination = try persistUserAvatar(from: url)
            userAvatarPath = destination.path
            UserDefaults.standard.set(destination.path, forKey: Self.userAvatarPathKey)
        } catch {
            lastError = error.localizedDescription
        }
    }

    func pickHerdAvatar(for item: HerdItem) {
        guard let url = OpenPanelBridge.pickAvatarImageURL() else { return }
        do {
            try persistHerdAvatar(from: url, key: herdAvatarKey(for: item))
        } catch {
            lastError = error.localizedDescription
        }
    }

    func herdAvatarURL(for item: HerdItem) -> URL? {
        let key = herdAvatarKey(for: item)
        guard let path = herdAvatarPaths[key], !path.isEmpty else { return nil }
        return URL(fileURLWithPath: path)
    }

    func revealDatabase() {
        guard !snapshot.databasePath.isEmpty else { return }
        let url = URL(fileURLWithPath: snapshot.databasePath)
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    private func persistUserAvatar(from sourceURL: URL) throws -> URL {
        let fileManager = FileManager.default
        let root = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        let directory = root.appendingPathComponent("Elephant Agent", isDirectory: true)
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)

        let ext = sourceURL.pathExtension.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? "png"
            : sourceURL.pathExtension.lowercased()
        let destination = directory.appendingPathComponent("user-avatar").appendingPathExtension(ext)
        let existing = try fileManager.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("user-avatar.") }
        for file in existing where file.standardizedFileURL.path != destination.standardizedFileURL.path {
            try? fileManager.removeItem(at: file)
        }
        if sourceURL.standardizedFileURL.path != destination.standardizedFileURL.path {
            if fileManager.fileExists(atPath: destination.path) {
                try fileManager.removeItem(at: destination)
            }
            try fileManager.copyItem(at: sourceURL, to: destination)
        }
        return destination
    }

    private func persistHerdAvatar(from sourceURL: URL, key: String) throws {
        let fileManager = FileManager.default
        let root = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        let directory = root
            .appendingPathComponent("Elephant Agent", isDirectory: true)
            .appendingPathComponent("Herd Avatars", isDirectory: true)
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)

        let ext = sourceURL.pathExtension.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? "png"
            : sourceURL.pathExtension.lowercased()
        let destination = directory.appendingPathComponent(UUID().uuidString).appendingPathExtension(ext)
        try fileManager.copyItem(at: sourceURL, to: destination)

        if let previous = herdAvatarPaths[key], !previous.isEmpty {
            try? fileManager.removeItem(at: URL(fileURLWithPath: previous))
        }
        herdAvatarPaths[key] = destination.path
        UserDefaults.standard.set(herdAvatarPaths, forKey: Self.herdAvatarPathsKey)
    }

    private func herdAvatarKey(for item: HerdItem?, fallback: String = "") -> String {
        guard let item else {
            let trimmed = fallback.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? UUID().uuidString : trimmed
        }
        return herdAvatarKey(for: item)
    }

    private func herdAvatarKey(for item: HerdItem) -> String {
        if !item.id.isEmpty { return item.id }
        if !item.elephantID.isEmpty { return item.elephantID }
        return item.title
    }

    func runReflect(trigger: String, features: String? = nil) async {
        guard !isReflecting else { return }
        isReflecting = true
        do {
            try await client.runReflect(trigger: trigger, features: features)
            try? await Task.sleep(nanoseconds: 700_000_000)
            try await refreshDashboard()
            UNNotificationBridge.notify(title: "Reflect finished", body: "Elephant updated its review queue.")
        } catch {
            lastError = error.localizedDescription
        }
        isReflecting = false
    }

    func writeDiary(targetDate: String) async {
        let date = targetDate.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !date.isEmpty else { return }
        do {
            try await client.writeDiary(targetDate: date)
            diaryActionResult = "Diary write queued for \(date)."
            try? await Task.sleep(nanoseconds: 700_000_000)
            try await refreshDashboard()
        } catch {
            diaryActionResult = ""
            lastError = error.localizedDescription
        }
    }

    func testProvider() async {
        do {
            providerTestResult = try await client.testProvider()
            try? await refreshDashboard()
        } catch {
            providerTestResult = ""
            lastError = error.localizedDescription
        }
    }

    func saveProviderSettings(
        providerID: String,
        baseURL: String,
        modelID: String,
        apiKey: String,
        contextWindow: String
    ) async {
        do {
            try await client.configureProvider(
                providerID: providerID,
                baseURL: baseURL,
                modelID: modelID,
                apiKey: apiKey,
                contextWindow: contextWindow
            )
            try await refreshDashboard()
            providerTestResult = "Provider saved."
        } catch {
            providerTestResult = ""
            lastError = error.localizedDescription
        }
    }

    func discoverProviderModels(providerID: String, baseURL: String, apiKey: String) async -> [ProviderModelOption] {
        do {
            let rows = try await client.discoverProviderModels(providerID: providerID, baseURL: baseURL, apiKey: apiKey)
            providerTestResult = rows.isEmpty ? "Model discovery returned no live rows." : "\(rows.count) models loaded."
            return rows
        } catch {
            providerTestResult = ""
            lastError = error.localizedDescription
            return []
        }
    }

    func setConsoleItem(kind: String, id: String, enabled: Bool) async {
        do {
            try await client.setConsoleItemEnabled(kind: kind, itemID: id, enabled: enabled)
            try await refreshDashboard()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func setCuriosityIntensity(_ intensity: String) async {
        do {
            try await client.configureLearningIntensity(intensity)
            try await refreshDashboard()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func saveGlobalConfig(yamlText: String) async {
        do {
            try await client.saveGlobalConfig(yamlText: yamlText)
            try await refreshDashboard()
            configActionResult = "Config saved."
        } catch {
            configActionResult = ""
            lastError = error.localizedDescription
        }
    }

    func surfaceQuestionSooner(_ question: PersonalModelQuestionItem) async {
        do {
            try await client.bumpPersonalModelQuestion(
                question.id,
                personalModelID: snapshot.currentPersonalModelID
            )
            try await refreshDashboard()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func dismissQuestion(_ question: PersonalModelQuestionItem) async {
        do {
            try await client.dismissPersonalModelQuestion(
                question.id,
                personalModelID: snapshot.currentPersonalModelID
            )
            try await refreshDashboard()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func answerQuestion(_ question: PersonalModelQuestionItem, content: String) async {
        let answer = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !answer.isEmpty else { return }
        do {
            try await client.answerPersonalModelQuestion(
                question.id,
                content: answer,
                personalModelID: snapshot.currentPersonalModelID,
                episodeID: activeEpisodeID
            )
            try await refreshDashboard()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func draftAnswerForQuestion(_ question: PersonalModelQuestionItem) {
        selectedSection = .wake
        wakeDraft = "Help me answer this Personal Model question:\n\(question.text)\n\n"
        focusComposer()
    }

    func createHerdElephant(
        name: String,
        identityText: String,
        avatarURL: URL? = nil
    ) async {
        do {
            let createdID = try await client.createHerdElephant(
                name: name,
                identityText: identityText
            )
            try await refreshDashboard()
            if let avatarURL {
                let key = herdAvatarKey(
                    for: snapshot.herdItems.first {
                        $0.id == createdID || $0.elephantID == createdID || $0.title.caseInsensitiveCompare(name) == .orderedSame
                    },
                    fallback: createdID.isEmpty ? name : createdID
                )
                try persistHerdAvatar(from: avatarURL, key: key)
            }
        } catch {
            lastError = error.localizedDescription
        }
    }

    func updateHerdElephant(
        _ item: HerdItem,
        name: String,
        identityText: String
    ) async {
        do {
            try await client.updateHerdElephant(
                item,
                name: name,
                identityText: identityText
            )
            try await refreshDashboard()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func deleteHerdElephant(_ item: HerdItem) async {
        do {
            try await client.deleteHerdElephant(item)
            try await refreshDashboard()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func updatePersonalFact(_ fact: PersonalModelFact, action: String, replacementText: String = "") async {
        do {
            try await client.updatePersonalModelClaim(
                claimRef: fact.id,
                action: action,
                lens: fact.lens,
                text: replacementText.isEmpty ? fact.text : replacementText
            )
            factActionResult = "\(action.capitalized) saved."
            try await refreshDashboard()
        } catch {
            factActionResult = ""
            lastError = error.localizedDescription
        }
    }

    func runGatewayAction(service: GatewayServiceItem, action: String) async {
        do {
            let result = try await client.runGatewayAction(
                service: service.id,
                action: action,
                accountID: service.accountID,
                transport: service.transport,
                force: action == "stop"
            )
            gatewayActionResult = result
            try await refreshDashboard()
        } catch {
            gatewayActionResult = ""
            lastError = error.localizedDescription
        }
    }

    func configureGatewayService(_ service: GatewayServiceItem) async {
        do {
            let result = try await client.configureGatewayService(
                service: service.id,
                accountID: service.accountID,
                transport: service.transport,
                secrets: gatewaySecretDrafts[service.id] ?? [:]
            )
            gatewayActionResult = result
            gatewaySecretDrafts[service.id] = [:]
            try await refreshDashboard()
        } catch {
            gatewayActionResult = ""
            lastError = error.localizedDescription
        }
    }

    func startWeixinQR() async {
        do {
            gatewayQR = try await client.startWeixinQR()
            gatewayActionResult = gatewayQR.message.isEmpty ? "Scan the WeChat QR code." : gatewayQR.message
        } catch {
            gatewayQR = GatewayQRState()
            gatewayActionResult = ""
            lastError = error.localizedDescription
        }
    }

    func pollWeixinQR() async {
        guard !gatewayQR.sessionID.isEmpty else { return }
        do {
            gatewayQR = try await client.pollWeixinQR(sessionID: gatewayQR.sessionID)
            gatewayActionResult = gatewayQR.message
            if gatewayQR.status == "confirmed" {
                if let weixin = snapshot.gatewayItems.first(where: { $0.id == "weixin" }) {
                    await runGatewayAction(service: weixin, action: "start")
                }
            }
        } catch {
            lastError = error.localizedDescription
        }
    }

    func createCronJob(name: String, schedule: String, prompt: String) async {
        do {
            try await client.createCronJob(
                name: name,
                schedule: schedule,
                prompt: prompt,
                elephantID: snapshot.currentStateID.replacingOccurrences(of: "state:", with: ""),
                profileID: snapshot.currentPersonalModelID
            )
            cronActionResult = "Reminder created."
            try await refreshDashboard()
        } catch {
            cronActionResult = ""
            lastError = error.localizedDescription
        }
    }

    func runCronJob(_ job: CronJobItem) async {
        do {
            try await client.runCronJob(job.id)
            cronActionResult = "\(job.title) ran."
            try await refreshDashboard()
        } catch {
            cronActionResult = ""
            lastError = error.localizedDescription
        }
    }

    func setCronJob(_ job: CronJobItem, paused: Bool) async {
        do {
            try await client.setCronJobStatus(job.id, action: paused ? "pause" : "resume")
            cronActionResult = paused ? "\(job.title) paused." : "\(job.title) resumed."
            try await refreshDashboard()
        } catch {
            cronActionResult = ""
            lastError = error.localizedDescription
        }
    }

    func deleteCronJob(_ job: CronJobItem) async {
        do {
            try await client.deleteCronJob(job.id)
            cronActionResult = "\(job.title) deleted."
            try await refreshDashboard()
        } catch {
            cronActionResult = ""
            lastError = error.localizedDescription
        }
    }

    func sendWakeMessage() async {
        let text = wakeDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isWakeRunning else { return }
        wakeDraft = ""
        messages.append(ChatMessage(role: .user, text: text))
        chatScrollRevision += 1
        isWakeRunning = true

        var assistantMessageID: UUID?
        var currentAssistantTextMessageID: UUID?
        var liveMessageIDs: [UUID] = []
        var liveToolMessageIDs: [String: UUID] = [:]
        var receivedStreamEvent = false
        var streamedText = ""
        var currentAssistantText = ""
        var renderedAssistantText = ""
        var lastTextFlush = Date.distantPast
        var lastScrollFlush = Date.distantPast
        var liveToolEvents: [ToolUseEvent] = []
        var completed = false
        let minimumTextFlushInterval: TimeInterval = 1.0 / 30.0
        let minimumScrollFlushInterval: TimeInterval = 0.25

        func appendLiveAssistantMessage(text: String = "", toolEvents: [ToolUseEvent] = []) -> UUID {
            let message = ChatMessage(role: .assistant, text: text, toolEvents: toolEvents, isStreaming: true)
            messages.append(message)
            chatScrollRevision += 1
            liveMessageIDs.append(message.id)
            if assistantMessageID == nil {
                assistantMessageID = message.id
            }
            return message.id
        }

        func ensureAssistantTextMessage() -> UUID {
            if let currentAssistantTextMessageID {
                return currentAssistantTextMessageID
            }
            currentAssistantText = ""
            renderedAssistantText = ""
            let id = appendLiveAssistantMessage()
            currentAssistantTextMessageID = id
            return id
        }

        func flushAssistantText(force: Bool = false) -> Bool {
            guard let id = currentAssistantTextMessageID else { return false }
            guard renderedAssistantText != currentAssistantText else { return false }
            let now = Date()
            if !force && now.timeIntervalSince(lastTextFlush) < minimumTextFlushInterval {
                return false
            }
            renderedAssistantText = currentAssistantText
            lastTextFlush = now
            let shouldScroll = force || now.timeIntervalSince(lastScrollFlush) >= minimumScrollFlushInterval
            updateAssistantMessage(
                id: id,
                text: currentAssistantText,
                toolEvents: nil,
                isStreaming: true,
                scroll: shouldScroll
            )
            if shouldScroll {
                lastScrollFlush = now
            }
            return true
        }

        func appendOrUpdateToolActivity(_ event: ToolUseEvent) -> Bool {
            _ = flushAssistantText(force: true)
            let key = Self.toolEventKey(event)
            var nextEvent = event
            if let index = liveToolEvents.firstIndex(where: { Self.toolEventKey($0) == key }) {
                nextEvent = Self.mergedToolEvent(existing: liveToolEvents[index], incoming: event)
                liveToolEvents[index] = nextEvent
            } else {
                liveToolEvents.append(nextEvent)
                liveToolEvents = Array(liveToolEvents.suffix(10))
            }

            let messageID: UUID
            if let existingMessageID = liveToolMessageIDs[key] {
                messageID = existingMessageID
            } else if let textMessageID = currentAssistantTextMessageID, currentAssistantText.isEmpty {
                messageID = textMessageID
                currentAssistantTextMessageID = nil
                renderedAssistantText = ""
                liveToolMessageIDs[key] = textMessageID
            } else {
                currentAssistantTextMessageID = nil
                currentAssistantText = ""
                renderedAssistantText = ""
                messageID = appendLiveAssistantMessage()
                liveToolMessageIDs[key] = messageID
            }
            updateAssistantMessage(
                id: messageID,
                text: "",
                toolEvents: [nextEvent],
                isStreaming: true
            )
            return true
        }

        func appendCompletedToolActivity(_ event: ToolUseEvent) {
            let key = Self.toolEventKey(event)
            guard liveToolMessageIDs[key] == nil else { return }
            currentAssistantTextMessageID = nil
            currentAssistantText = ""
            renderedAssistantText = ""
            _ = appendLiveAssistantMessage(toolEvents: [event])
        }

        func finishLiveMessages() {
            _ = flushAssistantText(force: true)
            for id in liveMessageIDs {
                updateAssistantMessage(id: id, text: nil, toolEvents: nil, isStreaming: false)
            }
        }

        do {
            let episodeID = try await client.ensureWakeEpisode(
                personalModelID: snapshot.currentPersonalModelID,
                elephantID: snapshot.currentStateID,
                activeEpisodeID: activeEpisodeID
            )
            activeEpisodeID = episodeID

            currentAssistantTextMessageID = appendLiveAssistantMessage()

            streamLoop: for try await event in client.streamWakeLoop(text, episodeID: episodeID) {
                receivedStreamEvent = true
                switch event.type {
                case "assistant.delta":
                    _ = ensureAssistantTextMessage()
                    streamedText += event.textDelta
                    currentAssistantText += event.textDelta
                    if flushAssistantText() {
                        await Task.yield()
                    }
                case "tool.lifecycle":
                    if let toolEvent = event.toolEvent {
                        if appendOrUpdateToolActivity(toolEvent) {
                            await Task.yield()
                        }
                    }
                case "loop.started", "kernel.stage":
                    continue
                case "loop.completed":
                    if let reply = event.reply {
                        completed = true
                        if flushAssistantText(force: true) {
                            await Task.yield()
                        }
                        if streamedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            if !reply.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                if let currentAssistantTextMessageID {
                                    currentAssistantText = reply.text
                                    renderedAssistantText = reply.text
                                    updateAssistantMessage(
                                        id: currentAssistantTextMessageID,
                                        text: reply.text,
                                        toolEvents: nil,
                                        isStreaming: true
                                    )
                                } else {
                                    _ = appendLiveAssistantMessage(text: reply.text)
                                }
                            }
                        } else if let currentAssistantTextMessageID,
                                  !reply.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                                  reply.text.hasPrefix(currentAssistantText),
                                  reply.text.count > currentAssistantText.count {
                            currentAssistantText = reply.text
                            renderedAssistantText = ""
                            updateAssistantMessage(
                                id: currentAssistantTextMessageID,
                                text: currentAssistantText,
                                toolEvents: nil,
                                isStreaming: true
                            )
                        }
                        if liveToolEvents.isEmpty {
                            for toolEvent in reply.toolEvents {
                                appendCompletedToolActivity(toolEvent)
                            }
                        }
                        finishLiveMessages()
                    }
                    break streamLoop
                case "loop.failed":
                    completed = true
                    finishLiveMessages()
                    messages.append(ChatMessage(role: .assistant, text: chatLoopFailureMessage(detail: event.error)))
                    lastError = event.error
                    break streamLoop
                default:
                    continue
                }
            }

            if !completed {
                if streamedText.isEmpty, let id = assistantMessageID {
                    updateAssistantMessage(
                        id: id,
                        text: "The live connection ended before Elephant returned a reply.",
                        toolEvents: nil,
                        isStreaming: false
                    )
                }
                finishLiveMessages()
            }
        } catch {
            if let assistantMessageID, !receivedStreamEvent, !activeEpisodeID.isEmpty {
                let episodeID = activeEpisodeID
                do {
                    let reply = try await client.runWakeLoop(text, episodeID: episodeID)
                    let toolEvents = reply.toolEvents.isEmpty
                        ? ((try? await client.fetchToolUseEvents(episodeID: episodeID)) ?? [])
                        : reply.toolEvents
                    updateAssistantMessage(
                        id: assistantMessageID,
                        text: reply.text,
                        toolEvents: toolEvents,
                        isStreaming: false
                    )
                } catch {
                    updateAssistantMessage(
                        id: assistantMessageID,
                        text: chatLoopFailureMessage(error),
                        toolEvents: nil,
                        isStreaming: false
                    )
                    lastError = error.localizedDescription
                }
            } else if !receivedStreamEvent, !activeEpisodeID.isEmpty {
                let episodeID = activeEpisodeID
                do {
                    let reply = try await client.runWakeLoop(text, episodeID: episodeID)
                    messages.append(ChatMessage(role: .assistant, text: reply.text, toolEvents: reply.toolEvents))
                } catch {
                    messages.append(ChatMessage(role: .assistant, text: chatLoopFailureMessage(error)))
                    lastError = error.localizedDescription
                }
            } else if let assistantMessageID {
                finishLiveMessages()
                if streamedText.isEmpty {
                    updateAssistantMessage(
                        id: assistantMessageID,
                        text: "The live connection stopped before the reply finished.",
                        toolEvents: liveToolEvents,
                        isStreaming: false
                    )
                } else {
                    messages.append(ChatMessage(role: .assistant, text: "The live connection stopped before the reply finished."))
                }
                lastError = error.localizedDescription
            } else {
                messages.append(ChatMessage(role: .assistant, text: chatLoopFailureMessage(error)))
                lastError = error.localizedDescription
            }
        }
        isWakeRunning = false
    }

    func focusComposer() {
        composerFocusToken = UUID()
    }

    private func updateAssistantMessage(
        id: UUID,
        text: String?,
        toolEvents: [ToolUseEvent]?,
        isStreaming: Bool?,
        scroll: Bool = true
    ) {
        guard let index = messages.firstIndex(where: { $0.id == id }) else { return }
        if !scroll {
            objectWillChange.send()
        }
        if let text {
            messages[index].text = text
        }
        if let toolEvents {
            messages[index].toolEvents = toolEvents
        }
        if let isStreaming {
            messages[index].isStreaming = isStreaming
        }
        if scroll {
            chatScrollRevision += 1
        }
    }

    private func chatLoopFailureMessage(_ error: Error) -> String {
        chatLoopFailureMessage(detail: error.localizedDescription)
    }

    private func chatLoopFailureMessage(detail: String) -> String {
        let trimmed = detail.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return "I could not run the full chat loop. Check provider and Personal Model settings, then send again."
        }
        return "I could not run the full chat loop: \(trimmed)"
    }

    private static func toolEventSignature(_ events: [ToolUseEvent]) -> String {
        events
            .map { [$0.invocationID, $0.name, $0.status, $0.arguments, $0.result].joined(separator: "|") }
            .joined(separator: "\n")
    }

    private static func toolEventKey(_ event: ToolUseEvent) -> String {
        let invocationID = event.invocationID.trimmingCharacters(in: .whitespacesAndNewlines)
        if !invocationID.isEmpty {
            return invocationID
        }
        return [event.name, event.arguments].joined(separator: "|")
    }

    private static func mergedToolEvent(existing: ToolUseEvent, incoming: ToolUseEvent) -> ToolUseEvent {
        ToolUseEvent(
            id: existing.id,
            invocationID: incoming.invocationID.isEmpty ? existing.invocationID : incoming.invocationID,
            name: incoming.name == "tool" ? existing.name : incoming.name,
            status: incoming.status.isEmpty ? existing.status : incoming.status,
            arguments: incoming.arguments.isEmpty ? existing.arguments : incoming.arguments,
            result: incoming.result.isEmpty ? existing.result : incoming.result
        )
    }

    private func resetOnboardingDrafts() {
        onboardingName = "Elephant"
        onboardingPurpose = "Be warm, precise, curious, and direct. Protect continuity, ask useful questions, and keep the user's Personal Model correctable."
        onboardingPreferredName = ""
        onboardingOccupation = ""
        onboardingSchool = ""
        onboardingCity = ""
        onboardingGender = ""
        onboardingBirthDate = ""
        onboardingMBTI = ""
        onboardingHobbies = ""
        onboardingDream = ""
        onboardingCreativeHobby = ""
        onboardingMediaHobby = ""
        onboardingMovementHobby = ""
        onboardingSafetyBoundaries = ""
        onboardingFoodAllergies = ""
        onboardingMedicationAllergies = ""
        onboardingChronicConditions = ""
        onboardingPrivateSafetyNote = ""
        onboardingFirstLanguage = "en"
        onboardingBlogURL = ""
        onboardingLinkedInURL = ""
        onboardingTwitterURL = ""
        onboardingInnerLandscape = ""
        onboardingValueAnchor = ""
        onboardingPressurePattern = ""
        onboardingRecoveryStyle = ""
        onboardingDecisionCompass = ""
        onboardingProviderID = "openai-compatible"
        onboardingBaseURL = ""
        onboardingModelID = ""
        onboardingAPIKey = ""
        onboardingContextWindow = ""
        onboardingStep = 0
        onboardingFinalizationStarted = false
        onboardingFinalizationComplete = false
        onboardingFinalizationFailed = false
        onboardingFinalizationStatus = ""
        onboardingInitReflectJobID = ""
        onboardingCreatedStateID = ""
    }

    private func resetLocalMacStateForFreshInstall() throws {
        let avatarPaths = [userAvatarPath] + herdAvatarPaths.values.map { $0 }
        try removeLocalAvatarFilesForReset(paths: avatarPaths)

        wakeDraft = ""
        providerTestResult = ""
        gatewayActionResult = ""
        gatewaySecretDrafts.removeAll()
        gatewayQR = GatewayQRState()
        cronActionResult = ""
        diaryActionResult = ""
        factActionResult = ""
        configActionResult = ""
        isReflecting = false
        isWakeRunning = false
        isSleepDisplayPresented = false
        sleepDisplayReason = "manual"
        sleepIdleMinutes = Self.defaultSleepIdleMinutes
        hiddenEpisodeIDs.removeAll()
        userAvatarPath = ""
        herdAvatarPaths.removeAll()

        let defaults = UserDefaults.standard
        [
            Self.onboardingCompleteKey,
            Self.userAvatarPathKey,
            Self.herdAvatarPathsKey,
            Self.hiddenEpisodeIDsKey,
            Self.sleepIdleMinutesKey
        ].forEach { defaults.removeObject(forKey: $0) }
    }

    private func removeLocalAvatarFilesForReset(paths: [String]) throws {
        let fileManager = FileManager.default
        for path in paths {
            let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }
            let url = URL(fileURLWithPath: trimmed)
            if fileManager.fileExists(atPath: url.path) {
                try? fileManager.removeItem(at: url)
            }
        }

        let root = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        let directory = root.appendingPathComponent("Elephant Agent", isDirectory: true)
        let userAvatars = (try? fileManager.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? []
        for file in userAvatars where file.lastPathComponent.hasPrefix("user-avatar.") {
            try fileManager.removeItem(at: file)
        }

        let herdAvatarDirectory = directory.appendingPathComponent("Herd Avatars", isDirectory: true)
        if fileManager.fileExists(atPath: herdAvatarDirectory.path) {
            try fileManager.removeItem(at: herdAvatarDirectory)
        }
    }

    private func startSleepIdleMonitorIfNeeded() {
        guard sleepIdleMonitorTask == nil else { return }
        sleepIdleMonitorTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 5_000_000_000)
                guard let self else { return }
                self.evaluateSleepIdleTimeout()
            }
        }
    }

    private func evaluateSleepIdleTimeout() {
        guard !isSleepDisplayPresented,
              !showingOnboarding,
              !isWakeRunning,
              sleepIdleMinutes > 0 else { return }

        let localIdleSeconds = Date().timeIntervalSince(lastInteractionDate)
        let systemIdleSeconds = Self.systemIdleSeconds()
        let observedIdleSeconds = min(localIdleSeconds, systemIdleSeconds)
        if observedIdleSeconds >= TimeInterval(sleepIdleMinutes * 60) {
            beginSleepDisplay(reason: "idle")
        }
    }

    private static func persistedSleepIdleMinutes() -> Int {
        let value = UserDefaults.standard.integer(forKey: sleepIdleMinutesKey)
        return value > 0 ? min(120, max(1, value)) : defaultSleepIdleMinutes
    }

    private static func systemIdleSeconds() -> TimeInterval {
        let eventTypes: [CGEventType] = [
            .keyDown,
            .leftMouseDown,
            .rightMouseDown,
            .otherMouseDown,
            .mouseMoved,
            .scrollWheel,
            .leftMouseDragged,
            .rightMouseDragged,
            .otherMouseDragged
        ]
        let intervals = eventTypes.map {
            CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: $0)
        }
        return intervals.min() ?? 0
    }

    func shutdownSync() {
        sleepIdleMonitorTask?.cancel()
        sleepIdleMonitorTask = nil
        runner.stop()
    }
}
