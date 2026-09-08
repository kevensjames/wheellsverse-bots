# KAI Computer Operations — Operator Guide

Covers the local harness runtime and desktop bridge as they exist today. It does not
describe a Holding Command panel or hosted dispatch, because those are not built yet.

## What exists right now

- A pinned DeepSeek Harness runtime at `/Users/jhonwheeler/kai-harness-runtime`,
  installed **outside** application source.
- Version-controlled policy overlays in `ops/computer-ops/harness/` that remove
  capability from the harness and pin the model route.
- A Python ACP connector that owns the harness child over stdio and answers its
  permission requests from KAI policy.
- A macOS desktop bridge with a closed verb set and a deterministic gate.

Nothing is deployed, nothing runs at startup, and no desktop verb has executed.

## Daily operations

```sh
cd /Users/jhonwheeler/wheellsverse-kai-compute

./ops/computer-ops/runtime/kai-harness-ctl.sh status   # pin drift, build, disk, launchd
./ops/computer-ops/runtime/kai-harness-ctl.sh verify   # attest ALL modes (the important one)
```

`verify` is the check to run after any change to an overlay, and after any upgrade. It
composes each autonomy mode through the real harness and asserts 25 containment
invariants per mode against the resulting tree. It is what catches a capability
silently coming back.

**Read `pin state` in `status` carefully.** `DRIFTED` means the runtime is not the
commit that was reviewed, and no attestation result should be trusted until it matches
again.

## Verification suite

```sh
python3 ops/computer-ops/connector/test_attest.py          # 8 attestation unit checks
python3 ops/computer-ops/bridge/test_desktop_bridge.py     # 13 gate checks
python3 ops/computer-ops/probes/verify_modes.py            # 3 modes x 25 invariants (real harness)
python3 ops/computer-ops/probes/probe_acp_local.py         # live ACP round trip, local model
```

The first two need nothing but Python. The last two need the built harness; the ACP
probe additionally needs a local model endpoint serving.

## Granting desktop permissions (operator only — KAI cannot do this)

Desktop verbs report `PERMISSION_NOT_GRANTED` until macOS grants the bridge binary its
TCC permissions. There is no API for this; it is a manual, per-binary grant:

**System Settings → Privacy & Security →**
- **Screen Recording** — required for `capture_screen`, `capture_window`
- **Accessibility** — required for `list_windows` and any window interaction

Grant them to the binary that actually runs the bridge (the Python interpreter or a
signed wrapper), not to the terminal you happen to be using. After granting, confirm:

```sh
python3 -c "import sys;sys.path.insert(0,'ops/computer-ops/bridge');
import desktop_bridge as d;print(d.capability_report())"
```

Note this probe attempts a real 1×1 screen capture and a real System Events query, so
it may surface permission dialogs. That is the intended grant flow.

To revoke, remove the entries in the same panes. Revocation is immediate; the gate will
report `PERMISSION_NOT_GRANTED` on the next call.

## Upgrading the pinned harness

```sh
# 1. Review the new commit's diff, especially packages/sandbox, packages/interaction,
#    packages/llm and any new lifecycle scripts.
# 2. Update PINNED_COMMIT in ops/computer-ops/runtime/kai-harness-ctl.sh
# 3. ./ops/computer-ops/runtime/kai-harness-ctl.sh upgrade
```

`upgrade` records a rollback point (previous commit + lockfile) under
`$KAI_HARNESS_ROOT/backup-<short-sha>/` **before** touching anything, then reinstalls
with `--frozen-lockfile`, rebuilds, and runs `verify`.

Upstream is a developer preview that states breaking changes are expected. Treat every
upgrade as a review, not a bump. In particular, if `verify` reports a **MISSING** plugin
id, upstream renamed or removed something and an overlay is no longer disabling what it
claims — that is a hard stop, not a warning.

## Rollback

```sh
# Set PINNED_COMMIT back to the recorded commit and re-run upgrade:
cat /Users/jhonwheeler/kai-harness-runtime/backup-<short-sha>/COMMIT
# edit PINNED_COMMIT in kai-harness-ctl.sh, then:
./ops/computer-ops/runtime/kai-harness-ctl.sh upgrade
```

The overlays are version-controlled separately, so rolling the runtime back does not
roll back policy. If a rollback crosses a change in plugin ids, run `verify` and expect
it to tell you.

## Uninstall

```sh
./ops/computer-ops/runtime/kai-harness-ctl.sh uninstall   # prompts; type REMOVE
```

Removes the harness checkout and `DSH_HOME` (sessions, storages, profiles). It does
**not** touch the KAI repository, and it does **not** revoke macOS TCC grants — remove
those by hand in System Settings. `node` and the corepack `pnpm` shim are left alone
because other projects share them.

## Enabling persistent startup (deliberately not done)

`runtime/com.wheellsverse.kai-harness.plist.template` is a template, not an installed
service, and `status` will tell you it is not loaded. Installing it is an explicit
operator decision; the header of that file carries the exact commands.

Two things about it are load-bearing: it is a **LaunchAgent**, not a LaunchDaemon,
because TCC grants only apply inside a user session — a daemon would report
`DESKTOP_UNAVAILABLE` forever. And it starts the **connector**, never the harness: the
harness must stay a short-lived per-mission child so that a STOP or crash cannot leave
an agent alive.

## If something looks wrong

- **`verify` fails on an id** → treat as a containment regression. Do not dispatch.
- **`MODEL_UNAVAILABLE`** → the configured route never registered. This is correct
  behaviour, not a bug to route around: the connector deliberately refuses to substitute
  a different provider, because under LOCAL_ONLY that would mean a cloud request.
- **Desktop verb returns `PERMISSION_NOT_GRANTED`** → grant TCC above. Do not attempt to
  work around it; there is no supported way, and any workaround would be exactly the
  permission-dialog bypass the design forbids.
