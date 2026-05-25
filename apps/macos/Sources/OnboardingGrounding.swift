import Foundation

struct OnboardingLocalizedCopy: Equatable {
    var en: String
    var zh: String
    var fr: String?
    var de: String?

    init(en: String, zh: String, fr: String? = nil, de: String? = nil) {
        self.en = en
        self.zh = zh
        self.fr = fr
        self.de = de
    }

    func text(_ language: AppLanguage) -> String {
        switch language {
        case .zh: return zh
        case .fr: return fr ?? en
        case .de: return de ?? en
        case .en: return en
        }
    }
}

private struct GroundingLocaleText {
    var fr: String
    var de: String
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
            switch language {
            case .zh: return "约 1-3 分钟"
            case .fr: return "Environ 1 à 3 min"
            case .de: return "Ca. 1-3 Min."
            case .en: return "About 1-3 min"
            }
        case .standard:
            switch language {
            case .zh: return "约 5-10 分钟"
            case .fr: return "Environ 5 à 10 min"
            case .de: return "Ca. 5-10 Min."
            case .en: return "About 5-10 min"
            }
        case .deep:
            switch language {
            case .zh: return "约 10-15 分钟"
            case .fr: return "Environ 10 à 15 min"
            case .de: return "Ca. 10-15 Min."
            case .en: return "About 10-15 min"
            }
        }
    }

    func title(_ language: AppLanguage) -> String {
        switch self {
        case .quick:
            switch language {
            case .zh: return "轻量了解"
            case .fr: return "Compréhension rapide"
            case .de: return "Kurzes Kennenlernen"
            case .en: return "Light understanding"
            }
        case .standard:
            switch language {
            case .zh: return "标准了解"
            case .fr: return "Compréhension standard"
            case .de: return "Standard-Kennenlernen"
            case .en: return "Standard understanding"
            }
        case .deep:
            switch language {
            case .zh: return "深入了解"
            case .fr: return "Compréhension approfondie"
            case .de: return "Tieferes Kennenlernen"
            case .en: return "Deeper understanding"
            }
        }
    }

    func subtitle(_ language: AppLanguage) -> String {
        switch self {
        case .quick:
            switch language {
            case .zh: return "先知道怎么和你相处，之后再慢慢补。"
            case .fr: return "Commence par la façon dont Elephant doit interagir avec vous ; on complètera ensuite."
            case .de: return "Beginnt damit, wie Elephant mit dir umgehen soll; mehr kommt später dazu."
            case .en: return "Start with how Elephant should work with you; fill in more later."
            }
        case .standard:
            switch language {
            case .zh: return "推荐。先建立一版可用理解。"
            case .fr: return "Recommandé. Crée une première compréhension vraiment utilisable."
            case .de: return "Empfohlen. Baut ein erstes brauchbares Verständnis auf."
            case .en: return "Recommended. Build a usable first understanding."
            }
        case .deep:
            switch language {
            case .zh: return "多问几题，补上关系、价值和长期模式。"
            case .fr: return "Ajoute quelques questions sur les relations, les valeurs et les schémas de long terme."
            case .de: return "Ergänzt Beziehungen, Werte und längerfristige Muster."
            case .en: return "Adds relationships, values, and longer-running patterns."
            }
        }
    }

    func buildsText(_ language: AppLanguage) -> String {
        switch self {
        case .quick:
            switch language {
            case .zh: return "最近操心的事、合作方式、压力信号、边界"
            case .fr: return "Préoccupation actuelle, façon de collaborer, signes de pression, limites"
            case .de: return "Aktuelle Sorge, Zusammenarbeit, Drucksignal, Grenzen"
            case .en: return "Current concern, collaboration style, pressure signal, boundaries"
            }
        case .standard:
            switch language {
            case .zh: return "第一版可用理解：角色、判断、恢复、隐私和经验"
            case .fr: return "Première carte utile : rôles, jugement, récupération, vie privée et expérience"
            case .de: return "Erste nützliche Karte: Rollen, Urteilen, Erholung, Privatsphäre und Erfahrung"
            case .en: return "First useful map: roles, judgment, recovery, privacy, and experience"
            }
        case .deep:
            switch language {
            case .zh: return "更深的关系、责任、环境、分歧和转折"
            case .fr: return "Relations, responsabilités, environnement, désaccords et tournants plus profonds"
            case .de: return "Tiefere Beziehungen, Verantwortung, Umfeld, Konflikte und Wendepunkte"
            case .en: return "Deeper relationships, responsibility, environment, conflict, and turning points"
            }
        }
    }

    var questionIDs: [String] {
        switch self {
        case .quick:
            return ["current_concern", "support_first", "pressure_change", "help_pressure"]
        case .standard:
            return [
                "current_concern", "support_first", "pressure_change", "help_pressure",
                "role_now", "decision_weight", "worthwhile_work", "recovery_path",
                "privacy_default", "learned_lesson"
            ]
        case .deep:
            return [
                "current_concern", "support_first", "pressure_change", "help_pressure",
                "role_now", "decision_weight", "worthwhile_work", "recovery_path",
                "privacy_default", "learned_lesson", "unwanted_future", "environment_fit",
                "hard_responsibility", "relationship_drain", "uncertainty_need",
                "conflict_first", "turning_point", "correction_style"
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
            switch language {
            case .zh: return "你自己"
            case .fr: return "Vous"
            case .de: return "Du"
            case .en: return "You"
            }
        case .world:
            switch language {
            case .zh: return "身边处境"
            case .fr: return "Votre contexte"
            case .de: return "Dein Umfeld"
            case .en: return "Context around you"
            }
        case .pulse:
            switch language {
            case .zh: return "当前状态"
            case .fr: return "État actuel"
            case .de: return "Aktueller Zustand"
            case .en: return "Current state"
            }
        case .journey:
            switch language {
            case .zh: return "过往经历"
            case .fr: return "Expériences passées"
            case .de: return "Vergangene Erfahrungen"
            case .en: return "Past experience"
            }
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
        groundingQuestions.map(withAdditionalLocales)
    }

    private static let groundingQuestions: [OnboardingGroundingQuestion] = [
        q(
            "current_concern",
            .pulse,
            "What are you most concerned about lately?",
            "最近你最操心的是什么？",
            "This tells Elephant what you are mainly holding right now, so future help is less likely to miss the point.",
            "我先知道你现在主要在顾哪件事，后面说话才不容易跑偏。",
            "pulse.current.main_concern",
            "medium",
            [
                o("work", "A project or work", "Something concrete needs to move forward.", "一个项目或工作", "主要是工作、项目，或要推进的事。", "The user is mainly trying to move something concrete forward lately.", "用户最近主要在推进具体事情。"),
                o("relationships", "Family, partner, or friends", "People close to me are taking attention.", "家人、伴侣或朋友", "主要是身边的人和关系。", "The user is currently affected by close relationships.", "用户最近被关系牵动。"),
                o("body", "Body, sleep, or energy", "Capacity needs attention first.", "身体、睡眠或精力", "主要是身体、睡眠、精力这些底盘。", "The user currently needs to care for body and energy first.", "用户最近需要先照顾身体和能量。"),
                o("change", "A choice or change", "Something is shifting or needs a decision.", "一个选择或变化", "主要是一个选择、变化，或者过渡期。", "The user is currently in a choice, change, or transition.", "用户最近处在选择、变化或过渡里。")
            ]
        ),
        q(
            "support_first",
            .identity,
            "When you get stuck, what should Elephant do first?",
            "你卡住的时候，希望我先怎么做？",
            "Some people want the next step. Some people need to talk the situation through first.",
            "有的人想要下一步，有的人想先把事情说清楚。",
            "identity.support.first_move",
            "medium",
            [
                o("next_step", "Give me one next step", "Start with something I can do.", "直接给我一个下一步", "先给我一个能做的动作。", "The user needs direct, actionable advice when stuck.", "用户卡住时需要直接、可执行的建议。"),
                o("organize", "Help me sort it out", "Put the mess into order.", "先帮我把事情理顺", "先把事情拆开、排出顺序。", "The user needs structure and order when stuck.", "用户卡住时需要结构和顺序。"),
                o("listen", "Let me finish saying it", "Do not solve before hearing the shape of it.", "先听我把话说完", "先听完整，再开始给建议。", "The user needs to be fully understood before problem-solving.", "用户卡住时需要先被完整理解。"),
                o("question", "Ask one key question", "A good question can unlock the next move.", "问我一个关键问题", "一个问到点上的问题就够。", "The user is often helped by one precise question.", "用户容易被一个准确的问题带动。")
            ]
        ),
        q(
            "pressure_change",
            .pulse,
            "When pressure rises, what changes first?",
            "压力上来的时候，你最先会有什么变化？",
            "Elephant can notice pressure earlier, before you are already very tired.",
            "我想早点看见你的压力，不等你已经很累了才发现。",
            "pulse.pressure.first_change",
            "medium",
            [
                o("quiet", "I talk less", "I need more quiet than usual.", "不太想说话", "表达会变少，更想安静一点。", "The user reduces expression under pressure and needs quiet space.", "用户压力上来时会减少表达，需要安静空间。"),
                o("details", "I keep checking details", "My mind starts looping on details.", "开始反复想细节", "脑子会反复检查细节。", "The user tends to enter repeated checking under pressure.", "用户压力上来时容易进入反复检查。"),
                o("action", "I want to do something quickly", "Action helps ease the pressure.", "想赶紧做点什么", "想先动起来，缓解不安。", "The user uses action to ease pressure.", "用户压力上来时会用行动缓解不安。"),
                o("co_think", "I want someone to think with me", "It is easier with another mind nearby.", "想找人一起想", "一个人想会太满，需要有人一起想。", "The user needs co-thinking and company under pressure.", "用户压力上来时需要共思和陪伴。")
            ]
        ),
        q(
            "help_pressure",
            .identity,
            "What kind of help creates more pressure for you?",
            "哪种帮助会让你更有压力？",
            "This tells Elephant when to slow down or change approach.",
            "这能让我知道什么时候该慢一点，或者换一种方式。",
            "identity.boundary.help_pressure",
            "high",
            [
                o("nag", "Keep pushing me", "Too many reminders become pressure.", "一直催我", "提醒太密会变成压力。", "The user is not helped by frequent pushing or reminders.", "用户不适合被频繁催促。"),
                o("lecture", "Explain too much", "Too much reasoning can feel heavy.", "讲太多道理", "道理太多会让人更累。", "The user dislikes over-explanation or lecturing.", "用户不喜欢被过度解释或说教。"),
                o("label", "Decide too quickly what I am like", "Fast labels do not feel accurate.", "很快就判断我是什么样的人", "太快下判断会让人不舒服。", "The user dislikes being quickly labeled.", "用户不喜欢被快速贴标签。"),
                o("premature_plan", "Give a plan before asking enough", "I need the situation understood first.", "没问清楚就给方案", "还没问清楚就给方案，会让我更有压力。", "The user needs to be understood before receiving advice.", "用户需要先被理解，再听建议。")
            ]
        ),
        q(
            "role_now",
            .world,
            "What role are you carrying most lately?",
            "最近你更像在承担哪种角色？",
            "The same thing can feel very different depending on the responsibility behind it.",
            "同一件事，放在不同责任里，重量会很不一样。",
            "world.roles.current_load",
            "medium",
            [
                o("builder", "The person making things happen", "I am trying to get something off the ground.", "把事情做起来的人", "我在负责推进、落地。", "The user is carrying responsibility for moving something forward.", "用户正在承担推进和落地的责任。"),
                o("caretaker", "The person caring for people or the situation", "I need to keep someone or something steady.", "照顾别人或照看局面的人", "我在照顾人，或维持局面稳定。", "The user is carrying care or stabilizing responsibility.", "用户正在承担照顾和稳定的责任。"),
                o("learner", "The person learning something new", "I am trying to grow into a new level.", "正在学新东西的人", "我在学新东西、升级或转型。", "The user is in a learning, upgrading, or transition phase.", "用户处在学习、升级或转型期。"),
                o("many_threads", "The person holding many things at once", "Many threads need attention at the same time.", "同时管很多事的人", "很多线都在我手里。", "The user is carrying many parallel threads and divided attention.", "用户当前多线并行，心力被分散。")
            ]
        ),
        q(
            "decision_weight",
            .identity,
            "When making a decision, what matters most to you?",
            "做决定时，你最看重什么？",
            "When Elephant helps compare options, it should start from the layer you actually care about.",
            "以后帮你比较选择时，我会先看你真正关心的那一层。",
            "identity.decision.weight",
            "medium",
            [
                o("true_want", "Whether this is what I really want", "I need the choice to feel true.", "这是不是我真心想要的", "我会先看这是不是自己真的想要。", "The user values inner truth when making decisions.", "用户做决定时重视真实感。"),
                o("important_people", "How it affects important people", "The people involved matter.", "会不会影响重要的人", "重要的人也要被算进去。", "The user includes important relationships in decisions.", "用户会把重要关系纳入判断。"),
                o("risk", "Whether the risk is too high", "The base needs to hold.", "风险会不会太大", "我会先看现实风险能不能扛住。", "The user values practical stability when making decisions.", "用户做决定时重视现实稳定。"),
                o("future_options", "Whether it creates more options later", "I care about future room to move.", "以后会不会多一些选择", "我会看它会不会让以后更有空间。", "The user values future optionality.", "用户重视未来的选择空间。")
            ]
        ),
        q(
            "worthwhile_work",
            .world,
            "What kind of work is worth serious effort for you?",
            "什么样的事值得你认真投入？",
            "Elephant should understand what feels worth it to you, not just whether something is finished.",
            "我想知道你眼里的“值得”，不只是看事情有没有完成。",
            "world.work.meaning",
            "medium",
            [
                o("help_people", "It can really help people", "The impact is concrete, not just nice in theory.", "能真的帮到人", "不是概念上有用，而是真的帮到人。", "The user values concrete, real-world impact.", "用户重视具体、真实的影响。"),
                o("solid", "It needs to be done well", "Quality and craft matter.", "需要做得很扎实", "它值得认真打磨。", "The user values quality, craft, and careful work.", "用户重视质量、手艺和打磨。"),
                o("new_direction", "It can open a new direction", "It may create a longer path.", "能打开新的方向", "它会带出长期可能性。", "The user is drawn to long-term possibility.", "用户会被长期可能性吸引。"),
                o("clarity", "It can make confusion clearer", "It reduces noise or mess.", "能把混乱变清楚", "它能减少混乱，让问题更清楚。", "The user values clarifying problems and reducing confusion.", "用户重视澄清问题、减少混乱。")
            ]
        ),
        q(
            "recovery_path",
            .pulse,
            "When you are very tired, what helps you recover a little?",
            "很累的时候，什么最能帮你恢复一点？",
            "Recovery is personal. Elephant should not apply someone else's way to you.",
            "恢复方式因人而异，我不该拿别人的办法套你。",
            "pulse.recovery.path",
            "medium",
            [
                o("body", "Sleep, walk, or eat something", "The body needs a reset first.", "睡觉、走路、吃点东西", "先让身体缓回来。", "The user mainly recovers through body rhythm.", "用户主要靠身体节奏恢复。"),
                o("talk", "Talk with someone I trust", "A low-pressure conversation helps.", "和信任的人聊一会儿", "轻轻说一会儿会有帮助。", "The user recovers through low-pressure conversation.", "用户能从低压力对话里恢复。"),
                o("quiet", "Be quiet with less input", "Less stimulation helps.", "安静待着，少点输入", "不要再塞更多信息进来。", "The user needs quiet and reduced input to recover.", "用户恢复时需要安静和减少刺激。"),
                o("small_done", "Finish one tiny thing", "A small completion brings back agency.", "做完一件很小的事", "做完一点点，会重新有掌控感。", "The user regains control through tiny completions.", "用户能从小完成里找回掌控感。")
            ]
        ),
        q(
            "privacy_default",
            .identity,
            "What should Elephant mention less by default?",
            "哪些内容你希望我默认少提？",
            "Not everything remembered should be brought up later without care.",
            "不是所有记住的东西，都适合在之后的对话里主动拿出来用。",
            "identity.privacy.default_care",
            "high",
            [
                o("health", "Body and health", "Treat this with extra care.", "身体和健康", "健康相关内容默认谨慎一点。", "The user wants health information handled cautiously by default.", "用户希望健康信息默认谨慎处理。"),
                o("relationships", "Relationship details", "Do not casually reuse private relationship context.", "关系细节", "私人关系细节不要随便主动提。", "The user wants private relationship details mentioned less by default.", "用户希望私人关系细节少被主动引用。"),
                o("security", "Money, housing, or security", "Practical security context needs discretion.", "钱、住处或安全感", "现实安全相关信息更需要分寸。", "The user wants practical security context handled cautiously.", "用户希望现实安全相关信息更谨慎。"),
                o("early_ideas", "Ideas I have not figured out yet", "Do not treat early thoughts as conclusions.", "还没想清楚的想法", "还没定型的想法，不要当成结论。", "The user does not want early ideas treated as conclusions.", "用户不希望早期想法被当成结论。")
            ]
        ),
        q(
            "learned_lesson",
            .journey,
            "What is something life has taught you more than once?",
            "你反复学到过的一件事是什么？",
            "These experiences shape how you judge things now. Elephant should not treat them as a passing mood.",
            "这些经验会影响你现在怎么判断，我不该把它当成一时情绪。",
            "journey.lesson.repeated",
            "medium",
            [
                o("trust_action", "Trust depends on actions", "Good intent is not enough.", "信任要看行动", "不能只看好意，要看时间和行动。", "The user believes trust needs time and behavior.", "用户相信信任需要时间和行为。"),
                o("body_limit", "The body cannot keep pushing forever", "Long-term overuse has a cost.", "身体不能一直硬撑", "一直透支，后面会有代价。", "The user knows long-term overuse has a cost.", "用户知道长期透支会有代价。"),
                o("say_early", "Unsaid things get heavier", "It helps to name reality earlier.", "没说清的事会越来越重", "越拖到后面，越沉。", "The user values naming reality early.", "用户重视早点说清现实情况。"),
                o("small_steps", "Small steady steps help more than big plans", "Sustainable progress matters.", "小步持续比大计划有用", "小步能持续，通常比大计划更有用。", "The user believes in sustainable small steps.", "用户相信可持续的小步。")
            ]
        ),
        q(
            "unwanted_future",
            .journey,
            "What kind of life do you most want to avoid becoming?",
            "你最不想把自己过成什么样？",
            "Knowing what you do not want helps Elephant avoid pushing you toward the wrong path.",
            "知道你不想变成什么，我以后就更少把你推向那种路。",
            "journey.future.unwanted",
            "medium",
            [
                o("numb_success", "Successful on the outside, numb inside", "Success would not be worth that cost.", "看起来成功，但人很麻木", "外面看着好，但自己没感觉。", "The user does not want to trade aliveness for success.", "用户不想用麻木换成功。"),
                o("trapped_stability", "Stable but without choices", "Security should not become a trap.", "很稳定，但没有选择", "稳定如果变成困住，也不对。", "The user does not want to be trapped by stability.", "用户不想被稳定困住。"),
                o("capable_lonely", "Capable but lonely", "Ability without connection would feel empty.", "很能干，但很孤单", "只剩能力，没有真实连接。", "The user does not want ability without connection.", "用户不想只剩能力、失去连接。"),
                o("free_scattered", "Free but scattered", "Freedom still needs direction.", "很自由，但生活散掉", "有自由，但没有方向。", "The user does not want freedom without direction.", "用户不想只有自由、没有方向。")
            ]
        ),
        q(
            "environment_fit",
            .world,
            "What kind of environment helps you feel better?",
            "什么样的环境会让你状态更好？",
            "Environment affects people. Elephant should include this when giving suggestions.",
            "环境会影响人。我以后给建议时，会把这个算进去。",
            "world.environment.fit",
            "medium",
            [
                o("quiet", "Quiet, with fewer interruptions", "Low noise helps.", "安静，少干扰", "少一点打断和噪音。", "The user fits low-noise environments with fewer interruptions.", "用户适合低噪音、少打断的环境。"),
                o("warm_serious", "People are gentle but serious", "Warmth and standards both matter.", "人温和，但做事认真", "人有温度，事情也认真做。", "The user fits warm groups that still have standards.", "用户适合温暖且有标准的人群。"),
                o("clear_rules", "Clear rules", "I can relax when boundaries are clear.", "规则清楚", "边界和规则清楚，就会轻松很多。", "The user needs clear boundaries and rules.", "用户需要清楚的边界和规则。"),
                o("order_beauty", "Order and beauty", "The surroundings affect stability.", "有秩序，也有美感", "环境有秩序、有照料感，会影响状态。", "Order and beauty help the user feel stable.", "秩序和美感会帮助用户稳定。")
            ]
        ),
        q(
            "hard_responsibility",
            .world,
            "What responsibility is hardest for you to put down?",
            "哪种责任你最难放下？",
            "Elephant should understand why it is hard before simply telling you to let go.",
            "这样我不会简单劝你“别管了”，而是先理解为什么难放。",
            "world.responsibility.hard_to_release",
            "high",
            [
                o("needed", "Someone really needs me", "Need makes it hard to step back.", "别人真的需要我", "只要别人真的需要，我就很难放下。", "The user finds it hard to step back when others need them.", "用户面对他人需要时很难放手。"),
                o("promised", "I promised", "A promise carries weight.", "我答应过", "答应过的事，对我分量很重。", "Promises carry strong weight for the user.", "承诺对用户有很重的分量。"),
                o("quality", "Quality depends on me", "If I stop watching it, it may get worse.", "质量靠我守住", "我一松手，质量可能就掉下去。", "The user tends to carry responsibility for quality.", "用户容易承担质量把关责任。"),
                o("worse", "I worry it will get worse if I let go", "Unclear consequences keep me holding on.", "我怕放下后更糟", "不知道放下后会怎样，所以继续扛着。", "Unclear consequences make the user keep carrying responsibility.", "不确定后果会让用户继续承担。")
            ]
        ),
        q(
            "relationship_drain",
            .world,
            "In relationships, what drains you most easily?",
            "关系里，什么最容易消耗你？",
            "Often the tiring part is not the task itself, but the pressure inside the relationship.",
            "很多时候，累人的不是事情本身，而是关系里的压力。",
            "world.relationships.drain",
            "high",
            [
                o("unsaid", "Things I cannot say", "The unsaid part takes up space.", "有话说不出口", "真正耗人的，是有些话一直说不出来。", "Unspoken content drains the user.", "没说出口的内容会消耗用户。"),
                o("unfair", "Unfair responsibility", "It feels like I am carrying more.", "责任不公平", "明明不是我一个人的事，却像我在扛。", "Unequal responsibility drains the user.", "用户会被不对等的承担消耗。"),
                o("misread", "Being misunderstood repeatedly", "Repeating myself costs energy.", "反复被误解", "反复解释自己，会很累。", "The user is sensitive to being misread.", "用户对被误读很敏感。"),
                o("unclear_line", "Unclear boundaries", "No one knows where the line is.", "边界说不清", "界限模糊，会一直消耗。", "Unclear boundaries drain the user.", "模糊边界会消耗用户。")
            ]
        ),
        q(
            "uncertainty_need",
            .pulse,
            "When something is still uncertain, what do you need most?",
            "事情还不确定时，你最需要什么？",
            "Elephant should not pretend something is settled just to comfort you.",
            "我不会为了安慰你，假装事情已经很确定。",
            "pulse.uncertainty.need",
            "medium",
            [
                o("possibilities", "Lay out the possible cases", "I can handle uncertainty if the range is clear.", "把可能情况列清楚", "知道大概有哪些可能，就没那么慌。", "The user can handle uncertainty when the range is made clear.", "用户能承受被说明范围的不确定。"),
                o("check_later", "Set a time to look again", "I need a next checkpoint.", "约好什么时候再看", "不确定没关系，但要知道什么时候再确认。", "The user needs a clear next checkpoint.", "用户需要明确的下次确认点。"),
                o("next_action", "Do what can be done now", "A small action helps hold the uncertainty.", "先做眼前能做的事", "先做现在能做的一点。", "The user uses small action to handle uncertainty.", "用户用小行动承受不确定。"),
                o("admit_unknown", "Say directly that we do not know yet", "Honesty is better than false certainty.", "直接承认现在不知道", "不知道就说不知道。", "The user trusts honest uncertainty.", "用户更信任诚实的不确定。")
            ]
        ),
        q(
            "conflict_first",
            .identity,
            "When you disagree with someone, what do you usually do first?",
            "和人有分歧时，你通常会先怎样？",
            "When conflict or disagreement shows up later, Elephant can help in a way that fits you better.",
            "以后遇到冲突或不同意见，我会用更适合你的方式帮你。",
            "identity.conflict.first_response",
            "high",
            [
                o("facts", "Clarify the facts first", "What happened and what it means are separate.", "先弄清事实", "先确认到底发生了什么。", "The user first separates facts from interpretations in conflict.", "用户在冲突里先区分事实和理解。"),
                o("temperature", "Keep the room from escalating", "The conversation needs to stay possible.", "先让气氛别失控", "先让大家还能继续说话。", "The user first lowers emotional temperature in conflict.", "用户会先降低情绪温度。"),
                o("distance", "Step away and think", "I respond better after distance.", "先退开想清楚", "先离开一点，想清楚再回应。", "The user needs distance before responding.", "用户需要距离，再回应。"),
                o("line", "Become clear when a line is crossed", "Some boundaries make the answer obvious.", "边界被碰到时会很明确", "如果越过了线，我会很清楚。", "The user becomes clear when a boundary is crossed.", "用户边界被越过时会变得清楚。")
            ]
        ),
        q(
            "turning_point",
            .journey,
            "What kind of event has changed you most?",
            "哪类事情最改变过你？",
            "You do not need to tell the full story. Just choose the closest kind.",
            "不用讲完整故事，选最接近的一类就好。",
            "journey.turning_point.change_type",
            "high",
            [
                o("loss", "A loss or ending", "Something ended and changed me.", "一次失去或结束", "有些东西结束后，人会变。", "A loss or ending changed the user.", "失去或结束改变过用户。"),
                o("success", "A complicated success", "Getting what I wanted was not simple.", "一次复杂的成功", "得到了想要的东西，但感受很复杂。", "The complexity after success changed the user.", "成功后的复杂感改变过用户。"),
                o("care", "Having to care for someone or something", "Responsibility changed me.", "不得不承担照顾", "因为要照顾人或事，自己也变了。", "Care responsibility changed the user.", "照顾责任改变过用户。"),
                o("big_choice", "A major choice I made", "A choice changed the path.", "做过一个很大的选择", "一个大的选择改变了后面很多事。", "A major choice changed the user.", "重大选择改变过用户。")
            ]
        ),
        q(
            "correction_style",
            .identity,
            "If Elephant gets you wrong later, how should it be corrected?",
            "如果我以后理解错你，你希望怎么改？",
            "Elephant's understanding of you must be editable, not a label that gets stuck.",
            "我对你的理解必须能改，不应该变成贴上去的标签。",
            "identity.personal_model.correction_style",
            "medium",
            [
                o("edit", "Edit that memory directly", "The wrong fact should be fixable.", "直接改掉那条记忆", "哪条不对，就直接改。", "The user wants incorrect facts to be directly editable.", "用户希望错误事实能直接编辑。"),
                o("source", "Tell me how you judged that", "I want to see where it came from.", "告诉我你是怎么判断的", "我想知道你是从哪里得出的。", "The user needs to see the source of understanding.", "用户需要看到理解来源。"),
                o("ask", "Ask me what is wrong", "Correction should help you understand better.", "先问我哪里不对", "先问清楚为什么不对。", "The user wants correction to improve underlying understanding.", "用户希望修正能帮助模型真正理解。"),
                o("forget", "Forget that part", "Some things should be removed, not repaired.", "直接忘掉这部分", "有些内容直接删掉更好。", "The user wants wrong or sensitive content to be removable.", "用户希望错误或敏感内容可以删除。")
            ]
        )
    ]

    private static let customAnswerOption = OnboardingGroundingOption(
        id: "custom",
        label: OnboardingLocalizedCopy(
            en: "None fit; I will write one",
            zh: "都不太像，我自己写一句",
            fr: "Aucun ne convient ; je l'écris moi-même",
            de: "Nichts passt richtig; ich schreibe es selbst"
        ),
        detail: OnboardingLocalizedCopy(
            en: "Choose this, then add a short note below.",
            zh: "先选这个，再在下面补一句。",
            fr: "Choisissez ceci, puis ajoutez une courte note ci-dessous.",
            de: "Wähle das und ergänze unten einen kurzen Satz."
        ),
        fact: OnboardingLocalizedCopy(
            en: "The listed answers did not quite fit; the user chose to describe this in their own words.",
            zh: "这些选项都不太像，用户选择用自己的话补充。",
            fr: "Les réponses proposées ne correspondaient pas vraiment ; l'utilisateur a choisi de le décrire avec ses propres mots.",
            de: "Die vorgeschlagenen Antworten passten nicht richtig; der Nutzer hat gewählt, es in eigenen Worten zu beschreiben."
        )
    )

    private static let questionLocaleText: [String: GroundingLocaleText] = [
        "current_concern.title": GroundingLocaleText(fr: "Qu'est-ce qui vous préoccupe le plus en ce moment ?", de: "Was beschäftigt dich in letzter Zeit am meisten?"),
        "current_concern.reason": GroundingLocaleText(fr: "Je veux d'abord savoir ce que vous portez surtout en ce moment, pour éviter de répondre à côté ensuite.", de: "Ich möchte zuerst wissen, worum du dich gerade vor allem kümmerst, damit spätere Antworten weniger danebenliegen."),
        "support_first.title": GroundingLocaleText(fr: "Quand vous êtes bloqué, que dois-je faire d'abord ?", de: "Wenn du feststeckst, was soll ich zuerst tun?"),
        "support_first.reason": GroundingLocaleText(fr: "Certaines personnes veulent une prochaine étape. D'autres ont besoin de clarifier la situation d'abord.", de: "Manche möchten sofort den nächsten Schritt. Andere müssen die Sache erst sortieren."),
        "pressure_change.title": GroundingLocaleText(fr: "Quand la pression monte, qu'est-ce qui change d'abord chez vous ?", de: "Wenn der Druck steigt, was verändert sich bei dir zuerst?"),
        "pressure_change.reason": GroundingLocaleText(fr: "Je veux repérer la pression plus tôt, avant que vous soyez déjà épuisé.", de: "Ich möchte deinen Druck früher erkennen, bevor du schon sehr erschöpft bist."),
        "help_pressure.title": GroundingLocaleText(fr: "Quel type d'aide vous met davantage sous pression ?", de: "Welche Art von Hilfe setzt dich eher zusätzlich unter Druck?"),
        "help_pressure.reason": GroundingLocaleText(fr: "Cela me dit quand ralentir ou changer de manière de faire.", de: "So weiß ich, wann ich langsamer werden oder anders vorgehen sollte."),
        "role_now.title": GroundingLocaleText(fr: "Quel rôle portez-vous le plus en ce moment ?", de: "Welche Rolle trägst du in letzter Zeit am ehesten?"),
        "role_now.reason": GroundingLocaleText(fr: "La même chose peut peser très différemment selon la responsabilité derrière.", de: "Dieselbe Sache kann sich je nach Verantwortung dahinter ganz anders anfühlen."),
        "decision_weight.title": GroundingLocaleText(fr: "Quand vous décidez, qu'est-ce qui compte le plus ?", de: "Worauf achtest du bei Entscheidungen am meisten?"),
        "decision_weight.reason": GroundingLocaleText(fr: "Quand je vous aiderai à comparer des options, je partirai de la couche qui compte vraiment pour vous.", de: "Wenn ich dir später beim Vergleichen von Optionen helfe, starte ich bei der Ebene, die dir wirklich wichtig ist."),
        "worthwhile_work.title": GroundingLocaleText(fr: "Quel genre de chose mérite votre vrai engagement ?", de: "Welche Art von Aufgabe verdient deinen ernsthaften Einsatz?"),
        "worthwhile_work.reason": GroundingLocaleText(fr: "Je veux comprendre ce qui est valable pour vous, pas seulement si quelque chose est terminé.", de: "Ich möchte verstehen, was für dich lohnt, nicht nur ob etwas erledigt ist."),
        "recovery_path.title": GroundingLocaleText(fr: "Quand vous êtes très fatigué, qu'est-ce qui vous aide à récupérer un peu ?", de: "Wenn du sehr müde bist, was hilft dir, wieder etwas aufzutanken?"),
        "recovery_path.reason": GroundingLocaleText(fr: "La récupération varie selon les personnes. Je ne dois pas plaquer la méthode de quelqu'un d'autre sur vous.", de: "Erholung ist persönlich. Ich sollte dir nicht einfach die Methode anderer überstülpen."),
        "privacy_default.title": GroundingLocaleText(fr: "Quels sujets voulez-vous que je mentionne moins par défaut ?", de: "Welche Themen soll ich standardmäßig seltener ansprechen?"),
        "privacy_default.reason": GroundingLocaleText(fr: "Tout ce qui est mémorisé ne doit pas forcément être réutilisé spontanément plus tard.", de: "Nicht alles, woran ich mich erinnere, sollte später ungefragt aktiv verwendet werden."),
        "learned_lesson.title": GroundingLocaleText(fr: "Quelle chose avez-vous apprise plusieurs fois ?", de: "Was hast du immer wieder gelernt?"),
        "learned_lesson.reason": GroundingLocaleText(fr: "Ces expériences influencent vos jugements actuels. Je ne dois pas les prendre pour une émotion passagère.", de: "Solche Erfahrungen beeinflussen, wie du heute urteilst. Ich sollte das nicht als vorübergehende Stimmung behandeln."),
        "unwanted_future.title": GroundingLocaleText(fr: "Quelle vie voulez-vous surtout éviter de vivre ?", de: "Wie möchtest du auf keinen Fall werden?"),
        "unwanted_future.reason": GroundingLocaleText(fr: "Savoir ce que vous ne voulez pas devenir m'aide à moins vous pousser vers cette voie.", de: "Wenn ich weiß, was du nicht werden willst, dränge ich dich später weniger in diese Richtung."),
        "environment_fit.title": GroundingLocaleText(fr: "Quel environnement vous aide à aller mieux ?", de: "Welche Umgebung tut dir gut?"),
        "environment_fit.reason": GroundingLocaleText(fr: "L'environnement influence les gens. Je le prendrai en compte dans mes suggestions.", de: "Umgebung beeinflusst Menschen. Ich werde das bei Vorschlägen mit einbeziehen."),
        "hard_responsibility.title": GroundingLocaleText(fr: "Quelle responsabilité est la plus difficile à déposer pour vous ?", de: "Welche Verantwortung kannst du am schwersten loslassen?"),
        "hard_responsibility.reason": GroundingLocaleText(fr: "Ainsi je ne vous dirai pas simplement de laisser tomber ; je chercherai d'abord pourquoi c'est difficile.", de: "Dann sage ich nicht einfach, lass es sein, sondern verstehe erst, warum es schwer loszulassen ist."),
        "relationship_drain.title": GroundingLocaleText(fr: "Dans les relations, qu'est-ce qui vous épuise le plus facilement ?", de: "Was erschöpft dich in Beziehungen am schnellsten?"),
        "relationship_drain.reason": GroundingLocaleText(fr: "Souvent, ce qui fatigue n'est pas la tâche elle-même, mais la pression dans la relation.", de: "Oft ist nicht die Sache selbst anstrengend, sondern der Druck in der Beziehung."),
        "uncertainty_need.title": GroundingLocaleText(fr: "Quand une situation reste incertaine, de quoi avez-vous le plus besoin ?", de: "Was brauchst du am meisten, wenn etwas noch ungewiss ist?"),
        "uncertainty_need.reason": GroundingLocaleText(fr: "Je ne ferai pas semblant que tout est clair juste pour vous rassurer.", de: "Ich werde nicht so tun, als wäre etwas schon sicher, nur um dich zu beruhigen."),
        "conflict_first.title": GroundingLocaleText(fr: "Quand vous êtes en désaccord avec quelqu'un, que faites-vous d'abord en général ?", de: "Wenn du mit jemandem uneinig bist, was tust du meistens zuerst?"),
        "conflict_first.reason": GroundingLocaleText(fr: "Si un conflit ou une divergence arrive plus tard, je pourrai vous aider d'une manière plus adaptée.", de: "Wenn später Konflikte oder unterschiedliche Meinungen auftauchen, kann ich passender helfen."),
        "turning_point.title": GroundingLocaleText(fr: "Quel type d'événement vous a le plus changé ?", de: "Welche Art von Ereignis hat dich am meisten verändert?"),
        "turning_point.reason": GroundingLocaleText(fr: "Pas besoin de raconter toute l'histoire. Choisissez seulement la catégorie la plus proche.", de: "Du musst nicht die ganze Geschichte erzählen. Wähle einfach die ähnlichste Art."),
        "correction_style.title": GroundingLocaleText(fr: "Si je vous comprends mal plus tard, comment voulez-vous corriger cela ?", de: "Wenn ich dich später falsch verstehe, wie soll das korrigiert werden?"),
        "correction_style.reason": GroundingLocaleText(fr: "Ma compréhension de vous doit pouvoir être modifiée, pas devenir une étiquette collée.", de: "Mein Verständnis von dir muss änderbar sein und darf nicht zu einem festen Etikett werden.")
    ]

    private static let optionLabelLocaleText: [String: GroundingLocaleText] = [
        "current_concern.work": GroundingLocaleText(fr: "Un projet ou du travail", de: "Ein Projekt oder Arbeit"),
        "current_concern.relationships": GroundingLocaleText(fr: "Famille, partenaire ou amis", de: "Familie, Partner oder Freunde"),
        "current_concern.body": GroundingLocaleText(fr: "Corps, sommeil ou énergie", de: "Körper, Schlaf oder Energie"),
        "current_concern.change": GroundingLocaleText(fr: "Un choix ou un changement", de: "Eine Entscheidung oder Veränderung"),
        "support_first.next_step": GroundingLocaleText(fr: "Donnez-moi directement une prochaine étape", de: "Gib mir direkt einen nächsten Schritt"),
        "support_first.organize": GroundingLocaleText(fr: "Aidez-moi d'abord à mettre de l'ordre", de: "Hilf mir zuerst, es zu sortieren"),
        "support_first.listen": GroundingLocaleText(fr: "Écoutez-moi jusqu'au bout d'abord", de: "Hör mir zuerst vollständig zu"),
        "support_first.question": GroundingLocaleText(fr: "Posez-moi une question clé", de: "Stell mir eine Schlüsselfrage"),
        "pressure_change.quiet": GroundingLocaleText(fr: "Je parle moins", de: "Ich rede weniger"),
        "pressure_change.details": GroundingLocaleText(fr: "Je repasse les détails en boucle", de: "Ich gehe Details immer wieder durch"),
        "pressure_change.action": GroundingLocaleText(fr: "Je veux vite faire quelque chose", de: "Ich will schnell etwas tun"),
        "pressure_change.co_think": GroundingLocaleText(fr: "Je veux réfléchir avec quelqu'un", de: "Ich will mit jemandem zusammen nachdenken"),
        "help_pressure.nag": GroundingLocaleText(fr: "Me relancer sans cesse", de: "Mich ständig antreiben"),
        "help_pressure.lecture": GroundingLocaleText(fr: "Trop expliquer", de: "Zu viel erklären"),
        "help_pressure.label": GroundingLocaleText(fr: "Me définir trop vite", de: "Mich zu schnell einordnen"),
        "help_pressure.premature_plan": GroundingLocaleText(fr: "Proposer une solution sans avoir assez demandé", de: "Eine Lösung geben, bevor genug gefragt wurde"),
        "role_now.builder": GroundingLocaleText(fr: "La personne qui fait avancer les choses", de: "Die Person, die Dinge voranbringt"),
        "role_now.caretaker": GroundingLocaleText(fr: "La personne qui prend soin des autres ou de la situation", de: "Die Person, die andere oder die Lage stabil hält"),
        "role_now.learner": GroundingLocaleText(fr: "La personne qui apprend quelque chose de nouveau", de: "Die Person, die Neues lernt"),
        "role_now.many_threads": GroundingLocaleText(fr: "La personne qui tient beaucoup de choses à la fois", de: "Die Person, die viele Dinge gleichzeitig hält"),
        "decision_weight.true_want": GroundingLocaleText(fr: "Est-ce ce que je veux vraiment", de: "Ob ich das wirklich will"),
        "decision_weight.important_people": GroundingLocaleText(fr: "Est-ce que cela affecte des personnes importantes", de: "Ob es wichtige Menschen betrifft"),
        "decision_weight.risk": GroundingLocaleText(fr: "Le risque est-il trop grand", de: "Ob das Risiko zu groß ist"),
        "decision_weight.future_options": GroundingLocaleText(fr: "Est-ce que cela ouvre plus de choix plus tard", de: "Ob es später mehr Optionen schafft"),
        "worthwhile_work.help_people": GroundingLocaleText(fr: "Cela peut vraiment aider des gens", de: "Es kann Menschen wirklich helfen"),
        "worthwhile_work.solid": GroundingLocaleText(fr: "Cela demande un travail solide", de: "Es muss wirklich solide gemacht werden"),
        "worthwhile_work.new_direction": GroundingLocaleText(fr: "Cela peut ouvrir une nouvelle direction", de: "Es kann eine neue Richtung öffnen"),
        "worthwhile_work.clarity": GroundingLocaleText(fr: "Cela peut rendre le désordre plus clair", de: "Es kann Chaos klarer machen"),
        "recovery_path.body": GroundingLocaleText(fr: "Dormir, marcher ou manger un peu", de: "Schlafen, spazieren gehen oder etwas essen"),
        "recovery_path.talk": GroundingLocaleText(fr: "Parler un moment avec quelqu'un de confiance", de: "Kurz mit jemandem Vertrautem reden"),
        "recovery_path.quiet": GroundingLocaleText(fr: "Rester au calme, avec moins d'entrées", de: "Still sein, mit weniger Input"),
        "recovery_path.small_done": GroundingLocaleText(fr: "Terminer une toute petite chose", de: "Eine sehr kleine Sache fertig machen"),
        "privacy_default.health": GroundingLocaleText(fr: "Corps et santé", de: "Körper und Gesundheit"),
        "privacy_default.relationships": GroundingLocaleText(fr: "Détails relationnels", de: "Beziehungsdetails"),
        "privacy_default.security": GroundingLocaleText(fr: "Argent, logement ou sentiment de sécurité", de: "Geld, Wohnsituation oder Sicherheitsgefühl"),
        "privacy_default.early_ideas": GroundingLocaleText(fr: "Idées pas encore clarifiées", de: "Gedanken, die noch nicht klar sind"),
        "learned_lesson.trust_action": GroundingLocaleText(fr: "La confiance se voit dans les actes", de: "Vertrauen zeigt sich in Handlungen"),
        "learned_lesson.body_limit": GroundingLocaleText(fr: "Le corps ne peut pas tenir indéfiniment", de: "Der Körper kann nicht ewig durchhalten"),
        "learned_lesson.say_early": GroundingLocaleText(fr: "Ce qui n'est pas dit devient plus lourd", de: "Unausgesprochenes wird immer schwerer"),
        "learned_lesson.small_steps": GroundingLocaleText(fr: "De petits pas réguliers aident plus que de grands plans", de: "Kleine stetige Schritte helfen mehr als große Pläne"),
        "unwanted_future.numb_success": GroundingLocaleText(fr: "Réussir en apparence, mais être engourdi", de: "Äußerlich erfolgreich, innerlich taub"),
        "unwanted_future.trapped_stability": GroundingLocaleText(fr: "Être stable, mais sans choix", de: "Stabil, aber ohne Wahlmöglichkeiten"),
        "unwanted_future.capable_lonely": GroundingLocaleText(fr: "Être très compétent, mais seul", de: "Sehr fähig, aber einsam"),
        "unwanted_future.free_scattered": GroundingLocaleText(fr: "Être libre, mais voir la vie se disperser", de: "Frei, aber das Leben zerfällt"),
        "environment_fit.quiet": GroundingLocaleText(fr: "Calme, avec peu d'interruptions", de: "Ruhig, mit wenig Störung"),
        "environment_fit.warm_serious": GroundingLocaleText(fr: "Des gens doux, mais sérieux dans le travail", de: "Menschen sind freundlich, nehmen die Arbeit aber ernst"),
        "environment_fit.clear_rules": GroundingLocaleText(fr: "Des règles claires", de: "Klare Regeln"),
        "environment_fit.order_beauty": GroundingLocaleText(fr: "De l'ordre et aussi de la beauté", de: "Ordnung und auch Schönheit"),
        "hard_responsibility.needed": GroundingLocaleText(fr: "Quelqu'un a vraiment besoin de moi", de: "Jemand braucht mich wirklich"),
        "hard_responsibility.promised": GroundingLocaleText(fr: "J'ai promis", de: "Ich habe es versprochen"),
        "hard_responsibility.quality": GroundingLocaleText(fr: "La qualité dépend de moi", de: "Die Qualität hängt an mir"),
        "hard_responsibility.worse": GroundingLocaleText(fr: "J'ai peur que ce soit pire si je lâche", de: "Ich fürchte, es wird schlimmer, wenn ich loslasse"),
        "relationship_drain.unsaid": GroundingLocaleText(fr: "Avoir des choses que je n'arrive pas à dire", de: "Dinge, die ich nicht aussprechen kann"),
        "relationship_drain.unfair": GroundingLocaleText(fr: "Une responsabilité injuste", de: "Unfaire Verantwortung"),
        "relationship_drain.misread": GroundingLocaleText(fr: "Être mal compris à répétition", de: "Immer wieder missverstanden werden"),
        "relationship_drain.unclear_line": GroundingLocaleText(fr: "Des limites floues", de: "Unklare Grenzen"),
        "uncertainty_need.possibilities": GroundingLocaleText(fr: "Lister les situations possibles", de: "Die möglichen Fälle klar auflisten"),
        "uncertainty_need.check_later": GroundingLocaleText(fr: "Fixer un moment pour regarder à nouveau", de: "Vereinbaren, wann wir wieder draufschauen"),
        "uncertainty_need.next_action": GroundingLocaleText(fr: "Faire d'abord ce qui est possible maintenant", de: "Zuerst tun, was jetzt möglich ist"),
        "uncertainty_need.admit_unknown": GroundingLocaleText(fr: "Reconnaître directement que l'on ne sait pas encore", de: "Direkt zugeben, dass wir es gerade nicht wissen"),
        "conflict_first.facts": GroundingLocaleText(fr: "Clarifier les faits d'abord", de: "Zuerst die Fakten klären"),
        "conflict_first.temperature": GroundingLocaleText(fr: "Empêcher l'ambiance de déraper", de: "Zuerst verhindern, dass die Stimmung kippt"),
        "conflict_first.distance": GroundingLocaleText(fr: "Prendre du recul pour réfléchir", de: "Erst Abstand nehmen und nachdenken"),
        "conflict_first.line": GroundingLocaleText(fr: "Je deviens très clair quand une limite est franchie", de: "Wenn eine Grenze überschritten wird, werde ich sehr klar"),
        "turning_point.loss": GroundingLocaleText(fr: "Une perte ou une fin", de: "Ein Verlust oder Ende"),
        "turning_point.success": GroundingLocaleText(fr: "Une réussite compliquée", de: "Ein komplizierter Erfolg"),
        "turning_point.care": GroundingLocaleText(fr: "Devoir prendre soin", de: "Pflege oder Fürsorge übernehmen müssen"),
        "turning_point.big_choice": GroundingLocaleText(fr: "Avoir fait un très grand choix", de: "Eine sehr große Entscheidung getroffen haben"),
        "correction_style.edit": GroundingLocaleText(fr: "Modifier directement cette mémoire", de: "Diese Erinnerung direkt ändern"),
        "correction_style.source": GroundingLocaleText(fr: "Me dire comment vous avez jugé cela", de: "Mir sagen, wie du darauf gekommen bist"),
        "correction_style.ask": GroundingLocaleText(fr: "Me demander d'abord ce qui ne va pas", de: "Mich zuerst fragen, was daran falsch ist"),
        "correction_style.forget": GroundingLocaleText(fr: "Oublier directement cette partie", de: "Diesen Teil direkt vergessen")
    ]

    private static func withAdditionalLocales(_ question: OnboardingGroundingQuestion) -> OnboardingGroundingQuestion {
        var localizedQuestion = question
        if let title = questionLocaleText["\(question.id).title"] {
            localizedQuestion.title.fr = title.fr
            localizedQuestion.title.de = title.de
            localizedQuestion.prompt.fr = title.fr
            localizedQuestion.prompt.de = title.de
        }
        if let reason = questionLocaleText["\(question.id).reason"] {
            localizedQuestion.reason.fr = reason.fr
            localizedQuestion.reason.de = reason.de
        }
        localizedQuestion.options = question.options.map { option in
            var localizedOption = option
            if let label = optionLabelLocaleText["\(question.id).\(option.id)"] {
                localizedOption.label.fr = label.fr
                localizedOption.label.de = label.de
                localizedOption.detail.fr = label.fr
                localizedOption.detail.de = label.de
                if localizedOption.fact.fr == nil {
                    localizedOption.fact.fr = "L'utilisateur indique : \(label.fr)."
                }
                if localizedOption.fact.de == nil {
                    localizedOption.fact.de = "Der Nutzer gibt an: \(label.de)."
                }
            }
            return localizedOption
        }
        return localizedQuestion
    }

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
            options: options + [customAnswerOption]
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
