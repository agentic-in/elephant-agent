import Foundation

struct WakeReply {
    var episodeID: String?
    var text: String
    var toolEvents: [ToolUseEvent]
}

struct WakeStreamEvent {
    var type: String
    var textDelta: String = ""
    var reasoningDelta: String = ""
    var toolEvent: ToolUseEvent?
    var reply: WakeReply?
    var stage: String = ""
    var detail: String = ""
    var error: String = ""
}

struct APIClient {
    var baseURL: URL?
    private let session: URLSession
    private static let loopTimeout: TimeInterval = 60 * 60 * 6

    init(baseURL: URL?) {
        self.baseURL = baseURL
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = Self.loopTimeout
        configuration.timeoutIntervalForResource = Self.loopTimeout
        self.session = URLSession(configuration: configuration)
    }

    func fetchSnapshot() async throws -> DashboardSnapshot {
        guard let baseURL else { return .empty }
        let sections = [
            "overview",
            "chat",
            "questions",
            "skills",
            "tools",
            "gateway",
            "cron",
            "runtime",
            "reflect",
            "providers",
            "personal-models",
            "diary",
            "usage",
            "settings",
            "logs",
        ]
        let dashboards = try await withThrowingTaskGroup(of: (String, [String: Any]).self) { group in
            for section in sections {
                group.addTask {
                    let json = try await request(path: "/v1/internal/dashboard/\(section)", method: "GET")
                    return (section, json["dashboard"] as? [String: Any] ?? [:])
                }
            }
            var result: [String: [String: Any]] = [:]
            for try await (section, dashboard) in group {
                result[section] = dashboard
            }
            return result
        }
        return SnapshotParser.parse(dashboards: dashboards, apiURL: baseURL.absoluteString)
    }

    func configureProvider(
        providerID: String,
        baseURL: String,
        modelID: String,
        apiKey: String,
        contextWindow: String
    ) async throws {
        let resolvedProviderID = providerID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !resolvedProviderID.isEmpty else { return }

        let profileID = "provider-\(resolvedProviderID)"
        let secretReferenceID = "secret-\(profileID)-api-key"
        var metadata: [String: String] = ["context_window_mode": contextWindow.isEmpty ? "auto" : "manual"]
        if !contextWindow.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            metadata["context_window_tokens"] = contextWindow.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        var providerProfile: [String: Any] = [
            "profile_id": profileID,
            "provider_id": resolvedProviderID,
            "metadata": metadata
        ]

        let trimmedBaseURL = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedModelID = modelID.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedBaseURL.isEmpty {
            providerProfile["base_url"] = trimmedBaseURL
        }
        if !trimmedModelID.isEmpty {
            providerProfile["default_model"] = trimmedModelID
        }

        let trimmedKey = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let secretMetadata = Self.defaultProviderSecretMetadata(providerID: resolvedProviderID)
        let needsSecret = !trimmedKey.isEmpty
            || secretMetadata != nil
            || resolvedProviderID == "openai-compatible"
            || resolvedProviderID.contains("openai")
        if needsSecret {
            providerProfile["secret_references"] = [[
                "reference_id": secretReferenceID,
                "provider_id": resolvedProviderID,
                "secret_name": "api_token",
                "secret_key": "api_key",
                "source": "workspace",
                "metadata": secretMetadata ?? ["storage": "local-vault"]
            ]]
        }

        _ = try await request(
            path: "/v1/providers/default",
            method: "POST",
            body: ["provider_profile": providerProfile]
        )

        if !trimmedKey.isEmpty {
            _ = try await request(
                path: "/v1/providers/keys",
                method: "POST",
                body: [
                    "profileId": profileID,
                    "providerId": resolvedProviderID,
                    "referenceId": secretReferenceID,
                    "secretKey": "api_key",
                    "secretName": "api_token",
                    "value": trimmedKey,
                    "metadata": ["storage": "local-vault"]
                ]
            )
        }
    }

    private static func defaultProviderSecretMetadata(providerID: String) -> [String: String]? {
        switch providerID.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "copilot":
            return ["storage": "local-vault", "env_var": "COPILOT_GITHUB_TOKEN"]
        default:
            return nil
        }
    }

    func configureLocalEmbedding(source: String, forceDownload: Bool) async throws {
        let normalizedSource = source.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let resolvedSource = normalizedSource == "modelscope" ? "modelscope" : "huggingface"
        _ = try await request(
            path: "/v1/providers/embeddings",
            method: "POST",
            body: [
                "source": "local",
                "modelSource": resolvedSource,
                "forceDownload": forceDownload
            ]
        )
    }

    func createElephant(name: String, identityText: String) async throws -> String {
        let json = try await request(
            path: "/v1/herd",
            method: "POST",
            body: [
                "display_name": name,
                "elephant_identity_text": identityText
            ]
        )
        if let elephant = json["elephant"] as? [String: Any] {
            return SnapshotParser.findString(in: elephant, keys: ["state_id", "stateId"]) ?? ""
        }
        return SnapshotParser.findString(in: json, keys: ["state_id", "stateId"]) ?? ""
    }

    func createHerdElephant(
        name: String,
        identityText: String
    ) async throws -> String {
        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedName.isEmpty else { return "" }
        var body: [String: Any] = [
            "display_name": trimmedName
        ]
        let identity = identityText.trimmingCharacters(in: .whitespacesAndNewlines)
        if !identity.isEmpty {
            body["elephant_identity_text"] = identity
        }
        let json = try await request(path: "/v1/herd", method: "POST", body: body)
        let elephant = SnapshotParser.findDictionary(in: json, keys: ["elephant", "state", "item"]) ?? [:]
        return SnapshotParser.findString(in: elephant, keys: ["state_id", "stateId", "elephant_id", "elephantId"])
            ?? SnapshotParser.findString(in: json, keys: ["state_id", "stateId", "elephant_id", "elephantId"])
            ?? ""
    }

    func updateHerdElephant(
        _ item: HerdItem,
        name: String,
        identityText: String
    ) async throws {
        let elephantID = item.elephantID.isEmpty ? item.id.replacingOccurrences(of: "state:", with: "") : item.elephantID
        guard !elephantID.isEmpty else { return }
        let body: [String: Any] = [
            "display_name": name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? item.title : name,
            "elephant_identity_text": identityText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? item.identityText : identityText
        ]
        _ = try await request(path: "/v1/herd/\(Self.pathSegment(elephantID))", method: "PATCH", body: body)
    }

    func deleteHerdElephant(_ item: HerdItem) async throws {
        let elephantID = item.elephantID.isEmpty ? item.id.replacingOccurrences(of: "state:", with: "") : item.elephantID
        guard !elephantID.isEmpty else { return }
        _ = try await request(path: "/v1/herd/\(Self.pathSegment(elephantID))", method: "DELETE")
    }

    func updateUserProfile(
        stateID: String,
        preferredName: String,
        occupation: String,
        school: String = "",
        city: String,
        gender: String,
        birthDate: String,
        mbti: String,
        hobbies: String,
        dream: String = "",
        creativeHobby: String = "",
        mediaHobby: String = "",
        movementHobby: String = "",
        safetyBoundaries: String,
        firstLanguage: String,
        blogURL: String = "",
        linkedInURL: String = "",
        twitterURL: String = "",
        personalLogoPath: String = "",
        innerLandscape: String = "",
        valueAnchor: String = "",
        pressurePattern: String = "",
        recoveryStyle: String = "",
        decisionCompass: String = "",
        groundingAnswers: [OnboardingGroundingAnswerRecord] = []
    ) async throws {
        guard !stateID.isEmpty else { return }
        let fields: [String: String] = [
            "preferred_name": preferredName,
            "current_work": occupation,
            "school": school,
            "current_city": city,
            "gender": gender,
            "birth_date": birthDate,
            "mbti": mbti,
            "hobbies": hobbies,
            "dream": dream,
            "creative_hobby": creativeHobby,
            "media_hobby": mediaHobby,
            "movement_hobby": movementHobby,
            "boundaries": safetyBoundaries,
            "safety_boundaries": safetyBoundaries,
            "first_language": firstLanguage
        ].filter { !$0.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

        let durableNotes: [String: String] = [
            "blog": blogURL,
            "linkedin": linkedInURL,
            "twitter": twitterURL,
            "personal_logo": personalLogoPath,
            "inner_landscape": innerLandscape,
            "value_anchor": valueAnchor,
            "pressure_pattern": pressurePattern,
            "recovery_style": recoveryStyle,
            "decision_compass": decisionCompass
        ].filter { !$0.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

        let groundingPayload = groundingAnswers.map(\.payload)
        guard !fields.isEmpty || !durableNotes.isEmpty || !groundingPayload.isEmpty else { return }
        let lines = (fields.map { "\($0.key): \($0.value)" } + durableNotes.map { "\($0.key): \($0.value)" })
            .sorted()
            .joined(separator: "\n")
        var body: [String: Any] = [
            "append": true,
            "fields": fields,
            "durable_fields": durableNotes,
            "split_personal_model_facts": true,
            "text": lines
        ]
        if !groundingPayload.isEmpty {
            body["grounding_answers"] = groundingPayload
        }
        _ = try await request(
            path: "/v1/states/\(stateID)/user",
            method: "POST",
            body: body
        )
    }

    func configureLearningIntensity(_ intensity: String) async throws {
        let value = intensity.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard ["low", "medium", "high"].contains(value) else { return }
        _ = try await request(
            path: "/v1/operator/personal-model/questions",
            method: "PATCH",
            body: ["learning_intensity": value]
        )
    }

    func bumpPersonalModelQuestion(_ questionID: String, personalModelID: String) async throws {
        _ = try await request(
            path: "/v1/operator/personal-model/questions/\(Self.pathSegment(questionID))/bump",
            method: "POST",
            body: ["personal_model_id": personalModelID]
        )
    }

    func dismissPersonalModelQuestion(_ questionID: String, personalModelID: String) async throws {
        _ = try await request(
            path: "/v1/operator/personal-model/questions/\(Self.pathSegment(questionID))/dismiss",
            method: "POST",
            body: [
                "personal_model_id": personalModelID,
                "reason": "desktop dismissed"
            ]
        )
    }

    func answerPersonalModelQuestion(_ questionID: String, content: String, personalModelID: String, episodeID: String) async throws {
        _ = try await request(
            path: "/v1/operator/personal-model/questions/\(Self.pathSegment(questionID))/answer",
            method: "POST",
            body: [
                "personal_model_id": personalModelID,
                "episode_id": episodeID.isEmpty ? "desktop" : episodeID,
                "content": content
            ]
        )
    }

    @discardableResult
    func runReflect(trigger: String, features: String? = nil) async throws -> String {
        var body: [String: Any] = ["trigger": trigger]
        if let features, !features.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            body["features"] = features
        }
        let json = try await request(
            path: "/v1/internal/reflect/run",
            method: "POST",
            body: body
        )
        return SnapshotParser.findString(in: json, keys: ["job_id", "jobId", "id"]) ?? ""
    }

    func writeDiary(targetDate: String) async throws {
        _ = try await request(
            path: "/v1/internal/diary/write",
            method: "POST",
            body: ["date": targetDate]
        )
    }

    func updatePersonalModelClaim(
        claimRef: String,
        action: String,
        lens: String,
        text: String
    ) async throws {
        let normalizedAction = action.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard ["correct", "forget", "restore", "delete"].contains(normalizedAction) else { return }
        var body: [String: Any] = [
            "lens": lens.isEmpty ? "identity" : lens,
            "reason": "macos app action"
        ]
        if normalizedAction == "correct" {
            body["text"] = text
        }
        _ = try await request(
            path: "/v1/operator/personal-model/claims/\(Self.pathSegment(claimRef))/\(normalizedAction)",
            method: "POST",
            body: body
        )
    }

    func testProvider() async throws -> String {
        let json = try await request(
            path: "/v1/providers/test",
            method: "POST",
            body: ["prompt": "Reply with one short sentence confirming the provider is ready."]
        )
        return SnapshotParser.firstText(in: json) ?? "Provider test completed."
    }

    func discoverProviderModels(providerID: String, baseURL: String, apiKey: String) async throws -> [ProviderModelOption] {
        let json = try await request(
            path: "/v1/providers/models",
            method: "POST",
            body: [
                "providerId": providerID,
                "baseUrl": baseURL,
                "apiKey": apiKey
            ]
        )
        let rows = json["models"] as? [[String: Any]] ?? []
        return SnapshotParser.providerModelOptions(fromDiscoveredRows: rows, providerRow: [:], defaultModel: "")
    }

    func setConsoleItemEnabled(kind: String, itemID: String, enabled: Bool) async throws {
        let normalizedKind = kind == "skills" ? "skills" : "tools"
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/")
        let encodedID = itemID.addingPercentEncoding(withAllowedCharacters: allowed) ?? itemID
        _ = try await request(
            path: "/v1/operator/\(normalizedKind)/\(encodedID)",
            method: "PATCH",
            body: ["enabled": enabled]
        )
    }

    func discoverMCPServer(payload: [String: Any]) async throws -> MCPDiscoveryResult {
        let json = try await request(
            path: "/v1/operator/mcp/discover",
            method: "POST",
            body: payload
        )
        return SnapshotParser.mcpDiscoveryResult(from: json)
    }

    func syncMCPServer(payload: [String: Any]) async throws -> String {
        let json = try await request(
            path: "/v1/operator/mcp/servers",
            method: "POST",
            body: payload
        )
        return SnapshotParser.findString(in: json, keys: ["runtimeStatus", "status"]) ?? ""
    }

    func deleteMCPServer(serverID: String) async throws -> String {
        let json = try await request(
            path: "/v1/operator/mcp/servers",
            method: "DELETE",
            body: ["serverId": serverID]
        )
        return SnapshotParser.findString(in: json, keys: ["runtimeStatus", "status"]) ?? ""
    }

    func setMCPToolEnabled(serverID: String, toolName: String, enabled: Bool) async throws -> String {
        let json = try await request(
            path: "/v1/operator/mcp/tools/enabled",
            method: "PATCH",
            body: [
                "serverId": serverID,
                "toolName": toolName,
                "enabled": enabled
            ]
        )
        return SnapshotParser.findString(in: json, keys: ["runtimeStatus", "status"]) ?? ""
    }

    func saveGlobalConfig(yamlText: String) async throws {
        _ = try await request(
            path: "/v1/operator/config",
            method: "PATCH",
            body: ["yamlText": yamlText]
        )
    }

    func runGatewayAction(
        service: String,
        action: String,
        accountID: String,
        transport: String,
        force: Bool
    ) async throws -> String {
        var body: [String: Any] = [
            "service": service,
            "action": action
        ]
        if !accountID.isEmpty {
            body["accountId"] = accountID
        }
        if !transport.isEmpty {
            body["transport"] = transport
        }
        if force {
            body["force"] = true
        }
        let json = try await request(path: "/v1/operator/gateway", method: "POST", body: body)
        let status = SnapshotParser.findString(in: json, keys: ["status"]) ?? "ok"
        if status == "ok" {
            return "\(service) \(action) completed."
        }
        let stderr = SnapshotParser.findString(in: json, keys: ["stderr"]) ?? ""
        throw APIClientError.badStatus(stderr.isEmpty ? "\(service) \(action) returned \(status)." : stderr)
    }

    func configureGatewayService(
        service: String,
        accountID: String,
        transport: String,
        secrets: [String: String]
    ) async throws -> String {
        let filteredSecrets = secrets.filter { !$0.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        let json = try await request(
            path: "/v1/operator/gateway",
            method: "POST",
            body: [
                "service": service,
                "action": "configure",
                "config": [
                    "accountId": accountID.isEmpty ? "default" : accountID,
                    "transport": transport,
                    "secrets": filteredSecrets
                ]
            ]
        )
        return SnapshotParser.findString(in: json, keys: ["status"]) ?? "configured"
    }

    func startWeixinQR() async throws -> GatewayQRState {
        let json = try await request(
            path: "/v1/operator/gateway",
            method: "POST",
            body: [
                "service": "weixin",
                "action": "qr-start",
                "config": ["transport": "ilink"]
            ]
        )
        return SnapshotParser.gatewayQRState(from: json)
    }

    func pollWeixinQR(sessionID: String) async throws -> GatewayQRState {
        let json = try await request(
            path: "/v1/operator/gateway",
            method: "POST",
            body: [
                "service": "weixin",
                "action": "qr-poll",
                "sessionId": sessionID
            ]
        )
        return SnapshotParser.gatewayQRState(from: json)
    }

    func createCronJob(
        name: String,
        schedule: String,
        prompt: String,
        elephantID: String,
        profileID: String
    ) async throws {
        var body: [String: Any] = [
            "name": name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "Elephant Agent job" : name,
            "schedule": schedule,
            "job_kind": "prompt",
            "prompt": prompt
        ]
        if !elephantID.isEmpty { body["elephant_id"] = elephantID }
        if !profileID.isEmpty { body["profile_id"] = profileID }
        _ = try await request(path: "/v1/operator/cron", method: "POST", body: body)
    }

    func runCronJob(_ jobID: String) async throws {
        _ = try await request(path: "/v1/operator/cron/\(Self.pathSegment(jobID))/run", method: "POST", body: [:])
    }

    func setCronJobStatus(_ jobID: String, action: String) async throws {
        _ = try await request(
            path: "/v1/operator/cron/\(Self.pathSegment(jobID))",
            method: "PATCH",
            body: ["action": action]
        )
    }

    func deleteCronJob(_ jobID: String) async throws {
        _ = try await request(path: "/v1/operator/cron/\(Self.pathSegment(jobID))", method: "DELETE")
    }

    func sendWakeMessage(
        _ text: String,
        personalModelID: String,
        elephantID: String,
        activeEpisodeID: String
    ) async throws -> WakeReply {
        let episodeID = try await ensureWakeEpisode(
            personalModelID: personalModelID,
            elephantID: elephantID,
            activeEpisodeID: activeEpisodeID
        )

        return try await runWakeLoop(text, episodeID: episodeID)
    }

    func ensureWakeEpisode(
        personalModelID: String,
        elephantID: String,
        activeEpisodeID: String
    ) async throws -> String {
        var episodeID = activeEpisodeID
        if episodeID.isEmpty {
            let profile = personalModelID.isEmpty ? "you" : personalModelID
            let payload: [String: Any] = [
                "profile_id": profile,
                "display_name": "Chat",
                "elephant_id": elephantID.replacingOccurrences(of: "state:", with: ""),
                "preferences": ["desktop", "native"],
                "enabled_capabilities": []
            ]
            let json = try await request(path: "/v1/episodes", method: "POST", body: payload)
            episodeID = SnapshotParser.findString(in: json, keys: ["episode_id", "episodeId", "id"]) ?? ""
            if episodeID.isEmpty, let episode = SnapshotParser.findDictionary(in: json, keys: ["episode"]) {
                episodeID = SnapshotParser.findString(in: episode, keys: ["episode_id", "episodeId", "id"]) ?? ""
            }
        }

        if episodeID.isEmpty {
            throw APIClientError.missingEpisode
        }

        return episodeID
    }

    func runWakeLoop(_ text: String, episodeID: String) async throws -> WakeReply {
        let result = try await request(
            path: "/v1/episodes/\(episodeID)/loops",
            method: "POST",
            body: ["prompt": text]
        )
        let reply = SnapshotParser.loopReplyText(in: result) ?? "I processed that chat and refreshed the local state."
        var toolEvents = SnapshotParser.toolUseEvents(in: result)
        if toolEvents.isEmpty {
            toolEvents = (try? await fetchToolUseEvents(episodeID: episodeID)) ?? []
        }
        return WakeReply(episodeID: episodeID, text: reply, toolEvents: toolEvents)
    }

    func streamWakeLoop(_ text: String, episodeID: String) -> AsyncThrowingStream<WakeStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let client = self
            let task = Task.detached(priority: .userInitiated) {
                do {
                    try await client.consumeWakeLoopStream(text, episodeID: episodeID, continuation: continuation)
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in
                task.cancel()
            }
        }
    }

    func fetchToolUseEvents(episodeID: String) async throws -> [ToolUseEvent] {
        let json = try await request(path: "/v1/internal/dashboard/chat", method: "GET")
        guard let dashboard = json["dashboard"] as? [String: Any],
              let runtime = dashboard["runtime"] as? [String: Any],
              let traces = runtime["episode_traces"] as? [[String: Any]] else {
            return SnapshotParser.toolUseEvents(in: json)
        }

        for trace in traces {
            let candidate = SnapshotParser.findString(in: trace, keys: ["episode_id", "episodeId", "id"]) ?? ""
            if candidate == episodeID {
                return SnapshotParser.toolUseEvents(in: trace)
            }
        }
        return SnapshotParser.toolUseEvents(in: dashboard)
    }

    private func consumeWakeLoopStream(
        _ text: String,
        episodeID: String,
        continuation: AsyncThrowingStream<WakeStreamEvent, Error>.Continuation
    ) async throws {
        guard let baseURL else { throw APIClientError.missingBaseURL }
        let normalizedPath = "v1/episodes/\(Self.pathSegment(episodeID))/loops/stream"
        let url = URL(string: normalizedPath, relativeTo: baseURL)?.absoluteURL
            ?? baseURL.appendingPathComponent(normalizedPath)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = Self.loopTimeout
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["prompt": text])

        let (bytes, response) = try await session.bytes(for: request)
        let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(statusCode) else {
            throw APIClientError.badStatus(try await Self.streamErrorDetail(from: bytes, statusCode: statusCode))
        }

        var dataLines: [String] = []
        var lineBuffer = Data()

        func consumeLine(_ rawLine: String) {
            var line = rawLine
            if line.hasSuffix("\r") {
                line.removeLast()
            }
            if line.isEmpty {
                if let event = Self.decodeWakeStreamEvent(dataLines.joined(separator: "\n"), episodeID: episodeID) {
                    continuation.yield(event)
                }
                dataLines.removeAll()
                return
            }
            if line.hasPrefix("data:") {
                var dataLine = String(line.dropFirst(5))
                if dataLine.hasPrefix(" ") {
                    dataLine.removeFirst()
                }
                dataLines.append(dataLine)
            }
        }

        for try await byte in bytes {
            if Task.isCancelled { break }
            if byte == 10 {
                consumeLine(String(data: lineBuffer, encoding: .utf8) ?? "")
                lineBuffer.removeAll(keepingCapacity: true)
                continue
            }
            lineBuffer.append(byte)
        }
        if !lineBuffer.isEmpty {
            consumeLine(String(data: lineBuffer, encoding: .utf8) ?? "")
        }
        if !dataLines.isEmpty, let event = Self.decodeWakeStreamEvent(dataLines.joined(separator: "\n"), episodeID: episodeID) {
            continuation.yield(event)
        }
    }

    private static func decodeWakeStreamEvent(_ payload: String, episodeID: String) -> WakeStreamEvent? {
        let trimmed = payload.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed != "[DONE]" else { return nil }
        let data = Data(trimmed.utf8)
        guard let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            return nil
        }
        let type = object["type"] as? String ?? "message"

        if type == "assistant.delta" {
            return WakeStreamEvent(type: type, textDelta: object["delta"] as? String ?? "")
        }
        if type == "assistant.reasoning.delta" {
            return WakeStreamEvent(type: type, reasoningDelta: object["delta"] as? String ?? "")
        }
        if type == "loop.started" {
            let message = object["message"] as? String ?? "Opening a live chat loop"
            return WakeStreamEvent(
                type: type,
                toolEvent: ToolUseEvent(
                    sourceID: "loop.started",
                    name: "Chat loop",
                    status: "running",
                    arguments: message,
                    result: ""
                ),
                detail: message
            )
        }
        if type == "tool.lifecycle" {
            return WakeStreamEvent(type: type, toolEvent: SnapshotParser.toolUseEvents(in: object).first)
        }
        if type == "kernel.stage" {
            return WakeStreamEvent(
                type: type,
                toolEvent: ToolUseEvent(
                    sourceID: String(describing: object["id"] ?? object["stream_sequence"] ?? ""),
                    name: stageTitle(object["stage"] as? String ?? "Working"),
                    status: object["status"] as? String ?? "running",
                    arguments: object["detail"] as? String ?? "",
                    result: object["result"] as? String ?? ""
                ),
                stage: object["stage"] as? String ?? "",
                detail: object["detail"] as? String ?? ""
            )
        }
        if type == "loop.completed" {
            let replyPayload = object["reply"] as? [String: Any] ?? object
            let replyText = SnapshotParser.loopReplyText(in: object)
                ?? SnapshotParser.loopReplyText(in: replyPayload)
                ?? "I processed that chat and refreshed the local state."
            let toolEvents = SnapshotParser.toolUseEvents(in: replyPayload)
            return WakeStreamEvent(
                type: type,
                reply: WakeReply(episodeID: episodeID, text: replyText, toolEvents: toolEvents)
            )
        }
        if type == "loop.failed" {
            return WakeStreamEvent(type: type, error: object["error"] as? String ?? "The chat loop stopped before it finished.")
        }
        return WakeStreamEvent(type: type)
    }

    private static func streamErrorDetail(from bytes: URLSession.AsyncBytes, statusCode: Int) async throws -> String {
        var data = Data()
        for try await byte in bytes {
            if data.count >= 4096 { break }
            data.append(byte)
        }
        guard !data.isEmpty else { return "HTTP \(statusCode)" }
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let detail = object["detail"] as? String, !detail.isEmpty {
                return detail
            }
            if let error = object["error"] as? String, !error.isEmpty {
                return error
            }
        }
        if let text = String(data: data, encoding: .utf8) {
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty {
                return trimmed
            }
        }
        return "HTTP \(statusCode)"
    }

    private static func stageTitle(_ raw: String) -> String {
        let normalized = raw.replacingOccurrences(of: "_", with: " ").replacingOccurrences(of: "-", with: " ")
        guard !normalized.isEmpty else { return "Working" }
        return normalized
            .split(separator: " ")
            .map { word in word.prefix(1).uppercased() + String(word.dropFirst()) }
            .joined(separator: " ")
    }

    private func request(path: String, method: String, body: [String: Any]? = nil) async throws -> [String: Any] {
        guard let baseURL else { throw APIClientError.missingBaseURL }
        let normalizedPath = path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let url = URL(string: normalizedPath, relativeTo: baseURL)?.absoluteURL
            ?? baseURL.appendingPathComponent(normalizedPath)
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = Self.loopTimeout
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await session.data(for: request)
        let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0
        let object = try JSONSerialization.jsonObject(with: data)
        let json = object as? [String: Any] ?? [:]
        guard (200..<300).contains(statusCode) else {
            let error = json["error"] as? String
            let detail = json["detail"] as? String
            let missing = json["missing"] as? String
            let message = [detail, error, missing.map { "missing \($0)" }]
                .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
                .joined(separator: ": ")
            let resolvedMessage = message.isEmpty ? "HTTP \(statusCode)" : message
            throw APIClientError.badStatus(resolvedMessage)
        }
        return json
    }

    private static func pathSegment(_ value: String) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/")
        return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
    }
}

enum APIClientError: LocalizedError {
    case missingBaseURL
    case missingEpisode
    case badStatus(String)

    var errorDescription: String? {
        switch self {
        case .missingBaseURL:
            return "The local API is not ready yet."
        case .missingEpisode:
                return "Could not open a chat episode."
        case .badStatus(let detail):
            return detail
        }
    }
}

enum SnapshotParser {
    private static let chatTimelineStepLimit = 120

    static func parse(dashboards: [String: [String: Any]], apiURL: String) -> DashboardSnapshot {
        var snapshot = DashboardSnapshot.empty
        snapshot.apiURL = apiURL

        let overviewRoot = dashboards["overview"] ?? [:]
        let overview = overviewRoot["overview"] as? [String: Any] ?? [:]
        let meta = overviewRoot["meta"] as? [String: Any] ?? [:]
        let counts = overview["counts"] as? [String: Any] ?? [:]

        snapshot.databasePath = string(meta["database_path"])
        snapshot.providerStatus = string(overview["provider_status"], fallback: "unknown")
        snapshot.semanticStatus = string(overview["semantic_index_status"], fallback: "unknown")
        snapshot.currentPersonalModelID = string(overview["current_personal_model_id"])
        snapshot.currentStateID = string(overview["current_state_id"])
        snapshot.states = int(counts["states"])
        snapshot.episodes = int(counts["episodes"])
        snapshot.loops = int(counts["loops"])
        snapshot.steps = int(counts["steps"])
        snapshot.semanticEntries = int(counts["semantic_index_entries"])

        let herdStateRows = overviewRoot["states"] as? [[String: Any]] ?? []
        let herdStateRowsByID = Dictionary(uniqueKeysWithValues: herdStateRows.compactMap { row -> (String, [String: Any])? in
            let stateID = string(row["state_id"] ?? row["stateId"])
            guard !stateID.isEmpty else { return nil }
            return (stateID, row)
        })
        let herd = overviewRoot["herd"] as? [[String: Any]] ?? []
        snapshot.herdItems = herd.compactMap { row in
            let id = string(row["state_id"] ?? row["stateId"] ?? row["elephant_id"] ?? row["elephantId"])
            let stateRow = herdStateRowsByID[id] ?? [:]
            let elephantID = string(row["elephant_id"] ?? row["elephantId"])
            let name = displayNameForState(row)
            guard !name.isEmpty || !id.isEmpty else { return nil }
            let profile = string(row["personal_model_id"] ?? row["personalModelId"])
            let identityFile = object(row["elephant_identity_file"] ?? row["elephantIdentityFile"])
            let metadata = object(row["metadata"] ?? row["metadata_json"] ?? row["metadataJson"] ?? stateRow["metadata"] ?? stateRow["metadata_json"] ?? stateRow["metadataJson"])
            return HerdItem(
                id: id.isEmpty ? name : id,
                elephantID: elephantID,
                title: name.isEmpty ? titleCaseIdentifier(id) : name,
                subtitle: "ELEPHANT.md",
                profileID: profile,
                current: herdItemIsCurrent(id: id, profile: profile, snapshot: snapshot),
                status: string(row["status"], fallback: "ready"),
                stage: string(row["stage"]),
                level: int(row["level"]),
                progressPercent: double(row["progress_percent"] ?? row["progressPercent"]),
                scoreToNextLevel: int(row["score_to_next_level"] ?? row["scoreToNextLevel"]),
                summary: string(row["summary"] ?? row["current_context_note"] ?? row["currentContextNote"]),
                identityText: string(row["elephant_identity_text"] ?? row["elephantIdentityText"] ?? identityFile["text"]),
                createdAt: string(row["created_at"] ?? row["createdAt"] ?? stateRow["created_at"] ?? stateRow["createdAt"]),
                updatedAt: string(row["updated_at"] ?? row["updatedAt"] ?? stateRow["updated_at"] ?? stateRow["updatedAt"]),
                source: string(row["source"] ?? metadata["source"])
            )
        }
        snapshot.stateNames = snapshot.herdItems.map(\.title)
        if let first = snapshot.stateNames.first, !first.isEmpty {
            snapshot.elephantName = first
        }

        let questionsRoot = dashboards["questions"] ?? [:]
        let questions = questionsRoot["questions"] as? [String: Any] ?? [:]
        let facts = questions["facts"] as? [[String: Any]] ?? []
        let waiting = questions["waiting_questions"] as? [[String: Any]] ?? []
        let asked = questions["asked_questions"] as? [[String: Any]] ?? []
        let answered = questions["answered_questions"] as? [[String: Any]] ?? []
        let dismissed = questions["dismissed_questions"] as? [[String: Any]] ?? []
        let lens = questions["lens_coverage"] as? [[String: Any]] ?? []
        let effectivePolicy = questions["effective_policy"] as? [String: Any] ?? [:]
        snapshot.facts = facts.count
        snapshot.waitingQuestions = waiting.count
        snapshot.askedQuestions = asked.count
        snapshot.answeredQuestions = answered.count
        snapshot.dismissedQuestions = dismissed.count
        snapshot.questionIntensity = string(questions["learning_intensity"], fallback: "medium")
        snapshot.questionAskEnabled = bool(effectivePolicy["enabled"], fallback: true)
        snapshot.questionIdleMinutes = int(effectivePolicy["idle_threshold_minutes"])
        if snapshot.questionIdleMinutes == 0 { snapshot.questionIdleMinutes = 180 }
        snapshot.questionDailyMax = int(effectivePolicy["daily_max"])
        if snapshot.questionDailyMax == 0 { snapshot.questionDailyMax = 8 }
        snapshot.questionQuietStart = int(effectivePolicy["quiet_hours_start_local"])
        snapshot.questionQuietEnd = int(effectivePolicy["quiet_hours_end_local"])
        snapshot.sampleFacts = facts.prefix(3).compactMap { firstText(in: $0) }
        snapshot.questionItems = questionItems(waiting, status: "ready")
            + questionItems(asked, status: "asked")
            + questionItems(answered, status: "answered")
            + questionItems(dismissed, status: "dismissed")
        snapshot.sampleQuestions = snapshot.questionItems
            .filter { $0.status == "ready" || $0.status == "asked" }
            .prefix(4)
            .map(\.text)
        snapshot.lensCoverage = Dictionary(uniqueKeysWithValues: lens.compactMap { row in
            let name = string(row["lens"] ?? row["name"] ?? row["id"])
            if name.isEmpty { return nil }
            return (name, int(row["count"] ?? row["facts"] ?? row["questions"]))
        })

        let skillsRoot = dashboards["skills"] ?? [:]
        let operations = skillsRoot["operations"] as? [String: Any] ?? [:]
        let skills = operations["skills"] as? [[String: Any]] ?? []
        let affinities = operations["skill_affinities"] as? [[String: Any]] ?? []
        snapshot.skills = skills.count
        snapshot.skillAffinities = affinities.count
        snapshot.skillNames = skills.prefix(8).compactMap {
            string($0["displayName"] ?? $0["display_name"] ?? $0["skillId"] ?? $0["skill_id"] ?? $0["id"])
        }.filter { !$0.isEmpty }
        snapshot.skillItems = skills.compactMap { row in
            let id = string(row["skillId"] ?? row["skill_id"] ?? row["id"])
            guard !id.isEmpty else { return nil }
            return OperationItem(
                id: id,
                title: string(row["displayName"] ?? row["display_name"] ?? row["name"], fallback: id),
                detail: string(row["summary"] ?? row["source"] ?? row["sourceId"]),
                enabled: bool(row["enabled"], fallback: false)
            )
        }
        snapshot.skillAffinityRows = affinities.prefix(8).compactMap { row in
            let topic = string(row["topic"] ?? row["skillId"] ?? row["indexId"])
            let skillID = string(row["skillId"])
            let title = skillID.isEmpty ? topic : skillID
            guard !title.isEmpty else { return nil }
            return SkillAffinity(
                id: string(row["indexId"], fallback: title),
                name: title,
                count: int(row["activeCount"]),
                latestText: string(row["latestText"])
            )
        }

        let toolsRoot = dashboards["tools"] ?? [:]
        let toolOps = toolsRoot["operations"] as? [String: Any] ?? [:]
        let toolRows = toolOps["tools"] as? [[String: Any]] ?? []
        let mcp = toolOps["mcp"] as? [String: Any] ?? [:]
        let mcpServerRows = mcp["servers"] as? [[String: Any]] ?? []
        let mcpToolRows = mcp["tools"] as? [[String: Any]] ?? []
        snapshot.tools = toolRows.count
        snapshot.enabledTools = toolRows.filter { bool($0["enabled"], fallback: true) }.count
        snapshot.toolNames = toolRows.prefix(10).compactMap {
            string($0["displayName"] ?? $0["display_name"] ?? $0["toolId"] ?? $0["tool_id"])
        }.filter { !$0.isEmpty }
        snapshot.toolItems = toolRows.compactMap { row in
            let id = string(row["toolId"] ?? row["tool_id"] ?? row["id"])
            guard !id.isEmpty else { return nil }
            return OperationItem(
                id: id,
                title: string(row["displayName"] ?? row["display_name"] ?? row["name"], fallback: id),
                detail: string(row["description"] ?? row["family"] ?? row["backend"]),
                enabled: bool(row["enabled"], fallback: true)
            )
        }
        snapshot.mcpServers = mcpServerRows.count
        snapshot.mcpTools = mcpToolRows.count
        snapshot.mcpConfigPath = string(mcp["configPath"] ?? mcp["config_path"])
        snapshot.mcpToolItems = mcpToolRows.compactMap { mcpToolItem(from: $0) }
        snapshot.mcpServerItems = mcpServerRows.compactMap { mcpServerItem(from: $0) }

        let gatewayRoot = dashboards["gateway"] ?? [:]
        let gatewayOps = gatewayRoot["operations"] as? [String: Any] ?? [:]
        let gateway = gatewayOps["gateway"] as? [String: Any] ?? [:]
        let gatewayServices = gateway["services"] as? [[String: Any]] ?? []
        snapshot.gatewayServices = gatewayServices.count
        snapshot.gatewayConfigured = int(gateway["configuredServiceCount"])
        if snapshot.gatewayConfigured == 0 {
            snapshot.gatewayConfigured = gatewayServices.filter { bool($0["configured"]) }.count
        }
        snapshot.gatewayRunning = int(gateway["runningServiceCount"])
        if snapshot.gatewayRunning == 0 {
            snapshot.gatewayRunning = gatewayServices.filter { bool($0["running"]) }.count
        }
        snapshot.gatewayNames = gatewayServices.prefix(8).compactMap {
            let name = string($0["displayName"] ?? $0["display_name"] ?? $0["label"] ?? $0["service"])
            guard !name.isEmpty else { return nil }
            let configured = bool($0["configured"]) ? "configured" : "not configured"
            let running = bool($0["running"]) ? "running" : configured
            return "\(name) · \(running)"
        }
        snapshot.gatewayItems = gatewayServices.compactMap { row in
            let id = string(row["service"] ?? row["id"] ?? row["key"])
            guard !id.isEmpty else { return nil }
            let account = row["primaryAccount"] as? [String: Any] ?? [:]
            let secrets = row["secretFields"] as? [[String: Any]] ?? []
            return GatewayServiceItem(
                id: id,
                title: string(row["label"] ?? row["displayName"] ?? row["display_name"], fallback: id),
                detail: string(row["summary"] ?? row["eventPath"] ?? row["configuredTransport"]),
                configured: bool(row["configured"]),
                running: bool(row["running"]),
                starting: bool(row["starting"]),
                accountID: string(row["primaryAccountId"] ?? account["account_id"], fallback: "default"),
                transport: string(row["configuredTransport"] ?? row["defaultTransport"] ?? row["transport"]),
                accountCount: int(row["accountCount"]),
                eventPath: string(row["eventPath"]),
                setupNote: string(row["setupNote"]),
                secretFields: secrets.compactMap { field in
                    let key = string(field["key"])
                    guard !key.isEmpty else { return nil }
                    return GatewaySecretField(
                        key: key,
                        label: string(field["label"], fallback: key),
                        hasValue: bool(field["hasValue"])
                    )
                }
            )
        }

        let cronRoot = dashboards["cron"] ?? [:]
        let cronOps = cronRoot["operations"] as? [String: Any] ?? [:]
        let cron = cronOps["cron"] as? [String: Any] ?? [:]
        let jobs = cron["jobs"] as? [[String: Any]] ?? []
        snapshot.cronJobs = jobs.count
        snapshot.cronNames = jobs.prefix(6).compactMap { string($0["name"] ?? $0["job_id"] ?? $0["id"]) }.filter { !$0.isEmpty }
        snapshot.cronItems = jobs.compactMap { row in
            let id = string(row["jobId"] ?? row["job_id"] ?? row["id"])
            guard !id.isEmpty else { return nil }
            let schedule = string(row["schedule"] ?? row["scheduleText"] ?? row["schedule_text"])
            let payload = row["payload"] as? [String: Any] ?? [:]
            let prompt = string(payload["prompt"] ?? payload["trigger"])
            return CronJobItem(
                id: id,
                title: string(row["name"], fallback: id),
                detail: string(row["lastSummary"] ?? row["last_summary"], fallback: prompt),
                schedule: schedule,
                status: string(row["status"], fallback: "unknown"),
                nextRun: string(row["nextRunAt"] ?? row["next_run_at"]),
                lastRun: string(row["lastRunAt"] ?? row["last_run_at"]),
                runCount: int(row["runCount"] ?? row["run_count"]),
                isSystem: bool(row["isSystem"] ?? row["is_system"]),
                systemKind: string(row["systemKind"] ?? row["system_kind"]),
                canRunNow: bool(row["canRunNow"] ?? row["can_run_now"], fallback: true),
                canPause: bool(row["canPause"] ?? row["can_pause"], fallback: true),
                canDelete: bool(row["canDelete"] ?? row["can_delete"], fallback: true)
            )
        }

        let runtimeRoot = dashboards["runtime"] ?? [:]
        let chatRoot = dashboards["chat"] ?? [:]
        let runtime = (chatRoot["runtime"] as? [String: Any])
            ?? (runtimeRoot["runtime"] as? [String: Any])
            ?? [:]
        let episodeTraces = runtime["episode_traces"] as? [[String: Any]]
            ?? runtime["episodes"] as? [[String: Any]]
            ?? []
        if snapshot.episodes == 0 {
            snapshot.episodes = episodeTraces.count
        }
        if snapshot.loops == 0 {
            snapshot.loops = (runtime["loops"] as? [[String: Any]])?.count ?? 0
        }
        if snapshot.steps == 0 {
            snapshot.steps = (runtime["steps"] as? [[String: Any]])?.count ?? 0
        }
        snapshot.episodeThreads = Array(episodeTraces.lazy.compactMap { episodeThread(from: $0) }.prefix(10))

        let reflectRoot = dashboards["reflect"] ?? [:]
        let learning = reflectRoot["learning"] as? [String: Any] ?? [:]
        let worker = learning["worker"] as? [String: Any] ?? [:]
        let summary = learning["summary"] as? [String: Any] ?? [:]
        let learningJobs = learning["jobs"] as? [[String: Any]] ?? []
        snapshot.workerStatus = string(worker["status"], fallback: string(summary["status"], fallback: "managed"))
        snapshot.latestCompletedAt = string(summary["latest_completed_at"])
        snapshot.learningItems = learningJobs.compactMap { row in
            let id = string(row["job_id"] ?? row["jobId"] ?? row["id"])
            guard !id.isEmpty else { return nil }
            let trigger = string(row["trigger"] ?? row["job_type"] ?? row["jobType"])
            let metadata = object(row["metadata"])
            let progressStage = string(row["progress_stage"] ?? row["progressStage"])
            let progressDetail = string(row["progress_detail"] ?? row["progressDetail"])
            let features = learningFeatures(from: row, metadata: metadata, trigger: trigger, progressDetail: progressDetail)
            let tools = learningTools(from: row, metadata: metadata, features: features)
            let usedTools = learningUsedTools(from: row)
            let toolProgress = learningToolProgress(from: progressDetail, progressStage: progressStage, usedTools: usedTools)
            let modelProgress = learningModelProgress(from: progressDetail)
            let resultText = learningMarkdown(from: row)
            return LearningJobItem(
                id: id,
                title: learningTitle(from: row, trigger: trigger, id: id, markdown: resultText, features: features),
                detail: [string(row["created_at"] ?? row["createdAt"]), string(row["finished_at"] ?? row["finishedAt"])].filter { !$0.isEmpty }.joined(separator: " → "),
                status: string(row["status"], fallback: "unknown"),
                trigger: trigger,
                progressStage: progressStage,
                progressDetail: progressDetail,
                resolvedFeatures: features,
                resolvedTools: tools,
                usedTools: usedTools,
                toolProgress: toolProgress,
                modelProgress: modelProgress,
                markdown: resultText
            )
        }

        let providersRoot = dashboards["providers"] ?? [:]
        let providerOperations = providersRoot["operations"] as? [String: Any] ?? [:]
        let models = providerOperations["models"] as? [String: Any] ?? [:]
        let activeProvider = models["activeProvider"] as? [String: Any] ?? [:]
        let embeddingProvider = models["embeddingProvider"] as? [String: Any] ?? [:]
        snapshot.providerID = string(activeProvider["provider_id"])
        snapshot.providerModelID = string(activeProvider["model_id"])
        snapshot.providerBaseURL = string(
            activeProvider["base_url"]
                ?? activeProvider["baseUrl"]
                ?? activeProvider["default_base_url"]
                ?? activeProvider["defaultBaseURL"]
                ?? activeProvider["endpoint"]
                ?? activeProvider["url"]
        )
        snapshot.providerSource = string(activeProvider["source"])
        snapshot.embeddingProviderID = string(embeddingProvider["provider_id"])
        snapshot.embeddingStatus = string(
            embeddingProvider["embedding_bootstrap_status"] ?? embeddingProvider["status"],
            fallback: snapshot.semanticStatus
        )
        snapshot.embeddingRuntimeStatus = string(embeddingProvider["embedding_runtime_status"] ?? embeddingProvider["runtime_status"])
        snapshot.embeddingRuntimeState = string(embeddingProvider["embedding_runtime_state"] ?? embeddingProvider["runtime_state"])
        snapshot.embeddingRuntimeSummary = string(embeddingProvider["embedding_runtime_summary"] ?? embeddingProvider["runtime_summary"])
        snapshot.embeddingBootstrapSource = string(
            embeddingProvider["embedding_bootstrap_source"]
                ?? embeddingProvider["embeddingSource"]
                ?? embeddingProvider["embedding_source"]
        )
        snapshot.embeddingModelRoot = string(embeddingProvider["embedding_model_root"] ?? embeddingProvider["model_root"])
        snapshot.embeddingModelSourceURL = string(embeddingProvider["embedding_model_source_url"] ?? embeddingProvider["model_source_url"])
        snapshot.embeddingReady = bool(
            embeddingProvider["embedding_ready"]
                ?? embeddingProvider["embedding_runtime_ready"]
                ?? embeddingProvider["ready"]
        )
        let activeStatus = string(activeProvider["status"])
        if !activeStatus.isEmpty {
            snapshot.providerStatus = activeStatus
        } else if !snapshot.providerID.isEmpty, !snapshot.providerModelID.isEmpty {
            snapshot.providerStatus = "configured"
        }
        let providerRows = models["providers"] as? [[String: Any]] ?? []
        let providerKeyRows = models["keys"] as? [[String: Any]] ?? []
        snapshot.providerOptions = providerOptions(
            from: providerRows,
            providerKeyRows: providerKeyRows,
            activeProviderID: snapshot.providerID,
            activeProviderModelID: snapshot.providerModelID
        )
        if snapshot.providerBaseURL.isEmpty,
           let activeOption = snapshot.providerOptions.first(where: { $0.id == snapshot.providerID }),
           !activeOption.defaultBaseURL.isEmpty {
            snapshot.providerBaseURL = activeOption.defaultBaseURL
        }

        let usageRoot = dashboards["usage"] ?? [:]
        let usageOps = usageRoot["operations"] as? [String: Any] ?? [:]
        let usage = usageOps["usage"] as? [String: Any] ?? [:]
        let usageSummary = usage["summary"] as? [String: Any] ?? [:]
        let tokenEvents = usage["tokenEvents"] as? [[String: Any]] ?? []
        let tokenTrend = usage["tokenTrend"] as? [[String: Any]] ?? []
        snapshot.usageEvents = int(usageSummary["usageEvents"] ?? usageSummary["runtimeStepUsageEvents"])
        if snapshot.usageEvents == 0 {
            snapshot.usageEvents = tokenEvents.count
        }
        snapshot.usageTokens = int(usageSummary["totalTokens"] ?? usageSummary["total_tokens"])
        if snapshot.usageTokens == 0 {
            snapshot.usageTokens = tokenEvents.reduce(0) { total, row in
                total + int(row["total_tokens"] ?? row["totalTokens"])
            }
        }
        snapshot.usagePromptTokens = int(usageSummary["promptTokens"] ?? usageSummary["prompt_tokens"])
        if snapshot.usagePromptTokens == 0 {
            snapshot.usagePromptTokens = tokenEvents.reduce(0) { $0 + int($1["prompt_tokens"] ?? $1["promptTokens"]) }
        }
        snapshot.usageCompletionTokens = int(usageSummary["completionTokens"] ?? usageSummary["completion_tokens"])
        if snapshot.usageCompletionTokens == 0 {
            snapshot.usageCompletionTokens = tokenEvents.reduce(0) { $0 + int($1["completion_tokens"] ?? $1["completionTokens"]) }
        }
        snapshot.usageItems = tokenEvents.prefix(40).compactMap { row in
            let id = string(row["usage_id"] ?? row["usageId"] ?? row["source_event_id"] ?? row["sourceEventId"])
            let rawModel = string(row["model_id"] ?? row["modelId"] ?? row["model"])
            let model = displayModelName(rawModel, fallback: snapshot.providerModelID)
            let provider = string(row["provider_id"] ?? row["providerId"], fallback: "local")
            let total = int(row["total_tokens"] ?? row["totalTokens"])
            guard total > 0 || !id.isEmpty else { return nil }
            return UsageEventItem(
                id: id.isEmpty ? UUID().uuidString : id,
                title: model,
                subtitle: string(row["created_at"] ?? row["createdAt"] ?? row["session_id"] ?? row["sessionId"]),
                provider: provider,
                model: model,
                promptTokens: int(row["prompt_tokens"] ?? row["promptTokens"]),
                completionTokens: int(row["completion_tokens"] ?? row["completionTokens"]),
                totalTokens: total
            )
        }
        snapshot.usageTrend = tokenTrend.compactMap { row in
            let date = string(row["date"] ?? row["day"])
            guard !date.isEmpty else { return nil }
            return UsageTrendPoint(
                date: date,
                promptTokens: int(row["promptTokens"] ?? row["prompt_tokens"]),
                completionTokens: int(row["completionTokens"] ?? row["completion_tokens"]),
                totalTokens: int(row["totalTokens"] ?? row["total_tokens"])
            )
        }

        let settingsRoot = dashboards["settings"] ?? [:]
        let settingsOps = settingsRoot["operations"] as? [String: Any] ?? [:]
        let settings = settingsOps["settings"] as? [String: Any] ?? [:]
        snapshot.settingsPath = string(settings["globalConfigPath"] ?? settings["global_config_path"])
        snapshot.settingsYaml = string(settings["globalConfigYaml"] ?? settings["global_config_yaml"])

        let logsRoot = dashboards["logs"] ?? [:]
        let logOps = logsRoot["operations"] as? [String: Any] ?? [:]
        let logs = logOps["logs"] as? [[String: Any]] ?? []
        snapshot.logs = logs.count
        snapshot.logFiles = logs.compactMap { row in
            let path = string(row["path"])
            let name = string(row["name"], fallback: path)
            guard !name.isEmpty else { return nil }
            let size = int(row["size"])
            let updated = string(row["updatedAt"] ?? row["updated_at"])
            let tail = listStrings(row["tail"])
            return LogFileItem(
                id: path.isEmpty ? name : path,
                name: name,
                path: path,
                size: size,
                updatedAt: updated,
                tail: tail
            )
        }
        snapshot.logItems = snapshot.logFiles.prefix(8).map { item in
            return OperationItem(
                id: item.id,
                title: item.name,
                detail: item.detail,
                enabled: true
            )
        }

        let personalModelsRoot = dashboards["personal-models"] ?? [:]
        let personalModels = personalModelsRoot["personal_models"] as? [[String: Any]] ?? []
        let selectedPersonalModel = personalModels.first { string($0["personal_model_id"]) == snapshot.currentPersonalModelID } ?? personalModels.first
        let modelFacts = selectedPersonalModel?["personal_model_all_facts"] as? [[String: Any]]
            ?? selectedPersonalModel?["personal_model_facts"] as? [[String: Any]]
            ?? []
        snapshot.profileFacts = profileAnchorFacts(from: selectedPersonalModel, modelFacts: modelFacts)
        snapshot.personalModelFacts = modelFacts.prefix(80).compactMap { row in
            let text = string(row["text"] ?? row["content"])
            guard !text.isEmpty else { return nil }
            let metadata = object(row["metadata"])
            let lens = string(row["lens"] ?? metadata["lens"] ?? metadata["topic"], fallback: "memory")
            let status = string(row["status"], fallback: "active")
            let detail = [
                string(row["source_id"] ?? row["source"] ?? metadata["source"]),
                string(row["updated_at"] ?? row["created_at"])
            ].filter { !$0.isEmpty }.joined(separator: " · ")
            return PersonalModelFact(
                id: string(row["ref"] ?? row["fact_id"] ?? row["id"], fallback: text),
                text: text,
                lens: lens,
                topic: string(row["topic"] ?? metadata["topic"]),
                status: status,
                detail: detail
            )
        }

        let diaryRoot = dashboards["diary"] ?? [:]
        let diary = diaryRoot["diary"] as? [String: Any] ?? [:]
        let entries = diary["entries"] as? [[String: Any]] ?? []
        snapshot.diaryEntries = entries.prefix(12).compactMap { row in
            let content = string(row["content"])
            guard !content.isEmpty else { return nil }
            return DiaryEntry(
                id: string(row["entry_id"], fallback: string(row["entry_date"], fallback: content)),
                date: string(row["entry_date"]),
                content: content,
                generatedAt: string(row["generated_at"])
            )
        }

        return snapshot
    }

    static func mcpDiscoveryResult(from json: [String: Any]) -> MCPDiscoveryResult {
        let toolRows = json["tools"] as? [[String: Any]] ?? []
        return MCPDiscoveryResult(
            status: string(json["status"], fallback: "unknown"),
            serverID: string(json["serverId"] ?? json["server_id"]),
            serverLabel: string(json["serverLabel"] ?? json["server_label"]),
            transport: string(json["transport"], fallback: "stdio"),
            toolCount: int(json["toolCount"] ?? json["tool_count"]),
            durationMs: int(json["durationMs"] ?? json["duration_ms"]),
            tools: toolRows.compactMap { row in
                let name = string(row["name"])
                guard !name.isEmpty else { return nil }
                return MCPDiscoveredTool(
                    name: name,
                    description: string(row["description"]),
                    requiredFields: listStrings(row["requiredFields"] ?? row["required_fields"]),
                    inputSchema: object(row["inputSchema"] ?? row["input_schema"] ?? row["schema"]),
                    enabled: bool(row["enabled"], fallback: true)
                )
            },
            error: string(json["error"]),
            stdout: string(json["stdout"]),
            stderr: string(json["stderr"])
        )
    }

    private static func providerOptions(
        from providerRows: [[String: Any]],
        providerKeyRows: [[String: Any]],
        activeProviderID: String,
        activeProviderModelID: String
    ) -> [ProviderOption] {
        providerRows.compactMap { row in
            providerOption(
                from: row,
                providerKeyRows: providerKeyRows,
                activeProviderID: activeProviderID,
                activeProviderModelID: activeProviderModelID
            )
        }
    }

    private static func providerOption(
        from row: [String: Any],
        providerKeyRows: [[String: Any]],
        activeProviderID: String,
        activeProviderModelID: String
    ) -> ProviderOption? {
        let id = string(row["provider_id"] ?? row["providerId"] ?? row["id"])
        guard !id.isEmpty else { return nil }

        let discovered = row["discovered_state"] as? [String: Any] ?? [:]
        let isActive = id == activeProviderID
        let storedKeyCount = storedProviderKeyCount(for: id, in: providerKeyRows)
        let status = providerStatus(discovered: discovered, row: row)
        let defaultModel = providerDefaultModel(discovered: discovered, row: row)
        let activeModel = isActive ? activeProviderModelID : ""
        let resolvedModel = activeModel.isEmpty ? defaultModel : activeModel
        let modelRows = providerModelOptions(
            fromDiscoveredRows: providerDiscoveredModels(discovered: discovered, row: row),
            providerRow: row,
            defaultModel: resolvedModel
        )

        return ProviderOption(
            id: id,
            displayName: providerDisplayName(row: row, fallback: id),
            defaultModel: resolvedModel,
            defaultBaseURL: providerBaseURL(discovered: discovered, row: row),
            status: status,
            source: string(discovered["source"] ?? row["source"]),
            authKind: providerAuthKind(row),
            summary: providerSummary(row),
            connected: isActive || providerRuntimeConnected(status) || storedKeyCount > 0,
            active: isActive,
            storedKeyCount: storedKeyCount,
            models: modelRows
        )
    }

    private static func storedProviderKeyCount(for providerID: String, in providerKeyRows: [[String: Any]]) -> Int {
        providerKeyRows.filter { key in
            string(key["providerId"] ?? key["provider_id"]) == providerID
                && bool(key["hasValue"] ?? key["has_value"])
        }.count
    }

    private static func providerStatus(discovered: [String: Any], row: [String: Any]) -> String {
        let discoveredStatus = string(discovered["status"])
        if !discoveredStatus.isEmpty {
            return discoveredStatus
        }
        return string(row["status"])
    }

    private static func providerDefaultModel(discovered: [String: Any], row: [String: Any]) -> String {
        let discoveredDefault = firstString(in: discovered, keys: ["default_model"])
        if !discoveredDefault.isEmpty {
            return discoveredDefault
        }
        return firstString(in: row, keys: ["default_model", "default_model_id", "model_id"])
    }

    private static func providerDiscoveredModels(discovered: [String: Any], row: [String: Any]) -> [[String: Any]] {
        if let rows = discovered["models"] as? [[String: Any]] { return rows }
        if let rows = row["models"] as? [[String: Any]] { return rows }
        if let rows = discovered["model_options"] as? [[String: Any]] { return rows }
        return []
    }

    private static func providerBaseURL(discovered: [String: Any], row: [String: Any]) -> String {
        let discoveredURL = firstString(
            in: discovered,
            keys: ["base_url", "baseUrl", "default_base_url", "defaultBaseURL", "endpoint"]
        )
        if !discoveredURL.isEmpty {
            return discoveredURL
        }
        return firstString(
            in: row,
            keys: ["default_base_url", "defaultBaseURL", "base_url", "baseUrl", "endpoint", "url"]
        )
    }

    private static func providerDisplayName(row: [String: Any], fallback: String) -> String {
        firstString(in: row, keys: ["display_name", "displayName", "name"], fallback: fallback)
    }

    private static func providerAuthKind(_ row: [String: Any]) -> String {
        firstString(
            in: row,
            keys: ["auth_method", "auth_type", "auth_kind", "authKind", "credential_kind", "credentialKind"]
        )
    }

    private static func providerSummary(_ row: [String: Any]) -> String {
        firstString(in: row, keys: ["catalog_summary", "onboarding_hint", "transport_display_name"])
    }

    private static func providerRuntimeConnected(_ status: String) -> Bool {
        let normalized = status.lowercased()
        return ["authenticated", "configured", "available", "ready"].contains { normalized.contains($0) }
    }

    private static func firstString(in row: [String: Any], keys: [String], fallback: String = "") -> String {
        for key in keys {
            let value = string(row[key])
            if !value.isEmpty {
                return value
            }
        }
        return fallback
    }

    static func providerModelOptions(
        fromDiscoveredRows discoveredRows: [[String: Any]],
        providerRow: [String: Any],
        defaultModel: String
    ) -> [ProviderModelOption] {
        var seen = Set<String>()
        var rows: [ProviderModelOption] = []

        func push(_ rawID: String, source: String, label: String = "", contextWindowTokens: Int = 0, maxOutputTokens: Int = 0) {
            let modelID = rawID.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !modelID.isEmpty, !seen.contains(modelID) else { return }
            seen.insert(modelID)
            rows.append(
                ProviderModelOption(
                    id: modelID,
                    label: label.isEmpty ? modelID : label,
                    source: source,
                    contextWindowTokens: contextWindowTokens,
                    maxOutputTokens: maxOutputTokens
                )
            )
        }

        for row in discoveredRows {
            push(
                string(row["model_id"] ?? row["modelId"] ?? row["id"]),
                source: string(row["source"], fallback: "endpoint"),
                label: string(row["label"] ?? row["name"]),
                contextWindowTokens: int(row["context_window_tokens"] ?? row["contextWindowTokens"] ?? row["context_window"] ?? row["contextWindow"]),
                maxOutputTokens: int(row["max_output_tokens"] ?? row["maxOutputTokens"] ?? row["max_tokens"] ?? row["maxTokens"])
            )
        }
        for modelID in listStrings(providerRow["model_hints"] ?? providerRow["modelHints"]) {
            push(modelID, source: "catalog")
        }
        push(defaultModel, source: "active")
        push(string(providerRow["default_model_id"] ?? providerRow["defaultModelId"]), source: "default")
        return rows
    }

    static func findString(in json: [String: Any], keys: [String]) -> String? {
        for key in keys {
            if let value = json[key] as? String, !value.isEmpty {
                return value
            }
        }
        for (_, value) in json {
            if let dictionary = value as? [String: Any], let found = findString(in: dictionary, keys: keys) {
                return found
            }
        }
        return nil
    }

    static func findDictionary(in json: [String: Any], keys: [String]) -> [String: Any]? {
        for key in keys {
            if let value = json[key] as? [String: Any] {
                return value
            }
        }
        return nil
    }

    static func firstText(in json: [String: Any]) -> String? {
        let preferred = ["text", "content", "summary", "message", "decision_summary", "response"]
        for key in preferred {
            if let value = json[key] as? String, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return value
            }
        }
        for (_, value) in json {
            if let dictionary = value as? [String: Any], let found = firstText(in: dictionary) {
                return found
            }
            if let array = value as? [[String: Any]] {
                for item in array {
                    if let found = firstText(in: item) {
                        return found
                    }
                }
            }
        }
        return nil
    }

    static func loopReplyText(in json: [String: Any]) -> String? {
        let directKeys = ["reply_text", "replyText", "assistant_response", "assistantResponse"]
        for key in directKeys {
            if let text = cleanLoopReplyText(json[key]) {
                return text
            }
        }

        let paths = [
            ["reply", "reply_text"],
            ["reply", "replyText"],
            ["outcome", "execution", "summary"],
            ["latest_loop", "outcome", "execution", "summary"],
            ["latestLoop", "outcome", "execution", "summary"],
            ["inspection", "latest_loop", "outcome", "execution", "summary"],
            ["inspection", "latestLoop", "outcome", "execution", "summary"]
        ]
        for path in paths {
            if let text = cleanLoopReplyText(value(in: json, path: path)) {
                return text
            }
        }

        if let outcome = json["outcome"] as? [String: Any],
           let text = lastAssistantTurnText(outcome["turn_messages"] ?? outcome["turnMessages"]) {
            return text
        }
        if let reply = json["reply"] as? [String: Any],
           let outcome = reply["outcome"] as? [String: Any],
           let text = lastAssistantTurnText(outcome["turn_messages"] ?? outcome["turnMessages"]) {
            return text
        }

        return cleanLoopReplyText(firstText(in: json))
    }

    private static func value(in json: [String: Any], path: [String]) -> Any? {
        var current: Any = json
        for key in path {
            guard let dictionary = current as? [String: Any], let next = dictionary[key] else {
                return nil
            }
            current = next
        }
        return current
    }

    private static func lastAssistantTurnText(_ value: Any?) -> String? {
        guard let messages = value as? [[String: Any]] else { return nil }
        for message in messages.reversed() {
            let role = string(message["role"]).lowercased()
            guard role == "assistant" else { continue }
            if let text = cleanLoopReplyText(message["content"] ?? message["text"] ?? message["summary"]) {
                return text
            }
        }
        return nil
    }

    private static func cleanLoopReplyText(_ value: Any?) -> String? {
        let text = string(value).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        let normalized = text.lowercased()
        let internalSummaries: Set<String> = [
            "source input recorded",
            "source input recorded ok",
            "runtime state persisted",
            "canonical state projection refreshed"
        ]
        guard !internalSummaries.contains(normalized) else { return nil }
        return text
    }

    private static func questionItems(_ rows: [[String: Any]], status: String) -> [PersonalModelQuestionItem] {
        rows.compactMap { row in
            let text = firstText(in: row) ?? ""
            guard !text.isEmpty else { return nil }
            let id = string(row["question_id"] ?? row["questionId"] ?? row["id"], fallback: text)
            return PersonalModelQuestionItem(
                id: id,
                text: text,
                status: status,
                lens: string(row["lens"], fallback: "coverage"),
                subLens: string(row["sub_lens"] ?? row["subLens"]),
                source: string(row["source"], fallback: "coverage"),
                sensitivity: string(row["sensitivity"], fallback: "low"),
                priority: double(row["priority"]),
                askedCount: int(row["asked_count"] ?? row["askedCount"]),
                lastAskedSurface: string(row["last_asked_surface"] ?? row["lastAskedSurface"]),
                lastAskedAt: string(row["last_asked_at"] ?? row["lastAskedAt"]),
                createdAt: string(row["created_at"] ?? row["createdAt"]),
                resultingFacts: questionResultingFacts(row["resulting_facts"] ?? row["resultingFacts"])
            )
        }
    }

    private static func questionResultingFacts(_ value: Any?) -> [PersonalModelFact] {
        guard let rows = value as? [[String: Any]] else { return [] }
        return rows.compactMap { row in
            let text = string(row["text"] ?? row["content"])
            guard !text.isEmpty else { return nil }
            let metadata = object(row["metadata"])
            return PersonalModelFact(
                id: string(row["fact_id"] ?? row["ref"] ?? row["id"], fallback: text),
                text: text,
                lens: string(row["lens"] ?? metadata["lens"] ?? metadata["topic"], fallback: "memory"),
                topic: string(row["topic"] ?? metadata["topic"]),
                status: string(row["status"], fallback: "active"),
                detail: [
                    string(row["source_id"] ?? row["source"] ?? metadata["source"]),
                    string(row["updated_at"] ?? row["created_at"])
                ].filter { !$0.isEmpty }.joined(separator: " · ")
            )
        }
    }

    static func toolUseEvents(in json: [String: Any]) -> [ToolUseEvent] {
        var events: [ToolUseEvent] = []

        func scan(_ value: Any) {
            if let dictionary = value as? [String: Any] {
                collectToolEvent(from: dictionary, into: &events)
                for value in dictionary.values {
                    scan(value)
                }
                return
            }

            if let array = value as? [Any] {
                for item in array {
                    scan(item)
                }
            }
        }

        scan(json)

        var seen = Set<String>()
        var deduped: [ToolUseEvent] = []
        for event in events {
            let key = [
                event.sourceID,
                event.invocationID,
                event.name,
                event.status,
                event.arguments,
                String(event.result.prefix(120))
            ].joined(separator: "|")
            guard !seen.contains(key) else { continue }
            seen.insert(key)
            deduped.append(event)
        }
        return Array(deduped.prefix(8))
    }

    static func gatewayQRState(from json: [String: Any]) -> GatewayQRState {
        let matrixValue = findValue(in: json, keys: ["qrMatrix", "qr_matrix"]) as? [[Any]] ?? []
        let matrix = matrixValue.map { row in
            row.map { value in
                if let intValue = value as? Int { return intValue }
                if let number = value as? NSNumber { return number.intValue }
                return Int(String(describing: value)) ?? 0
            }
        }
        return GatewayQRState(
            sessionID: findString(in: json, keys: ["sessionId", "session_id"]) ?? "",
            status: findString(in: json, keys: ["status"]) ?? "",
            message: findString(in: json, keys: ["message", "detail"]) ?? "",
            qrcodeURL: findString(in: json, keys: ["qrcodeUrl", "qrcode_url", "qrUrl", "qr_url"]) ?? "",
            matrix: matrix
        )
    }

    private static func findValue(in json: [String: Any], keys: [String]) -> Any? {
        for key in keys {
            if let value = json[key] { return value }
        }
        for (_, value) in json {
            if let dictionary = value as? [String: Any], let found = findValue(in: dictionary, keys: keys) {
                return found
            }
        }
        return nil
    }

    private static func collectToolEvent(from dictionary: [String: Any], into events: inout [ToolUseEvent]) {
        let detail = dictionary["detail"] as? [String: Any] ?? [:]
        let eventType = string(dictionary["event_type"] ?? dictionary["eventType"]).lowercased()
        let action = string(dictionary["action"]).lowercased()
        let metadata = dictionary["metadata"] as? [String: Any] ?? [:]
        let invocationID = string(
            detail["invocation_id"]
                ?? detail["invocationId"]
                ?? dictionary["invocation_id"]
                ?? dictionary["invocationId"]
                ?? metadata["invocation_id"]
                ?? metadata["invocationId"]
        )
        var sourceID = firstString(in: detail, keys: ["id", "event_id", "eventId"])
        if sourceID.isEmpty {
            sourceID = firstString(in: dictionary, keys: ["id", "event_id", "eventId", "stream_sequence"])
        }
        if sourceID.isEmpty {
            sourceID = firstString(in: metadata, keys: ["id", "event_id", "eventId"])
        }
        let name = compactToolText(
            detail["tool_name"]
                ?? dictionary["tool_name"]
                ?? dictionary["toolName"]
                ?? metadata["tool_name"]
                ?? metadata["toolName"]
                ?? dictionary["name"]
        )
        let arguments = compactToolText(
            detail["tool_arguments"]
                ?? dictionary["tool_arguments"]
                ?? dictionary["toolArguments"]
                ?? metadata["tool_arguments"]
                ?? metadata["toolArguments"]
                ?? dictionary["arguments"]
                ?? dictionary["args"]
        )
        let result = compactToolText(
            detail["tool_result"]
                ?? dictionary["tool_result"]
                ?? dictionary["toolResult"]
                ?? metadata["tool_result"]
                ?? metadata["toolResult"]
                ?? (eventType == "tool_execute" ? dictionary["content"] : nil)
                ?? dictionary["result"]
        )

        let looksLikeTool = eventType.contains("tool")
            || action == "call_tool"
            || (!name.isEmpty && (!arguments.isEmpty || !result.isEmpty))
        guard looksLikeTool, !name.isEmpty || !arguments.isEmpty || !result.isEmpty else {
            return
        }

        let fallbackStatus = eventType == "tool_call" ? "planned" : "completed"
        let rawStatus = string(dictionary["status"], fallback: fallbackStatus)
        events.append(
            ToolUseEvent(
                sourceID: sourceID,
                invocationID: invocationID,
                name: name.isEmpty ? "tool" : name,
                status: rawStatus.isEmpty ? fallbackStatus : rawStatus,
                arguments: abbreviate(arguments, maxLength: 420),
                result: abbreviate(result, maxLength: 520)
            )
        )
    }

    private static func compactToolText(_ value: Any?) -> String {
        guard let value else { return "" }
        if value is NSNull { return "" }
        if let string = value as? String {
            return string.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if let number = value as? NSNumber {
            return String(describing: number)
        }
        if JSONSerialization.isValidJSONObject(value),
           let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
           let text = String(data: data, encoding: .utf8) {
            return text
        }
        return String(describing: value).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func learningMarkdown(from row: [String: Any]) -> String {
        for key in ["result_markdown", "resultMarkdown"] {
            let text = markdownCandidate(row[key])
            if !text.isEmpty { return text }
        }
        let summary = string(row["summary"])
        if looksLikeLongMarkdown(summary) { return summary }
        for key in ["learning_result", "learningResult", "result"] {
            let text = markdownCandidate(row[key])
            if !text.isEmpty { return text }
        }
        if !summary.isEmpty { return summary }
        let error = markdownCandidate(row["error"])
        if !error.isEmpty { return error }
        return ""
    }

    private static func markdownCandidate(_ value: Any?) -> String {
        guard let value else { return "" }
        if value is NSNull { return "" }
        if let string = value as? String {
            return string.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if let number = value as? NSNumber {
            return String(describing: number)
        }
        if let object = value as? [String: Any] {
            for key in ["result_markdown", "resultMarkdown", "markdown", "summary", "content", "message", "error"] {
                let text = markdownCandidate(object[key])
                if !text.isEmpty { return text }
            }
            return ""
        }
        if let array = value as? [Any] {
            return array
                .map { markdownCandidate($0) }
                .filter { !$0.isEmpty }
                .joined(separator: "\n\n")
        }
        return ""
    }

    private static func learningTitle(from row: [String: Any], trigger: String, id: String, markdown: String, features: [String]) -> String {
        let summary = string(row["summary"])
        if !features.isEmpty, summary.lowercased().contains("features=default") {
            return "reflect job (features=\(features.joined(separator: ",")))"
        }
        if !summary.isEmpty && !looksLikeLongMarkdown(summary) {
            return compactLine(summary, maxLength: 72)
        }
        let firstLine = markdown
            .components(separatedBy: .newlines)
            .map { cleanMarkdownTitleLine($0) }
            .first { !$0.isEmpty }
        return compactLine(firstLine ?? (trigger.isEmpty ? id : trigger), maxLength: 72)
    }

    private static func learningFeatures(from row: [String: Any], metadata: [String: Any], trigger: String, progressDetail: String) -> [String] {
        let resolved = listStrings(row["resolved_features"] ?? row["resolvedFeatures"] ?? metadata["resolved_features"] ?? metadata["resolvedFeatures"])
        if !resolved.isEmpty { return deduplicated(resolved) }
        let explicit = listStrings(metadata["features"]).filter { $0.lowercased() != "default" }
        if !explicit.isEmpty { return deduplicated(explicit) }
        let progress = featuresFromProgressDetail(progressDetail)
        if !progress.isEmpty { return progress }
        return fallbackFeatures(for: trigger)
    }

    private static func learningTools(from row: [String: Any], metadata: [String: Any], features: [String]) -> [String] {
        let resolved = listStrings(row["resolved_tools"] ?? row["resolvedTools"] ?? metadata["resolved_tools"] ?? metadata["resolvedTools"])
        if !resolved.isEmpty { return deduplicated(resolved) }
        var tools: [String] = []
        for feature in features {
            tools.append(contentsOf: fallbackTools(for: feature))
        }
        return deduplicated(tools)
    }

    private static func learningUsedTools(from row: [String: Any]) -> [String] {
        let direct = listStrings(row["tool_names"] ?? row["toolNames"] ?? row["used_tools"] ?? row["usedTools"])
        if !direct.isEmpty { return deduplicated(direct) }
        for key in ["learning_result", "learningResult", "result_json", "resultJson", "result"] {
            let result = object(row[key])
            let tools = listStrings(result["tool_names"] ?? result["toolNames"] ?? result["used_tools"] ?? result["usedTools"])
            if !tools.isEmpty { return deduplicated(tools) }
        }
        return []
    }

    private static func learningProgressPayload(from progressDetail: String) -> [String: Any]? {
        let trimmed = progressDetail.trimmingCharacters(in: .whitespacesAndNewlines)
        for prefix in ["tool_event_v1=", "learning_event_v1="] {
            guard trimmed.hasPrefix(prefix) else { continue }
            return object(String(trimmed.dropFirst(prefix.count)))
        }
        return nil
    }

    private static func learningToolProgress(from progressDetail: String, progressStage: String, usedTools: [String]) -> LearningToolCallProgress {
        let trimmed = progressDetail.trimmingCharacters(in: .whitespacesAndNewlines)
        if let payload = learningProgressPayload(from: trimmed) {
            let activeTool = string(payload["active_tool"] ?? payload["activeTool"])
            let completedTools = deduplicated(listStrings(payload["completed_tools"] ?? payload["completedTools"]))
            let failedTools = deduplicated(listStrings(payload["failed_tools"] ?? payload["failedTools"]))
            let rawEvents = payload["events"] as? [[String: Any]] ?? []
            let events = rawEvents.enumerated().compactMap { index, event -> LearningToolCallEvent? in
                let toolID = string(event["tool_id"] ?? event["toolID"] ?? event["tool"])
                guard !toolID.isEmpty else { return nil }
                let phase = string(event["phase"], fallback: "execution.started")
                let preview = string(event["preview"])
                return LearningToolCallEvent(
                    id: "\(index)-\(toolID)-\(phase)-\(preview)",
                    toolID: toolID,
                    phase: phase,
                    preview: preview
                )
            }
            return LearningToolCallProgress(
                activeToolID: activeTool,
                completedToolIDs: completedTools,
                failedToolIDs: failedTools,
                events: events
            )
        }

        let legacy = legacyLearningToolProgress(from: trimmed, progressStage: progressStage)
        if !legacy.events.isEmpty {
            return legacy
        }
        let completedTools = deduplicated(usedTools.filter { $0.hasPrefix("tool.") })
        let events = completedTools.enumerated().map { index, toolID in
            LearningToolCallEvent(
                id: "used-\(index)-\(toolID)",
                toolID: toolID,
                phase: "execution.completed",
                preview: ""
            )
        }
        return LearningToolCallProgress(activeToolID: "", completedToolIDs: completedTools, failedToolIDs: [], events: events)
    }

    private static func learningModelProgress(from progressDetail: String) -> LearningModelProgress {
        guard let payload = learningProgressPayload(from: progressDetail) else {
            return .empty
        }
        let text = compactLearningModelPreview(
            string(
                payload["model_preview"]
                    ?? payload["modelPreview"]
                    ?? payload["model_text"]
                    ?? payload["modelText"]
            )
        )
        guard !text.isEmpty else { return .empty }
        let phase = string(payload["model_phase"] ?? payload["modelPhase"], fallback: "streaming")
        return LearningModelProgress(text: text, phase: phase)
    }

    private static func compactLearningModelPreview(_ value: String) -> String {
        let normalized = value
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .split(whereSeparator: { $0.isWhitespace })
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard normalized.count > 420 else { return normalized }
        let start = normalized.index(normalized.endIndex, offsetBy: -417)
        return "...\(normalized[start...])"
    }

    private static func legacyLearningToolProgress(from progressDetail: String, progressStage: String) -> LearningToolCallProgress {
        guard progressDetail.contains("tool_event") || progressDetail.contains("called=") else {
            return .empty
        }
        let completedTools = deduplicated(legacyCalledTools(from: progressDetail))
        let latestTool = legacyLatestTool(from: progressDetail)
        let normalizedStage = progressStage.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let normalizedDetail = progressDetail.lowercased()
        let phase: String
        if normalizedStage.contains("failed") || normalizedDetail.contains("execution.failed") {
            phase = "execution.failed"
        } else if normalizedStage.contains("completed") || normalizedDetail.contains("execution.completed") {
            phase = "execution.completed"
        } else if normalizedDetail.contains("requested") {
            phase = "requested"
        } else {
            phase = "execution.started"
        }
        var failedTools: [String] = []
        if phase == "execution.failed", !latestTool.isEmpty {
            failedTools = [latestTool]
        }
        var events: [LearningToolCallEvent] = completedTools.enumerated().map { index, toolID in
            LearningToolCallEvent(id: "legacy-completed-\(index)-\(toolID)", toolID: toolID, phase: "execution.completed", preview: "")
        }
        if !latestTool.isEmpty {
            events.append(
                LearningToolCallEvent(
                    id: "legacy-latest-\(latestTool)-\(phase)",
                    toolID: latestTool,
                    phase: phase,
                    preview: legacyToolPreview(from: progressDetail)
                )
            )
        }
        let activeTool = phase == "requested" || phase == "execution.started" ? latestTool : ""
        return LearningToolCallProgress(
            activeToolID: activeTool,
            completedToolIDs: completedTools,
            failedToolIDs: failedTools,
            events: events
        )
    }

    private static func legacyLatestTool(from progressDetail: String) -> String {
        let separators = CharacterSet(charactersIn: " =,()[]\n\t")
        return normalizedToolIDs(progressDetail.components(separatedBy: separators).filter { $0.contains("tool.") }).first ?? ""
    }

    private static func legacyCalledTools(from progressDetail: String) -> [String] {
        guard let range = progressDetail.range(of: "called=") else { return [] }
        return normalizedToolIDs(
            String(progressDetail[range.upperBound...])
                .components(separatedBy: CharacterSet(charactersIn: ", \n\t"))
        )
    }

    private static func legacyToolPreview(from progressDetail: String) -> String {
        for key in ["action=", "query=", "topic=", "url=", "ref=", "lens="] {
            guard let range = progressDetail.range(of: key) else { continue }
            let tail = progressDetail[range.lowerBound...]
            if let token = tail.split(whereSeparator: { $0.isWhitespace }).first {
                return String(token).trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }
        return ""
    }

    private static func normalizedToolIDs(_ values: [String]) -> [String] {
        var seen = Set<String>()
        var result: [String] = []
        for value in values {
            let normalized = value
                .trimmingCharacters(in: .whitespacesAndNewlines)
                .replacingOccurrences(of: "tool_event", with: "")
                .trimmingCharacters(in: CharacterSet(charactersIn: "=:;,"))
            guard normalized.hasPrefix("tool."), !seen.contains(normalized) else { continue }
            seen.insert(normalized)
            result.append(normalized)
        }
        return result
    }

    private static func featuresFromProgressDetail(_ detail: String) -> [String] {
        guard let range = detail.range(of: "features=") else { return [] }
        let tail = detail[range.upperBound...]
        let token = tail.split(whereSeparator: { $0.isWhitespace || $0 == ")" || $0 == "]" }).first.map(String.init) ?? ""
        return deduplicated(listStrings(token).filter { $0.lowercased() != "default" })
    }

    private static func fallbackFeatures(for trigger: String) -> [String] {
        switch trigger.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "init", "init_profile", "profile":
            return ["pm", "questions", "skills", "init_links"]
        case "manual":
            return ["pm", "questions", "recall", "skills"]
        case "dream":
            return ["dream", "questions", "skills", "diary"]
        case "diary":
            return ["diary"]
        case "context_compaction":
            return ["compress"]
        default:
            return ["pm", "questions", "skills"]
        }
    }

    private static func fallbackTools(for feature: String) -> [String] {
        switch feature.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "pm":
            return ["tool.personal_model.search", "tool.personal_model.update"]
        case "questions":
            return ["tool.personal_model.questions"]
        case "skills":
            return ["tool.skill.list", "tool.skill.view", "tool.personal_model.search", "tool.personal_model.update"]
        case "init_links":
            return ["tool.web.search", "tool.web.read", "tool.web.extract", "tool.browser.navigate", "tool.browser.snapshot", "tool.browser.scroll", "tool.browser.images"]
        case "recall":
            return ["tool.conversation.search"]
        case "diary":
            return ["tool.diary.write", "tool.diary.list", "tool.conversation.search", "tool.personal_model.search"]
        case "dream":
            return ["tool.personal_model.search", "tool.personal_model.update", "tool.conversation.search"]
        default:
            return []
        }
    }

    private static func deduplicated(_ values: [String]) -> [String] {
        var seen = Set<String>()
        var result: [String] = []
        for value in values {
            let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !normalized.isEmpty, !seen.contains(normalized) else { continue }
            seen.insert(normalized)
            result.append(normalized)
        }
        return result
    }

    private static func looksLikeLongMarkdown(_ text: String) -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.contains("\n") || trimmed.hasPrefix("#") || trimmed.hasPrefix("{")
    }

    private static func cleanMarkdownTitleLine(_ line: String) -> String {
        line
            .replacingOccurrences(of: #"^#{1,6}\s*"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"^[-*]\s+"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func episodeThread(from row: [String: Any]) -> EpisodeThread? {
        let id = string(row["episode_id"] ?? row["episodeId"] ?? row["id"])
        guard !id.isEmpty else { return nil }

        let rawTimeline = row["timeline"] as? [[String: Any]] ?? []
        let timeline = rawTimeline.count > chatTimelineStepLimit
            ? Array(rawTimeline.suffix(chatTimelineStepLimit))
            : rawTimeline
        let messages = chatMessages(from: timeline)
        let firstUserMessage = messages.first { $0.role == .user }?.text ?? ""
        let summary = string(row["exit_summary"] ?? row["summary"])
        guard shouldShowChatThread(row: row, messages: messages, firstUserMessage: firstUserMessage, summary: summary) else {
            return nil
        }
        let status = string(row["status"], fallback: "open")
        let titleSeed = firstUserMessage.isEmpty ? summary : firstUserMessage
        let title = compactLine(titleSeed.isEmpty ? "Conversation" : titleSeed, maxLength: 44)

        let loops = int(row["loop_count"] ?? row["loopCount"])
        let steps = int(row["step_count"] ?? row["stepCount"])
        let subtitleParts = [
            status,
            loops > 0 ? "\(loops) loops" : "",
            steps > 0 ? "\(steps) steps" : ""
        ].filter { !$0.isEmpty }

        return EpisodeThread(
            id: id,
            title: title,
            subtitle: subtitleParts.joined(separator: " · "),
            summary: compactLine(summary, maxLength: 220),
            status: status,
            messages: messages
        )
    }

    private static func shouldShowChatThread(
        row: [String: Any],
        messages: [ChatMessage],
        firstUserMessage: String,
        summary: String
    ) -> Bool {
        let userMessages = messages
            .filter { $0.role == .user }
            .map { $0.text.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        guard !userMessages.isEmpty else { return false }

        let titleText = [
            firstUserMessage,
            summary,
            string(row["display_name"] ?? row["displayName"] ?? row["title"] ?? row["name"])
        ].joined(separator: "\n")
        if looksLikeInternalChatHistoryTitle(titleText) {
            return false
        }
        return !userMessages.allSatisfy(looksLikeInternalChatHistoryTitle)
    }

    private static func looksLikeInternalChatHistoryTitle(_ value: String) -> Bool {
        let normalized = value
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        guard !normalized.isEmpty else { return false }
        let prefixes = [
            "[context compressed]",
            "context compressed",
            "token budget:",
            "trigger:",
            "job:",
            "reflect run",
            "reflect job",
            "run reflect",
            "context compression"
        ]
        if prefixes.contains(where: { normalized.hasPrefix($0) }) {
            return true
        }
        let markers = [
            "\n[context compressed]",
            "reflect context compression",
            "method=reflect",
            "phase=compressing"
        ]
        return markers.contains(where: { normalized.contains($0) })
    }

    private static func chatMessages(from timeline: [[String: Any]]) -> [ChatMessage] {
        let sorted = timeline.sorted { int($0["sequence"]) < int($1["sequence"]) }
        var result: [ChatMessage] = []
        var seen = Set<String>()
        var pendingToolEvents: [ToolUseEvent] = []

        for event in sorted {
            let eventType = string(event["event_type"] ?? event["eventType"]).lowercased()
            let action = string(event["action"]).lowercased()
            let metadata = event["metadata"] as? [String: Any] ?? [:]
            let detail = event["detail"] as? [String: Any] ?? [:]

            if eventType.contains("tool") || action == "call_tool" {
                pendingToolEvents.append(contentsOf: toolUseEvents(in: event))
                continue
            }

            if eventType == "source_input" || action == "record_input" {
                let text = compactLine(
                    string(metadata["user_query"] ?? metadata["raw_user_query"] ?? detail["raw_user_query"] ?? event["content"]),
                    maxLength: 4_000
                )
                appendMessage(text, role: .user, toolEvents: [], into: &result, seen: &seen)
                continue
            }

            if eventType == "llm_answer" {
                let text = string(metadata["assistant_response"] ?? event["content"] ?? event["summary"])
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                appendMessage(text, role: .assistant, toolEvents: pendingToolEvents, into: &result, seen: &seen)
                pendingToolEvents = []
            }
        }

        if !pendingToolEvents.isEmpty {
            result.append(ChatMessage(role: .assistant, text: "", toolEvents: pendingToolEvents))
        }

        return result
    }

    private static func appendMessage(
        _ text: String,
        role: ChatMessage.Role,
        toolEvents: [ToolUseEvent],
        into result: inout [ChatMessage],
        seen: inout Set<String>
    ) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty || !toolEvents.isEmpty else { return }
        let key = "\(role)-\(trimmed.count)-\(trimmed.prefix(512))-\(toolEvents.map(\.invocationID).joined(separator: ","))"
        guard !seen.contains(key) else { return }
        seen.insert(key)
        result.append(ChatMessage(role: role, text: trimmed, toolEvents: toolEvents))
    }

    private static func compactLine(_ text: String, maxLength: Int) -> String {
        let compact = text
            .components(separatedBy: .whitespacesAndNewlines)
            .filter { !$0.isEmpty }
            .joined(separator: " ")
        return abbreviate(compact, maxLength: maxLength)
    }

    private static func herdItemIsCurrent(id: String, profile: String, snapshot: DashboardSnapshot) -> Bool {
        if !snapshot.currentStateID.isEmpty {
            return id == snapshot.currentStateID
        }
        return !profile.isEmpty && profile == snapshot.currentPersonalModelID
    }

    private static func profileAnchorFacts(
        from model: [String: Any]?,
        modelFacts: [[String: Any]]
    ) -> [ProfileAnchorFact] {
        var result: [ProfileAnchorFact] = []
        var seen = Set<String>()
        var seenPrimaryLabels = Set<String>()

        func add(label: String, value: String, full: Bool = false) {
            let cleaned = value.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !cleaned.isEmpty else { return }
            let labelKey = label.lowercased()
            guard !seenPrimaryLabels.contains(labelKey) else { return }
            let key = "\(label):\(cleaned)".lowercased()
            guard !seen.contains(key) else { return }
            seen.insert(key)
            seenPrimaryLabels.insert(labelKey)
            result.append(ProfileAnchorFact(label: label, value: cleaned, full: full))
        }

        for item in profileTopicRows {
            guard let match = modelFacts.first(where: { row in
                let metadata = object(row["metadata"])
                let status = string(row["status"], fallback: "active").lowercased()
                let topic = string(row["topic"] ?? metadata["topic"])
                return status == "active" && topic == item.topic
            }) else { continue }
            add(
                label: item.label,
                value: stripProfileFactPrefix(string(match["text"] ?? match["content"])),
                full: item.full
            )
        }

        let userProfile = object(model?["user_profile"])
        for item in profileUserRows {
            add(
                label: item.label,
                value: string(userProfile[item.key]),
                full: profileFactWantsFullRow(label: item.label, value: string(userProfile[item.key]))
            )
        }

        add(label: "Name", value: string(model?["user_preferred_name"] ?? model?["preferred_name"]))
        addListFacts("How they like to be spoken to", userProfile["communication_preferences"], into: &result, seen: &seen)
        addListFacts("Boundaries", userProfile["boundaries"], into: &result, seen: &seen)
        addListFacts("Worth remembering", userProfile["biography_fragments"], into: &result, seen: &seen)
        addListFacts("Pinned notes", userProfile["durable_notes"], into: &result, seen: &seen)
        addListFacts("What they share with you", userProfile["shared_preferences"], into: &result, seen: &seen)

        return result
    }

    private static func addListFacts(
        _ label: String,
        _ value: Any?,
        into result: inout [ProfileAnchorFact],
        seen: inout Set<String>
    ) {
        for item in listStrings(value) {
            let key = "\(label):\(item)".lowercased()
            guard !seen.contains(key) else { continue }
            seen.insert(key)
            result.append(ProfileAnchorFact(label: label, value: item, full: true))
        }
    }

    private static func listStrings(_ value: Any?) -> [String] {
        if value == nil || value is NSNull { return [] }
        if let strings = value as? [String] {
            return strings.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        }
        if let array = value as? [Any] {
            return array.map { string($0) }.filter { !$0.isEmpty }
        }
        let raw = string(value)
        guard !raw.isEmpty else { return [] }
        return raw
            .components(separatedBy: CharacterSet(charactersIn: "\n;,"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private static func mcpServerItem(from row: [String: Any]) -> MCPServerItem? {
        let serverID = string(row["serverId"] ?? row["server_id"] ?? row["id"])
        guard !serverID.isEmpty else { return nil }
        return MCPServerItem(
            serverID: serverID,
            label: string(row["label"] ?? row["serverLabel"] ?? row["server_label"], fallback: serverID),
            transport: string(row["transport"], fallback: "stdio"),
            command: string(row["command"]),
            args: listStrings(row["args"]),
            url: string(row["url"]),
            env: stringMap(row["env"]),
            envKeys: listStrings(row["envKeys"] ?? row["env_keys"]),
            headers: stringMap(row["headers"]),
            headerKeys: listStrings(row["headerKeys"] ?? row["header_keys"]),
            toolCount: int(row["toolCount"] ?? row["tool_count"]),
            provenance: string(row["provenance"])
        )
    }

    private static func mcpToolItem(from row: [String: Any]) -> MCPToolItem? {
        let serverID = string(row["serverId"] ?? row["server_id"])
        let toolName = string(row["toolName"] ?? row["tool_name"] ?? row["name"])
        guard !serverID.isEmpty, !toolName.isEmpty else { return nil }
        let toolKey = string(row["toolKey"] ?? row["tool_key"], fallback: "\(serverID):\(toolName)")
        return MCPToolItem(
            toolID: string(row["toolId"] ?? row["tool_id"], fallback: "mcp.\(serverID).\(toolName)"),
            toolKey: toolKey,
            toolName: toolName,
            serverID: serverID,
            serverLabel: string(row["serverLabel"] ?? row["server_label"], fallback: serverID),
            displayName: string(row["displayName"] ?? row["display_name"], fallback: toolName),
            description: string(row["description"]),
            family: string(row["family"], fallback: "mcp"),
            enabled: bool(row["enabled"], fallback: true),
            defaultEnabled: bool(row["defaultEnabled"] ?? row["default_enabled"], fallback: true),
            available: bool(row["available"], fallback: true),
            availabilityReason: string(row["availabilityReason"] ?? row["availability_reason"]),
            riskClass: string(row["riskClass"] ?? row["risk_class"], fallback: "medium"),
            approvalClass: string(row["approvalClass"] ?? row["approval_class"], fallback: "standard"),
            requiredFields: listStrings(row["requiredFields"] ?? row["required_fields"]),
            schemaJSON: jsonString(row["schema"])
        )
    }

    private static func stringMap(_ value: Any?) -> [String: String] {
        guard let dictionary = value as? [String: Any] else { return [:] }
        var result: [String: String] = [:]
        for (key, value) in dictionary {
            let normalizedKey = key.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !normalizedKey.isEmpty else { continue }
            result[normalizedKey] = string(value)
        }
        return result
    }

    private static func jsonString(_ value: Any?) -> String {
        guard let value,
              JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]),
              let text = String(data: data, encoding: .utf8) else {
            return "{}"
        }
        return text
    }

    private static func stripProfileFactPrefix(_ text: String) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let preferredNamePatterns = [
            #"^(?:用户)?(?:偏好|希望|喜欢)?(?:被)?(?:称为|叫做|叫|称呼为)\s*"#,
            #"^(?:Preferred name|Name|昵称|名字|称呼)[：:]\s*"#
        ]
        for pattern in preferredNamePatterns {
            if let range = trimmed.range(of: pattern, options: [.regularExpression, .caseInsensitive]) {
                let cleaned = String(trimmed[range.upperBound...])
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                    .trimmingCharacters(in: CharacterSet(charactersIn: "。．."))
                if !cleaned.isEmpty { return cleaned }
            }
        }
        guard let range = trimmed.range(of: #"^[^:：]+[：:]\s*"#, options: .regularExpression) else {
            return trimmed.trimmingCharacters(in: CharacterSet(charactersIn: "。．."))
        }
        let cleaned = String(trimmed[range.upperBound...])
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "。．."))
        return cleaned.isEmpty ? trimmed : cleaned
    }

    private static func profileFactWantsFullRow(label: String, value: String) -> Bool {
        let normalized = "\(label) \(value)".lowercased()
        return [
            "hobbies",
            "relationship mode",
            "medication allergies",
            "health notes",
            "care context",
            "safety boundaries",
            "secret",
            "mbti",
            "药物过敏"
        ].contains { normalized.contains($0) }
    }

    private static func abbreviate(_ text: String, maxLength: Int) -> String {
        guard text.count > maxLength else { return text }
        let end = text.index(text.startIndex, offsetBy: maxLength)
        return String(text[..<end]).trimmingCharacters(in: .whitespacesAndNewlines) + "..."
    }

    private static func object(_ value: Any?) -> [String: Any] {
        if let value = value as? [String: Any] { return value }
        guard let text = value as? String,
              let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data),
              let object = json as? [String: Any] else {
            return [:]
        }
        return object
    }

    private static func string(_ value: Any?, fallback: String = "") -> String {
        if value == nil || value is NSNull { return fallback }
        if let value = value as? String {
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? fallback : trimmed
        }
        if let value { return String(describing: value) }
        return fallback
    }

    private static func displayModelName(_ value: String, fallback: String) -> String {
        let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines)
        let lower = normalized.lowercased()
        if normalized.isEmpty || lower == "runtime" || lower == "runtime-step" {
            return fallback.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "unknown model" : fallback
        }
        return normalized
    }

    private static func displayNameForState(_ row: [String: Any]) -> String {
        let elephantID = string(row["elephant_id"])
        let name = string(row["elephant_name"])
        let normalized = name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let nonAgentNames = Set(["mac wake", "new wake", "current wake", "wake", "chat", "new chat", "current chat"])
        if !normalized.isEmpty,
           !nonAgentNames.contains(normalized) {
            return name
        }
        let fallback = titleCaseIdentifier(elephantID.isEmpty ? "Elephant" : elephantID)
        let normalizedFallback = fallback.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if nonAgentNames.contains(normalizedFallback) {
            return "Elephant"
        }
        return fallback
    }

    private static func titleCaseIdentifier(_ value: String) -> String {
        value
            .replacingOccurrences(of: "state:", with: "")
            .split { $0 == "-" || $0 == "_" || $0 == ":" }
            .map { part in
                let lower = part.lowercased()
                guard let first = lower.first else { return "" }
                return first.uppercased() + lower.dropFirst()
            }
            .joined(separator: " ")
    }

    private static let profileTopicRows: [(topic: String, label: String, full: Bool)] = [
        ("identity.anchor.name.preferred", "Name", false),
        ("identity.anchor.gender.self_description", "Gender", false),
        ("world.places.city.current", "City", false),
        ("identity.anchor.birth.date", "Birth date", false),
        ("identity.style.language.first", "Speaks", false),
        ("pulse.chapter.work.role", "Working on", true),
        ("identity.character.mbti.type", "MBTI", true),
        ("identity.style.hobbies.personal", "Hobbies", true),
        ("identity.style.companion.posture", "Relationship mode", true),
        ("identity.body.allergy.medication", "Medication allergies", true),
        ("identity.body.condition.chronic", "Health notes", true),
        ("identity.body.allergy.food", "Food allergies", true),
        ("identity.body.history.trauma", "Care context", true),
        ("identity.body.boundary.personal", "Safety boundaries", true)
    ]

    private static let profileUserRows: [(key: String, label: String)] = [
        ("preferred_name", "Name"),
        ("current_work", "Working on"),
        ("current_city", "City"),
        ("birth_date", "Birth date"),
        ("age", "Life stage"),
        ("gender", "Gender"),
        ("mbti", "MBTI"),
        ("hobbies", "Hobbies"),
        ("symbolic_shorthand", "Symbol"),
        ("relationship_mode", "Relationship mode"),
        ("communication_preference", "Communication"),
        ("first_language", "Speaks"),
        ("locale", "Speaks"),
        ("timezone", "Timezone"),
        ("school", "School"),
        ("dream", "Dream"),
        ("creative_hobby", "Creative hobby"),
        ("media_hobby", "Media hobby")
    ]

    private static func int(_ value: Any?) -> Int {
        if let value = value as? Int { return value }
        if let value = value as? NSNumber { return value.intValue }
        if let value = value as? String { return Int(value) ?? 0 }
        return 0
    }

    private static func double(_ value: Any?) -> Double {
        if let value = value as? Double { return value }
        if let value = value as? NSNumber { return value.doubleValue }
        if let value = value as? String { return Double(value) ?? 0 }
        return 0
    }

    private static func bool(_ value: Any?, fallback: Bool = false) -> Bool {
        if let value = value as? Bool { return value }
        if let value = value as? NSNumber { return value.boolValue }
        if let value = value as? String {
            let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            if ["true", "yes", "1", "enabled", "running", "configured"].contains(normalized) {
                return true
            }
            if ["false", "no", "0", "disabled", "stopped", "missing"].contains(normalized) {
                return false
            }
        }
        return fallback
    }
}
