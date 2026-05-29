import AVFoundation
import Foundation

struct LocalSpeechVoiceOption: Identifiable, Equatable {
    var id: String
    var name: String
    var language: String
    var quality: Int

    var displayName: String {
        "\(name) · \(language) · \(qualityLabel)"
    }

    private var qualityLabel: String {
        switch quality {
        case 3...:
            return "Premium"
        case 2:
            return "Enhanced"
        default:
            return "Default"
        }
    }
}

@MainActor
final class LocalSpeechOutputController: NSObject, ObservableObject, AVSpeechSynthesizerDelegate, AVAudioPlayerDelegate {
    @Published private(set) var activeMessageID: UUID?
    @Published private(set) var isPreparing = false
    @Published private(set) var isSpeaking = false
    @Published private(set) var activeVoiceName = ""
    @Published private(set) var activeVoiceLanguage = ""
    @Published private(set) var lastError = ""
    @Published private(set) var lastPlaybackMessageID: UUID?
    @Published private(set) var lastFailedMessageID: UUID?

    private let synthesizer = AVSpeechSynthesizer()
    private var audioPlayer: AVAudioPlayer?
    private var speechTask: Task<Void, Never>?
    private var generationID: UUID?
    private var activeAudioURL: URL?
    private weak var activeSystemUtterance: AVSpeechUtterance?

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func speak(
        messageID: UUID? = nil,
        text: String,
        language: AppLanguage,
        engine: SpeechOutputEngine = .edgeOnline,
        systemVoiceIdentifier: String = "",
        edgeVoiceIdentifier: String = ""
    ) {
        let trimmed = Self.sanitizedSpeechText(from: text)
        guard !trimmed.isEmpty else { return }

        stop()
        lastError = ""
        lastPlaybackMessageID = messageID
        lastFailedMessageID = nil

        switch engine {
        case .edgeOnline:
            speakWithEdge(
                messageID: messageID,
                text: trimmed,
                language: language,
                edgeVoiceIdentifier: edgeVoiceIdentifier,
                systemVoiceIdentifier: systemVoiceIdentifier
            )
        case .systemAVSpeech:
            speakWithSystem(
                messageID: messageID,
                text: trimmed,
                language: language,
                preferredVoiceIdentifier: systemVoiceIdentifier
            )
        }
    }

    func stop() {
        speechTask?.cancel()
        speechTask = nil
        generationID = nil
        if synthesizer.isSpeaking || synthesizer.isPaused {
            synthesizer.stopSpeaking(at: .immediate)
        }
        if let audioPlayer {
            audioPlayer.stop()
        }
        audioPlayer = nil
        activeSystemUtterance = nil
        cleanupActiveAudio()
        activeMessageID = nil
        isPreparing = false
        isSpeaking = false
    }

    func toggle(
        messageID: UUID,
        text: String,
        language: AppLanguage,
        engine: SpeechOutputEngine = .edgeOnline,
        systemVoiceIdentifier: String = "",
        edgeVoiceIdentifier: String = ""
    ) {
        if activeMessageID == messageID, isSpeaking || isPreparing {
            stop()
            return
        }
        speak(
            messageID: messageID,
            text: text,
            language: language,
            engine: engine,
            systemVoiceIdentifier: systemVoiceIdentifier,
            edgeVoiceIdentifier: edgeVoiceIdentifier
        )
    }

    func speakPreview(
        language: AppLanguage,
        engine: SpeechOutputEngine = .edgeOnline,
        systemVoiceIdentifier: String = "",
        edgeVoiceIdentifier: String = ""
    ) {
        speak(
            text: Self.previewText(for: language, engine: engine),
            language: language,
            engine: engine,
            systemVoiceIdentifier: systemVoiceIdentifier,
            edgeVoiceIdentifier: edgeVoiceIdentifier
        )
    }

    static func targetLanguageIdentifier(for language: AppLanguage) -> String {
        language == .zh ? "zh-CN" : "en-US"
    }

    static func defaultEdgeVoiceIdentifier(for language: AppLanguage) -> String {
        language == .zh ? "zh-CN-XiaoxiaoNeural" : "en-US-AriaNeural"
    }

    static func edgeVoiceOptions(for language: AppLanguage) -> [EdgeSpeechVoiceOption] {
        if language == .zh {
            return [
                EdgeSpeechVoiceOption(id: "zh-CN-XiaoxiaoNeural", name: "Xiaoxiao", language: "zh-CN"),
                EdgeSpeechVoiceOption(id: "zh-CN-XiaoyiNeural", name: "Xiaoyi", language: "zh-CN"),
                EdgeSpeechVoiceOption(id: "zh-CN-YunjianNeural", name: "Yunjian", language: "zh-CN"),
                EdgeSpeechVoiceOption(id: "zh-CN-YunxiNeural", name: "Yunxi", language: "zh-CN")
            ]
        }
        return [
            EdgeSpeechVoiceOption(id: "en-US-AriaNeural", name: "Aria", language: "en-US"),
            EdgeSpeechVoiceOption(id: "en-US-JennyNeural", name: "Jenny", language: "en-US"),
            EdgeSpeechVoiceOption(id: "en-US-GuyNeural", name: "Guy", language: "en-US"),
            EdgeSpeechVoiceOption(id: "en-US-AvaMultilingualNeural", name: "Ava", language: "en-US")
        ]
    }

    static func edgeVoiceDisplayName(identifier: String, language: AppLanguage) -> String {
        let selected = edgeVoiceOptions(for: language).first { $0.id == identifier }
        return selected?.displayName ?? (language == .zh ? "Xiaoxiao · zh-CN" : "Aria · en-US")
    }

    static func voiceOptions(for language: AppLanguage) -> [LocalSpeechVoiceOption] {
        rankedVoices(for: targetLanguageIdentifier(for: language))
            .map {
                LocalSpeechVoiceOption(
                    id: $0.identifier,
                    name: $0.name,
                    language: $0.language,
                    quality: $0.quality.rawValue
                )
            }
    }

    static func preferredVoice(language: AppLanguage, preferredIdentifier: String) -> AVSpeechSynthesisVoice? {
        let target = targetLanguageIdentifier(for: language)
        if !preferredIdentifier.isEmpty,
           let voice = AVSpeechSynthesisVoice(identifier: preferredIdentifier),
           matchesTargetLanguage(voice.language, target: target) {
            return voice
        }

        if let voice = rankedVoices(for: target).first {
            return voice
        }

        return AVSpeechSynthesisVoice(language: target)
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didStart utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard self?.activeSystemUtterance === utterance else { return }
            self?.isPreparing = false
            self?.isSpeaking = true
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard self?.activeSystemUtterance === utterance else { return }
            self?.activeSystemUtterance = nil
            self?.activeMessageID = nil
            self?.isPreparing = false
            self?.isSpeaking = false
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard self?.activeSystemUtterance === utterance else { return }
            self?.activeSystemUtterance = nil
            self?.activeMessageID = nil
            self?.isPreparing = false
            self?.isSpeaking = false
        }
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor [weak self] in
            guard self?.audioPlayer === player else { return }
            self?.activeMessageID = nil
            self?.isPreparing = false
            self?.isSpeaking = false
            self?.audioPlayer = nil
            self?.cleanupActiveAudio()
        }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        Task { @MainActor [weak self] in
            guard self?.audioPlayer === player else { return }
            let failedMessageID = self?.activeMessageID
            self?.lastError = error?.localizedDescription ?? "Could not play the generated voice reply."
            self?.lastFailedMessageID = failedMessageID
            self?.activeMessageID = nil
            self?.isPreparing = false
            self?.isSpeaking = false
            self?.audioPlayer = nil
            self?.cleanupActiveAudio()
        }
    }

    private func speakWithEdge(
        messageID: UUID?,
        text: String,
        language: AppLanguage,
        edgeVoiceIdentifier: String,
        systemVoiceIdentifier: String
    ) {
        let voice = edgeVoiceIdentifier.isEmpty
            ? Self.defaultEdgeVoiceIdentifier(for: language)
            : edgeVoiceIdentifier
        let id = UUID()
        generationID = id
        activeSystemUtterance = nil
        activeMessageID = messageID
        isPreparing = true
        isSpeaking = false
        lastPlaybackMessageID = messageID
        lastFailedMessageID = nil
        activeVoiceName = Self.edgeVoiceDisplayName(identifier: voice, language: language)
        activeVoiceLanguage = Self.targetLanguageIdentifier(for: language)

        speechTask = Task { [weak self] in
            let textFile = MacVoiceRuntime.temporaryURL(prefix: "elephant-edge-tts", extension: "txt")
            let audioFile = MacVoiceRuntime.temporaryURL(prefix: "elephant-edge-tts", extension: "mp3")
            do {
                try text.write(to: textFile, atomically: true, encoding: .utf8)
                try await MacVoiceRuntime.renderEdgeSpeech(
                    textFile: textFile,
                    outputFile: audioFile,
                    voice: voice
                )
                try? FileManager.default.removeItem(at: textFile)
                guard !Task.isCancelled else {
                    try? FileManager.default.removeItem(at: audioFile)
                    return
                }
                await MainActor.run {
                    guard let self, self.generationID == id else {
                        try? FileManager.default.removeItem(at: audioFile)
                        return
                    }
                    self.playRenderedAudio(
                        audioFile,
                        messageID: messageID,
                        fallbackText: text,
                        language: language,
                        systemVoiceIdentifier: systemVoiceIdentifier
                    )
                }
            } catch {
                try? FileManager.default.removeItem(at: textFile)
                try? FileManager.default.removeItem(at: audioFile)
                await MainActor.run {
                    guard let self, self.generationID == id else { return }
                    self.finishEdgeFailure(
                        messageID: messageID,
                        language: language,
                        error: error,
                        fallbackText: text,
                        systemVoiceIdentifier: systemVoiceIdentifier
                    )
                }
            }
        }
    }

    private func playRenderedAudio(
        _ url: URL,
        messageID: UUID?,
        fallbackText: String,
        language: AppLanguage,
        systemVoiceIdentifier: String
    ) {
        do {
            cleanupActiveAudio()
            let player = try AVAudioPlayer(contentsOf: url)
            player.delegate = self
            player.prepareToPlay()
            audioPlayer = player
            activeAudioURL = url
            activeMessageID = messageID
            lastFailedMessageID = nil
            guard player.play() else {
                throw MacVoiceRuntimeError.processFailed("Could not start audio playback.")
            }
            isPreparing = false
            isSpeaking = true
        } catch {
            try? FileManager.default.removeItem(at: url)
            finishEdgeFailure(
                messageID: messageID,
                language: language,
                error: error,
                fallbackText: fallbackText,
                systemVoiceIdentifier: systemVoiceIdentifier
            )
        }
    }

    private func finishEdgeFailure(
        messageID: UUID?,
        language: AppLanguage,
        error: Error,
        fallbackText: String,
        systemVoiceIdentifier: String
    ) {
        speechTask?.cancel()
        speechTask = nil
        generationID = nil
        activeMessageID = nil
        isPreparing = false
        isSpeaking = false
        audioPlayer = nil
        cleanupActiveAudio()
        lastPlaybackMessageID = messageID
        lastFailedMessageID = messageID
        activeVoiceName = ""
        activeVoiceLanguage = ""
        let base = language == .zh
            ? "自然语音暂时不可用，已改用本机声音。"
            : "Natural voice is unavailable, so Elephant used the local Mac voice."
        lastError = "\(base) \(error.localizedDescription)"
        speakWithSystem(
            messageID: messageID,
            text: fallbackText,
            language: language,
            preferredVoiceIdentifier: systemVoiceIdentifier,
            preserveError: true
        )
    }

    private func speakWithSystem(
        messageID: UUID?,
        text: String,
        language: AppLanguage,
        preferredVoiceIdentifier: String,
        preserveError: Bool = false
    ) {
        if synthesizer.isSpeaking || synthesizer.isPaused {
            synthesizer.stopSpeaking(at: .immediate)
        }
        if let audioPlayer {
            audioPlayer.stop()
        }
        audioPlayer = nil
        activeSystemUtterance = nil
        cleanupActiveAudio()

        let voice = Self.preferredVoice(language: language, preferredIdentifier: preferredVoiceIdentifier)
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = voice
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        utterance.volume = 1.0
        utterance.pitchMultiplier = 1.0

        activeMessageID = messageID
        isPreparing = false
        isSpeaking = true
        activeSystemUtterance = utterance
        lastPlaybackMessageID = messageID
        lastFailedMessageID = nil
        activeVoiceName = voice?.name ?? "System Default"
        activeVoiceLanguage = voice?.language ?? Self.targetLanguageIdentifier(for: language)
        if !preserveError {
            lastError = ""
        }
        synthesizer.speak(utterance)
    }

    private func cleanupActiveAudio() {
        if let activeAudioURL {
            try? FileManager.default.removeItem(at: activeAudioURL)
        }
        activeAudioURL = nil
    }

    private static func rankedVoices(for target: String) -> [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices()
            .filter { matchesTargetLanguage($0.language, target: target) }
            .sorted { lhs, rhs in
                let left = voiceRank(lhs, target: target)
                let right = voiceRank(rhs, target: target)
                if left.language != right.language { return left.language < right.language }
                if left.quality != right.quality { return left.quality < right.quality }
                if left.name != right.name { return left.name < right.name }
                if left.kind != right.kind { return left.kind < right.kind }
                return lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending
            }
    }

    private static func voiceRank(
        _ voice: AVSpeechSynthesisVoice,
        target: String
    ) -> (language: Int, quality: Int, name: Int, kind: Int) {
        let normalizedLanguage = normalizedLanguageIdentifier(voice.language)
        let normalizedTarget = normalizedLanguageIdentifier(target)
        let targetPrefix = languagePrefix(normalizedTarget)
        let languageRank = normalizedLanguage == normalizedTarget ? 0 : 1
        let qualityRank = -voice.quality.rawValue
        let nameRank = preferredNameRank(voice.name, targetPrefix: targetPrefix)
        let kindRank = voice.identifier.localizedCaseInsensitiveContains("eloquence") ? 1 : 0
        return (languageRank, qualityRank, nameRank, kindRank)
    }

    private static func preferredNameRank(_ name: String, targetPrefix: String) -> Int {
        let normalized = name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let preferredNames: [String]
        if targetPrefix == "zh" {
            preferredNames = ["tingting", "meijia"]
        } else {
            preferredNames = ["samantha", "ava", "allison"]
        }
        return preferredNames.firstIndex(of: normalized) ?? preferredNames.count
    }

    private static func matchesTargetLanguage(_ language: String, target: String) -> Bool {
        let normalizedLanguage = normalizedLanguageIdentifier(language)
        let normalizedTarget = normalizedLanguageIdentifier(target)
        return normalizedLanguage == normalizedTarget
            || languagePrefix(normalizedLanguage) == languagePrefix(normalizedTarget)
    }

    private static func normalizedLanguageIdentifier(_ language: String) -> String {
        language
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "_", with: "-")
            .lowercased()
    }

    private static func languagePrefix(_ language: String) -> String {
        normalizedLanguageIdentifier(language)
            .split(separator: "-")
            .first
            .map(String.init) ?? ""
    }

    static func sanitizedSpeechText(from text: String) -> String {
        let markdownStripped = text
            .replacingOccurrences(of: #"(?s)<think>.*?</think>"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"(?s)<think>.*"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"</think>"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"(?s)```.*?```"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"`([^`]+)`"#, with: "$1", options: .regularExpression)
            .replacingOccurrences(of: #"\[([^\]]+)\]\(([^)]+)\)"#, with: "$1", options: .regularExpression)
            .replacingOccurrences(of: #"https?://\S+"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"(?m)^\s{0,3}#{1,6}\s*"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"(?m)^\s*[-*+]\s+\[[ xX]\]\s*"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"(?m)^\s*[-*+]\s+"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"(?m)^\s*\d+[\.)]\s+"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"(?m)^\s*>\s?"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"(?m)^\s*\|?[\s:|-]{3,}\|?\s*$"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"[*_~|]+"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"(?m)^\s*[-=]{3,}\s*$"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"[#`]"#, with: "", options: .regularExpression)
        return removingEmojiCharacters(from: markdownStripped)
            .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func removingEmojiCharacters(from text: String) -> String {
        var scalars = String.UnicodeScalarView()
        for scalar in text.unicodeScalars {
            if scalar.value == 0x200D || (0xFE00...0xFE0F).contains(scalar.value) {
                continue
            }
            if scalar.properties.isEmojiPresentation {
                continue
            }
            if scalar.properties.isEmoji, scalar.value > 0x238C {
                continue
            }
            scalars.append(scalar)
        }
        return String(scalars)
    }

    private static func previewText(for language: AppLanguage, engine: SpeechOutputEngine) -> String {
        switch (language, engine) {
        case (.zh, .edgeOnline):
            return "你好，我会用高质量在线语音回复你的语音消息。"
        case (.zh, .systemAVSpeech):
            return "你好，我会用本机系统语音回复你的语音消息。"
        case (_, .edgeOnline):
            return "Hello, I will reply to voice messages using high quality online speech."
        case (_, .systemAVSpeech):
            return "Hello, I will reply to voice messages using the local macOS voice."
        }
    }
}
