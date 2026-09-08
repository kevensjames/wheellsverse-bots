// KAI Desktop Bridge — the ONLY process permitted to touch the macOS desktop.
//
// WHY THIS IS NATIVE. macOS attributes a TCC grant (Screen Recording, Accessibility) to
// the EXECUTABLE. Granting Screen Recording to /usr/bin/python3 grants it to every Python
// script on the machine, forever, including anything dropped there later. The same is
// true of node, bash, Terminal and the harness process. So the trusted desktop controller
// must be its own narrow binary with its own stable bundle identifier, and nothing else.
//
// WHAT IT IS NOT. There is no shell verb, no AppleScript verb, no "run this" verb, no
// raw coordinate clicking and no way to name a process by pid without validation. The
// vocabulary below is the whole surface; anything absent from it cannot be asked for.
//
// PROTOCOL. Newline-delimited JSON on stdin/stdout. The bridge opens no socket and makes
// no network call: it is spawned by the KAI connector and speaks only to its parent.

import Foundation
#if canImport(AppKit)
import AppKit
#endif

let BUNDLE_ID = "com.wheellsverse.kai.desktopbridge"
let VERSION = "0.1.0"

// MARK: - Vocabulary

enum Verb: String, CaseIterable {
    case listWindows      = "desktop.list_windows"
    case observeWindow    = "desktop.observe_window"
    case focusWindow      = "desktop.focus_window"
    case clickElement     = "desktop.click_accessibility_element"
    case typeText         = "desktop.type_text"
    case pressShortcut    = "desktop.press_shortcut"
    case launchApp        = "desktop.launch_approved_application"
    case stop             = "desktop.stop"
    case probe            = "desktop.probe"

    /// Verbs that change observable state. Each requires a fresh, unexpired observation
    /// of the exact target AND an approval minted by KAI; the bridge never self-approves.
    var mutating: Bool {
        switch self {
        case .focusWindow, .clickElement, .typeText, .pressShortcut, .launchApp: return true
        default: return false
        }
    }

    var needsAccessibility: Bool {
        switch self {
        case .listWindows, .observeWindow, .focusWindow, .clickElement,
             .typeText, .pressShortcut: return true
        default: return false
        }
    }
}

/// Applications whose windows are never observed or interacted with, whatever an
/// allowlist says. Credential and identity surfaces are excluded by name because a
/// screenshot or a synthetic keystroke there is unrecoverable.
let SENSITIVE_APPS: Set<String> = [
    "1Password", "1Password 7", "1Password 8", "Bitwarden", "KeePassXC", "Dashlane",
    "LastPass", "Keychain Access", "Passwords", "Authy", "Proton Pass", "Secretive",
    "System Settings", "System Preferences", "Security & Privacy",
    "Messages", "Mail", "FaceTime"
]

/// Window-title fragments that indicate a credential, payment, or high-consequence
/// portal. Matched case-insensitively against the CURRENT title at action time, because
/// a tab can change under a window that was legitimately approved a moment ago.
let SENSITIVE_TITLE_FRAGMENTS: [String] = [
    "password", "passkey", "sign in", "log in", "login", "one-time", "verification code",
    "2fa", "two-factor", "mfa", "authenticator", "recovery code", "seed phrase",
    "bank", "payment", "checkout", "card number", "billing", "wire transfer",
    "uscis", "immigration", "visa application", "passport",
    "medical", "health record", "patient", "insurance claim",
    "keychain", "privacy & security", "filevault"
]

// MARK: - Wire types

struct Request: Decodable {
    let id: String
    let verb: String
    let missionId: String?
    let deviceId: String?
    let approvalToken: String?
    let observationToken: String?
    let app: String?
    let windowId: Int?
    let elementId: String?
    let text: String?
    let shortcut: String?
    let allowedApps: [String]?
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
}

struct WindowInfo: Encodable {
    let windowId: Int
    let app: String
    let title: String
    let sensitive: Bool
}

// MARK: - Observation tokens

/// A record that a specific window was observed at a specific moment, in a specific
/// state. Interaction verbs must present one.
///
/// This is what stops "click the button I saw ten seconds ago" acting on whatever
/// happens to be under that position now. The token binds the window id, the app, the
/// title AT OBSERVATION TIME and the frontmost app; if any of those differ when the
/// action is attempted, the observation is stale and the action is refused rather than
/// applied to a changed screen.
struct Observation {
    let token: String
    let windowId: Int
    let app: String
    let title: String
    let frontmostApp: String
    let at: Date
    let missionId: String
    let deviceId: String
}

let OBSERVATION_TTL: TimeInterval = 8.0
var observations: [String: Observation] = [:]

/// Rate limit: desktop input is the most consequential thing here, so it is bounded
/// independently of anything KAI does. A runaway loop upstream cannot become a runaway
/// stream of keystrokes.
var actionTimestamps: [Date] = []
let MAX_ACTIONS_PER_MINUTE = 20

var stopped = false

// MARK: - Capability probing (truthful, never a flag)

func hasInteractiveDesktop() -> Bool {
    #if canImport(AppKit)
    return NSWorkspace.shared.frontmostApplication != nil
    #else
    return false
    #endif
}

/// Probes the Accessibility grant WITHOUT prompting. `AXIsProcessTrusted()` reports the
/// current state; the prompting variant is deliberately not used, because a helper that
/// pops a system dialog on startup trains an operator to click through them.
func hasAccessibility() -> Bool {
    #if canImport(AppKit)
    return AXIsProcessTrusted()
    #else
    return false
    #endif
}

func bundleIdentifier() -> String {
    Bundle.main.bundleIdentifier ?? ProcessInfo.processInfo.environment["KAI_BRIDGE_BUNDLE_ID"] ?? ""
}

/// The bridge refuses to run at all unless it is the expected identity. An ad-hoc or
/// renamed build would collect TCC grants under an identity that changes on the next
/// rebuild, silently breaking the grant and tempting a re-grant to something broader.
func identityAcceptable() -> Bool {
    bundleIdentifier() == BUNDLE_ID
}

// MARK: - Window enumeration

func listWindows(allowed: Set<String>) -> [WindowInfo] {
    #if canImport(AppKit)
    guard let raw = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements],
                                               kCGNullWindowID) as? [[String: Any]] else { return [] }
    return raw.compactMap { w in
        guard let owner = w[kCGWindowOwnerName as String] as? String,
              let wid = w[kCGWindowNumber as String] as? Int else { return nil }
        let title = (w[kCGWindowName as String] as? String) ?? ""
        let sensitive = SENSITIVE_APPS.contains(owner) || isSensitiveTitle(title)
        // Only approved applications are ever returned. A window the mission was not
        // authorised for is not merely un-actionable, it is not disclosed at all.
        guard allowed.contains(owner) else { return nil }
        return WindowInfo(windowId: wid, app: owner,
                          title: sensitive ? "<redacted: sensitive window>" : title,
                          sensitive: sensitive)
    }
    #else
    return []
    #endif
}

func isSensitiveTitle(_ title: String) -> Bool {
    let t = title.lowercased()
    return SENSITIVE_TITLE_FRAGMENTS.contains { t.contains($0) }
}

func frontmostAppName() -> String {
    #if canImport(AppKit)
    return NSWorkspace.shared.frontmostApplication?.localizedName ?? ""
    #else
    return ""
    #endif
}

// MARK: - Gate

func rateLimitOk() -> Bool {
    let cutoff = Date().addingTimeInterval(-60)
    actionTimestamps = actionTimestamps.filter { $0 > cutoff }
    return actionTimestamps.count < MAX_ACTIONS_PER_MINUTE
}

func handle(_ req: Request) -> Response {
    guard let verb = Verb(rawValue: req.verb) else {
        return Response(id: req.id, ok: false, verb: req.verb,
                        reason: "unknown verb; the vocabulary is fixed and does not include this")
    }

    // 1. STOP outranks everything, including an otherwise valid approval.
    if verb == .stop {
        stopped = true
        observations.removeAll()
        return Response(id: req.id, ok: true, verb: req.verb,
                        reason: "stopped; all observations invalidated and control released")
    }
    if stopped {
        return Response(id: req.id, ok: false, verb: req.verb,
                        reason: "STOP is engaged; desktop control has been released")
    }

    // 2. Identity, before anything touches the desktop.
    if verb != .probe && !identityAcceptable() {
        return Response(id: req.id, ok: false, verb: req.verb,
                        reason: "refusing to act: running as bundle '\(bundleIdentifier())', " +
                                "expected '\(BUNDLE_ID)'. A TCC grant to a generic or unstable " +
                                "identity would extend to everything that identity runs.")
    }

    if verb == .probe {
        return Response(id: req.id, ok: true, verb: req.verb, data: [
            "version": VERSION,
            "bundle_id": bundleIdentifier(),
            "identity_acceptable": String(identityAcceptable()),
            "interactive_desktop": String(hasInteractiveDesktop()),
            "accessibility_granted": String(hasAccessibility()),
            "required_bundle_id": BUNDLE_ID,
            "grant_location": "System Settings > Privacy & Security > {Screen Recording, Accessibility}"
        ])
    }

    // 3. Mission/device binding. A verb with no mission is not a desktop action KAI knows about.
    guard let missionId = req.missionId, !missionId.isEmpty,
          let deviceId = req.deviceId, !deviceId.isEmpty else {
        return Response(id: req.id, ok: false, verb: req.verb,
                        reason: "missing mission/device binding")
    }

    // 4. Capability probe.
    if !hasInteractiveDesktop() {
        return Response(id: req.id, ok: false, verb: req.verb,
                        reason: "DESKTOP_UNAVAILABLE: no interactive session on this host")
    }
    if verb.needsAccessibility && !hasAccessibility() {
        return Response(id: req.id, ok: false, verb: req.verb,
                        reason: "PERMISSION_NOT_GRANTED: Accessibility has not been granted to " +
                                BUNDLE_ID + "; an operator must grant it in System Settings")
    }

    let allowed = Set(req.allowedApps ?? [])
    if allowed.isEmpty {
        return Response(id: req.id, ok: false, verb: req.verb,
                        reason: "no approved applications for this mission (default deny)")
    }

    switch verb {
    case .listWindows:
        return Response(id: req.id, ok: true, verb: req.verb, windows: listWindows(allowed: allowed))

    case .observeWindow:
        guard let wid = req.windowId else {
            return Response(id: req.id, ok: false, verb: req.verb, reason: "windowId required")
        }
        guard let win = listWindows(allowed: allowed).first(where: { $0.windowId == wid }) else {
            return Response(id: req.id, ok: false, verb: req.verb,
                            reason: "window not found among approved applications")
        }
        if win.sensitive {
            // Blocked, not masked: masking cannot be guaranteed across window moves,
            // overlays and Space changes, so capture is refused outright.
            return Response(id: req.id, ok: false, verb: req.verb,
                            reason: "sensitive window: observation is blocked, not masked")
        }
        let token = UUID().uuidString
        observations[token] = Observation(token: token, windowId: wid, app: win.app,
                                          title: win.title, frontmostApp: frontmostAppName(),
                                          at: Date(), missionId: missionId, deviceId: deviceId)
        return Response(id: req.id, ok: true, verb: req.verb,
                        data: ["app": win.app, "title": win.title],
                        observationToken: token, expiresInSeconds: OBSERVATION_TTL)

    case .focusWindow, .clickElement, .typeText, .pressShortcut, .launchApp:
        // 5. Consequential: an approval minted by KAI is required. The bridge has no
        //    path to create one, so it cannot authorise its own action.
        guard let approval = req.approvalToken, !approval.isEmpty else {
            return Response(id: req.id, ok: false, verb: req.verb,
                            reason: "APPROVAL_REQUIRED: this verb changes state outside KAI")
        }
        if !rateLimitOk() {
            return Response(id: req.id, ok: false, verb: req.verb,
                            reason: "rate limit exceeded (\(MAX_ACTIONS_PER_MINUTE)/min)")
        }
        // 6. Fresh observation of THIS target.
        if verb != .launchApp {
            guard let tok = req.observationToken, let obs = observations[tok] else {
                return Response(id: req.id, ok: false, verb: req.verb,
                                reason: "a fresh observation of the target is required")
            }
            if Date().timeIntervalSince(obs.at) > OBSERVATION_TTL {
                observations.removeValue(forKey: tok)
                return Response(id: req.id, ok: false, verb: req.verb,
                                reason: "observation expired; re-observe before acting")
            }
            if obs.missionId != missionId || obs.deviceId != deviceId {
                return Response(id: req.id, ok: false, verb: req.verb,
                                reason: "observation belongs to a different mission or device")
            }
            if let wid = req.windowId, wid != obs.windowId {
                return Response(id: req.id, ok: false, verb: req.verb,
                                reason: "observation does not cover this window")
            }
            // 7. The screen must not have changed under us.
            let now = listWindows(allowed: allowed).first(where: { $0.windowId == obs.windowId })
            guard let current = now else {
                return Response(id: req.id, ok: false, verb: req.verb,
                                reason: "target window has disappeared since observation")
            }
            if current.title != obs.title {
                return Response(id: req.id, ok: false, verb: req.verb,
                                reason: "target window title changed since observation " +
                                        "(possible navigation); re-observe before acting")
            }
            if isSensitiveTitle(current.title) {
                return Response(id: req.id, ok: false, verb: req.verb,
                                reason: "target became a sensitive window; refusing")
            }
            if frontmostAppName() != obs.frontmostApp {
                // The user very likely switched apps. Treat that as intervention.
                observations.removeAll()
                return Response(id: req.id, ok: false, verb: req.verb,
                                reason: "focus changed since observation (user intervention); " +
                                        "control released, re-observe before acting")
            }
        }
        if verb == .typeText, let t = req.text, isSensitiveTitle(t) {
            return Response(id: req.id, ok: false, verb: req.verb,
                            reason: "refusing to type text that looks like a credential")
        }
        actionTimestamps.append(Date())
        // Execution is intentionally NOT implemented in this build: the helper cannot be
        // signed on this machine, so it must never perform a desktop action under an
        // identity that will change. The gate above is complete and testable; the
        // effecting code lands with the signed build.
        return Response(id: req.id, ok: false, verb: req.verb,
                        reason: "GATE_PASSED_EXECUTION_WITHHELD: this build is unsigned; " +
                                "desktop effects are not performed under an unstable identity")

    case .stop, .probe:
        return Response(id: req.id, ok: false, verb: req.verb, reason: "unreachable")
    }
}

// MARK: - Loop

let encoder = JSONEncoder()
let decoder = JSONDecoder()
while let line = readLine(strippingNewline: true) {
    if line.isEmpty { continue }
    guard let data = line.data(using: .utf8) else { continue }
    let resp: Response
    if let req = try? decoder.decode(Request.self, from: data) {
        resp = handle(req)
    } else {
        resp = Response(id: "?", ok: false, verb: "?", reason: "malformed request")
    }
    if let out = try? encoder.encode(resp), let s = String(data: out, encoding: .utf8) {
        print(s)
        fflush(stdout)
    }
}
