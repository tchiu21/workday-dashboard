# Claude-driven dashboard refresh skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the token-based Python data generator with a user-level Claude skill that gathers data via existing MCP connections (Jira, GitHub, Slack), adds a new `slack_work` bucket for work mined from DMs and threads, and publishes by committing + pushing the generated JSON.

**Architecture:** One orchestrator skill at `~/.claude/skills/refresh-dashboard/SKILL.md` dispatches four parallel sub-agents (one per data source). Each sub-agent loads a ref file (`jira.md`, `github.md`, `slack-attention.md`, `slack-work-mining.md`) that describes its MCP calls and classification rules, and returns structured JSON. The orchestrator merges results, dedupes `slack_work` against Jira/GH, writes `data/YYYY-MM-DD.json`, prunes old files, and pushes.

**Tech Stack:** Claude skill (Markdown + frontmatter), MCP tools (`jiraconfluencegusto`, `Github-Gusto`, `slackgustoofficialmcp`), vanilla HTML/JS/CSS for the existing dashboard, `git` for publication.

**Spec reference:** `docs/superpowers/specs/2026-04-23-refresh-dashboard-skill-design.md`

**Testing approach:** This project has no automated test infrastructure, and the skill's behavior is inherently interactive (requires a Claude session with authenticated MCPs). Frontend changes are verified visually by seeding a fixture JSON with a known `slack_work` item and loading `index.html` in a browser. The skill is verified end-to-end by invoking it manually in a fresh Claude session and inspecting the produced JSON + the rendered dashboard.

---

## File Structure

**Skill files (user-level, outside this repo):**
- Create: `~/.claude/skills/refresh-dashboard/SKILL.md` — orchestrator with frontmatter + flow
- Create: `~/.claude/skills/refresh-dashboard/jira.md` — Jira queries via MCP
- Create: `~/.claude/skills/refresh-dashboard/github.md` — GitHub PR queries via MCP
- Create: `~/.claude/skills/refresh-dashboard/slack-attention.md` — mentions + unanswered @devs pings
- Create: `~/.claude/skills/refresh-dashboard/slack-work-mining.md` — DM + thread mining for uncaptured work

**Dashboard repo (this repo):**
- Modify: `index.html` — add `slackWorkItems` section + warnings banner container
- Modify: `app.js` — render slack_work + warnings, extend `createPill()` for `context` field
- Modify: `style.css` — add `.pill.slack-work`, `.slack-work-label`, `.warnings-banner` classes
- Modify: `.gitignore` — remove `.env` line (no longer relevant)
- Delete: `scripts/generate.py`, `scripts/` directory (empty after), `.env.example`

**Fixture for frontend verification:**
- Create then delete: `data/2026-04-23.json` fixture — committed-then-replaced by the first real skill run

---

## Task 1: Seed test fixture + add slack_work column to frontend

**Files:**
- Modify: `data/2026-04-23.json` (or create if missing) — fixture for visual verification
- Modify: `index.html:41-44` — add new `<section>` after slack attention
- Modify: `style.css:121-123` and `:189-198` — add `.slack-work-label` and `.pill.slack-work` classes
- Modify: `app.js` — extend `createPill()` + `renderDashboard()` for `slack_work`

- [ ] **Step 1: Seed a fixture JSON that includes a `slack_work` entry**

Write this to `data/2026-04-23.json` (overwrite any existing file):

```json
{
  "date": "2026-04-23",
  "generated_at": "2026-04-23T09:00:00-07:00",
  "done": [
    {
      "source": "jira",
      "key": "RETIRE-6789",
      "summary": "Fixture: done Jira item",
      "description": "Verifying the done pill still renders.",
      "url": "https://gusto.atlassian.net/browse/RETIRE-6789"
    }
  ],
  "in_progress": [],
  "up_next": [],
  "slack_attention": [
    {
      "channel": "#retirement-compliance",
      "summary": "Fixture: attention item",
      "description": "Verifying the slack attention pill still renders.",
      "age": "2h",
      "url": "https://gusto.slack.com/archives/CXXX/pYYY"
    }
  ],
  "slack_work": [
    {
      "source": "slack",
      "context": "DM with Jane Doe",
      "summary": "Fixture: uncaptured work item",
      "description": "Verifying the slack_work pill renders with context and age.",
      "age": "3h",
      "url": "https://gusto.slack.com/archives/DXXX/pZZZ"
    }
  ]
}
```

- [ ] **Step 2: Add the new section to `index.html`**

Replace lines 41-44 of `index.html` with:

```html
            <section class="section">
                <h2 class="section-label slack-label">Slack Attention</h2>
                <div id="slackItems" class="pill-container"></div>
            </section>

            <section class="section">
                <h2 class="section-label slack-work-label">Slack Work (not in Jira/GH)</h2>
                <div id="slackWorkItems" class="pill-container"></div>
            </section>
```

- [ ] **Step 3: Add CSS for the new label + pill**

Append after line 123 of `style.css` (immediately after `.slack-label { ... }`):

```css
.slack-work-label {
    color: #9c27b0;
}
```

Append after line 198 of `style.css` (immediately after `.pill.slack:hover { ... }`):

```css
.pill.slack-work {
    background-color: rgba(156, 39, 176, 0.15);
    border-color: rgba(156, 39, 176, 0.3);
    color: #9c27b0;
}

.pill.slack-work:hover {
    background-color: rgba(156, 39, 176, 0.25);
    border-color: rgba(156, 39, 176, 0.5);
}
```

Purple (#9c27b0) is distinct from done/in-progress/up-next/slack-attention while staying in the same warm-tone family as pink.

- [ ] **Step 4: Wire the new section into `app.js`**

Add to the DOM elements block (after line 15, the existing `slackItemsEl` line):

```javascript
const slackWorkItemsEl = document.getElementById('slackWorkItems');
```

Extend `createPill()` to handle the `context` field. The current shape (lines 81-92) handles `item.key` (Jira/GitHub) and `item.channel` (Slack attention). Add a `context` branch before the `else`:

```javascript
    // Determine display text based on item type
    let displayText;
    if (item.key) {
        // Jira or GitHub item
        displayText = `${item.key}: ${item.summary}`;
    } else if (item.channel) {
        // Slack attention item
        const ageText = item.age ? ` (${item.age})` : '';
        displayText = `${item.channel}: ${item.summary}${ageText}`;
    } else if (item.context) {
        // Slack work-mining item
        const ageText = item.age ? ` (${item.age})` : '';
        displayText = `${item.context}: ${item.summary}${ageText}`;
    } else {
        displayText = item.summary;
    }
```

Extend `renderDashboard()` by adding one line after the existing `renderSection(slackItemsEl, ...)` call (around line 124):

```javascript
    renderSection(slackWorkItemsEl, data.slack_work, 'slack-work');
```

- [ ] **Step 5: Verify visually**

Run:
```bash
cd /Users/tommy.chiu/code/workday-dashboard && python3 -m http.server 8000
```

Open `http://localhost:8000/` in a browser. Use the `←` navigation if needed to land on 2026-04-23. Expected:
- Five sections render: Done, In Progress, Up Next, Slack Attention, Slack Work (not in Jira/GH)
- The Slack Work section shows one purple pill: "DM with Jane Doe: Fixture: uncaptured work item (3h)"
- Hover on the pill shows the tooltip "Verifying the slack_work pill renders with context and age."
- Done section shows the Jira fixture; Slack Attention shows its fixture
- Kill the server with Ctrl-C.

If rendering is wrong, fix before committing.

- [ ] **Step 6: Commit**

```bash
git add index.html style.css app.js data/2026-04-23.json
git commit -m "Add slack_work section to dashboard

Fixture JSON in data/2026-04-23.json is for visual verification;
will be overwritten by the first real skill run."
```

---

## Task 2: Add warnings banner to frontend

**Files:**
- Modify: `index.html` — add `<div id="warningsBanner">` above the dashboard
- Modify: `style.css` — add `.warnings-banner` class
- Modify: `app.js` — extend `renderDashboard()` to populate the banner

- [ ] **Step 1: Add the banner container to `index.html`**

Replace the `<main>` block (lines 22-46) to include a warnings banner at the top of the dashboard:

```html
    <main>
        <div id="loading" class="loading">Loading...</div>
        <div id="error" class="error" style="display: none;"></div>
        <div id="warningsBanner" class="warnings-banner" style="display: none;"></div>
        <div id="dashboard" class="dashboard" style="display: none;">
            <section class="section">
                <h2 class="section-label done-label">Done</h2>
                <div id="doneItems" class="pill-container"></div>
            </section>

            <section class="section">
                <h2 class="section-label in-progress-label">In Progress</h2>
                <div id="inProgressItems" class="pill-container"></div>
            </section>

            <section class="section">
                <h2 class="section-label up-next-label">Up Next</h2>
                <div id="upNextItems" class="pill-container"></div>
            </section>

            <section class="section">
                <h2 class="section-label slack-label">Slack Attention</h2>
                <div id="slackItems" class="pill-container"></div>
            </section>

            <section class="section">
                <h2 class="section-label slack-work-label">Slack Work (not in Jira/GH)</h2>
                <div id="slackWorkItems" class="pill-container"></div>
            </section>
        </div>
    </main>
```

- [ ] **Step 2: Style the banner in `style.css`**

Append after the `.error { ... }` block (after line 86):

```css
.warnings-banner {
    max-width: 900px;
    margin: 0 auto 20px;
    padding: 12px 16px;
    background-color: rgba(255, 152, 0, 0.1);
    border: 1px solid rgba(255, 152, 0, 0.3);
    border-radius: 6px;
    color: #ff9800;
    font-size: 0.875rem;
}

.warnings-banner ul {
    list-style: none;
    padding: 0;
    margin: 0;
}

.warnings-banner li::before {
    content: '⚠ ';
}
```

- [ ] **Step 3: Populate the banner in `app.js`**

Add to the DOM elements block near the top:

```javascript
const warningsBannerEl = document.getElementById('warningsBanner');
```

Extend `renderDashboard()` to show/hide the banner. After `renderSection(slackWorkItemsEl, ...)` and before the `if (data.generated_at)` block:

```javascript
    if (Array.isArray(data.warnings) && data.warnings.length > 0) {
        const items = data.warnings.map(w => `<li>${w}</li>`).join('');
        warningsBannerEl.innerHTML = `<ul>${items}</ul>`;
        warningsBannerEl.style.display = 'block';
    } else {
        warningsBannerEl.style.display = 'none';
    }
```

- [ ] **Step 4: Seed warnings into the fixture and verify**

Update `data/2026-04-23.json` — add this key immediately after `"generated_at"`:

```json
  "warnings": ["github: MCP not responding (fixture)"],
```

Run:
```bash
cd /Users/tommy.chiu/code/workday-dashboard && python3 -m http.server 8000
```

Open `http://localhost:8000/`. Expected:
- An amber banner appears above the dashboard reading "⚠ github: MCP not responding (fixture)"
- The five sections still render below
- Kill the server with Ctrl-C

- [ ] **Step 5: Remove the warnings entry from the fixture so clean-run visualization is correct**

Edit `data/2026-04-23.json`, remove the `"warnings"` line, and re-verify the browser: banner should be hidden now.

- [ ] **Step 6: Commit**

```bash
git add index.html style.css app.js data/2026-04-23.json
git commit -m "Add warnings banner to dashboard

Shows a non-blocking banner when any data source fails during refresh.
Hidden when data.warnings is empty or absent."
```

---

## Task 3: Scaffold the skill directory and SKILL.md with path + MCP checks

**Files:**
- Create: `~/.claude/skills/refresh-dashboard/SKILL.md`
- Create: `~/.claude/skills/refresh-dashboard/jira.md` (stub)
- Create: `~/.claude/skills/refresh-dashboard/github.md` (stub)
- Create: `~/.claude/skills/refresh-dashboard/slack-attention.md` (stub)
- Create: `~/.claude/skills/refresh-dashboard/slack-work-mining.md` (stub)

- [ ] **Step 1: Create the skill directory**

```bash
mkdir -p ~/.claude/skills/refresh-dashboard
```

Verify:
```bash
ls -la ~/.claude/skills/refresh-dashboard
```
Expected: empty directory.

- [ ] **Step 2: Create SKILL.md with frontmatter + high-level flow (no sub-agent dispatch yet)**

Write `~/.claude/skills/refresh-dashboard/SKILL.md`:

````markdown
---
name: refresh-dashboard
description: Use when the user asks to "refresh the dashboard", "update workday dashboard", "refresh today's work", or similar. Gathers Jira issues, GitHub PRs, and Slack activity via MCP, writes today's JSON snapshot to the workday-dashboard repo, and commits + pushes to publish.
---

# Refresh Workday Dashboard

Populates `data/YYYY-MM-DD.json` in the workday-dashboard repo using live MCP data from Jira, GitHub, and Slack. No API tokens required — uses the user's existing MCP connections.

## Configuration

**Dashboard repo path (EDIT HERE IF IT MOVES):**

```
/Users/tommy.chiu/code/workday-dashboard
```

## Flow

Execute top-to-bottom. If any check fails, print the suggested fix and stop.

### Step 1: Path check

Verify the dashboard repo path above exists and is a git repo:

```bash
test -d /Users/tommy.chiu/code/workday-dashboard/.git && echo OK || echo MISSING
```

If `MISSING`, print:

> The dashboard repo is not at `/Users/tommy.chiu/code/workday-dashboard`. Edit the path in `~/.claude/skills/refresh-dashboard/SKILL.md` under "Configuration" to point to the current location of the repo, then retry.

And stop without doing anything else.

### Step 2: MCP availability check

Three MCPs are required: `jiraconfluencegusto`, `Github-Gusto`, `slackgustoofficialmcp`. Confirm each is loaded and authenticated by calling a no-op probe (e.g. a cheap whoami-style call per server). If any probe fails with an auth error, print:

> MCP `{{server_name}}` is not authenticated. Run the `complete_authentication` tool on that server, then retry.

And stop.

### Step 3: Compute time window

`since_last_workday` = start of the previous workday in local time (skipping weekends), through now. Format as ISO 8601 with timezone for use in queries.

Also compute `today` = current local calendar date in `YYYY-MM-DD` format (this is the output filename).

### Step 4: Gather data (stub for now — fill in during Task 8)

For now, set all four result lists to empty:

```
jira_result = { "done": [], "in_progress": [], "up_next": [] }
github_result = { "done": [], "in_progress": [], "up_next": [] }
slack_attention_result = []
slack_work_result = []
warnings = []
```

### Step 5: Merge (stub — fill in during Task 8)

### Step 6: Dedupe slack_work (stub — fill in during Task 9)

### Step 7: Write JSON (stub — fill in during Task 10)

### Step 8: Prune old files (stub — fill in during Task 10)

### Step 9: Commit + push (stub — fill in during Task 10)
````

- [ ] **Step 3: Create the four ref file stubs**

For each of `jira.md`, `github.md`, `slack-attention.md`, `slack-work-mining.md`, create a stub file like this (example shown for `jira.md`; repeat pattern for the others, swapping names):

```markdown
---
stub: true
---

# Jira data gathering (stub)

Returns `{ "done": [], "in_progress": [], "up_next": [] }`.

Will be filled in during Task 4 of the implementation plan.
```

Use the same pattern for:
- `github.md`: returns `{ "done": [], "in_progress": [], "up_next": [] }`
- `slack-attention.md`: returns `[]`
- `slack-work-mining.md`: returns `[]`

- [ ] **Step 4: Verify the files exist**

```bash
ls -la ~/.claude/skills/refresh-dashboard
```
Expected: 5 files — `SKILL.md`, `jira.md`, `github.md`, `slack-attention.md`, `slack-work-mining.md`.

- [ ] **Step 5: Smoke-test the path + MCP check by invoking the skill**

Open a new Claude session and say: "refresh the dashboard". Expected:
- Skill loads
- Path check passes (repo exists)
- MCP check prompts auth if any server is unauthed, or passes through if all authed
- Skill reports that gathering is a stub and no JSON is written yet — this is expected at this point

No commit needed here — the skill files live outside the repo.

---

## Task 4: Fill in jira.md with MCP-based Jira queries

**Files:**
- Modify: `~/.claude/skills/refresh-dashboard/jira.md`

Reference the current Python logic at `scripts/generate.py:76-198` for the exact query shape. Port to the `jiraconfluencegusto` MCP.

- [ ] **Step 1: Identify the MCP tool for JQL search**

The MCP `jiraconfluencegusto` exposes `searchJiraIssuesUsingJql`. This takes a JQL string and returns matching issues.

Quick check: confirm the tool is available by recalling it exists in the tool list (it's in the available MCP tools).

- [ ] **Step 2: Write `jira.md` with the two queries**

Replace the stub content in `~/.claude/skills/refresh-dashboard/jira.md` with:

````markdown
---
name: jira-source
description: Ref file for the refresh-dashboard skill. Gathers Jira issues for the user from the RETIRE project, categorizing into done / in_progress / up_next.
---

# Jira data gathering

**Inputs:**
- `window_start_iso`: ISO 8601 start of the time window (start of previous workday)

**Output:**
```json
{ "done": [ItemShape], "in_progress": [ItemShape], "up_next": [ItemShape] }
```

Where `ItemShape` is:
```json
{ "source": "jira", "key": "RETIRE-XXXX", "summary": "...", "description": "...", "url": "https://gusto.atlassian.net/browse/RETIRE-XXXX" }
```

## Procedure

### 1. Active + recently done issues

Call `mcp__jiraconfluencegusto__searchJiraIssuesUsingJql` with:

- JQL: `project = RETIRE AND assignee = currentUser() AND status in ("In Progress", "In Review", "Done") ORDER BY updated DESC`
- maxResults: 50
- fields: `summary,description,status,updated`

For each returned issue:

- `key` = issue.key
- `summary` = issue.fields.summary
- `description` = first 200 chars of plaintext extracted from `issue.fields.description` (ADF — see "Flattening ADF" below); empty string if absent
- `url` = `https://gusto.atlassian.net/browse/{{key}}`
- Categorize:
  - If status == "Done" AND issue.fields.updated >= window_start_iso → append to `done`
  - If status in ("In Progress", "In Review") → append to `in_progress`
  - Otherwise skip (e.g. Done items updated before window)

### 2. Backlog items (up next)

Call the same tool with:

- JQL: `project = RETIRE AND assignee = currentUser() AND status in ("To Do", "Backlog", "Open") ORDER BY priority ASC`
- maxResults: 5
- fields: `summary,description`

For each returned issue, build the item shape and append to `up_next`.

### Flattening ADF

Jira returns descriptions in Atlassian Document Format (ADF) — a nested JSON tree. To extract plaintext, walk the tree and concatenate all nodes where `type == "text"`, joined by spaces. Strip leading/trailing whitespace and truncate to 200 chars. If the field is null or empty, return "".

### Error handling

If the MCP call fails (timeout, auth error, 5xx), do NOT silently return empty — return the partial results gathered so far AND a warning string describing the failure (e.g. `"jira: search timed out"`). The orchestrator will append that to the `warnings[]` array in the final output.
````

- [ ] **Step 3: Verify the file**

```bash
grep -c "^### " ~/.claude/skills/refresh-dashboard/jira.md
```
Expected: `4` (H3 headings: 1. Active, 2. Backlog, Flattening ADF, Error handling).

- [ ] **Step 4: No repo commit needed (skill lives outside repo)**

Move to Task 5.

---

## Task 5: Fill in github.md with MCP-based GitHub queries

**Files:**
- Modify: `~/.claude/skills/refresh-dashboard/github.md`

Reference the current Python logic at `scripts/generate.py:220-406`. The `Github-Gusto` MCP exposes GitHub tools; confirm which fit best (it typically has a `get` / `search` family for PRs).

- [ ] **Step 1: Identify GitHub PR search tools on the MCP**

At time of writing, `Github-Gusto` MCP typically exposes `search_issues` or similar that accepts GitHub search qualifiers. If a GraphQL passthrough exists (e.g. `graphql` tool), that also works.

In the skill, prefer REST-style search tools if available for simplicity. Document both paths.

- [ ] **Step 2: Write `github.md`**

Replace the stub content in `~/.claude/skills/refresh-dashboard/github.md` with:

````markdown
---
name: github-source
description: Ref file for the refresh-dashboard skill. Gathers GitHub PRs for the user from Gusto/app, categorizing into done / in_progress / up_next.
---

# GitHub data gathering

**Inputs:**
- `window_start_iso`: ISO 8601 start of the time window

**Constants:**
- `ORG` = "Gusto"
- `REPO` = "app"
- `USERNAME` = "tchiu21"
- `REVIEW_TEAM` = "retirement-compliance"

**Output:**
```json
{ "done": [ItemShape], "in_progress": [ItemShape], "up_next": [ItemShape] }
```

Where `ItemShape` is:
```json
{ "source": "github", "key": "PR #NNNNN", "summary": "...", "description": "...", "url": "https://github.com/Gusto/app/pull/NNNNN" }
```

## Procedure

### 1. PRs authored by the user

Use the `Github-Gusto` MCP's PR search to find PRs in `Gusto/app` authored by `tchiu21`, updated since `window_start_iso`. Either:

- REST-style: `repos/Gusto/app/pulls?state=all&sort=updated&direction=desc&per_page=50`, then client-side filter by `user.login == "tchiu21"` and `updated_at >= window_start_iso`
- Or GraphQL: the PR query from the old Python script (`scripts/generate.py:244-261`) works — translate to the MCP's `graphql` tool if exposed

For each returned PR:
- `key` = `"PR #{{number}}"`
- `summary` = pr.title
- `description` = first 200 chars of `title + " - " + body` (body may be null; treat as "")
- `url` = pr.html_url (REST) or pr.url (GraphQL)
- Categorize:
  - If `state == "closed"` AND `merged_at` is set AND `merged_at >= window_start_iso` → append to `done`
  - If `state == "open"` → append to `in_progress`
  - Otherwise skip (closed-unmerged, or merged outside window)

### 2. PRs awaiting the user's review

Query open PRs in `Gusto/app` with review requested from `tchiu21` OR team `retirement-compliance`. Typical implementation:

- REST: `repos/Gusto/app/pulls?state=open&per_page=50`, then for each PR check `requested_reviewers` (users) and `requested_teams`
- Or GraphQL: the reviewRequests query from `scripts/generate.py:321-346`

For each matching PR, build the item shape and append to `up_next`.

### Error handling

If the MCP call fails, return the partial results so far AND a warning string (e.g. `"github: rate-limited"`). The orchestrator appends it to `warnings[]`.
````

- [ ] **Step 3: Verify the file exists and has content**

```bash
wc -l ~/.claude/skills/refresh-dashboard/github.md
```
Expected: more than 30 lines.

---

## Task 6: Fill in slack-attention.md

**Files:**
- Modify: `~/.claude/skills/refresh-dashboard/slack-attention.md`

Reference the current Python logic at `scripts/generate.py:409-642`. The `slackgustoofficialmcp` typically exposes Slack Web API methods.

- [ ] **Step 1: Identify the Slack MCP tools**

Typical tools on the Slack MCP include `auth_test`, `search_messages`, `conversations_list`, `conversations_history`, `conversations_replies`, `usergroups_list`. Exact names vary but mirror the Slack Web API.

- [ ] **Step 2: Write `slack-attention.md`**

Replace the stub content in `~/.claude/skills/refresh-dashboard/slack-attention.md` with:

````markdown
---
name: slack-attention-source
description: Ref file for the refresh-dashboard skill. Gathers Slack attention items — bot mentions + unanswered @retirement-compliance-devs pings.
---

# Slack attention gathering

**Inputs:**
- `window_start_ts`: Unix timestamp of start of window (used where Slack API takes `oldest`)

**Constants:**
- `CHANNELS` = ["#retirement-compliance-filings-help", "#retirement-compliance", "#retirement-compliance-lobby", "#retirement-apa-support"]
- `DEVS_HANDLE` = "retirement-compliance-devs"

**Output:**
```json
[ { "channel": "...", "summary": "...", "description": "...", "age": "Nh", "url": "..." }, ... ]
```

## Procedure

### 1. Resolve user identity

Call `auth_test` (or equivalent) on the Slack MCP to get the user's Slack user_id. Use this for mention search.

### 2. Mentions of the user in last 24h

Call the Slack `search.messages` tool with:
- query: `<@{{user_id}}>`
- sort: timestamp desc
- count: 20

For each match:
- `channel` = `#{{match.channel.name}}`
- `summary` = `"Mention in #{{match.channel.name}}"`
- `description` = first 200 chars of `match.text`
- `age` = hours since `match.ts` (e.g. `"3h"`)
- `url` = `https://gusto.slack.com/archives/{{match.channel.id}}/p{{match.ts with '.' removed}}`

Append each to the result list.

### 3. Unanswered @retirement-compliance-devs pings in the 4 channels

Resolve channel IDs for `CHANNELS` using `conversations.list` (types: `public_channel,private_channel`, limit: 1000). Match by name.

Resolve the `retirement-compliance-devs` user group via `usergroups.list` (include_users: true). Extract the set of user_ids that are group members.

For each channel ID:
- Call `conversations.history` with `oldest=window_start_ts`, limit 100
- For each message:
  - Skip if message does NOT contain `<!subteam^` or literal `@retirement-compliance-devs`
  - Skip if message age < 2 hours (too recent, give humans a chance)
  - Call `conversations.replies` for that thread. Check whether any reply's `user` is in the group-member set. If none of the replies is from a group member, this is an unanswered ping.
- For unanswered pings, append to the result:
  - `channel` = `#{{channel_name}}`
  - `summary` = `"@devs mention in #{{channel_name}} - no reply"`
  - `description` = first 200 chars of message text
  - `age` = hours since message
  - `url` = standard permalink

### Error handling

Each section (mentions, unanswered pings) is independent. If one fails, record a warning and continue with the other.
````

- [ ] **Step 3: Verify**

```bash
wc -l ~/.claude/skills/refresh-dashboard/slack-attention.md
```
Expected: more than 40 lines.

---

## Task 7: Build slack-work-mining.md

**Files:**
- Modify: `~/.claude/skills/refresh-dashboard/slack-work-mining.md`

This is the new logic — no Python precedent.

- [ ] **Step 1: Write `slack-work-mining.md`**

Replace the stub content with:

````markdown
---
name: slack-work-mining-source
description: Ref file for the refresh-dashboard skill. Mines DMs and threads the user participated in for work they've described but haven't captured in Jira or GitHub.
---

# Slack work-signal mining

**Inputs:**
- `window_start_ts`: Unix timestamp of start of window

**Constants:**
- `CHANNELS` = ["#retirement-compliance-filings-help", "#retirement-compliance", "#retirement-compliance-lobby", "#retirement-apa-support"]

**Output:**
```json
[ { "source": "slack", "context": "...", "summary": "...", "description": "...", "url": "...", "age": "Nh" }, ... ]
```

Dedupe against Jira + GitHub results is handled by the orchestrator in Step 6 of SKILL.md, not here.

## What counts as a work signal

A message **the user sent** that describes work done or in progress. Examples of signals to KEEP:

- "I pushed a fix for X"
- "PR up for Y"
- "I'll take a look at Z"
- "looking into the 5500 thing"
- "Debugged this earlier — the issue is..."
- "Working on adding support for QACA plans"
- Descriptions of investigation, design decisions, or findings the user authored

Examples to EXCLUDE:

- Pure questions asked without describing the user's own work
- Acknowledgments: "thanks", "yep", "lgtm", "sgtm"
- One-word replies
- Messages that are purely scheduling / logistics ("meeting at 3?")

Apply judgment. When uncertain, lean toward keeping — the dashboard is informational, not authoritative.

## Procedure

### 1. Resolve user identity

`auth_test` → user_id.

### 2. Enumerate channels to scan

- The 4 compliance channels (resolve IDs via `conversations.list`, same as slack-attention.md)
- All DMs: `conversations.list` with `types=im`. Filter to DMs where the user has sent at least one message during the window. (Quick heuristic: for each IM, call `conversations.history` with oldest=window_start_ts, limit 10 — if any message has `user == user_id`, include that DM.)

### 3. Gather candidate messages

For each channel/DM ID in scope:
- `conversations.history` with `oldest=window_start_ts`, limit 100
- Keep messages where `user == user_id`
- For each candidate, also fetch `conversations.replies` for the thread (`ts = candidate.ts` or `thread_ts` if candidate is itself a reply) to get surrounding context — needed for meaningful summaries.

### 4. Classify

For each candidate, decide keep/drop using the rules in "What counts as a work signal". Be specific about work described; drop anything purely conversational.

### 5. Summarize

For each kept item, write:
- `summary`: 1 sentence naming what the user did or is doing. Example: `"Debugging 5500 extension filing edge case for Acme Corp"`
- `description`: 1-2 sentences grounded in the thread. Example: `"Thread where you identified a bug in the extension date calculation and said you'd patch it. Not yet in Jira or a PR."`
- `context`:
  - For a DM: `"DM with {{other_user_display_name}}"` (resolve via `users.info` if needed; fall back to user_id if display name unresolvable)
  - For a channel thread: `"#{{channel_name}} thread"`
- `url`: permalink to the user's message
- `age`: hours between the message and now, formatted `"Nh"`
- `source`: always `"slack"`

### 6. Return

Return the list of kept items. Empty list (`[]`) is a valid, normal result.

### Error handling

If `conversations.history` fails for a specific channel, skip that channel and record a warning (e.g. `"slack-work-mining: history failed for #channel-name"`). Continue with remaining channels.
````

- [ ] **Step 2: Verify**

```bash
grep -c "^### " ~/.claude/skills/refresh-dashboard/slack-work-mining.md
```
Expected: `7` (1. Resolve, 2. Enumerate, 3. Gather, 4. Classify, 5. Summarize, 6. Return, Error handling).

---

## Task 8: Wire sub-agent dispatch + JSON merge into SKILL.md

**Files:**
- Modify: `~/.claude/skills/refresh-dashboard/SKILL.md` — replace stub Steps 4 and 5

- [ ] **Step 1: Replace Step 4 in SKILL.md with real parallel dispatch**

In `~/.claude/skills/refresh-dashboard/SKILL.md`, find the block:

```
### Step 4: Gather data (stub for now — fill in during Task 8)

For now, set all four result lists to empty:
...
warnings = []
```

Replace it with:

````markdown
### Step 4: Gather data (parallel sub-agents)

Dispatch FOUR sub-agents in parallel using the `Agent` tool with `subagent_type: general-purpose`. Each sub-agent:
- Runs in isolation (fresh context)
- Has access to all MCP tools (inherited)
- Receives the full content of its ref file + the computed time window as input
- Returns a JSON object matching the contract in its ref file

Dispatch all four in a SINGLE message (multiple `Agent` tool uses in one turn) so they run concurrently.

Agent prompts:

1. **jira-agent:**
   > Read `~/.claude/skills/refresh-dashboard/jira.md`. Follow its Procedure exactly with `window_start_iso = {{window_start_iso}}`. Return only a JSON object of shape `{ "done": [...], "in_progress": [...], "up_next": [...], "warning": null | "..." }`. Under 200 words of commentary outside the JSON.

2. **github-agent:**
   > Read `~/.claude/skills/refresh-dashboard/github.md`. Follow its Procedure exactly with `window_start_iso = {{window_start_iso}}`. Return only a JSON object of shape `{ "done": [...], "in_progress": [...], "up_next": [...], "warning": null | "..." }`. Under 200 words of commentary outside the JSON.

3. **slack-attention-agent:**
   > Read `~/.claude/skills/refresh-dashboard/slack-attention.md`. Follow its Procedure exactly with `window_start_ts = {{window_start_ts}}`. Return only a JSON array of attention items and optionally a `warning` field — wrap in `{ "items": [...], "warning": null | "..." }`. Under 200 words of commentary outside the JSON.

4. **slack-work-mining-agent:**
   > Read `~/.claude/skills/refresh-dashboard/slack-work-mining.md`. Follow its Procedure exactly with `window_start_ts = {{window_start_ts}}`. Return only a JSON array wrapped as `{ "items": [...], "warning": null | "..." }`. Under 200 words of commentary outside the JSON.

Parse each sub-agent's returned JSON object. Populate:

```
jira_result = <from jira-agent>
github_result = <from github-agent>
slack_attention_result = slack_attention_agent.items
slack_work_result = slack_work_mining_agent.items
warnings = [x.warning for x in all four if x.warning is not None]
```
````

- [ ] **Step 2: Replace Step 5 in SKILL.md with the merge**

Find:
```
### Step 5: Merge (stub — fill in during Task 8)
```

Replace with:

````markdown
### Step 5: Merge

Combine into a single result dict (order of items within a list preserved from each sub-agent):

```
result = {
    "date": today,
    "generated_at": <current ISO 8601 timestamp with timezone>,
    "done": jira_result.done + github_result.done,
    "in_progress": jira_result.in_progress + github_result.in_progress,
    "up_next": jira_result.up_next + github_result.up_next,
    "slack_attention": slack_attention_result,
    "slack_work": slack_work_result,
}
```

If `warnings` is non-empty, add `result["warnings"] = warnings`. Otherwise omit the key.
````

- [ ] **Step 3: No commit needed (skill lives outside repo)**

---

## Task 9: Add dedupe step + warnings plumbing

**Files:**
- Modify: `~/.claude/skills/refresh-dashboard/SKILL.md` — replace Step 6 stub

- [ ] **Step 1: Replace Step 6 in SKILL.md with the dedupe logic**

Find:
```
### Step 6: Dedupe slack_work (stub — fill in during Task 9)
```

Replace with:

````markdown
### Step 6: Dedupe slack_work against Jira + GitHub

Build a set of identifiers from the merged Jira + GitHub items:

```
known_refs = set()
for item in result["done"] + result["in_progress"] + result["up_next"]:
    key = item["key"]                       # e.g. "RETIRE-6789" or "PR #60710"
    known_refs.add(key.lower())
    # Also add bare PR number form for robustness:
    if key.startswith("PR #"):
        known_refs.add("pr " + key[4:].lower())    # "pr 60710"
```

For each `slack_work` item, drop it if its `summary` or `description` contains any token in `known_refs` (case-insensitive substring match). This is intentionally conservative — it only drops items that literally reference a ticket/PR already listed.

Replace `result["slack_work"]` with the filtered list. If items were dropped, that's fine — no warning needed (dedupe is expected behavior, not a failure).
````

- [ ] **Step 2: No commit needed**

---

## Task 10: Add write / prune / commit / push to SKILL.md

**Files:**
- Modify: `~/.claude/skills/refresh-dashboard/SKILL.md` — replace Steps 7, 8, 9 stubs

- [ ] **Step 1: Replace Step 7 with the write logic**

Find:
```
### Step 7: Write JSON (stub — fill in during Task 10)
```

Replace with:

````markdown
### Step 7: Write JSON

Pretty-print `result` with 2-space indent, write to `{{REPO_PATH}}/data/{{today}}.json`. Overwrite if present.

```bash
# Pseudocode (execute via appropriate tool):
# write_file "{{REPO_PATH}}/data/{{today}}.json" json.dumps(result, indent=2)
```

Confirm the file exists after write:
```bash
ls -la "{{REPO_PATH}}/data/{{today}}.json"
```
````

- [ ] **Step 2: Replace Step 8 with prune logic**

Find:
```
### Step 8: Prune old files (stub — fill in during Task 10)
```

Replace with:

````markdown
### Step 8: Prune data/ files older than 14 workdays

Compute `cutoff_date` = 14 workdays before today (iterate backwards skipping weekends).

List files in `{{REPO_PATH}}/data/` matching `YYYY-MM-DD.json`. For each, parse the date from the filename. If the parsed date < cutoff_date, delete the file:

```bash
rm "{{REPO_PATH}}/data/{{old_file}}"
```

Log how many files were deleted. If parsing any filename fails, skip that file (don't crash the run).
````

- [ ] **Step 3: Replace Step 9 with commit + push logic**

Find:
```
### Step 9: Commit + push (stub — fill in during Task 10)
```

Replace with:

````markdown
### Step 9: Commit + push

```bash
cd "{{REPO_PATH}}" && git add data/
```

Check if there is anything to commit:
```bash
cd "{{REPO_PATH}}" && git diff --cached --quiet; echo $?
```

If exit code is 0, nothing changed — skip commit and push. Report "No changes to publish" to the user.

Otherwise:
```bash
cd "{{REPO_PATH}}" && git commit -m "Update dashboard {{today}}"
cd "{{REPO_PATH}}" && git push
```

If push fails (non-zero exit), report the failure to the user and mention that the local JSON is still in place — they can rerun, investigate, or push manually.

Final report to user:
- Count of items in each bucket
- Any warnings
- "Pushed to origin — GitHub Pages will deploy shortly." (or the failure message)
````

- [ ] **Step 4: No commit needed (skill lives outside repo)**

---

## Task 11: End-to-end verification

**Files:**
- No files modified in this task — purely verification.

- [ ] **Step 1: Clear the seeded fixture so the real run shows real data**

```bash
rm /Users/tommy.chiu/code/workday-dashboard/data/2026-04-23.json
```

(The skill will recreate it in Step 2.)

- [ ] **Step 2: Invoke the skill in a fresh Claude session**

Open a new Claude session (in this repo or anywhere), type: "refresh the dashboard".

Expected sequence observed:
1. Path check: PASSES (prints OK or equivalent)
2. MCP check: PASSES for all three MCPs (or prompts auth — authenticate if needed, rerun)
3. Time window computed (log or inline mention of `window_start_iso` / `window_start_ts`)
4. Four sub-agents dispatched in parallel (visible as four `Agent` tool calls in one turn)
5. Sub-agents return — main thread logs counts per bucket
6. Dedupe runs — log mentions slack_work count before/after
7. JSON written to `data/2026-04-23.json`
8. Prune runs — log mentions any files deleted
9. Commit + push succeeds — log shows "Pushed to origin"

- [ ] **Step 3: Inspect the produced JSON**

```bash
cat /Users/tommy.chiu/code/workday-dashboard/data/2026-04-23.json | python3 -m json.tool | head -40
```

Verify:
- `date` is today's YYYY-MM-DD
- `generated_at` is a recent ISO 8601 timestamp
- Top-level keys include at least: `date`, `generated_at`, `done`, `in_progress`, `up_next`, `slack_attention`, `slack_work`
- `warnings` may or may not be present; if present, an array of strings
- Items in `done`/`in_progress`/`up_next` have the ItemShape from Task 4/5 (with `source`, `key`, `summary`, `description`, `url`)
- Items in `slack_attention` have `channel`, `summary`, `description`, `age`, `url`
- Items in `slack_work` have `source: "slack"`, `context`, `summary`, `description`, `age`, `url`

- [ ] **Step 4: Verify the dashboard renders the live data**

```bash
cd /Users/tommy.chiu/code/workday-dashboard && python3 -m http.server 8000
```

Open `http://localhost:8000/`. Expected:
- Today's date displayed
- Five sections populated (or showing "No items" if truly empty)
- Slack Work section exists and uses purple pills
- Warnings banner shows if `warnings` is in the JSON, otherwise hidden
- Kill server with Ctrl-C

- [ ] **Step 5: Verify the push actually happened**

```bash
cd /Users/tommy.chiu/code/workday-dashboard && git log --oneline -3
```

Expected: a recent commit "Update dashboard 2026-04-23" (and whatever remote publication the repo uses will follow).

If the skill reported a push failure, investigate — possibly the remote requires rebase or there's a network issue. Fix and rerun.

---

## Task 12: Delete scripts/generate.py, .env.example, .gitignore cleanup

**Files:**
- Delete: `scripts/generate.py`
- Delete: `scripts/` (directory, if empty)
- Delete: `.env.example`
- Modify: `.gitignore` — remove the `.env` line

- [ ] **Step 1: Delete the Python script**

```bash
cd /Users/tommy.chiu/code/workday-dashboard && rm scripts/generate.py
rmdir scripts/ 2>/dev/null || true
```

Verify:
```bash
ls scripts/ 2>/dev/null || echo "scripts removed"
```
Expected: "scripts removed" (or an empty listing).

- [ ] **Step 2: Delete `.env.example`**

```bash
cd /Users/tommy.chiu/code/workday-dashboard && rm .env.example
```

- [ ] **Step 3: Clean up `.gitignore`**

Open `.gitignore` and remove the `.env` line. If the file becomes empty, delete it:

```bash
cd /Users/tommy.chiu/code/workday-dashboard
# After editing:
if [ ! -s .gitignore ]; then rm .gitignore; fi
```

- [ ] **Step 4: Confirm the repo still loads the dashboard**

```bash
cd /Users/tommy.chiu/code/workday-dashboard && python3 -m http.server 8000
```

Open `http://localhost:8000/`. Dashboard should render exactly as in Task 11 Step 4 (the runtime doesn't depend on any of the deleted files). Kill server.

- [ ] **Step 5: Commit**

```bash
cd /Users/tommy.chiu/code/workday-dashboard
git add -A
git status   # verify only deletions + .gitignore staged
git commit -m "Remove Python generator; skill now owns data refresh

Data is now populated by the refresh-dashboard skill (user-level,
~/.claude/skills/refresh-dashboard/) using MCP connections. No API
tokens stored on disk."
git push
```

---

## Done

All spec goals satisfied:
- Token-based Python generator removed (Task 12)
- Skill populates `data/YYYY-MM-DD.json` via MCP (Tasks 3–10)
- New `slack_work` bucket in schema, rendered as a fifth section (Tasks 1, 7)
- Warnings banner for partial failures (Task 2, plumbing in Task 8)
- End-to-end verified (Task 11)
