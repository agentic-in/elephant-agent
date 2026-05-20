import SwiftUI

enum ElephantMascotMood: Equatable {
    case idle
    case listening
    case thinking
    case tooling
    case speaking
    case happy
    case concerned
    case sleeping

    var accessibilityLabel: String {
        switch self {
        case .idle: return "Elephant is ready"
        case .listening: return "Elephant is listening"
        case .thinking: return "Elephant is thinking"
        case .tooling: return "Elephant is using tools"
        case .speaking: return "Elephant is replying"
        case .happy: return "Elephant is pleased"
        case .concerned: return "Elephant needs attention"
        case .sleeping: return "Elephant is resting"
        }
    }
}

struct ElephantMascotView: View {
    var mood: ElephantMascotMood = .idle
    var size: CGFloat = 160
    var showsMemoryField = true
    var animated = true
    var energy: CGFloat = 1.0

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let shouldAnimate = animated && !reduceMotion

        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: !shouldAnimate)) { timeline in
            let phase = shouldAnimate ? timeline.date.timeIntervalSinceReferenceDate : 0
            let pose = ElephantMascotPose(mood: mood, phase: phase, energy: energy)

            ZStack {
                if showsMemoryField {
                    ElephantMascotMemoryField(mood: mood, phase: phase, animated: shouldAnimate, energy: energy)
                        .opacity(pose.auraOpacity)
                        .allowsHitTesting(false)
                }

                Ellipse()
                    .fill(.black.opacity(0.10))
                    .frame(width: size * 0.62, height: size * 0.11)
                    .blur(radius: size * 0.018)
                    .offset(y: size * 0.35)
                    .scaleEffect(x: 1.0 - pose.bob / 60.0, y: 1.0)

                mascotBody(pose: pose)
                    .scaleEffect(pose.breath, anchor: .bottom)
                    .offset(y: pose.bob)

                if mood == .listening || mood == .speaking {
                    ElephantSignalMarks(mood: mood, phase: phase, animated: shouldAnimate)
                        .frame(width: size * 0.34, height: size * 0.34)
                        .offset(x: size * 0.36, y: -size * 0.12)
                        .opacity(0.82)
                }
            }
            .frame(width: size, height: size)
            .contentShape(Rectangle())
            .accessibilityLabel(mood.accessibilityLabel)
        }
    }

    private func mascotBody(pose: ElephantMascotPose) -> some View {
        ZStack {
            if showsMemoryField {
                stickerBackplate
            }
            feet
            ears(pose: pose)
            torso
            head
            topTuft(pose: pose)
            tusks(pose: pose)
            trunk(pose: pose)
            face(pose: pose)
        }
        .rotationEffect(.degrees(pose.headTilt))
    }

    private var stickerBackplate: some View {
        ZStack {
            Ellipse()
                .frame(width: size * 0.98, height: size * 0.70)
                .offset(y: size * 0.00)
            Circle()
                .frame(width: size * 0.43, height: size * 0.43)
                .offset(x: -size * 0.35, y: -size * 0.07)
            Circle()
                .frame(width: size * 0.43, height: size * 0.43)
                .offset(x: size * 0.35, y: -size * 0.07)
            Ellipse()
                .frame(width: size * 0.68, height: size * 0.58)
                .offset(y: size * 0.13)
        }
        .foregroundStyle(Color(red: 1.00, green: 0.96, blue: 0.88).opacity(0.70))
        .blur(radius: size * 0.006)
        .shadow(color: .black.opacity(0.08), radius: size * 0.040, y: size * 0.020)
    }

    private var torso: some View {
        ZStack {
            Ellipse()
                .fill(
                    LinearGradient(
                        colors: [
                            Color(red: 0.78, green: 0.84, blue: 0.90),
                            Color(red: 0.56, green: 0.65, blue: 0.75)
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .frame(width: size * 0.61, height: size * 0.55)
                .offset(y: size * 0.17)

            Ellipse()
                .fill(.white.opacity(0.22))
                .frame(width: size * 0.29, height: size * 0.16)
                .blur(radius: size * 0.020)
                .offset(x: -size * 0.12, y: -size * 0.01)

            Ellipse()
                .fill(Color(red: 0.90, green: 0.94, blue: 0.98).opacity(0.22))
                .frame(width: size * 0.36, height: size * 0.30)
                .offset(y: size * 0.19)
        }
    }

    private var head: some View {
        ZStack {
            Ellipse()
                .fill(
                    LinearGradient(
                        colors: [
                            Color(red: 0.86, green: 0.91, blue: 0.96),
                            Color(red: 0.63, green: 0.72, blue: 0.82)
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .frame(width: size * 0.62, height: size * 0.53)
                .offset(y: -size * 0.060)

            Ellipse()
                .fill(.white.opacity(0.27))
                .frame(width: size * 0.27, height: size * 0.14)
                .blur(radius: size * 0.012)
                .offset(x: -size * 0.13, y: -size * 0.20)
        }
    }

    private var feet: some View {
        HStack(spacing: size * 0.16) {
            foot
            foot
        }
        .offset(y: size * 0.405)
    }

    private var foot: some View {
        Capsule(style: .continuous)
            .fill(Color(red: 0.49, green: 0.58, blue: 0.68))
            .frame(width: size * 0.18, height: size * 0.10)
            .overlay(
                Capsule(style: .continuous)
                    .stroke(.white.opacity(0.18), lineWidth: max(1, size * 0.008))
            )
    }

    private func ears(pose: ElephantMascotPose) -> some View {
        ZStack {
            ElephantEar()
                .fill(
                    LinearGradient(
                        colors: [
                            Color(red: 0.73, green: 0.78, blue: 0.83),
                            Color(red: 0.54, green: 0.60, blue: 0.67)
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .frame(width: size * 0.39, height: size * 0.51)
                .overlay(
                    ElephantEar()
                        .stroke(ElephantTheme.accent.opacity(0.14), lineWidth: max(1, size * 0.008))
                )
                .rotationEffect(.degrees(-14 + pose.leftEarAngle))
                .offset(x: -size * 0.335, y: -size * 0.055)

            ElephantEar()
                .fill(Color(red: 0.96, green: 0.70, blue: 0.74).opacity(0.36))
                .frame(width: size * 0.25, height: size * 0.34)
                .rotationEffect(.degrees(-14 + pose.leftEarAngle))
                .offset(x: -size * 0.325, y: -size * 0.035)

            ElephantEar()
                .fill(
                    LinearGradient(
                        colors: [
                            Color(red: 0.76, green: 0.80, blue: 0.84),
                            Color(red: 0.55, green: 0.61, blue: 0.68)
                        ],
                        startPoint: .topTrailing,
                        endPoint: .bottomLeading
                    )
                )
                .frame(width: size * 0.34, height: size * 0.46)
                .overlay(
                    ElephantEar()
                        .stroke(ElephantTheme.accent.opacity(0.12), lineWidth: max(1, size * 0.008))
                )
                .scaleEffect(x: -1, y: 1)
                .rotationEffect(.degrees(10 + pose.rightEarAngle))
                .offset(x: size * 0.325, y: -size * 0.045)

            ElephantEar()
                .fill(Color(red: 0.96, green: 0.70, blue: 0.74).opacity(0.32))
                .frame(width: size * 0.205, height: size * 0.30)
                .scaleEffect(x: -1, y: 1)
                .rotationEffect(.degrees(10 + pose.rightEarAngle))
                .offset(x: size * 0.318, y: -size * 0.028)
        }
    }

    private func topTuft(pose: ElephantMascotPose) -> some View {
        HStack(spacing: -size * 0.006) {
            Capsule(style: .continuous)
                .frame(width: size * 0.022, height: size * 0.085)
                .rotationEffect(.degrees(-18))
            Capsule(style: .continuous)
                .frame(width: size * 0.024, height: size * 0.10)
            Capsule(style: .continuous)
                .frame(width: size * 0.022, height: size * 0.082)
                .rotationEffect(.degrees(18))
        }
        .foregroundStyle(Color(red: 0.54, green: 0.63, blue: 0.72).opacity(0.88))
        .offset(x: -size * 0.02, y: -size * 0.345 + pose.bob * 0.10)
        .rotationEffect(.degrees(pose.headTilt * 0.35))
    }

    private func trunk(pose: ElephantMascotPose) -> some View {
        let tip = pose.naturalTrunkTip(size: size)
        let trunkPath = ElephantNaturalTrunk(curl: pose.trunkCurl, sway: pose.trunkSway, lift: pose.trunkLift)

        return ZStack {
            trunkPath
                .stroke(
                    Color(red: 0.31, green: 0.42, blue: 0.54).opacity(0.16),
                    style: StrokeStyle(lineWidth: size * 0.105, lineCap: .round, lineJoin: .round)
                )
                .frame(width: size, height: size)
                .shadow(color: Color(red: 0.27, green: 0.34, blue: 0.43).opacity(0.12), radius: size * 0.010, x: size * 0.004, y: size * 0.010)

            trunkPath
                .stroke(
                    LinearGradient(
                        colors: [
                            Color(red: 0.72, green: 0.82, blue: 0.91),
                            Color(red: 0.54, green: 0.66, blue: 0.77)
                        ],
                        startPoint: .top,
                        endPoint: .bottom
                    ),
                    style: StrokeStyle(lineWidth: size * 0.080, lineCap: .round, lineJoin: .round)
                )
                .frame(width: size, height: size)

            HStack(spacing: size * 0.010) {
                Circle()
                    .fill(Color(red: 0.18, green: 0.24, blue: 0.31).opacity(0.48))
                Circle()
                    .fill(Color(red: 0.18, green: 0.24, blue: 0.31).opacity(0.48))
            }
            .frame(width: size * 0.034, height: size * 0.010)
            .rotationEffect(.degrees(6 + pose.trunkSway * 0.08))
            .offset(x: tip.x + size * 0.010, y: tip.y + size * 0.003)
        }
    }

    private func tusks(pose: ElephantMascotPose) -> some View {
        ElephantSideTusk()
            .fill(
                LinearGradient(
                    colors: [
                        Color(red: 1.00, green: 0.97, blue: 0.86),
                        Color(red: 0.91, green: 0.84, blue: 0.66)
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
            )
            .frame(width: size * 0.052, height: size * 0.118)
            .rotationEffect(.degrees(-2 + pose.trunkSway * 0.08))
            .offset(x: size * 0.146, y: size * 0.098 + pose.trunkLift * size * 0.03)
            .opacity(pose.tuskOpacity * 0.56)
    }

    private func face(pose: ElephantMascotPose) -> some View {
        ZStack {
            if mood == .sleeping {
                sleepingEye(x: -size * 0.100)
                sleepingEye(x: size * 0.072)
            } else {
                eye(x: -size * 0.100, pose: pose)
                eye(x: size * 0.072, pose: pose)
                eyelashes(x: -size * 0.100, side: -1, pose: pose)
                eyelashes(x: size * 0.072, side: 1, pose: pose)
            }

            if mood == .concerned {
                eyebrow(x: -size * 0.105, angle: 18)
                eyebrow(x: size * 0.105, angle: -18)
            }

            Circle()
                .fill(Color(red: 0.98, green: 0.52, blue: 0.56).opacity(pose.blushOpacity))
                .frame(width: size * 0.064, height: size * 0.042)
                .offset(x: -size * 0.175, y: size * 0.030)

            Circle()
                .fill(Color(red: 0.98, green: 0.52, blue: 0.56).opacity(pose.blushOpacity * 0.86))
                .frame(width: size * 0.064, height: size * 0.042)
                .offset(x: size * 0.142, y: size * 0.030)
        }
        .offset(x: pose.gazeX * size * 0.012, y: -size * 0.145 + pose.gazeY * size * 0.010)
    }

    private func eye(x: CGFloat, pose: ElephantMascotPose) -> some View {
        ZStack {
            Capsule(style: .continuous)
                .fill(Color(red: 0.09, green: 0.10, blue: 0.11))
                .frame(width: size * 0.070, height: max(size * 0.008, size * 0.094 * pose.eyeOpen))

            Circle()
                .fill(.white.opacity(pose.eyeOpen > 0.25 ? 0.92 : 0.0))
                .frame(width: size * 0.020, height: size * 0.020)
                .offset(x: size * 0.014, y: -size * 0.020)

            Circle()
                .fill(.white.opacity(pose.eyeOpen > 0.25 ? 0.50 : 0.0))
                .frame(width: size * 0.010, height: size * 0.010)
                .offset(x: -size * 0.012, y: size * 0.018)
        }
        .offset(x: x, y: 0)
    }

    private func eyelashes(x: CGFloat, side: CGFloat, pose: ElephantMascotPose) -> some View {
        ZStack {
            eyelash(angle: side < 0 ? 34 : -34, length: 0.035)
                .offset(x: side * size * 0.018, y: -size * 0.046)
            eyelash(angle: side < 0 ? 10 : -10, length: 0.038)
                .offset(x: side * size * 0.034, y: -size * 0.040)
            eyelash(angle: side < 0 ? -14 : 14, length: 0.030)
                .offset(x: side * size * 0.048, y: -size * 0.026)
        }
        .opacity(pose.eyeOpen > 0.35 ? 0.72 : 0.0)
        .offset(x: x, y: 0)
    }

    private func eyelash(angle: Double, length: CGFloat) -> some View {
        Capsule(style: .continuous)
            .fill(Color(red: 0.10, green: 0.12, blue: 0.14).opacity(0.78))
            .frame(width: size * 0.008, height: size * length)
            .rotationEffect(.degrees(angle))
    }

    private func sleepingEye(x: CGFloat) -> some View {
        Path { path in
            let centerX = size * 0.50 + x
            path.move(to: CGPoint(x: centerX - size * 0.040, y: size * 0.51))
            path.addQuadCurve(
                to: CGPoint(x: centerX + size * 0.040, y: size * 0.51),
                control: CGPoint(x: centerX, y: size * 0.48)
            )
        }
        .stroke(Color(red: 0.12, green: 0.14, blue: 0.16).opacity(0.80), style: StrokeStyle(lineWidth: size * 0.012, lineCap: .round))
        .frame(width: size, height: size)
        .offset(y: -size * 0.010)
    }

    private func eyebrow(x: CGFloat, angle: Double) -> some View {
        Capsule(style: .continuous)
            .fill(Color(red: 0.22, green: 0.24, blue: 0.27).opacity(0.72))
            .frame(width: size * 0.060, height: size * 0.010)
            .rotationEffect(.degrees(angle))
            .offset(x: x, y: -size * 0.065)
    }

}

private struct ElephantMascotPose {
    var bob: CGFloat
    var breath: CGFloat
    var leftEarAngle: Double
    var rightEarAngle: Double
    var trunkSway: CGFloat
    var trunkLift: CGFloat
    var trunkCurl: CGFloat
    var headTilt: Double
    var eyeOpen: CGFloat
    var gazeX: CGFloat
    var gazeY: CGFloat
    var blushOpacity: CGFloat
    var auraOpacity: Double
    var tuskOpacity: Double

    init(mood: ElephantMascotMood, phase: TimeInterval, energy: CGFloat) {
        let idleWave = sin(phase * 1.55)
        let quickWave = sin(phase * 4.20)
        let slowWave = sin(phase * 0.82)
        let blink = Self.blinkOpen(phase: phase)
        let energyScale = max(0.60, min(1.90, energy))

        bob = CGFloat(idleWave) * 1.8
        breath = 1.0 + CGFloat(sin(phase * 1.25)) * 0.018
        leftEarAngle = Double(slowWave) * 2.4
        rightEarAngle = -Double(slowWave) * 2.1
        trunkSway = CGFloat(sin(phase * 1.35)) * 5.0
        trunkLift = 0
        trunkCurl = CGFloat(sin(phase * 1.10)) * 0.08
        headTilt = Double(sin(phase * 0.90)) * 1.1
        eyeOpen = blink
        gazeX = 0
        gazeY = 0
        blushOpacity = 0.22
        auraOpacity = 0.52
        tuskOpacity = 0.82

        switch mood {
        case .idle:
            break
        case .listening:
            bob = CGFloat(sin(phase * 2.2)) * 1.2
            breath = 1.0 + CGFloat(sin(phase * 2.0)) * 0.012
            leftEarAngle = -10 + Double(sin(phase * 2.5)) * 2.5
            rightEarAngle = 10 - Double(sin(phase * 2.3)) * 2.5
            trunkSway = CGFloat(sin(phase * 2.7)) * 3.2
            trunkLift = -0.18
            trunkCurl = 0.18
            eyeOpen = max(0.92, blink)
            gazeX = 1.2
            gazeY = -0.3
            blushOpacity = 0.30
            auraOpacity = 0.72
        case .thinking:
            bob = CGFloat(sin(phase * 1.4)) * 1.0
            leftEarAngle = 4 + Double(sin(phase * 1.8)) * 1.6
            rightEarAngle = -5 - Double(sin(phase * 1.6)) * 1.6
            trunkSway = -8 + CGFloat(sin(phase * 1.4)) * 2.4
            trunkLift = -0.28
            trunkCurl = 0.46 + CGFloat(sin(phase * 1.8)) * 0.05
            headTilt = -3.8 + Double(sin(phase * 0.8)) * 1.2
            eyeOpen = min(0.72, blink)
            gazeX = -1.2
            gazeY = -1.0
            blushOpacity = 0.12
            auraOpacity = 0.90
        case .tooling:
            bob = CGFloat(sin(phase * 2.0)) * 1.4
            leftEarAngle = -4 + Double(sin(phase * 3.1)) * 2.0
            rightEarAngle = 4 - Double(sin(phase * 2.8)) * 2.0
            trunkSway = 7 + CGFloat(sin(phase * 2.4)) * 4.0
            trunkLift = -0.12
            trunkCurl = -0.30 + CGFloat(sin(phase * 2.2)) * 0.06
            headTilt = 2.6 + Double(sin(phase * 1.2)) * 0.8
            eyeOpen = max(0.74, blink)
            gazeX = 1.5
            gazeY = -0.5
            blushOpacity = 0.16
            auraOpacity = 1.0
        case .speaking:
            bob = CGFloat(sin(phase * 3.2)) * 1.6
            breath = 1.0 + CGFloat(sin(phase * 2.6)) * 0.020
            leftEarAngle = Double(sin(phase * 3.0)) * 3.2
            rightEarAngle = -Double(sin(phase * 2.7)) * 3.2
            trunkSway = CGFloat(sin(phase * 4.4)) * 8.2
            trunkLift = -0.08
            trunkCurl = CGFloat(sin(phase * 5.0)) * 0.12
            eyeOpen = max(0.80, blink)
            blushOpacity = 0.32
            auraOpacity = 0.68
        case .happy:
            bob = -abs(CGFloat(quickWave)) * 5.0 + CGFloat(sin(phase * 2.1)) * 1.4
            breath = 1.035 + CGFloat(sin(phase * 2.5)) * 0.015
            leftEarAngle = -8 + Double(sin(phase * 5.0)) * 4.2
            rightEarAngle = 8 - Double(sin(phase * 4.8)) * 4.2
            trunkSway = CGFloat(sin(phase * 5.5)) * 9.0
            trunkLift = -0.16
            trunkCurl = 0.24
            eyeOpen = 0.28
            blushOpacity = 0.42
            auraOpacity = 0.80
        case .concerned:
            bob = 1.8 + CGFloat(sin(phase * 0.9)) * 0.6
            breath = 0.99
            leftEarAngle = 14 + Double(sin(phase * 1.1)) * 1.0
            rightEarAngle = -14 - Double(sin(phase * 1.0)) * 1.0
            trunkSway = CGFloat(sin(phase * 0.8)) * 2.0
            trunkLift = 0.24
            trunkCurl = -0.18
            headTilt = Double(sin(phase * 0.8)) * 0.6
            eyeOpen = min(0.82, blink)
            gazeY = 0.8
            blushOpacity = 0.08
            auraOpacity = 0.34
            tuskOpacity = 0.60
        case .sleeping:
            bob = CGFloat(sin(phase * 1.10)) * 2.1
            breath = 1.0 + CGFloat(sin(phase * 1.05)) * 0.026
            leftEarAngle = 7 + Double(sin(phase * 1.25)) * 1.8
            rightEarAngle = -7 - Double(sin(phase * 1.20)) * 1.8
            trunkSway = 4 + CGFloat(sin(phase * 1.25)) * 3.2
            trunkLift = -0.08
            trunkCurl = 0.30 + CGFloat(sin(phase * 1.45)) * 0.06
            headTilt = Double(sin(phase * 0.70)) * 1.8
            eyeOpen = 0.10
            gazeY = 0
            blushOpacity = 0.25
            auraOpacity = 0.74
            tuskOpacity = 0.76
        }

        bob *= energyScale
        breath = 1.0 + (breath - 1.0) * energyScale
        leftEarAngle *= Double(energyScale)
        rightEarAngle *= Double(energyScale)
        trunkSway *= energyScale
        headTilt *= Double(energyScale)
    }

    func trunkTip(size: CGFloat) -> CGPoint {
        let curlBoost = max(-0.18, min(0.34, trunkCurl)) * size * 0.11
        return CGPoint(
            x: size * 0.315 + trunkSway * size * 0.0025 + curlBoost,
            y: size * (0.070 + trunkLift * 0.10)
        )
    }

    func naturalTrunkTip(size: CGFloat) -> CGPoint {
        let curlBoost = max(-0.10, min(0.30, trunkCurl)) * size * 0.020
        return CGPoint(
            x: size * 0.276 + trunkSway * size * 0.0009 + curlBoost,
            y: size * (0.158 + trunkLift * 0.032)
        )
    }

    private static func blinkOpen(phase: TimeInterval) -> CGFloat {
        let cycle = phase.truncatingRemainder(dividingBy: 4.6)
        if cycle > 4.24 && cycle < 4.40 {
            return 0.10
        }
        if cycle > 4.40 && cycle < 4.54 {
            return 0.55
        }
        return 1.0
    }
}

private struct ElephantEar: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.midX * 1.04, y: rect.minY + rect.height * 0.02))
        path.addCurve(
            to: CGPoint(x: rect.maxX * 0.98, y: rect.maxY * 0.64),
            control1: CGPoint(x: rect.maxX * 1.05, y: rect.minY + rect.height * 0.06),
            control2: CGPoint(x: rect.maxX * 1.10, y: rect.maxY * 0.40)
        )
        path.addCurve(
            to: CGPoint(x: rect.midX * 0.78, y: rect.maxY * 0.97),
            control1: CGPoint(x: rect.maxX * 0.90, y: rect.maxY * 0.91),
            control2: CGPoint(x: rect.midX * 1.14, y: rect.maxY)
        )
        path.addCurve(
            to: CGPoint(x: rect.minX + rect.width * 0.06, y: rect.maxY * 0.55),
            control1: CGPoint(x: rect.minX + rect.width * 0.04, y: rect.maxY * 0.92),
            control2: CGPoint(x: rect.minX - rect.width * 0.02, y: rect.maxY * 0.70)
        )
        path.addCurve(
            to: CGPoint(x: rect.midX * 1.04, y: rect.minY + rect.height * 0.02),
            control1: CGPoint(x: rect.minX + rect.width * 0.05, y: rect.maxY * 0.24),
            control2: CGPoint(x: rect.minX + rect.width * 0.28, y: rect.minY + rect.height * 0.02)
        )
        path.closeSubpath()
        return path
    }
}

private struct ElephantTrunk: Shape {
    var curl: CGFloat
    var sway: CGFloat
    var lift: CGFloat

    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height)
        let side: CGFloat = 1
        let curlStrength = 1.0 + max(-0.18, min(0.34, curl))
        let start = CGPoint(x: rect.midX - side * s * 0.010, y: rect.midY - s * 0.095)
        let lower = CGPoint(
            x: rect.midX + side * s * (0.012 + sway * 0.0011),
            y: rect.midY + s * (0.180 + lift * 0.16)
        )
        let curlBottom = CGPoint(
            x: rect.midX + side * s * (0.205 + curlStrength * 0.040),
            y: rect.midY + s * (0.205 + lift * 0.07)
        )
        let end = CGPoint(
            x: rect.midX + side * s * (0.315 + curlStrength * 0.030) + sway * s * 0.0025,
            y: rect.midY + s * (0.070 + lift * 0.10)
        )

        var path = Path()
        path.move(to: start)
        path.addCurve(
            to: lower,
            control1: CGPoint(x: rect.midX + side * s * 0.014 + sway * s * 0.0017, y: rect.midY - s * 0.010),
            control2: CGPoint(x: rect.midX - side * s * 0.020, y: rect.midY + s * (0.115 + lift * 0.12))
        )
        path.addCurve(
            to: curlBottom,
            control1: CGPoint(x: rect.midX + side * s * 0.010, y: rect.midY + s * (0.305 + lift * 0.04)),
            control2: CGPoint(x: rect.midX + side * s * 0.150, y: rect.midY + s * (0.315 + lift * 0.04))
        )
        path.addCurve(
            to: end,
            control1: CGPoint(x: rect.midX + side * s * (0.345 + curlStrength * 0.020), y: rect.midY + s * (0.185 + lift * 0.04)),
            control2: CGPoint(x: rect.midX + side * s * (0.385 + curlStrength * 0.020), y: rect.midY + s * (0.070 + lift * 0.06))
        )
        return path
    }
}

private struct ElephantNaturalTrunk: Shape {
    var curl: CGFloat
    var sway: CGFloat
    var lift: CGFloat

    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height)
        let swayX = sway * s * 0.0007
        let liftY = lift * s * 0.032
        let curlAmount = max(-0.10, min(0.30, curl)) * s * 0.020

        let start = CGPoint(x: rect.midX + s * 0.020 + swayX * 0.20, y: rect.midY - s * 0.050)
        let drop = CGPoint(x: rect.midX + s * 0.122 + swayX * 0.78, y: rect.midY + s * 0.124 + liftY)
        let tip = CGPoint(x: rect.midX + s * 0.276 + swayX + curlAmount, y: rect.midY + s * 0.158 + liftY)

        var path = Path()
        path.move(to: start)
        path.addCurve(
            to: drop,
            control1: CGPoint(x: rect.midX + s * 0.092 + swayX * 0.30, y: rect.midY - s * 0.034),
            control2: CGPoint(x: rect.midX + s * 0.158 + swayX * 0.62, y: rect.midY + s * 0.070 + liftY)
        )
        path.addCurve(
            to: tip,
            control1: CGPoint(x: rect.midX + s * 0.104 + swayX * 0.88, y: rect.midY + s * 0.188 + liftY),
            control2: CGPoint(x: rect.midX + s * 0.218 + swayX + curlAmount, y: rect.midY + s * 0.196 + liftY)
        )
        return path
    }
}

private struct ElephantTrunkHighlight: Shape {
    var sway: CGFloat
    var lift: CGFloat

    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height)
        let swayX = sway * s * 0.0006
        let liftY = lift * s * 0.030
        var path = Path()
        path.move(to: CGPoint(x: rect.midX + s * 0.112 + swayX, y: rect.midY - s * 0.034))
        path.addCurve(
            to: CGPoint(x: rect.midX + s * 0.180 + swayX, y: rect.midY + s * 0.172 + liftY),
            control1: CGPoint(x: rect.midX + s * 0.106 + swayX, y: rect.midY + s * 0.048),
            control2: CGPoint(x: rect.midX + s * 0.136 + swayX, y: rect.midY + s * 0.132 + liftY)
        )
        return path
    }
}

private struct ElephantTrunkSmileWrinkles: Shape {
    var sway: CGFloat
    var lift: CGFloat

    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height)
        let baseX = rect.midX + s * (0.154 + sway * 0.0006)
        let baseY = rect.midY + s * (0.024 + lift * 0.032)
        var path = Path()

        for index in 0..<3 {
            let y = baseY + CGFloat(index) * s * 0.042
            let x = baseX + CGFloat(index) * s * 0.004
            path.move(to: CGPoint(x: x - s * 0.025, y: y))
            path.addQuadCurve(
                to: CGPoint(x: x + s * 0.036, y: y + s * 0.004),
                control: CGPoint(x: x + s * 0.008, y: y - s * 0.014)
            )
        }

        path.move(to: CGPoint(x: rect.midX + s * 0.224, y: rect.midY + s * 0.166 + lift * s * 0.035))
        path.addQuadCurve(
            to: CGPoint(x: rect.midX + s * 0.294, y: rect.midY + s * 0.138 + lift * s * 0.035),
            control: CGPoint(x: rect.midX + s * 0.266, y: rect.midY + s * 0.180 + lift * s * 0.035)
        )
        return path
    }
}

private struct ElephantTrunkWrinkles: Shape {
    var sway: CGFloat
    var lift: CGFloat

    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height)
        let baseX = rect.midX + s * (0.060 + sway * 0.0010)
        let baseY = rect.midY + s * (0.005 + lift * 0.06)
        var path = Path()

        for index in 0..<4 {
            let y = baseY + CGFloat(index) * s * 0.055
            let x = baseX + CGFloat(index) * s * 0.012
            path.move(to: CGPoint(x: x - s * 0.025, y: y))
            path.addQuadCurve(
                to: CGPoint(x: x + s * 0.046, y: y + s * 0.002),
                control: CGPoint(x: x + s * 0.012, y: y - s * 0.018)
            )
        }

        let curlY = rect.midY + s * (0.174 + lift * 0.04)
        path.move(to: CGPoint(x: rect.midX + s * 0.238, y: curlY))
        path.addQuadCurve(
            to: CGPoint(x: rect.midX + s * 0.342, y: curlY - s * 0.070),
            control: CGPoint(x: rect.midX + s * 0.320, y: curlY + s * 0.008)
        )
        return path
    }
}

private struct ElephantSideTusk: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.width * 0.52, y: rect.minY))
        path.addCurve(
            to: CGPoint(x: rect.width * 0.42, y: rect.height * 0.98),
            control1: CGPoint(x: rect.width * 0.20, y: rect.height * 0.26),
            control2: CGPoint(x: rect.width * 0.20, y: rect.height * 0.76)
        )
        path.addCurve(
            to: CGPoint(x: rect.width * 0.78, y: rect.height * 0.10),
            control1: CGPoint(x: rect.width * 0.74, y: rect.height * 0.76),
            control2: CGPoint(x: rect.width * 0.88, y: rect.height * 0.34)
        )
        path.addCurve(
            to: CGPoint(x: rect.width * 0.52, y: rect.minY),
            control1: CGPoint(x: rect.width * 0.70, y: rect.height * 0.04),
            control2: CGPoint(x: rect.width * 0.60, y: rect.height * 0.00)
        )
        path.closeSubpath()
        return path
    }
}

private struct ElephantTusk: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.midX, y: rect.minY))
        path.addCurve(
            to: CGPoint(x: rect.midX * 0.74, y: rect.maxY),
            control1: CGPoint(x: rect.minX, y: rect.midY * 0.96),
            control2: CGPoint(x: rect.minX + rect.width * 0.12, y: rect.maxY * 0.88)
        )
        path.addCurve(
            to: CGPoint(x: rect.midX, y: rect.minY),
            control1: CGPoint(x: rect.maxX * 0.66, y: rect.maxY * 0.78),
            control2: CGPoint(x: rect.maxX * 0.62, y: rect.midY * 0.72)
        )
        path.closeSubpath()
        return path
    }
}

private struct ElephantMascotMemoryField: View {
    var mood: ElephantMascotMood
    var phase: TimeInterval
    var animated: Bool
    var energy: CGFloat

    var body: some View {
        Canvas { context, size in
            let center = CGPoint(x: size.width / 2, y: size.height / 2)
            let baseRadius = min(size.width, size.height) * 0.42
            let palette = [ElephantTheme.accent, ElephantTheme.green, ElephantTheme.ember]
            let stateBoost: Double = mood == .thinking || mood == .tooling || mood == .sleeping ? 1.0 : 0.62
            let motion = max(0.65, min(1.8, Double(energy)))

            for index in 0..<3 {
                let offset = Double(index) * 0.72
                let radius = baseRadius * (0.72 + CGFloat(index) * 0.13)
                let wobble = animated ? CGFloat(sin(phase * (0.55 + Double(index) * 0.12) * motion + offset)) * 5 * CGFloat(motion) : 0
                let rect = CGRect(
                    x: center.x - radius + wobble,
                    y: center.y - radius * 0.72 - wobble * 0.4,
                    width: radius * 2,
                    height: radius * 1.44
                )
                var path = Path()
                path.addEllipse(in: rect)
                context.stroke(
                    path,
                    with: .color(palette[index].opacity((0.08 + Double(index) * 0.018) * stateBoost)),
                    style: StrokeStyle(lineWidth: 1.1, lineCap: .round, dash: [8, 15])
                )
            }

            for index in 0..<6 {
                let travel = animated ? (phase * (0.055 + Double(index) * 0.007) * motion + Double(index) * 0.17).truncatingRemainder(dividingBy: 1) : Double(index) / 6.0
                let angle = travel * Double.pi * 2
                let radius = baseRadius * (0.76 + CGFloat(index % 3) * 0.12)
                let point = CGPoint(
                    x: center.x + cos(angle) * radius,
                    y: center.y + sin(angle) * radius * 0.68
                )
                let tile = CGRect(x: point.x - 2.4, y: point.y - 2.4, width: 4.8, height: 4.8)
                context.fill(
                    Path(roundedRect: tile, cornerRadius: 1.4),
                    with: .color(palette[index % palette.count].opacity((mood == .tooling ? 0.30 : 0.18) * stateBoost))
                )
            }
        }
    }
}

private struct ElephantSignalMarks: View {
    var mood: ElephantMascotMood
    var phase: TimeInterval
    var animated: Bool

    var body: some View {
        Canvas { context, size in
            let base = CGPoint(x: size.width * 0.14, y: size.height * 0.52)
            let pulse = animated ? (sin(phase * (mood == .speaking ? 5.0 : 3.0)) + 1.0) / 2.0 : 0.55
            let tint = mood == .speaking ? ElephantTheme.accent : ElephantTheme.green

            for index in 0..<3 {
                let inset = CGFloat(index) * size.width * 0.16
                var path = Path()
                path.move(to: CGPoint(x: base.x + inset, y: base.y - size.height * (0.18 + CGFloat(index) * 0.05)))
                path.addQuadCurve(
                    to: CGPoint(x: base.x + inset, y: base.y + size.height * (0.18 + CGFloat(index) * 0.05)),
                    control: CGPoint(x: base.x + size.width * (0.26 + CGFloat(index) * 0.13), y: base.y)
                )
                context.stroke(
                    path,
                    with: .color(tint.opacity(0.16 + pulse * 0.20 - Double(index) * 0.035)),
                    style: StrokeStyle(lineWidth: 2.0, lineCap: .round)
                )
            }
        }
    }
}
