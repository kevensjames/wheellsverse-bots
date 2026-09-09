// KAI Desktop Bridge — the ONLY process permitted to touch the macOS desktop.
//
// WHY NATIVE. macOS attributes a TCC grant (Screen Recording, Accessibility) to the
// EXECUTABLE. Granting to /usr/bin/python3 or Terminal would grant every script they run.
// So the trusted desktop controller is its own narrow, signed binary with a fixed bundle
// identifier, and nothing else.
//
// WHAT IT IS NOT. No shell verb, no AppleScript verb, no arbitrary bundle id or path, no
// coordinate replay, no background surveillance, no clipboard extraction, no password
// field interaction, no unrestricted shortcuts. The verb vocabulary below is the whole
// surface; anything absent cannot be requested.
//
// TRUST MODEL. KAI proposes actions; the bridge INDEPENDENTLY re-validates every one
// against the live desktop and refuses fail-closed. KAI's assertion that an action is
// safe is never trusted.
//
// PROTOCOL. Newline-delimited JSON on stdin/stdout. No socket, no network.
//
// TEST SEAM. Compiled with -DKAI_TEST_HARNESS, the capability probes and effect emitters
// are stubbed and the live window model is driven from env vars, so the full decision
// logic is deterministically testable with NO real desktop effects and NO signing. The
// production build (no flag) contains none of that path — the real APIs stand.

import Foundation
#if canImport(AppKit)
import AppKit
import ApplicationServices
import ScreenCaptureKit
#endif

let BUNDLE_ID = "com.wheellsverse.kai.desktopbridge"
let VERSION = "0.2.0"

#if KAI_TEST_HARNESS
let STATE_DIR = ProcessInfo.processInfo.environment["KAI_TEST_STATE_DIR"]
    ?? (NSHomeDirectory() as NSString).appendingPathComponent(".kai-desktop-bridge")
#else
let STATE_DIR = (NSHomeDirectory() as NSString).appendingPathComponent(".kai-desktop-bridge")
#endif
let STOP_SENTINEL = (STATE_DIR as NSString).appendingPathComponent("STOP")           // OPERATOR emergency; reset NEVER clears it
let VERB_STOP = (STATE_DIR as NSString).appendingPathComponent("STOP.verb")           // engaged by desktop.stop; reset clears it
let EVIDENCE_DIR = (STATE_DIR as NSString).appendingPathComponent("evidence")
let AUDIT_LOG = (STATE_DIR as NSString).appendingPathComponent("audit.jsonl")
let CONTROLLER_LOCK = (STATE_DIR as NSString).appendingPathComponent("controller.lock")

let OBSERVATION_TTL: TimeInterval = 8.0
let MAX_ACTIONS_PER_MINUTE = 20
let MAX_TYPE_CHARS = 1000
let MAX_CLOCK_SKEW: TimeInterval = 120

// MARK: - Vocabulary

enum Verb: String, CaseIterable {
    case probe          = "desktop.probe"
    case listWindows    = "desktop.list_windows"
    case observeWindow  = "desktop.observe_window"
    case launchApp      = "desktop.launch_approved_application"
    case focusWindow    = "desktop.focus_window"
    case typeText       = "desktop.type_text"
    case pressShortcut  = "desktop.press_shortcut"
    case clickPoint     = "desktop.click_point"
    case cancel         = "desktop.cancel"
    case stop           = "desktop.stop"
    case reset          = "desktop.reset"

    var mutating: Bool {
        switch self {
        case .launchApp, .focusWindow, .typeText, .pressShortcut, .clickPoint: return true
        default: return false
        }
    }
    var needsAccessibility: Bool {
        switch self {
        case .listWindows, .observeWindow, .focusWindow, .typeText, .pressShortcut, .clickPoint:
            return true
        default: return false
        }
    }
}

let SENSITIVE_APPS: Set<String> = [
    "1Password", "1Password 7", "1Password 8", "Bitwarden", "KeePassXC", "Dashlane",
    "LastPass", "Keychain Access", "Passwords", "Authy", "Proton Pass", "Secretive",
    "System Settings", "System Preferences", "Security & Privacy", "Messages", "Mail",
    "FaceTime", "Terminal", "iTerm2", "Console",
]
let SENSITIVE_BUNDLE_IDS: Set<String> = [
    "com.apple.keychainaccess", "com.apple.systempreferences", "com.apple.Passwords",
    "com.1password.1password", "com.agilebits.onepassword7", "com.apple.Terminal",
    "com.googlecode.iterm2", "com.apple.MobileSMS", "com.apple.mail",
]
let SENSITIVE_TITLE_FRAGMENTS: [String] = [
    "password", "passkey", "sign in", "log in", "login", "one-time", "verification code",
    "2fa", "two-factor", "mfa", "authenticator", "recovery code", "seed phrase", "bank",
    "payment", "checkout", "card number", "billing", "wire transfer", "uscis",
    "immigration", "visa application", "passport", "medical", "health record", "patient",
    "insurance claim", "keychain", "privacy & security", "filevault",
]

/// The ONLY shortcuts permitted, by canonical string. Deliberately tiny: destructive or
/// state-changing chords (save, close, quit, delete) are not here and cannot be added by
/// a request. Each maps to (CGEventFlags, virtual keycode).
let ALLOWED_SHORTCUTS: [String: (CGEventFlags, CGKeyCode)] = [
    "cmd+a": (.maskCommand, 0),   // Select All — non-destructive
]

// MARK: - Wire types

struct Request: Decodable {
    let id: String
    let verb: String
    var correlationId: String?
    var principal: String?
    var targetBundleId: String?
    var targetPid: Int?
    var windowId: Int?
    var expectedTitle: String?
    var createdAt: Double?
    var expiresAt: Double?
    var nonce: String?
    var policyDecision: String?
    var confirmationRequired: Bool?
    var evidencePath: String?
    var text: String?
    var shortcut: String?
    var clickX: Double?
    var clickY: Double?
    var observationToken: String?
    var allowedApps: [String]?
    var allowedBundleIds: [String]?
}

struct Response: Encodable {
    let id: String
    let ok: Bool
    let verb: String
    var reason: String? = nil
    var data: [String: String]? = nil
    var windows: [WindowInfo]? = nil
    var observationToken: String? = nil
    var expiresInSeconds: Double? = nil
    var correlationId: String? = nil
}

struct WindowInfo: Encodable {
    let windowId: Int
    let pid: Int
    let app: String
    let bundleId: String
    let title: String
    let sensitive: Bool
    let onscreen: Bool
}

struct Observation {
    let token: String
    let windowId: Int
    let pid: Int
    let bundleId: String
    let app: String
    let title: String
    let bounds: CGRect
    let frontmostBundleId: String
    let at: Date
    let correlationId: String
}

var observations: [String: Observation] = [:]
var consumedNonces: [String: Double] = [:]   // nonce -> expiry epoch; pruned on burn
func burnNonce(_ n: String, _ exp: Double?) {
    let now = Date().timeIntervalSince1970
    consumedNonces = consumedNonces.filter { $0.value > now }        // evict expired
    consumedNonces[n] = exp ?? (now + 300)
}
var actionTimestamps: [Date] = []
var stopped = false
var haveController = false

// MARK: - Test seam (compiled only under -DKAI_TEST_HARNESS; absent from production)

#if KAI_TEST_HARNESS
struct TestControl: Decodable {
    let id: String; let verb: String
    var windows: String?; var frontmost: String?; var secure: Bool?; var roleSensitive: Bool?; var bounds: [String: Double]?
}
enum TestModel {
    static func env(_ k: String) -> String { ProcessInfo.processInfo.environment[k] ?? "" }
    static func parseWindows(_ s: String) -> [WindowInfo] {
        guard let data = s.data(using: .utf8),
              let arr = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return [] }
        return arr.map { w in
            WindowInfo(windowId: w["windowId"] as? Int ?? 0, pid: w["pid"] as? Int ?? 0,
                       app: w["app"] as? String ?? "", bundleId: w["bundleId"] as? String ?? "",
                       title: w["title"] as? String ?? "", sensitive: w["sensitive"] as? Bool ?? false,
                       onscreen: w["onscreen"] as? Bool ?? true)
        }
    }
    static func parseBounds(_ s: String) -> [Int: CGRect] {
        guard let data = s.data(using: .utf8),
              let arr = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return [:] }
        var out: [Int: CGRect] = [:]
        for w in arr {
            guard let id = w["windowId"] as? Int, let b = w["bounds"] as? [String: Double] else { continue }
            out[id] = CGRect(x: b["x"] ?? 0, y: b["y"] ?? 0, width: b["w"] ?? 0, height: b["h"] ?? 0)
        }
        return out
    }
    static var _windows: [WindowInfo] = parseWindows(env("KAI_TEST_WINDOWS"))
    static var _bounds: [Int: CGRect] = parseBounds(env("KAI_TEST_WINDOWS"))
    static var frontmost: String = env("KAI_TEST_FRONTMOST")
    static var secureField: Bool = env("KAI_TEST_SECURE") == "1"
    static var roleSensitive: Bool = env("KAI_TEST_ROLE_SENSITIVE") == "1"
    static var focusedBounds: CGRect? = nil
    static var windows: [WindowInfo] { _windows }
    static func bounds(_ id: Int) -> CGRect? { _bounds[id] }
    static func setWindows(_ s: String) { _windows = parseWindows(s); _bounds = parseBounds(s) }
}
#endif

// MARK: - Audit (append-only; never records sensitive data)

@discardableResult
func auditPrivacySafe(_ fields: [String: String]) -> Bool {
    var rec = fields
    rec["ts"] = ISO8601DateFormatter().string(from: Date())
    guard let data = try? JSONSerialization.data(withJSONObject: rec),
          let line = String(data: data, encoding: .utf8) else { return false }
    let entry = line + "\n"
    if let fh = FileHandle(forWritingAtPath: AUDIT_LOG) {
        fh.seekToEndOfFile(); fh.write(entry.data(using: .utf8)!); try? fh.close(); return true
    }
    do { try entry.data(using: .utf8)!.write(to: URL(fileURLWithPath: AUDIT_LOG)); return true }
    catch { return false }
}
func titleMarker(_ title: String) -> String { "len:\(title.count)" }

// MARK: - STOP (two independent paths, persistent)

func stopEngaged() -> Bool {
    // Re-read the sentinel every time: an operator (or any process) can `touch` it to halt
    // the bridge instantly, with no dependency on KAI, the network, or the current task.
    stopped || FileManager.default.fileExists(atPath: STOP_SENTINEL)
        || FileManager.default.fileExists(atPath: VERB_STOP)
}
func engageStop(reason: String) {
    stopped = true
    observations.removeAll()
    FileManager.default.createFile(atPath: VERB_STOP, contents: (reason + "\n").data(using: .utf8))
    auditPrivacySafe(["event": "STOP_ENGAGED", "reason_category": "control"])
}
func resetStop() {
    // Clears ONLY the in-app verb-stop. An operator-created STOP_SENTINEL is never removed
    // here -- the emergency path stays independent of anything KAI can send.
    stopped = false
    try? FileManager.default.removeItem(atPath: VERB_STOP)
    auditPrivacySafe(["event": "STOP_RESET"])
}

// MARK: - Capability probing (truthful; stubbed only under the test seam)

func hasInteractiveDesktop() -> Bool {
    #if KAI_TEST_HARNESS
    return true
    #elseif canImport(AppKit)
    return NSWorkspace.shared.frontmostApplication != nil
    #else
    return false
    #endif
}
func hasAccessibility() -> Bool {
    #if KAI_TEST_HARNESS
    return true
    #elseif canImport(AppKit)
    return AXIsProcessTrusted()
    #else
    return false
    #endif
}
func bundleIdentifier() -> String {
    #if KAI_TEST_HARNESS
    return Bundle.main.bundleIdentifier ?? ProcessInfo.processInfo.environment["KAI_BRIDGE_BUNDLE_ID"] ?? ""
    #else
    return Bundle.main.bundleIdentifier ?? ""   // prod: identity derives ONLY from the signed bundle
    #endif
}
func identityAcceptable() -> Bool { bundleIdentifier() == BUNDLE_ID }

// MARK: - Window model (real; driven from env under the test seam)

func bundleIdForPid(_ pid: Int) -> String {
    #if canImport(AppKit)
    return NSRunningApplication(processIdentifier: pid_t(pid))?.bundleIdentifier ?? ""
    #else
    return ""
    #endif
}
func frontmostBundleId() -> String {
    #if KAI_TEST_HARNESS
    return TestModel.frontmost
    #elseif canImport(AppKit)
    return NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? ""
    #else
    return ""
    #endif
}
func isSensitiveTitle(_ t: String) -> Bool {
    let l = t.lowercased(); return SENSITIVE_TITLE_FRAGMENTS.contains { l.contains($0) }
}
func listWindows(allowedApps: Set<String>, allowedBundles: Set<String>) -> [WindowInfo] {
    #if KAI_TEST_HARNESS
    return TestModel.windows.filter { allowedApps.contains($0.app) || allowedBundles.contains($0.bundleId) }
        .map { w in
            let sensitive = SENSITIVE_APPS.contains(w.app) || SENSITIVE_BUNDLE_IDS.contains(w.bundleId)
                            || isSensitiveTitle(w.title)
            return WindowInfo(windowId: w.windowId, pid: w.pid, app: w.app, bundleId: w.bundleId,
                              title: sensitive ? "<redacted: sensitive window>" : w.title,
                              sensitive: sensitive, onscreen: w.onscreen)
        }
    #elseif canImport(AppKit)
    guard let raw = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements],
                                               kCGNullWindowID) as? [[String: Any]] else { return [] }
    return raw.compactMap { w in
        guard let owner = w[kCGWindowOwnerName as String] as? String,
              let wid = w[kCGWindowNumber as String] as? Int,
              let pid = w[kCGWindowOwnerPID as String] as? Int else { return nil }
        let bundle = bundleIdForPid(pid)
        guard allowedApps.contains(owner) || allowedBundles.contains(bundle) else { return nil }
        let title = (w[kCGWindowName as String] as? String) ?? ""
        let sensitive = SENSITIVE_APPS.contains(owner) || SENSITIVE_BUNDLE_IDS.contains(bundle)
                        || isSensitiveTitle(title)
        return WindowInfo(windowId: wid, pid: pid, app: owner, bundleId: bundle,
                          title: sensitive ? "<redacted: sensitive window>" : title,
                          sensitive: sensitive, onscreen: true)
    }
    #else
    return []
    #endif
}
func windowBounds(_ wid: Int) -> CGRect? {
    #if KAI_TEST_HARNESS
    return TestModel.bounds(wid)
    #elseif canImport(AppKit)
    guard let raw = CGWindowListCopyWindowInfo([.optionIncludingWindow], CGWindowID(wid))
            as? [[String: Any]], let first = raw.first,
          let b = first[kCGWindowBounds as String] as? [String: CGFloat] else { return nil }
    return CGRect(x: b["X"] ?? 0, y: b["Y"] ?? 0, width: b["Width"] ?? 0, height: b["Height"] ?? 0)
    #else
    return nil
    #endif
}
func focusedElementIsSecureOrUnknown() -> Bool {
    #if KAI_TEST_HARNESS
    return TestModel.secureField
    #elseif canImport(AppKit)
    let sys = AXUIElementCreateSystemWide()
    var focused: AnyObject?
    guard AXUIElementCopyAttributeValue(sys, kAXFocusedUIElementAttribute as CFString, &focused)
            == .success, let el = focused else { return true }
    var roleRef: AnyObject?; var subRef: AnyObject?
    AXUIElementCopyAttributeValue(el as! AXUIElement, kAXRoleAttribute as CFString, &roleRef)
    AXUIElementCopyAttributeValue(el as! AXUIElement, kAXSubroleAttribute as CFString, &subRef)
    let role = (roleRef as? String) ?? ""
    let sub = (subRef as? String) ?? ""
    if role.isEmpty { return true }
    if sub == (kAXSecureTextFieldSubrole as String) { return true }
    if role == "AXSecureTextField" { return true }
    return false
    #else
    return true
    #endif
}
func roleAtPointIsSensitiveOrUnknown(_ pt: CGPoint) -> Bool {
    #if KAI_TEST_HARNESS
    return TestModel.roleSensitive
    #elseif canImport(AppKit)
    let sys = AXUIElementCreateSystemWide()
    var el: AXUIElement?
    guard AXUIElementCopyElementAtPosition(sys, Float(pt.x), Float(pt.y), &el) == .success,
          let element = el else { return true }
    var subRef: AnyObject?
    AXUIElementCopyAttributeValue(element, kAXSubroleAttribute as CFString, &subRef)
    if (subRef as? String) == (kAXSecureTextFieldSubrole as String) { return true }
    return false
    #else
    return true
    #endif
}

// MARK: - Effecting (reached ONLY after the full gate passes; no-ops under the test seam)

func launchAppByBundle(_ bundleId: String) -> Bool {
    #if KAI_TEST_HARNESS
    return true
    #else
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    p.arguments = ["-b", bundleId]
    do { try p.run(); p.waitUntilExit(); return p.terminationStatus == 0 } catch { return false }
    #endif
}
func activateApp(pid: Int) -> Bool {
    #if KAI_TEST_HARNESS
    return true
    #elseif canImport(AppKit)
    guard let app = NSRunningApplication(processIdentifier: pid_t(pid)) else { return false }
    return app.activate(options: [.activateAllWindows])
    #else
    return false
    #endif
}
func typeUnicode(_ s: String) -> Bool {
    #if KAI_TEST_HARNESS
    return true
    #elseif canImport(AppKit)
    guard let src = CGEventSource(stateID: .hidSystemState),
          let down = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: true),
          let up = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: false) else { return false }
    var u = Array(s.utf16)
    down.keyboardSetUnicodeString(stringLength: u.count, unicodeString: &u)
    up.keyboardSetUnicodeString(stringLength: u.count, unicodeString: &u)
    down.post(tap: .cghidEventTap); up.post(tap: .cghidEventTap)
    return true
    #else
    return false
    #endif
}
func pressShortcut(_ canonical: String) -> Bool {
    #if KAI_TEST_HARNESS
    return ALLOWED_SHORTCUTS[canonical] != nil
    #elseif canImport(AppKit)
    guard let (flags, key) = ALLOWED_SHORTCUTS[canonical],
          let src = CGEventSource(stateID: .hidSystemState),
          let down = CGEvent(keyboardEventSource: src, virtualKey: key, keyDown: true),
          let up = CGEvent(keyboardEventSource: src, virtualKey: key, keyDown: false) else { return false }
    down.flags = flags; up.flags = flags
    down.post(tap: .cghidEventTap); up.post(tap: .cghidEventTap)
    return true
    #else
    return false
    #endif
}
func clickAt(_ pt: CGPoint) -> Bool {
    #if KAI_TEST_HARNESS
    return true
    #elseif canImport(AppKit)
    guard let src = CGEventSource(stateID: .hidSystemState),
          let down = CGEvent(mouseEventSource: src, mouseType: .leftMouseDown,
                             mouseCursorPosition: pt, mouseButton: .left),
          let up = CGEvent(mouseEventSource: src, mouseType: .leftMouseUp,
                           mouseCursorPosition: pt, mouseButton: .left) else { return false }
    down.post(tap: .cghidEventTap); up.post(tap: .cghidEventTap)
    return true
    #else
    return false
    #endif
}
func captureWindow(id: Int, to path: String) -> Bool {
    #if KAI_TEST_HARNESS
    return true
    #elseif canImport(AppKit)
    guard #available(macOS 14.0, *) else { return false }
    let sem = DispatchSemaphore(value: 0)
    var success = false
    Task {
        defer { sem.signal() }
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            guard let win = content.windows.first(where: { $0.windowID == CGWindowID(id) }) else { return }
            let filter = SCContentFilter(desktopIndependentWindow: win)
            let cfg = SCStreamConfiguration()
            cfg.width = max(1, Int(win.frame.width)); cfg.height = max(1, Int(win.frame.height))
            cfg.showsCursor = false
            let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: cfg)
            let rep = NSBitmapImageRep(cgImage: image)
            if let png = rep.representation(using: .png, properties: [:]) {
                try png.write(to: URL(fileURLWithPath: path)); success = true
            }
        } catch { success = false }
    }
    _ = sem.wait(timeout: .now() + 10)
    return success
    #else
    return false
    #endif
}

func rateLimitOk() -> Bool {
    let cutoff = Date().addingTimeInterval(-60)
    actionTimestamps = actionTimestamps.filter { $0 > cutoff }
    return actionTimestamps.count < MAX_ACTIONS_PER_MINUTE
}

func operatorAllowlist() -> (Set<String>, Set<String>)? {
    let path = (STATE_DIR as NSString).appendingPathComponent("approved-apps.json")
    guard let data = FileManager.default.contents(atPath: path),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
    return (Set((obj["apps"] as? [String]) ?? []), Set((obj["bundleIds"] as? [String]) ?? []))
}

func boundsApproximatelyEqual(_ a: CGRect, _ b: CGRect, tol: CGFloat = 3) -> Bool {
    abs(a.origin.x - b.origin.x) <= tol && abs(a.origin.y - b.origin.y) <= tol &&
    abs(a.size.width - b.size.width) <= tol && abs(a.size.height - b.size.height) <= tol
}

/// Bounds of the window that currently holds KEY focus (where synthesized input actually
/// lands), so type/click can be bound to the observed window and not merely the frontmost
/// app. Returns nil if it cannot be resolved -- callers fall back to the frontmost guarantee.
func focusedWindowBounds() -> CGRect? {
    #if KAI_TEST_HARNESS
    return TestModel.focusedBounds
    #elseif canImport(AppKit)
    let sys = AXUIElementCreateSystemWide()
    var focused: AnyObject?
    guard AXUIElementCopyAttributeValue(sys, kAXFocusedUIElementAttribute as CFString, &focused) == .success,
          let elObj = focused else { return nil }
    var winRef: AnyObject?
    guard AXUIElementCopyAttributeValue(elObj as! AXUIElement, kAXWindowAttribute as CFString, &winRef) == .success,
          let winObj = winRef else { return nil }
    let win = winObj as! AXUIElement
    var posRef: AnyObject?; var sizeRef: AnyObject?
    guard AXUIElementCopyAttributeValue(win, kAXPositionAttribute as CFString, &posRef) == .success,
          AXUIElementCopyAttributeValue(win, kAXSizeAttribute as CFString, &sizeRef) == .success,
          let posObj = posRef, let sizeObj = sizeRef else { return nil }
    var pt = CGPoint.zero; var sz = CGSize.zero
    AXValueGetValue(posObj as! AXValue, .cgPoint, &pt)
    AXValueGetValue(sizeObj as! AXValue, .cgSize, &sz)
    return CGRect(origin: pt, size: sz)
    #else
    return nil
    #endif
}

// MARK: - The gate

func deny(_ req: Request, _ reason: String, category: String = "policy") -> Response {
    auditPrivacySafe(["event": "REFUSED", "verb": req.verb,
                      "correlation_id": req.correlationId ?? "", "reason_category": category])
    return Response(id: req.id, ok: false, verb: req.verb, reason: reason, correlationId: req.correlationId)
}

func handle(_ req: Request) -> Response {
    guard let verb = Verb(rawValue: req.verb) else {
        return deny(req, "unknown verb; the vocabulary is fixed", category: "unknown_action")
    }

    // 1. STOP outranks everything.
    if verb == .stop { engageStop(reason: "operator STOP verb")
        return Response(id: req.id, ok: true, verb: req.verb,
            reason: "stopped; observations invalidated, control released, persisted",
            correlationId: req.correlationId) }
    if verb == .reset {
        if !haveController { return deny(req, "another controller holds the desktop lock; reset refused",
                                         category: "multi_controller") }
        resetStop()
        if FileManager.default.fileExists(atPath: STOP_SENTINEL) {
            return deny(req, "operator STOP sentinel present; clear it out-of-band (rm the STOP file); " +
                        "in-app verb-stop cleared", category: "stop_active")
        }
        return Response(id: req.id, ok: true, verb: req.verb, reason: "STOP cleared by explicit reset",
                        correlationId: req.correlationId)
    }
    if verb == .cancel { observations.removeAll()
        return Response(id: req.id, ok: true, verb: req.verb,
            reason: "in-progress operation cancelled; observation tokens invalidated",
            correlationId: req.correlationId) }
    if stopEngaged() && verb != .probe {
        return deny(req, "STOP is engaged; desktop control released until explicit reset",
                    category: "stop_active")
    }

    // 2. Identity.
    if verb != .probe && !identityAcceptable() {
        return deny(req, "refusing to act as '\(bundleIdentifier())', expected '\(BUNDLE_ID)'",
                    category: "identity")
    }

    if verb == .probe {
        return Response(id: req.id, ok: true, verb: req.verb, data: [
            "version": VERSION, "bundle_id": bundleIdentifier(),
            "identity_acceptable": String(identityAcceptable()),
            "interactive_desktop": String(hasInteractiveDesktop()),
            "accessibility_granted": String(hasAccessibility()),
            "stop_engaged": String(stopEngaged()), "required_bundle_id": BUNDLE_ID],
            correlationId: req.correlationId)
    }

    // 3. Envelope: expiry + replay.
    let now = Date().timeIntervalSince1970
    if let exp = req.expiresAt, now > exp { return deny(req, "request expired", category: "expired") }
    if let created = req.createdAt, created - now > MAX_CLOCK_SKEW {
        return deny(req, "createdAt beyond allowed future skew", category: "expired")
    }
    if let n = req.nonce {
        if consumedNonces[n] != nil { return deny(req, "nonce replay/duplicate refused", category: "replay") }
    } else if verb.mutating {
        return deny(req, "mutating request requires a nonce", category: "schema")
    }
    if verb.mutating && req.expiresAt == nil {
        return deny(req, "mutating request requires expiresAt", category: "schema")
    }

    // 4. Capability.
    if !hasInteractiveDesktop() { return deny(req, "DESKTOP_UNAVAILABLE", category: "capability") }
    if verb.needsAccessibility && !hasAccessibility() {
        return deny(req, "PERMISSION_NOT_GRANTED: Accessibility not granted to \(BUNDLE_ID)",
                    category: "capability")
    }

    var allowedApps = Set(req.allowedApps ?? [])
    var allowedBundles = Set(req.allowedBundleIds ?? [])
    if let op = operatorAllowlist() {                 // operator file is authoritative when present
        allowedApps = allowedApps.intersection(op.0)
        allowedBundles = allowedBundles.intersection(op.1)
    }
    if allowedApps.isEmpty && allowedBundles.isEmpty && verb != .listWindows {
        return deny(req, "no approved applications (default deny)", category: "allowlist")
    }

    switch verb {
    case .listWindows:
        return Response(id: req.id, ok: true, verb: req.verb,
                        windows: listWindows(allowedApps: allowedApps, allowedBundles: allowedBundles),
                        correlationId: req.correlationId)

    case .observeWindow:
        guard let wid = req.windowId else { return deny(req, "windowId required", category: "schema") }
        guard let win = listWindows(allowedApps: allowedApps, allowedBundles: allowedBundles)
                .first(where: { $0.windowId == wid }) else {
            return deny(req, "window not found among approved applications", category: "target")
        }
        if win.sensitive { return deny(req, "sensitive window: capture/observe blocked, not masked",
                                       category: "sensitive") }
        guard let bounds = windowBounds(wid) else {
            return deny(req, "window has no bounds (hidden/minimized?)", category: "target")
        }
        let token = UUID().uuidString
        observations[token] = Observation(token: token, windowId: wid, pid: win.pid,
            bundleId: win.bundleId, app: win.app, title: win.title, bounds: bounds,
            frontmostBundleId: frontmostBundleId(), at: Date(), correlationId: req.correlationId ?? "")
        var data = ["app": win.app, "bundle_id": win.bundleId, "title": win.title,
                    "bounds": NSStringFromRect(bounds)]
        if let cap = req.evidencePath, !cap.isEmpty, haveController {
            // Never trust a caller-supplied path: take only the basename, under a fixed evidence
            // dir, and reject anything that resolves outside it (no traversal, no arbitrary write).
            try? FileManager.default.createDirectory(atPath: EVIDENCE_DIR, withIntermediateDirectories: true)
            let base = URL(fileURLWithPath: EVIDENCE_DIR).standardizedFileURL.path
            let target = URL(fileURLWithPath: (EVIDENCE_DIR as NSString)
                .appendingPathComponent((cap as NSString).lastPathComponent)).standardizedFileURL.path
            if target.hasPrefix(base + "/") {
                let ok = captureWindow(id: wid, to: target)
                data["captured"] = String(ok)
                if ok {
                    data["capture_path"] = target
                    auditPrivacySafe(["event": "CAPTURE", "bundle_id": win.bundleId,
                                      "window_id": String(wid), "correlation_id": req.correlationId ?? ""])
                }
            } else {
                data["captured"] = "false"; data["capture_error"] = "path escaped evidence dir"
            }
        }
        auditPrivacySafe(["event": "OBSERVE", "verb": req.verb, "bundle_id": win.bundleId,
                          "window_id": String(wid), "pid": String(win.pid),
                          "title_marker": titleMarker(win.title), "correlation_id": req.correlationId ?? ""])
        return Response(id: req.id, ok: true, verb: req.verb, data: data,
                        observationToken: token, expiresInSeconds: OBSERVATION_TTL,
                        correlationId: req.correlationId)

    case .launchApp, .focusWindow, .typeText, .pressShortcut, .clickPoint:
        // 5. Consequential: an approval decision from KAI is required. The bridge cannot
        //    mint one, so it cannot authorise its own action.
        if (req.policyDecision ?? "") != "APPROVED" {
            return deny(req, "APPROVAL_REQUIRED: this verb changes state outside KAI", category: "approval")
        }
        if !rateLimitOk() { return deny(req, "rate limit exceeded", category: "rate_limit") }
        // Fail closed on audit failure: an effecting action that cannot be recorded must not run.
        if !auditPrivacySafe(["event": "ATTEMPT", "verb": req.verb,
                              "correlation_id": req.correlationId ?? ""]) {
            return deny(req, "AUDIT_UNAVAILABLE: cannot persist audit record; refusing to act",
                        category: "audit")
        }

        if verb == .launchApp {
            guard let b = req.targetBundleId, allowedBundles.contains(b) else {
                return deny(req, "launch target bundle id not in approved list", category: "allowlist")
            }
            if SENSITIVE_BUNDLE_IDS.contains(b) { return deny(req, "refusing to launch a sensitive app",
                                                              category: "sensitive") }
            if let n = req.nonce { burnNonce(n, req.expiresAt) }
            actionTimestamps.append(Date())
            let ok = launchAppByBundle(b)
            auditPrivacySafe(["event": ok ? "LAUNCH" : "LAUNCH_FAIL", "bundle_id": b,
                              "correlation_id": req.correlationId ?? ""])
            return Response(id: req.id, ok: ok, verb: req.verb,
                            reason: ok ? "launched approved application" : "failed to launch",
                            data: ["bundle_id": b], correlationId: req.correlationId)
        }

        // 6. Interaction verbs: fresh observation of THIS target, unchanged since.
        guard let tok = req.observationToken, let obs = observations[tok] else {
            return deny(req, "a fresh observation of the target is required", category: "observation")
        }
        if Date().timeIntervalSince(obs.at) > OBSERVATION_TTL {
            observations.removeValue(forKey: tok)
            return deny(req, "observation expired; re-observe before acting", category: "stale")
        }
        if let wid = req.windowId, wid != obs.windowId {
            return deny(req, "observation does not cover the requested window", category: "target")
        }
        if let b = req.targetBundleId, b != obs.bundleId {
            return deny(req, "target bundle id does not match observed window", category: "target")
        }
        if let p = req.targetPid, p != obs.pid {
            return deny(req, "target pid does not match observed window", category: "target")
        }
        if let et = req.expectedTitle, et != obs.title {
            return deny(req, "expected title does not match observed window", category: "target")
        }
        guard let live = listWindows(allowedApps: allowedApps, allowedBundles: allowedBundles)
                .first(where: { $0.windowId == obs.windowId }) else {
            return deny(req, "target window disappeared/minimized since observation", category: "target")
        }
        if live.pid != obs.pid || live.bundleId != obs.bundleId {
            return deny(req, "window id reused by a different process since observation", category: "target")
        }
        if live.title != obs.title { return deny(req, "window title changed since observation", category: "stale") }
        if live.sensitive { return deny(req, "target became a sensitive window", category: "sensitive") }
        guard let liveBounds = windowBounds(obs.windowId), liveBounds == obs.bounds else {
            return deny(req, "window geometry changed since observation", category: "stale")
        }
        if frontmostBundleId() != obs.frontmostBundleId {
            observations.removeAll()
            return deny(req, "focus changed since observation (user intervention); control released",
                        category: "focus")
        }
        if obs.frontmostBundleId != obs.bundleId {
            return deny(req, "target window is not frontmost; refusing background action", category: "focus")
        }
        if verb == .typeText || verb == .clickPoint {
            if let fwb = focusedWindowBounds(), !boundsApproximatelyEqual(fwb, obs.bounds) {
                return deny(req, "the key-focused window is not the observed window", category: "focus")
            }
        }

        if let n = req.nonce { burnNonce(n, req.expiresAt) }
        actionTimestamps.append(Date())

        switch verb {
        case .focusWindow:
            let ok = activateApp(pid: obs.pid)
            auditPrivacySafe(["event": ok ? "FOCUS" : "FOCUS_FAIL", "bundle_id": obs.bundleId,
                              "window_id": String(obs.windowId), "correlation_id": obs.correlationId])
            return Response(id: req.id, ok: ok, verb: req.verb,
                            reason: ok ? "focused approved window" : "could not focus",
                            data: ["bundle_id": obs.bundleId], correlationId: req.correlationId)
        case .typeText:
            guard let t = req.text, !t.isEmpty else { return deny(req, "text required", category: "schema") }
            if t.count > MAX_TYPE_CHARS { return deny(req, "text exceeds \(MAX_TYPE_CHARS)-char cap",
                                                      category: "schema") }
            if isSensitiveTitle(t) { return deny(req, "refusing to type credential-like text",
                                                 category: "sensitive") }
            if focusedElementIsSecureOrUnknown() {
                return deny(req, "focused element is a secure/password field or unknown role", category: "secure_field")
            }
            let ok = typeUnicode(t)
            auditPrivacySafe(["event": ok ? "TYPE" : "TYPE_FAIL", "bundle_id": obs.bundleId,
                              "window_id": String(obs.windowId), "typed_chars": String(t.count),
                              "correlation_id": obs.correlationId])
            return Response(id: req.id, ok: ok, verb: req.verb,
                            reason: ok ? "synthesized text into the focused element" : "type failed",
                            data: ["typed_chars": String(t.count)], correlationId: req.correlationId)
        case .pressShortcut:
            guard let sc = req.shortcut, ALLOWED_SHORTCUTS[sc] != nil else {
                return deny(req, "shortcut is not on the allowlist", category: "shortcut")
            }
            let ok = pressShortcut(sc)
            auditPrivacySafe(["event": ok ? "SHORTCUT" : "SHORTCUT_FAIL", "shortcut": sc,
                              "bundle_id": obs.bundleId, "correlation_id": obs.correlationId])
            return Response(id: req.id, ok: ok, verb: req.verb,
                            reason: ok ? "pressed allowlisted shortcut \(sc)" : "shortcut failed",
                            data: ["shortcut": sc], correlationId: req.correlationId)
        case .clickPoint:
            guard let rx = req.clickX, let ry = req.clickY else {
                return deny(req, "clickX/clickY required (relative to the window)", category: "schema")
            }
            let point = CGPoint(x: obs.bounds.origin.x + rx, y: obs.bounds.origin.y + ry)
            if !obs.bounds.contains(point) { return deny(req, "click point outside target window",
                                                        category: "geometry") }
            if roleAtPointIsSensitiveOrUnknown(point) {
                return deny(req, "UI element at click point is secure/unknown", category: "secure_field")
            }
            let ok = clickAt(point)
            if frontmostBundleId() != obs.bundleId { observations.removeAll() }
            auditPrivacySafe(["event": ok ? "CLICK" : "CLICK_FAIL", "bundle_id": obs.bundleId,
                              "window_id": String(obs.windowId), "correlation_id": obs.correlationId])
            return Response(id: req.id, ok: ok, verb: req.verb,
                            reason: ok ? "single click inside the target window" : "click failed",
                            data: ["x": String(Int(point.x)), "y": String(Int(point.y))],
                            correlationId: req.correlationId)
        default:
            return deny(req, "unreachable", category: "internal")
        }

    case .probe, .stop, .reset, .cancel:
        return deny(req, "unreachable", category: "internal")
    }
}

// MARK: - Startup + loop

try? FileManager.default.createDirectory(atPath: STATE_DIR, withIntermediateDirectories: true)
if FileManager.default.fileExists(atPath: STOP_SENTINEL) || FileManager.default.fileExists(atPath: VERB_STOP) { stopped = true }

// Single-controller lock: only one bridge instance may hold the effecting role at a time.
let lockFd = open(CONTROLLER_LOCK, O_CREAT | O_RDWR, 0o600)
haveController = (lockFd >= 0 && flock(lockFd, LOCK_EX | LOCK_NB) == 0)

let encoder = JSONEncoder()
let decoder = JSONDecoder()
while let line = readLine(strippingNewline: true) {
    if line.isEmpty { continue }
    guard let data = line.data(using: .utf8) else { continue }
    #if KAI_TEST_HARNESS
    if let tc = try? decoder.decode(TestControl.self, from: data), tc.verb.hasPrefix("test.") {
        switch tc.verb {
        case "test.set_windows": if let w = tc.windows { TestModel.setWindows(w) }
        case "test.set_frontmost": TestModel.frontmost = tc.frontmost ?? ""
        case "test.set_secure": TestModel.secureField = tc.secure ?? false
        case "test.set_role_sensitive": TestModel.roleSensitive = tc.roleSensitive ?? false
        case "test.set_focused_bounds":
            if let b = tc.bounds { TestModel.focusedBounds = CGRect(x: b["x"] ?? 0, y: b["y"] ?? 0, width: b["w"] ?? 0, height: b["h"] ?? 0) }
            else { TestModel.focusedBounds = nil }
        default: break
        }
        print("{\"id\":\"\(tc.id)\",\"ok\":true,\"verb\":\"\(tc.verb)\"}"); fflush(stdout); continue
    }
    #endif
    let resp: Response
    if let req = try? decoder.decode(Request.self, from: data) {
        if !haveController, Verb(rawValue: req.verb)?.mutating == true {
            resp = deny(req, "another controller holds the desktop lock; refusing simultaneous control",
                        category: "multi_controller")
        } else {
            resp = handle(req)
        }
    } else {
        resp = Response(id: "?", ok: false, verb: "?", reason: "malformed request (schema validation failed)")
    }
    if let out = try? encoder.encode(resp), let s = String(data: out, encoding: .utf8) {
        print(s); fflush(stdout)
    }
}
