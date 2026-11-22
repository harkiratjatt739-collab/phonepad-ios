import Foundation

/// Native WebSocket to the PC server. Accepts the server's self-signed certificate.
final class PCConnection: NSObject, URLSessionDelegate, URLSessionWebSocketDelegate {
    var onStatus: ((Bool) -> Void)?
    var onRumble: ((Int, Int) -> Void)?

    private var session: URLSession!
    private var task: URLSessionWebSocketTask?
    private var url: URL?
    private var active = false

    override init() {
        super.init()
        session = URLSession(configuration: .default, delegate: self, delegateQueue: .main)
    }

    func start(pageURL: String) {
        guard var c = URLComponents(string: pageURL) else { return }
        c.scheme = "wss"
        c.path = "/ws"
        url = c.url
        active = true
        open()
    }

    func stop() {
        active = false
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        session.invalidateAndCancel()
    }

    func send(_ text: String) {
        task?.send(.string(text)) { _ in }
    }

    private func open() {
        guard active, let url else { return }
        let t = session.webSocketTask(with: url)
        task = t
        t.resume()
        listen(t)
    }

    private func listen(_ t: URLSessionWebSocketTask) {
        t.receive { [weak self] result in
            guard let self, t === self.task else { return }
            switch result {
            case .success(let message):
                if case .string(let s) = message,
                   let d = s.data(using: .utf8),
                   let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
                   o["t"] as? String == "r" {
                    self.onRumble?((o["l"] as? Int) ?? 0, (o["s"] as? Int) ?? 0)
                }
                self.listen(t)
            case .failure:
                self.onStatus?(false)
                DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in self?.open() }
            }
        }
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocol: String?) {
        onStatus?(true)
    }

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        let space = challenge.protectionSpace
        if space.authenticationMethod == NSURLAuthenticationMethodServerTrust,
           let trust = space.serverTrust, space.host == url?.host {
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else {
            completionHandler(.performDefaultHandling, nil)
        }
    }
}
