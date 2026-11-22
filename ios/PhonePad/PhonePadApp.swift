import SwiftUI

@main
struct PhonePadApp: App {
    var body: some Scene {
        WindowGroup { RootView() }
    }
}

struct RootView: View {
    @AppStorage("pcurl") private var pcURL = ""

    var body: some View {
        ZStack {
            Color(red: 0.08, green: 0.09, blue: 0.11).ignoresSafeArea()
            if pcURL.isEmpty {
                SetupView(pcURL: $pcURL)
            } else {
                ControllerView(pageURL: pcURL, onReset: { pcURL = "" })
            }
        }
        .statusBarHidden(true)
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
    }
}

struct SetupView: View {
    @Binding var pcURL: String
    @State private var text = ""
    @State private var scanning = false
    @State private var error = ""

    var body: some View {
        HStack(spacing: 40) {
            VStack(alignment: .leading, spacing: 14) {
                Text("PhonePad").font(.largeTitle.bold())
                Text("Run server.exe on your PC, then scan the QR code it shows in the console.")
                    .foregroundColor(.gray)
                Button("Scan QR code") { scanning = true }
                    .buttonStyle(.borderedProminent)
            }
            VStack(alignment: .leading, spacing: 12) {
                Text("Or paste the link").foregroundColor(.gray)
                TextField("https://192.168.x.x:8443/?k=...", text: $text)
                    .textFieldStyle(.roundedBorder)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Connect") { save(text) }.buttonStyle(.bordered)
                if !error.isEmpty { Text(error).foregroundColor(.red).font(.footnote) }
            }
        }
        .padding(32)
        .foregroundColor(.white)
        .fullScreenCover(isPresented: $scanning) {
            ZStack(alignment: .topTrailing) {
                ScannerView { code in
                    scanning = false
                    save(code)
                }
                .ignoresSafeArea()
                Button("Close") { scanning = false }
                    .buttonStyle(.borderedProminent)
                    .padding()
            }
        }
    }

    private func save(_ raw: String) {
        let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let c = URLComponents(string: t), c.host != nil,
              c.queryItems?.contains(where: { $0.name == "k" }) == true else {
            error = "That doesn't look like the PhonePad link."
            return
        }
        error = ""
        pcURL = t
    }
}
