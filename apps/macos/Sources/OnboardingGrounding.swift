import Foundation

struct OnboardingLocalizedCopy: Equatable {
    var en: String
    var zh: String

    func text(_ language: AppLanguage) -> String {
        language == .zh ? zh : en
    }
}

enum OnboardingGroundingDepth: String, CaseIterable, Identifiable {
    case quick
    case standard
    case deep

    var id: String { rawValue }

    var questionCount: Int {
        switch self {
        case .quick: return 4
        case .standard: return 10
        case .deep: return 18
        }
    }

    func minutesText(_ language: AppLanguage) -> String {
        switch self {
        case .quick:
            return language == .zh ? "约 1-3 分钟" : "About 1-3 min"
        case .standard:
            return language == .zh ? "约 5-10 分钟" : "About 5-10 min"
        case .deep:
            return language == .zh ? "约 10-15 分钟" : "About 10-15 min"
        }
    }

    func title(_ language: AppLanguage) -> String {
        switch self {
        case .quick:
            return language == .zh ? "轻量了解" : "Light understanding"
        case .standard:
            return language == .zh ? "标准了解" : "Standard understanding"
        case .deep:
            return language == .zh ? "深入了解" : "Deeper understanding"
        }
    }

    func subtitle(_ language: AppLanguage) -> String {
        switch self {
        case .quick:
            return language == .zh ? "先让 Elephant 避免明显误解你，之后再慢慢补全。" : "Help Elephant avoid obvious mismatches first; fill in more later."
        case .standard:
            return language == .zh ? "推荐。覆盖当前重点、支持方式、关系处境和边界。" : "Recommended. Covers focus, support style, relationships, context, and boundaries."
        case .deep:
            return language == .zh ? "加入价值取舍、长期模式、信任条件和更细的压力恢复线索。" : "Adds values, recurring patterns, trust conditions, and finer pressure-recovery cues."
        }
    }

    func buildsText(_ language: AppLanguage) -> String {
        switch self {
        case .quick:
            return language == .zh ? "当前重点、支持方式、恢复路径、边界信号" : "Current focus, support style, recovery path, boundary signal"
        case .standard:
            return language == .zh ? "一版可用的身份、处境、状态、路径理解" : "A usable first understanding across identity, context, state, and path"
        case .deep:
            return language == .zh ? "价值判断、社会处境、压力恢复、长期轨迹" : "Values, social context, pressure recovery, long-term trajectory"
        }
    }

    var questionIDs: [String] {
        switch self {
        case .quick:
            return ["current_focus", "support_tone", "recovery_path", "boundary_signal"]
        case .standard:
            return [
                "current_focus", "support_tone", "recovery_path", "boundary_signal",
                "decision_style", "role_load", "important_relationship", "pressure_first",
                "growth_direction", "trust_condition"
            ]
        case .deep:
            return [
                "current_focus", "support_tone", "recovery_path", "boundary_signal",
                "decision_style", "role_load", "important_relationship", "pressure_first",
                "growth_direction", "trust_condition", "value_guardrail", "recurring_pattern",
                "formative_lesson", "environment_shape", "change_underway", "relationship_tension",
                "attention_protection", "vulnerability_boundary"
            ]
        }
    }
}

enum OnboardingGroundingLens: String, Equatable {
    case identity
    case world
    case pulse
    case journey

    func title(_ language: AppLanguage) -> String {
        switch self {
        case .identity:
            return language == .zh ? "价值与判断" : "Values and judgment"
        case .world:
            return language == .zh ? "关系与处境" : "Relationships and context"
        case .pulse:
            return language == .zh ? "节奏与压力" : "Rhythm and pressure"
        case .journey:
            return language == .zh ? "经历与方向" : "Experience and direction"
        }
    }

    var symbol: String {
        switch self {
        case .identity: return "person.text.rectangle"
        case .world: return "person.2.wave.2"
        case .pulse: return "waveform.path.ecg"
        case .journey: return "point.topleft.down.curvedto.point.bottomright.up"
        }
    }
}

struct OnboardingGroundingOption: Identifiable, Equatable {
    var id: String
    var label: OnboardingLocalizedCopy
    var detail: OnboardingLocalizedCopy
    var fact: OnboardingLocalizedCopy
}

struct OnboardingGroundingQuestion: Identifiable, Equatable {
    var id: String
    var lens: OnboardingGroundingLens
    var title: OnboardingLocalizedCopy
    var prompt: OnboardingLocalizedCopy
    var reason: OnboardingLocalizedCopy
    var topic: String
    var sensitivity: String
    var options: [OnboardingGroundingOption]
}

struct OnboardingGroundingAnswerDraft: Equatable {
    var questionID: String
    var optionID: String
    var note: String
    var skipped: Bool

    static func empty(questionID: String) -> OnboardingGroundingAnswerDraft {
        OnboardingGroundingAnswerDraft(questionID: questionID, optionID: "", note: "", skipped: false)
    }
}

struct OnboardingGroundingAnswerRecord: Equatable {
    var questionID: String
    var optionID: String
    var questionTitle: String
    var questionPrompt: String
    var optionLabel: String
    var optionDetail: String
    var note: String
    var factText: String
    var lens: String
    var topic: String
    var sensitivity: String

    var payload: [String: Any] {
        [
            "question_id": questionID,
            "option_id": optionID,
            "question_title": questionTitle,
            "question_prompt": questionPrompt,
            "option_label": optionLabel,
            "option_detail": optionDetail,
            "note": note,
            "fact_text": factText,
            "lens": lens,
            "topic": topic,
            "sensitivity": sensitivity
        ]
    }
}

enum OnboardingGroundingCatalog {
    static func questions(for language: AppLanguage, depth: OnboardingGroundingDepth) -> [OnboardingGroundingQuestion] {
        let lookup = Dictionary(uniqueKeysWithValues: allQuestions.map { ($0.id, $0) })
        return depth.questionIDs.compactMap { lookup[$0] }
    }

    static var allQuestions: [OnboardingGroundingQuestion] {
        standardQuestions + deepQuestions + extendedQuestions
    }

    private static let standardQuestions: [OnboardingGroundingQuestion] = [
        q(
            "value_guardrail",
            .identity,
            "What should not be lost when you make a hard trade-off?",
            "做艰难取舍时，你最不希望自己弄丢什么？",
            "This helps Elephant weigh advice by your durable values, not only by efficiency.",
            "这会帮助 Elephant 以后判断事情时，不只看效率，也看你真正想守住的东西。",
            "identity.values.guardrail",
            "medium",
            [
                o("authorship", "My sense of authorship", "I need the choice to still feel like mine.", "我想保住选择权", "我不一定要最快，但希望最后的方向仍然像是自己选出来的。", "The user protects authorship and agency when making hard trade-offs.", "用户在艰难取舍中很重视自主感和作者性，希望保住自己的选择权。"),
                o("stability", "Stable ground", "I need to reduce collapse risk before optimizing.", "我想先踩稳地面", "先确认现实不会塌，再谈优化、冒险或更大的投入。", "The user prioritizes stable ground and reduced collapse risk before optimization.", "用户在取舍中会先确认安全感和现实稳定，再考虑优化或冒险。"),
                o("truth", "Inner honesty", "I would rather move slowly than betray what feels true.", "我不想背离真心", "有些决定不只是对错，也关乎是否还像自己。", "The user values inner honesty and consistency, even when it slows decisions.", "用户很重视真实感和内在一致性，宁可慢一点也不想背离真心。"),
                o("people", "People who matter", "Important relationships and promises need a seat at the table.", "我想顾住重要的人", "这件事不只属于我一个人，关系、承诺和照顾也要被算进去。", "The user includes important relationships and commitments in trade-offs.", "用户做取舍时会把重要关系、承诺和照顾责任一起纳入判断。")
            ]
        ),
        q(
            "decision_style",
            .identity,
            "When a decision is complex, what helps you trust your judgment?",
            "面对复杂决定时，什么最能让你相信自己的判断？",
            "This shapes whether Elephant should reason, simulate, simplify, or slow down with you.",
            "这会影响 Elephant 以后是帮你推演、拆解、简化，还是陪你慢一点确认。",
            "identity.decision.style",
            "medium",
            [
                o("principle", "A clear principle", "I trust the decision when the principle underneath is clear.", "先看底层原则", "只要底层原则清楚，具体选项就比较容易排出轻重。", "The user trusts decisions more when the underlying principle is explicit.", "用户在复杂决定里需要先看清底层原则，再判断具体选项。"),
                o("simulation", "A concrete simulation", "I need to see what each path would feel like in real life.", "把未来具体推演出来", "抽象比较不够，我需要看到每条路进入生活后会变成什么样。", "The user trusts decisions through concrete future simulation.", "用户更容易通过具体推演未来情境来相信自己的判断。"),
                o("body", "A body-level signal", "My body often knows before my explanation catches up.", "听身体的信号", "有时候身体先知道答案，只是语言还没有跟上。", "The user uses body-level signals as part of decision confidence.", "用户会把身体感受当作复杂决定中的重要判断信号。"),
                o("conversation", "Thinking with someone", "I find my judgment by hearing it in conversation.", "和信任的人说一遍", "把话说出来、被认真接住之后，判断会变得清楚。", "The user often clarifies judgment through trusted conversation.", "用户常通过和信任的人对话来澄清自己的判断。")
            ]
        ),
        q(
            "self_standard",
            .identity,
            "What kind of self-demand tends to run in the background?",
            "你心里常年运行着哪一种自我要求？",
            "This helps Elephant distinguish helpful standards from pressure that needs softening.",
            "这会帮助 Elephant 区分哪些标准能支持你，哪些压力需要被放轻一点。",
            "identity.self_standard.background",
            "medium",
            [
                o("competent", "Be genuinely competent", "I need to know the thing is solid, not only presentable.", "真的要做扎实", "不是看起来完成就好，我会在意它到底稳不稳、准不准。", "The user has a durable self-demand for real competence and solidity.", "用户有长期的扎实感要求，会在意事情是否真的稳、准、可靠。"),
                o("kind", "Do not become careless with people", "I care about not hurting or neglecting people in the process.", "不要亏待人", "事情可以推进，但我不希望自己在过程中变得粗糙、冷漠或亏待别人。", "The user carries a self-demand to remain careful and humane with people.", "用户有不亏待人的自我要求，会在推进事情时顾及他人的感受和位置。"),
                o("free", "Do not get trapped", "I notice when a path starts taking away too much freedom.", "不要把自己困住", "我会警惕一种路越走越窄、越来越不像自己的感觉。", "The user watches for paths that reduce freedom or trap their future self.", "用户会警惕让自己被困住、未来选择变窄的路径。"),
                o("honest", "Stay honest about reality", "I need to name what is true, even when it is inconvenient.", "要诚实面对现实", "即使不舒服，我也希望先把真实情况说清楚。", "The user values honest contact with reality, even when inconvenient.", "用户重视诚实面对现实，即使真相不舒服也希望先说清楚。")
            ]
        ),
        q(
            "support_tone",
            .identity,
            "When you are stuck, what kind of support is most useful first?",
            "卡住的时候，哪种支持最先对你有用？",
            "This calibrates Elephant's first move before it gives advice.",
            "这会校准 Elephant 以后在你卡住时，第一步应该怎么靠近你。",
            "identity.support.first_move",
            "medium",
            [
                o("direct", "Be direct and practical", "Help me name the issue and choose the next move.", "直接一点，先帮我动起来", "先把问题说清楚，再给我一个能做的小步。", "The user often wants direct, practical support when stuck.", "用户卡住时通常希望先得到直接、可执行的支持。"),
                o("gentle", "Be gentle before solving", "Help me land before pushing toward action.", "先温和一点", "我可能需要先落地、被接住，再进入解决问题。", "The user benefits from gentle grounding before problem-solving.", "用户卡住时通常需要先被温和接住，再进入解决问题。"),
                o("reflective", "Ask one precise question", "A good question helps me find the real knot.", "问一个准的问题", "不要问太多，一个问到点上的问题就能让我看见结在哪里。", "The user benefits from one precise question before advice.", "用户卡住时常被一个精准问题帮助，而不是一串追问。"),
                o("structured", "Give me structure", "Turn the mess into parts, order, and a first step.", "帮我把混乱分层", "我需要有人把一团东西拆成层次、顺序和第一步。", "The user benefits from structure and decomposition when stuck.", "用户卡住时通常需要结构化拆解，把混乱分成层次和步骤。")
            ]
        ),
        q(
            "boundary_signal",
            .identity,
            "What is an early sign that help is becoming too much?",
            "什么迹象说明，别人的帮助开始让你不舒服了？",
            "This keeps Elephant useful without becoming intrusive.",
            "这会让 Elephant 以后知道什么时候该退后一点，避免好心变成打扰。",
            "identity.boundary.help_signal",
            "high",
            [
                o("over_explained", "Too much explanation", "I feel crowded when every step is over-explained.", "解释太多", "每一步都被解释、补充、提醒时，我会觉得空间被占满。", "The user can feel crowded when help over-explains every step.", "当帮助包含过多解释和提醒时，用户容易感到空间被占满。"),
                o("too_fast", "Too much momentum", "I need room to choose pace, not only be moved forward.", "推进太快", "一直被往前推时，我会需要重新拿回节奏。", "The user needs control over pace and can resist overly fast momentum.", "用户需要保有自己的节奏，过快推进会让其不舒服。"),
                o("too_intimate", "Too intimate too soon", "Depth is fine, but it needs permission and timing.", "太快进入私密处", "我可以谈深的东西，但需要合适的时机和许可感。", "The user can engage deeply but needs permission and timing around intimacy.", "用户可以进入深度话题，但需要合适时机和清晰许可感。"),
                o("premature_answer", "Answers before understanding", "I notice when someone solves before they understand.", "还没理解就给答案", "我会在意对方是不是真的听懂了，而不是急着表现有办法。", "The user dislikes premature answers before adequate understanding.", "用户不喜欢还没理解就给答案，更看重先被准确理解。")
            ]
        ),
        q(
            "role_load",
            .world,
            "Which role takes the most from you right now?",
            "现在最占用你心力的是哪一种角色？",
            "This grounds Elephant in your social and practical load.",
            "这会让 Elephant 理解你现在不是抽象地活着，而是带着具体角色和责任在生活。",
            "world.roles.current_load",
            "medium",
            [
                o("builder", "Builder or owner", "I am carrying something that needs to be made real.", "建设者或负责人", "我在把一个东西做出来，也要承担它能不能成立。", "The user's current load is strongly shaped by building or owning something.", "用户当前心力主要被建设者或负责人角色占用。"),
                o("caretaker", "Caretaker", "Someone or something depends on my steadiness.", "照顾者", "有人或某件事需要我稳住、照看、不要掉链子。", "The user's current load includes caretaking responsibility.", "用户当前心力包含明显的照顾责任，需要长期保持稳定。"),
                o("learner", "Learner in transition", "I am trying to grow into a new level or field.", "转变中的学习者", "我正在进入新的层级或领域，还在建立手感。", "The user is carrying the load of learning or transition into a new level.", "用户当前处在学习或转型中，需要建立新领域或新层级的手感。"),
                o("integrator", "Person holding many threads", "My load is keeping many parts from drifting apart.", "把很多线拢住的人", "我像是在同时照看很多线，不能让它们散掉。", "The user's current load involves holding many threads together.", "用户当前心力主要花在同时拢住多条线索和责任上。")
            ]
        ),
        q(
            "important_relationship",
            .world,
            "Which kind of relationship most changes how decisions feel?",
            "哪类关系最会影响你做决定时的感受？",
            "This helps Elephant include the right social context instead of treating choices as isolated.",
            "这会帮助 Elephant 不把你的选择当成孤立计算，而是把真正相关的人放进来。",
            "world.relationships.decision_weight",
            "medium",
            [
                o("family", "Family or long obligations", "History and responsibility make these choices heavier.", "家人或长期责任", "这里面有历史、责任和很多说不清的重量。", "Family or long obligations strongly affect how decisions feel for the user.", "家人或长期责任会显著影响用户做决定时的感受。"),
                o("partner", "A close partner", "One person's response can change the emotional shape of a path.", "亲密伴侣", "有些决定不是我一个人的，它会改变两个人的生活形状。", "A close partner's needs and response strongly shape the user's choices.", "亲密伴侣的需要和反应会显著塑造用户的选择感受。"),
                o("team", "Team or collaborators", "Coordination, trust, and fairness matter.", "团队或合作者", "协作、信任和公平感会影响我能不能安心往前。", "Team trust, coordination, and fairness matter in the user's decisions.", "团队信任、协作和公平感会影响用户是否能安心推进决定。"),
                o("future_self", "My future self", "I often decide by imagining who has to live with the result.", "未来的自己", "我会想到以后那个要承受结果的自己。", "The user often includes their future self as a meaningful stakeholder.", "用户常把未来的自己当作重要关系对象来考虑。")
            ]
        ),
        q(
            "current_focus",
            .pulse,
            "What deserves the most protection in this season of life?",
            "在这个阶段，什么最值得被保护？",
            "This gives Elephant a Pulse anchor for current priorities.",
            "这会给 Elephant 一个当前阶段的锚点，知道什么不能随便被牺牲。",
            "pulse.chapter.protected_priority",
            "medium",
            [
                o("deep_work", "Deep work", "I need protected attention to make something real.", "深度工作", "我需要守住注意力，才能把真正重要的东西做出来。", "The user's current season needs protection for deep work and attention.", "用户当前阶段最需要保护深度工作和注意力。"),
                o("health", "Health and energy", "Without the body, the plan does not matter.", "健康和精力", "身体和精力如果先崩掉，再好的计划也没有意义。", "The user's current season needs protection for health and energy.", "用户当前阶段最需要保护健康、身体和精力。"),
                o("relationship", "A key relationship", "A person or relationship needs care, repair, or presence.", "一段重要关系", "有一段关系需要被照看、修复，或认真在场。", "The user's current season needs protection for a key relationship.", "用户当前阶段最需要保护一段重要关系。"),
                o("transition", "A transition", "I need space to cross from one shape of life into another.", "一次转变", "我正在从一种生活形状走向另一种，需要空间完成过渡。", "The user's current season needs protection for a life or work transition.", "用户当前阶段最需要保护一次生活或工作的转变。")
            ]
        ),
        q(
            "pressure_first",
            .pulse,
            "When pressure rises, what usually appears first?",
            "压力升起来时，你通常最先出现什么反应？",
            "This helps Elephant notice pressure earlier and choose the right support mode.",
            "这会帮助 Elephant 更早识别你的压力，并选择合适的支持方式。",
            "pulse.pattern.pressure.first_signal",
            "medium",
            [
                o("quiet", "I pull inward", "I need low input before I can explain.", "先缩回安静里", "不是逃开，而是需要一点低输入的空间，才听得见自己。", "When pressure rises, the user tends to pull inward and need low-input space.", "压力升起时，用户倾向先缩回安静里，需要低输入空间。"),
                o("structure", "I start organizing", "Lists, order, and decomposition make things less threatening.", "先把乱麻理成线", "把混乱拆成线、列成项、排出顺序，会让我稳一点。", "When pressure rises, the user regains stability through structure and decomposition.", "压力升起时，用户通常通过结构、清单和拆解恢复稳定。"),
                o("motion", "I move into action", "A small action helps me recover feel.", "先动手让车跑起来", "我常常不是想明白才动，而是动起来以后找回手感。", "When pressure rises, the user often uses action to regain feel and stability.", "压力升起时，用户常通过先行动来找回手感和稳定。"),
                o("co_think", "I look for another mind", "Thinking with someone helps me metabolize the pressure.", "先找个人一起想", "一个人扛着会太满，需要另一个脑子和一个能接住话的人。", "When pressure rises, the user benefits from co-thinking and being accompanied.", "压力升起时，用户常需要共思和被接住，而不是独自消化。")
            ]
        ),
        q(
            "recovery_path",
            .pulse,
            "When your energy is low, what usually helps you return to yourself?",
            "当你需要恢复精力、让自己舒服一点时，通常会怎么做？",
            "This prevents Elephant from recommending the wrong kind of recovery.",
            "这会避免 Elephant 在你低能量时推荐不适合你的恢复方式。",
            "pulse.pattern.recovery.path",
            "medium",
            [
                o("quiet_corner", "Less input and quiet", "I need fewer demands before anything else.", "少一点输入，安静下来", "恢复有时不是被鼓励，而是先少一点声音、少一点催促。", "The user's recovery often starts with quiet, less input, and fewer demands.", "用户恢复时通常先需要安静、减少输入和降低外界要求。"),
                o("soft_talk", "A calm conversation", "A low-pressure conversation helps my mind land.", "轻轻说一会儿", "有时不是立刻解决什么，而是有人在旁边说话，心慢慢落回身体里。", "The user's recovery is supported by calm, low-pressure conversation.", "用户恢复时常受益于温和、低压的对话陪伴。"),
                o("body_rhythm", "A body rhythm reset", "Walking, sleep, food, music, or movement can lead the mind back.", "让身体换个节奏", "走路、睡觉、音乐、吃点东西，都可能是一条回来的路。", "The user's recovery is helped by resetting body rhythm through rest, movement, food, or music.", "用户恢复时常通过睡眠、走路、饮食、音乐或身体节奏重置来回到自己。"),
                o("small_completion", "One tiny completion", "Finishing a small action restores agency.", "完成一个很小动作", "把一件很小的事做完，会让我重新有一点掌控感。", "The user's recovery is helped by one tiny completed action that restores agency.", "用户恢复时常通过完成一个很小的动作重新获得掌控感。")
            ]
        ),
        q(
            "energy_rhythm",
            .pulse,
            "Which rhythm should Elephant respect most?",
            "哪种节奏最需要 Elephant 尊重？",
            "This helps Elephant time suggestions instead of interrupting useful cycles.",
            "这会帮助 Elephant 以后把建议放在合适时机，而不是打断你的节奏。",
            "pulse.rhythm.respect",
            "low",
            [
                o("slow_start", "Slow starts", "I may need time before momentum appears.", "启动慢一点", "我可能不是不想做，只是需要一点进入状态的时间。", "The user may need slow starts before momentum appears.", "用户可能需要较慢启动，进入状态后动能才会出现。"),
                o("deep_blocks", "Long focus blocks", "Interruptions cost more than they look.", "长块专注", "打断的成本比看起来更高，我需要完整的注意力块。", "The user needs long focus blocks and interruptions are costly.", "用户需要长块专注时间，打断成本较高。"),
                o("bursts", "Short bursts", "I work best with small intense pushes and recovery between them.", "短促冲刺", "我适合一小段一小段推进，中间要留恢复空间。", "The user works well in short bursts with recovery space between them.", "用户适合短促冲刺式推进，并需要在中间留恢复空间。"),
                o("night", "Late clarity", "Some important clarity comes later in the day.", "晚些时候更清楚", "有些重要判断和表达，会在一天后半段才慢慢浮出来。", "The user may find important clarity later in the day.", "用户的重要清晰感可能在一天后半段更容易出现。")
            ]
        ),
        q(
            "trust_condition",
            .world,
            "What makes you trust a person or system with important context?",
            "什么会让你愿意把重要背景交给一个人或系统？",
            "This informs how Elephant should earn trust rather than assume it.",
            "这会让 Elephant 知道信任不是默认拥有的，而是要用正确方式慢慢赢得。",
            "world.trust.condition",
            "high",
            [
                o("accuracy", "It remembers accurately", "Small distortions make trust weaker.", "它记得准确", "哪怕是小的误读或张冠李戴，也会削弱信任。", "The user trusts more when important context is remembered accurately.", "当重要背景被准确记住时，用户更容易信任。"),
                o("correctable", "It is easy to correct", "I need mistakes to be repairable without drama.", "它容易被修正", "出错没关系，但必须能轻松改，不要让我费力解释。", "The user trusts more when mistakes are easy to correct and repair.", "当错误能轻松修正且不需要费力解释时，用户更容易信任。"),
                o("discretion", "It is discreet", "Not everything I say should be repeated or overused.", "它知道分寸", "不是我说过的每句话，都应该被到处引用或过度使用。", "The user trusts more when discretion is shown around sensitive context.", "当系统能对敏感背景保持分寸，不过度引用或使用时，用户更容易信任。"),
                o("usefulness", "It proves usefulness", "Trust grows when the memory makes help better.", "它真的变得更有用", "如果理解能让帮助变准，信任就会慢慢长出来。", "The user trusts more when remembered context visibly improves help.", "当被记住的背景让帮助明显更准确时，用户更容易信任。")
            ]
        ),
        q(
            "environment_shape",
            .world,
            "Which environment helps you become more like yourself?",
            "什么样的环境会让你更像自己？",
            "This grounds recommendations in the conditions where you function well.",
            "这会帮助 Elephant 以后推荐更适合你的环境和节奏，而不是只看任务本身。",
            "world.environment.self_fit",
            "medium",
            [
                o("quiet_depth", "Quiet with depth", "I need fewer signals and more room to think.", "安静、有深度", "信号少一点，思考深一点，我会更像自己。", "The user becomes more like themselves in quiet, deep environments.", "用户在安静、有深度、少噪音的环境中更容易像自己。"),
                o("warm_people", "Warm, serious people", "I thrive around people who are kind and not careless.", "温暖但认真", "我需要温度，也需要认真，不适合太随便或太冷。", "The user thrives around people who are warm and serious.", "用户在温暖但认真的人群和环境里更容易舒展。"),
                o("high_agency", "High agency", "I do better when I can shape the work, not only receive it.", "有主动权", "能参与塑造事情，而不只是接收任务时，我会更有生命力。", "The user does better in environments with meaningful agency.", "用户在有主动权、能塑造工作的环境中更容易发挥。"),
                o("beautiful_order", "Beautiful order", "Order, taste, and care in the surroundings affect me.", "有秩序和美感", "空间、秩序、审美和照料感，会影响我能不能稳定下来。", "The user is affected by order, taste, and care in their environment.", "用户会被环境中的秩序、审美和照料感影响。")
            ]
        ),
        q(
            "change_underway",
            .pulse,
            "What kind of change are you carrying right now?",
            "你现在正在承受哪一种变化？",
            "This keeps Elephant from treating an active transition as a stable preference.",
            "这会避免 Elephant 把过渡期的状态误认为长期不变的偏好。",
            "pulse.transition.current",
            "medium",
            [
                o("work_shift", "Work or ambition is changing", "My standards, role, or direction are moving.", "工作或野心在变", "我的标准、角色或方向正在移动，还没有完全定型。", "The user is currently carrying a work, ambition, role, or direction shift.", "用户当前正在经历工作、野心、角色或方向上的变化。"),
                o("relationship_shift", "A relationship is changing", "The emotional map around someone is different now.", "关系在变", "某段关系的位置、温度或边界，已经和以前不一样了。", "The user is currently carrying a relationship change.", "用户当前正在承受一段关系的变化。"),
                o("self_shift", "My self-image is changing", "I am not understanding myself in the old way anymore.", "对自己的理解在变", "我不再完全用以前那套方式理解自己。", "The user's self-image or self-understanding is currently changing.", "用户当前对自己的理解或自我形象正在变化。"),
                o("capacity_shift", "My capacity is changing", "Energy, health, or available attention is not what it used to be.", "能力和精力边界在变", "我的精力、身体或注意力容量，和以前不太一样了。", "The user's capacity, energy, health, or available attention is currently changing.", "用户当前的精力、身体或可用注意力边界正在变化。")
            ]
        ),
        q(
            "recurring_pattern",
            .journey,
            "Which pattern tends to return in different forms?",
            "哪种模式会反复以不同形式回到你的生活里？",
            "This gives Elephant a Journey clue without turning one episode into a personality label.",
            "这会给 Elephant 一个长期轨迹线索，而不是把单次经历误读成人格标签。",
            "journey.pattern.recurring",
            "medium",
            [
                o("overcarry", "I carry too much alone", "I realize late that I have been holding too many parts by myself.", "自己扛太多", "常常到很后面才发现，我已经一个人扛了太多部分。", "A recurring pattern is that the user carries too much alone.", "用户的一个反复模式是容易自己扛太多，到后面才意识到负荷过重。"),
                o("late_boundary", "I set boundaries late", "I notice the boundary after I am already depleted.", "边界设得太晚", "我常常是已经累了、烦了，才发现边界早该出现。", "A recurring pattern is that the user sets boundaries late after depletion.", "用户的一个反复模式是边界常设得偏晚，耗竭后才意识到。"),
                o("restart", "I rebuild after disruption", "My life has a pattern of rebuilding after things break or shift.", "中断后重建", "有些阶段像是被打断，然后我又一点点重新搭起来。", "A recurring pattern is rebuilding after disruption or major shifts.", "用户的一个反复模式是在中断或变化后重新搭建生活。"),
                o("seek_depth", "I keep seeking deeper meaning", "Surface answers rarely feel like enough.", "一直想追深一点", "表面的答案常常不够，我会想知道更深的原因和意义。", "A recurring pattern is seeking deeper meaning beyond surface answers.", "用户的一个反复模式是不断追问更深层的原因和意义。")
            ]
        ),
        q(
            "formative_lesson",
            .journey,
            "Which lesson has life taught you more than once?",
            "生活反复教过你哪件事？",
            "This helps Elephant respect hard-earned knowledge, not just current mood.",
            "这会帮助 Elephant 尊重你从经历里得来的判断，而不只看当下情绪。",
            "journey.lesson.repeated",
            "medium",
            [
                o("trust_slowly", "Trust should grow slowly", "Good intent is not enough; time and behavior matter.", "信任要慢慢长出来", "好意不等于可靠，时间和行动更能说明问题。", "The user has learned that trust should grow slowly through behavior.", "用户从经历中学到，信任要通过时间和行动慢慢长出来。"),
                o("body_truth", "The body tells the truth", "Ignoring capacity eventually becomes expensive.", "身体不会一直替我兜底", "如果长期忽视身体和容量，后面会付出更大的代价。", "The user has learned that ignoring body capacity becomes costly.", "用户从经历中学到，长期忽视身体和容量会带来代价。"),
                o("small_steps", "Small steps are not small", "A tiny sustainable step can matter more than a dramatic plan.", "小步不是小事", "能持续的小步，有时比宏大的计划更能改变现实。", "The user has learned that sustainable small steps can matter more than dramatic plans.", "用户从经历中学到，可持续的小步有时比宏大计划更能改变现实。"),
                o("name_reality", "Name reality early", "Unspoken truths become heavier over time.", "真实情况要早点说出来", "越晚说清楚的真实，后面越重。", "The user has learned that naming reality early prevents heavier problems.", "用户从经历中学到，真实情况越早说清楚，后面越不沉重。")
            ]
        ),
        q(
            "growth_direction",
            .journey,
            "What direction would feel like real growth, not just achievement?",
            "哪种方向会让你觉得自己真的在成长，而不只是完成更多？",
            "This helps Elephant tell the difference between output and growth.",
            "这会帮助 Elephant 区分什么只是产出，什么才是你真正想长成的方向。",
            "journey.direction.growth",
            "medium",
            [
                o("clearer", "Become clearer", "I want less fog around what matters.", "变得更清楚", "我想更清楚地知道什么重要、什么不必再追。", "The user sees growth as becoming clearer about what matters.", "用户把成长理解为更清楚地知道什么重要、什么不必再追。"),
                o("freer", "Become freer", "I want more room to choose from the inside.", "变得更自由", "我想从内在出发选择，而不是总被惯性和外界推着走。", "The user sees growth as becoming freer and more internally directed.", "用户把成长理解为更自由、更能从内在出发选择。"),
                o("steadier", "Become steadier", "I want to hold more without losing myself.", "变得更稳", "我想能承载更多事情，同时不把自己弄丢。", "The user sees growth as becoming steadier while staying self-connected.", "用户把成长理解为更稳定地承载事情，同时不弄丢自己。"),
                o("braver", "Become braver", "I want to face what I already know is true.", "变得更勇敢", "我想更敢面对自己其实已经知道的真实。", "The user sees growth as becoming braver with known truths.", "用户把成长理解为更勇敢地面对自己已经知道的真实。")
            ]
        ),
        q(
            "support_when_stuck",
            .journey,
            "When an old pattern returns, what should Elephant remember?",
            "当旧模式又回来时，Elephant 应该记得什么？",
            "This gives Elephant a humane way to respond when progress is not linear.",
            "这会让 Elephant 在你不是线性前进时，仍然用合适的方式陪你。",
            "journey.support.old_pattern",
            "medium",
            [
                o("not_failure", "Do not treat it as failure", "Returning patterns need care, not shame.", "不要把它当失败", "旧模式回来时，我更需要理解和调整，而不是被提醒又失败了。", "When old patterns return, the user needs care and adjustment rather than shame.", "当旧模式回来时，用户需要理解和调整，而不是被当作失败。"),
                o("name_gently", "Name it gently", "It helps if the pattern is named without accusation.", "温和地指出来", "如果能不带指责地说出模式，我反而更容易看见它。", "When old patterns return, the user benefits from gentle naming without accusation.", "当旧模式回来时，用户受益于温和、不带指责地指出模式。"),
                o("find_exit", "Find the smallest exit", "I need one realistic way out, not a full life redesign.", "找一个最小出口", "我不需要立刻重塑人生，只需要先找到一个能走出去的小出口。", "When old patterns return, the user needs one small realistic exit.", "当旧模式回来时，用户需要一个现实可行的小出口。"),
                o("remember_progress", "Remember previous progress", "Help me see what is different this time.", "提醒我这次哪里不一样", "旧模式像以前，但不一定完全一样。请帮我看见已经变化的部分。", "When old patterns return, the user benefits from seeing what has changed and improved.", "当旧模式回来时，用户受益于看见这一次和过去不同、已经进步的地方。")
            ]
        )
    ]

    private static let deepQuestions: [OnboardingGroundingQuestion] = [
        q("relationship_tension", .world, "What relationship tension tends to cost the most energy?", "哪种关系张力最消耗你？", "This helps Elephant notice hidden social cost behind decisions.", "这会帮助 Elephant 看见决定背后那些不明显的人际成本。", "world.relationships.tension.cost", "high", [
            o("unspoken", "Things left unsaid", "What is not said takes up the most room.", "说不出口的东西", "真正耗人的不是争执，而是那些一直没说出来的话。", "Unspoken relational material can cost the user significant energy.", "关系里说不出口的东西会显著消耗用户。"),
            o("unequal", "Uneven responsibility", "I feel the weight when responsibility is not shared.", "责任不对等", "最累的是明明是共同的事，却像只有我在扛。", "Uneven responsibility in relationships costs the user energy.", "关系中的责任不对等会明显消耗用户。"),
            o("misread", "Being misread", "It is draining when my intent is repeatedly misunderstood.", "被误读", "反复解释自己为什么不是那个意思，会很累。", "Being repeatedly misread in relationships drains the user.", "在关系中被反复误读会消耗用户。"),
            o("distance", "Distance that cannot be named", "Something changes, but no one says what changed.", "说不清的疏远", "距离变了，但没有人真正说清它为什么变了。", "Unnamed distance in relationships can be emotionally costly for the user.", "关系中说不清的疏远会给用户带来消耗。")
        ]),
        q("belonging_place", .world, "Where do you feel a rare sense of belonging?", "在哪些地方，你会少见地觉得自己属于那里？", "This grounds social memory in places and communities that restore the user.", "这会让 Elephant 记住哪些地方和群体会让你恢复归属感。", "world.belonging.place", "medium", [
            o("people", "With a few specific people", "Belonging is person-shaped for me.", "和少数具体的人在一起", "归属感不是来自场合，而是来自某几个具体的人。", "The user's belonging is strongly tied to a few specific people.", "用户的归属感主要来自少数具体的人。"),
            o("making", "Where something is being made", "I belong where attention and craft are respected.", "有人认真创造的地方", "只要大家真的在做东西、尊重手艺，我就比较容易安定。", "The user feels belonging in places where serious making and craft are respected.", "用户在认真创造、尊重手艺的环境里更容易有归属感。"),
            o("quiet", "Quiet shared space", "I like being together without too much performance.", "安静的共同空间", "可以一起待着、不必表演、不必一直解释，我会比较自在。", "The user feels belonging in quiet shared spaces without performance pressure.", "用户在安静、不需表演的共同空间里更容易有归属感。"),
            o("movement", "Places in motion", "Belonging comes through walking, travel, or moving through the world.", "在路上或移动中", "走路、旅行、城市里移动的时候，我反而更容易觉得自己活着。", "The user can feel belonging through movement, walking, travel, or changing places.", "用户可能通过移动、步行、旅行或转换地点获得归属感。")
        ]),
        q("obligation_pattern", .world, "What obligation is hardest for you to put down?", "哪种责任最难被你放下？", "This helps Elephant understand moral pressure without flattening it into productivity.", "这会帮助 Elephant 理解你的责任感，而不是把它简单当成效率问题。", "world.obligation.hard_to_release", "high", [
            o("people_need", "When someone needs me", "Need makes it difficult to choose myself.", "有人需要我", "只要别人真的需要我，我就很难轻易把自己放在前面。", "The user finds it hard to put down obligations when someone needs them.", "当别人需要自己时，用户很难放下责任。"),
            o("promise", "When I promised", "A promise continues to matter even when circumstances change.", "我答应过的事", "只要答应过，即使情况变了，我也很难当作没发生。", "Promises carry strong moral weight for the user.", "承诺对用户有很强的道德重量。"),
            o("quality", "When quality depends on me", "I feel responsible if the work would become careless without me.", "质量靠我守住", "如果我一松手，事情会变粗糙，我就很难真的放下。", "The user feels obligation when quality depends on their care.", "当事情的质量依赖自己的把关时，用户很难放下责任。"),
            o("future", "When future consequences are unclear", "I keep holding it because I cannot yet see the cost of letting go.", "后果还看不清", "看不清放手的后果时，我会继续抓着它。", "Unclear consequences make it hard for the user to release obligations.", "当放手后果不清晰时，用户很难放下责任。")
        ]),
        q("work_meaning", .world, "What makes work feel worthy of your life?", "什么会让一份工作值得占用你的生命？", "This grounds career and project advice in meaning, not only output.", "这会让 Elephant 以后谈工作和项目时，不只看产出，也看意义。", "world.work.meaning", "medium", [
            o("craft", "It asks for real craft", "The work deserves care and skill.", "它需要真正的手艺", "这件事值得被认真做，也能让我把能力磨深。", "The user finds work meaningful when it asks for real craft.", "当工作需要真正的手艺和能力深度时，用户更觉得它值得。"),
            o("people", "It helps real people", "The usefulness is not abstract.", "它真的帮到人", "它不是概念上有用，而是真的能改变某些人的处境。", "The user finds work meaningful when it helps real people concretely.", "当工作能具体帮助真实的人时，用户更觉得它值得。"),
            o("frontier", "It opens a frontier", "It gives me a door into something larger.", "它打开新边界", "它像一扇门，让我进入更大的问题或更长的未来。", "The user finds work meaningful when it opens a larger frontier.", "当工作打开更大的问题、边界或未来空间时，用户更觉得它值得。"),
            o("truth", "It makes something truer", "It reduces confusion, distortion, or noise.", "它让事情更真实清楚", "它能减少混乱、误解或噪音，让真实的东西显出来。", "The user finds work meaningful when it makes reality clearer or truer.", "当工作能减少混乱、让事情更真实清楚时，用户更觉得它值得。")
        ]),
        q("conflict_style", .identity, "What do you tend to do in conflict?", "发生冲突时，你通常会怎么保护局面？", "This helps Elephant support disagreement without escalating it.", "这会帮助 Elephant 在分歧里支持你，而不是把冲突推得更硬。", "identity.conflict.style", "high", [
            o("clarify", "Clarify what is true", "I need facts and meanings separated.", "先把事实和意思分开", "我会想先弄清楚到底发生了什么，和大家各自怎么理解它。", "In conflict, the user tends to clarify facts and meanings.", "冲突中，用户倾向先区分事实和各自的理解。"),
            o("soften", "Soften the room", "I try to lower the emotional temperature first.", "先把气氛降下来", "如果场面太硬，我会先想办法让大家能继续说话。", "In conflict, the user tends to lower emotional temperature first.", "冲突中，用户倾向先降低情绪温度，让对话能继续。"),
            o("withdraw", "Withdraw to think", "I need distance before I can respond well.", "先退开想清楚", "我需要先离开一点，不然容易说出不准确或太重的话。", "In conflict, the user may withdraw to think before responding.", "冲突中，用户可能需要先退开思考，再回应。"),
            o("protect_line", "Protect a line", "When a boundary is crossed, I become very clear.", "守住一条线", "如果某条边界被越过，我会突然变得很明确。", "In conflict, the user becomes very clear when a boundary is crossed.", "冲突中，当边界被越过时，用户会变得很明确。")
        ]),
        q("attention_protection", .identity, "What most often steals your attention from what matters?", "什么最常把你的注意力从重要的事上带走？", "This helps Elephant protect attention without blaming the user.", "这会帮助 Elephant 以后保护你的注意力，而不是责备你不够专注。", "identity.attention.threat", "medium", [
            o("open_loops", "Too many open loops", "Unclosed tasks keep calling from the background.", "太多没关上的线头", "未完成的小事会一直在后台发出声音。", "Open loops are a major attention drain for the user.", "太多未关闭的线头会明显消耗用户注意力。"),
            o("people_noise", "People noise", "Expectations and messages scatter my inner room.", "人际噪音", "别人的期待、消息和情绪，会把我的内在房间弄散。", "People noise and expectations can scatter the user's attention.", "人际噪音和他人期待会分散用户注意力。"),
            o("unclear_priority", "Unclear priority", "When everything matters, nothing can hold me.", "优先级不清", "如果每件事都重要，我就很难真的落在一件事上。", "Unclear priorities make it difficult for the user to hold attention.", "优先级不清会让用户难以稳定注意力。"),
            o("inner_alarm", "Inner alarm", "Anxiety or unresolved meaning keeps pulling focus.", "内心警报", "焦虑、委屈或没想清楚的意义，会一直把我拉走。", "Inner alarm, anxiety, or unresolved meaning pulls the user's attention.", "内心警报、焦虑或未解决的意义感会持续拉走用户注意力。")
        ]),
        q("vulnerability_boundary", .identity, "What makes a deep question feel safe enough to answer?", "什么会让一个很深的问题变得可以回答？", "This calibrates sensitive onboarding and future curiosity.", "这会校准 Elephant 以后如何问敏感问题，避免让深度变成冒犯。", "identity.boundary.vulnerability", "high", [
            o("permission", "Permission first", "Ask whether now is a good time.", "先给我选择权", "先问我现在是否适合，而不是直接把问题放到面前。", "The user needs permission and timing before deep questions.", "用户面对深问题时需要先拥有选择权和时机感。"),
            o("why", "A clear reason", "I can answer if I know why it matters.", "说明为什么要问", "如果我知道这个问题会怎样帮助你理解我，就更容易回答。", "The user feels safer answering deep questions when the reason is clear.", "当问题的理由清楚时，用户更容易回答深问题。"),
            o("skip", "An easy skip", "Safety comes from knowing I can pass.", "能轻松跳过", "知道可以不答，反而会让我更愿意答。", "The user feels safer with sensitive questions when skipping is easy.", "当敏感问题可以轻松跳过时，用户更有安全感。"),
            o("gentle_language", "Gentle language", "The wording should not sound clinical or interrogating.", "措辞要有人味", "不要像诊断或审问，要像一个认真但温和的人在问。", "The user needs deep questions to be worded gently and humanely.", "用户需要深问题的措辞温和、有人的语气，而不是诊断或审问。")
        ]),
        q("recognition_need", .identity, "What kind of being seen matters most to you?", "哪种被看见，对你最重要？", "This helps Elephant recognize the right layer of effort or selfhood.", "这会帮助 Elephant 看见正确的那一层，而不是只夸表面结果。", "identity.recognition.need", "medium", [
            o("effort", "See the effort under the result", "The invisible work matters.", "看见结果背后的努力", "有些努力不在台面上，但它们真的花了我很多力气。", "The user values recognition of invisible effort behind outcomes.", "用户重视别人看见结果背后那些不可见的努力。"),
            o("taste", "See my taste and standards", "I care how things are made, not only that they exist.", "看见我的审美和标准", "我在意东西怎么被做出来，不只是它有没有完成。", "The user values recognition of taste, craft, and standards.", "用户重视自己的审美、手艺和标准被看见。"),
            o("courage", "See the courage it took", "Some small moves are large from the inside.", "看见我用了多大勇气", "有些外面看着很小的动作，对我来说其实很大。", "The user values recognition of the courage behind actions.", "用户重视别人看见某些行动背后的勇气。"),
            o("complexity", "See the complexity", "I want the full context held, not flattened.", "看见事情的复杂性", "我希望别人不要把我和事情都讲得太简单。", "The user values having complexity and full context recognized.", "用户重视自己的复杂处境被完整看见，而不是被简化。")
        ]),
        q("stress_cost", .pulse, "What does stress usually cost you first?", "压力通常最先让你失去什么？", "This helps Elephant detect costs before they become visible failure.", "这会帮助 Elephant 在明显崩掉之前，先看见压力已经拿走了什么。", "pulse.stress.first_cost", "medium", [
            o("sleep", "Sleep or rest", "Recovery gets interrupted first.", "睡眠或休息", "压力最先偷走的是睡眠、放松和身体恢复。", "Stress first tends to cost the user sleep, rest, or recovery.", "压力通常最先消耗用户的睡眠、休息或身体恢复。"),
            o("kindness", "Kindness toward myself", "My inner voice gets harsher.", "对自己的温柔", "我会开始对自己说更重的话。", "Stress first tends to make the user's inner voice harsher.", "压力通常最先让用户对自己变得更严厉。"),
            o("focus", "Focus", "My attention splits and keeps checking for danger.", "专注力", "注意力会碎掉，好像一直在检查哪里有危险。", "Stress first tends to fragment the user's attention.", "压力通常最先让用户注意力碎片化。"),
            o("joy", "Small joy", "The world becomes functional and less alive.", "小小的快乐", "世界会变得只剩功能，少了很多活着的感觉。", "Stress first tends to cost the user small joy and aliveness.", "压力通常最先拿走用户的小快乐和生命感。")
        ]),
        q("body_warning", .pulse, "What body signal should Elephant take seriously?", "哪种身体信号，Elephant 应该认真对待？", "This lets support respect capacity instead of pushing through it.", "这会让 Elephant 尊重你的容量，而不是只催你撑过去。", "pulse.body.warning_signal", "high", [
            o("tight_chest", "Tightness or shallow breath", "My body shows alarm before my words do.", "胸口紧或呼吸浅", "身体可能比语言更早发出警报。", "Tightness or shallow breathing can be an important warning signal for the user.", "胸口紧或呼吸变浅可能是用户重要的身体警报。"),
            o("headache", "Headache or eye strain", "Cognitive load shows up physically.", "头痛或眼睛累", "认知负荷太高时，身体会先表现出来。", "Headache or eye strain can signal cognitive overload for the user.", "头痛或眼睛疲劳可能表示用户认知负荷过高。"),
            o("numb", "Numbness", "If I feel numb, pushing harder will not help.", "麻木或没感觉", "如果已经麻木，继续硬推通常不会更好。", "Numbness can be a warning that pushing harder will not help the user.", "麻木感可能表示用户不适合继续硬推。"),
            o("restless", "Restlessness", "My body may need movement before my mind can settle.", "坐不住或烦躁", "身体可能需要先动一动，心才会重新落地。", "Restlessness can mean the user needs movement before mental settling.", "坐不住或烦躁可能表示用户需要先通过身体活动落地。")
        ]),
        q("overwhelm_signal", .pulse, "How can Elephant tell that a plan is becoming too much?", "Elephant 怎么判断一个计划对你来说开始太满了？", "This helps plan suggestions stay humane and executable.", "这会让 Elephant 以后给计划时保持人性化、可执行。", "pulse.overwhelm.plan_signal", "medium", [
            o("avoid", "I start avoiding it", "Avoidance means the plan may be too large or unclear.", "我开始回避", "如果我开始绕开它，可能不是懒，而是计划太大或太糊。", "Avoidance may signal that a plan is too large or unclear for the user.", "当用户开始回避时，可能表示计划过大或不清晰。"),
            o("overplan", "I keep replanning", "Too much planning can be a way to not touch the task.", "我一直重新计划", "不停重排计划，有时是在避免真正碰它。", "Repeated replanning can signal overwhelm for the user.", "反复重新计划可能表示用户已经被计划压住。"),
            o("flat", "I feel flat", "No resistance, just no energy.", "我变得很平", "不是强烈抗拒，而是整个人没有能量。", "Flatness or low energy can signal that a plan is too much for the user.", "变得很平、没有能量可能表示计划对用户来说太满。"),
            o("irritable", "I get irritable", "I may need the plan simplified, not more persuasion.", "我开始烦躁", "这时可能需要简化计划，而不是更多说服。", "Irritability can signal the user needs a simpler plan, not more persuasion.", "烦躁可能表示用户需要计划被简化，而不是被继续说服。")
        ]),
        q("repair_after_conflict", .pulse, "After a difficult exchange, what helps you repair?", "一场困难对话之后，什么能帮你修复状态？", "This helps Elephant support relationship aftercare.", "这会帮助 Elephant 在困难对话之后支持你恢复，而不是只分析对错。", "pulse.relationship.repair_after_conflict", "high", [
            o("quiet", "Quiet decompression", "I need time without more words.", "安静地缓一缓", "对话之后我可能不想继续说，需要一点没有语言的空间。", "After difficult exchanges, the user may need quiet decompression.", "困难对话后，用户可能需要安静缓冲。"),
            o("meaning", "Understand what happened", "I need to make sense of the exchange.", "弄明白发生了什么", "我会想知道那场对话到底触到了什么。", "After difficult exchanges, the user may need to understand what happened and what was touched.", "困难对话后，用户可能需要理解发生了什么以及触动了哪里。"),
            o("reconnect", "A small sign of reconnection", "A simple repair signal matters.", "一个重新连接的小信号", "不一定要大和解，但一个小小的修复信号很重要。", "After difficult exchanges, a small signal of reconnection helps the user repair.", "困难对话后，一个小的重新连接信号能帮助用户修复。"),
            o("action", "One practical next step", "I recover when I know what to do next.", "一个实际下一步", "知道接下来具体做什么，会让我从情绪里回来一点。", "After difficult exchanges, one practical next step helps the user recover.", "困难对话后，一个实际下一步能帮助用户恢复。")
        ]),
        q("turning_point", .journey, "Which kind of turning point changed how you understand yourself?", "哪种转折改变过你理解自己的方式？", "This gives Journey facts a grounded source without requiring a full life story.", "这会给 Journey 一个有根的线索，不需要你一次讲完整个人生故事。", "journey.turning_point.self_understanding", "high", [
            o("loss", "A loss or ending", "Something ended and forced a new self-understanding.", "一次失去或结束", "某件事结束之后，我不得不重新理解自己。", "A loss or ending has shaped the user's self-understanding.", "一次失去或结束曾改变用户理解自己的方式。"),
            o("success", "A success that felt complicated", "Getting what I wanted taught me something unexpected.", "一次复杂的成功", "得到想要的东西之后，我反而学到一些没想到的事。", "A complicated success has shaped the user's self-understanding.", "一次复杂的成功曾改变用户理解自己的方式。"),
            o("care", "Having to care for someone or something", "Responsibility changed my sense of self.", "不得不照顾某人或某事", "责任改变了我对自己的认识。", "Caretaking responsibility has shaped the user's self-understanding.", "照顾责任曾改变用户理解自己的方式。"),
            o("leap", "Taking a leap", "I learned who I was by crossing a line.", "跨出很大一步", "我是在跨过某条线之后，才知道自己能成为什么样。", "Taking a leap has shaped the user's self-understanding.", "一次大的跨越曾改变用户理解自己的方式。")
        ]),
        q("old_wound_pattern", .journey, "What old wound should not be casually poked?", "哪类旧伤不适合被随便碰？", "This creates a respectful boundary around sensitive history.", "这会为敏感经历建立边界，让 Elephant 不轻率触碰。", "journey.sensitive.old_wound_boundary", "high", [
            o("abandonment", "Being left or replaced", "Do not treat this lightly.", "被丢下或被替代", "这类感觉不适合被轻描淡写。", "Being left or replaced is a sensitive wound area for the user.", "被丢下或被替代是用户不适合被轻率触碰的敏感旧伤。"),
            o("humiliation", "Being shamed", "Shame can echo for a long time.", "被羞辱", "羞耻感会回声很久，不适合随便调侃或用力推动。", "Shame or humiliation is a sensitive wound area for the user.", "羞辱或羞耻感是用户不适合被轻率触碰的敏感旧伤。"),
            o("not_believed", "Not being believed", "I need careful listening around this.", "不被相信", "如果涉及不被相信的经历，我需要非常认真地被听见。", "Not being believed is a sensitive wound area for the user.", "不被相信是用户不适合被轻率触碰的敏感旧伤。"),
            o("body_safety", "Body or safety boundaries", "This needs explicit permission.", "身体或安全边界", "涉及身体和安全边界时，需要非常清楚的许可。", "Body or safety boundaries are highly sensitive for the user and need explicit permission.", "身体或安全边界对用户高度敏感，需要清晰许可。")
        ]),
        q("proud_thread", .journey, "What are you quietly proud of, even if it is hard to explain?", "有什么事，你其实悄悄为自己骄傲？", "This helps Elephant remember strength without turning it into performance.", "这会帮助 Elephant 记住你的力量，而不是把它变成表演。", "journey.strength.quiet_pride", "medium", [
            o("survived", "I survived something difficult", "Continuing was not small.", "我撑过了一些难事", "继续走到现在，本身就不是小事。", "The user is quietly proud of surviving difficult things.", "用户悄悄为自己撑过一些难事而骄傲。"),
            o("made", "I made something real", "Something exists because I cared enough.", "我把东西做出来了", "有些东西能存在，是因为我真的在乎并把它做了出来。", "The user is quietly proud of making something real.", "用户悄悄为自己把东西做出来而骄傲。"),
            o("changed", "I changed a pattern", "It took time to become different.", "我改变过一个旧模式", "变得不一样花了时间，也花了力气。", "The user is quietly proud of changing an old pattern.", "用户悄悄为自己改变过旧模式而骄傲。"),
            o("cared", "I cared when it was costly", "Care remained even when it was not convenient.", "我在不容易时仍然认真照顾", "即使不方便、不轻松，我也没有变得随便。", "The user is quietly proud of caring when care was costly.", "用户悄悄为自己在不容易时仍认真照顾而骄傲。")
        ]),
        q("regret_pattern", .journey, "What kind of regret do you most want to avoid repeating?", "哪种遗憾你最不想再重复？", "This helps Elephant respect learned aversions without trapping the user in fear.", "这会帮助 Elephant 尊重你从遗憾里学到的东西，但不让你被恐惧困住。", "journey.regret.avoid_repeating", "high", [
            o("silence", "Staying silent too long", "I do not want truth to arrive too late.", "沉默太久", "我不想等到太晚，才说出真正重要的话。", "The user wants to avoid repeating the regret of staying silent too long.", "用户最不想重复沉默太久、真实来得太晚的遗憾。"),
            o("overstay", "Staying too long", "I do not want loyalty to become self-erasure.", "停留太久", "我不想把忠诚变成对自己的消耗和擦除。", "The user wants to avoid staying too long where loyalty becomes self-erasure.", "用户不想再重复停留太久、把忠诚变成自我消耗的遗憾。"),
            o("rush", "Rushing past myself", "I do not want speed to override inner consent.", "越过自己太快", "我不想因为赶路，把自己的同意和感受落在后面。", "The user wants to avoid rushing past their own inner consent.", "用户不想再重复因为太快而越过自己内在同意的遗憾。"),
            o("not_try", "Not trying", "I do not want fear to make the decision for me.", "因为害怕而没试", "我不想让恐惧替我做决定。", "The user wants to avoid letting fear decide by not trying.", "用户不想再重复因为害怕而没有尝试的遗憾。")
        ]),
        q("learning_style", .journey, "How do you usually learn something that truly changes you?", "你通常怎么学会那些真的改变你的东西？", "This helps Elephant choose teaching, coaching, and reflection modes.", "这会帮助 Elephant 选择更适合你的教学、陪练和反思方式。", "journey.learning.style", "low", [
            o("practice", "By practicing until it becomes embodied", "I need lived repetition.", "反复练到身体会", "真的学会不是听懂，而是身体和手感也变了。", "The user learns deeply through embodied practice and repetition.", "用户通常通过反复练习到身体会，来学会真正改变自己的东西。"),
            o("dialogue", "Through dialogue", "My understanding sharpens with another mind.", "通过对话", "和另一个脑子来回碰撞时，我会更快看清。", "The user learns deeply through dialogue and co-thinking.", "用户通常通过对话和共思来学会真正改变自己的东西。"),
            o("reading", "By reading and connecting ideas", "Concepts give me handles for experience.", "通过阅读和连接概念", "概念会给经验一个把手，让我终于能抓住它。", "The user learns deeply by reading and connecting ideas to experience.", "用户通常通过阅读、概念连接和经验理解来学会深层东西。"),
            o("crisis", "After something breaks", "Some lessons only land after reality interrupts me.", "在事情被打断之后", "有些课是在现实打断我之后才真正落下来的。", "The user often learns deeply after disruption or crisis makes a lesson land.", "用户常在事情被打断或现实强行介入后学会深层东西。")
        ]),
        q("future_fear", .journey, "Which future would feel especially wrong for you?", "哪种未来会让你觉得特别不对劲？", "This gives Elephant a negative compass for long-term advice.", "这会给 Elephant 一个长期建议里的反向指南针，知道哪些路不适合你。", "journey.future.negative_compass", "medium", [
            o("numb_success", "Successful but numb", "Outcomes look good, but I cannot feel my life.", "看起来成功但内心麻木", "外面看一切都好，但我感觉不到自己在生活。", "A future that looks successful but feels numb would be wrong for the user.", "看起来成功但内心麻木的未来，对用户来说是不对劲的。"),
            o("trapped", "Stable but trapped", "Security costs too much aliveness.", "稳定但被困住", "安全感如果换走了太多生命力，就不对。", "A stable but trapped future would be wrong for the user.", "稳定但被困住、生命力被换走的未来，对用户来说是不对劲的。"),
            o("alone", "Capable but alone", "Competence without real connection would feel empty.", "很能干但很孤单", "如果只剩能力，没有真实连接，会很空。", "A capable but isolated future would feel wrong for the user.", "很能干但缺少真实连接的未来，对用户来说是不对劲的。"),
            o("scattered", "Free but scattered", "Possibility without direction can become loss.", "自由但散掉", "如果只有可能性却没有方向，也会像一种失去。", "A free but scattered future without direction would feel wrong for the user.", "自由但散掉、没有方向的未来，对用户来说是不对劲的。")
        ])
    ]

    private static let extendedQuestions: [OnboardingGroundingQuestion] = [
        q("family_imprint", .world, "What did your early family system teach you to notice?", "早年的家庭系统，让你特别会注意什么？", "This adds anthropological context without assuming pathology.", "这会补上更早期的生活环境线索，但不把它简单病理化。", "world.family.imprint.attention", "high", [
            o("mood", "Other people's mood", "I learned to read atmosphere quickly.", "别人的情绪和气氛", "我很早就学会观察房间里的气氛变没变。", "The user learned early to read other people's mood and atmosphere.", "用户早年学会了敏锐观察他人的情绪和气氛。"),
            o("needs", "Unspoken needs", "I notice what people need before they say it.", "没说出口的需要", "别人还没说，我可能已经在猜他们需要什么。", "The user learned early to notice unspoken needs.", "用户早年学会了注意他人没说出口的需要。"),
            o("rules", "Hidden rules", "I look for what is allowed and what is not.", "隐藏规则", "我会很快寻找这里什么能说、什么不能说。", "The user learned early to read hidden rules in a social system.", "用户早年学会了读取环境里的隐藏规则。"),
            o("self_reliance", "How to rely on myself", "I became used to handling things internally.", "怎么靠自己", "很多事情我会先自己消化、自己处理。", "The user learned early to rely on themselves and handle things internally.", "用户早年学会了先靠自己消化和处理事情。")
        ]),
        q("chosen_people", .world, "Who are the people you choose, not only inherit?", "哪些人是你主动选择靠近的，而不只是继承来的？", "This separates chosen community from default social context.", "这会区分你主动选择的共同体和默认继承的关系。", "world.relationships.chosen_people", "medium", [
            o("thinkers", "People who think seriously", "I choose people who care about meaning and precision.", "认真思考的人", "我会靠近那些真的在意意义、准确和思考质量的人。", "The user chooses people who think seriously and value meaning.", "用户主动靠近认真思考、在意意义和准确的人。"),
            o("warm", "People with warmth", "Kindness matters as much as brilliance.", "有温度的人", "聪明不够，我会选择有温度、有照顾感的人。", "The user chooses warmth and care, not only brilliance.", "用户主动选择有温度和照顾感的人，不只看聪明。"),
            o("makers", "People who make things", "I trust people who put care into reality.", "真正做东西的人", "我会靠近那些把想法变成现实、愿意下手做的人。", "The user chooses people who make things and put care into reality.", "用户主动靠近真正做东西、把照料放进现实的人。"),
            o("free", "People who let me breathe", "I choose relationships where I can keep my inner room.", "让我能呼吸的人", "我会选择那些靠近后仍然能保有自己空间的人。", "The user chooses people who allow breathing room and inner space.", "用户主动选择能让自己保有呼吸感和内在空间的人。")
        ]),
        q("institution_fit", .world, "What kind of institution or system fits you poorly?", "什么样的机构或系统最不适合你？", "This helps Elephant avoid recommending contexts that erode the user.", "这会帮助 Elephant 避免推荐会消耗你的环境。", "world.institutions.bad_fit", "medium", [
            o("opaque", "Opaque power", "I struggle where rules are hidden and arbitrary.", "权力不透明", "规则藏着、决定随意的地方会让我很难安定。", "Opaque or arbitrary systems fit the user poorly.", "权力不透明、规则随意的系统不适合用户。"),
            o("performative", "Performance over substance", "I lose energy where appearance beats reality.", "重表演轻实质", "如果外观和姿态比真实工作更重要，我会很快消耗。", "Systems that reward performance over substance fit the user poorly.", "重表演轻实质的系统不适合用户。"),
            o("cold", "Cold efficiency", "Efficiency without care makes me smaller.", "冰冷效率", "只剩效率、没有照顾感的系统，会让我变小。", "Cold efficiency without care fits the user poorly.", "只有冰冷效率、缺少照顾感的系统不适合用户。"),
            o("chaotic", "Permanent chaos", "I can handle intensity, but not endless disorder.", "长期混乱", "我可以承受强度，但不适合永无止境的混乱。", "Endless disorder or permanent chaos fits the user poorly.", "长期混乱、无止境失序的系统不适合用户。")
        ]),
        q("privacy_line", .identity, "What should stay private unless you clearly choose otherwise?", "哪些内容应该默认保持私密，除非你明确选择分享？", "This makes privacy a first-class Personal Model boundary.", "这会把隐私边界明确放进 Personal Model，而不是靠临时猜测。", "identity.privacy.default_private", "high", [
            o("health", "Health and body", "Treat health context as private by default.", "健康和身体", "涉及健康、身体和安全的信息，默认应该更谨慎。", "Health and body context should be private by default for the user.", "健康和身体相关信息对用户应默认保持私密。"),
            o("relationships", "Relationship details", "Do not casually surface private relational context.", "关系细节", "具体关系里的细节，不适合被随便拿出来用。", "Relationship details should be private by default for the user.", "具体关系细节对用户应默认保持私密。"),
            o("finances", "Money or security", "Financial and security context needs discretion.", "金钱或安全", "金钱、安全、住处等现实底盘信息，需要有分寸。", "Money and security context should be private by default for the user.", "金钱和安全相关信息对用户应默认保持私密。"),
            o("creative", "Unfinished ideas", "Early ideas should not be treated as public commitments.", "还没成形的想法", "早期想法不应该被当成公开承诺或稳定结论。", "Unfinished ideas should remain private and not be treated as commitments.", "用户未成形的想法应默认保持私密，不能当作公开承诺。")
        ]),
        q("moral_tradeoff", .identity, "What moral trade-off is hardest for you?", "哪种道德取舍对你最难？", "This gives philosophical grounding for advice under conflict.", "这会给 Elephant 在冲突建议里加入更深的价值判断基础。", "identity.values.moral_tradeoff", "high", [
            o("truth_kindness", "Truth and kindness", "I struggle when honesty may hurt.", "真实和善意", "当说真话可能伤人时，我会很难。", "The user finds trade-offs between truth and kindness especially hard.", "真实和善意之间的取舍对用户尤其困难。"),
            o("self_others", "Self and others", "I struggle when caring for myself costs someone else.", "自己和他人", "当照顾自己会让别人失望或受影响时，我会很难。", "The user finds trade-offs between self-care and others' needs especially hard.", "自我照顾和他人需要之间的取舍对用户尤其困难。"),
            o("loyal_change", "Loyalty and change", "I struggle when growth asks me to leave an old promise.", "忠诚和改变", "当成长意味着离开某种旧承诺时，我会很难。", "The user finds trade-offs between loyalty and change especially hard.", "忠诚和改变之间的取舍对用户尤其困难。"),
            o("freedom_safety", "Freedom and safety", "I struggle when aliveness asks for risk.", "自由和安全", "当生命力需要冒险，而安全感不允许时，我会很难。", "The user finds trade-offs between freedom and safety especially hard.", "自由和安全之间的取舍对用户尤其困难。")
        ]),
        q("beauty_ritual", .identity, "What small ritual makes life feel more habitable?", "什么小仪式会让生活变得更能住进去？", "This gives Elephant humane recovery cues beyond productivity.", "这会让 Elephant 记住不只是效率，还有让生活可居住的小方式。", "identity.ritual.habitable_life", "low", [
            o("morning", "A quiet beginning", "How a day starts changes how I inhabit it.", "安静地开始一天", "一天怎么开始，会影响我能不能住进这一天。", "A quiet beginning helps the user inhabit the day.", "安静地开始一天能帮助用户更好地进入生活。"),
            o("space", "Putting the space in order", "A cared-for room helps my mind return.", "整理空间", "空间被照料过，心也会比较容易回来。", "Putting space in order helps the user return to themselves.", "整理和照料空间能帮助用户回到自己。"),
            o("music", "Music or sound", "Sound changes the emotional weather.", "音乐或声音", "声音会改变房间里的天气。", "Music or sound can change the user's emotional weather.", "音乐或声音能改变用户的情绪气候。"),
            o("object", "A meaningful object", "Small objects can hold continuity.", "一个有意义的小物件", "小物件有时能把我和某种连续性连起来。", "Meaningful objects can help the user hold continuity.", "有意义的小物件能帮助用户保持连续感。")
        ]),
        q("time_orientation", .identity, "Which time horizon do you naturally protect?", "你天然会保护哪一种时间尺度？", "This helps Elephant match short-term and long-term reasoning.", "这会帮助 Elephant 在短期行动和长期判断之间找到适合你的尺度。", "identity.time_horizon.protected", "low", [
            o("today", "Today needs to be survivable", "A good future cannot ignore today's capacity.", "今天要先过得去", "再好的未来，也不能完全无视今天的容量。", "The user protects today's survivability and capacity.", "用户会保护今天是否过得去和当下容量。"),
            o("season", "This season matters", "I think in chapters and transitions.", "这个阶段很重要", "我会按阶段、章节和过渡期来理解生活。", "The user naturally thinks in seasons, chapters, and transitions.", "用户天然会用阶段、章节和过渡期理解生活。"),
            o("years", "The next few years", "I care about compounding direction.", "未来几年", "我会在意方向是否能复利，几年后会把我带到哪里。", "The user protects multi-year direction and compounding effects.", "用户会保护未来几年的方向和复利效应。"),
            o("life", "The life arc", "Some questions only make sense at the scale of a life.", "整个人生弧线", "有些问题只有放到人生尺度里才说得清。", "The user sometimes thinks at the scale of a full life arc.", "用户有时会以整个人生弧线来判断事情。")
        ]),
        q("praise_correction", .identity, "How should Elephant correct you when it sees a mismatch?", "当 Elephant 发现你说的和你的长期方向不太一致时，应该怎么提醒？", "This makes correction explicit and consent-based.", "这会让修正和提醒有明确方式，不靠冒犯式猜测。", "identity.correction.preference", "medium", [
            o("plain", "Say it plainly", "I prefer clear, respectful friction.", "直接说清楚", "只要尊重，直接指出不一致对我有帮助。", "The user prefers clear and respectful correction when there is a mismatch.", "当出现不一致时，用户偏好清楚且尊重地被提醒。"),
            o("question", "Ask a question", "Help me notice it myself.", "用问题提醒我", "问一个准的问题，让我自己看见哪里不对。", "The user prefers correction through a precise question.", "当出现不一致时，用户偏好通过精准问题自己看见。"),
            o("evidence", "Show the evidence", "Tell me what you are comparing against.", "告诉我依据是什么", "请说清你是根据什么判断不一致的。", "The user prefers correction that includes the evidence or remembered basis.", "当出现不一致时，用户希望看到提醒依据。"),
            o("soft", "Be very gentle", "I may need the reminder softened before I can use it.", "非常温和一点", "有些提醒如果太硬，我会先防御，反而听不进去。", "The user needs gentle correction so reminders remain usable.", "用户需要较温和的修正方式，太硬会引发防御。")
        ]),
        q("solitude_social", .pulse, "When do you need solitude, and when do you need people?", "什么时候你需要独处，什么时候你需要人？", "This prevents Elephant from treating isolation and restoration as the same thing.", "这会避免 Elephant 把独处、孤立和恢复混成一件事。", "pulse.social.solitude_balance", "medium", [
            o("solitude_first", "Solitude first, then people", "I need to hear myself before I can be with others.", "先独处，再见人", "我需要先听见自己，之后才更能好好和人在一起。", "The user often needs solitude first before social contact becomes restorative.", "用户通常需要先独处，再进入有恢复感的人际连接。"),
            o("people_first", "People first, then solitude", "A trusted person helps me land; then I need quiet.", "先见信任的人，再独处", "先被接住一下，之后我会需要安静消化。", "The user may need trusted contact first, then solitude to process.", "用户可能先需要信任的人接住，再独处消化。"),
            o("parallel", "Parallel presence", "Being near someone without much talking helps.", "并排待着", "有人在，但不用一直说话，这种在场会让我舒服。", "Parallel presence without much talking can restore the user.", "不用频繁说话的并排在场能帮助用户恢复。"),
            o("depends", "It depends on the kind of tired", "Mental, emotional, and body tiredness need different care.", "要看是哪种累", "脑力累、情绪累、身体累，需要的东西不一样。", "The user's need for solitude or people depends on the type of tiredness.", "用户需要独处还是人，取决于是哪一种累。")
        ]),
        q("money_security", .world, "How does security shape your choices?", "安全感会怎样影响你的选择？", "This adds material grounding without reducing the user to finances.", "这会补上现实底盘，但不把你简化成财务状况。", "world.security.choice_shape", "high", [
            o("base", "I need a stable base", "Without a base, possibility feels unsafe.", "需要稳定底盘", "没有底盘时，很多可能性会变得不安全。", "The user needs a stable security base before possibility feels safe.", "用户需要稳定的安全底盘，可能性才会变得可承受。"),
            o("freedom", "Security means freedom", "A buffer gives me room to choose well.", "安全感意味着自由", "有缓冲，才有空间做真正好的选择。", "For the user, security creates freedom and better choice space.", "对用户来说，安全感会创造自由和更好的选择空间。"),
            o("risk", "Too much safety can trap me", "Security is good until it takes over aliveness.", "太安全也会困住我", "安全感很好，但如果它拿走生命力，就变成另一种笼子。", "The user values security but notices when it becomes a trap.", "用户重视安全感，但也会警惕过度安全变成束缚。"),
            o("unspoken", "Security is hard to talk about", "It carries emotion, not only numbers.", "安全感很难开口谈", "它不只是数字，也有很多情绪、尊严和过去经验。", "Security is emotionally loaded for the user and not only numerical.", "安全感对用户带有情绪、尊严和经验负荷，不只是数字。")
        ]),
        q("ambition_shape", .journey, "What shape does your ambition have when it is healthy?", "当你的野心是健康的，它长什么样？", "This helps Elephant support ambition without feeding self-erasure.", "这会帮助 Elephant 支持你的野心，而不是助长自我消耗。", "journey.ambition.healthy_shape", "medium", [
            o("craft", "Deep craft", "I want to become genuinely good at something.", "深手艺", "我想真的把某件事做深、做准、做成自己的能力。", "The user's healthy ambition is shaped by deep craft.", "用户健康的野心呈现为把一件事做深、做准的手艺感。"),
            o("impact", "Real impact", "I want the work to touch real lives.", "真实影响", "我希望做的事真的改变某些人的处境。", "The user's healthy ambition is shaped by real impact.", "用户健康的野心呈现为对真实生活产生影响。"),
            o("freedom", "More freedom", "I want ambition to widen life, not narrow it.", "更大的自由", "野心应该把生活打开，而不是越收越窄。", "The user's healthy ambition should widen life and freedom.", "用户健康的野心应该扩大生活和自由，而不是收窄它们。"),
            o("legacy", "A durable body of work", "I want something that lasts beyond one sprint.", "留下长期作品", "我想留下经得起时间的东西，不只是完成一次冲刺。", "The user's healthy ambition is shaped by durable work that lasts.", "用户健康的野心呈现为留下经得起时间的长期作品。")
        ]),
        q("grief_change", .journey, "How do you usually move through endings?", "面对结束时，你通常怎么走过去？", "This helps Elephant respect grief and transition rather than rushing closure.", "这会让 Elephant 尊重结束和过渡，而不是急着帮你翻篇。", "journey.endings.movement", "high", [
            o("slow", "Slowly and privately", "I may need more time than I show.", "慢慢地、私下地", "我表面可能没什么，但里面需要很久。", "The user may move through endings slowly and privately.", "用户面对结束时可能需要慢慢、私下地消化。"),
            o("meaning", "By making meaning", "I need to understand what the ending changed.", "通过理解意义", "我需要知道这次结束到底改变了什么。", "The user moves through endings by making meaning of what changed.", "用户面对结束时会通过理解意义和变化来走过去。"),
            o("new_form", "By building a new form", "I recover by giving life a next shape.", "搭一个新的形状", "我需要给生活重新搭出一个能继续住进去的形状。", "The user moves through endings by building a new form of life.", "用户面对结束时会通过搭建新的生活形状来恢复。"),
            o("contact", "Through shared remembrance", "It helps to remember with someone safe.", "和安全的人一起记得", "有人能一起记得，而不是让我独自收起来，会有帮助。", "The user moves through endings with shared remembrance and safe contact.", "用户面对结束时受益于和安全的人共同记得。")
        ]),
        q("care_language", .world, "How do you most naturally show care?", "你最自然地怎么表达照顾？", "This helps Elephant understand care as action, attention, or presence.", "这会帮助 Elephant 理解你的照顾方式，不只看表面语言。", "world.care.expression", "low", [
            o("acts", "Doing practical things", "I care by making life easier.", "做具体的事", "我会通过实际行动让对方轻松一点。", "The user often shows care through practical action.", "用户常通过做具体的事来表达照顾。"),
            o("attention", "Careful attention", "I remember details and notice changes.", "认真注意细节", "我会记得细节，也会注意对方哪里不一样了。", "The user often shows care through careful attention and remembering details.", "用户常通过认真注意细节和记住变化来表达照顾。"),
            o("words", "Words that hold", "I care by saying the thing that helps someone stay with themselves.", "用话接住对方", "我会用一些话，让对方能重新和自己待在一起。", "The user often shows care through words that hold and orient others.", "用户常通过能接住对方的话来表达照顾。"),
            o("space", "Giving space", "I care by not crowding the other person.", "给对方空间", "我会通过不挤压、不追问，来表达尊重和照顾。", "The user often shows care by giving space and not crowding others.", "用户常通过给空间、不挤压来表达照顾。")
        ]),
        q("authority_pattern", .world, "How do you respond to authority?", "面对权威时，你通常是什么反应？", "This helps Elephant understand power dynamics around advice.", "这会帮助 Elephant 理解建议里的权力感，避免变成另一种压迫。", "world.power.authority_response", "medium", [
            o("test", "I test whether it is legitimate", "Authority needs to earn trust.", "先判断它是否正当", "我不会因为它像权威就自动相信，它需要证明自己正当。", "The user evaluates whether authority is legitimate before trusting it.", "用户面对权威时会先判断其是否正当，而不是自动相信。"),
            o("resist", "I resist being controlled", "Control triggers a strong boundary response.", "抗拒被控制", "一旦感觉被控制，我的边界会变得很明显。", "The user strongly resists authority that feels controlling.", "用户对带有控制感的权威会产生强边界反应。"),
            o("seek", "I appreciate trustworthy authority", "Good authority can feel relieving.", "欣赏可靠的权威", "如果对方真的可靠、有能力、有分寸，我会觉得省力。", "The user can appreciate trustworthy and well-boundaried authority.", "用户能欣赏可靠、有能力且有分寸的权威。"),
            o("freeze", "I may freeze first", "Old power dynamics can make response slower.", "可能先僵住", "某些权力感会让我先变慢，之后才知道怎么回应。", "The user may freeze or slow down around some power dynamics.", "某些权力感可能让用户先僵住或变慢。")
        ]),
        q("risk_appetite", .identity, "What kind of risk feels alive rather than reckless?", "哪种冒险会让你觉得有生命力，而不是鲁莽？", "This calibrates growth suggestions and risk tolerance.", "这会校准 Elephant 以后给成长建议时的风险尺度。", "identity.risk.alive_not_reckless", "medium", [
            o("reversible", "Reversible experiments", "I like risks with a way back.", "可逆的小实验", "如果能退回来，我会更愿意试。", "The user prefers risks framed as reversible experiments.", "用户更能接受可逆的小实验式风险。"),
            o("meaningful", "Meaningful leaps", "I can take risk when the meaning is strong.", "意义足够强的跃迁", "如果意义真的强，我可以跨出很大一步。", "The user can take larger risks when the meaning is strong.", "当意义足够强时，用户可以承受较大的跃迁风险。"),
            o("prepared", "Prepared risk", "Risk feels alive when the base is cared for.", "有准备的冒险", "底盘被照顾好之后，冒险才像生命力，不像自毁。", "The user needs a cared-for base for risk to feel alive.", "用户需要底盘被照顾好，风险才会显得有生命力。"),
            o("shared", "Shared risk", "It helps to not carry the risk alone.", "有人一起承担", "如果不是我一个人承担，风险会更可承受。", "The user finds risk more tolerable when it is shared.", "当风险有人共同承担时，用户更能承受。")
        ]),
        q("uncertainty_style", .pulse, "What do you need when uncertainty stays unresolved?", "当不确定性暂时无法消除时，你需要什么？", "This keeps Elephant from forcing false certainty.", "这会避免 Elephant 为了安慰而制造虚假的确定性。", "pulse.uncertainty.support", "medium", [
            o("ranges", "A range of possibilities", "I can stand uncertainty if the range is named.", "一个可能性的范围", "如果能知道大概有哪些可能，我就不需要假装确定。", "The user can tolerate uncertainty better when the range of possibilities is named.", "当可能性范围被说清楚时，用户更能承受不确定。"),
            o("next_check", "A next check-in point", "I need to know when we will revisit it.", "下次确认点", "不确定没关系，但要知道什么时候再看一次。", "The user handles uncertainty better with a clear next check-in point.", "用户在不确定时需要明确下次确认点。"),
            o("body", "Grounding in the body", "My mind may not solve it, but my body can settle.", "先让身体落地", "脑子未必能马上解决，但身体可以先稳一点。", "The user handles uncertainty better by grounding the body first.", "用户面对不确定时受益于先让身体落地。"),
            o("truth", "Plain truth", "Do not pretend we know more than we do.", "诚实说不知道", "请不要假装知道得比实际更多。", "The user prefers honest uncertainty over false certainty.", "用户更喜欢诚实承认不知道，而不是虚假的确定性。")
        ]),
        q("hope_signal", .journey, "What is a reliable sign that hope is returning?", "什么迹象说明，希望正在回来？", "This helps Elephant notice recovery before everything is solved.", "这会帮助 Elephant 看见恢复正在发生，即使问题还没完全解决。", "journey.hope.return_signal", "low", [
            o("curiosity", "Curiosity returns", "I start asking better questions again.", "好奇心回来", "我又开始问更好的问题了。", "Curiosity returning is a reliable hope signal for the user.", "好奇心回来是用户希望正在恢复的可靠信号。"),
            o("making", "I want to make something", "Creation returns before confidence does.", "想做点东西", "创造欲可能比信心更早回来。", "Wanting to make something is a hope signal for the user.", "想做点东西是用户希望正在恢复的信号。"),
            o("contact", "I reach out", "I become more willing to be in contact.", "愿意和人连接", "我开始更愿意和某些人重新连接。", "Willingness to reach out is a hope signal for the user.", "愿意和人重新连接是用户希望正在恢复的信号。"),
            o("future", "I can imagine a future scene", "A small future image appears again.", "能想象一点未来画面", "未来又开始有一点画面，而不是一片空白。", "Being able to imagine a future scene is a hope signal for the user.", "能想象一点未来画面是用户希望正在恢复的信号。")
        ]),
        q("identity_transition", .journey, "What identity are you outgrowing?", "你正在长出哪种旧身份？", "This helps Elephant support transition without clinging to stale facts.", "这会帮助 Elephant 支持身份转变，而不是抓着过期事实不放。", "journey.identity.outgrowing", "medium", [
            o("always_strong", "The one who is always strong", "I may be learning to need and receive.", "永远很强的人", "我可能正在学习也可以需要别人、接住别人给的东西。", "The user may be outgrowing the identity of always being strong.", "用户可能正在长出必须永远很强的旧身份。"),
            o("productive", "The one who only proves through output", "I may be more than what I produce.", "只能靠产出证明自己的人", "我可能正在学习，自己不只是产出。", "The user may be outgrowing proving themselves only through output.", "用户可能正在长出只能靠产出证明自己的旧身份。"),
            o("adapter", "The one who adapts to every room", "I may be learning to let the room adapt too.", "总是适应别人的人", "我可能正在学习，不必总是由我适应环境。", "The user may be outgrowing always adapting to others.", "用户可能正在长出总是适应别人的旧身份。"),
            o("observer", "The one who watches from outside", "I may be entering life more directly.", "只在旁边观察的人", "我可能正在更直接地进入生活，而不只是理解它。", "The user may be outgrowing only observing from the outside.", "用户可能正在长出只在旁边观察生活的旧身份。")
        ]),
        q("daily_ritual", .pulse, "Which daily anchor would most improve your next month?", "哪种日常锚点最可能改善你接下来一个月？", "This turns early understanding into near-term support.", "这会把刚刚了解你的内容转成接下来就有用的支持。", "pulse.daily_anchor.next_month", "low", [
            o("sleep", "A more protected sleep window", "Energy would improve if sleep had a boundary.", "更被保护的睡眠窗口", "如果睡眠边界更稳，很多事会跟着变好。", "A protected sleep window would likely improve the user's next month.", "更被保护的睡眠窗口可能改善用户接下来一个月。"),
            o("review", "A short daily review", "A few minutes of orientation would reduce drift.", "很短的每日整理", "每天几分钟重新对齐，会减少漂移感。", "A short daily review would likely reduce drift for the user.", "很短的每日整理可能减少用户接下来一个月的漂移感。"),
            o("movement", "Gentle movement", "The body needs a small reliable path.", "温和身体活动", "身体需要一条小而可靠的路径。", "Gentle movement would likely improve the user's next month.", "温和身体活动可能改善用户接下来一个月。"),
            o("focus", "One protected focus block", "A small protected block would change the week.", "一块受保护的专注时间", "哪怕不长，只要稳定受保护，就会改变一周的形状。", "One protected focus block would likely improve the user's next month.", "一块受保护的专注时间可能改善用户接下来一个月。")
        ]),
        q("place_attachment", .world, "What kind of place do you become attached to?", "你容易对什么样的地方产生依恋？", "This adds place-based context to World facts.", "这会给 World 维度补上地点和空间的情感线索。", "world.places.attachment", "low", [
            o("walkable", "Walkable places", "I bond with places I can slowly move through.", "可以慢慢走的地方", "能一步一步走过的地方，更容易和我建立关系。", "The user becomes attached to walkable places.", "用户容易对可以慢慢步行穿过的地方产生依恋。"),
            o("light", "Places with good light", "Light changes whether a place feels livable.", "光线好的地方", "光会改变一个地方是否能住进心里。", "The user becomes attached to places with good light.", "用户容易对光线好的地方产生依恋。"),
            o("memory", "Places with memory", "History and traces make a place feel alive.", "有记忆的地方", "有历史、有痕迹的地方，会让我觉得它是活的。", "The user becomes attached to places with memory, history, or traces.", "用户容易对有记忆、有历史或有痕迹的地方产生依恋。"),
            o("quiet", "Places that do not demand performance", "I like places where I can simply be.", "不用表演的地方", "在那里不必证明什么，只要待着就可以。", "The user becomes attached to places that do not demand performance.", "用户容易对不需要表演或证明自己的地方产生依恋。")
        ]),
        q("creativity_source", .identity, "Where does your best creativity usually come from?", "你最好的创造力通常从哪里来？", "This helps Elephant support creation in the right mode.", "这会帮助 Elephant 用更适合你的方式支持创造。", "identity.creativity.source", "low", [
            o("friction", "A real friction", "I create when something bothers me enough.", "真实摩擦", "有什么东西不对劲、不够好，我才会真的想做。", "The user's creativity often starts from real friction.", "用户最好的创造力常从真实摩擦和不对劲开始。"),
            o("beauty", "Aesthetic pull", "Beauty or form pulls me forward.", "审美牵引", "某种美感、形式或气质会把我往前拉。", "The user's creativity often starts from aesthetic pull.", "用户最好的创造力常受审美、形式或气质牵引。"),
            o("care", "Care for someone", "I create because someone needs a better thing.", "想照顾某个人", "因为有人需要一个更好的东西，我就会想把它做出来。", "The user's creativity often starts from care for someone.", "用户最好的创造力常从想照顾某个人开始。"),
            o("play", "Play and curiosity", "I make things by following a living question.", "玩心和好奇", "一个活的问题会带着我往前做。", "The user's creativity often starts from play and curiosity.", "用户最好的创造力常从玩心和好奇开始。")
        ]),
        q("help_boundary", .identity, "What should Elephant avoid doing when trying to help?", "Elephant 想帮你时，最应该避免什么？", "This adds an explicit assistant behavior boundary.", "这会给助手行为本身设定清楚边界。", "identity.assistant.boundary.avoid", "medium", [
            o("nag", "Nagging", "Repeated reminders can turn support into pressure.", "反复催促", "提醒太密时，支持会变成压力。", "Elephant should avoid nagging because repeated reminders can become pressure.", "Elephant 应避免反复催促，因为提醒过密会变成压力。"),
            o("therapize", "Over-therapizing", "Not every problem needs emotional interpretation.", "过度心理分析", "不是每个问题都需要被解释成心理原因。", "Elephant should avoid over-therapizing the user's problems.", "Elephant 应避免把每个问题都过度心理分析。"),
            o("takeover", "Taking over", "Help should not remove my agency.", "替我接管", "帮忙不应该拿走我的主动权。", "Elephant should avoid taking over in ways that remove the user's agency.", "Elephant 应避免替用户接管并拿走其主动权。"),
            o("generic", "Generic advice", "I would rather hear less than be given a template.", "模板化建议", "我宁愿少听一点，也不想收到泛泛的模板。", "Elephant should avoid generic advice and templates.", "Elephant 应避免泛泛的模板化建议。")
        ]),
        q("question_preference", .pulse, "What kind of question is worth interrupting you for?", "什么样的问题值得打断你来问？", "This calibrates future proactive curiosity.", "这会校准 Elephant 以后什么时候值得主动问你。", "pulse.curiosity.interruption_threshold", "low", [
            o("behavior_change", "It changes how you will help", "Ask if the answer will change future behavior.", "会改变你以后怎么帮我", "如果答案会明显改变你之后的支持方式，就值得问。", "The user welcomes questions when answers materially change future help.", "当答案会明显改变 Elephant 未来支持方式时，用户欢迎被问。"),
            o("conflict", "You see a real mismatch", "Ask when my words and patterns conflict.", "你发现真实不一致", "如果你发现我说的和长期模式冲突，可以问。", "The user welcomes questions when Elephant sees a meaningful mismatch.", "当 Elephant 发现有意义的不一致时，用户欢迎被问。"),
            o("stale", "Something may be outdated", "Ask when old context may no longer be true.", "旧信息可能过期", "如果旧背景可能已经不准了，可以来确认。", "The user welcomes questions when old context may be stale.", "当旧背景可能过期时，用户欢迎 Elephant 确认。"),
            o("rarely", "Ask rarely", "I prefer quiet unless the question really matters.", "尽量少问", "除非真的重要，否则我更喜欢安静一点。", "The user prefers proactive questions to be rare unless they clearly matter.", "用户偏好少被主动提问，除非问题确实重要。")
        ]),
        q("model_correction", .identity, "If Elephant gets you wrong, how should correction work?", "如果 Elephant 理解错你，修正应该怎么发生？", "This makes the Personal Model correctable from the start.", "这会让 Personal Model 从一开始就是可修正的，而不是隐藏画像。", "identity.personal_model.correction_flow", "low", [
            o("quick_edit", "Let me edit the fact", "The wrong claim should be directly fixable.", "让我直接改事实", "错的理解应该能被直接改掉。", "The user wants wrong Personal Model facts to be directly editable.", "用户希望错误的 Personal Model 事实可以直接编辑。"),
            o("explain", "Ask why it is wrong", "Correction should improve the underlying model.", "问我错在哪里", "修正不只是删掉，也应该让你知道为什么错。", "The user wants corrections to improve underlying understanding.", "用户希望修正不仅删除错误，还能改善底层理解。"),
            o("forget", "Offer forgetting", "Some wrong or sensitive context should simply be removed.", "提供忘记", "有些错的或敏感的背景，应该可以彻底移除。", "The user wants the option to remove wrong or sensitive context.", "用户希望能移除错误或敏感的背景。"),
            o("show_source", "Show the source", "I want to know where the understanding came from.", "显示来源", "我需要知道你是从哪里得出这个理解的。", "The user wants Personal Model corrections to show source provenance.", "用户希望修正 Personal Model 时能看到理解来源。")
        ])
    ]

    private static func q(
        _ id: String,
        _ lens: OnboardingGroundingLens,
        _ enTitle: String,
        _ zhTitle: String,
        _ enReason: String,
        _ zhReason: String,
        _ topic: String,
        _ sensitivity: String,
        _ options: [OnboardingGroundingOption]
    ) -> OnboardingGroundingQuestion {
        OnboardingGroundingQuestion(
            id: id,
            lens: lens,
            title: OnboardingLocalizedCopy(en: enTitle, zh: zhTitle),
            prompt: OnboardingLocalizedCopy(en: enTitle, zh: zhTitle),
            reason: OnboardingLocalizedCopy(en: enReason, zh: zhReason),
            topic: topic,
            sensitivity: sensitivity,
            options: options
        )
    }

    private static func o(
        _ id: String,
        _ enLabel: String,
        _ enDetail: String,
        _ zhLabel: String,
        _ zhDetail: String,
        _ enFact: String,
        _ zhFact: String
    ) -> OnboardingGroundingOption {
        OnboardingGroundingOption(
            id: id,
            label: OnboardingLocalizedCopy(en: enLabel, zh: zhLabel),
            detail: OnboardingLocalizedCopy(en: enDetail, zh: zhDetail),
            fact: OnboardingLocalizedCopy(en: enFact, zh: zhFact)
        )
    }
}

@MainActor
extension ElephantAppModel {
    var onboardingGroundingDepthValue: OnboardingGroundingDepth {
        get { OnboardingGroundingDepth(rawValue: onboardingGroundingDepth) ?? .standard }
        set { onboardingGroundingDepth = newValue.rawValue }
    }

    var onboardingGroundingQuestions: [OnboardingGroundingQuestion] {
        OnboardingGroundingCatalog.questions(for: appLanguage, depth: onboardingGroundingDepthValue)
    }

    func onboardingGroundingDraft(for questionID: String) -> OnboardingGroundingAnswerDraft {
        onboardingGroundingAnswers[questionID] ?? .empty(questionID: questionID)
    }

    func onboardingGroundingQuestion(at index: Int) -> OnboardingGroundingQuestion? {
        let questions = onboardingGroundingQuestions
        guard questions.indices.contains(index) else { return nil }
        return questions[index]
    }

    func selectOnboardingGroundingDepth(_ depth: OnboardingGroundingDepth) {
        onboardingGroundingDepthValue = depth
    }

    func selectOnboardingGroundingOption(questionID: String, optionID: String) {
        var draft = onboardingGroundingDraft(for: questionID)
        draft.optionID = optionID
        draft.skipped = false
        onboardingGroundingAnswers[questionID] = draft
    }

    func updateOnboardingGroundingNote(questionID: String, note: String) {
        var draft = onboardingGroundingDraft(for: questionID)
        draft.note = note
        draft.skipped = false
        onboardingGroundingAnswers[questionID] = draft
    }

    func skipOnboardingGroundingQuestion(questionID: String) {
        var draft = onboardingGroundingDraft(for: questionID)
        draft.skipped = true
        onboardingGroundingAnswers[questionID] = draft
    }

    func onboardingGroundingAnswerRecords() -> [OnboardingGroundingAnswerRecord] {
        onboardingGroundingQuestions.compactMap { question in
            let draft = onboardingGroundingDraft(for: question.id)
            guard !draft.skipped,
                  let option = question.options.first(where: { $0.id == draft.optionID }) else {
                return nil
            }
            let note = draft.note.trimmingCharacters(in: .whitespacesAndNewlines)
            let baseFact = option.fact.text(appLanguage)
            let factText: String
            if note.isEmpty {
                factText = baseFact
            } else if appLanguage == .zh {
                factText = "\(baseFact) 用户补充：\(note)"
            } else {
                factText = "\(baseFact) User note: \(note)"
            }
            return OnboardingGroundingAnswerRecord(
                questionID: question.id,
                optionID: option.id,
                questionTitle: question.title.text(appLanguage),
                questionPrompt: question.prompt.text(appLanguage),
                optionLabel: option.label.text(appLanguage),
                optionDetail: option.detail.text(appLanguage),
                note: note,
                factText: factText,
                lens: question.lens.rawValue,
                topic: question.topic,
                sensitivity: question.sensitivity
            )
        }
    }
}
