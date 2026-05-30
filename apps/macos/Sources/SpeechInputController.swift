import AVFoundation
import AVFAudio
import Foundation
import Speech

private final class SpeechAudioTapSink {
    private let lock = NSLock()
    private var acceptingBuffers = true
    private let file: AVAudioFile?
    private let recognitionRequest: SFSpeechAudioBufferRecognitionRequest?

    init(
        file: AVAudioFile? = nil,
        recognitionRequest: SFSpeechAudioBufferRecognitionRequest? = nil
    ) {
        self.file = file
        self.recognitionRequest = recognitionRequest
    }

    func accept(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        defer { lock.unlock() }
        guard acceptingBuffers else { return }
        if let file {
            try? file.write(from: buffer)
        }
        recognitionRequest?.append(buffer)
    }

    func close() {
        lock.lock()
        acceptingBuffers = false
        lock.unlock()
    }
}

// System permission callbacks can arrive from different queues; the lock makes delivery one-shot.
private final class OneShotPermissionCompletion: @unchecked Sendable {
    private let lock = NSLock()
    private var didFinish = false

    func finish(_ action: () -> Void) {
        lock.lock()
        guard !didFinish else {
            lock.unlock()
            return
        }
        didFinish = true
        lock.unlock()
        action()
    }

    func deliver(_ allowed: Bool, completion: @escaping (Bool) -> Void) {
        finish {
            Task { @MainActor in completion(allowed) }
        }
    }
}

private final class SpeechRecognitionTaskBox: @unchecked Sendable {
    private let lock = NSLock()
    private var task: SFSpeechRecognitionTask?

    func set(_ task: SFSpeechRecognitionTask) {
        lock.lock()
        self.task = task
        lock.unlock()
    }

    func cancel() {
        lock.lock()
        let activeTask = task
        task = nil
        lock.unlock()
        activeTask?.cancel()
    }
}

@MainActor
final class SpeechInputController: NSObject, ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var isTranscribing = false
    @Published private(set) var isPreparingCapture = false
    @Published private(set) var statusText = ""
    @Published private(set) var recordingStartedAt: Date?
    @Published private(set) var capturedDuration: TimeInterval = 0
    @Published private(set) var recognizedText = ""

    private enum ActiveMode {
        case apple(locale: Locale, fallbackLocales: [Locale], statusNotice: String?)
        case funASR(previewLocale: Locale?, statusNotice: String?)
    }

    private enum PermissionRequestKind {
        case microphone
        case speechRecognition
    }

    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var recognizer: SFSpeechRecognizer?
    private var audioTapSink: SpeechAudioTapSink?
    private var recordingURL: URL?
    private var convertedRecordingURL: URL?
    private var transcriptionTask: Task<Void, Never>?
    private var permissionTimeoutTask: Task<Void, Never>?
    private var captureGeneration = 0
    private var baseText = ""
    private var onText: ((String) -> Void)?
    private var activeMode: ActiveMode = .apple(locale: Locale(identifier: "en-US"), fallbackLocales: [], statusNotice: nil)
    private var activeLanguage: AppLanguage = .en
    private static let localTranscriptionTimeout: TimeInterval = 60
    private static let appleFallbackTranscriptionTimeout: TimeInterval = 24
    private static let chineseAppleSpeechLocaleIdentifiers = ["zh-CN", "zh_CN", "zh-Hans-CN", "zh_Hans_CN", "cmn-Hans-CN"]
    private static let englishAppleSpeechLocaleIdentifiers = ["en-US", "en_US", "en"]

    func toggle(
        startingWith text: String,
        language: AppLanguage,
        recognitionEngine: SpeechRecognitionEngine,
        onText: @escaping (String) -> Void
    ) {
        if isRecording {
            stop()
        } else {
            start(startingWith: text, language: language, recognitionEngine: recognitionEngine, onText: onText)
        }
    }

    func start(
        startingWith text: String,
        language: AppLanguage,
        recognitionEngine: SpeechRecognitionEngine,
        onText: @escaping (String) -> Void
    ) {
        guard !isRecording && !isTranscribing && !isPreparingCapture else { return }
        captureGeneration += 1
        let generation = captureGeneration
        permissionTimeoutTask?.cancel()
        isPreparingCapture = true
        baseText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        self.onText = onText
        activeLanguage = language
        recognizedText = ""
        capturedDuration = 0
        recordingStartedAt = nil
        cleanupRecordingFiles()
        activeMode = Self.resolvedMode(language: language, recognitionEngine: recognitionEngine)
        statusText = Self.localizedStatus(language, en: "Requesting microphone access...", zh: "正在请求麦克风权限...")
        guard Self.hasAudioInputDevice() else {
            finishCaptureSetupFailure(Self.localizedStatus(language, en: "No microphone input device was found.", zh: "没有找到可用的麦克风输入设备。"))
            return
        }

        schedulePermissionTimeout(generation: generation, language: language)
        requestMicrophoneAccess(generation: generation) { [weak self] allowed in
            guard let self else { return }
            guard self.isActiveCapture(generation) else { return }
            guard allowed else {
                self.finishCaptureSetupFailure(Self.localizedStatus(self.activeLanguage, en: "Microphone access is disabled.", zh: "麦克风权限未开启。"))
                return
            }

            switch self.activeMode {
            case .funASR(let previewLocale, _):
                self.startLocalRecording(
                    previewLocale: previewLocale.flatMap { self.authorizedSpeechPreviewLocale($0) },
                    generation: generation
                )
            case .apple(let locale, let fallbackLocales, let statusNotice):
                self.statusText = Self.localizedStatus(
                    self.activeLanguage,
                    en: "Requesting speech recognition access...",
                    zh: "正在请求语音识别权限..."
                )
                self.schedulePermissionTimeout(generation: generation, language: self.activeLanguage, kind: .speechRecognition)
                SFSpeechRecognizer.requestAuthorization { status in
                    Task { @MainActor [weak self] in
                        guard let self else { return }
                        guard self.isActiveCapture(generation) else { return }
                        guard status == .authorized else {
                            self.finishCaptureSetupFailure(Self.localizedStatus(self.activeLanguage, en: "Speech recognition is not authorized.", zh: "语音识别权限未开启。"))
                            return
                        }
                        self.startAppleRecording(
                            locale: locale,
                            fallbackLocales: fallbackLocales,
                            statusNotice: statusNotice,
                            generation: generation
                        )
                    }
                }
            }
        }
    }

    func stop() {
        guard isRecording || audioEngine.isRunning || isPreparingCapture else { return }
        if isPreparingCapture && !isRecording && !audioEngine.isRunning {
            permissionTimeoutTask?.cancel()
            permissionTimeoutTask = nil
            onText = nil
            captureGeneration += 1
            isPreparingCapture = false
            recordingStartedAt = nil
            statusText = Self.localizedStatus(activeLanguage, en: "Voice input stopped.", zh: "语音输入已停止。")
            return
        }
        updateCapturedDuration()
        let mode = activeMode
        let generation = captureGeneration
        stopAudioEngine()
        isPreparingCapture = false
        isRecording = false
        recordingStartedAt = nil

        switch mode {
        case .funASR:
            stopApplePreviewRecognition()
            startFunASRTranscription(generation: generation)
        case .apple(_, let fallbackLocales, _):
            recognitionRequest?.endAudio()
            recognitionTask?.finish()
            recognitionRequest = nil
            let hasRecognizedText = !recognizedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            if !hasRecognizedText, recordingURL != nil, !fallbackLocales.isEmpty {
                startAppleFallbackTranscription(locales: fallbackLocales, generation: generation)
            } else {
                statusText = hasRecognizedText
                    ? Self.localizedStatus(activeLanguage, en: "Voice input captured.", zh: "已捕捉到语音。")
                    : Self.localizedStatus(activeLanguage, en: "Voice input stopped.", zh: "语音输入已停止。")
            }
        }
    }

    func resetCapture() {
        captureGeneration += 1
        permissionTimeoutTask?.cancel()
        permissionTimeoutTask = nil
        transcriptionTask?.cancel()
        transcriptionTask = nil
        if isRecording || audioEngine.isRunning {
            stopAudioEngine()
        }
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
        recognizer = nil
        onText = nil
        baseText = ""
        isPreparingCapture = false
        isRecording = false
        isTranscribing = false
        recognizedText = ""
        capturedDuration = 0
        recordingStartedAt = nil
        statusText = ""
        cleanupRecordingFiles()
    }

    static func installFunASRRuntime() async throws -> String {
        try await MacVoiceRuntime.installFunASRRuntime()
    }

    static var funASRInstalled: Bool {
        MacVoiceRuntime.isFunASRInstalled()
    }

    private static func resolvedMode(
        language: AppLanguage,
        recognitionEngine: SpeechRecognitionEngine
    ) -> ActiveMode {
        switch recognitionEngine {
        case .automatic:
            return automaticMode(language: language)
        case .funASRLocal:
            return localChineseMode(language: language)
        case .appleSpeech:
            let locale = appleSpeechLocale(for: language)
            return .apple(
                locale: locale,
                fallbackLocales: alternateAppleSpeechFallbackLocales(for: locale),
                statusNotice: nil
            )
        }
    }

    private static func automaticMode(language: AppLanguage) -> ActiveMode {
        if MacVoiceRuntime.isFunASRInstalled() {
            return .funASR(
                previewLocale: automaticAppleSpeechPrimaryLocale(for: language),
                statusNotice: localChineseRecordingNotice(language)
            )
        }
        let locale = automaticAppleSpeechPrimaryLocale(for: language)
        return .apple(
            locale: locale,
            fallbackLocales: alternateAppleSpeechFallbackLocales(for: locale),
            statusNotice: nil
        )
    }

    private static func localChineseMode(language: AppLanguage) -> ActiveMode {
        if MacVoiceRuntime.isFunASRInstalled() {
            return .funASR(
                previewLocale: Locale(identifier: "zh-CN"),
                statusNotice: localChineseRecordingNotice(language)
            )
        }
        let locale = appleSpeechLocale(for: .zh)
        return .apple(
            locale: locale,
            fallbackLocales: [],
            statusNotice: localizedStatus(language, en: "Local Chinese recognition is not ready; using system dictation for now.", zh: "本地中文识别尚未就绪，暂时使用系统听写。")
        )
    }

    private static func appleSpeechLocale(for language: AppLanguage) -> Locale {
        language == .zh ? preferredAppleSpeechLocale(for: chineseAppleSpeechLocaleIdentifiers) : preferredAppleSpeechLocale(for: englishAppleSpeechLocaleIdentifiers)
    }

    private static func automaticAppleSpeechPrimaryLocale(for language: AppLanguage) -> Locale {
        if language == .zh || preferredSystemLanguageIsChinese() {
            return preferredAppleSpeechLocale(for: chineseAppleSpeechLocaleIdentifiers)
        }
        return preferredAppleSpeechLocale(for: englishAppleSpeechLocaleIdentifiers)
    }

    private static func alternateAppleSpeechFallbackLocales(for primary: Locale) -> [Locale] {
        let primaryIdentifier = normalizedLocaleIdentifier(primary.identifier)
        let candidates = [
            preferredAppleSpeechLocale(for: chineseAppleSpeechLocaleIdentifiers),
            preferredAppleSpeechLocale(for: englishAppleSpeechLocaleIdentifiers)
        ]
        return candidates.filter { normalizedLocaleIdentifier($0.identifier) != primaryIdentifier }
    }

    private static func preferredSystemLanguageIsChinese() -> Bool {
        Locale.preferredLanguages.contains { identifier in
            AppLanguage(code: identifier) == .zh
        }
    }

    private static func preferredAppleSpeechLocale(for identifiers: [String]) -> Locale {
        let supportedLocales = SFSpeechRecognizer.supportedLocales()
        for identifier in identifiers {
            let normalized = normalizedLocaleIdentifier(identifier)
            if let locale = supportedLocales.first(where: { normalizedLocaleIdentifier($0.identifier) == normalized }) {
                return locale
            }
        }
        for identifier in identifiers {
            let languagePrefix = normalizedLocaleIdentifier(identifier).prefix(2)
            if let locale = supportedLocales.first(where: { normalizedLocaleIdentifier($0.identifier).hasPrefix(languagePrefix) }) {
                return locale
            }
        }
        return Locale(identifier: identifiers[0])
    }

    nonisolated private static func normalizedLocaleIdentifier(_ identifier: String) -> String {
        identifier.replacingOccurrences(of: "-", with: "_").lowercased()
    }

    private static func localChineseRecordingNotice(_ language: AppLanguage) -> String {
        localizedStatus(
            language,
            en: "Listening. Press Stop to transcribe Chinese.",
            zh: "正在听。说完后点停止开始中文识别。"
        )
    }

    private func requestMicrophoneAccess(generation: Int, _ completion: @escaping (Bool) -> Void) {
        let completionGate = OneShotPermissionCompletion()
        requestCaptureDeviceMicrophoneAccess(
            generation: generation,
            completionGate: completionGate,
            completion: { [weak self] allowed in
                guard let self else { return }
                guard self.isActiveCapture(generation) else { return }
                completion(allowed && self.audioApplicationRecordPermissionAllowsCapture())
            }
        )
    }

    private func audioApplicationRecordPermissionAllowsCapture() -> Bool {
        if #available(macOS 14.0, *) {
            switch AVAudioApplication.shared.recordPermission {
            case .denied:
                return false
            case .granted, .undetermined:
                return true
            @unknown default:
                return false
            }
        }
        return true
    }

    private func requestCaptureDeviceMicrophoneAccess(
        generation: Int,
        completionGate: OneShotPermissionCompletion,
        completion: @escaping (Bool) -> Void
    ) {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            completionGate.deliver(true, completion: completion)
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { allowed in
                Task { @MainActor [weak self] in
                    guard let self, self.isActiveCapture(generation) else { return }
                    completionGate.deliver(allowed, completion: completion)
                }
            }
        default:
            completionGate.deliver(false, completion: completion)
        }
    }

    private func schedulePermissionTimeout(
        generation: Int,
        language: AppLanguage,
        kind: PermissionRequestKind = .microphone
    ) {
        permissionTimeoutTask?.cancel()
        permissionTimeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            await MainActor.run {
                guard let self, !Task.isCancelled else { return }
                guard self.isActiveCapture(generation), !self.isRecording, !self.isTranscribing else { return }
                let lowerStatus = self.statusText.lowercased()
                guard lowerStatus.contains("requesting") || self.statusText.contains("请求") else { return }
                self.statusText = Self.permissionTimeoutMessage(kind: kind, language: language)
                self.isPreparingCapture = false
                self.onText = nil
                self.captureGeneration += 1
                self.permissionTimeoutTask = nil
            }
        }
    }

    private static func permissionTimeoutMessage(kind: PermissionRequestKind, language: AppLanguage) -> String {
        switch (kind, language) {
        case (.microphone, .zh):
            return "麦克风权限请求没有完成。如果没有出现系统弹窗，请打开“系统设置 > 隐私与安全性 > 麦克风”，允许 Elephant Agent 后重试。"
        case (.microphone, _):
            return "Microphone permission did not finish. If no system prompt appeared, open System Settings > Privacy & Security > Microphone, allow Elephant Agent, then try again."
        case (.speechRecognition, .zh):
            return "语音识别权限请求没有完成。如果没有出现系统弹窗，请打开“系统设置 > 隐私与安全性 > 语音识别”，允许 Elephant Agent 后重试。"
        case (.speechRecognition, _):
            return "Speech recognition permission did not finish. If no system prompt appeared, open System Settings > Privacy & Security > Speech Recognition, allow Elephant Agent, then try again."
        }
    }

    private func isActiveCapture(_ generation: Int) -> Bool {
        captureGeneration == generation && onText != nil
    }

    private func finishCaptureSetupFailure(_ message: String) {
        permissionTimeoutTask?.cancel()
        permissionTimeoutTask = nil
        statusText = message
        isPreparingCapture = false
        onText = nil
        captureGeneration += 1
    }

    private func authorizedSpeechPreviewLocale(_ locale: Locale) -> Locale? {
        switch SFSpeechRecognizer.authorizationStatus() {
        case .authorized:
            return locale
        default:
            return nil
        }
    }

    private func startAppleRecording(
        locale: Locale,
        fallbackLocales: [Locale],
        statusNotice: String?,
        generation: Int
    ) {
        guard isActiveCapture(generation) else { return }
        recognizer = SFSpeechRecognizer(locale: locale)
        guard let recognizer, recognizer.isAvailable else {
            self.recognizer = nil
            if let fallbackLocale = fallbackLocales.first {
                startAppleRecording(
                    locale: fallbackLocale,
                    fallbackLocales: Array(fallbackLocales.dropFirst()),
                    statusNotice: statusNotice,
                    generation: generation
                )
                return
            }
            finishCaptureSetupFailure(Self.localizedStatus(activeLanguage, en: "Speech recognizer is unavailable.", zh: "语音识别暂不可用。"))
            return
        }

        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest else {
            finishCaptureSetupFailure(Self.localizedStatus(activeLanguage, en: "Could not create speech request.", zh: "无法创建语音识别请求。"))
            return
        }
        recognitionRequest.shouldReportPartialResults = true

        let inputNode = audioEngine.inputNode
        inputNode.removeTap(onBus: 0)
        let format: AVAudioFormat
        do {
            format = try validInputFormat(from: inputNode)
        } catch {
            recognitionRequest.endAudio()
            self.recognitionRequest = nil
            self.recognizer = nil
            finishCaptureSetupFailure(Self.localizedStatus(activeLanguage, en: "Could not start microphone: \(error.localizedDescription)", zh: "无法启动麦克风：\(error.localizedDescription)"))
            return
        }
        let fallbackRecordingFile: AVAudioFile?
        do {
            let recording = try makeRecordingFile(inputFormat: format)
            recordingURL = recording.0
            fallbackRecordingFile = recording.1
        } catch {
            recordingURL = nil
            fallbackRecordingFile = nil
        }
        let sink = SpeechAudioTapSink(file: fallbackRecordingFile, recognitionRequest: recognitionRequest)
        audioTapSink = sink
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            sink.accept(buffer)
        }

        guard isActiveCapture(generation) else {
            stopAudioEngine()
            recognitionRequest.endAudio()
            self.recognitionRequest = nil
            self.recognizer = nil
            return
        }
        do {
            audioEngine.prepare()
            try audioEngine.start()
        } catch {
            stopAudioEngine()
            recognitionRequest.endAudio()
            self.recognitionRequest = nil
            self.recognizer = nil
            finishCaptureSetupFailure(Self.localizedStatus(activeLanguage, en: "Could not start microphone: \(error.localizedDescription)", zh: "无法启动麦克风：\(error.localizedDescription)"))
            return
        }

        permissionTimeoutTask?.cancel()
        permissionTimeoutTask = nil
        isPreparingCapture = false
        isRecording = true
        recordingStartedAt = Date()
        capturedDuration = 0
        statusText = statusNotice ?? Self.localizedStatus(activeLanguage, en: "Listening...", zh: "正在听...")
        recognitionTask = recognizer.recognitionTask(with: recognitionRequest) { [weak self] result, error in
            Task { @MainActor [weak self] in
                guard let self else { return }
                guard self.isActiveCapture(generation) else { return }
                if let result {
                    let spoken = result.bestTranscription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
                    self.applyRecognizedText(spoken)
                    self.statusText = result.isFinal
                        ? Self.localizedStatus(self.activeLanguage, en: "Voice input captured.", zh: "已捕捉到语音。")
                        : Self.localizedStatus(self.activeLanguage, en: "Listening...", zh: "正在听...")
                }

                if error != nil || result?.isFinal == true {
                    self.finishAppleRecognition(generation: generation)
                }
            }
        }
    }

    private func startLocalRecording(previewLocale: Locale?, generation: Int) {
        guard isActiveCapture(generation) else { return }
        let inputNode = audioEngine.inputNode
        inputNode.removeTap(onBus: 0)
        let format: AVAudioFormat
        do {
            format = try validInputFormat(from: inputNode)
        } catch {
            finishCaptureSetupFailure(Self.localizedStatus(activeLanguage, en: "Could not start microphone: \(error.localizedDescription)", zh: "无法启动麦克风：\(error.localizedDescription)"))
            return
        }

        let file: AVAudioFile
        let url: URL
        do {
            (url, file) = try makeRecordingFile(inputFormat: format)
        } catch {
            finishCaptureSetupFailure(Self.localizedStatus(activeLanguage, en: "Could not prepare local recording: \(error.localizedDescription)", zh: "无法准备本地录音：\(error.localizedDescription)"))
            return
        }
        recordingURL = url
        let previewRequest = previewLocale.flatMap { startApplePreviewRecognition(locale: $0, generation: generation) }

        let sink = SpeechAudioTapSink(file: file, recognitionRequest: previewRequest)
        audioTapSink = sink
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            sink.accept(buffer)
        }

        guard isActiveCapture(generation) else {
            stopAudioEngine()
            previewRequest?.endAudio()
            return
        }
        do {
            audioEngine.prepare()
            try audioEngine.start()
        } catch {
            stopAudioEngine()
            stopApplePreviewRecognition()
            finishCaptureSetupFailure(Self.localizedStatus(activeLanguage, en: "Could not start microphone: \(error.localizedDescription)", zh: "无法启动麦克风：\(error.localizedDescription)"))
            return
        }

        permissionTimeoutTask?.cancel()
        permissionTimeoutTask = nil
        isPreparingCapture = false
        isRecording = true
        recordingStartedAt = Date()
        capturedDuration = 0
        statusText = recordingStatusText()
    }

    private func startApplePreviewRecognition(locale: Locale, generation: Int) -> SFSpeechAudioBufferRecognitionRequest? {
        guard isActiveCapture(generation) else { return nil }
        recognizer = SFSpeechRecognizer(locale: locale)
        guard let recognizer, recognizer.isAvailable else {
            recognizer = nil
            return nil
        }

        recognitionTask?.cancel()
        recognitionTask = nil
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        recognitionRequest = request
        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor [weak self] in
                guard let self else { return }
                guard self.isActiveCapture(generation) else { return }
                if let result {
                    let spoken = result.bestTranscription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
                    if !spoken.isEmpty {
                        self.applyRecognizedText(spoken)
                    }
                    if self.isRecording {
                        self.statusText = self.recordingStatusText()
                    }
                }

                if error != nil || result?.isFinal == true {
                    self.clearAppleRecognitionReferences()
                }
            }
        }
        return request
    }

    private func startFunASRTranscription(generation: Int) {
        guard isActiveCapture(generation) else { return }
        guard let recordingURL else {
            statusText = Self.localizedStatus(activeLanguage, en: "No local recording was captured.", zh: "没有捕捉到本地录音。")
            return
        }
        isTranscribing = true
        statusText = recognizedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? Self.localizedStatus(activeLanguage, en: "Recognizing Chinese...", zh: "正在识别中文...")
            : Self.localizedStatus(activeLanguage, en: "Improving with local Chinese recognition...", zh: "正在用本地中文识别优化...")
        transcriptionTask?.cancel()
        transcriptionTask = Task { [weak self] in
            do {
                let wavURL = try await Self.convertToSixteenKilohertzWAV(recordingURL)
                let text = try await MacVoiceRuntime.transcribeChineseAudio(
                    inputURL: wavURL,
                    timeout: Self.localTranscriptionTimeout
                )
                await MainActor.run {
                    guard let self, !Task.isCancelled else { return }
                    guard self.isActiveCapture(generation) else { return }
                    self.convertedRecordingURL = wavURL
                    self.applyRecognizedText(text)
                    self.statusText = Self.localizedStatus(self.activeLanguage, en: "Voice input captured.", zh: "已捕捉到语音。")
                    self.isTranscribing = false
                }
            } catch {
                await MainActor.run {
                    guard let self, !Task.isCancelled else { return }
                    guard self.isActiveCapture(generation) else { return }
                    let draft = self.recognizedText.trimmingCharacters(in: .whitespacesAndNewlines)
                    self.statusText = draft.isEmpty
                        ? Self.localizedStatus(self.activeLanguage, en: "Chinese recognition failed: \(error.localizedDescription)", zh: "中文识别失败：\(error.localizedDescription)")
                        : Self.localizedStatus(self.activeLanguage, en: "Local recognition was slow; kept the live draft.", zh: "本地识别较慢，已保留实时草稿。")
                    self.isTranscribing = false
                }
            }
        }
    }

    private func startAppleFallbackTranscription(locales: [Locale], generation: Int) {
        guard isActiveCapture(generation) else { return }
        guard let recordingURL else {
            statusText = Self.localizedStatus(activeLanguage, en: "No voice recording was captured.", zh: "没有捕捉到语音录音。")
            return
        }
        let fallbackLocales = Self.uniqueLocales(locales)
        guard !fallbackLocales.isEmpty else {
            statusText = Self.localizedStatus(activeLanguage, en: "No speech was recognized.", zh: "没有识别到语音。")
            return
        }
        isTranscribing = true
        statusText = Self.localizedStatus(activeLanguage, en: "Checking alternate speech language...", zh: "正在尝试备用语音语言...")
        transcriptionTask?.cancel()
        transcriptionTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 450_000_000)
            let shouldContinue = await MainActor.run {
                guard let self, self.isActiveCapture(generation), !Task.isCancelled else { return false }
                return self.recognizedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            }
            guard shouldContinue else {
                await MainActor.run { [weak self] in
                    guard let self, self.isActiveCapture(generation) else { return }
                    self.isTranscribing = false
                }
                return
            }

            for locale in fallbackLocales {
                guard !Task.isCancelled else { return }
                do {
                    let text = try await Self.recognizeRecordedAudio(
                        recordingURL,
                        locale: locale,
                        timeout: Self.appleFallbackTranscriptionTimeout
                    )
                    let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !trimmed.isEmpty else { continue }
                    await MainActor.run {
                        guard let self, self.isActiveCapture(generation), !Task.isCancelled else { return }
                        self.applyRecognizedText(trimmed)
                        self.statusText = Self.localizedStatus(self.activeLanguage, en: "Voice input captured.", zh: "已捕捉到语音。")
                        self.isTranscribing = false
                    }
                    return
                } catch {
                    continue
                }
            }

            await MainActor.run {
                guard let self, self.isActiveCapture(generation), !Task.isCancelled else { return }
                self.statusText = Self.localizedStatus(
                    self.activeLanguage,
                    en: "No speech was recognized. Try Local Chinese in Voice settings if you mainly speak Chinese.",
                    zh: "没有识别到语音。如果主要说中文，请在语音设置里启用本地中文识别。"
                )
                self.isTranscribing = false
            }
        }
    }

    private func finishAppleRecognition(generation: Int) {
        guard isActiveCapture(generation) else { return }
        updateCapturedDuration()
        if audioEngine.isRunning {
            stopAudioEngine()
        }
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask = nil
        recognizer = nil
        isPreparingCapture = false
        isRecording = false
        recordingStartedAt = nil
    }

    private func stopApplePreviewRecognition() {
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        clearAppleRecognitionReferences()
    }

    private func clearAppleRecognitionReferences() {
        recognitionRequest = nil
        recognitionTask = nil
        recognizer = nil
    }

    private func stopAudioEngine() {
        audioTapSink?.close()
        audioTapSink = nil
        if audioEngine.isRunning {
            audioEngine.stop()
        }
        audioEngine.inputNode.removeTap(onBus: 0)
    }

    private func updateCapturedDuration() {
        if let recordingStartedAt {
            capturedDuration = max(capturedDuration, Date().timeIntervalSince(recordingStartedAt))
        }
    }

    private func applyRecognizedText(_ spoken: String) {
        let trimmed = spoken.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let onText else { return }
        recognizedText = trimmed
        let combined = [baseText, trimmed].filter { !$0.isEmpty }.joined(separator: " ")
        onText(combined)
    }

    private func recordingStatusText() -> String {
        switch activeMode {
        case .funASR(_, let statusNotice):
            return statusNotice ?? Self.localizedStatus(activeLanguage, en: "Listening...", zh: "正在听...")
        case .apple(_, _, let statusNotice):
            return statusNotice ?? Self.localizedStatus(activeLanguage, en: "Listening...", zh: "正在听...")
        }
    }

    private static func localizedStatus(_ language: AppLanguage, en: String, zh: String) -> String {
        language == .zh ? zh : en
    }

    private static func hasAudioInputDevice() -> Bool {
        AVCaptureDevice.default(for: .audio) != nil
    }

    private func validInputFormat(from inputNode: AVAudioInputNode) throws -> AVAudioFormat {
        let format = inputNode.outputFormat(forBus: 0)
        guard format.sampleRate.isFinite, format.sampleRate > 0, format.channelCount > 0 else {
            throw MacVoiceRuntimeError.invalidOutput(Self.localizedStatus(
                activeLanguage,
                en: "The current microphone input format is not usable.",
                zh: "当前麦克风输入格式不可用。"
            ))
        }
        return format
    }

    private func makeRecordingFile(inputFormat: AVAudioFormat) throws -> (URL, AVAudioFile) {
        let url = MacVoiceRuntime.temporaryURL(prefix: "elephant-voice-input", extension: "caf")
        let file = try AVAudioFile(forWriting: url, settings: inputFormat.settings)
        return (url, file)
    }

    private func cleanupRecordingFiles() {
        if let recordingURL {
            try? FileManager.default.removeItem(at: recordingURL)
        }
        if let convertedRecordingURL {
            try? FileManager.default.removeItem(at: convertedRecordingURL)
        }
        recordingURL = nil
        convertedRecordingURL = nil
    }

    nonisolated private static func convertToSixteenKilohertzWAV(_ input: URL) async throws -> URL {
        try await Task.detached(priority: .userInitiated) {
            let output = MacVoiceRuntime.temporaryURL(prefix: "elephant-voice-input-16k", extension: "wav")
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/afconvert")
            process.arguments = [
                "-f", "WAVE",
                "-d", "LEI16@16000",
                input.path,
                output.path
            ]
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe
            try process.run()
            process.waitUntilExit()
            guard process.terminationStatus == 0, FileManager.default.fileExists(atPath: output.path) else {
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let detail = String(data: data, encoding: .utf8) ?? "afconvert failed."
                throw MacVoiceRuntimeError.processFailed(detail.trimmingCharacters(in: .whitespacesAndNewlines))
            }
            return output
        }.value
    }

    nonisolated private static func recognizeRecordedAudio(
        _ input: URL,
        locale: Locale,
        timeout: TimeInterval
    ) async throws -> String {
        let taskBox = SpeechRecognitionTaskBox()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                guard SFSpeechRecognizer.authorizationStatus() == .authorized else {
                    continuation.resume(throwing: MacVoiceRuntimeError.processFailed("Speech recognition is not authorized."))
                    return
                }
                guard let recognizer = SFSpeechRecognizer(locale: locale), recognizer.isAvailable else {
                    continuation.resume(throwing: MacVoiceRuntimeError.processFailed("Speech recognizer is unavailable."))
                    return
                }
                let completionGate = OneShotPermissionCompletion()
                let request = SFSpeechURLRecognitionRequest(url: input)
                request.shouldReportPartialResults = false
                let task = recognizer.recognitionTask(with: request) { result, error in
                    if let result, result.isFinal {
                        let text = result.bestTranscription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
                        completionGate.finish {
                            continuation.resume(returning: text)
                        }
                        return
                    }
                    if let error {
                        completionGate.finish {
                            continuation.resume(throwing: error)
                        }
                    }
                }
                taskBox.set(task)
                DispatchQueue.main.asyncAfter(deadline: .now() + timeout) {
                    completionGate.finish {
                        taskBox.cancel()
                        continuation.resume(throwing: MacVoiceRuntimeError.timedOut("Speech recognition timed out."))
                    }
                }
            }
        } onCancel: {
            taskBox.cancel()
        }
    }

    nonisolated private static func uniqueLocales(_ locales: [Locale]) -> [Locale] {
        var seen = Set<String>()
        var result: [Locale] = []
        for locale in locales {
            let key = normalizedLocaleIdentifier(locale.identifier)
            guard !seen.contains(key) else { continue }
            seen.insert(key)
            result.append(locale)
        }
        return result
    }
}
