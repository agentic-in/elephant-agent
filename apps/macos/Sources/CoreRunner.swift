import Darwin
import Foundation

struct CoreRuntime {
    var baseURL: URL
    var databasePath: URL
    var repoRoot: URL?
}

final class CoreRunner {
    private var process: Process?
    private(set) var baseURL: URL?
    private(set) var databasePath: URL?
    private(set) var repoRoot: URL?
    private var managedPIDFile: URL?
    private var apiLogFile: URL?
    private var apiLogHandle: FileHandle?
    private let ownerID = UUID().uuidString
    private static let runtimeStampFileName = "mac-runtime.stamp"

    func start() async throws -> CoreRuntime {
        if let process, process.isRunning, let baseURL, let databasePath {
            return CoreRuntime(baseURL: baseURL, databasePath: databasePath, repoRoot: repoRoot)
        }

        let root = Self.findRepoRoot()
        let data = try Self.resolveDataPaths(preferUserInstall: root == nil)
        return try await startResolved(root: root, data: data)
    }

    func resetLocalData() async throws -> CoreRuntime {
        let root = Self.findRepoRoot()
        let data = try Self.resolveDataPaths(preferUserInstall: root == nil)
        stop()
        Self.cleanupStaleManagedProcess(home: data.home, database: data.database)
        Self.cleanupOrphanedManagedAPIs(database: data.database)
        Self.cleanupManagedStateProcesses(stateDir: data.herd)
        try Self.removeLocalRuntimeData(data: data)
        return try await startResolved(root: root, data: data)
    }

    private func startResolved(
        root: URL?,
        data: (home: URL, herd: URL, database: URL)
    ) async throws -> CoreRuntime {
        if let process, process.isRunning, let baseURL, let databasePath {
            return CoreRuntime(baseURL: baseURL, databasePath: databasePath, repoRoot: repoRoot)
        }

        Self.cleanupStaleManagedProcess(home: data.home, database: data.database)
        Self.cleanupOrphanedManagedAPIs(database: data.database)
        let pythonRuntime = try await Self.resolvePythonRuntime(repoRoot: root, data: data)
        let port = try Self.freeLoopbackPort()
        let url = URL(string: "http://127.0.0.1:\(port)")!
        let logFile = data.herd.appendingPathComponent("mac-api.log")
        try? FileManager.default.createDirectory(at: data.herd, withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: logFile.path, contents: nil)
        let logHandle = try? FileHandle(forWritingTo: logFile)
        _ = try? logHandle?.seekToEnd()
        let launchLine = "Launching Elephant API: \(pythonRuntime.executableURL.path) \((pythonRuntime.argumentsPrefix + ["-m", "apps.api"]).joined(separator: " ")) --port \(port)\n"
        if let data = launchLine.data(using: .utf8) {
            try? logHandle?.write(contentsOf: data)
        }

        let python = Process()
        python.executableURL = pythonRuntime.executableURL
        python.arguments = pythonRuntime.argumentsPrefix + [
            "-m",
            "apps.api",
            "--host",
            "127.0.0.1",
            "--port",
            String(port),
            "--database",
            data.database.path
        ]
        python.currentDirectoryURL = root ?? data.home

        var environment = ProcessInfo.processInfo.environment
        if let root {
            environment["PYTHONPATH"] = root.path
        }
        for (key, value) in pythonRuntime.environment {
            environment[key] = value
        }
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["ELEPHANT_HOME"] = data.home.path
        environment["ELEPHANT_HERD_DIR"] = data.herd.path
        environment["ELEPHANT_MAC_MANAGED_API"] = "1"
        python.environment = environment

        if let logHandle {
            python.standardOutput = logHandle
            python.standardError = logHandle
        }
        try python.run()

        process = python
        baseURL = url
        databasePath = data.database
        repoRoot = root
        apiLogFile = logFile
        apiLogHandle = logHandle
        managedPIDFile = Self.managedPIDFile(home: data.home)
        try? Self.writeManagedPID(
            python.processIdentifier,
            home: data.home,
            ownerID: ownerID,
            database: data.database,
            port: port
        )

        do {
            try await waitUntilReady(baseURL: url, logFile: logFile)
        } catch {
            stop()
            throw error
        }

        return CoreRuntime(baseURL: url, databasePath: data.database, repoRoot: root)
    }

    func stop() {
        defer {
            if let managedPIDFile {
                Self.removeManagedPIDIfOwned(file: managedPIDFile, ownerID: ownerID)
            }
            self.process = nil
            self.baseURL = nil
            self.repoRoot = nil
            self.managedPIDFile = nil
            try? self.apiLogHandle?.close()
            self.apiLogHandle = nil
            self.apiLogFile = nil
        }

        guard let process else { return }
        if process.isRunning {
            Self.terminatePID(process.processIdentifier)
        }
    }

    private func waitUntilReady(baseURL: URL, logFile: URL?) async throws {
        let health = baseURL.appendingPathComponent("healthz")
        let overview = baseURL.appendingPathComponent("v1/internal/dashboard/overview")
        var lastError: Error?

        for _ in 0..<80 {
            if let process, !process.isRunning {
                throw CoreRunnerError.processExited(Self.tailLog(logFile))
            }
            do {
                _ = try await URLSession.shared.data(from: health)
                _ = try await URLSession.shared.data(from: overview)
                return
            } catch {
                lastError = error
                try await Task.sleep(nanoseconds: 150_000_000)
            }
        }
        let details = [
            lastError?.localizedDescription ?? "Timed out waiting for /healthz.",
            Self.tailLog(logFile)
        ].filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        throw CoreRunnerError.notReady(details.joined(separator: "\n"))
    }

    private static func findRepoRoot() -> URL? {
        let fileManager = FileManager.default
        let env = ProcessInfo.processInfo.environment
        for key in ["ELEPHANT_MAC_REPO_ROOT", "ELEPHANT_REPO_ROOT"] {
            if let value = env[key], !value.isEmpty {
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

    private static func resolveDataPaths(preferUserInstall: Bool) throws -> (home: URL, herd: URL, database: URL) {
        let fileManager = FileManager.default
        let userHome = fileManager.homeDirectoryForCurrentUser
        let existingHome = userHome.appendingPathComponent(".elephant", isDirectory: true)
        let existingHerd = existingHome.appendingPathComponent("herd", isDirectory: true)
        let existingDatabase = existingHerd.appendingPathComponent("elephant.sqlite3")
        let existingRuntime = existingHome.appendingPathComponent("venv/bin/python")
        let existingConfig = existingHome.appendingPathComponent("config.yaml")
        if preferUserInstall
            || fileManager.fileExists(atPath: existingDatabase.path)
            || fileManager.fileExists(atPath: existingRuntime.path)
            || fileManager.fileExists(atPath: existingConfig.path) {
            try fileManager.createDirectory(at: existingHerd, withIntermediateDirectories: true)
            return (existingHome, existingHerd, existingDatabase)
        }

        let support = try fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        ).appendingPathComponent("Elephant Agent", isDirectory: true)
        let herd = support.appendingPathComponent("herd", isDirectory: true)
        try fileManager.createDirectory(at: herd, withIntermediateDirectories: true)
        return (support, herd, herd.appendingPathComponent("elephant.sqlite3"))
    }

    private static func removeLocalRuntimeData(data: (home: URL, herd: URL, database: URL)) throws {
        let fileManager = FileManager.default
        let resetTargets = [
            data.herd,
            data.home.appendingPathComponent("config.yaml"),
            data.home.appendingPathComponent("cron", isDirectory: true),
            data.home.appendingPathComponent("pairing", isDirectory: true),
            data.home.appendingPathComponent("skills", isDirectory: true),
            data.home.appendingPathComponent("workspaces", isDirectory: true),
            managedPIDFile(home: data.home)
        ]

        for target in resetTargets {
            if fileManager.fileExists(atPath: target.path) {
                try fileManager.removeItem(at: target)
            }
        }
        try fileManager.createDirectory(at: data.herd, withIntermediateDirectories: true)
    }

    private static func managedPIDFile(home: URL) -> URL {
        home.appendingPathComponent("mac-api.pid")
    }

    private struct ManagedPIDRecord {
        var pid: Int32
        var ownerID: String?
        var databasePath: String?
        var port: Int?
    }

    private static func writeManagedPID(
        _ pid: Int32,
        home: URL,
        ownerID: String,
        database: URL,
        port: Int
    ) throws {
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        let payload: [String: Any] = [
            "pid": Int(pid),
            "ownerID": ownerID,
            "databasePath": database.path,
            "port": port
        ]
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: managedPIDFile(home: home), options: .atomic)
    }

    private static func cleanupStaleManagedProcess(home: URL, database: URL) {
        let file = managedPIDFile(home: home)
        guard let record = readManagedPID(file: file), record.pid > 1 else {
            try? FileManager.default.removeItem(at: file)
            return
        }

        guard isProcessAlive(record.pid) else {
            try? FileManager.default.removeItem(at: file)
            return
        }

        let command = commandLine(for: record.pid)
        if command.contains("apps.api") && command.contains(database.path) {
            terminatePID(record.pid)
        }
        try? FileManager.default.removeItem(at: file)
    }

    private static func readManagedPID(file: URL) -> ManagedPIDRecord? {
        guard let data = try? Data(contentsOf: file) else { return nil }
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            let pidValue = object["pid"]
            let pid: Int32?
            if let intPID = pidValue as? Int {
                pid = Int32(intPID)
            } else if let stringPID = pidValue as? String {
                pid = Int32(stringPID)
            } else {
                pid = nil
            }
            guard let pid else { return nil }
            return ManagedPIDRecord(
                pid: pid,
                ownerID: object["ownerID"] as? String,
                databasePath: object["databasePath"] as? String,
                port: object["port"] as? Int
            )
        }

        let raw = (String(data: data, encoding: .utf8) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard let pid = Int32(raw) else { return nil }
        return ManagedPIDRecord(pid: pid, ownerID: nil, databasePath: nil, port: nil)
    }

    private static func removeManagedPIDIfOwned(file: URL, ownerID: String) {
        guard let record = readManagedPID(file: file) else {
            try? FileManager.default.removeItem(at: file)
            return
        }
        guard record.ownerID == nil || record.ownerID == ownerID else {
            return
        }
        try? FileManager.default.removeItem(at: file)
    }

    private static func cleanupOrphanedManagedAPIs(database: URL) {
        let stalePIDs = apiProcessRows()
            .filter { process in
                process.ppid == 1
                    && process.command.contains("apps.api")
                    && process.command.contains("--host 127.0.0.1")
                    && process.command.contains(database.path)
                    && !process.command.contains("--port 8000")
            }
            .map(\.pid)
        terminatePIDs(stalePIDs)
    }

    private static func cleanupManagedStateProcesses(stateDir: URL) {
        let fileManager = FileManager.default
        let files = (try? fileManager.contentsOfDirectory(
            at: stateDir,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        )) ?? []

        for file in files where file.lastPathComponent.hasSuffix(".runtime.json") {
            guard let pid = readPIDFromRuntimeRecord(file) else { continue }
            terminateStateManagedPID(pid, stateDir: stateDir)
        }

        for file in files where file.pathExtension == "pid" {
            guard let raw = try? String(contentsOf: file, encoding: .utf8),
                  let pid = Int32(raw.trimmingCharacters(in: .whitespacesAndNewlines)) else { continue }
            terminateStateManagedPID(pid, stateDir: stateDir)
        }
    }

    private static func readPIDFromRuntimeRecord(_ file: URL) -> Int32? {
        guard let data = try? Data(contentsOf: file),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        let value = object["pid"]
        if let pid = value as? Int {
            return Int32(pid)
        }
        if let raw = value as? String {
            return Int32(raw)
        }
        return nil
    }

    private static func terminateStateManagedPID(_ pid: Int32, stateDir: URL) {
        guard pid > 1, isProcessAlive(pid) else { return }
        let command = commandLine(for: pid)
        guard command.contains(stateDir.path) else { return }
        let managedMarkers = [
            "apps.api",
            "apps.daemon_command",
            "apps.gateway",
            "apps.learning_worker_command"
        ]
        guard managedMarkers.contains(where: { command.contains($0) }) else { return }
        terminatePID(pid)
    }

    private struct ProcessRow {
        var pid: Int32
        var ppid: Int32
        var command: String
    }

    private struct PythonRuntime {
        var executableURL: URL
        var argumentsPrefix: [String]
        var environment: [String: String] = [:]
    }

    private static func apiProcessRows() -> [ProcessRow] {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/ps")
        process.arguments = ["-axo", "pid=,ppid=,command="]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        do {
            try process.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let output = String(data: data, encoding: .utf8) ?? ""
            return output
                .components(separatedBy: .newlines)
                .compactMap { line in
                    let trimmed = line.trimmingCharacters(in: .whitespaces)
                    guard !trimmed.isEmpty else { return nil }
                    let parts = trimmed.split(separator: " ", maxSplits: 2, omittingEmptySubsequences: true)
                    guard parts.count == 3,
                          let pid = Int32(parts[0]),
                          let ppid = Int32(parts[1])
                    else { return nil }
                    let command = String(parts[2])
                    guard command.contains("apps.api") else { return nil }
                    return ProcessRow(pid: pid, ppid: ppid, command: command)
                }
        } catch {
            return []
        }
    }

    private static func terminatePID(_ pid: Int32) {
        guard pid > 1, isProcessAlive(pid) else { return }
        _ = Darwin.kill(pid, SIGTERM)
        if !waitForExit(pid, timeout: 2.0) {
            _ = Darwin.kill(pid, SIGKILL)
            _ = waitForExit(pid, timeout: 1.0)
        }
    }

    private static func terminatePIDs(_ pids: [Int32]) {
        let livePIDs = pids.filter { $0 > 1 && isProcessAlive($0) }
        guard !livePIDs.isEmpty else { return }

        for pid in livePIDs {
            _ = Darwin.kill(pid, SIGTERM)
        }

        let deadline = Date().addingTimeInterval(1.0)
        while Date() < deadline {
            if livePIDs.allSatisfy({ !isProcessAlive($0) }) {
                return
            }
            Thread.sleep(forTimeInterval: 0.05)
        }

        for pid in livePIDs where isProcessAlive(pid) {
            _ = Darwin.kill(pid, SIGKILL)
        }
    }

    private static func isProcessAlive(_ pid: Int32) -> Bool {
        if Darwin.kill(pid, 0) == 0 {
            return true
        }
        return errno == EPERM
    }

    private static func waitForExit(_ pid: Int32, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if !isProcessAlive(pid) {
                return true
            }
            Thread.sleep(forTimeInterval: 0.05)
        }
        return !isProcessAlive(pid)
    }

    private static func commandLine(for pid: Int32) -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/ps")
        process.arguments = ["-p", "\(pid)", "-o", "command="]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        do {
            try process.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            return String(data: data, encoding: .utf8) ?? ""
        } catch {
            return ""
        }
    }

    private static func resolveInstalledPythonIfNeeded(
        repoRoot: URL?,
        data: (home: URL, herd: URL, database: URL)
    ) async throws -> URL? {
        guard repoRoot == nil else { return nil }
        return try await Task.detached(priority: .userInitiated) {
            try ensureInstalledRuntime(data: data)
        }.value
    }

    private static func ensureInstalledRuntime(data: (home: URL, herd: URL, database: URL)) throws -> URL {
        let fileManager = FileManager.default
        let runtimePython = data.home.appendingPathComponent("venv/bin/python")
        let desiredStamp = bundleRuntimeStamp()
        let existingStamp = readRuntimeStamp(home: data.home)
        let runtimeExists = fileManager.isExecutableFile(atPath: runtimePython.path)
        if runtimeExists && existingStamp == desiredStamp {
            return runtimePython
        }

        guard let installer = Bundle.main.url(forResource: "install", withExtension: "sh", subdirectory: "Install") else {
            throw CoreRunnerError.runtimeMissing("The app bundle does not include Install/install.sh.")
        }

        try fileManager.createDirectory(at: data.home, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: data.herd, withIntermediateDirectories: true)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [
            installer.path,
            runtimeExists ? "upgrade" : "install",
            "--install-root",
            data.home.path,
            "--bin-dir",
            fileManager.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin").path,
            "--skip-run"
        ]

        var environment = ProcessInfo.processInfo.environment
        environment["ELEPHANT_HOME"] = data.home.path
        environment["ELEPHANT_HERD_DIR"] = data.herd.path
        process.environment = environment

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        try process.run()
        let output = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()

        guard process.terminationStatus == 0, fileManager.isExecutableFile(atPath: runtimePython.path) else {
            let detail = String(data: output, encoding: .utf8) ?? "Installer exited with status \(process.terminationStatus)."
            throw CoreRunnerError.installerFailed(detail.trimmingCharacters(in: .whitespacesAndNewlines))
        }

        try writeRuntimeStamp(desiredStamp, home: data.home)
        return runtimePython
    }

    private static func runtimeStampFile(home: URL) -> URL {
        home.appendingPathComponent(runtimeStampFileName)
    }

    private static func bundleRuntimeStamp() -> String {
        let info = Bundle.main.infoDictionary ?? [:]
        let bundleID = (info["CFBundleIdentifier"] as? String) ?? "ai.agentic.elephant.mac"
        let shortVersion = (info["CFBundleShortVersionString"] as? String) ?? "0"
        let build = (info["CFBundleVersion"] as? String) ?? "0"
        return [bundleID, shortVersion, build].joined(separator: ":")
    }

    private static func readRuntimeStamp(home: URL) -> String? {
        try? String(contentsOf: runtimeStampFile(home: home), encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func writeRuntimeStamp(_ stamp: String, home: URL) throws {
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        try "\(stamp)\n".write(to: runtimeStampFile(home: home), atomically: true, encoding: .utf8)
    }

    private static func resolvePythonRuntime(
        repoRoot: URL?,
        data: (home: URL, herd: URL, database: URL)
    ) async throws -> PythonRuntime {
        if let repoRoot {
            if let python = repoPythonCandidates(repoRoot: repoRoot, data: data).first(where: { FileManager.default.isExecutableFile(atPath: $0.path) }) {
                return PythonRuntime(executableURL: python, argumentsPrefix: [])
            }
            return PythonRuntime(executableURL: URL(fileURLWithPath: "/usr/bin/env"), argumentsPrefix: ["python3"])
        }

        if let bundled = bundledPythonRuntime() {
            return bundled
        }

        guard let runtimePython = try await resolveInstalledPythonIfNeeded(repoRoot: nil, data: data) else {
            throw CoreRunnerError.runtimeMissing("No Python runtime was resolved.")
        }
        return PythonRuntime(executableURL: runtimePython, argumentsPrefix: [])
    }

    private static func bundledPythonRuntime() -> PythonRuntime? {
        let fileManager = FileManager.default
        guard let resources = Bundle.main.resourceURL else { return nil }
        let runtime = resources.appendingPathComponent("Runtime")
        let manifest = runtime.appendingPathComponent("manifest.json")
        guard fileManager.fileExists(atPath: manifest.path) else { return nil }

        let pythonCandidates = [
            runtime.appendingPathComponent("python/bin/python3.12"),
            runtime.appendingPathComponent("python/bin/python3"),
            runtime.appendingPathComponent("python/bin/python")
        ]
        guard let python = pythonCandidates.first(where: { fileManager.isExecutableFile(atPath: $0.path) }) else {
            return nil
        }

        let sitePackages = runtime.appendingPathComponent("site-packages")
        var environment: [String: String] = [
            "ELEPHANT_MAC_BUNDLED_RUNTIME": "1",
            "PYTHONNOUSERSITE": "1"
        ]
        if fileManager.fileExists(atPath: sitePackages.path) {
            environment["PYTHONPATH"] = sitePackages.path
        }
        let browsers = runtime.appendingPathComponent("ms-playwright")
        if fileManager.fileExists(atPath: browsers.path) {
            environment["PLAYWRIGHT_BROWSERS_PATH"] = browsers.path
            environment["PLAYWRIGHT_SKIP_BROWSER_GC"] = "1"
        }
        return PythonRuntime(executableURL: python, argumentsPrefix: [], environment: environment)
    }

    private static func repoPythonCandidates(
        repoRoot: URL,
        data: (home: URL, herd: URL, database: URL)
    ) -> [URL] {
        let env = ProcessInfo.processInfo.environment
        let explicit = ["ELEPHANT_MAC_PYTHON", "PYTHON"]
            .compactMap { env[$0] }
            .filter { !$0.isEmpty }
            .map { URL(fileURLWithPath: $0) }
        let bundled = Bundle.main.url(forResource: "PythonPath", withExtension: "txt")
            .flatMap { try? String(contentsOf: $0).trimmingCharacters(in: .whitespacesAndNewlines) }
            .flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: $0) }
            .map { [$0] } ?? []
        return explicit + bundled + [
            repoRoot.appendingPathComponent(".venv/bin/python"),
            repoRoot.appendingPathComponent(".venv/bin/python3"),
            data.home.appendingPathComponent("venv/bin/python"),
            URL(fileURLWithPath: "/opt/homebrew/bin/python3"),
            URL(fileURLWithPath: "/usr/local/bin/python3")
        ]
    }

    private static func tailLog(_ file: URL?, maxBytes: Int = 4_000) -> String {
        guard let file, let data = try? Data(contentsOf: file), !data.isEmpty else { return "" }
        let tail = data.count > maxBytes ? Data(data.suffix(maxBytes)) : data
        return (String(data: tail, encoding: .utf8) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func freeLoopbackPort() throws -> Int {
        let socketFD = socket(AF_INET, SOCK_STREAM, 0)
        guard socketFD >= 0 else { throw CoreRunnerError.portUnavailable }
        defer { close(socketFD) }

        var value: Int32 = 1
        setsockopt(socketFD, SOL_SOCKET, SO_REUSEADDR, &value, socklen_t(MemoryLayout<Int32>.size))

        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = 0
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))

        let bindResult = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { socketAddress in
                bind(socketFD, socketAddress, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bindResult == 0 else { throw CoreRunnerError.portUnavailable }

        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        let nameResult = withUnsafeMutablePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { socketAddress in
                getsockname(socketFD, socketAddress, &length)
            }
        }
        guard nameResult == 0 else { throw CoreRunnerError.portUnavailable }
        return Int(UInt16(bigEndian: address.sin_port))
    }
}

enum CoreRunnerError: LocalizedError {
    case runtimeMissing(String)
    case installerFailed(String)
    case portUnavailable
    case processExited(String)
    case notReady(String)

    var errorDescription: String? {
        switch self {
        case .runtimeMissing(let detail):
            return "Could not prepare the local Elephant runtime. \(detail)"
        case .installerFailed(let detail):
            return "The bundled installer could not prepare the local Elephant runtime. \(detail)"
        case .portUnavailable:
            return "Could not reserve a local API port."
        case .processExited(let detail):
            let trimmed = detail.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty
                ? "The Python API exited before it became ready."
                : "The Python API exited before it became ready.\n\(trimmed)"
        case .notReady(let detail):
            return "The local API did not become ready. \(detail)"
        }
    }
}
