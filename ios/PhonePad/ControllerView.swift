import CoreMotion
import SwiftUI
import WebKit

struct ControllerView: UIViewRepresentable {
    let pageURL: String
    let onReset: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(pageURL: pageURL, onReset: onReset)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "pp")
        let wv = WKWebView(frame: .zero, configuration: config)
        let bg = UIColor(red: 0.08, green: 0.09, blue: 0.11, alpha: 1)
        wv.isOpaque = false
        wv.backgroundColor = bg
        wv.scrollView.backgroundColor = bg
        wv.scrollView.isScrollEnabled = false
        wv.scrollView.bounces = false
        wv.scrollView.contentInsetAdjustmentBehavior = .never
        context.coordinator.webView = wv
        context.coordinator.startMotion()
        if let url = Bundle.main.url(forResource: "controller", withExtension: "html") {
            wv.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
        }
        return wv
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    static func dismantleUIView(_ uiView: WKWebView, coordinator: Coordinator) {
        coordinator.stop()
        uiView.configuration.userContentController.removeScriptMessageHandler(forName: "pp")
    }

    final class Coordinator: NSObject, WKScriptMessageHandler {
        weak var webView: WKWebView?
        private let pageURL: String
        private let onReset: () -> Void
        private let conn = PCConnection()
        private let motion = CMMotionManager()

        init(pageURL: String, onReset: @escaping () -> Void) {
            self.pageURL = pageURL
            self.onReset = onReset
            super.init()
            conn.onStatus = { [weak self] ok in
                self?.webView?.evaluateJavaScript("window.nativeStatus&&window.nativeStatus(\(ok))")
            }
            conn.onRumble = { l, s in
                Haptics.shared.rumble(large: l, small: s)
            }
        }

        func startMotion() {
            guard motion.isDeviceMotionAvailable else { return }
            motion.deviceMotionUpdateInterval = 1.0 / 60.0
            motion.startDeviceMotionUpdates(to: .main) { [weak self] dm, _ in
                guard let self, let dm else { return }
                let d = 180.0 / Double.pi
                // Same axes/units as the web DeviceMotion API (deg/s), gravity as "up" vector.
                let js = String(format: "window.nativeMotion&&window.nativeMotion(%f,%f,%f,%f,%f,%f)",
                                dm.rotationRate.z * d, dm.rotationRate.x * d, dm.rotationRate.y * d,
                                -dm.gravity.x * 9.81, -dm.gravity.y * 9.81, -dm.gravity.z * 9.81)
                self.webView?.evaluateJavaScript(js)
            }
        }

        func stop() {
            motion.stopDeviceMotionUpdates()
            conn.stop()
            Haptics.shared.rumble(large: 0, small: 0)
        }

        func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let body = message.body as? [String: Any], let t = body["t"] as? String else { return }
            switch t {
            case "connect": conn.start(pageURL: pageURL)
            case "send": if let d = body["d"] as? String { conn.send(d) }
            case "tap": Haptics.shared.tap()
            case "rumble":
                Haptics.shared.rumble(large: (body["l"] as? Int) ?? 0, small: (body["s"] as? Int) ?? 0)
            case "reset": onReset()
            default: break
            }
        }
    }
}
