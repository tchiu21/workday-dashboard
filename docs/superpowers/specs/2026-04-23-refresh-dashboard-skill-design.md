# Claude-driven dashboard refresh skill

**Date:** 2026-04-23
**Status:** Approved, ready for implementation plan

## Problem

Today the workday dashboard is populated by `scripts/generate.py`, which reads API tokens from `.env` (Jira, GitHub, Slack) and hits each service directly. This means:

- Credentials for three services live on disk
- The script is a second code path parallel to the Claude sessions that already have authenticated MCP access to the same services
- Work that lives only in Slack DMs or threads — discussions where the user describes what they're doing but hasn't filed a ticket or PR — is invisible to the dashboard

We want to replace the Python script with a Claude-native flow that uses existing MCP connections, and at the same time surface uncaptured Slack work.

## Goals

- Populate the dashboard without managing API tokens
- Add a new category of dashboard data: work described in Slack DMs and threads that isn't tracked in Jira or GitHub
- Keep the static frontend (`index.html` + `app.js` + `data/*.json`) as the publication surface — nothing changes about how the dashboard is hosted or viewed

## Non-goals

- Keeping the Python script as a fallback
- Scheduling / automated refresh (manual slash-command invocation only)
- Reworking the frontend beyond adding one new section and a warnings banner
- Making the skill generic or reusable across other dashboards

## Design

### File layout

```
~/.claude/skills/refresh-workday-dashboard/
├── SKILL.md                    # orchestrator
├── jira.md                     # RETIRE project queries via jiraconfluencegusto MCP
├── github.md                   # PR queries via Github-Gusto MCP
├── slack-attention.md          # mentions + unanswered @devs pings
└── slack-work-mining.md        # DM + thread scanning for uncaptured work

/Users/tommy.chiu/code/workday-dashboard/
├── app.js                      # + render slack_work section + warnings banner
├── index.html                  # + <div id="slackWorkItems">
├── style.css                   # + .pill.slack-work
└── data/YYYY-MM-DD.json        # adds slack_work and optional warnings
```

Deleted on implementation: `scripts/generate.py`, `.env.example`, any `.env` line in `.gitignore`.

The skill is **user-level** (lives in `~/.claude/skills/`, not in this repo) so it can be invoked from any Claude session without first `cd`ing into the dashboard repo. The dashboard repo path is hardcoded in SKILL.md; if it doesn't exist, the skill prompts the user to update the path and stops.

The skill's `description:` frontmatter triggers on phrases like "refresh dashboard", "update workday dashboard", "refresh today's work".

### Skill flow (SKILL.md orchestrator)

1. **Path check.** Verify `/Users/tommy.chiu/code/workday-dashboard/` exists and is a git repo. If missing, print instructions to edit the hardcoded path in SKILL.md and stop.
2. **MCP availability check.** Confirm `jiraconfluencegusto`, `Github-Gusto`, and `slackgustoofficialmcp` are connected. If any are missing, prompt the user to authenticate (`complete_authentication` tool on the relevant server) and stop.
3. **Compute time window.** `since_last_workday` = start of the previous workday (Mon–Fri, skipping weekends) through now. Compute once, pass into each sub-agent.
4. **Gather data in parallel** — dispatch four sub-agents (`Agent` tool, `general-purpose` subagent) to keep the main thread's context small. Each sub-agent receives the relevant ref file content and the time window, and returns structured JSON. The sub-agents have no cross-dependencies; dedupe between them is handled in step 6.
   - `jira.md` sub-agent → returns `{done, in_progress, up_next}` from Jira
   - `github.md` sub-agent → returns `{done, in_progress, up_next}` from GitHub
   - `slack-attention.md` sub-agent → returns `slack_attention` list
   - `slack-work-mining.md` sub-agent → returns `slack_work` list
5. **Merge** results. Jira + GitHub items concatenate into `done` / `in_progress` / `up_next`. Slack lists remain separate.
6. **Dedupe `slack_work`** against the merged Jira + GitHub results: drop any `slack_work` item whose summary clearly refers to a Jira key or PR number already listed.
7. **Write** `data/YYYY-MM-DD.json`, using today's calendar date.
8. **Prune** JSON files in `data/` from earlier calendar months (keep current month only).
9. **Commit + push.** `git add data/` → commit `Update dashboard YYYY-MM-DD` → push. No-op if nothing changed. Report result to the user.

If any single sub-agent fails, record a string in `warnings[]` in the output JSON (e.g. `"github: MCP not responding"`) and continue. Partial dashboard beats no dashboard.

### Output JSON schema

```json
{
  "date": "2026-04-23",
  "generated_at": "2026-04-23T08:50:00-07:00",
  "warnings": [],
  "done":            [ /* Jira + GitHub items */ ],
  "in_progress":     [ /* Jira + GitHub items */ ],
  "up_next":         [ /* Jira + GitHub items */ ],
  "slack_attention": [ /* unchanged */ ],
  "slack_work":      [ /* NEW */ ]
}
```

Item shapes:

```json
// Jira / GitHub (done, in_progress, up_next) — unchanged
{ "source": "jira" | "github",
  "key": "RETIRE-6789" | "PR #60710",
  "summary": "...",
  "description": "...",
  "url": "..." }

// slack_attention — unchanged
{ "channel": "#retirement-compliance",
  "summary": "...",
  "description": "...",
  "age": "3h",
  "url": "..." }

// slack_work — NEW
{ "source": "slack",
  "context": "DM with Jane Doe" | "#retirement-compliance-lobby thread",
  "summary": "Debugging 5500 extension filing edge case for Acme Corp",
  "description": "Thread where you identified a bug in the extension date calculation and said you'd patch it. Not yet in Jira or a PR.",
  "url": "https://gusto.slack.com/archives/.../p...",
  "age": "4h" }
```

`warnings` is an optional array; omitted or empty on a clean run.

### Per-source details

**`jira.md`** — mechanical port of the current Python script's queries to MCP calls on `jiraconfluencegusto`:
- JQL 1 (active + recently done): `project = RETIRE AND assignee = currentUser() AND status in ("In Progress", "In Review", "Done") ORDER BY updated DESC`, maxResults 50. Categorize `status == "Done"` items into `done` if `updated` falls within the time window; `"In Progress" | "In Review"` → `in_progress`.
- JQL 2 (backlog): `project = RETIRE AND assignee = currentUser() AND status in ("To Do", "Backlog", "Open") ORDER BY priority ASC`, maxResults 5 → `up_next`.
- Description: first 200 chars of ADF-flattened plaintext.

**`github.md`** — queries `Gusto/app` via `Github-Gusto` MCP (GraphQL equivalent or REST, whichever the MCP exposes cleanly):
- PRs authored by `tchiu21`, updated in window → `done` (if `MERGED` and `mergedAt` in window) or `in_progress` (if `OPEN`).
- Open PRs with review requested from `tchiu21` or team `retirement-compliance` → `up_next`.
- Description: title + first 200 chars of body, capped at 200.

**`slack-attention.md`** — mirrors the current Python logic on `slackgustoofficialmcp`:
- Bot mentions (`<@{user_id}>`) in last 24h via `search.messages` → attention items with `age` in hours.
- `@retirement-compliance-devs` user-group mentions in the 4 compliance channels, older than 2h, with no reply from a member of `retirement-compliance-devs` → attention items.

**`slack-work-mining.md`** — the new and fuzzy one:

*Inputs:* time window, user's Slack ID, channels (the 4 compliance channels + all DMs the user has sent a message in during the window). The sub-agent gathers candidates without dedupe against Jira/GH — that's done centrally by the orchestrator in step 6 so all four sub-agents can run in parallel with no cross-dependencies.

*Work signal =* a message **the user sent** that describes work done or in progress. Examples:
- "I pushed a fix for X" / "PR up for Y"
- "I'll take a look at Z" / "looking into the 5500 thing"
- "Debugged this earlier — the issue is..."
- "Working on adding support for QACA plans"
- Descriptions of investigation, design, or findings the user authored

*Exclusions:*
- Pure questions (unless describing the user's own investigation)
- Acknowledgments ("thanks", "yep", "lgtm")
- Messages that clearly map to a Jira key or PR number already in this run's Jira/GH results

*Procedure:*
1. Enumerate DMs via `conversations.list` with `types=im`
2. For each DM + each of the 4 compliance channels: `conversations.history` with `oldest={{window_start_ts}}`
3. Filter to messages where `user == {{me}}`
4. For each candidate, read surrounding thread via `conversations.replies` for context
5. Classify each as work-signal or not
6. For each kept item, produce: 1-sentence `summary` of the work; 1-2 sentence `description` grounded in the thread; `url` = permalink to the message; `context` = either `"DM with {{other_user_name}}"` or `"#{{channel_name}} thread"`; `age` = hours since the message
7. Return the list (may be empty — that's normal)

### Frontend changes

**`index.html`** — add after the slack_attention column:
```html
<section class="column">
  <h2>Slack Work (not in Jira/GH)</h2>
  <div id="slackWorkItems" class="items"></div>
</section>
```

**`app.js`:**
- New `const slackWorkItemsEl = document.getElementById('slackWorkItems');`
- Extend `createPill()`: for items with a `context` field, render `${context}: ${summary}${ageText}` (mirrors the `channel` branch)
- Extend `renderDashboard()`: `renderSection(slackWorkItemsEl, data.slack_work, 'slack-work');`
- If `data.warnings?.length`, render a one-line banner above the dashboard listing each warning (non-blocking, dismissible optional)

**`style.css`** — one new pill class `.pill.slack-work` with a color distinct from `.pill.slack` (amber or similar warm tone) so the two Slack categories are visually distinguishable.

### Error handling & edge cases

| Condition | Behavior |
|-----------|----------|
| Hardcoded repo path missing | Skill prints instructions to fix path; stops before gathering |
| MCP unauthenticated | Skill prints which MCP to auth and stops |
| One source fails mid-run | Skill adds entry to `warnings[]`, continues with others; frontend banner surfaces it |
| Weekend invocation | Skill runs normally; date stamp = today; window = since previous Friday |
| Multiple invocations same day | Newer JSON overwrites older; commit is no-op if git diff empty |
| Empty category | Empty array in JSON; frontend already handles empty sections |
| Dup between slack_work and Jira/GH | Deduped in step 6 of flow; slack_work item dropped |
| Push fails (network/auth/non-ff) | Skill reports failure; JSON left on disk; user reruns or pushes manually |

## Deletions

- `scripts/generate.py` — replaced entirely by the skill
- `.env.example` — no tokens needed anymore
- `.env` entry in `.gitignore` (if present) — no longer relevant

## Out of scope

- Automated scheduling (not even via `/loop` or cron; invocation is manual)
- Any change to how the dashboard is hosted (GitHub Pages or wherever it lives)
- Changes to Jira/GitHub query semantics beyond porting to MCP
- Slack work-mining for channels other than the 4 compliance channels (DMs are included)

## Implementation order (for the plan doc)

1. Frontend changes (add `slack_work` section + warnings banner), using seeded JSON data with a `slack_work` entry to verify rendering
2. Skill scaffolding: `SKILL.md` + four ref files; path check + MCP check + stub sub-agents returning empty results
3. Port `jira.md` from Python logic
4. Port `github.md` from Python logic
5. Port `slack-attention.md` from Python logic
6. Build `slack-work-mining.md` (the new one)
7. Dedupe step and `warnings[]` plumbing
8. End-to-end run: skill produces real JSON, commits, pushes; verify dashboard renders
9. Delete `scripts/generate.py`, `.env.example`, `.gitignore` `.env` line
