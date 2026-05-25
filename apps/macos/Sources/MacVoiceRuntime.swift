import Foundation

enum SpeechOutputEngine: String, CaseIterable, Identifiable {
    case edgeOnline
    case systemAVSpeech

    var id: String { rawValue }
}

enum SpeechRecognitionEngine: String, CaseIterable, Identifiable {
    case automatic
    case funASRLocal
    case appleSpeech

    var id: String { rawValue }
}

struct EdgeSpeechVoiceOption: Identifiable, Equatable {
    var id: String
    var name: String
    var language: String

    var displayName: String {
        "\(name) · \(language)"
    }
}

struct MacVoiceProcessOutput {
    var stdout: String
    var stderr: String
}

enum MacVoiceRuntimeError: LocalizedError {
    case helperMissing(String)
    case pythonMissing
    case processFailed(String)
    case timedOut(String)
    case invalidOutput(String)

    var errorDescription: String? {
        switch self {
        case .helperMissing(let name):
            return "The voice helper is missing: \(name)."
        case .pythonMissing:
            return "No Python runtime was found for voice features."
        case .processFailed(let detail):
            return detail.isEmpty ? "The voice helper failed." : detail
        case .timedOut(let detail):
            return detail
        case .invalidOutput(let detail):
            return detail
        }
    }
}

enum MacVoiceRuntime {
    private final class ProcessOutputBuffer {
        private let lock = NSLock()
        private var data = Data()

        func append(_ chunk: Data) {
            guard !chunk.isEmpty else { return }
            lock.lock()
            data.append(chunk)
            lock.unlock()
        }

        var stringValue: String {
            lock.lock()
            let snapshot = data
            lock.unlock()
            return String(data: snapshot, encoding: .utf8) ?? ""
        }
    }

    private struct PythonInvocation {
        var executableURL: URL
        var argumentsPrefix: [String]
        var environment: [String: String]
        var currentDirectoryURL: URL
    }

    static let defaultEdgeRate = "+0%"
    static let funASRRequirements = [
        "funasr>=1.2,<2",
        "modelscope>=1.10,<2",
        "setuptools>=69"
    ]

    static var voiceRuntimeRoot: URL {
        applicationSupportRoot().appendingPathComponent("VoiceRuntime", isDirectory: true)
    }

    static var funASRSitePackages: URL {
        voiceRuntimeRoot
            .appendingPathComponent("funasr", isDirectory: true)
            .appendingPathComponent("site-packages", isDirectory: true)
    }

    static var voiceCacheRoot: URL {
        applicationSupportRoot().appendingPathComponent("VoiceCache", isDirectory: true)
    }

    static func isFunASRInstalled() -> Bool {
        if isFunASRReady(in: funASRSitePackages) {
            return true
        }
        if let bundledSitePackages = bundledSitePackages() {
            return isFunASRReady(in: bundledSitePackages)
        }
        return false
    }

    static func isEdgeTTSInstalled() -> Bool {
        if let bundledSitePackages = bundledSitePackages(),
           FileManager.default.fileExists(
            atPath: bundledSitePackages
                .appendingPathComponent("edge_tts", isDirectory: true)
                .appendingPathComponent("__init__.py")
                .path
           ) {
            return true
        }
        if let repo = findRepoRoot() {
            let candidates = [
                repo.appendingPathComponent(".venv/lib/python3.12/site-packages/edge_tts/__init__.py"),
                repo.appendingPathComponent(".venv/lib/python3.11/site-packages/edge_tts/__init__.py"),
                repo.appendingPathComponent(".venv/lib/python3.10/site-packages/edge_tts/__init__.py")
            ]
            if candidates.contains(where: { FileManager.default.fileExists(atPath: $0.path) }) {
                return true
            }
        }
        return false
    }

    static func renderEdgeSpeech(
        textFile: URL,
        outputFile: URL,
        voice: String,
        rate: String = defaultEdgeRate
    ) async throws {
        _ = try await runHelper(
            name: "edge_tts_render.py",
            arguments: [
                "--text-file", textFile.path,
                "--output-file", outputFile.path,
                "--voice", voice,
                "--rate", rate
            ],
            timeout: 90
        )
    }

    static func transcribeChineseAudio(
        inputURL: URL,
        hotwords: URL? = nil,
        timeout: TimeInterval = 60
    ) async throws -> String {
        let output = temporaryURL(prefix: "elephant-funasr", extension: "json")
        var arguments = [
            "--input", inputURL.path,
            "--output-json", output.path,
            "--language", "zh"
        ]
        if let hotwords {
            arguments += ["--hotwords", hotwords.path]
        }
        _ = try await runHelper(
            name: "funasr_transcribe.py",
            arguments: arguments,
            timeout: timeout,
            acceptedExitCodes: [0, 2, 3]
        )
        let data = try Data(contentsOf: output)
        guard let payload = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw MacVoiceRuntimeError.invalidOutput("Chinese recognition did not return a readable result.")
        }
        if let error = payload["error"] as? String, !error.isEmpty {
            throw MacVoiceRuntimeError.processFailed(userFacingRecognitionError(error))
        }
        let text = (payload["text"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            throw MacVoiceRuntimeError.invalidOutput("No speech was recognized.")
        }
        return text
    }

    static func installFunASRRuntime() async throws -> String {
        try await Task.detached(priority: .userInitiated) {
            let invocation = try pythonInvocation()
            try? FileManager.default.removeItem(at: funASRReadyMarker(in: funASRSitePackages))
            try FileManager.default.createDirectory(at: funASRSitePackages, withIntermediateDirectories: true)
            let arguments = invocation.argumentsPrefix + [
                "-m", "pip", "install",
                "--upgrade",
                "--force-reinstall",
                "--target", funASRSitePackages.path
            ] + funASRRequirements
            _ = try runProcess(
                executableURL: invocation.executableURL,
                arguments: arguments,
                environment: invocation.environment,
                currentDirectoryURL: invocation.currentDirectoryURL,
                timeout: 1_800,
                timeoutLabel: "Installing Chinese recognition timed out."
            )
            let healthOutput = temporaryURL(prefix: "elephant-funasr-health", extension: "json")
            defer { try? FileManager.default.removeItem(at: healthOutput) }
            _ = try await runHelper(
                name: "funasr_transcribe.py",
                arguments: [
                    "--input", healthOutput.path,
                    "--output-json", healthOutput.path,
                    "--language", "zh",
                    "--health-check"
                ],
                timeout: 1_800,
                acceptedExitCodes: [0, 2, 3]
            )
            let healthData = try Data(contentsOf: healthOutput)
            guard let healthPayload = try JSONSerialization.jsonObject(with: healthData) as? [String: Any],
                  healthPayload["ok"] as? Bool == true
            else {
                let payload = (try? JSONSerialization.jsonObject(with: healthData) as? [String: Any]) ?? [:]
                let detail = (payload["error"] as? String) ?? "Chinese recognition health check failed."
                throw MacVoiceRuntimeError.processFailed(userFacingRecognitionError(detail))
            }
            try "ready\n".write(to: funASRReadyMarker(in: funASRSitePackages), atomically: true, encoding: .utf8)
            return "Local Chinese recognition is ready."
        }.value
    }

    static func temporaryURL(prefix: String, extension pathExtension: String) -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("\(prefix)-\(UUID().uuidString)")
            .appendingPathExtension(pathExtension)
    }

    private static func userFacingRecognitionError(_ error: String) -> String {
        error
            .replacingOccurrences(of: "FunASR", with: "Chinese recognition")
            .replacingOccurrences(of: "funasr", with: "Chinese recognition")
            .replacingOccurrences(of: "Paraformer", with: "Chinese recognition")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func runHelper(
        name: String,
        arguments: [String],
        timeout: TimeInterval,
        acceptedExitCodes: Set<Int32> = [0]
    ) async throws -> MacVoiceProcessOutput {
        let task = Task.detached(priority: .userInitiated) {
            let helper = try helperURL(name: name)
            let invocation = try pythonInvocation()
            return try runProcess(
                executableURL: invocation.executableURL,
                arguments: invocation.argumentsPrefix + [helper.path] + arguments,
                environment: invocation.environment,
                currentDirectoryURL: invocation.currentDirectoryURL,
                timeout: timeout,
                timeoutLabel: "\(name) timed out.",
                acceptedExitCodes: acceptedExitCodes
            )
        }
        return try await withTaskCancellationHandler {
            try await task.value
        } onCancel: {
            task.cancel()
        }
    }

    private static func funASRReadyMarker(in sitePackages: URL) -> URL {
        sitePackages.appendingPathComponent(".elephant-funasr-ready")
    }

    private static func isFunASRReady(in sitePackages: URL) -> Bool {
        FileManager.default.fileExists(atPath: funASRReadyMarker(in: sitePackages).path)
            && hasFunASRPackage(in: sitePackages)
    }

    private static func hasFunASRPackage(in preferredSitePackages: URL) -> Bool {
        if hasFunASRPackageOnly(in: preferredSitePackages) {
            return true
        }
        if let bundledSitePackages = bundledSitePackages() {
            return hasFunASRPackageOnly(in: bundledSitePackages)
        }
        return false
    }

    private static func hasFunASRPackageOnly(in sitePackages: URL) -> Bool {
        FileManager.default.fileExists(
            atPath: sitePackages
                .appendingPathComponent("funasr", isDirectory: true)
                .appendingPathComponent("__init__.py")
                .path
        )
    }

    private static func helperURL(name: String) throws -> URL {
        let resourceName = (name as NSString).deletingPathExtension
        let resourceExtension = (name as NSString).pathExtension
        if let bundled = Bundle.main.url(
            forResource: resourceName,
            withExtension: resourceExtension,
            subdirectory: "Voice"
        ) {
            return bundled
        }
        if let repo = findRepoRoot() {
            let source = repo
                .appendingPathComponent("apps/macos/Sources/Resources/Voice", isDirectory: true)
                .appendingPathComponent(name)
            if FileManager.default.fileExists(atPath: source.path) {
                return source
            }
        }
        throw MacVoiceRuntimeError.helperMissing(name)
    }

    private static func pythonInvocation() throws -> PythonInvocation {
        let fileManager = FileManager.default
        let root = findRepoRoot()
        var environment = ProcessInfo.processInfo.environment
        environment["ELEPHANT_VOICE_CACHE"] = voiceCacheRoot.path
        environment["MODELSCOPE_CACHE"] = voiceCacheRoot.appendingPathComponent("modelscope", isDirectory: true).path
        environment["HF_HOME"] = voiceCacheRoot.appendingPathComponent("huggingface", isDirectory: true).path
        environment["TORCH_HOME"] = voiceCacheRoot.appendingPathComponent("torch", isDirectory: true).path

        var pythonPathEntries: [String] = []
        if fileManager.fileExists(atPath: funASRSitePackages.path) {
            pythonPathEntries.append(funASRSitePackages.path)
        }
        if let bundledSitePackages = bundledSitePackages() {
            pythonPathEntries.append(bundledSitePackages.path)
            environment["PYTHONNOUSERSITE"] = "1"
        }
        if let root {
            pythonPathEntries.append(root.path)
        }
        if let existing = environment["PYTHONPATH"], !existing.isEmpty {
            pythonPathEntries.append(existing)
        }
        if !pythonPathEntries.isEmpty {
            environment["PYTHONPATH"] = pythonPathEntries.joined(separator: ":")
        }

        let candidates = pythonCandidates(repoRoot: root)
        if let python = candidates.first(where: { fileManager.isExecutableFile(atPath: $0.path) }) {
            return PythonInvocation(
                executableURL: python,
                argumentsPrefix: [],
                environment: environment,
                currentDirectoryURL: root ?? applicationSupportRoot()
            )
        }
        return PythonInvocation(
            executableURL: URL(fileURLWithPath: "/usr/bin/env"),
            argumentsPrefix: ["python3"],
            environment: environment,
            currentDirectoryURL: root ?? applicationSupportRoot()
        )
    }

    private static func runProcess(
        executableURL: URL,
        arguments: [String],
        environment: [String: String],
        currentDirectoryURL: URL,
        timeout: TimeInterval,
        timeoutLabel: String,
        acceptedExitCodes: Set<Int32> = [0]
    ) throws -> MacVoiceProcessOutput {
        let process = Process()
        process.executableURL = executableURL
        process.arguments = arguments
        process.environment = environment
        process.currentDirectoryURL = currentDirectoryURL

        let outputPipe = Pipe()
        let errorPipe = Pipe()
        let stdoutBuffer = ProcessOutputBuffer()
        let stderrBuffer = ProcessOutputBuffer()
        outputPipe.fileHandleForReading.readabilityHandler = { handle in
            stdoutBuffer.append(handle.availableData)
        }
        errorPipe.fileHandleForReading.readabilityHandler = { handle in
            stderrBuffer.append(handle.availableData)
        }
        process.standardOutput = outputPipe
        process.standardError = errorPipe
        do {
            try process.run()
        } catch {
            outputPipe.fileHandleForReading.readabilityHandler = nil
            errorPipe.fileHandleForReading.readabilityHandler = nil
            throw error
        }

        let deadline = Date().addingTimeInterval(timeout)
        while process.isRunning && Date() < deadline {
            if Task.isCancelled {
                process.terminate()
                outputPipe.fileHandleForReading.readabilityHandler = nil
                errorPipe.fileHandleForReading.readabilityHandler = nil
                throw CancellationError()
            }
            Thread.sleep(forTimeInterval: 0.05)
        }
        if process.isRunning {
            process.terminate()
            outputPipe.fileHandleForReading.readabilityHandler = nil
            errorPipe.fileHandleForReading.readabilityHandler = nil
            throw MacVoiceRuntimeError.timedOut(timeoutLabel)
        }

        outputPipe.fileHandleForReading.readabilityHandler = nil
        errorPipe.fileHandleForReading.readabilityHandler = nil
        stdoutBuffer.append(outputPipe.fileHandleForReading.readDataToEndOfFile())
        stderrBuffer.append(errorPipe.fileHandleForReading.readDataToEndOfFile())
        let stdout = stdoutBuffer.stringValue
        let stderr = stderrBuffer.stringValue
        guard acceptedExitCodes.contains(process.terminationStatus) else {
            let detail = [stderr, stdout]
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
                .joined(separator: "\n")
            throw MacVoiceRuntimeError.processFailed(detail)
        }
        return MacVoiceProcessOutput(stdout: stdout, stderr: stderr)
    }

    private static func pythonCandidates(repoRoot: URL?) -> [URL] {
        let environment = ProcessInfo.processInfo.environment
        let explicit = ["ELEPHANT_MAC_PYTHON", "PYTHON"]
            .compactMap { environment[$0] }
            .filter { !$0.isEmpty }
            .map { URL(fileURLWithPath: $0) }
        let bundled = bundledPython().map { [$0] } ?? []
        let repo = repoRoot.map {
            [
                $0.appendingPathComponent(".venv/bin/python"),
                $0.appendingPathComponent(".venv/bin/python3")
            ]
        } ?? []
        let user = [
            FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".elephant/venv/bin/python"),
            URL(fileURLWithPath: "/opt/homebrew/bin/python3"),
            URL(fileURLWithPath: "/usr/local/bin/python3"),
            URL(fileURLWithPath: "/usr/bin/python3")
        ]
        return explicit + bundled + repo + user
    }

    private static func bundledPython() -> URL? {
        guard let runtime = bundledRuntimeRoot() else { return nil }
        let candidates = [
            runtime.appendingPathComponent("python/bin/python3.12"),
            runtime.appendingPathComponent("python/bin/python3"),
            runtime.appendingPathComponent("python/bin/python")
        ]
        return candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0.path) })
    }

    private static func bundledSitePackages() -> URL? {
        guard let runtime = bundledRuntimeRoot() else { return nil }
        let sitePackages = runtime.appendingPathComponent("site-packages", isDirectory: true)
        return FileManager.default.fileExists(atPath: sitePackages.path) ? sitePackages : nil
    }

    private static func bundledRuntimeRoot() -> URL? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        let runtime = resources.appendingPathComponent("Runtime", isDirectory: true)
        let manifest = runtime.appendingPathComponent("manifest.json")
        guard FileManager.default.fileExists(atPath: manifest.path) else { return nil }
        return runtime
    }

    private static func findRepoRoot() -> URL? {
        let fileManager = FileManager.default
        let environment = ProcessInfo.processInfo.environment
        for key in ["ELEPHANT_MAC_REPO_ROOT", "ELEPHANT_REPO_ROOT"] {
            if let value = environment[key], !value.isEmpty {
                let url = URL(fileURLWithPath: value)
                if fileManager.fileExists(atPath: url.appendingPathComponent("pyproject.toml").path) {
                    return url
                }
            }
        }
        if let resource = Bundle.main.url(forResource: "RepoRoot", withExtension: "txt"),
           let value = try? String(contentsOf: resource).trimmingCharacters(in: .whitespacesAndNewlines),
           !value.isEmpty {
            let url = URL(fileURLWithPath: value)
            if fileManager.fileExists(atPath: url.appendingPathComponent("pyproject.toml").path) {
                return url
            }
        }

        var candidate = URL(fileURLWithPath: fileManager.currentDirectoryPath)
        for _ in 0..<8 {
            if fileManager.fileExists(atPath: candidate.appendingPathComponent("pyproject.toml").path) {
                return candidate
            }
            candidate.deleteLastPathComponent()
        }
        return nil
    }

    private static func applicationSupportRoot() -> URL {
        let fileManager = FileManager.default
        let support = (try? fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )) ?? fileManager.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support", isDirectory: true)
        let root = support.appendingPathComponent("Elephant Agent", isDirectory: true)
        try? fileManager.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }
}
