import CoreHaptics
import UIKit

final class Haptics {
    static let shared = Haptics()

    private var engine: CHHapticEngine?
    private var player: CHHapticAdvancedPatternPlayer?
    private let impact = UIImpactFeedbackGenerator(style: .rigid)

    private init() {
        if CHHapticEngine.capabilitiesForHardware().supportsHaptics {
            engine = try? CHHapticEngine()
            engine?.isAutoShutdownEnabled = true
            engine?.resetHandler = { [weak self] in try? self?.engine?.start() }
            try? engine?.start()
        }
    }

    func tap() {
        impact.impactOccurred()
    }

    /// Game rumble (0-255 per motor). Zero stops it.
    func rumble(large: Int, small: Int) {
        try? player?.stop(atTime: 0)
        player = nil
        let level = max(large, small)
        guard level > 10, let engine else { return }
        do {
            try engine.start()
            let intensity = CHHapticEventParameter(parameterID: .hapticIntensity, value: Float(level) / 255)
            let sharp = CHHapticEventParameter(parameterID: .hapticSharpness,
                                               value: large >= small ? 0.2 : 0.8)
            let event = CHHapticEvent(eventType: .hapticContinuous, parameters: [intensity, sharp],
                                      relativeTime: 0, duration: 10)
            let pattern = try CHHapticPattern(events: [event], parameters: [])
            let p = try engine.makeAdvancedPlayer(with: pattern)
            player = p
            try p.start(atTime: 0)
        } catch {}
    }
}
