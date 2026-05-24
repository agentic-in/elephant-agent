import AVFoundation
import Foundation
import Speech

@MainActor
final class SpeechInputController: NSObject, ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var isTranscribing = false
    @Published private(set) var statusText = ""
    @Published private(set) var recordingStartedAt: Date?
    @Published private(set) var capturedDuration: TimeInterval = 0
    @Published private(set) var recognizedText = ""

    private enum ActiveMode {
        case apple(locale: Locale, statusNotice: String?)
        case funASR
    }

    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var recognizer: SFSpeechRecognizer?
    private var recordingURL: URL?
    private var convertedRecordingURL: URL?
    private var transcriptionTask: Task<Void, Never>?
    private var baseText = ""
    private var onText: ((String) -> Void)?
    private var activeMode: ActiveMode = .apple(locale: Locale(identifier: "en-US"), statusNotice: nil)
    private var activeLanguage: AppLanguage = .en

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
        guard !isRecording && !isTranscribing else { return }
        baseText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        self.onText = onText
        activeLanguage = language
        recognizedText = ""
        capturedDuration = 0
        recordingStartedAt = nil
        cleanupRecordingFiles()
        activeMode = Self.resolvedMode(language: language, recognitionEngine: recognitionEngine)
        statusText = Self.localizedStatus(language, en: "Requesting microphone access...", zh: "正在请求麦克风权限...")

        requestMicrophoneAccess { [weak self] allowed in
            guard let self else { return }
            guard allowed else {
                self.statusText = Self.localizedStatus(self.activeLanguage, en: "Microphone access is disabled.", zh: "麦克风权限未开启。")
                return
            }

            switch self.activeMode {
            case .funASR:
                self.startLocalRecording()
            case .apple(let locale, let statusNotice):
                SFSpeechRecognizer.requestAuthorization { status in
                    Task { @MainActor [weak self] in
                        guard let self else { return }
                        guard status == .authorized else {
                            self.statusText = Self.localizedStatus(self.activeLanguage, en: "Speech recognition is not authorized.", zh: "语音识别权限未开启。")
                            return
                        }
                        self.startAppleRecording(locale: locale, statusNotice: statusNotice)
                    }
                }
            }
        }
    }

    func stop() {
        guard isRecording || audioEngine.isRunning else { return }
        updateCapturedDuration()
        let mode = activeMode
        stopAudioEngine()
        isRecording = false
        recordingStartedAt = nil

        switch mode {
        case .funASR:
            startFunASRTranscription()
        case .apple:
            recognitionRequest?.endAudio()
            recognitionTask?.finish()
            recognitionRequest = nil
            statusText = recognizedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? Self.localizedStatus(activeLanguage, en: "Voice input stopped.", zh: "语音输入已停止。")
                : Self.localizedStatus(activeLanguage, en: "Voice input captured.", zh: "已捕捉到语音。")
        }
    }

    func resetCapture() {
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
        if language == .zh {
            switch recognitionEngine {
            case .automatic:
                if MacVoiceRuntime.isFunASRInstalled() {
                    return .funASR
                }
                return .apple(
                    locale: Locale(identifier: "zh-CN"),
                    statusNotice: localizedStatus(language, en: "Chinese recognition pack is not installed; using system dictation for now.", zh: "中文识别包未安装，暂时使用系统听写。")
                )
            case .funASRLocal:
                if MacVoiceRuntime.isFunASRInstalled() {
                    return .funASR
                }
                return .apple(
                    locale: Locale(identifier: "zh-CN"),
                    statusNotice: localizedStatus(language, en: "Chinese recognition pack is not installed; using system dictation for now.", zh: "中文识别包未安装，暂时使用系统听写。")
                )
            case .appleSpeech:
                return .apple(locale: Locale(identifier: "zh-CN"), statusNotice: nil)
            }
        }
        return .apple(locale: Locale(identifier: "en-US"), statusNotice: nil)
    }

    private func requestMicrophoneAccess(_ completion: @escaping (Bool) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            completion(true)
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { allowed in
                Task { @MainActor in completion(allowed) }
            }
        default:
            completion(false)
        }
    }

    private func startAppleRecording(locale: Locale, statusNotice: String?) {
        recognizer = SFSpeechRecognizer(locale: locale)
        guard let recognizer, recognizer.isAvailable else {
            statusText = Self.localizedStatus(activeLanguage, en: "Speech recognizer is unavailable.", zh: "语音识别暂不可用。")
            return
        }

        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest else {
            statusText = Self.localizedStatus(activeLanguage, en: "Could not create speech request.", zh: "无法创建语音识别请求。")
            return
        }
        recognitionRequest.shouldReportPartialResults = true

        let inputNode = audioEngine.inputNode
        inputNode.removeTap(onBus: 0)
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak recognitionRequest] buffer, _ in
            recognitionRequest?.append(buffer)
        }

        do {
            audioEngine.prepare()
            try audioEngine.start()
        } catch {
            inputNode.removeTap(onBus: 0)
            statusText = Self.localizedStatus(activeLanguage, en: "Could not start microphone: \(error.localizedDescription)", zh: "无法启动麦克风：\(error.localizedDescription)")
            return
        }

        isRecording = true
        recordingStartedAt = Date()
        capturedDuration = 0
        statusText = statusNotice ?? Self.localizedStatus(activeLanguage, en: "Listening...", zh: "正在听...")
        recognitionTask = recognizer.recognitionTask(with: recognitionRequest) { [weak self] result, error in
            Task { @MainActor [weak self] in
                guard let self else { return }
                if let result {
                    let spoken = result.bestTranscription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
                    self.applyRecognizedText(spoken)
                    self.statusText = result.isFinal
                        ? Self.localizedStatus(self.activeLanguage, en: "Voice input captured.", zh: "已捕捉到语音。")
                        : Self.localizedStatus(self.activeLanguage, en: "Listening...", zh: "正在听...")
                }

                if error != nil || result?.isFinal == true {
                    self.finishAppleRecognition()
                }
            }
        }
    }

    private func startLocalRecording() {
        let inputNode = audioEngine.inputNode
        inputNode.removeTap(onBus: 0)
        let format = inputNode.outputFormat(forBus: 0)

        let file: AVAudioFile
        let url: URL
        do {
            (url, file) = try makeRecordingFile(inputFormat: format)
        } catch {
            statusText = Self.localizedStatus(activeLanguage, en: "Could not prepare local recording: \(error.localizedDescription)", zh: "无法准备本地录音：\(error.localizedDescription)")
            return
        }
        recordingURL = url

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            try? file.write(from: buffer)
        }

        do {
            audioEngine.prepare()
            try audioEngine.start()
        } catch {
            inputNode.removeTap(onBus: 0)
            statusText = Self.localizedStatus(activeLanguage, en: "Could not start microphone: \(error.localizedDescription)", zh: "无法启动麦克风：\(error.localizedDescription)")
            return
        }

        isRecording = true
        recordingStartedAt = Date()
        capturedDuration = 0
        statusText = Self.localizedStatus(activeLanguage, en: "Listening...", zh: "正在听...")
    }

    private func startFunASRTranscription() {
        guard let recordingURL else {
            statusText = Self.localizedStatus(activeLanguage, en: "No local recording was captured.", zh: "没有捕捉到本地录音。")
            return
        }
        isTranscribing = true
        statusText = Self.localizedStatus(activeLanguage, en: "Recognizing Chinese...", zh: "正在识别中文...")
        transcriptionTask?.cancel()
        transcriptionTask = Task { [weak self] in
            do {
                let wavURL = try await Self.convertToSixteenKilohertzWAV(recordingURL)
                let text = try await MacVoiceRuntime.transcribeChineseAudio(inputURL: wavURL)
                await MainActor.run {
                    guard let self, !Task.isCancelled else { return }
                    self.convertedRecordingURL = wavURL
                    self.applyRecognizedText(text)
                    self.statusText = Self.localizedStatus(self.activeLanguage, en: "Voice input captured.", zh: "已捕捉到语音。")
                    self.isTranscribing = false
                }
            } catch {
                await MainActor.run {
                    guard let self, !Task.isCancelled else { return }
                    self.statusText = Self.localizedStatus(self.activeLanguage, en: "Chinese recognition failed: \(error.localizedDescription)", zh: "中文识别失败：\(error.localizedDescription)")
                    self.isTranscribing = false
                }
            }
        }
    }

    private func finishAppleRecognition() {
        updateCapturedDuration()
        if audioEngine.isRunning {
            stopAudioEngine()
        }
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask = nil
        recognizer = nil
        isRecording = false
        recordingStartedAt = nil
    }

    private func stopAudioEngine() {
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

    private static func localizedStatus(_ language: AppLanguage, en: String, zh: String) -> String {
        language == .zh ? zh : en
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
}
