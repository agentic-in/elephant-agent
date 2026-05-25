import AppKit
import CryptoKit
import Foundation
import SwiftUI
import UniformTypeIdentifiers

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
        case .skills: return "For you"
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
    var sourceID: String = ""
    var invocationID: String = ""
    var name: String
    var status: String
    var arguments: String
    var result: String
    var phase: String = ""
    var detail: String = ""
    var backend: String = ""
    var babyID: String = ""
    var babyName: String = ""
    var babyRole: String = ""
    var providerID: String = ""
    var runtimeID: String = ""
    var runtimeName: String = ""
    var runtimePath: String = ""
    var runtimeModel: String = ""
    var childEpisodeID: String = ""
    var task: String = ""

    var isChildAgentRun: Bool {
        backend == "local_cli"
            || !babyID.isEmpty
            || !childEpisodeID.isEmpty
            || arguments.contains("sub_agent_child")
    }
}

struct ChatMessage: Identifiable, Equatable {
    enum Role {
        case user
        case assistant
        case system
    }

    enum InputModality: Equatable {
        case text
        case voice
    }

    enum OutputPresentation: Equatable {
        case text
        case voice
    }

    var id = UUID()
    var role: Role
    var text: String
    var date = Date()
    var attachments: [WakeAttachment] = []
    var toolEvents: [ToolUseEvent] = []
    var isStreaming = false
    var inputModality: InputModality = .text
    var outputPresentation: OutputPresentation = .text
    var voiceDuration: TimeInterval?

    var isVoiceMessage: Bool {
        role == .user && inputModality == .voice
    }

    var isAssistantVoiceReply: Bool {
        role == .assistant && outputPresentation == .voice
    }
}

struct WakeAttachment: Identifiable, Equatable {
    enum Kind: String {
        case image
    }

    var id = UUID()
    var kind: Kind = .image
    var url: URL
    var displayName: String

    var promptFragment: String {
        "@\(kind.rawValue):\(url.path)"
    }
}

struct WakeQueuedPrompt: Identifiable, Equatable {
    var id = UUID()
    var text: String
    var attachments: [WakeAttachment] = []
    var date = Date()
    var inputModality: ChatMessage.InputModality = .text
    var voiceDuration: TimeInterval?

    var previewText: String {
        if inputModality == .voice {
            return "Voice message"
        }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty {
            return trimmed
        }
        if attachments.count == 1 {
            return attachments[0].displayName
        }
        if !attachments.isEmpty {
            return "\(attachments.count) images"
        }
        return ""
    }
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
    var metadata: [String: String] = [:]

    var isOnboardingLetter: Bool {
        let kind = (metadata["kind"] ?? metadata["letter_kind"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let source = (metadata["source"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return kind == "onboarding_letter" || source == "onboarding_letter"
    }
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
    var contextWindowTokens: Int
    var maxOutputTokens: Int
}

struct OnboardingBabyRoleTemplate: Identifiable, Equatable {
    var id: String
    var title: String
    var subtitle: String
    var prompt: String
    var symbol: String
}

func onboardingBabyRoleTemplates(for occupation: String, language: AppLanguage) -> [OnboardingBabyRoleTemplate] {
    let normalized = occupation.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    func containsAny(_ terms: [String]) -> Bool {
        terms.contains { normalized.contains($0) }
    }
    func pick(en: String, zh: String, fr: String? = nil, de: String? = nil) -> String {
        switch language {
        case .zh: return zh
        case .fr: return fr ?? en
        case .de: return de ?? en
        case .en: return en
        }
    }
    func template(_ id: String, _ titleEn: String, _ titleZh: String, _ subtitleEn: String, _ subtitleZh: String, _ promptEn: String, _ promptZh: String, _ symbol: String) -> OnboardingBabyRoleTemplate {
        OnboardingBabyRoleTemplate(
            id: id,
            title: pick(en: titleEn, zh: titleZh),
            subtitle: pick(en: subtitleEn, zh: subtitleZh),
            prompt: pick(en: promptEn, zh: promptZh),
            symbol: symbol
        )
    }

    if containsAny(["engineer", "developer", "technology", "code", "coding", "technical", "systems", "程序", "工程", "技术", "研发", "代码", "système", "technique", "technik", "technologie", "system"]) {
        return [
            template("engineering-coding", "coding baby elephant", "编码小象", "Code changes and validation.", "写代码、改代码和验证。", "Use this baby elephant for implementation plans, code changes, terminal investigation, and validation-heavy engineering work.", "把实现方案、代码修改、终端排查和验证密集的工程任务交给这只小象。", "curlybraces.square"),
            template("engineering-research", "research baby elephant", "研究小象", "Context, APIs, and tradeoffs.", "查上下文、API 和技术取舍。", "Use this baby elephant for technical research, source reading, API comparison, and implementation options.", "把技术调研、资料阅读、API 对比和实现选型交给这只小象。", "doc.text.magnifyingglass"),
            template("engineering-review", "review baby elephant", "评审小象", "Risk, quality, and tests.", "风险、质量和测试。", "Use this baby elephant for code review, regression risk checks, edge cases, and missing-test analysis.", "把代码审查、回归风险、边界情况和缺失测试分析交给这只小象。", "checkmark.shield"),
            template("engineering-debug", "debugging baby elephant", "调试小象", "Failures, logs, and root cause.", "失败、日志和根因。", "Use this baby elephant for reproductions, log reading, failing command triage, and concise root-cause notes.", "把复现、日志阅读、失败命令排查和根因摘要交给这只小象。", "stethoscope")
        ]
    }
    if containsAny(["product", "design", "产品", "设计", "ux", "ui", "produit", "expérience utilisateur", "produkt", "nutzererlebnis"]) {
        return [
            template("product-ux", "design baby elephant", "设计小象", "UX, interaction, and polish.", "体验、交互和打磨感。", "Use this baby elephant for rigorous product critique, UX acceptance, hierarchy, wording, and interaction polish.", "把严苛产品评审、UX 验收、信息层级、文案和交互打磨交给这只小象。", "sparkles.rectangle.stack"),
            template("product-strategy", "product baby elephant", "产品小象", "Tradeoffs, framing, and direction.", "取舍、定位和方向。", "Use this baby elephant for product framing, tradeoff analysis, roadmap slices, and user-first alternatives.", "把产品定位、取舍分析、路线切片和用户优先的替代方案交给这只小象。", "point.3.connected.trianglepath.dotted"),
            template("product-research", "research baby elephant", "研究小象", "Users, competitors, evidence.", "用户、竞品和证据。", "Use this baby elephant for user research, competitor scans, evidence collection, and synthesis.", "把用户研究、竞品扫描、证据收集和综合交给这只小象。", "person.text.rectangle"),
            template("product-copy", "copy baby elephant", "文案小象", "Interface language and tone.", "界面语言和语气。", "Use this baby elephant for interface copy, empty states, labels, onboarding text, and tone consistency.", "把界面文案、空状态、标签、onboarding 文案和语气一致性交给这只小象。", "text.quote")
        ]
    }
    if containsAny(["research", "student", "learning", "teaching", "study", "transition", "job search", "care", "education", "medical", "health", "研究", "学生", "学术", "学习", "教学", "转型", "求职", "换方向", "暂停", "照护", "教育", "医疗", "心理", "健康", "apprentissage", "enseignement", "recherche", "transition", "soin", "santé", "lernen", "lehren", "forschung", "fürsorge", "gesundheit"]) {
        return [
            template("research-synthesis", "research baby elephant", "研究小象", "Context, sources, and synthesis.", "上下文、资料和综合。", "Use this baby elephant for research, source comparison, reading notes, and synthesis before the primary Elephant answers.", "把研究、资料对比、阅读笔记和回答前综合交给这只小象。", "doc.text.magnifyingglass"),
            template("research-learning", "learning baby elephant", "学习小象", "Study paths and examples.", "学习路径和例子。", "Use this baby elephant for study plans, concept checks, examples, and learning follow-ups.", "把学习计划、概念检查、例子和后续学习提醒交给这只小象。", "graduationcap"),
            template("research-literature", "literature baby elephant", "文献小象", "Papers, docs, and references.", "论文、文档和引用。", "Use this baby elephant for paper digestion, long-document outlines, claims, limitations, and references.", "把论文消化、长文提纲、核心主张、局限和引用整理交给这只小象。", "books.vertical"),
            template("research-writing", "writing baby elephant", "写作小象", "Drafts, abstracts, and clarity.", "草稿、摘要和表达清晰度。", "Use this baby elephant for abstracts, paper drafts, study notes, and making complex material clear.", "把摘要、论文草稿、学习笔记和复杂材料的清晰表达交给这只小象。", "pencil.and.outline")
        ]
    }
    if containsAny(["operations", "project", "process", "workflow", "support", "admin", "customer service", "运营", "项目", "推进", "流程", "支持", "行政", "客服", "助理", "事务", "projet", "processus", "opérations", "support", "administratif", "projekt", "prozesse", "abläufe"]) {
        return [
            template("ops-project", "project baby elephant", "项目小象", "Milestones, owners, blockers.", "里程碑、责任人和阻塞。", "Use this baby elephant for project plans, owner mapping, blocker summaries, and execution rhythm.", "把项目计划、责任人梳理、阻塞摘要和推进节奏交给这只小象。", "checklist"),
            template("ops-process", "process baby elephant", "流程小象", "Systems, handoffs, repeatability.", "系统、交接和可复用流程。", "Use this baby elephant for process design, SOPs, handoffs, and repeatable operating systems.", "把流程设计、SOP、协作交接和可复用运营系统交给这只小象。", "arrow.triangle.2.circlepath"),
            template("ops-review", "review baby elephant", "复盘小象", "Signals, lessons, next changes.", "信号、经验和下一步改动。", "Use this baby elephant for weekly reviews, retrospectives, metrics notes, and improvement options.", "把周复盘、项目复盘、指标笔记和改进选项交给这只小象。", "chart.line.uptrend.xyaxis"),
            template("ops-communication", "communication baby elephant", "沟通小象", "Updates, alignment, follow-up.", "同步、对齐和跟进。", "Use this baby elephant for updates, stakeholder notes, meeting follow-ups, and clear asks.", "把进展同步、相关方笔记、会议跟进和清晰请求交给这只小象。", "bubble.left.and.bubble.right")
        ]
    }
    if containsAny(["founder", "business", "manager", "leadership", "team", "freelance", "services", "consulting", "legal", "finance", "advisory", "创业", "经营", "管理", "团队", "自由职业", "服务", "咨询", "法律", "财务", "顾问", "entreprise", "indépendant", "équipe", "services", "conseil", "droit", "finance", "gründung", "geschäft", "team", "freiberuflich", "beratung"]) {
        return [
            template("business-strategy", "strategy baby elephant", "策略小象", "Clarify direction and leverage.", "澄清方向和杠杆点。", "Use this baby elephant for strategy memos, market reads, prioritization, and decision options.", "把策略 memo、市场判断、优先级和决策选项交给这只小象。", "chart.line.uptrend.xyaxis"),
            template("business-ops", "ops baby elephant", "运营小象", "Turn plans into operating rhythm.", "把计划落成节奏。", "Use this baby elephant for operating checklists, weekly reviews, process design, and follow-through.", "把运营清单、周复盘、流程设计和推进跟踪交给这只小象。", "checklist"),
            template("business-market", "market baby elephant", "市场小象", "Positioning, audience, channels.", "定位、人群和渠道。", "Use this baby elephant for positioning, audience research, launch copy, and channel ideas.", "把定位、人群研究、发布文案和渠道想法交给这只小象。", "megaphone"),
            template("business-research", "research baby elephant", "研究小象", "Signals, competitors, evidence.", "信号、竞品和证据。", "Use this baby elephant for market research, competitor notes, customer signals, and concise decision context.", "把市场研究、竞品笔记、客户信号和决策上下文交给这只小象。", "doc.text.magnifyingglass")
        ]
    }
    if containsAny(["writer", "writing", "content", "creator", "creative", "写作", "内容", "创作", "媒体", "écriture", "contenu", "créative", "schreiben", "kreativ"]) {
        return [
            template("writing-draft", "writing baby elephant", "写作小象", "Drafts, outlines, and rewrites.", "起草、提纲和改写。", "Use this baby elephant for drafts, outlines, rewrites, structure, and voice exploration.", "把起草、提纲、改写、结构和语气探索交给这只小象。", "pencil.and.outline"),
            template("writing-editor", "editor baby elephant", "编辑小象", "Tighten arguments and rhythm.", "收紧论证和节奏。", "Use this baby elephant for editing, clarity, argument flow, repetition, and final polish.", "把编辑、清晰度、论证流、重复检查和最终润色交给这只小象。", "text.magnifyingglass"),
            template("writing-ideas", "ideas baby elephant", "灵感小象", "Angles, titles, and creative routes.", "角度、标题和创意路线。", "Use this baby elephant for angles, titles, hooks, creative alternatives, and content calendars.", "把角度、标题、开头钩子、创意替代方案和内容日历交给这只小象。", "lightbulb"),
            template("writing-research", "research baby elephant", "研究小象", "Facts, references, examples.", "事实、引用和例子。", "Use this baby elephant for fact gathering, examples, reference notes, and topic background.", "把事实收集、例子、引用笔记和选题背景交给这只小象。", "doc.text.magnifyingglass")
        ]
    }
    if containsAny(["marketing", "sales", "growth", "bd", "市场", "销售", "增长", "商务", "vente", "croissance", "vertrieb", "wachstum"]) {
        return [
            template("market-positioning", "market baby elephant", "市场小象", "Positioning, audience, channels.", "定位、人群和渠道。", "Use this baby elephant for positioning, audience research, launch copy, and channel ideas.", "把定位、人群研究、发布文案和渠道想法交给这只小象。", "megaphone"),
            template("market-customer", "customer baby elephant", "客户小象", "Pain points, objections, follow-up.", "痛点、异议和跟进。", "Use this baby elephant for customer notes, objection handling, follow-up plans, and account context.", "把客户笔记、异议处理、跟进计划和账户上下文交给这只小象。", "person.2"),
            template("market-copy", "copy baby elephant", "文案小象", "Messages, landing copy, outreach.", "信息、落地页和外联表达。", "Use this baby elephant for campaign copy, landing-page wording, outreach drafts, and concise messaging.", "把活动文案、落地页措辞、外联草稿和清晰信息表达交给这只小象。", "text.quote"),
            template("market-research", "research baby elephant", "研究小象", "Signals, competitors, evidence.", "信号、竞品和证据。", "Use this baby elephant for market signals, competitor notes, audience evidence, and synthesis.", "把市场信号、竞品笔记、人群证据和综合交给这只小象。", "doc.text.magnifyingglass")
        ]
    }
    return [
        template("general-research", "research baby elephant", "研究小象", "Context, comparison, synthesis.", "上下文、对比和综合。", "Use this baby elephant for research, comparison, and concise synthesis.", "把研究、对比和简洁综合交给这只小象。", "doc.text.magnifyingglass"),
        template("general-planning", "planning baby elephant", "规划小象", "Direction, options, next steps.", "方向、选项和下一步。", "Use this baby elephant for planning, tradeoffs, next steps, and turning unclear work into a path.", "把规划、取舍、下一步和把模糊工作变成路径交给这只小象。", "point.3.connected.trianglepath.dotted"),
        template("general-coding", "coding baby elephant", "编码小象", "Code and technical validation.", "代码和技术验证。", "Use this baby elephant for technical investigation, implementation, and validation-heavy work.", "把技术排查、实现和验证密集的工作交给这只小象。", "curlybraces.square"),
        template("general-expression", "expression baby elephant", "表达小象", "Writing, editing, and wording.", "写作、编辑和措辞。", "Use this baby elephant for writing, rewriting, naming, and turning loose material into a clear message.", "把写作、改写、命名和把松散材料变成清晰表达交给这只小象。", "text.quote")
    ]
}

struct OperationItem: Identifiable, Equatable {
    var id: String
    var title: String
    var detail: String
    var enabled: Bool
}

struct MCPServerItem: Identifiable, Equatable {
    var id: String { serverID }
    var serverID: String
    var label: String
    var transport: String
    var command: String
    var args: [String]
    var url: String
    var env: [String: String]
    var envKeys: [String]
    var headers: [String: String]
    var headerKeys: [String]
    var toolCount: Int
    var provenance: String

    var target: String {
        if transport == "stdio" || transport.isEmpty {
            return ([command] + args).filter { !$0.isEmpty }.joined(separator: " ")
        }
        return url
    }
}

struct MCPToolItem: Identifiable, Equatable {
    var id: String { toolKey }
    var toolID: String
    var toolKey: String
    var toolName: String
    var serverID: String
    var serverLabel: String
    var displayName: String
    var description: String
    var family: String
    var enabled: Bool
    var defaultEnabled: Bool
    var available: Bool
    var availabilityReason: String
    var riskClass: String
    var approvalClass: String
    var requiredFields: [String]
    var schemaJSON: String
}

struct MCPKeyValueRow: Identifiable, Equatable {
    var id = UUID()
    var key: String
    var value: String

    static let empty = MCPKeyValueRow(key: "", value: "")
}

struct MCPServerDraft: Equatable {
    var serverID: String
    var serverLabel: String
    var transport: String
    var command: String
    var argsText: String
    var url: String
    var envRows: [MCPKeyValueRow]
    var headerRows: [MCPKeyValueRow]

    static let empty = MCPServerDraft(
        serverID: "",
        serverLabel: "",
        transport: "stdio",
        command: "",
        argsText: "[]",
        url: "",
        envRows: [.empty],
        headerRows: [.empty]
    )

    static func from(server: MCPServerItem) -> MCPServerDraft {
        MCPServerDraft(
            serverID: server.serverID,
            serverLabel: server.label,
            transport: server.transport.isEmpty ? "stdio" : server.transport,
            command: server.command,
            argsText: Self.jsonString(server.args),
            url: server.url,
            envRows: Self.rows(from: server.env),
            headerRows: Self.rows(from: server.headers)
        )
    }

    static func from(jsonText: String) throws -> MCPServerDraft {
        let rawObject = try jsonObject(from: jsonText)

        if let servers = firstServerMap(in: rawObject) {
            guard let serverID = servers.keys.sorted().first,
                  let server = servers[serverID] as? [String: Any] else {
                throw MCPDraftError.invalid("MCP JSON must contain at least one server object.")
            }
            return from(serverID: serverID, object: server)
        }
        return from(serverID: string(rawObject["serverId"] ?? rawObject["serverID"] ?? rawObject["id"]), object: rawObject)
    }

    func payload(discoveredTools: [MCPDiscoveredTool] = [], enabledToolNames: Set<String> = []) throws -> [String: Any] {
        let serverID = serverID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !serverID.isEmpty else { throw MCPDraftError.invalid("Server ID is required.") }
        let normalizedTransport = transport.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "stdio" : transport.trimmingCharacters(in: .whitespacesAndNewlines)
        var body: [String: Any] = [
            "serverId": serverID,
            "serverLabel": serverLabel.trimmingCharacters(in: .whitespacesAndNewlines),
            "transport": normalizedTransport,
            "args": try Self.parseArgs(argsText),
            "env": try Self.record(from: envRows, label: "Environment"),
            "headers": try Self.record(from: headerRows, label: "Headers")
        ]
        if normalizedTransport == "stdio" {
            let command = command.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !command.isEmpty else { throw MCPDraftError.invalid("Command is required for stdio transport.") }
            body["command"] = command
            body["url"] = ""
        } else {
            let url = url.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !url.isEmpty else { throw MCPDraftError.invalid("URL is required for remote MCP transport.") }
            body["url"] = url
            body["command"] = ""
        }
        if !discoveredTools.isEmpty {
            body["tools"] = discoveredTools.map { tool in
                tool.payload(enabled: enabledToolNames.contains(tool.name))
            }
        }
        return body
    }

    func jsonText() -> String {
        let entry: [String: Any] = [
            "command": command,
            "args": (try? Self.parseArgs(argsText)) ?? [],
            "env": (try? Self.record(from: envRows, label: "Environment")) ?? [:],
            "url": url,
            "headers": (try? Self.record(from: headerRows, label: "Headers")) ?? [:],
            "transport": transport
        ].filter { _, value in
            if let text = value as? String { return !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            if let list = value as? [Any] { return !list.isEmpty }
            if let object = value as? [String: Any] { return !object.isEmpty }
            return true
        }
        return Self.jsonString(["mcpServers": [serverID.isEmpty ? "server" : serverID: entry]])
    }

    private static func from(serverID: String, object: [String: Any]) -> MCPServerDraft {
        let env = object["env"] ?? object["environment"] ?? [:]
        let commandParts = stringList(object["command"])
        let command = commandParts.first ?? string(object["command"])
        let explicitArgs = stringList(object["args"] ?? object["arguments"])
        let args = Array(commandParts.dropFirst()) + explicitArgs
        let transportValue = normalizedTransport(
            string(object["transport"] ?? object["transportType"] ?? object["type"]),
            hasURL: object["url"] != nil
        )
        return MCPServerDraft(
            serverID: serverID.isEmpty ? string(object["serverId"] ?? object["id"], fallback: "server") : serverID,
            serverLabel: string(object["serverLabel"] ?? object["label"], fallback: serverID),
            transport: transportValue,
            command: command,
            argsText: jsonString(args),
            url: string(object["url"]),
            envRows: rows(from: stringMap(env)),
            headerRows: rows(from: stringMap(object["headers"]))
        )
    }

    private static func firstServerMap(in object: [String: Any]) -> [String: Any]? {
        for key in ["mcpServers", "servers", "mcp"] {
            if let servers = object[key] as? [String: Any] {
                return servers
            }
        }
        return nil
    }

    private static func jsonObject(from jsonText: String) throws -> [String: Any] {
        let trimmed = jsonText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw MCPDraftError.invalid("JSON is empty.") }
        if let object = parseJSONObject(trimmed) {
            return object
        }
        let repaired = repairLenientJSON(trimmed)
        if repaired != trimmed, let object = parseJSONObject(repaired) {
            return object
        }
        throw MCPDraftError.invalid("MCP JSON is not valid. Check quotes, commas, and line breaks inside values.")
    }

    private static func parseJSONObject(_ text: String) -> [String: Any]? {
        guard let data = text.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        return object
    }

    private static func repairLenientJSON(_ text: String) -> String {
        var output = ""
        var inString = false
        var escaped = false
        var skippingWhitespaceAfterStringNewline = false
        for scalar in text.unicodeScalars {
            if inString {
                if escaped {
                    output.unicodeScalars.append(scalar)
                    escaped = false
                    skippingWhitespaceAfterStringNewline = false
                    continue
                }
                if scalar == "\\" {
                    output.unicodeScalars.append(scalar)
                    escaped = true
                    continue
                }
                if scalar == "\"" {
                    output.unicodeScalars.append(scalar)
                    inString = false
                    skippingWhitespaceAfterStringNewline = false
                    continue
                }
                if scalar == "\n" || scalar == "\r" {
                    skippingWhitespaceAfterStringNewline = true
                    continue
                }
                if skippingWhitespaceAfterStringNewline,
                   CharacterSet.whitespaces.contains(scalar) {
                    continue
                }
                skippingWhitespaceAfterStringNewline = false
                if scalar.value < 0x20 {
                    output.append(" ")
                    continue
                }
                output.unicodeScalars.append(scalar)
            } else {
                output.unicodeScalars.append(scalar)
                if scalar == "\"" {
                    inString = true
                }
            }
        }
        return output
            .replacingOccurrences(of: #",\s*([}\]])"#, with: "$1", options: .regularExpression)
    }

    private static func normalizedTransport(_ value: String, hasURL: Bool) -> String {
        switch value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "", "local", "stdio":
            return hasURL ? "streamable-http" : "stdio"
        case "remote":
            return "streamable-http"
        default:
            return value
        }
    }

    private static func rows(from record: [String: String]) -> [MCPKeyValueRow] {
        let rows = record.keys.sorted().map { MCPKeyValueRow(key: $0, value: record[$0] ?? "") }
        return rows.isEmpty ? [.empty] : rows
    }

    private static func record(from rows: [MCPKeyValueRow], label: String) throws -> [String: String] {
        var record: [String: String] = [:]
        for row in rows {
            let key = row.key.trimmingCharacters(in: .whitespacesAndNewlines)
            let value = row.value
            if key.isEmpty && value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { continue }
            guard !key.isEmpty else { throw MCPDraftError.invalid("\(label) key is required.") }
            guard record[key] == nil else { throw MCPDraftError.invalid("\(label) contains duplicate key: \(key)") }
            record[key] = value
        }
        return record
    }

    private static func parseArgs(_ text: String) throws -> [String] {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return [] }
        if let data = trimmed.data(using: .utf8),
           let array = try? JSONSerialization.jsonObject(with: data) as? [Any] {
            return array.map { string($0) }.filter { !$0.isEmpty }
        }
        return trimmed
            .components(separatedBy: CharacterSet(charactersIn: "\n,"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private static func stringMap(_ value: Any?) -> [String: String] {
        guard let dict = value as? [String: Any] else { return [:] }
        var record: [String: String] = [:]
        for (key, value) in dict {
            let normalized = key.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !normalized.isEmpty else { continue }
            record[normalized] = string(value)
        }
        return record
    }

    private static func stringList(_ value: Any?) -> [String] {
        if let list = value as? [Any] {
            return list.map { string($0) }.filter { !$0.isEmpty }
        }
        let text = string(value)
        return text.isEmpty ? [] : [text]
    }

    private static func string(_ value: Any?, fallback: String = "") -> String {
        if value == nil || value is NSNull { return fallback }
        if let text = value as? String {
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? fallback : trimmed
        }
        if let value { return String(describing: value) }
        return fallback
    }

    private static func jsonString(_ value: Any) -> String {
        guard JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]),
              let text = String(data: data, encoding: .utf8) else {
            return "[]"
        }
        return text
    }
}

struct MCPDiscoveredTool: Identifiable {
    var id: String { name }
    var name: String
    var description: String
    var requiredFields: [String]
    var inputSchema: [String: Any]
    var enabled: Bool = true

    func payload(enabled: Bool) -> [String: Any] {
        [
            "name": name,
            "description": description,
            "inputSchema": inputSchema,
            "enabled": enabled
        ]
    }
}

struct MCPDiscoveryResult {
    var status: String
    var serverID: String
    var serverLabel: String
    var transport: String
    var toolCount: Int
    var durationMs: Int
    var tools: [MCPDiscoveredTool]
    var error: String
    var stdout: String
    var stderr: String

    var ok: Bool { status.lowercased() == "ok" && error.isEmpty }
}

enum MCPDraftError: LocalizedError {
    case invalid(String)

    var errorDescription: String? {
        switch self {
        case .invalid(let message): return message
        }
    }
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
    var herdKind: String
    var parentElephantID: String
    var roleTitle: String
    var rolePrompt: String
    var runtimeID: String
    var providerID: String
    var runtimeStatus: String
    var authStatus: String
    var canExecute: Bool
    var cliPath: String
    var cliVersion: String
    var enabled: Bool
    var lastDelegation: String
}

struct LocalAgentRuntimeItem: Identifiable, Equatable {
    var id: String { runtimeID }
    var runtimeID: String
    var providerID: String
    var displayName: String
    var command: String
    var resolvedPath: String
    var version: String
    var status: String
    var authStatus: String
    var source: String
    var defaultModel: String
    var canExecute: Bool
    var roleTitle: String
    var rolePrompt: String
    var detectedAt: String
    var lastError: String
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

struct LearningToolCallEvent: Identifiable, Equatable {
    var id: String
    var toolID: String
    var phase: String
    var preview: String
}

struct LearningToolCallProgress: Equatable {
    var activeToolID: String
    var completedToolIDs: [String]
    var failedToolIDs: [String]
    var events: [LearningToolCallEvent]

    static let empty = LearningToolCallProgress(activeToolID: "", completedToolIDs: [], failedToolIDs: [], events: [])
}

struct LearningModelProgress: Equatable {
    var text: String
    var phase: String

    var isEmpty: Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    static let empty = LearningModelProgress(text: "", phase: "")
}

struct LearningJobItem: Identifiable, Equatable {
    var id: String
    var title: String
    var detail: String
    var status: String
    var trigger: String
    var progressStage: String
    var progressDetail: String
    var resolvedFeatures: [String]
    var resolvedTools: [String]
    var usedTools: [String]
    var toolProgress: LearningToolCallProgress
    var modelProgress: LearningModelProgress
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
    var embeddingBootstrapSource = ""
    var embeddingModelRoot = ""
    var embeddingModelSourceURL = ""
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
    var mcpConfigPath = ""
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
    var localAgentRuntimes: [LocalAgentRuntimeItem] = []
    var skillItems: [OperationItem] = []
    var toolNames: [String] = []
    var toolItems: [OperationItem] = []
    var mcpServerItems: [MCPServerItem] = []
    var mcpToolItems: [MCPToolItem] = []
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

    var localModelAvailable: Bool {
        if localModelWarm { return true }
        return Self.statusIndicatesAvailable(embeddingStatus)
            || Self.statusIndicatesAvailable(semanticStatus)
    }

    var readyForInteraction: Bool {
        providerReady && localModelAvailable
    }

    private static func statusIndicatesAvailable(_ value: String) -> Bool {
        switch value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "active", "external", "healthy", "indexed", "loaded", "ok", "ready", "serving":
            return true
        default:
            return false
        }
    }
}

@MainActor
final class ElephantAppModel: ObservableObject {
    @Published var selectedSection: AppSection = .home
    @Published var corePhase: CorePhase = .idle
    @Published var snapshot: DashboardSnapshot = .empty
    @Published var messages: [ChatMessage] = [
        ChatMessage(role: .system, text: AppText.chatReady.text(ElephantAppModel.persistedAppLanguage()))
    ]
    @Published var chatScrollRevision = 0
    @Published var wakeDraft = ""
    @Published var wakeAttachments: [WakeAttachment] = []
    @Published var wakeQueue: [WakeQueuedPrompt] = []
    @Published var onboardingName = "Elephant"
    @Published var onboardingPurpose = ElephantAppModel.persistedAppLanguage().defaultElephantVibe
    @Published var onboardingPreferredName = ""
    @Published var onboardingOccupation = ""
    @Published var onboardingSchool = ""
    @Published var onboardingCity = ""
    @Published var onboardingCurrentFocus = ""
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
    @Published var onboardingFirstLanguage = ElephantAppModel.persistedAppLanguage().rawValue
    @Published var onboardingBlogURL = ""
    @Published var onboardingLinkedInURL = ""
    @Published var onboardingTwitterURL = ""
    @Published var onboardingGroundingDepth = OnboardingGroundingDepth.standard.rawValue
    @Published var onboardingGroundingAnswers: [String: OnboardingGroundingAnswerDraft] = [:]
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
    @Published var onboardingLockPassword = ""
    @Published var onboardingLockPasswordConfirmation = ""
    @Published var onboardingStep = 0
    @Published var onboardingHerdDiscoveryStarted = false
    @Published var onboardingHerdDiscoveryComplete = false
    @Published var onboardingHerdDiscoveryStatus = ""
    @Published var onboardingSelectedRuntimeIDs: Set<String> = []
    @Published var onboardingSelectedBabyBackend = ""
    @Published var onboardingSelectedBabyRuntimeID = ""
    @Published var onboardingBabyProviderModelID = ""
    @Published var onboardingBabyTemplateID = ""
    @Published var onboardingHerdAdoptionInFlight = false
    @Published var onboardingFinalizationStarted = false
    @Published var onboardingFinalizationComplete = false
    @Published var onboardingFinalizationFailed = false
    @Published var onboardingFinalizationStatus = ""
    @Published var onboardingInitReflectJobID = ""
    @Published var onboardingLetterJobID = ""
    @Published var showingOnboarding = ElephantAppModel.onboardingPreviewMode
    @Published var onboardingLetterEntry: DiaryEntry?
    @Published var showingOnboardingLetterPrompt = false
    @Published var showingOnboardingLetterEnvelope = false
    @Published var showingCommandPalette = false
    @Published var lastError = "" {
        didSet {
            if Self.isBenignCancellationErrorMessage(lastError) {
                lastError = ""
            }
        }
    }
    @Published var providerTestResult = ""
    @Published var providerActionFailed = false
    @Published var providerActionInFlight = false
    @Published var embeddingActionResult = ""
    @Published var gatewayActionResult = ""
    @Published var gatewayActionFailed = false
    @Published var gatewayActionInFlight = false
    @Published var gatewayQRPolling = false
    @Published var gatewayQRAutoPolling = false
    @Published var gatewaySecretDrafts: [String: [String: String]] = [:]
    @Published var gatewayQR = GatewayQRState()
    @Published var cronActionResult = ""
    @Published var diaryActionResult = ""
    @Published var factActionResult = ""
    @Published var configActionResult = ""
    @Published var mcpActionResult = ""
    @Published var mcpActionFailed = false
    @Published var mcpActionInFlight = false
    @Published var isReflecting = false
    @Published var isWakeRunning = false
    @Published var activeEpisodeID = ""
    @Published var composerFocusToken = UUID()
    @Published var userAvatarPath = UserDefaults.standard.string(forKey: ElephantAppModel.userAvatarPathKey) ?? ""
    @Published var herdAvatarPaths: [String: String] = UserDefaults.standard.dictionary(forKey: ElephantAppModel.herdAvatarPathsKey) as? [String: String] ?? [:]
    @Published var hiddenEpisodeIDs: Set<String> = Set(UserDefaults.standard.stringArray(forKey: ElephantAppModel.hiddenEpisodeIDsKey) ?? [])
    @Published var isSleepDisplayPresented = ElephantAppModel.shouldPresentLaunchLockScreen()
    @Published var sleepDisplayReason = ElephantAppModel.shouldPresentLaunchLockScreen() ? "launch" : "manual"
    @Published var sleepUnlockPassword = ""
    @Published var sleepUnlockError = ""
    @Published var sleepIdleMinutes = ElephantAppModel.persistedSleepIdleMinutes()
    @Published var lastInteractionDate = Date()
    @Published var isResettingData = false
    @Published var resetDataResult = ""
    @Published var voiceRepliesEnabled = ElephantAppModel.persistedBool(
        ElephantAppModel.voiceRepliesEnabledKey,
        defaultValue: true
    )
    @Published var voiceRepliesAutoPlay = ElephantAppModel.persistedBool(
        ElephantAppModel.voiceRepliesAutoPlayKey,
        defaultValue: true
    )
    @Published var voiceReplyEngineRaw = UserDefaults.standard.string(forKey: ElephantAppModel.voiceReplyEngineKey) ?? SpeechOutputEngine.edgeOnline.rawValue
    @Published var voiceReplyVoiceIdentifier = UserDefaults.standard.string(forKey: ElephantAppModel.voiceReplyVoiceIdentifierKey) ?? ""
    @Published var voiceReplyEdgeVoiceIdentifier = UserDefaults.standard.string(forKey: ElephantAppModel.voiceReplyEdgeVoiceIdentifierKey) ?? ""
    @Published var voiceInputEngineRaw = UserDefaults.standard.string(forKey: ElephantAppModel.voiceInputEngineKey) ?? SpeechRecognitionEngine.automatic.rawValue
    @Published var voiceRuntimeActionResult = ""
    @Published var voiceRuntimeActionInFlight = false

    let speechOutput = LocalSpeechOutputController()
    private let runner = CoreRunner()
    private var client = APIClient(baseURL: nil)
    private var readinessPollTask: Task<Void, Never>?
    private var onboardingLetterPollTask: Task<Void, Never>?
    private var sleepIdleMonitorTask: Task<Void, Never>?
    private var weixinQRPollTask: Task<Void, Never>?
    private var onboardingCreatedStateID = ""
    private static let onboardingCompleteKey = "elephant.mac.onboardingComplete"
    private static let onboardingLetterSeenEntryIDKey = "elephant.mac.onboardingLetterSeenEntryID"
    private static let onboardingLetterPendingKey = "elephant.mac.onboardingLetterPending"
    private static let userAvatarPathKey = "elephant.mac.userAvatarImagePath"
    private static let herdAvatarPathsKey = "elephant.mac.herdAvatarImagePaths"
    private static let hiddenEpisodeIDsKey = "elephant.mac.hiddenEpisodeIDs"
    static let appLanguageKey = "elephant.mac.appLanguage"
    private static let voiceRepliesEnabledKey = "elephant.mac.voiceRepliesEnabled"
    private static let voiceRepliesAutoPlayKey = "elephant.mac.voiceRepliesAutoPlay"
    private static let voiceReplyEngineKey = "elephant.mac.voiceReplyEngine"
    private static let voiceReplyVoiceIdentifierKey = "elephant.mac.voiceReplyVoiceIdentifier"
    private static let voiceReplyEdgeVoiceIdentifierKey = "elephant.mac.voiceReplyEdgeVoiceIdentifier"
    private static let voiceInputEngineKey = "elephant.mac.voiceInputEngine"
    private static let sleepIdleMinutesKey = "elephant.mac.sleepIdleMinutes"
    private static let appLockPasswordRecordKey = "elephant.mac.appLockPasswordRecord"
    private static let defaultSleepIdleMinutes = 10
    private static let onboardingPreviewMode = ProcessInfo.processInfo.environment["ELEPHANT_MAC_ONBOARDING_PREVIEW"] == "1"

    static func persistedAppLanguage() -> AppLanguage {
        if let code = UserDefaults.standard.string(forKey: appLanguageKey) {
            return AppLanguage(code: code)
        }
        return .preferred
    }

    private static func persistedBool(_ key: String, defaultValue: Bool) -> Bool {
        guard UserDefaults.standard.object(forKey: key) != nil else {
            return defaultValue
        }
        return UserDefaults.standard.bool(forKey: key)
    }

    private static func hasCompletedOnboarding() -> Bool {
        UserDefaults.standard.bool(forKey: onboardingCompleteKey)
    }

    private static func shouldPresentLaunchLockScreen() -> Bool {
        !onboardingPreviewMode
            && hasCompletedOnboarding()
            && storedAppLockPasswordRecord() != nil
    }

    private static func localizedText(_ language: AppLanguage, en: String, zh: String, fr: String, de: String) -> String {
        switch language {
        case .zh: return zh
        case .fr: return fr
        case .de: return de
        case .en: return en
        }
    }

    static func localizedPublicText(_ language: AppLanguage, en: String, zh: String, fr: String, de: String) -> String {
        localizedText(language, en: en, zh: zh, fr: fr, de: de)
    }

    private static func localizedText(_ language: AppLanguage, en: String, zh: String, fr: String, de: String, _ arguments: CVarArg...) -> String {
        String(format: localizedText(language, en: en, zh: zh, fr: fr, de: de), arguments: arguments)
    }

    private static func isBenignCancellationErrorMessage(_ value: String) -> Bool {
        value.lowercased().contains("cancellationerror")
    }

    var userDisplayName: String {
        if let name = snapshot.profileFacts.first(where: { $0.label == "Name" })?.value,
           let normalized = Self.normalizedPreferredName(name),
           !normalized.isEmpty {
            return normalized
        }
        let preferred = onboardingPreferredName.trimmingCharacters(in: .whitespacesAndNewlines)
        if !preferred.isEmpty { return preferred }
        return "You"
    }

    private static func normalizedPreferredName(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let patterns = [
            #"^(?:用户)?(?:偏好|希望|喜欢)?(?:被)?(?:称为|叫做|叫|称呼为)\s*"#,
            #"^(?:Preferred name|Name|昵称|名字|称呼)[：:]\s*"#
        ]
        for pattern in patterns {
            if let range = trimmed.range(of: pattern, options: [.regularExpression, .caseInsensitive]) {
                let cleaned = String(trimmed[range.upperBound...])
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                    .trimmingCharacters(in: CharacterSet(charactersIn: "。．."))
                if !cleaned.isEmpty { return cleaned }
            }
        }
        return trimmed
    }

    var userAvatarURL: URL? {
        let path = userAvatarPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !path.isEmpty else { return nil }
        return URL(fileURLWithPath: path)
    }

    var hasAppLockPassword: Bool {
        Self.storedAppLockPasswordRecord() != nil
    }

    var onboardingLockPasswordIsValid: Bool {
        let password = onboardingLockPassword.trimmingCharacters(in: .whitespacesAndNewlines)
        return password.count >= 6 && password == onboardingLockPasswordConfirmation
    }

    var onboardingElephantMarkdown: String {
        let name = onboardingName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? "Elephant"
            : onboardingName.trimmingCharacters(in: .whitespacesAndNewlines)
        let vibe = onboardingPurpose.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? appLanguage.defaultElephantVibe
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
            let needsOnboarding = Self.onboardingPreviewMode || !snapshot.hasElephant || snapshot.providerID.isEmpty
            if needsOnboarding {
                if !Self.onboardingPreviewMode {
                    UserDefaults.standard.set(false, forKey: Self.onboardingCompleteKey)
                }
                isSleepDisplayPresented = false
                showingOnboarding = true
            } else if hasAppLockPassword {
                UserDefaults.standard.set(true, forKey: Self.onboardingCompleteKey)
                beginSleepDisplay(reason: "launch")
            }
            if UserDefaults.standard.bool(forKey: Self.onboardingLetterPendingKey) {
                startOnboardingLetterPollingIfNeeded()
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
        syncAppLanguageFromSnapshot(next)
        snapshot = next
        syncOnboardingLetterState(from: next)
        if snapshot.readyForInteraction {
            readinessPollTask?.cancel()
            readinessPollTask = nil
        } else if corePhase == .ready {
            startReadinessPollingIfNeeded()
        }
    }

    func refreshProviderCatalogForOnboarding() async {
        if !snapshot.providerOptions.isEmpty { return }
        do {
            if client.baseURL == nil {
                let runtime = try await runner.start()
                client = APIClient(baseURL: runtime.baseURL)
                snapshot.apiURL = runtime.baseURL.absoluteString
                snapshot.databasePath = runtime.databasePath.path
            }
            let providerOptions = try await client.fetchProviderCatalog()
            if !providerOptions.isEmpty {
                snapshot.providerOptions = providerOptions
                return
            }
            try await refreshDashboard()
        } catch {
            lastError = error.localizedDescription
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

    private func syncOnboardingLetterState(from snapshot: DashboardSnapshot) {
        guard let entry = snapshot.diaryEntries.first(where: { $0.isOnboardingLetter }) else { return }
        onboardingLetterEntry = entry
        UserDefaults.standard.set(false, forKey: Self.onboardingLetterPendingKey)
        onboardingLetterPollTask?.cancel()
        onboardingLetterPollTask = nil

        let seenEntryID = UserDefaults.standard.string(forKey: Self.onboardingLetterSeenEntryIDKey) ?? ""
        guard !showingOnboarding, seenEntryID != entry.id else { return }
        withAnimation(.spring(response: 0.42, dampingFraction: 0.88)) {
            showingOnboardingLetterPrompt = true
        }
    }

    private func markOnboardingLetterPending() {
        UserDefaults.standard.set(true, forKey: Self.onboardingLetterPendingKey)
        startOnboardingLetterPollingIfNeeded()
    }

    private func startOnboardingLetterPollingIfNeeded() {
        guard corePhase == .ready, onboardingLetterPollTask == nil else { return }
        onboardingLetterPollTask = Task { [weak self] in
            for _ in 0..<96 {
                guard let self else { return }
                if Task.isCancelled { return }
                do {
                    try await self.refreshDashboard()
                    if self.onboardingLetterEntry != nil {
                        return
                    }
                } catch {
                    self.lastError = error.localizedDescription
                }
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
            self?.onboardingLetterPollTask = nil
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
                ChatMessage(role: .system, text: text(.resetChatReady))
            ]
            chatScrollRevision += 1
            try await refreshDashboard()
            corePhase = .ready
            selectedSection = .home
            showingOnboarding = true
            resetDataResult = text(.resetComplete)
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
        try await client.configureLocalEmbedding(
            source: appLanguage.defaultEmbeddingModelSource,
            forceDownload: false
        )
        let stateID: String
        if onboardingCreatedStateID.isEmpty {
            stateID = try await client.createElephant(name: onboardingName, identityText: onboardingElephantMarkdown)
            onboardingCreatedStateID = stateID
            _ = try? await client.scanLocalAgents()
        } else {
            stateID = onboardingCreatedStateID
        }
        try await client.updateUserProfile(
            stateID: stateID,
            preferredName: onboardingPreferredName,
            occupation: onboardingOccupation,
            school: onboardingSchool,
            city: onboardingCity,
            currentFocus: onboardingCurrentFocus,
            gender: onboardingGender,
            birthDate: onboardingBirthDate,
            mbti: onboardingMBTI,
            hobbies: onboardingHobbies,
            dream: onboardingDream,
            creativeHobby: onboardingCreativeHobby,
            mediaHobby: onboardingMediaHobby,
            movementHobby: onboardingMovementHobby,
            safetyBoundaries: onboardingCareSummary,
            firstLanguage: appLanguage.rawValue,
            blogURL: onboardingBlogURL,
            linkedInURL: onboardingLinkedInURL,
            twitterURL: onboardingTwitterURL,
            personalLogoPath: userAvatarPath,
            innerLandscape: onboardingInnerLandscape,
            valueAnchor: onboardingValueAnchor,
            pressurePattern: onboardingPressurePattern,
            recoveryStyle: onboardingRecoveryStyle,
            decisionCompass: onboardingDecisionCompass,
            groundingAnswers: onboardingGroundingAnswerRecords()
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
        onboardingFinalizationStatus = text(.learningCreateModel)
        onboardingInitReflectJobID = ""
        onboardingLetterJobID = ""
        lastError = ""
        do {
            let stateID = try await createElephantProfileFromOnboarding()
            onboardingFinalizationStatus = text(.learningOpenEpisode)
            try await refreshDashboard()
            let resolvedStateID = snapshot.currentStateID.isEmpty ? stateID : snapshot.currentStateID
            let episodeID = try await client.ensureWakeEpisode(
                personalModelID: snapshot.currentPersonalModelID,
                elephantID: resolvedStateID,
                activeEpisodeID: ""
            )
            activeEpisodeID = episodeID
            onboardingFinalizationStatus = text(.learningStartReflect)
            let jobID = try await client.runReflect(trigger: "init_profile")
            onboardingInitReflectJobID = jobID
            markOnboardingLetterPending()
            try await pollOnboardingInitReflectJob(jobID: jobID)
        } catch {
            onboardingFinalizationFailed = true
            onboardingFinalizationStarted = false
            onboardingFinalizationStatus = text(.learningNeedsAttention)
            lastError = error.localizedDescription
        }
    }

    private func pollOnboardingInitReflectJob(jobID: String) async throws {
        let maxAttempts = 180
        for attempt in 0..<maxAttempts {
            if Task.isCancelled { return }
            onboardingFinalizationStatus = attempt < 2 ? text(.learningFromAnswers) : text(.learningFinishing)
            try await refreshDashboard()
            if let job = onboardingInitReflectJob(jobID: jobID) {
                let status = job.status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                if status.contains("completed") || status.contains("succeeded") || status == "success" {
                    onboardingFinalizationStatus = text(.learningReady)
                    onboardingFinalizationComplete = true
                    scheduleOnboardingAutoCompletion()
                    return
                }
                if status.contains("failed") || status.contains("cancel") || status.contains("error") {
                    throw APIClientError.badStatus(job.detail.isEmpty ? "The init learning job did not complete." : job.detail)
                }
            }
            try await Task.sleep(nanoseconds: 1_000_000_000)
        }
        onboardingFinalizationStatus = text(.learningReady)
        onboardingFinalizationComplete = true
        scheduleOnboardingAutoCompletion()
    }

    private func scheduleOnboardingAutoCompletion() {
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 850_000_000)
            await MainActor.run {
                guard let self,
                      self.showingOnboarding,
                      self.onboardingFinalizationComplete
                else { return }
                self.completeOnboarding()
            }
        }
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

    var onboardingLearningJob: LearningJobItem? {
        onboardingInitReflectJob(jobID: onboardingInitReflectJobID)
    }

    func completeOnboarding() {
        UserDefaults.standard.set(true, forKey: Self.onboardingCompleteKey)
        showingOnboarding = false
        selectedSection = .home
        syncOnboardingLetterState(from: snapshot)
        if onboardingLetterEntry == nil, UserDefaults.standard.bool(forKey: Self.onboardingLetterPendingKey) {
            startOnboardingLetterPollingIfNeeded()
        }
    }

    func skipOnboardingLearningAndContinue() {
        onboardingFinalizationFailed = false
        onboardingFinalizationComplete = true
        onboardingFinalizationStatus = text(.learningReady)
        completeOnboarding()
    }

    func startNewChat() {
        speechOutput.stop()
        activeEpisodeID = ""
        messages = [
            ChatMessage(role: .system, text: text(.newConversationReady))
        ]
        selectedSection = .wake
        focusComposer()
    }

    func openEpisodeThread(_ thread: EpisodeThread) {
        speechOutput.stop()
        activeEpisodeID = thread.id
        if thread.messages.isEmpty {
            messages = [
                ChatMessage(role: .system, text: thread.summary.isEmpty ? text(.noRenderedMessagesYet) : thread.summary)
            ]
        } else {
            messages = thread.messages
        }
        selectedSection = .wake
        focusComposer()
    }

    var voiceReplyVoiceOptions: [LocalSpeechVoiceOption] {
        LocalSpeechOutputController.voiceOptions(for: appLanguage)
    }

    var voiceReplyEdgeVoiceOptions: [EdgeSpeechVoiceOption] {
        LocalSpeechOutputController.edgeVoiceOptions(for: appLanguage)
    }

    var voiceReplyEngine: SpeechOutputEngine {
        SpeechOutputEngine(rawValue: voiceReplyEngineRaw) ?? .edgeOnline
    }

    var voiceInputEngine: SpeechRecognitionEngine {
        SpeechRecognitionEngine(rawValue: voiceInputEngineRaw) ?? .automatic
    }

    var effectiveEdgeVoiceIdentifier: String {
        voiceReplyEdgeVoiceOptions.contains { $0.id == voiceReplyEdgeVoiceIdentifier }
            ? voiceReplyEdgeVoiceIdentifier
            : LocalSpeechOutputController.defaultEdgeVoiceIdentifier(for: appLanguage)
    }

    var voiceReplyVoiceSummary: String {
        if voiceReplyEngine == .edgeOnline {
            return LocalSpeechOutputController.edgeVoiceDisplayName(
                identifier: effectiveEdgeVoiceIdentifier,
                language: appLanguage
            )
        }
        let selected = voiceReplyVoiceOptions.first { $0.id == voiceReplyVoiceIdentifier }
        if let selected {
            return selected.displayName
        }
        if let voice = LocalSpeechOutputController.preferredVoice(
            language: appLanguage,
            preferredIdentifier: voiceReplyVoiceIdentifier
        ) {
            return "\(voice.name) · \(voice.language)"
        }
        return Self.localizedText(appLanguage, en: "System default", zh: "系统默认", fr: "Voix système", de: "Systemstimme")
    }

    var voiceReplyEngineLabel: String {
        switch voiceReplyEngine {
        case .edgeOnline:
            return Self.localizedText(appLanguage, en: "High-quality online voice", zh: "高质量在线声音", fr: "Voix en ligne haute qualité", de: "Hochwertige Online-Stimme")
        case .systemAVSpeech:
            return Self.localizedText(appLanguage, en: "Apple local voice", zh: "Apple 本机声音", fr: "Voix locale Apple", de: "Lokale Apple-Stimme")
        }
    }

    var voiceInputEngineLabel: String {
        switch voiceInputEngine {
        case .automatic:
            return appLanguage == .zh && SpeechInputController.funASRInstalled
                ? Self.localizedText(appLanguage, en: "Auto · local Chinese", zh: "自动 · 本地中文", fr: "Auto · chinois local", de: "Auto · lokales Chinesisch")
                : Self.localizedText(appLanguage, en: "Auto · system dictation", zh: "自动 · 系统听写", fr: "Auto · dictée système", de: "Auto · Systemdiktat")
        case .funASRLocal:
            return SpeechInputController.funASRInstalled
                ? Self.localizedText(appLanguage, en: "Local Chinese", zh: "本地中文", fr: "Chinois local", de: "Lokales Chinesisch")
                : Self.localizedText(appLanguage, en: "Local Chinese · setup needed", zh: "本地中文 · 需启用", fr: "Chinois local · configuration requise", de: "Lokales Chinesisch · Einrichtung nötig")
        case .appleSpeech:
            return Self.localizedText(appLanguage, en: "System dictation", zh: "系统听写", fr: "Dictée système", de: "Systemdiktat")
        }
    }

    var chineseSpeechRecognitionStatus: String {
        if SpeechInputController.funASRInstalled {
            return Self.localizedText(appLanguage, en: "Ready on this Mac", zh: "本机已就绪", fr: "Prêt sur ce Mac", de: "Auf diesem Mac bereit")
        }
        return Self.localizedText(appLanguage, en: "Setup required; Chinese currently uses system dictation", zh: "需要启用；当前使用系统中文听写", fr: "Configuration requise ; le chinois utilise la dictée système", de: "Einrichtung nötig; Chinesisch nutzt Systemdiktat")
    }

    func setVoiceRepliesEnabled(_ enabled: Bool) {
        voiceRepliesEnabled = enabled
        UserDefaults.standard.set(enabled, forKey: Self.voiceRepliesEnabledKey)
        if !enabled {
            speechOutput.stop()
        }
    }

    func setVoiceRepliesAutoPlay(_ enabled: Bool) {
        voiceRepliesAutoPlay = enabled
        UserDefaults.standard.set(enabled, forKey: Self.voiceRepliesAutoPlayKey)
    }

    func setVoiceReplyEngine(_ engine: SpeechOutputEngine) {
        voiceReplyEngineRaw = engine.rawValue
        UserDefaults.standard.set(engine.rawValue, forKey: Self.voiceReplyEngineKey)
        speechOutput.stop()
    }

    func setVoiceReplyVoiceIdentifier(_ identifier: String) {
        voiceReplyVoiceIdentifier = identifier
        UserDefaults.standard.set(identifier, forKey: Self.voiceReplyVoiceIdentifierKey)
    }

    func setVoiceReplyEdgeVoiceIdentifier(_ identifier: String) {
        voiceReplyEdgeVoiceIdentifier = identifier
        UserDefaults.standard.set(identifier, forKey: Self.voiceReplyEdgeVoiceIdentifierKey)
    }

    func setVoiceInputEngine(_ engine: SpeechRecognitionEngine) {
        voiceInputEngineRaw = engine.rawValue
        UserDefaults.standard.set(engine.rawValue, forKey: Self.voiceInputEngineKey)
    }

    func stopVoiceReply() {
        speechOutput.stop()
    }

    func previewVoiceReply() {
        speechOutput.speakPreview(
            language: appLanguage,
            engine: voiceReplyEngine,
            systemVoiceIdentifier: voiceReplyVoiceIdentifier,
            edgeVoiceIdentifier: effectiveEdgeVoiceIdentifier
        )
    }

    func installChineseSpeechRecognition() async {
        guard !voiceRuntimeActionInFlight else { return }
        voiceRuntimeActionInFlight = true
        voiceRuntimeActionResult = Self.localizedText(appLanguage, en: "Installing local Chinese recognition...", zh: "正在安装本地中文识别...", fr: "Installation de la reconnaissance chinoise locale...", de: "Installiere lokale chinesische Erkennung...")
        do {
            _ = try await SpeechInputController.installFunASRRuntime()
            voiceRuntimeActionResult = Self.localizedText(appLanguage, en: "Local Chinese recognition is ready.", zh: "本地中文识别已就绪。", fr: "La reconnaissance chinoise locale est prête.", de: "Lokale chinesische Erkennung ist bereit.")
        } catch {
            voiceRuntimeActionResult = error.localizedDescription
            lastError = error.localizedDescription
        }
        voiceRuntimeActionInFlight = false
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
        guard Self.hasCompletedOnboarding(), !showingOnboarding else { return }
        speechOutput.stop()
        sleepDisplayReason = reason
        sleepUnlockPassword = ""
        sleepUnlockError = ""
        isSleepDisplayPresented = true
    }

    func dismissSleepDisplay() {
        guard isSleepDisplayPresented else {
            lastInteractionDate = Date()
            return
        }
        isSleepDisplayPresented = false
        sleepUnlockPassword = ""
        sleepUnlockError = ""
        lastInteractionDate = Date()
    }

    func registerUserActivity() {
        if isSleepDisplayPresented {
            lastInteractionDate = Date()
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

    @discardableResult
    func persistOnboardingLockPassword() -> Bool {
        guard onboardingLockPasswordIsValid else { return false }
        return setAppLockPassword(onboardingLockPassword)
    }

    @discardableResult
    func setAppLockPassword(_ password: String) -> Bool {
        let trimmed = password.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 6 else { return false }
        UserDefaults.standard.set(Self.makeAppLockPasswordRecord(for: trimmed), forKey: Self.appLockPasswordRecordKey)
        return true
    }

    func clearAppLockPassword() {
        UserDefaults.standard.removeObject(forKey: Self.appLockPasswordRecordKey)
        sleepUnlockPassword = ""
        sleepUnlockError = ""
    }

    func verifySleepUnlock() {
        if !hasAppLockPassword {
            dismissSleepDisplay()
            return
        }
        if Self.password(sleepUnlockPassword, matches: Self.storedAppLockPasswordRecord()) {
            dismissSleepDisplay()
        } else {
            sleepUnlockError = text(.sleepPasswordWrong)
        }
    }

    func pickUserAvatar() {
        guard let url = OpenPanelBridge.pickAvatarImageURL(language: appLanguage) else { return }
        do {
            let destination = try persistUserAvatar(from: url)
            userAvatarPath = destination.path
            UserDefaults.standard.set(destination.path, forKey: Self.userAvatarPathKey)
        } catch {
            lastError = error.localizedDescription
        }
    }

    func pickHerdAvatar(for item: HerdItem) {
        guard let url = OpenPanelBridge.pickAvatarImageURL(language: appLanguage) else { return }
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

    func requestOnboardingLetter() async {
        guard !isReflecting else { return }
        isReflecting = true
        do {
            let jobID = try await client.runReflect(trigger: "onboarding_letter")
            onboardingLetterJobID = jobID
            markOnboardingLetterPending()
            diaryActionResult = Self.localizedText(
                appLanguage,
                en: "Elephant is writing your letter.",
                zh: "Elephant 正在给你写信。",
                fr: "Elephant écrit votre lettre.",
                de: "Elephant schreibt deinen Brief."
            )
            try? await Task.sleep(nanoseconds: 700_000_000)
            try await refreshDashboard()
        } catch {
            lastError = error.localizedDescription
        }
        isReflecting = false
    }

    func openOnboardingLetter(_ entry: DiaryEntry? = nil) {
        if let entry {
            onboardingLetterEntry = entry
        }
        guard onboardingLetterEntry != nil else { return }
        showingOnboardingLetterPrompt = false
        showingOnboardingLetterEnvelope = true
        if let entryID = onboardingLetterEntry?.id, !entryID.isEmpty {
            UserDefaults.standard.set(entryID, forKey: Self.onboardingLetterSeenEntryIDKey)
        }
    }

    func dismissOnboardingLetterPrompt(markSeen: Bool = true) {
        showingOnboardingLetterPrompt = false
        if markSeen, let entryID = onboardingLetterEntry?.id, !entryID.isEmpty {
            UserDefaults.standard.set(entryID, forKey: Self.onboardingLetterSeenEntryIDKey)
        }
    }

    func closeOnboardingLetterEnvelope() {
        showingOnboardingLetterEnvelope = false
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
        providerActionInFlight = true
        providerActionFailed = false
        providerTestResult = localizedProviderActionText("test_running")
        defer { providerActionInFlight = false }
        do {
            let reply = try await client.testProvider()
            providerActionFailed = false
            providerTestResult = localizedProviderActionText("test_success", detail: reply)
            try? await refreshDashboard()
        } catch {
            providerActionFailed = true
            providerTestResult = localizedProviderActionText("test_failed", detail: error.localizedDescription)
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
        providerActionInFlight = true
        providerActionFailed = false
        providerTestResult = localizedProviderActionText("save_running")
        defer { providerActionInFlight = false }
        do {
            try await client.configureProvider(
                providerID: providerID,
                baseURL: baseURL,
                modelID: modelID,
                apiKey: apiKey,
                contextWindow: contextWindow
            )
            try await refreshDashboard()
            providerActionFailed = false
            providerTestResult = localizedProviderActionText("save_success")
        } catch {
            providerActionFailed = true
            providerTestResult = localizedProviderActionText("save_failed", detail: error.localizedDescription)
            lastError = error.localizedDescription
        }
    }

    func saveLocalEmbeddingSettings(source: String, forceDownload: Bool) async {
        do {
            try await client.configureLocalEmbedding(source: source, forceDownload: forceDownload)
            try await refreshDashboard()
            let normalized = source.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            let label = normalized == "modelscope" ? "ModelScope" : "HuggingFace"
            embeddingActionResult = localizedEmbeddingActionResult(label: label, forceDownload: forceDownload)
        } catch {
            embeddingActionResult = ""
            lastError = error.localizedDescription
        }
    }

    private func localizedEmbeddingActionResult(label: String, forceDownload: Bool) -> String {
        switch appLanguage {
        case .zh:
            return forceDownload ? "已从 \(label) 重新开始下载记忆模型。" : "记忆模型来源已切换为 \(label)。"
        case .fr:
            return forceDownload ? "Téléchargement du modèle mémoire relancé depuis \(label)." : "Source du modèle mémoire définie sur \(label)."
        case .de:
            return forceDownload ? "Download des Speichermodells von \(label) neu gestartet." : "Quelle des Speichermodells auf \(label) gesetzt."
        case .en:
            return forceDownload ? "Memory model download restarted from \(label)." : "Memory model source set to \(label)."
        }
    }

    func discoverProviderModels(providerID: String, baseURL: String, apiKey: String) async -> [ProviderModelOption] {
        do {
            let rows = try await client.discoverProviderModels(providerID: providerID, baseURL: baseURL, apiKey: apiKey)
            providerActionFailed = false
            providerTestResult = rows.isEmpty ? localizedProviderActionText("fetch_empty") : localizedProviderActionText("fetch_success", count: rows.count)
            return rows
        } catch {
            providerActionFailed = true
            providerTestResult = localizedProviderActionText("fetch_failed", detail: error.localizedDescription)
            lastError = error.localizedDescription
            return []
        }
    }

    private func localizedProviderActionText(_ key: String, detail: String = "", count: Int = 0) -> String {
        switch appLanguage {
        case .zh:
            switch key {
            case "test_running": return "正在测试模型服务..."
            case "test_success": return detail.isEmpty ? "测试成功。" : "测试成功：\(detail)"
            case "test_failed": return detail.isEmpty ? "测试失败。" : "测试失败：\(detail)"
            case "save_running": return "正在保存模型服务..."
            case "save_success": return "保存成功。"
            case "save_failed": return detail.isEmpty ? "保存失败。" : "保存失败：\(detail)"
            case "fetch_empty": return "模型列表刷新完成，但没有返回可用模型。"
            case "fetch_success": return "模型列表已刷新：\(count) 个模型。"
            case "fetch_failed": return detail.isEmpty ? "模型列表刷新失败。" : "模型列表刷新失败：\(detail)"
            default: return detail
            }
        case .fr:
            switch key {
            case "test_running": return "Test du provider..."
            case "test_success": return detail.isEmpty ? "Test réussi." : "Test réussi : \(detail)"
            case "test_failed": return detail.isEmpty ? "Test échoué." : "Test échoué : \(detail)"
            case "save_running": return "Enregistrement du provider..."
            case "save_success": return "Enregistrement réussi."
            case "save_failed": return detail.isEmpty ? "Enregistrement échoué." : "Enregistrement échoué : \(detail)"
            case "fetch_empty": return "Liste des modèles actualisée, aucun modèle disponible."
            case "fetch_success": return "Liste des modèles actualisée : \(count) modèles."
            case "fetch_failed": return detail.isEmpty ? "Actualisation des modèles échouée." : "Actualisation des modèles échouée : \(detail)"
            default: return detail
            }
        case .de:
            switch key {
            case "test_running": return "Provider wird getestet..."
            case "test_success": return detail.isEmpty ? "Test erfolgreich." : "Test erfolgreich: \(detail)"
            case "test_failed": return detail.isEmpty ? "Test fehlgeschlagen." : "Test fehlgeschlagen: \(detail)"
            case "save_running": return "Provider wird gespeichert..."
            case "save_success": return "Speichern erfolgreich."
            case "save_failed": return detail.isEmpty ? "Speichern fehlgeschlagen." : "Speichern fehlgeschlagen: \(detail)"
            case "fetch_empty": return "Modellliste aktualisiert, aber ohne verfügbare Modelle."
            case "fetch_success": return "Modellliste aktualisiert: \(count) Modelle."
            case "fetch_failed": return detail.isEmpty ? "Modellliste konnte nicht aktualisiert werden." : "Modellliste konnte nicht aktualisiert werden: \(detail)"
            default: return detail
            }
        case .en:
            switch key {
            case "test_running": return "Testing provider..."
            case "test_success": return detail.isEmpty ? "Test succeeded." : "Test succeeded: \(detail)"
            case "test_failed": return detail.isEmpty ? "Test failed." : "Test failed: \(detail)"
            case "save_running": return "Saving provider..."
            case "save_success": return "Save succeeded."
            case "save_failed": return detail.isEmpty ? "Save failed." : "Save failed: \(detail)"
            case "fetch_empty": return "Model list refreshed, but no live models were returned."
            case "fetch_success": return "Model list refreshed: \(count) models."
            case "fetch_failed": return detail.isEmpty ? "Model list refresh failed." : "Model list refresh failed: \(detail)"
            default: return detail
            }
        }
    }

    private func localizedGatewayActionText(_ key: String, detail: String = "") -> String {
        func withDetail(_ base: String) -> String {
            detail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? base : "\(base) \(detail)"
        }
        switch appLanguage {
        case .zh:
            switch key {
            case "start_running": return "正在启动聊天连接..."
            case "start_success": return "聊天连接已启动，可以回到对应聊天里发消息了。"
            case "start_failed": return withDetail("聊天连接启动失败。")
            case "restart_running": return "正在重新连接聊天服务..."
            case "restart_success": return "聊天服务已重新连接。"
            case "restart_failed": return withDetail("聊天服务重新连接失败。")
            case "stop_running": return "正在停止聊天连接..."
            case "stop_success": return "聊天连接已停止。"
            case "stop_failed": return withDetail("聊天连接停止失败。")
            case "configure_running": return "正在保存消息渠道配置..."
            case "configure_success": return "消息渠道配置已保存。"
            case "configure_failed": return withDetail("消息渠道配置保存失败。")
            case "qr_starting": return "正在生成微信二维码..."
            case "qr_start_failed": return withDetail("微信二维码生成失败。")
            case "qr_checking": return "正在检查扫码状态..."
            case "qr_poll_failed": return withDetail("扫码状态检查失败。")
            case "qr_confirmed_starting": return "微信已确认，正在刷新账号并启动聊天连接..."
            case "qr_confirmed_missing_service": return "微信已确认，但本地运行时没有返回 WeChat 服务；请刷新后再启动。"
            default: return detail
            }
        case .fr:
            switch key {
            case "start_running": return "Connexion au chat en cours..."
            case "start_success": return "Chat connecté. Vous pouvez écrire dans le chat associé."
            case "start_failed": return withDetail("Connexion au chat échouée.")
            case "restart_running": return "Reconnexion au chat..."
            case "restart_success": return "Chat reconnecté."
            case "restart_failed": return withDetail("Reconnexion au chat échouée.")
            case "stop_running": return "Arrêt de la connexion au chat..."
            case "stop_success": return "Connexion au chat arrêtée."
            case "stop_failed": return withDetail("Arrêt de la connexion au chat échoué.")
            case "configure_running": return "Enregistrement de la configuration..."
            case "configure_success": return "Configuration de messagerie enregistrée."
            case "configure_failed": return withDetail("Échec de l'enregistrement de la configuration.")
            case "qr_starting": return "Génération du QR WeChat..."
            case "qr_start_failed": return withDetail("Échec de la génération du QR WeChat.")
            case "qr_checking": return "Vérification du scan..."
            case "qr_poll_failed": return withDetail("Échec de la vérification du scan.")
            case "qr_confirmed_starting": return "WeChat confirmé. Actualisation du compte et connexion au chat..."
            case "qr_confirmed_missing_service": return "WeChat est confirmé, mais le runtime local n'a pas renvoyé le service WeChat."
            default: return detail
            }
        case .de:
            switch key {
            case "start_running": return "Chat-Verbindung wird gestartet..."
            case "start_success": return "Chat ist verbunden. Du kannst im verbundenen Chat schreiben."
            case "start_failed": return withDetail("Chat-Verbindung konnte nicht gestartet werden.")
            case "restart_running": return "Chat wird neu verbunden..."
            case "restart_success": return "Chat wurde neu verbunden."
            case "restart_failed": return withDetail("Chat konnte nicht neu verbunden werden.")
            case "stop_running": return "Chat-Verbindung wird beendet..."
            case "stop_success": return "Chat-Verbindung wurde beendet."
            case "stop_failed": return withDetail("Chat-Verbindung konnte nicht beendet werden.")
            case "configure_running": return "Nachrichtenkanal wird gespeichert..."
            case "configure_success": return "Nachrichtenkanal gespeichert."
            case "configure_failed": return withDetail("Nachrichtenkanal konnte nicht gespeichert werden.")
            case "qr_starting": return "WeChat-QR wird erstellt..."
            case "qr_start_failed": return withDetail("WeChat-QR konnte nicht erstellt werden.")
            case "qr_checking": return "Scanstatus wird geprüft..."
            case "qr_poll_failed": return withDetail("Scanstatus konnte nicht geprüft werden.")
            case "qr_confirmed_starting": return "WeChat bestätigt. Konto wird aktualisiert und Chat verbunden..."
            case "qr_confirmed_missing_service": return "WeChat ist bestätigt, aber die lokale Runtime hat keinen WeChat-Dienst zurückgegeben."
            default: return detail
            }
        case .en:
            switch key {
            case "start_running": return "Connecting chat..."
            case "start_success": return "Chat connected. You can message from the connected chat now."
            case "start_failed": return withDetail("Chat connection failed to start.")
            case "restart_running": return "Reconnecting chat..."
            case "restart_success": return "Chat reconnected."
            case "restart_failed": return withDetail("Chat failed to reconnect.")
            case "stop_running": return "Disconnecting chat..."
            case "stop_success": return "Chat disconnected."
            case "stop_failed": return withDetail("Chat failed to disconnect.")
            case "configure_running": return "Saving messaging channel..."
            case "configure_success": return "Messaging channel saved."
            case "configure_failed": return withDetail("Messaging channel failed to save.")
            case "qr_starting": return "Generating WeChat QR..."
            case "qr_start_failed": return withDetail("WeChat QR failed to start.")
            case "qr_checking": return "Checking scan status..."
            case "qr_poll_failed": return withDetail("Scan status check failed.")
            case "qr_confirmed_starting": return "WeChat confirmed. Refreshing the account and connecting chat..."
            case "qr_confirmed_missing_service": return "WeChat is confirmed, but the local runtime did not return the WeChat service."
            default: return detail
            }
        }
    }

    private func localizedWeixinQRStatusText(_ status: String, fallback: String = "") -> String {
        let normalized = status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized == "confirmed" {
            return localizedGatewayActionText("qr_confirmed_starting")
        }
        if normalized == "expired" || normalized.contains("expire") {
            switch appLanguage {
            case .zh: return "二维码已过期，请重新生成。"
            case .fr: return "Le QR a expiré. Générez-en un nouveau."
            case .de: return "Der QR ist abgelaufen. Bitte neu erstellen."
            case .en: return "The QR code expired. Generate a new one."
            }
        }
        if normalized == "need_verifycode" {
            switch appLanguage {
            case .zh: return "已扫描，请在手机上确认验证码。"
            case .fr: return "QR scanné. Confirmez le code sur votre téléphone."
            case .de: return "QR gescannt. Bitte Code am Telefon bestätigen."
            case .en: return "Scanned. Confirm the verification code on your phone."
            }
        }
        if normalized == "scaned_but_redirect" {
            switch appLanguage {
            case .zh: return "已扫描，正在切换校验通道..."
            case .fr: return "QR scanné. Changement du canal de vérification..."
            case .de: return "QR gescannt. Prüfkanal wird gewechselt..."
            case .en: return "Scanned. Switching verification channel..."
            }
        }
        if normalized.contains("fail") || normalized.contains("error") || normalized.contains("cancel") || normalized.contains("reject") {
            let trimmed = fallback.trimmingCharacters(in: .whitespacesAndNewlines)
            switch appLanguage {
            case .zh: return trimmed.isEmpty ? "扫码登录失败，请重新生成二维码。" : "扫码登录失败：\(trimmed)"
            case .fr: return trimmed.isEmpty ? "Connexion QR échouée. Générez un nouveau QR." : "Connexion QR échouée : \(trimmed)"
            case .de: return trimmed.isEmpty ? "QR-Anmeldung fehlgeschlagen. Bitte neu erstellen." : "QR-Anmeldung fehlgeschlagen: \(trimmed)"
            case .en: return trimmed.isEmpty ? "QR login failed. Generate a new QR code." : "QR login failed: \(trimmed)"
            }
        }
        switch appLanguage {
        case .zh: return "二维码已生成。扫码后这里会自动更新状态。"
        case .fr: return "QR généré. Le statut se mettra à jour automatiquement après le scan."
        case .de: return "QR erstellt. Der Status aktualisiert sich nach dem Scan automatisch."
        case .en: return "QR code generated. This status updates automatically after scanning."
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

    func discoverMCPServer(draft: MCPServerDraft) async -> MCPDiscoveryResult? {
        mcpActionInFlight = true
        defer { mcpActionInFlight = false }
        do {
            let result = try await client.discoverMCPServer(payload: try draft.payload())
            mcpActionFailed = !result.ok
            if result.ok {
                mcpActionResult = Self.localizedText(
                    appLanguage,
                    en: "%@ verified with %d tool(s).",
                    zh: "%@ 已通过测试，发现 %d 个工具。",
                    fr: "%@ vérifié avec %d outil(s).",
                    de: "%@ geprüft mit %d Tool(s).",
                    result.serverID,
                    result.tools.count
                )
            } else {
                mcpActionResult = result.error.isEmpty
                    ? Self.localizedText(appLanguage, en: "MCP discovery failed.", zh: "MCP 测试失败。", fr: "La découverte MCP a échoué.", de: "MCP-Erkennung fehlgeschlagen.")
                    : result.error
            }
            return result
        } catch {
            mcpActionFailed = true
            mcpActionResult = error.localizedDescription
            lastError = error.localizedDescription
            return nil
        }
    }

    func syncMCPServer(
        draft: MCPServerDraft,
        discoveredTools: [MCPDiscoveredTool],
        enabledToolNames: Set<String>
    ) async -> Bool {
        mcpActionInFlight = true
        defer { mcpActionInFlight = false }
        do {
            let status = try await client.syncMCPServer(
                payload: try draft.payload(discoveredTools: discoveredTools, enabledToolNames: enabledToolNames)
            )
            try await refreshDashboard()
            mcpActionFailed = false
            mcpActionResult = status.isEmpty
                ? Self.localizedText(appLanguage, en: "MCP server saved and synced.", zh: "MCP 服务已保存并同步。", fr: "Serveur MCP enregistré et synchronisé.", de: "MCP-Server gespeichert und synchronisiert.")
                : status
            return true
        } catch {
            mcpActionFailed = true
            mcpActionResult = error.localizedDescription
            lastError = error.localizedDescription
            return false
        }
    }

    func deleteMCPServer(_ server: MCPServerItem) async {
        mcpActionInFlight = true
        defer { mcpActionInFlight = false }
        do {
            let status = try await client.deleteMCPServer(serverID: server.serverID)
            try await refreshDashboard()
            mcpActionFailed = false
            mcpActionResult = status.isEmpty
                ? Self.localizedText(appLanguage, en: "MCP server removed.", zh: "MCP 服务已删除。", fr: "Serveur MCP supprimé.", de: "MCP-Server entfernt.")
                : status
        } catch {
            mcpActionFailed = true
            mcpActionResult = error.localizedDescription
            lastError = error.localizedDescription
        }
    }

    func setMCPToolEnabled(_ tool: MCPToolItem, enabled: Bool) async {
        mcpActionInFlight = true
        defer { mcpActionInFlight = false }
        do {
            let status = try await client.setMCPToolEnabled(serverID: tool.serverID, toolName: tool.toolName, enabled: enabled)
            try await refreshDashboard()
            mcpActionFailed = false
            mcpActionResult = status.isEmpty
                ? Self.localizedText(appLanguage, en: "MCP tool updated.", zh: "MCP 工具已更新。", fr: "Outil MCP mis à jour.", de: "MCP-Tool aktualisiert.")
                : status
        } catch {
            mcpActionFailed = true
            mcpActionResult = error.localizedDescription
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
        identityText: String,
        roleTitle: String? = nil,
        rolePrompt: String? = nil,
        enabled: Bool? = nil
    ) async {
        do {
            try await client.updateHerdElephant(
                item,
                name: name,
                identityText: identityText,
                roleTitle: roleTitle,
                rolePrompt: rolePrompt,
                enabled: enabled
            )
            try await refreshDashboard()
        } catch {
            lastError = error.localizedDescription
        }
    }

    @discardableResult
    func scanLocalAgentsForHerd() async -> [LocalAgentRuntimeItem] {
        do {
            onboardingHerdDiscoveryStarted = true
            onboardingHerdDiscoveryStatus = Self.localizedText(appLanguage, en: "Scanning nearby local agents...", zh: "正在扫描本地 agent...", fr: "Analyse des agents locaux...", de: "Lokale Agents werden gesucht...")
            let discovered = try await client.scanLocalAgents()
            try await refreshDashboard()
            let latest = snapshot.localAgentRuntimes.isEmpty ? discovered : snapshot.localAgentRuntimes
            if onboardingSelectedBabyBackend.isEmpty {
                onboardingSelectedBabyBackend = "provider"
                onboardingSelectedBabyRuntimeID = "provider:\(onboardingProviderID)"
            }
            if onboardingBabyProviderModelID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                onboardingBabyProviderModelID = onboardingModelID
            }
            onboardingHerdDiscoveryComplete = true
            onboardingHerdDiscoveryStatus = latest.isEmpty
                ? Self.localizedText(appLanguage, en: "No local agents found yet.", zh: "还没有找到本地 agent。", fr: "Aucun agent local trouvé.", de: "Noch keine lokalen Agents gefunden.")
                : Self.localizedText(appLanguage, en: "Choose which agents should become baby elephants.", zh: "选择哪些 agent 要成为小象。", fr: "Choisissez les agents à adopter.", de: "Wähle Agents als Baby Elephants.")
            return latest
        } catch {
            lastError = error.localizedDescription
            onboardingHerdDiscoveryComplete = true
            onboardingHerdDiscoveryStatus = error.localizedDescription
            return []
        }
    }

    func adoptLocalAgent(
        _ runtime: LocalAgentRuntimeItem,
        displayName: String,
        roleTitle: String,
        rolePrompt: String,
        enabled: Bool
    ) async {
        do {
            _ = try await client.adoptLocalAgent(
                runtime: runtime,
                displayName: displayName,
                roleTitle: roleTitle,
                rolePrompt: rolePrompt,
                enabled: enabled
            )
            try await refreshDashboard()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func adoptSelectedBabyFromOnboarding() async {
        guard !onboardingHerdAdoptionInFlight else { return }
        onboardingHerdAdoptionInFlight = true
        defer { onboardingHerdAdoptionInFlight = false }
        let backend = onboardingSelectedBabyBackend.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !backend.isEmpty else { return }
        do {
            let template = onboardingSelectedBabyTemplate
            if backend == "provider" {
                try await client.adoptProviderAgent(
                    providerID: onboardingProviderID,
                    providerName: onboardingProviderDisplayName,
                    modelID: onboardingBabyProviderModelID.isEmpty ? onboardingModelID : onboardingBabyProviderModelID,
                    displayName: onboardingProviderBabyDisplayName(template: template),
                    roleTitle: template.title,
                    rolePrompt: template.prompt,
                    enabled: true
                )
            } else if let runtime = snapshot.localAgentRuntimes.first(where: { $0.runtimeID == onboardingSelectedBabyRuntimeID && $0.canExecute }) {
                _ = try await client.adoptLocalAgent(
                    runtime: runtime,
                    displayName: onboardingBabyDisplayName(for: runtime, template: template),
                    roleTitle: template.title,
                    rolePrompt: template.prompt,
                    enabled: true
                )
            }
            onboardingSelectedRuntimeIDs.removeAll()
            onboardingSelectedBabyBackend = ""
            onboardingSelectedBabyRuntimeID = ""
            try await refreshDashboard()
        } catch {
            lastError = error.localizedDescription
        }
    }

    private var onboardingProviderDisplayName: String {
        snapshot.providerOptions.first(where: { $0.id == onboardingProviderID })?.displayName
            ?? onboardingProviderID
    }

    private var onboardingSelectedBabyTemplate: OnboardingBabyRoleTemplate {
        let templates = onboardingBabyRoleTemplates(for: onboardingOccupation, language: appLanguage)
        if let selected = templates.first(where: { $0.id == onboardingBabyTemplateID }) {
            return selected
        }
        return templates.first ?? OnboardingBabyRoleTemplate(
            id: "general",
            title: ElephantAppModel.localizedText(appLanguage, en: "focused helper", zh: "专注小象", fr: "assistant ciblé", de: "Fokussierter Helfer"),
            subtitle: ElephantAppModel.localizedText(appLanguage, en: "Handle one bounded task at a time.", zh: "一次处理一个边界清楚的任务。", fr: "Traite une tâche bornée à la fois.", de: "Bearbeitet jeweils eine klar begrenzte Aufgabe."),
            prompt: ElephantAppModel.localizedText(appLanguage, en: "Use this baby elephant for bounded specialist work that benefits from an independent pass.", zh: "把适合专业独立处理的边界清晰任务交给这只小象。", fr: "Confiez-lui le travail spécialisé et borné qui bénéficie d'un passage indépendant.", de: "Nutze es für klar begrenzte Spezialarbeit, die von einem unabhängigen Durchgang profitiert."),
            symbol: "sparkles"
        )
    }

    private func onboardingProviderBabyDisplayName(template: OnboardingBabyRoleTemplate) -> String {
        let provider = onboardingProviderDisplayName.trimmingCharacters(in: .whitespacesAndNewlines)
        let title = template.title.trimmingCharacters(in: .whitespacesAndNewlines)
        if provider.isEmpty { return title }
        return "\(provider) \(title)".trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func onboardingBabyDisplayName(for runtime: LocalAgentRuntimeItem, template: OnboardingBabyRoleTemplate? = nil) -> String {
        let provider = runtime.displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        let role = template?.title ?? onboardingBabyRoleTitle(for: runtime)
        if provider.lowercased().contains(role.lowercased()) {
            return provider
        }
        return "\(provider) \(role)".trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func onboardingBabyRoleTitle(for runtime: LocalAgentRuntimeItem) -> String {
        if appLanguage == .en, !runtime.roleTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return runtime.roleTitle
        }
        let provider = runtime.providerID.lowercased()
        if provider.contains("codex") {
            return Self.localizedText(appLanguage, en: "coding implementer", zh: "编码小象", fr: "implémentation code", de: "Code-Implementierung")
        }
        if provider.contains("gemini") {
            return Self.localizedText(appLanguage, en: "research analyst", zh: "研究小象", fr: "analyse recherche", de: "Recherche")
        }
        if provider.contains("copilot") {
            return Self.localizedText(appLanguage, en: "GitHub assistant", zh: "GitHub 小象", fr: "assistant GitHub", de: "GitHub-Assistent")
        }
        if provider.contains("claude") {
            return Self.localizedText(appLanguage, en: "code reviewer", zh: "审查小象", fr: "revue de code", de: "Code-Review")
        }
        return Self.localizedText(appLanguage, en: "local specialist", zh: "本地专长小象", fr: "spécialiste local", de: "Lokaler Spezialist")
    }

    private func onboardingBabyRolePrompt(for runtime: LocalAgentRuntimeItem) -> String {
        if appLanguage == .en, !runtime.rolePrompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return runtime.rolePrompt
        }
        let provider = runtime.providerID.lowercased()
        if provider.contains("codex") {
            return Self.localizedText(appLanguage, en: "Use this baby elephant for repository changes, code review, terminal-driven investigation, and validation-heavy engineering work.", zh: "把代码修改、代码审查、终端排查和需要严格验证的工程任务交给这只小象。", fr: "Confiez-lui les changements repo, revues de code, investigations terminal et validations exigeantes.", de: "Nutze es für Repository-Änderungen, Code-Review, Terminal-Recherche und validierungsintensive Arbeit.")
        }
        if provider.contains("gemini") {
            return Self.localizedText(appLanguage, en: "Use this baby elephant for research, comparison, synthesis, and broad context gathering.", zh: "把研究、对比、资料综合和大范围上下文收集交给这只小象。", fr: "Confiez-lui la recherche, la comparaison, la synthèse et le contexte large.", de: "Nutze es für Recherche, Vergleich, Synthese und breiten Kontext.")
        }
        if provider.contains("copilot") {
            return Self.localizedText(appLanguage, en: "Use this baby elephant for GitHub-centric code questions and repository workflow assistance.", zh: "把 GitHub 相关代码问题和仓库工作流协助交给这只小象。", fr: "Confiez-lui les questions GitHub et les workflows de dépôt.", de: "Nutze es für GitHub-nahe Codefragen und Repository-Workflows.")
        }
        return Self.localizedText(appLanguage, en: "Use this baby elephant for focused local CLI work that matches its specialist runtime.", zh: "把适合这个本地 CLI 专长的边界清晰任务交给这只小象。", fr: "Confiez-lui le travail CLI local ciblé qui correspond à son runtime spécialisé.", de: "Nutze es für fokussierte lokale CLI-Arbeit, die zu seiner spezialisierten Runtime passt.")
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
        gatewayActionInFlight = true
        gatewayActionFailed = false
        gatewayActionResult = localizedGatewayActionText("\(action)_running")
        defer { gatewayActionInFlight = false }
        do {
            let result = try await client.runGatewayAction(
                service: service.id,
                action: action,
                accountID: service.accountID,
                transport: service.transport,
                force: action == "stop"
            )
            gatewayActionFailed = false
            gatewayActionResult = localizedGatewayActionText("\(action)_success", detail: result)
            try await refreshDashboard()
        } catch {
            gatewayActionFailed = true
            gatewayActionResult = localizedGatewayActionText("\(action)_failed", detail: error.localizedDescription)
            lastError = error.localizedDescription
        }
    }

    func configureGatewayService(_ service: GatewayServiceItem) async {
        gatewayActionInFlight = true
        gatewayActionFailed = false
        gatewayActionResult = localizedGatewayActionText("configure_running")
        defer { gatewayActionInFlight = false }
        do {
            _ = try await client.configureGatewayService(
                service: service.id,
                accountID: service.accountID,
                transport: service.transport,
                secrets: gatewaySecretDrafts[service.id] ?? [:]
            )
            gatewayActionFailed = false
            gatewayActionResult = localizedGatewayActionText("configure_success")
            gatewaySecretDrafts[service.id] = [:]
            try await refreshDashboard()
        } catch {
            gatewayActionFailed = true
            gatewayActionResult = localizedGatewayActionText("configure_failed", detail: error.localizedDescription)
            lastError = error.localizedDescription
        }
    }

    func startWeixinQR() async {
        gatewayActionInFlight = true
        gatewayActionFailed = false
        gatewayActionResult = localizedGatewayActionText("qr_starting")
        stopWeixinQRAutoPoll()
        defer { gatewayActionInFlight = false }
        do {
            gatewayQR = try await client.startWeixinQR()
            gatewayActionFailed = false
            gatewayActionResult = localizedWeixinQRStatusText(gatewayQR.status, fallback: gatewayQR.message)
            startWeixinQRAutoPoll(sessionID: gatewayQR.sessionID)
        } catch {
            gatewayQR = GatewayQRState()
            gatewayActionFailed = true
            gatewayActionResult = localizedGatewayActionText("qr_start_failed", detail: error.localizedDescription)
            lastError = error.localizedDescription
        }
    }

    func pollWeixinQR(auto: Bool = false) async {
        guard !gatewayQR.sessionID.isEmpty else { return }
        guard !gatewayQRPolling else { return }
        gatewayQRPolling = true
        if !auto {
            gatewayActionFailed = false
            gatewayActionResult = localizedGatewayActionText("qr_checking")
        }
        defer { gatewayQRPolling = false }
        do {
            gatewayQR = try await client.pollWeixinQR(sessionID: gatewayQR.sessionID)
            gatewayActionFailed = weixinQRStatusIsFailure(gatewayQR.status)
            gatewayActionResult = localizedWeixinQRStatusText(gatewayQR.status, fallback: gatewayQR.message)
            if gatewayQR.status == "confirmed" {
                stopWeixinQRAutoPoll(cancelTask: !auto)
                gatewayActionFailed = false
                gatewayActionResult = localizedGatewayActionText("qr_confirmed_starting")
                try await refreshDashboard()
                if let weixin = snapshot.gatewayItems.first(where: { $0.id == "weixin" }) {
                    await runGatewayAction(service: weixin, action: "start")
                } else {
                    gatewayActionFailed = true
                    gatewayActionResult = localizedGatewayActionText("qr_confirmed_missing_service")
                }
            } else if weixinQRStatusIsTerminal(gatewayQR.status) {
                stopWeixinQRAutoPoll(cancelTask: !auto)
            }
        } catch {
            if !auto {
                gatewayActionFailed = true
                gatewayActionResult = localizedGatewayActionText("qr_poll_failed", detail: error.localizedDescription)
            }
            lastError = error.localizedDescription
        }
    }

    private func startWeixinQRAutoPoll(sessionID: String) {
        guard !sessionID.isEmpty else { return }
        gatewayQRAutoPolling = true
        weixinQRPollTask?.cancel()
        weixinQRPollTask = Task { [weak self] in
            for _ in 0..<240 {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                if Task.isCancelled { return }
                guard let self else { return }
                let shouldContinue = await MainActor.run {
                    self.gatewayQR.sessionID == sessionID && !self.weixinQRStatusIsTerminal(self.gatewayQR.status)
                }
                if !shouldContinue { break }
                await self.pollWeixinQR(auto: true)
            }
            await MainActor.run {
                guard self?.gatewayQR.sessionID == sessionID else { return }
                self?.gatewayQRAutoPolling = false
            }
        }
    }

    private func stopWeixinQRAutoPoll(cancelTask: Bool = true) {
        if cancelTask {
            weixinQRPollTask?.cancel()
        }
        weixinQRPollTask = nil
        gatewayQRAutoPolling = false
    }

    private func weixinQRStatusIsTerminal(_ status: String) -> Bool {
        let normalized = status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return normalized == "confirmed" || normalized == "expired" || normalized.contains("expire") || normalized.contains("fail") || normalized.contains("error") || normalized.contains("cancel") || normalized.contains("reject")
    }

    private func weixinQRStatusIsFailure(_ status: String) -> Bool {
        let normalized = status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return normalized == "expired" || normalized.contains("expire") || normalized.contains("fail") || normalized.contains("error") || normalized.contains("cancel") || normalized.contains("reject")
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
        await enqueueWakeMessage(inputModality: .text, voiceDuration: nil)
    }

    func sendVoiceWakeMessage(text: String? = nil, duration: TimeInterval?) async {
        await enqueueWakeMessage(inputModality: .voice, voiceDuration: duration, textOverride: text)
    }

    private func enqueueWakeMessage(
        inputModality: ChatMessage.InputModality,
        voiceDuration: TimeInterval?,
        textOverride: String? = nil
    ) async {
        let text = (textOverride ?? wakeDraft).trimmingCharacters(in: .whitespacesAndNewlines)
        let attachments = wakeAttachments
        guard !text.isEmpty || !attachments.isEmpty else { return }
        wakeDraft = ""
        wakeAttachments = []
        wakeQueue.append(WakeQueuedPrompt(text: text, attachments: attachments, inputModality: inputModality, voiceDuration: voiceDuration))
        focusComposer()
        await drainWakeQueueIfNeeded()
    }

    func addWakeImageURLs(_ urls: [URL]) {
        let prepared = urls.compactMap { prepareWakeImageAttachment(from: $0) }
        guard !prepared.isEmpty else { return }
        wakeAttachments.append(contentsOf: prepared)
        focusComposer()
    }

    func importWakeImages(from pasteboard: NSPasteboard) -> Bool {
        let options: [NSPasteboard.ReadingOptionKey: Any] = [.urlReadingFileURLsOnly: true]
        let urlObjects = pasteboard.readObjects(forClasses: [NSURL.self], options: options) as? [NSURL] ?? []
        let urls = urlObjects.map { $0 as URL }.filter(Self.isImageURL)
        if !urls.isEmpty {
            addWakeImageURLs(urls)
            return true
        }

        if let pngData = pasteboard.data(forType: .png),
           let image = NSImage(data: pngData),
           appendWakeImage(image, sourceName: "pasted-image") {
            focusComposer()
            return true
        }
        if let tiffData = pasteboard.data(forType: .tiff),
           let image = NSImage(data: tiffData),
           appendWakeImage(image, sourceName: "pasted-image") {
            focusComposer()
            return true
        }
        if let image = NSImage(pasteboard: pasteboard),
           appendWakeImage(image, sourceName: "pasted-image") {
            focusComposer()
            return true
        }
        return false
    }

    func removeWakeAttachment(_ attachment: WakeAttachment) {
        wakeAttachments.removeAll { $0.id == attachment.id }
    }

    private func prepareWakeImageAttachment(from url: URL) -> WakeAttachment? {
        guard Self.isImageURL(url), let image = NSImage(contentsOf: url) else {
            return nil
        }
        return makeWakeImageAttachment(from: image, sourceName: url.deletingPathExtension().lastPathComponent)
    }

    @discardableResult
    private func appendWakeImage(_ image: NSImage, sourceName: String) -> Bool {
        guard let attachment = makeWakeImageAttachment(from: image, sourceName: sourceName) else {
            return false
        }
        wakeAttachments.append(attachment)
        return true
    }

    private func makeWakeImageAttachment(from image: NSImage, sourceName: String) -> WakeAttachment? {
        guard let data = Self.pngData(from: image) else { return nil }
        do {
            let directory = try Self.wakeAttachmentDirectory()
            let safeName = Self.safeAttachmentStem(sourceName)
            let filename = "\(Int(Date().timeIntervalSince1970))-\(UUID().uuidString)-\(safeName).png"
            let url = directory.appendingPathComponent(filename)
            try data.write(to: url, options: [.atomic])
            return WakeAttachment(url: url, displayName: "\(safeName).png")
        } catch {
            lastError = error.localizedDescription
            return nil
        }
    }

    private static func wakePrompt(text: String, attachments: [WakeAttachment]) -> String {
        let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let fragments = attachments.map(\.promptFragment)
        return ([normalized] + fragments)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n\n")
    }

    private static func isImageURL(_ url: URL) -> Bool {
        guard url.isFileURL else { return false }
        if let type = UTType(filenameExtension: url.pathExtension), type.conforms(to: .image) {
            return true
        }
        return false
    }

    private static func wakeAttachmentDirectory() throws -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")
        let directory = base.appendingPathComponent("Elephant Agent/Chat Attachments", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private static func safeAttachmentStem(_ rawValue: String) -> String {
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        let base = trimmed.isEmpty ? "image" : trimmed
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_"))
        let scalars = base.unicodeScalars.map { scalar in
            allowed.contains(scalar) ? Character(scalar) : "-"
        }
        let collapsed = String(scalars).split(separator: "-").joined(separator: "-")
        return String(collapsed.prefix(48)).trimmingCharacters(in: CharacterSet(charactersIn: "-")).isEmpty
            ? "image"
            : String(collapsed.prefix(48)).trimmingCharacters(in: CharacterSet(charactersIn: "-"))
    }

    private static func pngData(from image: NSImage) -> Data? {
        var proposedRect = NSRect(origin: .zero, size: image.size)
        guard let cgImage = image.cgImage(forProposedRect: &proposedRect, context: nil, hints: nil) else {
            return nil
        }
        let bitmap = NSBitmapImageRep(cgImage: cgImage)
        return bitmap.representation(using: .png, properties: [:])
    }

    func removeQueuedWakeMessage(_ item: WakeQueuedPrompt) {
        wakeQueue.removeAll { $0.id == item.id }
    }

    private func drainWakeQueueIfNeeded() async {
        guard !isWakeRunning else { return }
        isWakeRunning = true
        defer {
            isWakeRunning = false
            focusComposer()
        }
        while !wakeQueue.isEmpty {
            let item = wakeQueue.removeFirst()
            await runWakeMessage(
                item.text,
                attachments: item.attachments,
                inputModality: item.inputModality,
                voiceDuration: item.voiceDuration
            )
        }
    }

    private func runWakeMessage(
        _ text: String,
        attachments: [WakeAttachment],
        inputModality: ChatMessage.InputModality,
        voiceDuration: TimeInterval?
    ) async {
        speechOutput.stop()
        messages.append(ChatMessage(role: .user, text: text, attachments: attachments, inputModality: inputModality, voiceDuration: voiceDuration))
        chatScrollRevision += 1

        let prompt = Self.wakePrompt(text: text, attachments: attachments)
        let shouldPresentVoiceReply = inputModality == .voice && voiceRepliesEnabled
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
        var liveToolCardKeys: [UUID: String] = [:]
        var liveToolGenerations: [String: Int] = [:]
        let minimumTextFlushInterval: TimeInterval = 0.08
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

        func toolCardKey(for event: ToolUseEvent) -> String {
            let baseKey = Self.toolEventKey(event)
            let generation = liveToolGenerations[baseKey] ?? 0
            let currentKey = generation == 0 ? baseKey : "\(baseKey)|\(generation)"
            if let index = liveToolEvents.firstIndex(where: { liveToolCardKeys[$0.id] == currentKey }) {
                let existing = liveToolEvents[index]
                if Self.shouldAppendNewToolCard(existing: existing, incoming: event) {
                    let nextGeneration = generation + 1
                    liveToolGenerations[baseKey] = nextGeneration
                    return "\(baseKey)|\(nextGeneration)"
                }
            }
            return currentKey
        }

        func appendOrUpdateToolActivity(_ event: ToolUseEvent) -> Bool {
            _ = flushAssistantText(force: true)
            let key = toolCardKey(for: event)
            var nextEvent = event
            if let index = liveToolEvents.firstIndex(where: { liveToolCardKeys[$0.id] == key }) {
                nextEvent = Self.mergedToolEvent(existing: liveToolEvents[index], incoming: event)
                liveToolEvents[index] = nextEvent
            } else {
                liveToolEvents.append(nextEvent)
                liveToolEvents = Array(liveToolEvents.suffix(10))
            }
            liveToolCardKeys[nextEvent.id] = key

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
            let key = toolCardKey(for: event)
            guard liveToolMessageIDs[key] == nil else { return }
            currentAssistantTextMessageID = nil
            currentAssistantText = ""
            renderedAssistantText = ""
            liveToolCardKeys[event.id] = key
            _ = appendLiveAssistantMessage(toolEvents: [event])
        }

        func finishedKernelStageEvents(for id: UUID) -> [ToolUseEvent]? {
            guard let index = messages.firstIndex(where: { $0.id == id }) else { return nil }
            let events = messages[index].toolEvents
            guard events.contains(where: { $0.invocationID == "kernel.stage" }) else { return nil }
            return events.map { event in
                guard event.invocationID == "kernel.stage" else { return event }
                var finished = event
                finished.status = "done"
                return finished
            }
        }

        func finishLiveMessages() {
            _ = flushAssistantText(force: true)
            for id in liveMessageIDs {
                updateAssistantMessage(id: id, text: nil, toolEvents: finishedKernelStageEvents(for: id), isStreaming: false)
            }
        }

        func finishVoiceReplyIfNeeded(id: UUID?) {
            guard shouldPresentVoiceReply,
                  let id,
                  let index = messages.firstIndex(where: { $0.id == id }) else {
                return
            }
            let speakableText = Self.speechOutputText(from: messages[index].text)
            guard !speakableText.isEmpty else { return }
            messages[index].outputPresentation = .voice
            chatScrollRevision += 1
            guard voiceRepliesAutoPlay else { return }
            speechOutput.speak(
                messageID: id,
                text: speakableText,
                language: appLanguage,
                engine: voiceReplyEngine,
                systemVoiceIdentifier: voiceReplyVoiceIdentifier,
                edgeVoiceIdentifier: effectiveEdgeVoiceIdentifier
            )
        }

        currentAssistantTextMessageID = appendLiveAssistantMessage()

        do {
            let episodeID = try await client.ensureWakeEpisode(
                personalModelID: snapshot.currentPersonalModelID,
                elephantID: snapshot.currentStateID,
                activeEpisodeID: activeEpisodeID
            )
            activeEpisodeID = episodeID

            streamLoop: for try await event in client.streamWakeLoop(prompt, episodeID: episodeID) {
                if event.type == "stream.heartbeat" {
                    continue
                }
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
                case "kernel.stage":
                    if let toolEvent = event.toolEvent {
                        var stageEvent = toolEvent
                        if stageEvent.invocationID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            stageEvent.invocationID = "kernel.stage"
                        }
                        if appendOrUpdateToolActivity(stageEvent) {
                            await Task.yield()
                        }
                    }
                case "loop.started":
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
                                    currentAssistantTextMessageID = appendLiveAssistantMessage(text: reply.text)
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
                        finishVoiceReplyIfNeeded(id: currentAssistantTextMessageID)
                    }
                    break streamLoop
                case "loop.failed":
                    completed = true
                    finishLiveMessages()
                    messages.append(ChatMessage(role: .assistant, text: chatLoopFailureMessage(detail: event.error)))
                    lastError = chatLoopFailureDetail(event.error)
                    break streamLoop
                default:
                    continue
                }
            }

            if !completed {
                if streamedText.isEmpty, let id = assistantMessageID {
                    updateAssistantMessage(
                        id: id,
                        text: self.text(.liveConnectionEnded),
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
                    finishVoiceReplyIfNeeded(id: assistantMessageID)
                } catch {
                    updateAssistantMessage(
                        id: assistantMessageID,
                        text: chatLoopFailureMessage(error),
                        toolEvents: nil,
                        isStreaming: false
                    )
                    lastError = chatLoopFailureDetail(error.localizedDescription)
                }
            } else if !receivedStreamEvent, !activeEpisodeID.isEmpty {
                let episodeID = activeEpisodeID
                do {
                    let reply = try await client.runWakeLoop(text, episodeID: episodeID)
                    let message = ChatMessage(role: .assistant, text: reply.text, toolEvents: reply.toolEvents)
                    messages.append(message)
                    finishVoiceReplyIfNeeded(id: message.id)
                } catch {
                    messages.append(ChatMessage(role: .assistant, text: chatLoopFailureMessage(error)))
                    lastError = chatLoopFailureDetail(error.localizedDescription)
                }
            } else if let assistantMessageID {
                finishLiveMessages()
                if streamedText.isEmpty {
                    let fallbackText = (!receivedStreamEvent && activeEpisodeID.isEmpty)
                        ? chatLoopFailureMessage(error)
                        : self.text(.liveConnectionStopped)
                    updateAssistantMessage(
                        id: assistantMessageID,
                        text: fallbackText,
                        toolEvents: liveToolEvents,
                        isStreaming: false
                    )
                } else {
                    messages.append(ChatMessage(role: .assistant, text: self.text(.liveConnectionStopped)))
                }
                lastError = chatLoopFailureDetail(error.localizedDescription)
            } else {
                messages.append(ChatMessage(role: .assistant, text: chatLoopFailureMessage(error)))
                lastError = chatLoopFailureDetail(error.localizedDescription)
            }
        }
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

    private static func speechOutputText(from text: String) -> String {
        LocalSpeechOutputController.sanitizedSpeechText(from: text)
    }

    private func chatLoopFailureMessage(detail: String) -> String {
        let trimmed = chatLoopFailureDetail(detail)
        guard !trimmed.isEmpty else {
            return text(.chatLoopFailureGeneric)
        }
        return String(format: text(.chatLoopFailureDetail), trimmed)
    }

    private func chatLoopFailureDetail(_ detail: String) -> String {
        let trimmed = detail.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "" }
        let normalized = trimmed.lowercased()
        let providerIsCopilot = snapshot.providerID.lowercased().contains("copilot")
        let authorizationMissing = normalized.contains("missing required authorization")
            || normalized.contains("authorization header")
            || normalized.contains("missing runtime secret")
        if providerIsCopilot && authorizationMissing {
            return localizedCopilotAuthorizationRecoveryMessage()
        }
        return trimmed
    }

    private func localizedCopilotAuthorizationRecoveryMessage() -> String {
        switch appLanguage {
        case .zh:
            return "GitHub Copilot 已在列表中，但这次对话没有拿到可用授权。重新保存 GitHub Copilot 或重启 Elephant 后再发送，Elephant 会复用本机 GitHub 登录。"
        case .fr:
            return "GitHub Copilot est visible, mais ce chat n'a pas reçu d'autorisation utilisable. Enregistrez à nouveau GitHub Copilot ou redémarrez Elephant, puis renvoyez le message."
        case .de:
            return "GitHub Copilot ist sichtbar, aber dieser Chat hat keine nutzbare Autorisierung erhalten. Speichere GitHub Copilot erneut oder starte Elephant neu und sende dann noch einmal."
        case .en:
            return "GitHub Copilot is visible, but this chat did not receive usable authorization. Save GitHub Copilot again or restart Elephant, then send the message again."
        }
    }

    private static func toolEventSignature(_ events: [ToolUseEvent]) -> String {
        events
            .map {
                [
                    $0.sourceID,
                    $0.invocationID,
                    $0.name,
                    $0.status,
                    $0.arguments,
                    $0.result,
                    $0.phase,
                    $0.backend,
                    $0.babyID,
                    $0.providerID,
                    $0.runtimeID,
                    $0.childEpisodeID
                ].joined(separator: "|")
            }
            .joined(separator: "\n")
    }

    private static func toolEventKey(_ event: ToolUseEvent) -> String {
        let invocationID = event.invocationID.trimmingCharacters(in: .whitespacesAndNewlines)
        if !invocationID.isEmpty {
            return invocationID
        }
        return [event.name, event.arguments].joined(separator: "|")
    }

    private static func shouldAppendNewToolCard(existing: ToolUseEvent, incoming: ToolUseEvent) -> Bool {
        let existingSourceID = existing.sourceID.trimmingCharacters(in: .whitespacesAndNewlines)
        let incomingSourceID = incoming.sourceID.trimmingCharacters(in: .whitespacesAndNewlines)
        if !existingSourceID.isEmpty && existingSourceID == incomingSourceID {
            return false
        }
        return isFinishedToolStatus(existing.status) && isNewToolLifecycleStatus(incoming.status)
    }

    private static func isFinishedToolStatus(_ status: String) -> Bool {
        let value = status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return value.contains("complete")
            || value.contains("success")
            || value.contains("failed")
            || value.contains("error")
            || value.contains("denied")
            || value.contains("deferred")
            || value.contains("blocked")
    }

    private static func isNewToolLifecycleStatus(_ status: String) -> Bool {
        let value = status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return value.isEmpty
            || value.contains("preparing")
            || value.contains("planned")
            || value.contains("requested")
            || value.contains("approved")
            || value.contains("running")
            || value.contains("start")
            || isFinishedToolStatus(value)
    }

    private static func mergedToolEvent(existing: ToolUseEvent, incoming: ToolUseEvent) -> ToolUseEvent {
        ToolUseEvent(
            id: existing.id,
            sourceID: incoming.sourceID.isEmpty ? existing.sourceID : incoming.sourceID,
            invocationID: incoming.invocationID.isEmpty ? existing.invocationID : incoming.invocationID,
            name: incoming.name == "tool" || incoming.name.isEmpty ? existing.name : incoming.name,
            status: incoming.status.isEmpty ? existing.status : incoming.status,
            arguments: incoming.arguments.isEmpty ? existing.arguments : incoming.arguments,
            result: incoming.result.isEmpty ? existing.result : incoming.result,
            phase: incoming.phase.isEmpty ? existing.phase : incoming.phase,
            detail: incoming.detail.isEmpty ? existing.detail : incoming.detail,
            backend: incoming.backend.isEmpty ? existing.backend : incoming.backend,
            babyID: incoming.babyID.isEmpty ? existing.babyID : incoming.babyID,
            babyName: incoming.babyName.isEmpty ? existing.babyName : incoming.babyName,
            babyRole: incoming.babyRole.isEmpty ? existing.babyRole : incoming.babyRole,
            providerID: incoming.providerID.isEmpty ? existing.providerID : incoming.providerID,
            runtimeID: incoming.runtimeID.isEmpty ? existing.runtimeID : incoming.runtimeID,
            runtimeName: incoming.runtimeName.isEmpty ? existing.runtimeName : incoming.runtimeName,
            runtimePath: incoming.runtimePath.isEmpty ? existing.runtimePath : incoming.runtimePath,
            runtimeModel: incoming.runtimeModel.isEmpty ? existing.runtimeModel : incoming.runtimeModel,
            childEpisodeID: incoming.childEpisodeID.isEmpty ? existing.childEpisodeID : incoming.childEpisodeID,
            task: incoming.task.isEmpty ? existing.task : incoming.task
        )
    }

    private func resetOnboardingDrafts() {
        let freshLanguage = AppLanguage.preferred
        onboardingName = "Elephant"
        onboardingPurpose = freshLanguage.defaultElephantVibe
        onboardingPreferredName = ""
        onboardingOccupation = ""
        onboardingSchool = ""
        onboardingCity = ""
        onboardingCurrentFocus = ""
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
        setAppLanguage(freshLanguage, updateDefaultVibe: false)
        onboardingBlogURL = ""
        onboardingLinkedInURL = ""
        onboardingTwitterURL = ""
        onboardingGroundingDepth = OnboardingGroundingDepth.standard.rawValue
        onboardingGroundingAnswers = [:]
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
        onboardingLockPassword = ""
        onboardingLockPasswordConfirmation = ""
        onboardingStep = 0
        onboardingHerdDiscoveryStarted = false
        onboardingHerdDiscoveryComplete = false
        onboardingHerdDiscoveryStatus = ""
        onboardingSelectedRuntimeIDs = []
        onboardingSelectedBabyBackend = ""
        onboardingSelectedBabyRuntimeID = ""
        onboardingBabyProviderModelID = ""
        onboardingBabyTemplateID = ""
        onboardingHerdAdoptionInFlight = false
        onboardingFinalizationStarted = false
        onboardingFinalizationComplete = false
        onboardingFinalizationFailed = false
        onboardingFinalizationStatus = ""
        onboardingInitReflectJobID = ""
        onboardingLetterJobID = ""
        onboardingLetterEntry = nil
        showingOnboardingLetterPrompt = false
        showingOnboardingLetterEnvelope = false
        onboardingLetterPollTask?.cancel()
        onboardingLetterPollTask = nil
        onboardingCreatedStateID = ""
    }

    private func resetLocalMacStateForFreshInstall() throws {
        let avatarPaths = [userAvatarPath] + herdAvatarPaths.values.map { $0 }
        try removeLocalAvatarFilesForReset(paths: avatarPaths)

        wakeDraft = ""
        providerTestResult = ""
        providerActionFailed = false
        providerActionInFlight = false
        embeddingActionResult = ""
        gatewayActionResult = ""
        gatewayActionFailed = false
        gatewayActionInFlight = false
        gatewayQRPolling = false
        gatewayQRAutoPolling = false
        gatewaySecretDrafts.removeAll()
        stopWeixinQRAutoPoll()
        gatewayQR = GatewayQRState()
        cronActionResult = ""
        diaryActionResult = ""
        factActionResult = ""
        configActionResult = ""
        isReflecting = false
        isWakeRunning = false
        isSleepDisplayPresented = false
        sleepDisplayReason = "manual"
        sleepUnlockPassword = ""
        sleepUnlockError = ""
        sleepIdleMinutes = Self.defaultSleepIdleMinutes
        voiceRepliesEnabled = true
        voiceRepliesAutoPlay = true
        voiceReplyEngineRaw = SpeechOutputEngine.edgeOnline.rawValue
        voiceReplyVoiceIdentifier = ""
        voiceReplyEdgeVoiceIdentifier = ""
        voiceInputEngineRaw = SpeechRecognitionEngine.automatic.rawValue
        voiceRuntimeActionResult = ""
        voiceRuntimeActionInFlight = false
        speechOutput.stop()
        hiddenEpisodeIDs.removeAll()
        userAvatarPath = ""
        herdAvatarPaths.removeAll()

        let defaults = UserDefaults.standard
        [
            Self.onboardingCompleteKey,
            Self.onboardingLetterSeenEntryIDKey,
            Self.onboardingLetterPendingKey,
            Self.userAvatarPathKey,
            Self.herdAvatarPathsKey,
            Self.hiddenEpisodeIDsKey,
            Self.appLanguageKey,
            Self.voiceRepliesEnabledKey,
            Self.voiceRepliesAutoPlayKey,
            Self.voiceReplyEngineKey,
            Self.voiceReplyVoiceIdentifierKey,
            Self.voiceReplyEdgeVoiceIdentifierKey,
            Self.voiceInputEngineKey,
            Self.sleepIdleMinutesKey,
            Self.appLockPasswordRecordKey
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

    private static func storedAppLockPasswordRecord() -> String? {
        let value = UserDefaults.standard.string(forKey: appLockPasswordRecordKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return value?.isEmpty == false ? value : nil
    }

    private static func makeAppLockPasswordRecord(for password: String) -> String {
        let salt = UUID().uuidString.replacingOccurrences(of: "-", with: "")
        return "\(salt):\(passwordDigest(salt: salt, password: password))"
    }

    private static func password(_ password: String, matches record: String?) -> Bool {
        guard let record else { return false }
        let pieces = record.split(separator: ":", maxSplits: 1).map(String.init)
        guard pieces.count == 2 else { return false }
        return passwordDigest(salt: pieces[0], password: password) == pieces[1]
    }

    private static func passwordDigest(salt: String, password: String) -> String {
        let data = Data("\(salt):\(password)".utf8)
        let digest = SHA256.hash(data: data)
        return digest.map { String(format: "%02x", $0) }.joined()
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
