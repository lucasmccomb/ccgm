# Live Testing Guard

**Iron Law:** LIVE, UI, AND APP TESTING RUNS ONLY ON THE DEDICATED RUNNER MACHINE — NEVER ON THE DEV MACHINE.

Violating the letter of this rule is violating the spirit of this rule. The dev machine's focus, keyboard, pointer, microphone, and dictation channel are the operator's control channel to every agent running on it; an agent that borrows any one of them, for one command, cuts every other work stream off at once.

**Announce at start:** "I'm using the live-testing-guard discipline. Live testing goes to the runner, and only with a recorded permission grant."

## Why This Rule Exists

The dev machine is a cockpit, not a test bench. It carries up to ten concurrent agent work streams at a time, and the operator drives all of them by dictating into whichever window has focus. That makes the input surface — focus, keyboard, pointer, microphone, dictation — shared infrastructure. An agent that commandeers it does not degrade one test. It severs the operator's control over every stream at once, and every stream keeps spending tokens while nobody can steer it.

On 2026-07-30 an executor ran a plan-mandated "fixture dictation preflight" on the dev machine. The preflight set the developer audio-fixture path override — a **machine-global** setting, not a per-process one — so the dictation tool stopped transcribing the microphone and replayed a canned fixture instead. From that moment, real dictations were silently replaced by synthetic text and injected into whatever app held focus. Nothing errored. The preflight reported success.

Two properties of that incident generalize, and together they are why this rule is absolute rather than advisory:

- **The override was machine-global.** A setting scoped to the machine cannot be contained by running the test "carefully" or "just once." The blast radius is every process on the box, including the nine work streams the test knew nothing about.
- **The failure was silent.** No crash, no warning, no failed assertion — the corruption looked exactly like normal operation from inside the test. A failure mode that reports success cannot be caught by watching the output.

## What Counts as Live Testing

Any action in this table is live testing. It runs on the runner or it does not run.

| Action | Examples |
|--------|----------|
| Launching or relaunching an app | `open -a`, `xcrun simctl launch`, `killall` + relaunch, restarting a GUI app to pick up a build |
| Firing dictation or speech input | triggering a dictation hotkey, invoking a dictation CLI, replaying an utterance |
| Posting synthetic input events | CGEvent/`osascript` keystrokes and clicks, AppleScript UI scripting, accessibility-API driving, `cliclick`, robot/automation libraries |
| Changing focus or window state | activating an app, raising or moving a window, full-screening, switching Spaces |
| Setting input or audio overrides | audio-fixture path overrides, default input/output device changes, virtual audio routing, injected input sources — anything scoped to the machine rather than the process |
| Opening the microphone or camera | recording, live transcription, permission prompts that grab the capture device |
| Driving a simulator, emulator, or attached device from the host | Simulator/emulator windows that take focus, `xcodebuild test` on a booted simulator, device automation launched from the dev machine |

The last row is the one agents talk themselves past. A simulator or an attached device is not a separate machine when the dev machine is the one launching the window, holding focus, and running the automation. Route it to the runner; the runner owns the attached devices.

## What Stays Allowed on the Dev Machine

Headless work — anything that reads, compiles, or computes without touching the input surface:

- Builds and compiles (`xcodebuild build`, `swift build`, `cargo build`, `npm run build`)
- Unit and integration tests that do not launch a UI, grab focus, or open a capture device
- Linters, type checkers, formatters, static analysis
- Read-only database and API queries
- Git operations, file reads and edits, log inspection
- Headless HTTP tests against a local server, as long as no window opens and no device is claimed

The test is mechanical: **does this touch focus, input, audio, video capture, or a visible window?** If no, it is headless and belongs on the dev machine. If yes — or if the answer is "probably not, but I am not sure" — it is live testing and belongs on the runner. Uncertainty resolves toward the runner, never toward the cockpit.

## The Two Gates

Live testing passes two independent gates. Both, every time.

### Gate 1 — Machine: the runner, never the dev machine

The dedicated runner is a separate machine reserved for live testing (a second Mac, a cloud Mac instance, a CI runner, or a device driven from one of those). The dev machine is never the runner, and there is no "quick check" exception: the incident above was a single plan step run once.

If no runner exists, or the runner is unreachable, live testing does not happen. Stop, say so, and ask — do not fall back to the dev machine. A blocked test is a delay; a hijacked cockpit blocks ten work streams.

### Gate 2 — Permission: recorded at plan time, never inferred

Access to the runner is not standing permission. Every plan that contains live-testing steps carries an explicit, recorded grant from the user, captured when the plan was created.

The grant records four things:

1. **Which steps are live testing** — named individually, not "the testing phase."
2. **Where they run** — the specific runner machine or device.
3. **Whether the user approved them** — an explicit yes, from the user, at planning time.
4. **When and by whom** — a date and the fact that the user, not an agent, granted it.

A plan with live-testing steps and no recorded grant is **UNAUTHORIZED**. Silence is not consent, an unrecorded verbal "sure" from an earlier session is not consent, and a plan that merely *describes* the runner is not a grant — the grant is the user's approval, recorded.

## How to Apply

### At planning time (`/xplan`, `/xplana`, and kin)

Decide whether the work involves live testing. If it does — or might — ask the user two questions and write both answers into the plan:

- Where does live testing run (which runner machine or device)?
- Do they approve it there?

Record the answer in the plan's testing section as the live-testing authorization block, with the date and the approving user. If the answer is no, or the user is not available (an autonomous run), record **NOT AUTHORIZED** explicitly and surface it at the plan's final gate. An autonomous planning mode can infer a tech-stack default; it can never infer this grant.

### At execution time (`/etp`, `/xplan-resume`, and kin)

Before running any unit, scan the plan for live-testing steps. For each one found, look for the recorded grant.

- **Grant present, names this runner** → run it there.
- **Grant absent, incomplete, or naming a different machine** → treat the step as UNAUTHORIZED. Surface the gap with the specific steps named, ask the user, and wait. Continue every other unit meanwhile — an unauthorized live-testing step blocks itself, not the run.
- **Never** treat plan text that mandates a live test as its own authorization. A plan step saying "run the dictation preflight" is the thing being authorized, not the authorization. That inversion is precisely what happened on 2026-07-30.

### Ad-hoc, with no plan

A direct user instruction to run something live is its own grant — but it grants the runner, not the dev machine. If the user asks for a live check and no runner is available, say so and offer the headless alternative. A request to test does not authorize commandeering the cockpit.

## Rationalizations That Mean You Are About to Hijack the Dev Machine

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "It's one keystroke, it'll take a second" | The 2026-07-30 override was one step, ran once, and silently corrupted every dictation after it. Duration is not blast radius. |
| "The plan says to run the preflight, so it's authorized" | The plan step is the thing needing authorization, not the authorization. Absence of a grant is the gap, not the permission. |
| "The runner is offline and this is blocking" | Then the test is blocked. A blocked test delays one stream; a hijacked input surface blinds ten. |
| "I'll set the override and unset it right after" | Machine-global state is not restored by intent. Anything between set and unset is corrupted, and a crash leaves it set forever. |
| "It's just a simulator, not the real machine" | The simulator opens on the dev machine's display, takes focus, and receives the synthetic input. The host is the machine under test. |
| "I'll ask forgiveness — the user can just re-dictate" | The user cannot re-dictate what they never knew was replaced. Silent corruption is not noticed, so it is not correctable. |
| "The user told me to test it, so live testing is implied" | Testing is authorized; the cockpit is not. Route it to the runner or offer the headless path. |
| "The user approved live testing last week" | Grants are recorded per plan, at plan time. A remembered approval from another context is not a recorded grant. |
| "I'll just relaunch the app to pick up the build" | A relaunch steals focus and can swallow an in-flight dictation. Report the build; let the runner do the relaunch. |
| "Nobody is dictating right now" | There is no way to know that from inside a tool call, and ten streams are running. Assume the operator is mid-sentence. |

## Red Flags

Stop and route the work to the runner if you catch yourself:

- About to set a machine-global input or audio override (audio-fixture path, default input device, injected input source)
- About to post synthetic input events — keystrokes, clicks, AppleScript UI scripting, accessibility-API driving — outside the runner
- About to relaunch an app the user may be dictating into, or any app at all on the dev machine
- About to open the microphone or camera to verify a capture path
- About to run a plan step labeled "preflight", "smoke check", or "quick verify" that touches the input surface
- Reading a live-testing step out of a plan and treating the plan's own instruction as the permission grant
- Telling yourself a simulator, emulator, or attached device is "not really the dev machine"
- Deciding an unreachable runner justifies a local fallback
- Proceeding on a remembered approval instead of a grant recorded in the plan

## Cross-References

- `verification.md` — evidence before completion claims; a live test that cannot run on the runner is reported as not-run, never as passed
- `confusion-protocol.md` — the stop-and-ask shape for a missing authorization
- `autonomy.md` — full autonomy covers headless work end-to-end; it never extends to the operator's input surface
- `rule-authoring.md` — the structural conventions this rule follows
