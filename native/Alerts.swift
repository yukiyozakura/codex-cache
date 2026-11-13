// Apache-2.0. Native macOS notifications; no network, shell, or Desktop control.
import AppKit
import UserNotifications

final class Alerts: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let center = UNUserNotificationCenter.current()
    let command = CommandLine.arguments.dropFirst().first ?? "status"
    var finished = false

    func finish(_ value: [String: Any], code: Int32 = 0) {
        DispatchQueue.main.async {
            guard !self.finished else { return }
            self.finished = true
            let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data([10]))
            exit(code)
        }
    }

    func authorizationName(_ status: UNAuthorizationStatus) -> String {
        switch status {
        case .notDetermined: return "notDetermined"
        case .denied: return "denied"
        case .authorized: return "authorized"
        case .provisional: return "provisional"
        case .ephemeral: return "ephemeral"
        @unknown default: return "unknown"
        }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        center.delegate = self
        if command == "authorize" {
            center.requestAuthorization(options: [.alert, .sound]) { allowed, error in
                self.finish(["allowed": allowed, "error": error?.localizedDescription ?? NSNull()], code: allowed ? 0 : 3)
            }
            return
        }
        if command == "list" {
            center.getDeliveredNotifications { notifications in
                self.finish(["delivered": notifications.map { ["id": $0.request.identifier, "at": $0.date.timeIntervalSince1970] }])
            }
            return
        }
        center.getNotificationSettings { settings in
            let auth = self.authorizationName(settings.authorizationStatus)
            if self.command == "status" {
                self.finish(["authorization": auth, "alertStyle": settings.alertStyle.rawValue,
                             "soundEnabled": settings.soundSetting == .enabled,
                             "bundleId": Bundle.main.bundleIdentifier ?? "unknown"])
                return
            }
            guard self.command == "notify" || self.command == "test" else {
                self.finish(["error": "unknown command"], code: 2); return
            }
            guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else {
                self.finish(["error": "notification-permission-not-authorized", "authorization": auth], code: 3); return
            }
            var payload: [String: Any] = [:]
            if self.command == "notify" {
                let input = FileHandle.standardInput.readDataToEndOfFile()
                guard let parsed = try? JSONSerialization.jsonObject(with: input) as? [String: Any] else {
                    self.finish(["error": "invalid payload"], code: 2); return
                }
                payload = parsed
            }
            let tid = payload["threadId"] as? String ?? "test"
            guard self.command == "test" || UUID(uuidString: tid) != nil else {
                self.finish(["error": "invalid thread ID"], code: 2); return
            }
            let minutes = payload["idleMinutes"] as? Double ?? 50
            let label = String((payload["label"] as? String ?? String(tid.prefix(8))).prefix(80))
            let content = UNMutableNotificationContent()
            content.title = "Codex Cache"
            content.subtitle = self.command == "test" ? "テスト通知" : "\(label)：約\(Int(minutes))分idleです"
            content.body = self.command == "test" ? "50分idle後の繰り返し通知は、このアプリから届きます。" : "必要ならCodexで手動compactしてください。会話を再開するかOFFにすると通知は止まります。"
            content.sound = .default
            content.threadIdentifier = "codex-cache.\(tid)"
            // Replace the conversation's previous entry instead of filling Notification Center.
            let identifier = "codex-cache.\(tid)"
            let request = UNNotificationRequest(identifier: identifier, content: content, trigger: nil)
            self.center.add(request) { error in
                if let error = error { self.finish(["error": error.localizedDescription], code: 4) }
                else { self.finish(["accepted": true, "id": identifier, "at": Date().timeIntervalSince1970]) }
            }
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound, .list])
    }
}
let delegate = Alerts()
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
app.delegate = delegate
app.run()
