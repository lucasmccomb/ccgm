# Live Testing Guard

Live, UI, and app testing runs only on the dedicated runner machine, never on the dev machine. The dev machine's focus, keyboard, pointer, microphone, and dictation channel are the operator's control channel to every agent running on it; an agent that borrows any of them, even for one command, cuts every other work stream off at once, and the other streams keep spending tokens while nobody can steer them.

The failure that shaped this rule was a plan-mandated "dictation preflight" that set a machine-global audio-fixture override on the dev machine: from that moment real dictations were silently replaced with canned text in whatever window had focus, and the preflight reported success. Two properties generalize. Machine-global state cannot be contained by running a test carefully or once. And the failure was silent, so watching the output cannot catch it.

## What Counts as Live Testing

| Action | Examples |
|--------|----------|
| Launching or relaunching an app | `open -a`, `xcrun simctl launch`, `killall` plus relaunch, restarting a GUI app to pick up a build |
| Firing dictation or speech input | a dictation hotkey, a dictation CLI, replaying an utterance |
| Posting synthetic input events | CGEvent or `osascript` keystrokes and clicks, AppleScript UI scripting, accessibility-API driving, `cliclick`, robot libraries |
| Changing focus or window state | activating an app, raising or moving a window, full-screening, switching Spaces |
| Setting input or audio overrides | audio-fixture paths, default input or output devices, virtual audio routing, injected input sources |
| Opening the microphone or camera | recording, live transcription, permission prompts that grab the capture device |
| Driving a simulator, emulator, or attached device from the host | simulator windows that take focus, `xcodebuild test` on a booted simulator, device automation launched from the dev machine |

A simulator or attached device is not a separate machine when the dev machine launches the window, holds focus, and runs the automation.

## What Stays Allowed on the Dev Machine

Headless work: builds and compiles, unit and integration tests that open no UI and claim no capture device, linters and type checkers, read-only database and API queries, git and file operations, log inspection, and headless HTTP tests against a local server. The test is mechanical: does this touch focus, input, audio or video capture, or a visible window? If no, it is headless. If yes, or if the answer is "probably not," it belongs on the runner.

## The Two Gates

**Machine.** The runner is a separate machine reserved for live testing (a second Mac, a cloud Mac, a CI runner, or a device driven from one of those). If no runner exists or it is unreachable, live testing does not happen: stop, say so, and ask. Never fall back to the dev machine.

**Permission.** Access to the runner is not standing permission. Every plan with live-testing steps carries an explicit grant recorded when the plan was created: which steps are live testing (named individually), where they run, that the user approved them, and when. A plan with live-testing steps and no recorded grant is unauthorized. Silence, an unrecorded earlier "sure," and a plan that merely describes the runner are not grants.

## How to Apply

- **Planning** (`/xplan`, `/xplana`): if the work involves or might involve live testing, ask where it runs and whether the user approves it there, and record both in the plan's testing section with the date. If the answer is no or the user is unavailable, record NOT AUTHORIZED and surface it at the plan's final gate. An autonomous planner may infer a tech-stack default; it never infers this grant.
- **Execution** (`/etp`, `/xplan-resume`): before running any unit, scan the plan for live-testing steps and check each for its grant. Grant present and naming this runner: run it there. Grant absent, incomplete, or naming another machine: treat the step as unauthorized, name the steps, ask, and continue every other unit meanwhile. A plan step that mandates a live test is the thing being authorized, not the authorization.
- **Ad hoc**: a direct user instruction to run something live grants the runner, not the dev machine. With no runner available, say so and offer the headless alternative.

A blocked test delays one stream; a hijacked input surface blinds ten. Uncertainty resolves toward the runner.
