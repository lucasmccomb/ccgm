# Latent vs Deterministic Work

Agent bugs often come from doing deterministic work in latent space: the model reasoning about something a script could compute exactly. Before acting on a step, classify it.

- **Latent**: judgment, synthesis, open-ended choice. Needs the model. No single right answer.
- **Deterministic**: same input always gives the same output. A short script produces it exactly, faster, cheaper, and without fabrication.

Mixing the two is the bug. A script that weighs tradeoffs is over-engineered; a model that adds timestamps in its head is wrong on the first DST boundary.

| Work | Class | Belongs in |
|------|-------|-----------|
| Is this PR ready to merge? | Latent | Model |
| Summarizing an error log | Latent | Model |
| Picking which test suite to run | Latent | Model |
| Computing `now - event_time` in minutes | Deterministic | Script |
| Converting UTC to local time | Deterministic | Script |
| Grepping for a keyword across files | Deterministic | Script |
| Counting lines, files, matches | Deterministic | Script |
| Parsing a URL, a date, a path | Deterministic | Script |
| Reading the contents of a known file | Deterministic | Tool (Read) |

Reach for a script or an existing tool when you catch yourself doing arithmetic on numbers that came from data, converting timezones or units by hand, eyeballing whether a regex matches, inferring file existence from naming, counting without `wc -l`, remembering a value from earlier in the session instead of reading it fresh, or parsing JSON or CSV by scanning the text. Each of these is a computation that, if wrong once, is wrong every time.

## The Loop

When authoring a skill, hook, or command:

1. List the steps the agent will perform.
2. Mark each step latent or deterministic.
3. For every deterministic step, write or find a script that produces the answer.
4. Have the skill invoke the script instead of describing the computation in prose.
5. Write a test that pins the script's behavior on a representative input.

The script constrains the model; the test constrains the script.

## When to Leave Work in Latent Space

Skip the extraction when the computation runs once in a session, when the inputs are themselves latent ("summarize, then count the key points"), or when the script would be longer than the prose and no clearer. If the model does the same deterministic computation more than twice across sessions, it belongs in a script.
