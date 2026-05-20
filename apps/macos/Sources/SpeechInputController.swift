import AVFoundation
import Foundation
import Speech

@MainActor
final class SpeechInputController: NSObject, ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var statusText = ""

    private let audioEngine = AVAudioEngine()
    private let recognizer = SFSpeechRecognizer(locale: Locale.current)
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var baseText = ""
    private var onText: ((String) -> Void)?

    func toggle(startingWith text: String, onText: @escaping (String) -> Void) {
        if isRecording {
            stop()
        } else {
            start(startingWith: text, onText: onText)
        }
    }

    func start(startingWith text: String, onText: @escaping (String) -> Void) {
        guard !isRecording else { return }
        baseText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        self.onText = onText
        statusText = "Requesting microphone access..."

        requestMicrophoneAccess { [weak self] allowed in
            guard let self else { return }
            guard allowed else {
                self.statusText = "Microphone access is disabled."
                return
            }

            SFSpeechRecognizer.requestAuthorization { status in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    guard status == .authorized else {
                        self.statusText = "Speech recognition is not authorized."
                        return
                    }
                    self.startRecording()
                }
            }
        }
    }

    func stop() {
        guard isRecording || audioEngine.isRunning else { return }
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
        isRecording = false
        statusText = "Voice input stopped."
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

    private func startRecording() {
        guard let recognizer, recognizer.isAvailable else {
            statusText = "Speech recognizer is unavailable."
            return
        }

        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest else {
            statusText = "Could not create speech request."
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
            statusText = "Could not start microphone: \(error.localizedDescription)"
            return
        }

        isRecording = true
        statusText = "Listening..."
        recognitionTask = recognizer.recognitionTask(with: recognitionRequest) { [weak self] result, error in
            Task { @MainActor [weak self] in
                guard let self else { return }
                if let result {
                    let spoken = result.bestTranscription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
                    let combined = [self.baseText, spoken].filter { !$0.isEmpty }.joined(separator: " ")
                    self.onText?(combined)
                    self.statusText = result.isFinal ? "Voice input captured." : "Listening..."
                }

                if error != nil || result?.isFinal == true {
                    self.finishRecognition()
                }
            }
        }
    }

    private func finishRecognition() {
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask = nil
        isRecording = false
    }
}
