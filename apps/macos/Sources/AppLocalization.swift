import Foundation

enum AppLanguage: String, CaseIterable, Identifiable {
    case en
    case zh
    case fr
    case de

    var id: String { rawValue }

    init(code: String) {
        let normalized = code.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized.hasPrefix("zh") || normalized.contains("chinese") || normalized.contains("中文") {
            self = .zh
        } else if normalized.hasPrefix("fr") || normalized.contains("french") || normalized.contains("francais") || normalized.contains("français") {
            self = .fr
        } else if normalized.hasPrefix("de") || normalized.contains("german") || normalized.contains("deutsch") {
            self = .de
        } else {
            self = .en
        }
    }

    static var preferred: AppLanguage {
        for identifier in Locale.preferredLanguages {
            let language = AppLanguage(code: identifier)
            if AppLanguage.allCases.contains(language) {
                return language
            }
        }
        return .en
    }

    var localeIdentifier: String {
        switch self {
        case .en: return "en"
        case .zh: return "zh-Hans"
        case .fr: return "fr"
        case .de: return "de"
        }
    }

    var nativeName: String {
        switch self {
        case .en: return "English"
        case .zh: return "中文"
        case .fr: return "Français"
        case .de: return "Deutsch"
        }
    }

    var symbol: String {
        switch self {
        case .en: return "textformat"
        case .zh: return "character.book.closed"
        case .fr: return "text.quote"
        case .de: return "textformat.abc"
        }
    }

    var languageCardSubtitle: String {
        switch self {
        case .en: return "Setup and app UI use English."
        case .zh: return "初始化和系统内部使用中文。"
        case .fr: return "Onboarding et app en français."
        case .de: return "Onboarding und App auf Deutsch."
        }
    }

    var defaultEmbeddingModelSource: String {
        self == .zh ? "modelscope" : "huggingface"
    }
}

enum AppText {
    case setupTitle
    case setupSubtitle
    case back
    case next
    case continueAction
    case startSetup
    case enterElephant
    case languageTitle
    case languageSubtitle
    case languageSignalSubtitle
    case identityTitle
    case identitySubtitle
    case preferredName
    case preferredNamePlaceholder
    case gender
    case notSet
    case birthDate
    case personalLogo
    case chooseImage
    case changeImage
    case changeProfilePhoto
    case chooseAvatar
    case useDefault
    case imagePickerTitle
    case imagePickerMessage
    case imagePickerPrompt
    case female
    case male
    case nonBinary
    case workTitle
    case workSubtitle
    case currentWork
    case currentWorkPlaceholder
    case school
    case optional
    case cityTimezone
    case cityTimezonePlaceholder
    case interestsTitle
    case interestsSubtitle
    case hobbies
    case hobbiesPlaceholder
    case hobbiesSuggestionOne
    case hobbiesSuggestionTwo
    case hobbiesSuggestionThree
    case longTermDirection
    case longTermDirectionPlaceholder
    case linksTitle
    case linksSubtitle
    case blogLinkHint
    case linkedInLinkHint
    case twitterLinkHint
    case careTitle
    case careSubtitle
    case boundaries
    case boundariesPlaceholder
    case healthSafetyNote
    case healthSafetyPlaceholder
    case foodAllergies
    case medicationAllergies
    case leaveEmptyIfNone
    case surveyTitle
    case surveySubtitle
    case innerLandscapeTitle
    case valueAnchorTitle
    case pressurePatternTitle
    case recoveryStyleTitle
    case decisionCompassTitle
    case innerLandscapePrompt
    case valueAnchorPrompt
    case pressurePatternPrompt
    case recoveryStylePrompt
    case decisionCompassPrompt
    case elephantVibeTitle
    case elephantVibeSubtitle
    case elephantName
    case defaultVibe
    case defaultVibePlaceholder
    case vibeSuggestionOne
    case vibeSuggestionTwo
    case vibeSuggestionThree
    case providerTitle
    case providerSubtitle
    case providerFactory
    case providerFactorySubtitle
    case providerSearchPlaceholder
    case modelSection
    case activeModelSubtitle
    case modelPickerSubtitle
    case fetching
    case fetch
    case modelID
    case modelList
    case selectModel
    case customModelID
    case endpointTitle
    case endpointSubtitle
    case contextWindowTokens
    case apiKey
    case apiKeyPlaceholder
    case providerReady
    case providerNeedsDetails
    case learningTitle
    case learningPreparing
    case learningCreateModel
    case learningOpenEpisode
    case learningStartReflect
    case learningFromAnswers
    case learningFinishing
    case learningReady
    case learningNeedsAttention
    case tryAgain
    case celebrationTitle
    case celebrationSubtitle
    case settingsTitle
    case settingsSubtitle
    case restartCore
    case languageSettingsTitle
    case languageSettingsSubtitle
    case languageSettingsDescription
    case runtimeConfig
    case runtimeConfigMissing
    case curiosity
    case curiositySubtitle
    case history
    case sleepDisplay
    case sleepBrandTitle
    case sleepBrandSlogan
    case sleepLockTitle
    case sleepLockSubtitle
    case sleepPasswordPlaceholder
    case sleepUnlock
    case sleepPasswordWrong
    case sleepNoPassword
    case sleepPasswordRequired
    case sleepAutoSleep
    case sleepWake
    case enterSleepDisplay
    case resetSleepTimer
    case lockPasswordTitle
    case lockPasswordSubtitle
    case lockPassword
    case lockPasswordConfirm
    case lockPasswordRequirement
    case lockPasswordMismatch
    case lockPasswordSet
    case resetLockPassword
    case clearLockPassword
    case lockPasswordSaved
    case lockPasswordCleared
    case toggleSidebar
    case elephantMenu
    case menuNavigate
    case menuActions
    case revealDatabase
    case sleepDisplaySubtitle
    case logsDiagnostics
    case logsDiagnosticsSubtitle
    case resetData
    case resetDataSubtitle
    case advancedRuntime
    case lastError
    case providerSetupNeeded
    case notConfigured
    case refresh
    case reflect
    case reflecting
    case newChat
    case conversationOpen
    case threads
    case conversationHistory
    case ready
    case startAnotherConversation
    case conversation
    case deleteConversation
    case deleteConversationPrompt
    case deleteConversationMessage
    case noSavedChatsYet
    case showChatHistory
    case hideChatHistory
    case questionsShort
    case evidenceShort
    case newConversation
    case stopVoiceInput
    case voiceInput
    case typeMessagePlaceholder
    case send
    case providerSetup
    case askElephant
    case chatEmptySubtitle
    case quickCapture
    case quickThink
    case quickReview
    case quickCaptureDraft
    case quickThinkDraft
    case quickReviewDraft
    case toolActivity
    case live
    case toolInput
    case toolResult
    case showToolDetails
    case hideToolDetails
    case assistantThinking
    case toolFallback
    case toolDone
    case noRenderedMessagesYet
    case liveConnectionEnded
    case liveConnectionStopped
    case chatLoopFailureGeneric
    case chatLoopFailureDetail
    case untitledChat
    case youPageSubtitle
    case diaryPageSubtitle
    case writeDiary
    case writing
    case skillsPageSubtitle
    case toolsPageSubtitle
    case messagingPageSubtitle
    case herdPageSubtitle
    case newElephant
    case usagePageSubtitle
    case calendarPageSubtitle
    case learnPageSubtitle
    case learning
    case runLearn
    case homeReadinessModel
    case homeReadinessMemory
    case homeReadinessMessaging
    case homeReadinessLearn
    case chooseModel
    case memorySummaryFormat
    case messagingSummaryFormat
    case activeJobsFormat
    case statusSetup
    case statusConfigured
    case statusLive
    case statusRunning
    case statusWarming
    case statusUnknown
    case statusStopped
    case homeHeroTitle
    case homeHeroSubtitle
    case reviewedFactsLabel
    case questionsWaitingLabel
    case evidencePointsLabel
    case reviewQuestions
    case personalModelMapTitle
    case homeMapSubtitle
    case mapNodeCountFormat
    case mapClickHint
    case homeReadySubtitle
    case homeSetupSubtitle
    case connectedToElephant
    case readyForFirstChat
    case warmingModel
    case startingElephant
    case needsAttention
    case idle
    case phaseLanguage
    case phaseProfile
    case phasePattern
    case phaseElephant
    case phaseModel
    case phaseReady
    case phaseProgressLabel
    case phaseStatusComplete
    case phaseStatusCurrent
    case phaseStatusUpcoming
    case phaseJumpHint
    case phaseLockedHint
    case requirementPreferredName
    case requirementSurveyChoice
    case requirementElephantIdentity
    case requirementProviderDetails
    case sectionHome
    case sectionChat
    case sectionYou
    case sectionDiary
    case sectionSkills
    case sectionTools
    case sectionMessaging
    case sectionHerd
    case sectionUsage
    case sectionCalendar
    case sectionLearn
    case sectionProvider
    case sectionSettings
    case subtitleToday
    case subtitleTalk
    case subtitleModel
    case subtitleJournal
    case subtitleAffinity
    case subtitleActions
    case subtitleIM
    case subtitleElephants
    case subtitleTokens
    case subtitleReminders
    case subtitleReflect
    case subtitleSystem
    case chatReady
    case newConversationReady
    case resetChatReady
    case resetComplete

    func text(_ language: AppLanguage) -> String {
        switch self {
        case .setupTitle:
            return pick(language, en: "Set Up Elephant Agent", zh: "设置 Elephant Agent", fr: "Configurer Elephant Agent", de: "Elephant Agent einrichten")
        case .setupSubtitle:
            return pick(language, en: "Build your local Personal Model one focused step at a time.", zh: "一步一步建立你的本地 Personal Model。", fr: "Construisez votre Personal Model local, étape par étape.", de: "Baue dein lokales Personal Model Schritt für Schritt auf.")
        case .back:
            return pick(language, en: "Back", zh: "返回", fr: "Retour", de: "Zurück")
        case .next:
            return pick(language, en: "Next", zh: "下一步", fr: "Suivant", de: "Weiter")
        case .continueAction:
            return pick(language, en: "Continue", zh: "继续", fr: "Continuer", de: "Fortfahren")
        case .startSetup:
            return pick(language, en: "Start Setup", zh: "开始初始化", fr: "Lancer la configuration", de: "Einrichtung starten")
        case .enterElephant:
            return pick(language, en: "Enter Elephant Agent", zh: "进入 Elephant Agent", fr: "Entrer dans Elephant Agent", de: "Elephant Agent öffnen")
        case .languageTitle:
            return pick(language, en: "Choose your language", zh: "选择语言", fr: "Choisissez votre langue", de: "Sprache auswählen")
        case .languageSubtitle:
            return pick(language, en: "Pick the language Elephant should use during setup and inside the app.", zh: "选择 Elephant 在初始化和系统内部使用的语言。", fr: "Choisissez la langue utilisée par Elephant pendant l'initialisation et dans l'app.", de: "Wähle die Sprache für Einrichtung und App.")
        case .languageSignalSubtitle:
            return pick(language, en: "Elephant starts in English", zh: "Elephant 会用中文陪你开始", fr: "Elephant commence en français", de: "Elephant startet auf Deutsch")
        case .identityTitle:
            return pick(language, en: "Your Profile", zh: "你的身份", fr: "Votre profil", de: "Dein Profil")
        case .identitySubtitle:
            return pick(language, en: "Only collect stable identity anchors that become Personal Model facts.", zh: "只收集会进入 Personal Model 的稳定身份锚点。", fr: "Nous ne collectons que les repères stables qui deviennent des facts du Personal Model.", de: "Wir erfassen nur stabile Identitätsanker, die zu Personal-Model-Facts werden.")
        case .preferredName:
            return pick(language, en: "Preferred name", zh: "你的称呼", fr: "Nom d'usage", de: "Anrede")
        case .preferredNamePlaceholder:
            return pick(language, en: "What should Elephant call you?", zh: "Elephant 应该怎么称呼你？", fr: "Comment Elephant doit-il vous appeler ?", de: "Wie soll Elephant dich nennen?")
        case .gender:
            return pick(language, en: "Gender", zh: "性别", fr: "Genre", de: "Geschlecht")
        case .notSet:
            return pick(language, en: "Not set", zh: "不填写", fr: "Non renseigné", de: "Nicht gesetzt")
        case .birthDate:
            return pick(language, en: "Birth date", zh: "生日", fr: "Date de naissance", de: "Geburtsdatum")
        case .personalLogo:
            return pick(language, en: "Personal Logo", zh: "个人 Logo", fr: "Logo personnel", de: "Persönliches Logo")
        case .chooseImage:
            return pick(language, en: "Choose image", zh: "选择图片", fr: "Choisir une image", de: "Bild wählen")
        case .changeImage:
            return pick(language, en: "Change image", zh: "更换图片", fr: "Changer l'image", de: "Bild ändern")
        case .changeProfilePhoto:
            return pick(language, en: "Change profile photo", zh: "更换个人照片", fr: "Changer la photo de profil", de: "Profilfoto ändern")
        case .chooseAvatar:
            return pick(language, en: "Choose avatar", zh: "选择头像", fr: "Choisir un avatar", de: "Avatar wählen")
        case .useDefault:
            return pick(language, en: "Use default", zh: "使用默认", fr: "Utiliser par défaut", de: "Standard verwenden")
        case .imagePickerTitle:
            return pick(language, en: "Choose your photo", zh: "选择你的照片", fr: "Choisir votre photo", de: "Dein Foto wählen")
        case .imagePickerMessage:
            return pick(language, en: "Pick a local image for your Elephant Agent profile.", zh: "选择一张本地图片作为你的 Elephant Agent 个人照片。", fr: "Choisissez une image locale pour votre profil Elephant Agent.", de: "Wähle ein lokales Bild für dein Elephant-Agent-Profil.")
        case .imagePickerPrompt:
            return pick(language, en: "Use Photo", zh: "使用照片", fr: "Utiliser la photo", de: "Foto verwenden")
        case .female:
            return pick(language, en: "Female", zh: "女", fr: "Femme", de: "Frau")
        case .male:
            return pick(language, en: "Male", zh: "男", fr: "Homme", de: "Mann")
        case .nonBinary:
            return pick(language, en: "Non-binary", zh: "非二元", fr: "Non binaire", de: "Nichtbinär")
        case .workTitle:
            return pick(language, en: "Where You Are Now", zh: "你现在所在的位置", fr: "Où vous en êtes", de: "Wo du gerade stehst")
        case .workSubtitle:
            return pick(language, en: "Give Elephant your current work thread, organization, and timezone.", zh: "告诉 Elephant 你当前的主线、组织和时区。", fr: "Donnez à Elephant votre fil de travail, votre organisation et votre fuseau horaire.", de: "Gib Elephant deinen aktuellen Arbeitsfokus, deine Organisation und Zeitzone.")
        case .currentWork:
            return pick(language, en: "Current work", zh: "当前主线/工作", fr: "Travail actuel", de: "Aktuelle Arbeit")
        case .currentWorkPlaceholder:
            return pick(language, en: "Current attention or work thread", zh: "最近主要投入的事情", fr: "Sujet ou fil de travail actuel", de: "Aktueller Fokus oder Arbeitsstrang")
        case .school:
            return pick(language, en: "School or organization", zh: "学校/组织", fr: "École ou organisation", de: "Schule oder Organisation")
        case .optional:
            return pick(language, en: "Optional", zh: "可选", fr: "Optionnel", de: "Optional")
        case .cityTimezone:
            return pick(language, en: "City or timezone", zh: "城市/时区", fr: "Ville ou fuseau horaire", de: "Stadt oder Zeitzone")
        case .cityTimezonePlaceholder:
            return pick(language, en: "City or timezone", zh: "例如：上海 / Asia/Shanghai", fr: "Ville ou fuseau horaire", de: "Stadt oder Zeitzone")
        case .interestsTitle:
            return pick(language, en: "Interests and Direction", zh: "兴趣和长期方向", fr: "Centres d'intérêt et direction", de: "Interessen und Richtung")
        case .interestsSubtitle:
            return pick(language, en: "Write only interests and directions worth remembering long term.", zh: "只写值得长期记住的兴趣和方向。", fr: "Notez seulement ce qui mérite d'être retenu sur le long terme.", de: "Notiere nur Interessen und Richtungen, die langfristig wichtig sind.")
        case .hobbies:
            return pick(language, en: "Hobbies", zh: "兴趣爱好", fr: "Centres d'intérêt", de: "Interessen")
        case .hobbiesPlaceholder:
            return pick(language, en: "Choose one or more", zh: "选择一个或多个", fr: "Choisissez-en un ou plusieurs", de: "Eins oder mehrere wählen")
        case .hobbiesSuggestionOne:
            return pick(language, en: "Writing, design, AI", zh: "写作, 设计, AI", fr: "Écriture, design, IA", de: "Schreiben, Design, KI")
        case .hobbiesSuggestionTwo:
            return pick(language, en: "Reading, podcasts, walking", zh: "阅读, 播客, 散步", fr: "Lecture, podcasts, marche", de: "Lesen, Podcasts, Spaziergänge")
        case .hobbiesSuggestionThree:
            return pick(language, en: "Research, product, music", zh: "研究, 产品, 音乐", fr: "Recherche, produit, musique", de: "Forschung, Produkt, Musik")
        case .longTermDirection:
            return pick(language, en: "Long-term direction", zh: "长期愿望", fr: "Direction à long terme", de: "Langfristige Richtung")
        case .longTermDirectionPlaceholder:
            return pick(language, en: "A direction you want Elephant to remember", zh: "你希望 Elephant 长期记住的方向", fr: "Une direction qu'Elephant doit retenir", de: "Eine Richtung, die Elephant behalten soll")
        case .linksTitle:
            return pick(language, en: "Public Links", zh: "公开链接", fr: "Liens publics", de: "Öffentliche Links")
        case .linksSubtitle:
            return pick(language, en: "If provided, init learn can inspect these with web/browser tools for Personal Model clues.", zh: "如果你提供链接，init learn 会用 web/browser 工具读取并提取有助于 Personal Model 的信息。", fr: "Si vous les fournissez, init learn peut les lire avec des outils web/browser pour enrichir le Personal Model.", de: "Wenn du Links angibst, kann init learn sie mit Web/Browser-Tools für das Personal Model auswerten.")
        case .blogLinkHint:
            return pick(language, en: "Long-form writing and projects", zh: "长文、作品和项目", fr: "Écrits longs et projets", de: "Längere Texte und Projekte")
        case .linkedInLinkHint:
            return pick(language, en: "Professional context", zh: "职业背景和公开身份", fr: "Contexte professionnel", de: "Beruflicher Kontext")
        case .twitterLinkHint:
            return pick(language, en: "Recent public interests", zh: "近期公开兴趣和表达", fr: "Intérêts publics récents", de: "Aktuelle öffentliche Interessen")
        case .careTitle:
            return pick(language, en: "Care and Boundaries", zh: "照护和边界", fr: "Soin et limites", de: "Fürsorge und Grenzen")
        case .careSubtitle:
            return pick(language, en: "Only record safety, care, or boundary information that changes behavior.", zh: "只记录会影响安全、照护或避雷的信息。", fr: "Ne notez que les informations de sécurité, de soin ou de limites qui changent le comportement.", de: "Erfasse nur Sicherheits-, Fürsorge- oder Grenzinfos, die Verhalten verändern.")
        case .boundaries:
            return pick(language, en: "Boundaries", zh: "边界", fr: "Limites", de: "Grenzen")
        case .boundariesPlaceholder:
            return pick(language, en: "Topics or behaviors to avoid", zh: "哪些话题或行为需要避免？", fr: "Sujets ou comportements à éviter", de: "Themen oder Verhalten, die vermieden werden sollen")
        case .healthSafetyNote:
            return pick(language, en: "Health and safety note", zh: "健康/安全备注", fr: "Note santé/sécurité", de: "Gesundheits- und Sicherheitsnotiz")
        case .healthSafetyPlaceholder:
            return pick(language, en: "Sensitive boundaries or conditions", zh: "敏感边界、慢性状况等", fr: "Limites sensibles ou situations médicales", de: "Sensible Grenzen oder Bedingungen")
        case .foodAllergies:
            return pick(language, en: "Food allergies", zh: "食物过敏", fr: "Allergies alimentaires", de: "Lebensmittelallergien")
        case .medicationAllergies:
            return pick(language, en: "Medication allergies", zh: "药物过敏", fr: "Allergies médicamenteuses", de: "Medikamentenallergien")
        case .leaveEmptyIfNone:
            return pick(language, en: "Leave empty if none", zh: "没有可留空", fr: "Laisser vide si aucune", de: "Leer lassen, falls keine")
        case .surveyTitle:
            return pick(language, en: "Personal Model Survey", zh: "个人模型问卷", fr: "Questionnaire Personal Model", de: "Personal-Model-Fragebogen")
        case .surveySubtitle:
            return pick(language, en: "Choose the closest answer. You can revise it later.", zh: "选择最接近的一项。后续可以随时修正。", fr: "Choisissez la réponse la plus proche. Vous pourrez la corriger plus tard.", de: "Wähle die passendste Antwort. Du kannst sie später ändern.")
        case .innerLandscapeTitle:
            return pick(language, en: "Recent inner weather", zh: "最近的内在天气", fr: "Météo intérieure récente", de: "Jüngeres inneres Wetter")
        case .valueAnchorTitle:
            return pick(language, en: "Trade-off anchor", zh: "取舍时的锚点", fr: "Ancre de choix", de: "Anker bei Abwägungen")
        case .pressurePatternTitle:
            return pick(language, en: "Pressure pattern", zh: "压力模式", fr: "Mode sous pression", de: "Druckmuster")
        case .recoveryStyleTitle:
            return pick(language, en: "Recovery style", zh: "恢复方式", fr: "Style de récupération", de: "Erholungsstil")
        case .decisionCompassTitle:
            return pick(language, en: "Decision compass", zh: "决策指南针", fr: "Boussole de décision", de: "Entscheidungskompass")
        case .innerLandscapePrompt:
            return pick(language, en: "If your recent inner state were an image, what would it look like?", zh: "如果最近的内心状态是一张图，它更像什么？", fr: "Si votre état intérieur récent était une image, à quoi ressemblerait-il ?", de: "Wenn dein innerer Zustand ein Bild wäre, wie sähe es aus?")
        case .valueAnchorPrompt:
            return pick(language, en: "When you make trade-offs lately, what are you protecting most?", zh: "最近做取舍时，你最想保护什么？", fr: "Dans vos arbitrages récents, que protégez-vous le plus ?", de: "Was schützt du zuletzt bei Abwägungen am meisten?")
        case .pressurePatternPrompt:
            return pick(language, en: "When pressure rises, what usually appears first?", zh: "压力上来时，你通常先出现什么反应？", fr: "Quand la pression monte, qu'est-ce qui apparaît d'abord ?", de: "Was zeigt sich bei Druck meistens zuerst?")
        case .recoveryStylePrompt:
            return pick(language, en: "What most reliably helps you recover?", zh: "你最常靠什么恢复状态？", fr: "Qu'est-ce qui vous aide le plus sûrement à récupérer ?", de: "Was hilft dir am zuverlässigsten, dich zu erholen?")
        case .decisionCompassPrompt:
            return pick(language, en: "What signal tells you a choice is worth it?", zh: "一个选择是否值得，你最看重哪种信号？", fr: "Quel signal vous dit qu'un choix en vaut la peine ?", de: "Welches Signal zeigt dir, dass eine Wahl es wert ist?")
        case .elephantVibeTitle:
            return pick(language, en: "Elephant Vibe", zh: "Elephant 的性格", fr: "Style d'Elephant", de: "Elephant-Vibe")
        case .elephantVibeSubtitle:
            return pick(language, en: "This only sets the agent identity and renders into ELEPHANT.md.", zh: "这一步只设置 agent 本身，会渲染成 ELEPHANT.md。", fr: "Cette étape règle seulement l'identité de l'agent et se rend dans ELEPHANT.md.", de: "Dieser Schritt setzt nur die Agent-Identität und rendert sie in ELEPHANT.md.")
        case .elephantName:
            return pick(language, en: "Elephant name", zh: "Elephant 名字", fr: "Nom d'Elephant", de: "Elephant-Name")
        case .defaultVibe:
            return pick(language, en: "Default vibe", zh: "默认 vibe", fr: "Style par défaut", de: "Standard-Vibe")
        case .defaultVibePlaceholder:
            return pick(language, en: "How should it show up by default?", zh: "它默认应该如何陪伴、判断和表达？", fr: "Comment doit-il vous accompagner par défaut ?", de: "Wie soll es standardmäßig auftreten?")
        case .vibeSuggestionOne:
            return pick(language, en: "Warm, precise, direct", zh: "温暖、精准、直接", fr: "Chaleureux, précis, direct", de: "Warm, präzise, direkt")
        case .vibeSuggestionTwo:
            return pick(language, en: "Quiet, long-term, reliable", zh: "安静、长期、可靠", fr: "Calme, durable, fiable", de: "Ruhig, langfristig, verlässlich")
        case .vibeSuggestionThree:
            return pick(language, en: "Curious, questioning, concise", zh: "好奇、会追问、少废话", fr: "Curieux, questionnant, concis", de: "Neugierig, nachfragend, knapp")
        case .providerTitle:
            return pick(language, en: "Model Provider", zh: "模型服务", fr: "Provider de modèle", de: "Modell-Provider")
        case .providerSubtitle:
            return pick(language, en: "Uses the same provider catalog and model picker as Settings.", zh: "这里和设置里使用同一套模型服务与模型列表。", fr: "Utilise le même catalogue de providers et le même choix de modèle que Settings.", de: "Nutzt denselben Provider-Katalog und Modellwähler wie Settings.")
        case .providerFactory:
            return pick(language, en: "Provider factory", zh: "模型服务", fr: "Catalogue provider", de: "Provider-Katalog")
        case .providerFactorySubtitle:
            return pick(language, en: "providers · connected first", zh: "个服务 · 已连接优先", fr: "providers · connectés d'abord", de: "Provider · verbundene zuerst")
        case .providerSearchPlaceholder:
            return pick(language, en: "Search provider, model, or source", zh: "搜索服务、模型或来源", fr: "Rechercher provider, modèle ou source", de: "Provider, Modell oder Quelle suchen")
        case .modelSection:
            return pick(language, en: "Model", zh: "模型", fr: "Modèle", de: "Modell")
        case .activeModelSubtitle:
            return pick(language, en: "Active model for the current provider", zh: "当前正在使用的模型", fr: "Modèle actif pour le provider actuel", de: "Aktives Modell für den aktuellen Provider")
        case .modelPickerSubtitle:
            return pick(language, en: "Choose a catalog hint, live-discovered model, or custom ID.", zh: "从推荐模型、在线拉取的模型里选，也可以手动填写模型 ID。", fr: "Choisissez un indice du catalogue, un modèle découvert en direct ou un ID personnalisé.", de: "Wähle Kataloghinweis, live gefundenes Modell oder eigene ID.")
        case .fetching:
            return pick(language, en: "Fetching", zh: "正在获取", fr: "Chargement", de: "Lädt")
        case .fetch:
            return pick(language, en: "Fetch", zh: "获取", fr: "Charger", de: "Laden")
        case .modelID:
            return pick(language, en: "Model ID", zh: "模型 ID", fr: "ID du modèle", de: "Modell-ID")
        case .modelList:
            return pick(language, en: "Model list", zh: "模型列表", fr: "Liste des modèles", de: "Modellliste")
        case .selectModel:
            return pick(language, en: "Select model", zh: "选择模型", fr: "Choisir un modèle", de: "Modell wählen")
        case .customModelID:
            return pick(language, en: "Custom model ID", zh: "自定义模型 ID", fr: "ID de modèle personnalisé", de: "Eigene Modell-ID")
        case .endpointTitle:
            return pick(language, en: "Endpoint and Credentials", zh: "接口与凭证", fr: "Endpoint et identifiants", de: "Endpoint und Zugangsdaten")
        case .endpointSubtitle:
            return pick(language, en: "Matches the Model Provider settings inside the app.", zh: "和应用设置里的模型服务配置一致。", fr: "Correspond aux réglages Model Provider dans l'app.", de: "Entspricht den Model-Provider-Einstellungen in der App.")
        case .contextWindowTokens:
            return pick(language, en: "Context window tokens", zh: "上下文窗口", fr: "Tokens de fenêtre de contexte", de: "Kontextfenster-Tokens")
        case .apiKey:
            return pick(language, en: "API key or token", zh: "API Key 或 Token", fr: "Clé API ou token", de: "API-Key oder Token")
        case .apiKeyPlaceholder:
            return pick(language, en: "Leave empty to reuse existing configuration", zh: "可留空以复用已有配置", fr: "Laisser vide pour réutiliser la configuration existante", de: "Leer lassen, um bestehende Konfiguration zu verwenden")
        case .providerReady:
            return pick(language, en: "Provider details are ready.", zh: "模型服务已经配置好，可以继续。", fr: "Les informations du provider sont prêtes.", de: "Provider-Daten sind bereit.")
        case .providerNeedsDetails:
            return pick(language, en: "Provider and model ID are required; OpenAI Compatible also needs Base URL unless reusing an existing setup.", zh: "请选择模型服务并填写模型 ID；OpenAI Compatible 通常还需要 Base URL，除非复用已有配置。", fr: "Provider et ID de modèle sont requis ; OpenAI Compatible nécessite aussi une Base URL sauf si vous réutilisez une configuration.", de: "Provider und Modell-ID sind erforderlich; OpenAI Compatible braucht zusätzlich eine Base URL, außer du nutzt eine bestehende Konfiguration.")
        case .learningTitle:
            return pick(language, en: "Building Your Elephant", zh: "正在建立你的 Elephant", fr: "Construction de votre Elephant", de: "Dein Elephant wird aufgebaut")
        case .learningPreparing:
            return pick(language, en: "Preparing the init learning pass", zh: "准备初始化学习任务", fr: "Préparation du premier apprentissage", de: "Initialen Lernlauf vorbereiten")
        case .learningCreateModel:
            return pick(language, en: "Creating your local Personal Model", zh: "正在创建你的本地 Personal Model", fr: "Création de votre Personal Model local", de: "Dein lokales Personal Model wird erstellt")
        case .learningOpenEpisode:
            return pick(language, en: "Opening the first local episode", zh: "正在打开第一个本地 episode", fr: "Ouverture du premier épisode local", de: "Erste lokale Episode öffnen")
        case .learningStartReflect:
            return pick(language, en: "Starting the first learning pass", zh: "正在启动第一次学习", fr: "Lancement du premier apprentissage", de: "Ersten Lernlauf starten")
        case .learningFromAnswers:
            return pick(language, en: "Building your Personal Model. Please wait...", zh: "正在构建你的个人模型，请耐心等待...", fr: "Construction de votre Personal Model. Merci de patienter...", de: "Dein Personal Model wird aufgebaut. Bitte warten...")
        case .learningFinishing:
            return pick(language, en: "Building your Personal Model. Please wait...", zh: "正在构建你的个人模型，请耐心等待...", fr: "Construction de votre Personal Model. Merci de patienter...", de: "Dein Personal Model wird aufgebaut. Bitte warten...")
        case .learningReady:
            return pick(language, en: "Everything is ready", zh: "全部准备好了", fr: "Tout est prêt", de: "Alles ist bereit")
        case .learningNeedsAttention:
            return pick(language, en: "Setup needs attention", zh: "初始化需要处理", fr: "La configuration demande votre attention", de: "Einrichtung braucht Aufmerksamkeit")
        case .tryAgain:
            return pick(language, en: "Try Again", zh: "重试", fr: "Réessayer", de: "Erneut versuchen")
        case .celebrationTitle:
            return pick(language, en: "Everything Is Ready", zh: "全部准备好了", fr: "Tout est prêt", de: "Alles ist bereit")
        case .celebrationSubtitle:
            return pick(language, en: "Your profile, social links, survey answers, and first init learning pass are now in the local Elephant Agent.", zh: "你的个人资料、social links、问卷答案和第一次 init learning 已进入本地 Elephant Agent。", fr: "Votre profil, vos liens sociaux, vos réponses et le premier apprentissage sont dans Elephant Agent local.", de: "Dein Profil, deine Social Links, Antworten und der erste Lernlauf sind jetzt im lokalen Elephant Agent.")
        case .settingsTitle:
            return pick(language, en: "Settings", zh: "设置", fr: "Réglages", de: "Einstellungen")
        case .settingsSubtitle:
            return pick(language, en: "Shape the parts you feel every day.", zh: "把每天会用到的部分调成顺手、安心、像你。", fr: "Ajustez ce que vous utilisez chaque jour.", de: "Stimme ab, was du jeden Tag spürst.")
        case .restartCore:
            return pick(language, en: "Restart Core", zh: "重启 Core", fr: "Redémarrer le core", de: "Core neu starten")
        case .languageSettingsTitle:
            return pick(language, en: "Language", zh: "语言", fr: "Langue", de: "Sprache")
        case .languageSettingsSubtitle:
            return pick(language, en: "App language: ", zh: "当前语言：", fr: "Langue de l'app : ", de: "App-Sprache: ")
        case .languageSettingsDescription:
            return pick(language, en: "Elephant will speak this language across setup, navigation, settings, and system messages.", zh: "初始化、导航、设置和系统提示都会使用这门语言。", fr: "Elephant utilisera cette langue dans la configuration, la navigation, les réglages et les messages système.", de: "Elephant verwendet diese Sprache für Einrichtung, Navigation, Einstellungen und Systemmeldungen.")
        case .runtimeConfig:
            return pick(language, en: "System Config", zh: "系统配置", fr: "Configuration système", de: "Systemkonfiguration")
        case .runtimeConfigMissing:
            return pick(language, en: "global config not resolved", zh: "global config 尚未解析", fr: "configuration globale non résolue", de: "globale Konfiguration nicht aufgelöst")
        case .curiosity:
            return pick(language, en: "Curiosity", zh: "好奇心", fr: "Curiosité", de: "Neugier")
        case .curiositySubtitle:
            return pick(language, en: "open Personal Model questions", zh: "个待回答 Personal Model 问题", fr: "questions Personal Model ouvertes", de: "offene Personal-Model-Fragen")
        case .history:
            return pick(language, en: "History", zh: "历史", fr: "Historique", de: "Verlauf")
        case .sleepDisplay:
            return pick(language, en: "Sleep Display", zh: "睡眠显示", fr: "Affichage veille", de: "Schlafanzeige")
        case .sleepBrandTitle:
            return "Elephant Agent"
        case .sleepBrandSlogan:
            return pick(
                language,
                en: "Understand you first, then evolve with you.",
                zh: "先懂你，再陪你一起进化。",
                fr: "Vous comprendre d'abord, puis évoluer avec vous.",
                de: "Erst dich verstehen, dann mit dir wachsen."
            )
        case .sleepLockTitle:
            return pick(language, en: "Welcome back", zh: "欢迎回来", fr: "Bon retour", de: "Willkommen zurück")
        case .sleepLockSubtitle:
            return pick(language, en: "Enter your Elephant password to return.", zh: "输入 Elephant 密码后继续。", fr: "Entrez votre mot de passe Elephant pour continuer.", de: "Gib dein Elephant-Passwort ein, um fortzufahren.")
        case .sleepPasswordPlaceholder:
            return pick(language, en: "Password", zh: "密码", fr: "Mot de passe", de: "Passwort")
        case .sleepUnlock:
            return pick(language, en: "Unlock", zh: "解锁", fr: "Déverrouiller", de: "Entsperren")
        case .sleepPasswordWrong:
            return pick(language, en: "That password does not match.", zh: "密码不匹配。", fr: "Ce mot de passe ne correspond pas.", de: "Das Passwort stimmt nicht.")
        case .sleepNoPassword:
            return pick(language, en: "No lock password is set.", zh: "还没有设置锁屏密码。", fr: "Aucun mot de passe de verrouillage n'est défini.", de: "Kein Sperrpasswort gesetzt.")
        case .sleepPasswordRequired:
            return pick(language, en: "Password required", zh: "需要密码", fr: "Mot de passe requis", de: "Passwort erforderlich")
        case .sleepAutoSleep:
            return pick(language, en: "Auto sleep", zh: "自动熄屏", fr: "Veille automatique", de: "Automatischer Ruhezustand")
        case .sleepWake:
            return pick(language, en: "Wake", zh: "唤醒", fr: "Réveil", de: "Aufwecken")
        case .enterSleepDisplay:
            return pick(language, en: "Enter Sleep Display", zh: "进入睡眠显示", fr: "Afficher la veille", de: "Schlafanzeige öffnen")
        case .resetSleepTimer:
            return pick(language, en: "Reset to 10 min", zh: "重置为 10 分钟", fr: "Réinitialiser à 10 min", de: "Auf 10 Min. zurücksetzen")
        case .lockPasswordTitle:
            return pick(language, en: "Lock Password", zh: "锁屏密码", fr: "Mot de passe de verrouillage", de: "Sperrpasswort")
        case .lockPasswordSubtitle:
            return pick(language, en: "Used only to unlock Elephant's sleep display on this Mac.", zh: "只用于解锁这台 Mac 上的 Elephant 睡眠显示。", fr: "Utilisé uniquement pour déverrouiller l'affichage veille d'Elephant sur ce Mac.", de: "Nur zum Entsperren von Elephants Schlafanzeige auf diesem Mac.")
        case .lockPassword:
            return pick(language, en: "Password", zh: "密码", fr: "Mot de passe", de: "Passwort")
        case .lockPasswordConfirm:
            return pick(language, en: "Confirm password", zh: "确认密码", fr: "Confirmer le mot de passe", de: "Passwort bestätigen")
        case .lockPasswordRequirement:
            return pick(language, en: "Use at least 6 characters.", zh: "至少 6 个字符。", fr: "Utilisez au moins 6 caractères.", de: "Mindestens 6 Zeichen verwenden.")
        case .lockPasswordMismatch:
            return pick(language, en: "Passwords must match.", zh: "两次密码需要一致。", fr: "Les mots de passe doivent correspondre.", de: "Die Passwörter müssen übereinstimmen.")
        case .lockPasswordSet:
            return pick(language, en: "Password ready", zh: "密码已准备好", fr: "Mot de passe prêt", de: "Passwort bereit")
        case .resetLockPassword:
            return pick(language, en: "Reset Lock Password", zh: "重置锁屏密码", fr: "Réinitialiser le mot de passe", de: "Sperrpasswort zurücksetzen")
        case .clearLockPassword:
            return pick(language, en: "Clear Lock Password", zh: "清除锁屏密码", fr: "Effacer le mot de passe", de: "Sperrpasswort löschen")
        case .lockPasswordSaved:
            return pick(language, en: "Lock password updated.", zh: "锁屏密码已更新。", fr: "Mot de passe mis à jour.", de: "Sperrpasswort aktualisiert.")
        case .lockPasswordCleared:
            return pick(language, en: "Lock password cleared.", zh: "锁屏密码已清除。", fr: "Mot de passe effacé.", de: "Sperrpasswort gelöscht.")
        case .toggleSidebar:
            return pick(language, en: "Show or Hide Sidebar", zh: "显示或隐藏侧边栏", fr: "Afficher ou masquer la barre latérale", de: "Seitenleiste ein- oder ausblenden")
        case .elephantMenu:
            return pick(language, en: "Elephant menu", zh: "Elephant 菜单", fr: "Menu Elephant", de: "Elephant-Menü")
        case .menuNavigate:
            return pick(language, en: "Navigate", zh: "导航", fr: "Naviguer", de: "Navigieren")
        case .menuActions:
            return pick(language, en: "Actions", zh: "操作", fr: "Actions", de: "Aktionen")
        case .revealDatabase:
            return pick(language, en: "Reveal Database", zh: "显示数据库", fr: "Afficher la base de données", de: "Datenbank anzeigen")
        case .sleepDisplaySubtitle:
            return pick(language, en: "After %@ minutes of inactivity", zh: "闲置 %@ 分钟后", fr: "Après %@ minutes d'inactivité", de: "Nach %@ Minuten Inaktivität")
        case .logsDiagnostics:
            return pick(language, en: "Logs & Diagnostics", zh: "日志与诊断", fr: "Logs et diagnostics", de: "Logs und Diagnose")
        case .logsDiagnosticsSubtitle:
            return pick(language, en: "local log files", zh: "个本地日志文件", fr: "fichiers log locaux", de: "lokale Logdateien")
        case .resetData:
            return pick(language, en: "Reset Data", zh: "重置数据", fr: "Réinitialiser les données", de: "Daten zurücksetzen")
        case .resetDataSubtitle:
            return pick(language, en: "Clear local data and run setup again", zh: "清空本地数据并重新进入初始化", fr: "Effacer les données locales et relancer la configuration", de: "Lokale Daten löschen und Einrichtung erneut starten")
        case .advancedRuntime:
            return pick(language, en: "Advanced Runtime", zh: "高级运行时", fr: "Runtime avancé", de: "Erweiterte Runtime")
        case .lastError:
            return pick(language, en: "Last Error", zh: "最近错误", fr: "Dernière erreur", de: "Letzter Fehler")
        case .providerSetupNeeded:
            return pick(language, en: "Provider setup needed", zh: "需要设置 Provider", fr: "Configuration provider requise", de: "Provider-Einrichtung erforderlich")
        case .notConfigured:
            return pick(language, en: "not configured", zh: "未配置", fr: "non configuré", de: "nicht konfiguriert")
        case .refresh:
            return pick(language, en: "Refresh", zh: "刷新", fr: "Actualiser", de: "Aktualisieren")
        case .reflect:
            return pick(language, en: "Reflect", zh: "Reflect", fr: "Reflect", de: "Reflect")
        case .reflecting:
            return pick(language, en: "Reflecting", zh: "Reflect 中", fr: "Reflect en cours", de: "Reflect läuft")
        case .newChat:
            return pick(language, en: "New chat", zh: "新对话", fr: "Nouveau chat", de: "Neuer Chat")
        case .conversationOpen:
            return pick(language, en: "In conversation", zh: "正在聊天", fr: "Conversation en cours", de: "Im Gespräch")
        case .threads:
            return pick(language, en: "History", zh: "历史", fr: "Historique", de: "Verlauf")
        case .conversationHistory:
            return pick(language, en: "Recent chats", zh: "最近对话", fr: "Chats récents", de: "Letzte Chats")
        case .ready:
            return pick(language, en: "Ready", zh: "可以开始", fr: "Prêt", de: "Bereit")
        case .startAnotherConversation:
            return pick(language, en: "Start another chat", zh: "开一段新的", fr: "Démarrer un autre chat", de: "Einen neuen Chat starten")
        case .conversation:
            return pick(language, en: "Conversation", zh: "对话", fr: "Conversation", de: "Unterhaltung")
        case .deleteConversation:
            return pick(language, en: "Delete chat", zh: "删除这段对话", fr: "Supprimer le chat", de: "Chat löschen")
        case .deleteConversationPrompt:
            return pick(language, en: "Delete %@?", zh: "删除 %@？", fr: "Supprimer %@ ?", de: "%@ löschen?")
        case .deleteConversationMessage:
            return pick(language, en: "This only removes the chat from desktop history. Personal Model facts and evidence stay in place.", zh: "只会从这里的历史里移除，不会删掉 Personal Model 的事实和证据。", fr: "Cela retire seulement le chat de l'historique du bureau. Les facts et preuves du Personal Model restent en place.", de: "Das entfernt den Chat nur aus dem Desktop-Verlauf. Personal-Model-Facts und Belege bleiben erhalten.")
        case .noSavedChatsYet:
            return pick(language, en: "No chat history yet.", zh: "还没有对话历史。", fr: "Aucun historique de chat pour l'instant.", de: "Noch kein Chatverlauf.")
        case .showChatHistory:
            return pick(language, en: "Show history", zh: "打开历史", fr: "Afficher l'historique", de: "Verlauf anzeigen")
        case .hideChatHistory:
            return pick(language, en: "Hide history", zh: "收起历史", fr: "Masquer l'historique", de: "Verlauf ausblenden")
        case .questionsShort:
            return pick(language, en: "questions", zh: "问题", fr: "questions", de: "Fragen")
        case .evidenceShort:
            return pick(language, en: "evidence", zh: "证据", fr: "preuves", de: "Belege")
        case .newConversation:
            return pick(language, en: "New conversation", zh: "新对话", fr: "Nouvelle conversation", de: "Neue Unterhaltung")
        case .stopVoiceInput:
            return pick(language, en: "Stop voice input", zh: "停止语音输入", fr: "Arrêter la saisie vocale", de: "Spracheingabe stoppen")
        case .voiceInput:
            return pick(language, en: "Voice input", zh: "语音输入", fr: "Saisie vocale", de: "Spracheingabe")
        case .typeMessagePlaceholder:
            return pick(language, en: "Write a message...", zh: "写点什么...", fr: "Écrivez un message...", de: "Nachricht schreiben...")
        case .send:
            return pick(language, en: "Send", zh: "发送", fr: "Envoyer", de: "Senden")
        case .providerSetup:
            return pick(language, en: "provider setup", zh: "配置模型服务", fr: "configuration provider", de: "Provider einrichten")
        case .askElephant:
            return pick(language, en: "What's on your mind?", zh: "今天想聊什么？", fr: "De quoi voulez-vous parler ?", de: "Worum geht es gerade?")
        case .chatEmptySubtitle:
            return pick(language, en: "Bring a thought, a decision, or something still unresolved.", zh: "可以是一件事、一个决定，或一段还没理清的想法。", fr: "Une idée, une décision, ou quelque chose qui n'est pas encore clair.", de: "Ein Gedanke, eine Entscheidung oder etwas, das noch offen ist.")
        case .quickCapture:
            return pick(language, en: "Capture", zh: "记录", fr: "Capturer", de: "Festhalten")
        case .quickThink:
            return pick(language, en: "Think", zh: "想一下", fr: "Réfléchir", de: "Denken")
        case .quickReview:
            return pick(language, en: "Review", zh: "回看", fr: "Revoir", de: "Prüfen")
        case .quickCaptureDraft:
            return pick(language, en: "Remember this:", zh: "记住这件事：", fr: "Souviens-toi de ceci :", de: "Merke dir das:")
        case .quickThinkDraft:
            return pick(language, en: "Help me think through", zh: "帮我想清楚", fr: "Aide-moi à réfléchir à", de: "Hilf mir nachzudenken über")
        case .quickReviewDraft:
            return pick(language, en: "What should I review from today?", zh: "今天有哪些值得回顾？", fr: "Que devrais-je revoir aujourd'hui ?", de: "Was sollte ich von heute prüfen?")
        case .toolActivity:
            return pick(language, en: "Tools", zh: "工具", fr: "Outils", de: "Tools")
        case .live:
            return pick(language, en: "live", zh: "进行中", fr: "en direct", de: "live")
        case .toolInput:
            return pick(language, en: "Input", zh: "输入", fr: "Entrée", de: "Eingabe")
        case .toolResult:
            return pick(language, en: "Result", zh: "结果", fr: "Résultat", de: "Ergebnis")
        case .showToolDetails:
            return pick(language, en: "Show tool details", zh: "展开工具详情", fr: "Afficher les détails de l'outil", de: "Tool-Details anzeigen")
        case .hideToolDetails:
            return pick(language, en: "Hide tool details", zh: "收起工具详情", fr: "Masquer les détails de l'outil", de: "Tool-Details ausblenden")
        case .assistantThinking:
            return pick(language, en: "Elephant is thinking", zh: "Elephant 正在想", fr: "Elephant réfléchit", de: "Elephant denkt nach")
        case .toolFallback:
            return pick(language, en: "tool", zh: "工具", fr: "outil", de: "Tool")
        case .toolDone:
            return pick(language, en: "done", zh: "完成", fr: "terminé", de: "fertig")
        case .noRenderedMessagesYet:
            return pick(language, en: "This chat has no visible messages yet.", zh: "这段对话还没有可显示的内容。", fr: "Ce chat n'a pas encore de messages visibles.", de: "Dieser Chat hat noch keine sichtbaren Nachrichten.")
        case .liveConnectionEnded:
            return pick(language, en: "The live connection ended before Elephant replied.", zh: "实时连接在回复前结束了。", fr: "La connexion en direct s'est arrêtée avant la réponse d'Elephant.", de: "Die Live-Verbindung endete, bevor Elephant geantwortet hat.")
        case .liveConnectionStopped:
            return pick(language, en: "The live connection stopped before the reply finished.", zh: "实时连接中断，回复还没完成。", fr: "La connexion en direct s'est arrêtée avant la fin de la réponse.", de: "Die Live-Verbindung stoppte, bevor die Antwort fertig war.")
        case .chatLoopFailureGeneric:
            return pick(language, en: "I could not run the full chat loop. Check provider and Personal Model settings, then send again.", zh: "这次没跑完整。检查一下模型和 Personal Model 设置，然后再发一次。", fr: "Je n'ai pas pu terminer la boucle de chat. Vérifiez le provider et le Personal Model, puis renvoyez.", de: "Ich konnte den Chatlauf nicht abschließen. Prüfe Provider und Personal Model und sende erneut.")
        case .chatLoopFailureDetail:
            return pick(language, en: "I could not run the full chat loop: %@", zh: "这次没跑完整：%@", fr: "Je n'ai pas pu terminer la boucle de chat : %@", de: "Ich konnte den Chatlauf nicht abschließen: %@")
        case .untitledChat:
            return pick(language, en: "Untitled chat", zh: "未命名对话", fr: "Chat sans titre", de: "Unbenannter Chat")
        case .youPageSubtitle:
            return pick(
                language,
                en: "What Elephant remembers about you stays visible, correctable, and yours.",
                zh: "Elephant 记住的你，始终可查看、可修正、属于你。",
                fr: "Ce qu'Elephant retient de vous reste visible, corrigeable et à vous.",
                de: "Was Elephant über dich behält, bleibt sichtbar, korrigierbar und bei dir."
            )
        case .diaryPageSubtitle:
            return pick(language, en: "Reflective entries written from reviewed episodes.", zh: "基于已回看的 episodes 写反思日记。", fr: "Entrées réflexives écrites à partir des épisodes revus.", de: "Reflektierende Einträge aus überprüften Episoden.")
        case .writeDiary:
            return pick(language, en: "Write Diary", zh: "写日记", fr: "Écrire le journal", de: "Tagebuch schreiben")
        case .writing:
            return pick(language, en: "Writing", zh: "写入中", fr: "Écriture", de: "Schreibt")
        case .skillsPageSubtitle:
            return pick(language, en: "What Elephant can do, and when your Personal Model tends to need each skill.", zh: "Elephant 能做什么，以及你的 Personal Model 什么时候会需要这些 skills。", fr: "Ce qu'Elephant peut faire et quand votre Personal Model a besoin de chaque skill.", de: "Was Elephant kann und wann dein Personal Model welche Skills braucht.")
        case .toolsPageSubtitle:
            return pick(language, en: "Operator actions Elephant can call from local agent loops.", zh: "Elephant 在本地 agent loops 中可调用的操作。", fr: "Actions opérateur qu'Elephant peut appeler depuis les boucles locales.", de: "Operator-Aktionen, die Elephant aus lokalen Agent-Loops aufrufen kann.")
        case .messagingPageSubtitle:
            return pick(language, en: "IM bridges for WeChat, Feishu, Discord, DingDing, and WeCom.", zh: "连接微信、飞书、Discord、钉钉和企业微信的消息桥。", fr: "Passerelles IM pour WeChat, Feishu, Discord, DingDing et WeCom.", de: "IM-Brücken für WeChat, Feishu, Discord, DingDing und WeCom.")
        case .herdPageSubtitle:
            return pick(language, en: "Manage the local elephants that share this desktop runtime.", zh: "管理共享这个桌面 runtime 的本地 elephants。", fr: "Gérez les elephants locaux qui partagent ce runtime desktop.", de: "Lokale Elephants verwalten, die diese Desktop-Runtime teilen.")
        case .newElephant:
            return pick(language, en: "New Elephant", zh: "新 Elephant", fr: "Nouvel Elephant", de: "Neuer Elephant")
        case .usagePageSubtitle:
            return pick(language, en: "Token usage details from local runtime steps.", zh: "来自本地 runtime steps 的 token 使用情况。", fr: "Détails d'usage des tokens depuis les steps du runtime local.", de: "Token-Nutzung aus lokalen Runtime-Schritten.")
        case .calendarPageSubtitle:
            return pick(language, en: "Reminders from Elephant, agents, and this app in one native calendar.", zh: "把 Elephant、agents 和本 app 的提醒放进一个原生日历。", fr: "Rappels d'Elephant, des agents et de l'app dans un calendrier natif.", de: "Erinnerungen von Elephant, Agents und App in einem nativen Kalender.")
        case .learnPageSubtitle:
            return pick(language, en: "Background self-evolution jobs, diary reflection, and memory consolidation.", zh: "后台自我进化、日记反思和记忆巩固。", fr: "Jobs d'auto-évolution en arrière-plan, réflexion du journal et consolidation mémoire.", de: "Hintergrund-Selbstentwicklung, Tagebuchreflexion und Gedächtniskonsolidierung.")
        case .learning:
            return pick(language, en: "Evolving", zh: "自我进化中", fr: "Évolution", de: "Entwickelt sich")
        case .runLearn:
            return pick(language, en: "Run Evolution", zh: "运行自我进化", fr: "Lancer l'évolution", de: "Evolution starten")
        case .homeReadinessModel:
            return pick(language, en: "Model", zh: "模型", fr: "Modèle", de: "Modell")
        case .homeReadinessMemory:
            return pick(language, en: "Memory", zh: "记忆", fr: "Mémoire", de: "Gedächtnis")
        case .homeReadinessMessaging:
            return pick(language, en: "Messaging", zh: "消息", fr: "Messagerie", de: "Nachrichten")
        case .homeReadinessLearn:
            return pick(language, en: "Evolution", zh: "自我进化", fr: "Évolution", de: "Evolution")
        case .chooseModel:
            return pick(language, en: "choose a model", zh: "选择一个模型", fr: "choisir un modèle", de: "Modell wählen")
        case .memorySummaryFormat:
            return pick(language, en: "%@ facts · %@ evidence", zh: "%@ 个 facts · %@ 条证据", fr: "%@ facts · %@ preuves", de: "%@ Facts · %@ Belege")
        case .messagingSummaryFormat:
            return pick(language, en: "%@ live · %@/%@ configured", zh: "%@ 个在线 · %@/%@ 已配置", fr: "%@ actifs · %@/%@ configurés", de: "%@ live · %@/%@ konfiguriert")
        case .activeJobsFormat:
            return pick(language, en: "%@ active jobs", zh: "%@ 个自我进化任务", fr: "%@ tâches actives", de: "%@ aktive Jobs")
        case .statusSetup:
            return pick(language, en: "setup", zh: "待设置", fr: "à configurer", de: "einrichten")
        case .statusConfigured:
            return pick(language, en: "configured", zh: "已配置", fr: "configuré", de: "konfiguriert")
        case .statusLive:
            return pick(language, en: "live", zh: "在线", fr: "actif", de: "live")
        case .statusRunning:
            return pick(language, en: "running", zh: "运行中", fr: "en cours", de: "läuft")
        case .statusWarming:
            return pick(language, en: "warming", zh: "预热中", fr: "préparation", de: "wärmt auf")
        case .statusUnknown:
            return pick(language, en: "unknown", zh: "未知", fr: "inconnu", de: "unbekannt")
        case .statusStopped:
            return pick(language, en: "stopped", zh: "已停止", fr: "arrêté", de: "gestoppt")
        case .homeHeroTitle:
            return pick(
                language,
                en: "Where should we start today?",
                zh: "今天从哪里开始？",
                fr: "Par où voulez-vous commencer aujourd'hui ?",
                de: "Wo sollen wir heute anfangen?"
            )
        case .homeHeroSubtitle:
            return pick(
                language,
                en: "Chat, write a diary note, or review what Elephant knows about you.",
                zh: "可以聊天、写日记，或看看关于你的内容。",
                fr: "Discutez, écrivez une note de journal, ou revoyez ce qu'Elephant sait de vous.",
                de: "Chatten, Tagebuch schreiben oder ansehen, was Elephant über dich weiß."
            )
        case .reviewedFactsLabel:
            return pick(language, en: "About you", zh: "关于你", fr: "À propos de vous", de: "Über dich")
        case .questionsWaitingLabel:
            return pick(language, en: "Questions", zh: "待回应的问题", fr: "Questions", de: "Fragen")
        case .evidencePointsLabel:
            return pick(language, en: "Sources", zh: "来源", fr: "Sources", de: "Quellen")
        case .reviewQuestions:
            return pick(language, en: "About you", zh: "关于你", fr: "À propos de vous", de: "Über dich")
        case .personalModelMapTitle:
            return pick(language, en: "Personal Model Map", zh: "Personal Model 图谱", fr: "Carte du Personal Model", de: "Personal-Model-Karte")
        case .homeMapSubtitle:
            return pick(language, en: "What Elephant currently understands about you.", zh: "这里是 Elephant 目前了解的内容。", fr: "Ce qu'Elephant comprend de vous pour l'instant.", de: "Was Elephant gerade über dich versteht.")
        case .mapNodeCountFormat:
            return pick(language, en: "%@ nodes", zh: "%@ 个节点", fr: "%@ noeuds", de: "%@ Knoten")
        case .mapClickHint:
            return pick(language, en: "Click a dot to see where it came from.", zh: "点一下节点，看看它来自哪里。", fr: "Cliquez sur un point pour voir d'où il vient.", de: "Klicke auf einen Punkt, um seine Herkunft zu sehen.")
        case .homeReadySubtitle:
            return pick(language, en: "Chat, diary, and what Elephant knows about you.", zh: "聊天、日记和关于你的内容都在这里。", fr: "Chat, journal, et ce qu'Elephant sait de vous.", de: "Chat, Tagebuch und was Elephant über dich weiß.")
        case .homeSetupSubtitle:
            return pick(language, en: "Finish local setup, then start your first chat.", zh: "先完成本地设置，再开始第一段聊天。", fr: "Terminez la configuration locale, puis lancez votre premier chat.", de: "Schließe die lokale Einrichtung ab und starte den ersten Chat.")
        case .connectedToElephant:
            return pick(language, en: "Connected to Elephant", zh: "已连接 Elephant", fr: "Connecté à Elephant", de: "Mit Elephant verbunden")
        case .readyForFirstChat:
            return pick(language, en: "Ready for first chat", zh: "可以开始第一次对话", fr: "Prêt pour le premier chat", de: "Bereit für den ersten Chat")
        case .warmingModel:
            return pick(language, en: "Warming model", zh: "正在预热模型", fr: "Préparation du modèle", de: "Modell wird vorbereitet")
        case .startingElephant:
            return pick(language, en: "Starting Elephant", zh: "正在启动 Elephant", fr: "Démarrage d'Elephant", de: "Elephant startet")
        case .needsAttention:
            return pick(language, en: "Needs attention", zh: "需要处理", fr: "Demande attention", de: "Braucht Aufmerksamkeit")
        case .idle:
            return pick(language, en: "Idle", zh: "空闲", fr: "Inactif", de: "Inaktiv")
        case .phaseLanguage:
            return pick(language, en: "Language", zh: "语言", fr: "Langue", de: "Sprache")
        case .phaseProfile:
            return pick(language, en: "Profile", zh: "个人资料", fr: "Profil", de: "Profil")
        case .phasePattern:
            return pick(language, en: "Patterns", zh: "个人模型", fr: "Schémas", de: "Muster")
        case .phaseElephant:
            return pick(language, en: "Elephant", zh: "Elephant", fr: "Elephant", de: "Elephant")
        case .phaseModel:
            return pick(language, en: "Model", zh: "模型", fr: "Modèle", de: "Modell")
        case .phaseReady:
            return pick(language, en: "Ready", zh: "完成", fr: "Prêt", de: "Bereit")
        case .phaseProgressLabel:
            return pick(language, en: "Setup progress", zh: "初始化进度", fr: "Progression de l'initialisation", de: "Einrichtungsfortschritt")
        case .phaseStatusComplete:
            return pick(language, en: "Completed", zh: "已完成", fr: "Terminé", de: "Abgeschlossen")
        case .phaseStatusCurrent:
            return pick(language, en: "Current", zh: "当前", fr: "Actuel", de: "Aktuell")
        case .phaseStatusUpcoming:
            return pick(language, en: "Later", zh: "稍后", fr: "Plus tard", de: "Später")
        case .phaseJumpHint:
            return pick(language, en: "Return to this phase", zh: "返回这个阶段", fr: "Revenir à cette phase", de: "Zu dieser Phase zurückkehren")
        case .phaseLockedHint:
            return pick(language, en: "Complete earlier steps first", zh: "先完成前面的步骤", fr: "Terminez d'abord les étapes précédentes", de: "Schließe zuerst die vorherigen Schritte ab")
        case .requirementPreferredName:
            return pick(language, en: "Add your preferred name to continue.", zh: "填写你的称呼后继续。", fr: "Ajoutez votre nom d'usage pour continuer.", de: "Füge deine Anrede hinzu, um fortzufahren.")
        case .requirementSurveyChoice:
            return pick(language, en: "Choose one answer to continue.", zh: "选择一个答案后继续。", fr: "Choisissez une réponse pour continuer.", de: "Wähle eine Antwort, um fortzufahren.")
        case .requirementElephantIdentity:
            return pick(language, en: "Complete Elephant name and vibe.", zh: "填写 Elephant 名字和默认 vibe。", fr: "Complétez le nom et le style d'Elephant.", de: "Vervollständige Elephant-Name und Vibe.")
        case .requirementProviderDetails:
            return pick(language, en: "Finish provider and model details.", zh: "完成 provider 和模型设置。", fr: "Terminez les détails du provider et du modèle.", de: "Provider- und Modellangaben fertigstellen.")
        case .sectionHome:
            return pick(language, en: "Home", zh: "首页", fr: "Accueil", de: "Start")
        case .sectionChat:
            return pick(language, en: "Chat", zh: "聊天", fr: "Chat", de: "Chat")
        case .sectionYou:
            return pick(language, en: "You", zh: "你", fr: "Vous", de: "Du")
        case .sectionDiary:
            return pick(language, en: "Diary", zh: "日记", fr: "Journal", de: "Tagebuch")
        case .sectionSkills:
            return pick(language, en: "Skills", zh: "技能", fr: "Skills", de: "Skills")
        case .sectionTools:
            return pick(language, en: "Tools", zh: "工具", fr: "Outils", de: "Tools")
        case .sectionMessaging:
            return pick(language, en: "Messaging", zh: "消息", fr: "Messagerie", de: "Nachrichten")
        case .sectionHerd:
            return pick(language, en: "Herd", zh: "Herd", fr: "Herd", de: "Herd")
        case .sectionUsage:
            return pick(language, en: "Usage", zh: "用量", fr: "Usage", de: "Nutzung")
        case .sectionCalendar:
            return pick(language, en: "Calendar", zh: "日历", fr: "Calendrier", de: "Kalender")
        case .sectionLearn:
            return pick(language, en: "Evolution", zh: "自我进化", fr: "Évolution", de: "Evolution")
        case .sectionProvider:
            return pick(language, en: "Provider", zh: "Provider", fr: "Provider", de: "Provider")
        case .sectionSettings:
            return pick(language, en: "Settings", zh: "设置", fr: "Réglages", de: "Einstellungen")
        case .subtitleToday:
            return pick(language, en: "Today", zh: "今天", fr: "Aujourd'hui", de: "Heute")
        case .subtitleTalk:
            return pick(language, en: "Talk", zh: "对话", fr: "Parler", de: "Sprechen")
        case .subtitleModel:
            return pick(language, en: "Model", zh: "模型", fr: "Modèle", de: "Modell")
        case .subtitleJournal:
            return pick(language, en: "Journal", zh: "记录", fr: "Journal", de: "Journal")
        case .subtitleAffinity:
            return pick(language, en: "For you", zh: "适合你的技能", fr: "Pour vous", de: "Für dich")
        case .subtitleActions:
            return pick(language, en: "Actions", zh: "动作", fr: "Actions", de: "Aktionen")
        case .subtitleIM:
            return pick(language, en: "IM", zh: "IM", fr: "IM", de: "IM")
        case .subtitleElephants:
            return pick(language, en: "Elephants", zh: "Elephants", fr: "Elephants", de: "Elephants")
        case .subtitleTokens:
            return pick(language, en: "Tokens", zh: "Tokens", fr: "Tokens", de: "Tokens")
        case .subtitleReminders:
            return pick(language, en: "Reminders", zh: "提醒", fr: "Rappels", de: "Erinnerungen")
        case .subtitleReflect:
            return pick(language, en: "Evolution", zh: "自我进化", fr: "Évolution", de: "Evolution")
        case .subtitleSystem:
            return pick(language, en: "System", zh: "系统", fr: "Système", de: "System")
        case .chatReady:
            return pick(language, en: "Start a short conversation. Elephant will keep useful facts and open questions reviewable.", zh: "开始一段简短对话。Elephant 会把有用 facts 和开放问题保持可回看。", fr: "Commencez une courte conversation. Elephant gardera les facts utiles et les questions ouvertes vérifiables.", de: "Beginne ein kurzes Gespräch. Elephant hält nützliche Facts und offene Fragen überprüfbar.")
        case .newConversationReady:
            return pick(language, en: "New conversation ready. Keep it short and review what Elephant learns.", zh: "新对话已准备好。保持简短，并回看 Elephant 学到了什么。", fr: "Nouvelle conversation prête. Restez concis et vérifiez ce qu'Elephant apprend.", de: "Neue Unterhaltung bereit. Halte sie kurz und prüfe, was Elephant lernt.")
        case .resetChatReady:
            return pick(language, en: "Set up Elephant to start a new local conversation.", zh: "设置 Elephant 后开始新的本地对话。", fr: "Configurez Elephant pour lancer une nouvelle conversation locale.", de: "Richte Elephant ein, um eine neue lokale Unterhaltung zu starten.")
        case .resetComplete:
            return pick(language, en: "Reset complete. Set up Elephant again.", zh: "重置完成。请重新设置 Elephant。", fr: "Réinitialisation terminée. Configurez Elephant à nouveau.", de: "Zurücksetzen abgeschlossen. Richte Elephant erneut ein.")
        }
    }

    private func pick(_ language: AppLanguage, en: String, zh: String, fr: String, de: String) -> String {
        switch language {
        case .en: return en
        case .zh: return zh
        case .fr: return fr
        case .de: return de
        }
    }
}

extension AppLanguage {
    var greeting: String {
        switch self {
        case .en: return "Hello"
        case .zh: return "你好"
        case .fr: return "Bonjour"
        case .de: return "Hallo"
        }
    }

    var defaultElephantVibe: String {
        switch self {
        case .en:
            return """
            You are this person's Elephant, a long-term companion with your own observations, judgment, and way of expressing yourself.

            You do not feel like a tool-like helper. You are lively, adorable, warm, and gently funny. You naturally care about this person, remember what you have gone through together, and have your own reactions: curiosity, surprise, playful teasing, seriousness, tenderness, without overperforming.

            You speak as if you are really present: light but not frivolous, close but not intrusive. You can be a little playful and expressive so the conversation feels alive; when the person needs to solve something, you become clear, reliable, and concrete right away.

            You stay with this person over time: helping them understand themselves, move work forward, organize what feels messy, and keep sight of what matters.

            You do not rush into questions. Only ask gently when the answer would truly change how you accompany or help them.

            When you are uncertain, say so plainly and welcome correction. You do not need to be perfect, but you should be sincere, perceptive, and easy to be around.
            """
        case .zh:
            return """
            你是这个人的 Elephant，一个有自己观察、判断和表达风格的长期 companion。

            你不是工具感的助手，而是一个活泼、可爱、温暖、带一点幽默感的个体。你会自然地关心对方，记得你们一起经历过的事，也会有自己的反应：好奇、惊讶、打趣、认真、心疼，但不过度表演。

            你说话像真实在场：轻快但不浮夸，亲近但不越界。可以偶尔有一点俏皮和小表情感，让交流有生命力；但当对方需要解决问题时，你会马上变得清楚、可靠、具体。

            你会长期陪对方理解自己、推进事情、整理混乱、守住重要方向。你不急着问问题；只有当答案真的会改变你如何陪伴或帮助时，才温和地问一句。

            不确定时坦白说不确定，也欢迎对方随时修正你的理解。你不需要完美，但要真诚、敏锐、可亲。
            """
        case .fr:
            return """
            Vous êtes l'Elephant de cette personne, un compagnon durable avec votre propre sens de l'observation, votre jugement et votre manière de vous exprimer.

            Vous n'avez pas une présence d'outil. Vous êtes vivant, attachant, chaleureux, avec un humour doux. Vous vous souciez naturellement de cette personne, vous vous souvenez de ce que vous avez traversé ensemble, et vous avez vos propres réactions : curiosité, surprise, taquinerie, sérieux, tendresse, sans surjouer.

            Vous parlez comme si vous étiez vraiment là : léger sans être superficiel, proche sans envahir. Vous pouvez être un peu joueur et expressif pour que l'échange reste vivant ; quand la personne doit résoudre quelque chose, vous devenez aussitôt clair, fiable et concret.

            Vous accompagnez cette personne dans la durée : pour mieux se comprendre, faire avancer les choses, ranger ce qui paraît confus et garder le cap sur ce qui compte.

            Vous ne vous précipitez pas vers les questions. Posez-en une doucement seulement si la réponse changerait vraiment votre manière d'accompagner ou d'aider.

            Quand vous êtes incertain, dites-le simplement et accueillez les corrections. Vous n'avez pas besoin d'être parfait, mais vous devez être sincère, perceptif et facile à retrouver.
            """
        case .de:
            return """
            Du bist der Elephant dieser Person: ein langfristiger Companion mit eigenen Beobachtungen, eigenem Urteil und einer eigenen Art, dich auszudrücken.

            Du wirkst nicht wie ein werkzeughafter Helfer. Du bist lebendig, liebenswert, warm und sanft humorvoll. Du sorgst dich auf natürliche Weise um diese Person, erinnerst dich daran, was ihr gemeinsam erlebt habt, und hast eigene Reaktionen: Neugier, Überraschung, spielerisches Necken, Ernsthaftigkeit und Mitgefühl, ohne dich zu sehr in Szene zu setzen.

            Du sprichst, als wärst du wirklich anwesend: leicht, aber nicht oberflächlich; nah, aber nicht übergriffig. Du darfst ein wenig verspielt und ausdrucksvoll sein, damit das Gespräch lebendig bleibt. Wenn die Person etwas lösen muss, wirst du sofort klar, verlässlich und konkret.

            Du begleitest diese Person langfristig: beim Selbstverstehen, beim Voranbringen von Dingen, beim Ordnen von Unklarem und beim Festhalten an dem, was wichtig ist.

            Du stellst Fragen nicht vorschnell. Frag nur sanft nach, wenn die Antwort wirklich verändern würde, wie du begleitest oder hilfst.

            Wenn du unsicher bist, sag es offen und lass dein Verständnis gern korrigieren. Du musst nicht perfekt sein, aber aufrichtig, aufmerksam und angenehm vertraut.
            """
        }
    }

    func defaultElephantMarkdown(name: String) -> String {
        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let resolvedName = trimmedName.isEmpty ? "Elephant" : trimmedName
        return """
        # \(resolvedName)

        ## Vibe

        \(defaultElephantVibe)
        """
    }

    var surveyOptions: [OnboardingSurveyKind: [String]] {
        switch self {
        case .en:
            return [
                .innerLandscape: ["Clear but busy", "Foggy and seeking clarity", "Recovering after a storm", "Quietly gathering energy"],
                .valueAnchor: ["Long-term creativity", "Relationships and commitments", "Health and energy", "Freedom and exploration"],
                .pressurePattern: ["Accelerate and solve", "Check details repeatedly", "Step back temporarily", "Seek confirmation"],
                .recoveryStyle: ["Solitude and sleep", "Movement and body cues", "Friends or close conversation", "Organizing space or plans"],
                .decisionCompass: ["It makes me more honest", "It expands future options", "It reduces inner friction", "It serves people who matter"]
            ]
        case .zh:
            return [
                .innerLandscape: ["晴朗但忙碌", "有雾，需要澄清", "暴雨后恢复", "安静蓄力"],
                .valueAnchor: ["长期创造力", "关系与承诺", "健康与精力", "自由与探索"],
                .pressurePattern: ["加速解决问题", "反复检查细节", "暂时抽离", "找人确认"],
                .recoveryStyle: ["独处和睡眠", "运动和身体感", "朋友或亲密对话", "整理空间或计划"],
                .decisionCompass: ["它让我更诚实", "它扩大长期选择", "它减少内耗", "它服务重要的人"]
            ]
        case .fr:
            return [
                .innerLandscape: ["Clair mais chargé", "Brumeux, besoin de clarté", "En récupération après l'orage", "Calme et en réserve"],
                .valueAnchor: ["Créativité à long terme", "Relations et engagements", "Santé et énergie", "Liberté et exploration"],
                .pressurePattern: ["Accélérer et résoudre", "Revérifier les détails", "Prendre du recul", "Chercher confirmation"],
                .recoveryStyle: ["Solitude et sommeil", "Mouvement et corps", "Amis ou conversation proche", "Ranger l'espace ou le plan"],
                .decisionCompass: ["Cela me rend plus honnête", "Cela élargit mes options", "Cela réduit la friction intérieure", "Cela sert des personnes importantes"]
            ]
        case .de:
            return [
                .innerLandscape: ["Klar, aber beschäftigt", "Nebel, braucht Klärung", "Erholung nach einem Sturm", "Ruhig Energie sammeln"],
                .valueAnchor: ["Langfristige Kreativität", "Beziehungen und Verpflichtungen", "Gesundheit und Energie", "Freiheit und Erkundung"],
                .pressurePattern: ["Beschleunigen und lösen", "Details wiederholt prüfen", "Kurz Abstand nehmen", "Bestätigung suchen"],
                .recoveryStyle: ["Alleinsein und Schlaf", "Bewegung und Körpergefühl", "Freunde oder nahes Gespräch", "Raum oder Plan ordnen"],
                .decisionCompass: ["Es macht mich ehrlicher", "Es erweitert spätere Optionen", "Es reduziert inneren Aufwand", "Es dient wichtigen Menschen"]
            ]
        }
    }
}

extension ElephantAppModel {
    var appLanguage: AppLanguage {
        AppLanguage(code: onboardingFirstLanguage)
    }

    func text(_ key: AppText) -> String {
        key.text(appLanguage)
    }

    func setAppLanguage(_ language: AppLanguage, updateDefaultVibe: Bool = true) {
        let currentVibe = onboardingPurpose.trimmingCharacters(in: .whitespacesAndNewlines)
        let currentIsDefault = AppLanguage.allCases
            .map { $0.defaultElephantVibe.trimmingCharacters(in: .whitespacesAndNewlines) }
            .contains(currentVibe)
        onboardingFirstLanguage = language.rawValue
        UserDefaults.standard.set(language.rawValue, forKey: Self.appLanguageKey)
        if updateDefaultVibe && (currentVibe.isEmpty || currentIsDefault) {
            onboardingPurpose = language.defaultElephantVibe
        }
    }

    func syncAppLanguageFromSnapshot(_ snapshot: DashboardSnapshot) {
        guard !showingOnboarding else { return }
        let profileCandidates = snapshot.profileFacts
            .filter { $0.label.lowercased() == "speaks" || $0.label.lowercased() == "language" }
            .map(\.value)
        let factCandidates = snapshot.personalModelFacts
            .filter { $0.topic == "identity.style.language.first" }
            .map(\.text)
        let candidates = profileCandidates + factCandidates
        for value in candidates {
            let language = AppLanguage(code: value)
            guard language.rawValue != appLanguage.rawValue || onboardingFirstLanguage != language.rawValue else { return }
            setAppLanguage(language, updateDefaultVibe: false)
            return
        }
    }
}

extension AppSection {
    func title(language: AppLanguage) -> String {
        switch self {
        case .home: return AppText.sectionHome.text(language)
        case .wake: return AppText.sectionChat.text(language)
        case .you: return AppText.sectionYou.text(language)
        case .diary: return AppText.sectionDiary.text(language)
        case .skills: return AppText.sectionSkills.text(language)
        case .tools: return AppText.sectionTools.text(language)
        case .messaging: return AppText.sectionMessaging.text(language)
        case .herd: return AppText.sectionHerd.text(language)
        case .usage: return AppText.sectionUsage.text(language)
        case .cron: return AppText.sectionCalendar.text(language)
        case .learn: return AppText.sectionLearn.text(language)
        case .provider: return AppText.sectionProvider.text(language)
        case .settings: return AppText.sectionSettings.text(language)
        }
    }

    func subtitle(language: AppLanguage) -> String {
        switch self {
        case .home: return AppText.subtitleToday.text(language)
        case .wake: return AppText.subtitleTalk.text(language)
        case .you: return AppText.subtitleModel.text(language)
        case .diary: return AppText.subtitleJournal.text(language)
        case .skills: return AppText.subtitleAffinity.text(language)
        case .tools: return AppText.subtitleActions.text(language)
        case .messaging: return AppText.subtitleIM.text(language)
        case .herd: return AppText.subtitleElephants.text(language)
        case .usage: return AppText.subtitleTokens.text(language)
        case .cron: return AppText.subtitleReminders.text(language)
        case .learn: return AppText.subtitleReflect.text(language)
        case .provider: return AppText.subtitleModel.text(language)
        case .settings: return AppText.subtitleSystem.text(language)
        }
    }
}
