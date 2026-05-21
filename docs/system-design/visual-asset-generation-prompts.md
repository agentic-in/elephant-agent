# Elephant Agent Visual Asset Generation Prompts

This is the batch prompt sheet for regenerating Elephant Agent website, README,
blog, and paper imagery with one coherent visual system.

Use these prompts with GPT Image2 one image at a time. Each prompt is
self-contained. Do not ask the image model to generate a contact sheet, grid, or
multiple variants unless a section explicitly says so.

## Approved Visual Direction

Elephant Agent should feel like a native Mac companion and a
personal-model-first AI system, not a generic memory app, chatbot, or mascot
toy.

Core product meaning:

- Personal-model-first AI.
- Remembers less, understands deeper.
- Starts from the person, not from a blank task.
- Grows a correctable understanding across Identity, World, Pulse, and Journey.
- Asks gently at the user's pace.
- Reflects after the turn.
- Helps the user pick up the right thread.

Visual system:

- Warm porcelain and soft matte glass.
- Warm ivory, greige, muted blue-gray ink, muted mint-gray, and one amber core
  accent.
- Calm dimensional lighting and soft shadows.
- Large simple forms, readable at thumbnail size.
- Elephant presence as a quiet guide, not a loud mascot.
- Path, thread, core, evidence, and four-lens symbols as recurring motifs.

Avoid across all images:

- Cyberpunk, neon, sci-fi control rooms, glowing neural webs.
- Childish cartoon baby elephant styling.
- Realistic safari photography.
- Dense tiny text.
- Stock AI brain imagery.
- Generic chatbot bubbles as the main idea.
- Stars, magic wands, floating decoration, or loud marketing gradients.
- Text-heavy diagrams that rely on paragraphs inside the image.

If the image model supports reference images, attach the approved app icon as
the style reference for every generation. If it does not, each prompt below is
still complete enough to run independently.

## Generation Workflow

1. Generate each asset independently.
2. Use the requested target size when the model supports exact dimensions.
3. For `.jpg` and `.webp` targets, generate a PNG first, then convert after
   review.
4. Keep the main subject inside a safe crop area with at least 6 percent padding.
5. Reject any result where small labels are unreadable, the elephant becomes a
   toy character, or the visual style drifts away from warm porcelain and quiet
   Mac polish.

## Asset Manifest

| Target path | Size | Prompt section |
| --- | ---: | --- |
| `apps/site/static/assets/resources/readme-1.png` | 1672x941 | README Hero |
| `apps/site/static/assets/resources/readme-2.png` | 1672x941 | README Lenses |
| `apps/site/static/assets/brand/social-share-card.png` | 1672x941 | Social Share Card |
| `apps/site/static/assets/brand/blog-cover.png` | 1672x941 | Blog Cover |
| `apps/site/static/assets/brand/elephant-herd.jpg` | 2000x1333 | Website Herd Background |
| `apps/site/static/assets/brand/elephant-savanna-snr.jpg` | 2560x1440 | Website Savanna Background |
| `apps/site/static/assets/brand/elephant-body-image-02.webp` | 1600x868 | Website Elephant Texture |
| `apps/site/static/assets/resources/paper-1.png` | 1672x941 | Paper Figure 1 |
| `apps/site/static/assets/resources/paper-2.png` | 1448x1086 | Paper Figure 2 |
| `apps/site/static/assets/resources/paper-3.png` | 1448x1086 | Paper Figure 3 |
| `apps/site/static/assets/resources/paper-4.png` | 1448x1086 | Paper Figure 4 |
| `apps/site/static/assets/resources/paper-5.png` | 1448x1086 | Paper Figure 5 |
| `apps/site/static/assets/resources/paper-6.png` | 1448x1086 | Paper Figure 6 |
| `apps/site/static/assets/resources/paper-7.png` | 1448x1086 | Paper Figure 7 |
| `apps/site/static/assets/blog/1.png` | 1672x941 | Blog Image 1 |
| `apps/site/static/assets/blog/2.png` | 1672x941 | Blog Image 2 |
| `apps/site/static/assets/blog/3.png` | 1672x941 | Blog Image 3 |
| `apps/site/static/assets/blog/4.png` | 1672x941 | Blog Image 4 |
| `apps/site/static/assets/blog/5.png` | 1672x941 | Blog Image 5 |
| `apps/site/static/assets/blog/6.png` | 1672x941 | Blog Image 6 |
| `apps/site/static/assets/blog/7.png` | 1672x941 | Blog Image 7 |
| `apps/site/static/assets/blog/8.png` | 1672x941 | Blog Image 8 |
| `apps/site/static/assets/blog/9.png` | 1672x941 | Blog Image 9 |
| `apps/site/static/assets/blog/10.png` | 1672x941 | Blog Image 10 |
| `docs/paper/assets/elephant-logo.png` | 1024x1024 | Paper Product Logo |
| `docs/paper/assets/favicon.png` | 1024x1024 | Paper Product Favicon |

Do not regenerate these unless the lab brand itself changes:

- `docs/paper/assets/logo_AIL.png`
- `docs/paper/assets/agentic-intelligence-lab-logo.png`
- `docs/paper/assets/agentic-intelligence-lab-lockup.png`

## README Hero

Target: `apps/site/static/assets/resources/readme-1.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 README hero illustration for Elephant Agent.

Use a warm porcelain and soft matte glass visual system: warm ivory, greige, muted blue-gray ink lines, muted mint-gray panels, calm dimensional lighting, soft shadows, and exactly one amber Personal Model core accent.

Elephant Agent is a personal-model-first AI companion. It remembers less but understands deeper. It starts from the person, grows a correctable understanding, asks gently at the user's pace, reflects after the turn, and helps the user pick up the right thread.

Scene: a quiet personal path map. A calm porcelain elephant companion walks beside one person. A soft path flows across the image through symbolic people, places, risks, rhythms, decisions, and one central Personal Model core. The path should feel like returning to the right thread, not like a fantasy treasure map.

Composition: spacious 16:9 editorial documentation hero. Keep the elephant and person on the left third, the path and Personal Model core moving across the center and right. Use small symbolic objects, not detailed scenes. The image must work at README width.

Text: no title text, no paragraphs. If labels are needed, use only tiny abstract icon labels, not readable prose.

Avoid cyberpunk, neon, neural webs, realistic safari photography, childish cartoon baby elephant, busy map labels, floating stars, magic effects, and stock AI brain imagery.
```

## README Lenses

Target: `apps/site/static/assets/resources/readme-2.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 clean documentation diagram for Elephant Agent titled visually as "What Elephant Agent Learns".

Use a warm porcelain and soft matte glass visual system: warm ivory, greige, muted blue-gray ink, muted mint-gray panels, soft shadows, and one amber Personal Model core accent. It should match a native Mac product, not a web SaaS illustration.

Meaning: Elephant Agent grows a correctable Personal Model across four lenses: Identity, World, Pulse, and Journey. It is not a hidden profile or a memory database. It remembers less but understands deeper.

Composition: center a simple porcelain elephant-head Personal Model core. Around it place four large rounded panels in a balanced 2x2 layout: Identity, World, Pulse, Journey. Use one clear icon per panel: identity card, world/context globe, pulse wave, journey path. Connect the panels to the center with soft muted blue-gray paths. Place a small amber core dot at the center.

Text: use only these exact labels if text is included: Identity, World, Pulse, Journey, correctable, visible, evidence-backed. No bullet lists, no paragraphs, no tiny text.

Avoid dense technical boxes, realistic elephant anatomy, childish mascot styling, neon, neural webs, and generic chatbot imagery.
```

## Social Share Card

Target: `apps/site/static/assets/brand/social-share-card.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 social share card for Elephant Agent.

Use the Elephant Agent porcelain visual system: warm ivory, greige, muted blue-gray ink, soft matte glass, calm dimensional lighting, subtle shadows, and one amber Personal Model core accent.

Brand positioning: Elephant Agent is personal-model-first AI. It remembers less but understands deeper. It starts from the person, asks gently, reflects after the turn, and grows a correctable understanding over time.

Composition: large porcelain elephant-head logo mark on the left, quiet Personal Model path field on the right. The right side should show a soft returning thread, four subtle lens marks, and one amber core. Leave generous whitespace. Make it premium, calm, and editorial.

Text: include only this exact text, large and legible:
Elephant Agent
Personal-model-first AI. Remembers less, understands deeper.

Avoid extra slogans, tiny labels, screenshots, terminal windows, stock AI imagery, neon, cyberpunk, realistic safari photography, and childish cartoon style.
```

## Blog Cover

Target: `apps/site/static/assets/brand/blog-cover.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 blog cover image for Elephant Agent's essay "Personal-Model-First".

Use a warm porcelain and soft matte glass visual system: warm ivory, greige, muted blue-gray ink, muted mint-gray surfaces, calm dimensional lighting, soft shadows, and one amber Personal Model core accent.

Concept: a porcelain elephant companion studies a soft personal path map with one person. The map contains subtle symbols for people, projects, risks, rhythms, decisions, and four Personal Model lenses. The feeling should be thoughtful and durable: understanding that deepens over time.

Composition: editorial cover with a calm focal scene and clean negative space for headline overlay. Keep any drawn text out of the image. Place the porcelain elephant and map across the lower two thirds, with gentle spacious background above.

Avoid a baby mascot, realistic safari photography, dense notes, tiny labels, sci-fi AI visuals, neural webs, neon, and dramatic fantasy lighting.
```

## Website Herd Background

Target: `apps/site/static/assets/brand/elephant-herd.jpg`

Size: `2000x1333`

Prompt:

```text
Create one 2000x1333 stylized website background for Elephant Agent.

Use the Elephant Agent porcelain visual system: warm ivory, greige, muted blue-gray, matte glass softness, calm natural light, subtle shadows, and one or two tiny amber Personal Model core accents. This should replace realistic elephant photography while keeping a quiet sense of companionship and continuity.

Scene: a small stylized elephant herd represented as soft porcelain forms moving across a gentle abstract landscape. Their path should imply memory, care, continuity, and shared direction. The image must work behind glass UI overlays, so keep contrast low and the composition spacious.

Composition: broad atmospheric background, subject slightly off-center, with generous calm areas for overlays. No hard horizon, no busy scenery, no photographic texture.

Avoid realistic safari photography, wildlife documentary style, neon, fantasy, childish cartoon, detailed faces, dense objects, and any text.
```

## Website Savanna Background

Target: `apps/site/static/assets/brand/elephant-savanna-snr.jpg`

Size: `2560x1440`

Prompt:

```text
Create one 2560x1440 wide website background for Elephant Agent.

Use the Elephant Agent porcelain visual system: warm greige canvas, ivory porcelain forms, muted blue-gray linework, soft matte glass, calm dimensional lighting, and restrained amber core accents.

Scene: an abstract savanna-like continuity landscape, but not realistic photography. A quiet porcelain elephant silhouette appears as a soft presence in the distance. Curved path lines move through people, place markers, risks, rhythms, and a Personal Model core. The image should feel like a living map of understanding, not a literal safari scene.

Composition: very wide and overlay-friendly. Keep the left side calmer for UI text, and place more path detail toward the right and lower areas. Low contrast, premium, quiet.

Avoid stock photo realism, animals rendered as realistic wildlife, neon AI graphics, dense map labels, childish cartoon style, and visible text.
```

## Website Elephant Texture

Target: `apps/site/static/assets/brand/elephant-body-image-02.webp`

Size: `1600x868`

Prompt:

```text
Create one 1600x868 contextual website texture for Elephant Agent.

Use the Elephant Agent porcelain visual system: warm ivory, greige, muted blue-gray, matte glass softness, soft shadows, and a single amber accent. The image should replace a realistic elephant body photo.

Scene: a close but abstract porcelain elephant presence, cropped like a quiet texture rather than a hero image. Show only a large soft ear curve, part of the head, and a gentle trunk path. The form should be recognizable but subtle enough to sit behind UI content.

Composition: atmospheric, low-contrast, edge-to-edge texture, no central loud subject. Keep safe empty areas for overlay text.

Avoid realistic skin texture, wildlife photography, cute cartoon face, neon effects, busy background, and any text.
```

## Paper Figure 1

Target: `apps/site/static/assets/resources/paper-1.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 paper figure for Elephant Agent: "Personal-Model-First Memory for Personal AI".

Use a publication-ready porcelain technical illustration style: warm ivory, greige, muted blue-gray ink, soft matte glass panels, precise rounded shapes, calm shadows, and one amber Personal Model core. It must feel consistent with a premium Mac app visual system.

Meaning: Elephant Agent is not a memory database. It is an understanding system. Show how a person and their path feed a correctable Personal Model, with surrounding layers for Elephant State, Episode/Loop/Step Trail, Contextual Recall, and Background Learning.

Composition: landscape paper figure. Left side: person and calm porcelain elephant companion. Center: amber Personal Model core. Right side: five system layer panels connected by a returning path. Use sparse labels only.

Text: if labels are included, use only these exact labels: Personal Model, Elephant State, Step Trail, Contextual Recall, Background Learning.

Avoid dense UI mockups, tiny paragraphs, neural network webs, cyberpunk, childish mascot style, and unrelated icons.
```

## Paper Figure 2

Target: `apps/site/static/assets/resources/paper-2.png`

Size: `1448x1086`

Prompt:

```text
Create one 1448x1086 paper architecture figure for Elephant Agent: "Personal-Model-First Memory Architecture".

Use a warm porcelain and soft matte glass technical diagram style: warm ivory, greige, muted blue-gray ink, muted mint-gray surfaces, soft shadows, rounded panels, and one amber Personal Model core accent.

Meaning: show the five product-facing memory and understanding layers. Personal Model is durable truth. Elephant State keeps the current identity and continuation note. Episode/Loop/Step Trail is evidence. Contextual Recall retrieves support. Background Learning turns evidence into governed updates.

Composition: vertical stacked architecture with five large rounded panels, connected by soft path arrows. Put the amber core in the Personal Model layer. Show tiny evidence chips moving from Step Trail through Recall and Background Learning into the core.

Text: use only these labels: Personal Model, Elephant State, Episode / Loop / Step Trail, Contextual Recall, Background Learning, Evidence, Governed update.

Avoid small unreadable text, database-cylinder cliches, neon AI visuals, realistic animals, and busy diagrams.
```

## Paper Figure 3

Target: `apps/site/static/assets/resources/paper-3.png`

Size: `1448x1086`

Prompt:

```text
Create one 1448x1086 paper figure for Elephant Agent: "Memory Evaluation Lifecycle".

Use a warm porcelain publication diagram style: ivory and greige background, muted blue-gray ink, soft matte glass panels, calm shadows, and a single amber core accent for durable Personal Model truth.

Meaning: show how evidence becomes useful only when it improves future judgment. The lifecycle should include evidence captured, later value, dashboard inspection, user correction, and claim update. The visual should make correction and provenance feel central.

Composition: a circular but spacious lifecycle flow with five large stations. Place the amber Personal Model core in the center. Use small evidence cards, a gentle question mark, a correction checkmark, and a soft returning path.

Text: use only these exact labels: Evidence, Later value, Inspect, Correct, Claim update.

Avoid dense text, tiny arrows, neon, neural networks, magic stars, and childish cartoon styling.
```

## Paper Figure 4

Target: `apps/site/static/assets/resources/paper-4.png`

Size: `1448x1086`

Prompt:

```text
Create one 1448x1086 paper figure for Elephant Agent: "Contextual Recall Is Support, Not Truth".

Use the Elephant Agent porcelain technical diagram style: warm ivory, greige, muted blue-gray ink, soft matte glass panels, precise rounded shapes, soft shadows, and one amber Personal Model core accent.

Meaning: recall can retrieve support from evidence, but durable truth changes only through governed Personal Model updates. Show a clear boundary between retrieved support and active claims.

Composition: three-column diagram. Left: Evidence Trail with Step records. Middle: Contextual Recall lens/search support. Right: Personal Model claims with strong match, weak match, and no match states. Put an amber core only on the durable Personal Model side. Use a visible but soft boundary line between support and truth.

Text: use only these labels: Evidence Trail, Contextual Recall, Support, Personal Model Truth, strong, weak, no match.

Avoid dense UI screenshots, tiny code, cyberpunk search graphics, neural webs, and decorative stars.
```

## Paper Figure 5

Target: `apps/site/static/assets/resources/paper-5.png`

Size: `1448x1086`

Prompt:

```text
Create one 1448x1086 paper figure for Elephant Agent: "Proactive Curiosity Keeps the Personal Model Alive".

Use a warm porcelain and soft matte glass diagram style: ivory, greige, muted blue-gray ink, muted mint-gray surfaces, soft shadows, and a single amber Personal Model core accent.

Meaning: Elephant Agent asks gently when one answer would change future help. Curiosity is visible, optional, and user-paced. It is not a survey or hidden profiling.

Composition: center a Personal Model core with four incoming signals: gap, conflict, stale pulse, adaptation. These feed one gentle question card. Below or beside it show three calm effort states: quiet, balanced, active. Use one path back into governed claim update.

Text: use only these labels: gap, conflict, stale pulse, adaptation, one gentle question, quiet, balanced, active.

Avoid interrogation imagery, survey forms, many question marks, neon, cute baby elephant mascot, and text-heavy layouts.
```

## Paper Figure 6

Target: `apps/site/static/assets/resources/paper-6.png`

Size: `1448x1086`

Prompt:

```text
Create one 1448x1086 paper figure for Elephant Agent: "Runtime Layers and Continuity".

Use the Elephant Agent porcelain system style: warm ivory, greige, muted blue-gray ink, soft matte glass panels, rounded geometry, calm shadows, and one amber core accent.

Meaning: show how a wake session moves through Personal Model, Elephant State, Episode, Loop, Step, Contextual Recall, and Background Learning while maintaining a continuity line.

Composition: calm vertical runtime stack. Use broad rounded panels with a continuous path line running through them. The path should feel like picking up the right thread. Show current-turn support as muted blue-gray, and governed durable updates as amber.

Text: use only these labels: Personal Model, Elephant State, Episode, Loop, Step, Contextual Recall, Background Learning, continuity.

Avoid complex flowchart clutter, tiny fields, code snippets, database icons, neon, and realistic elephant photography.
```

## Paper Figure 7

Target: `apps/site/static/assets/resources/paper-7.png`

Size: `1448x1086`

Prompt:

```text
Create one 1448x1086 paper figure for Elephant Agent: "Multilingual Hybrid Time-Aware Search".

Use a warm porcelain technical diagram style: ivory, greige, muted blue-gray ink, soft matte glass panels, precise rounded shapes, soft shadows, and a single amber Personal Model core accent.

Meaning: show how mixed-language user queries are shaped into variants, matched through lexical, semantic, topic, and time signals, fused into ranking, and returned as either Personal Model claim support or Conversation trail provenance.

Composition: left-to-right flow. Left: mixed-language query card. Middle: four signal lanes labeled lexical, semantic, topic, time. Center-right: evidence fusion and ranking. Right: two possible outputs, claim support and conversation trail. Amber only marks durable claim support.

Text: use only these labels: Query, lexical, semantic, topic, time, evidence fusion, ranking, claim support, conversation trail.

Avoid tiny language samples, illegible glyphs, neon networks, code-heavy UI, and crowded arrows.
```

## Blog Image 1

Target: `apps/site/static/assets/blog/1.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 blog hero image for Elephant Agent: "Personal-Model-First".

Use the Elephant Agent porcelain editorial style: warm ivory, greige, muted blue-gray ink, muted mint-gray planes, soft matte glass, calm dimensional lighting, soft shadows, and one amber Personal Model core accent.

Concept: a porcelain elephant companion and one person study a living path map. The map shows people, projects, risks, rhythms, decisions, and a central Personal Model core. The image should communicate that personal AI starts from understanding the person, not from a blank prompt.

Composition: wide editorial blog cover. Keep the main scene grounded and readable, with enough negative space for page layout. The elephant should feel calm and wise, not cute or childish.

Text: no embedded title text. No paragraphs.

Avoid safari realism, baby mascot style, cyberpunk AI, neural webs, dense labels, and magic stars.
```

## Blog Image 2

Target: `apps/site/static/assets/blog/2.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 blog illustration for Elephant Agent: "The Personal Model".

Use a warm porcelain and matte glass style: ivory, greige, muted blue-gray ink, muted mint-gray panels, calm shadows, and one amber Personal Model core accent.

Meaning: the Personal Model is explicit, inspectable, and correctable. It is not a hidden profile, a longer prompt, or a vector database with a nicer name.

Composition: center a porcelain elephant-head Personal Model core. Around it place four large rounded lens zones: Identity, World, Pulse, Journey. Add small evidence chips and correction marks around the lenses. Make it warm and editorial, not a strict enterprise diagram.

Text: use only these exact labels if text is included: Identity, World, Pulse, Journey, active, retired, disputed, evidence.

Avoid tiny bullet lists, dense model fields, neural webs, childish cartoon, and realistic animal rendering.
```

## Blog Image 3

Target: `apps/site/static/assets/blog/3.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 blog diagram for Elephant Agent: "Elephant Memory Architecture".

Use the Elephant Agent porcelain technical editorial style: warm ivory, greige, muted blue-gray ink, soft matte glass rounded panels, calm shadows, and one amber Personal Model core accent.

Meaning: memory is an architecture for turning experience into judgment. The five layers are Personal Model, Elephant State, Episode/Loop/Step Trail, Contextual Recall, and Background Learning.

Composition: a wide layered architecture map. Place the amber Personal Model core near the top or center. Use broad layers and returning path connectors. Add a subtle porcelain elephant presence as a quiet side marker, not a mascot.

Text: use only these labels: Personal Model, Elephant State, Step Trail, Contextual Recall, Background Learning.

Avoid dense implementation details, small tables, code, neon AI visuals, and stock diagram cliches.
```

## Blog Image 4

Target: `apps/site/static/assets/blog/4.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 blog diagram for Elephant Agent: "Contextual Recall".

Use a warm porcelain diagram style: ivory and greige background, muted blue-gray ink, soft matte glass cards, calm shadows, rounded connectors, and one amber Personal Model core accent.

Meaning: Contextual Recall retrieves support from Steps and Facts for the current turn. Retrieved material is support, not durable truth.

Composition: left side shows current user query and conversation Steps. Center shows a local semantic index and lexical recall lens. Right side shows Personal Model claims and current-turn support. Draw a clear soft boundary between support and truth.

Text: use only these labels: Query, Steps, Local semantic index, Personal Model claims, current-turn support, not truth.

Avoid screenshots, raw terminal UI, dense fields, neural webs, neon, and childish mascot style.
```

## Blog Image 5

Target: `apps/site/static/assets/blog/5.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 editorial illustration for Elephant Agent: "The Core Bet".

Use the Elephant Agent porcelain editorial style: warm ivory, greige, muted blue-gray ink, soft matte glass, calm lighting, gentle shadows, and one amber Personal Model core accent.

Concept: a person and a calm porcelain elephant look at an open Personal Model notebook or path map. Around the central Personal Model are subtle orbiting capability icons: memory, skills, tools, models, cron, messaging, and UI. The visual should say that these capabilities orbit the Personal Model, not the other way around.

Composition: centered warm editorial scene, no technical clutter. Make the central amber core clearly more important than the surrounding capability icons.

Text: no embedded title text. If labels are needed, use only "Personal Model".

Avoid magical stars, complex orbit lines, toy mascot style, sci-fi dashboards, and stock productivity imagery.
```

## Blog Image 6

Target: `apps/site/static/assets/blog/6.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 warm blog illustration for Elephant Agent: "Curiosity Is the Learning Loop".

Use a warm porcelain and soft matte glass style: ivory, greige, muted blue-gray ink, muted mint-gray, soft shadows, calm lighting, and one amber Personal Model core accent.

Meaning: Elephant Agent asks gently when one answer would change future help. Curiosity is optional, visible, user-paced, and never a survey.

Composition: a calm porcelain elephant companion offers one small question card to a seated person. Nearby are three subtle effort states: quiet, balanced, active. A soft path from the question card returns to the Personal Model core.

Text: use only these labels if included: quiet, balanced, active, one question.

Avoid interrogation scenes, survey forms, many question marks, chatbot bubbles, childish elephant mascot, and neon effects.
```

## Blog Image 7

Target: `apps/site/static/assets/blog/7.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 blog diagram for Elephant Agent: "Background Learning".

Use the Elephant Agent porcelain technical editorial style: warm ivory, greige, muted blue-gray ink, soft matte glass panels, calm shadows, and one amber Personal Model core accent.

Meaning: background learning runs after the turn. Episode close, diary, reflect, dream, and compaction triggers read evidence and write governed updates through Personal Model, Questions, Diary, or Skills tools.

Composition: warm night-desk mood combined with a clean system diagram. Left side shows triggers: episode close, diary, reflect, dream, compaction. Center shows evidence packet. Right side shows governed updates to Personal Model and Questions. Use the amber core only for durable understanding.

Text: use only these labels: episode close, diary, reflect, dream, compaction, evidence packet, governed updates.

Avoid dark cyberpunk, busy office scenes, raw code, tiny logs, and toy mascot style.
```

## Blog Image 8

Target: `apps/site/static/assets/blog/8.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 blog illustration for Elephant Agent: "The Operator Surface".

Use a warm porcelain and soft matte glass Mac-product style: ivory, greige, muted blue-gray ink, muted mint-gray UI panels, calm shadows, and one amber Personal Model core accent.

Meaning: CLI, Dashboard, Chat, Messaging, Cron, Tools, and Skills are surfaces around the Personal Model. They should remain visible capabilities, not hidden personality changes.

Composition: center one amber Personal Model core inside a porcelain elephant-head mark. Around it place simple quiet Mac-like panels for CLI, Dashboard, Chat, Messaging, Cron, Tools, and Skills. Use soft connector paths. Keep it clean, not screenshot-heavy.

Text: use only these labels: CLI, Dashboard, Chat, Messaging, Cron, Tools, Skills.

Avoid real screenshots, terminal clutter, dense dashboards, neon, stock SaaS cards, and cartoon mascots.
```

## Blog Image 9

Target: `apps/site/static/assets/blog/9.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 blog technical illustration for Elephant Agent: "Multilingual, Hybrid, Time-Aware Search".

Use the Elephant Agent porcelain technical style: warm ivory, greige, muted blue-gray ink, soft matte glass cards, precise rounded shapes, calm shadows, and one amber Personal Model core accent.

Meaning: real personal context is multilingual, hybrid, and time-sensitive. Search combines semantic, lexical, topic, time, and evidence signals to recover the right path with the right confidence.

Composition: left side shows a mixed-language query as abstract glyph cards, not readable sentences. Middle shows signal lanes: semantic, lexical, topic, time. Right side shows evidence fusion, confidence, and right-thread recovery. Put a small amber core on durable claim support.

Text: use only these labels: semantic, lexical, topic, time, evidence, confidence, right thread.

Avoid illegible language paragraphs, code, neon graphs, neural webs, and crowded arrows.
```

## Blog Image 10

Target: `apps/site/static/assets/blog/10.png`

Size: `1672x941`

Prompt:

```text
Create one 1672x941 blog diagram for Elephant Agent: "Claim-Aware Recall".

Use the Elephant Agent porcelain technical editorial style: warm ivory, greige, muted blue-gray ink, soft matte glass cards, calm shadows, and one amber Personal Model core accent.

Meaning: Elephant Agent searches active claims, not a pile of notes. Recall can return strong match, weak clue, or no match. No match is a safe boundary, not a failure.

Composition: left side: user question. Center: Personal Model claim cards with lens and evidence marks. Right side: three output cards: strong match, weak clue, no match. Make the no-match card calm and protective, not alarming. Use amber only for strong durable claim support.

Text: use only these labels: Question, active claims, evidence, strong match, weak clue, no match.

Avoid tiny fields, dense database rows, neon, scary warning icons, toy mascot, and generic search UI.
```

## Paper Product Logo

Target: `docs/paper/assets/elephant-logo.png`

Size: `1024x1024`

Prompt:

```text
Create one 1024x1024 square Elephant Agent product logo for use inside an academic paper.

Use the approved Elephant Agent app icon direction: warm porcelain elephant head in profile, oversized soft ear, simple curved trunk forming a returning path, one amber Personal Model core accent, and a warm greige rounded-square background. The material should feel like soft matte glass and porcelain, with calm dimensional lighting and gentle shadow.

The logo must be publication-safe at small size, visually consistent with the macOS app icon, and readable in both PDF and web contexts.

No text, no letters, no full body, no legs, no star, no orbit, no neural network, no props, no watermark.
```

## Paper Product Favicon

Target: `docs/paper/assets/favicon.png`

Size: `1024x1024`

Prompt:

```text
Create one 1024x1024 square Elephant Agent favicon for paper and web use.

Use the same approved Elephant Agent app icon direction: a warm porcelain elephant-head mark in profile, oversized ear, simple trunk as a returning path, one amber Personal Model core, and a warm greige rounded-square background. Keep the silhouette simple and strong so it reads at 16px and 32px.

The result should match the macOS app icon style and the paper product logo.

No text, no letters, no full body, no legs, no star, no orbit, no neural network, no props, no watermark.
```

## Review Checklist

Accept an image only if all of these are true:

- It matches warm porcelain, greige, muted blue-gray, and amber core styling.
- It feels like a calm Mac-native personal AI companion.
- The Personal Model or right-thread idea is visible when relevant.
- Text, if present, is sparse and legible.
- The elephant does not become a baby toy, safari photo, or generic AI mascot.
- The image works at the target aspect ratio without cropping important content.

Reject and regenerate if any of these appear:

- Neon, cyberpunk, glowing neural web, or generic AI brain.
- Dense illegible text.
- A cute full-body baby elephant as the main visual.
- Random stars, magic wands, or decorative sparkles.
- Realistic wildlife photography.
- UI screenshots that look like a different product.
