# Jaza Sentinel

Jaza Sentinel is King Trizzen's local, human-in-the-loop command center. Jaza Soulminder manages the bigger picture: programs, software projects, priorities, goals and tasks, notes, checkpoints, scheduled reviews, and lightweight AI/tool usage records.

Version 0.2 is deliberately an observational intelligence control plane, not an unrestricted autonomous agent. It runs locally, stores readable Jaza state in JSON, reads GuardThisKingdom evidence without modifying it, and makes every Star Reborn handoff explicit without pretending an execution runtime exists.

## Architecture

```text
King Trizzen
     │ direction / approval
     ▼
Jaza Soulminder — prioritize · watch · plan
     │
     ├── Programs and life domains
     ├── Software projects
     ├── Goals, tasks, notes, and check-ins
     ├── Scheduled/review timestamps
     └── Work queue JSON
              │ execution_status: prepared_for_star
              ▼
        Star Reborn boundary (future, not connected)

GuardThisKingdom.App (user 1002, SELECT only)
     │ historical goals + Garden Pro evidence
     ▼
normalized Jaza facts → deterministic statistics → Luna interpretation
     │
     └── facts and AI interpretation remain visibly separate
```

- `jaza_sentinel/` contains the Flask API, validation, dashboard summaries, and atomic JSON repository.
- `jaza_sentinel/integrations/guard_this_kingdom/` contains the isolated connection, SELECT-only repository, and GTK-to-Jaza mapper.
- `jaza_sentinel/reporting/` contains normalized contracts, deterministic classification/statistics, the Jaza-specific Luna provider, report caching, and feedback orchestration.
- `data/defaults/` contains committed seed state for seven programs, four software projects, and the initial Sentinel watch items.
- `data/runtime/` contains ignored, human-owned runtime copies. Missing or malformed runtime documents recover from defaults; malformed files are preserved beside the replacement with a `.corrupt-<timestamp>` suffix.
- `frontend/` contains a standalone Angular dashboard. Its development proxy forwards `/api` to Flask on `127.0.0.1:5001`.
- `legacy_gemini/` preserves the former user-edited Gemini/Star CLI entrypoint. The original tool declarations, calculator sandbox, prompt, and fixtures remain available as a future execution-layer reference, but are not imported by Jaza Sentinel.

Jaza still creates no database of its own. GuardThisKingdom remains an external evidence source; Jaza never duplicates its dataset into JSON. The local app has no authentication, background scheduler, cloud deployment, or autonomous shell loop. Deterministic reporting works without Luna; an OpenAI API key is needed only when the user explicitly generates an insight.

## GuardThisKingdom read-only reporting

The data flow is intentionally ordered:

```text
GTK MSSQL
  -> SELECT-only connection and repository
  -> normalized ActivityFact records
  -> explainable domain classification
  -> deterministic statistics and attention rules
  -> bounded GPT-5.6 Luna structured interpretation
  -> Jaza Command Domain reporting
```

The server owns the private v0.2 target scope as the constant `user_id = 1002`. Angular never sends or selects a GTK user ID. Reads use the verified GTK structures:

- `live_goals`, `dbo.completed_goals`, and `dbo.failed_goals` for goal evidence;
- `dbo.[user]` for timezone;
- `dbo.scorecard_settings.goal_settings` for the configured week start;
- `dbo.gardening_pro` and `dbo.gardening_pro_history` for plants and garden events.

GTK `goalNumber` is the recorded minute value. `goalType` preserves the actual `Spirit`, `Soul`, `Body`, and `Garden` taxonomy. `goalMeasure == "slider"` is a sliding goal; other rows are reported as standard. Standard recurrence is represented by materialized occurrence rows in GTK, not a separate recurrence table or invented Jaza field.

Daily, weekly, monthly, year-to-date, and all-time boundaries follow the inspected GTK dashboard implementation. Counts use `goalStart`; completed minutes are summed only from completed goals and grouped by the real goal type. Daily GTK parity percentage includes live goals in its denominator, while the longer GTK parity windows use completed plus failed outcomes. The existing GTK YTD helper uses the current local midnight as its exclusive end. Its MTD helper likewise passes the month's final calendar date into the shared exclusive-end query, excluding that final day. Jaza v0.2 preserves both compatibility edges rather than silently changing the product's numbers.

### Read-only protections

The integration exposes query methods only. It never imports GTK write services, calls GTK routes, invokes stored procedures, or calls SQLAlchemy `add`, `delete`, or `commit`. Every query includes the server-owned `1002` parameter. Both the connection and repository layers reject statements containing `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `EXEC`, DDL, or permission verbs before SQL reaches the driver. The GTK working tree is inspected before and after verification so unrelated owner changes remain untouched.

SQL Server does not provide a general transaction-level read-only mode equivalent to PostgreSQL's read-only transactions for this `mssql+pymssql` connection. The current GTK credential may therefore remain database-write-capable even though Jaza's code is fail-closed and SELECT-only. For stronger defense in depth, set `JAZA_GTK_DATABASE_URI` to a dedicated SQL login granted SELECT permissions only. Do not describe application-level enforcement as a database permission guarantee.

If GTK is unavailable, the reporting panel shows an unavailable state while all existing JSON programs, projects, work items, notes, checkpoints, Sentinel Watch behavior, and pet-presence controls continue working.

## Luna reporting

Luna is the GPT-5.6 Luna model (`gpt-5.6-luna`) used through the official OpenAI Responses API. Jaza reuses MenuShield's proven generic inference pattern—`responses.parse`, strict Pydantic structured output, `store=false`, bounded timeout, low reasoning, safe errors, and genuine usage telemetry—without importing restaurant/Harvest schemas or prompts.

Python and SQL own all counts, sums, rates, trends, date windows, and attention rules. Luna receives a minimized context containing only normalized facts, deterministic results, transparent attention signals, explicitly labeled Jaza planning state, and a bounded set of ambiguous facts. Luna may categorize those ambiguous facts using constrained domain IDs, but cannot alter GTK or silently change authoritative deterministic statistics. Its response is structurally separated from facts and includes report, prompt, provider, model, timestamp, usage, groundedness, and source-modification metadata.

The first classification rules are explicit and versioned:

- Garden Pro records, `Garden` goals, and clear plant/garden text map to Gardening.
- Workout/exercise signals map to Fitness.
- Meal, hydration, food, and nutrition signals map to Nutrition.
- Software, coding, debugging, API, database, and known project signals map to Coding Projects.
- Budget/expense/bill signals map to Budgeting; investment/retirement/finance signals map to Financial Planning.
- Ambiguous Spirit, Soul, or Body rows are not forced into an unrelated domain. They remain unclassified for Luna or human review.

Insights are generated only by `POST /api/reporting/domains/<domain>/insight`. Angular never calls Luna merely because it rendered. A valid insight is cached in process for `JAZA_REPORT_CACHE_TTL_SECONDS` (one hour by default); explicit Refresh bypasses the cache. Useful and Needs Adjustment feedback is stored in Jaza's existing `sentinel.json` as versioned local evaluation data. Feedback never writes to GTK and never modifies prompts or source code automatically.

## Local environment

Copy `.env.example` to the ignored `.env` only when configuring a new checkout. Never commit real credentials. Supported reporting variables are:

- `JAZA_GTK_ENV_FILE`: optional path to GTK's existing local `.env`; Jaza reads only `params` or `SQLALCHEMY_DATABASE_URI` from it.
- `JAZA_GTK_DATABASE_URI`: optional direct URI, preferably for a dedicated SELECT-only SQL login.
- `JAZA_SHARED_OPENAI_ENV_FILE`: optional path to MenuShield's local `.env`; Jaza reads only `OPENAI_API_KEY` and `OPENAI_MODEL`. This reuses the same key without copying it.
- `OPENAI_API_KEY`: process-level alternative to the shared-file pointer.
- `JAZA_LUNA_MODEL`: defaults to `gpt-5.6-luna`.
- `JAZA_LUNA_REASONING_EFFORT`: `none`, `low`, `medium`, or `high`; defaults to `low`.
- `JAZA_LUNA_TIMEOUT_SECONDS`: defaults to `90`.
- `JAZA_REPORT_CACHE_TTL_SECONDS`: defaults to `3600`.

The current local ignored `.env` contains only pointers to the existing GTK and MenuShield environment files plus non-secret model/cache settings. It contains no copied key or database URI.

## Run the backend

From the repository root:

```bash
uv sync --dev
uv run python main.py
```

The local API starts at `http://127.0.0.1:5001`. Verify readiness with:

```bash
curl http://127.0.0.1:5001/api/health
```

The existing local shortcut is also supported:

```bash
python app.py
```

Optional overrides are `JAZA_HOST`, `JAZA_PORT`, `PORT`, or the CLI flags shown by `uv run python main.py --help`. A separate runtime location can be tested safely with `--data-dir /path/to/runtime`.

Useful reporting endpoints are:

- `GET /api/reporting/overview`
- `GET /api/reporting/domains/<domain>?window=week`
- `POST /api/reporting/domains/<domain>/insight` with `{"window":"week","refresh":false}`
- `POST /api/reporting/feedback`

There is intentionally no route parameter for a GTK user ID.

## Run the Angular frontend

Angular 21 is used because it is supported and works with the local Homebrew Node 20 runtime. From `frontend/`:

```bash
PATH="/opt/homebrew/opt/node@20/bin:$PATH" npm install
PATH="/opt/homebrew/opt/node@20/bin:$PATH" npm start -- --port 4201
```

Open `http://localhost:4201`. Keep the Flask backend running in the other terminal.

If your terminal is already at the repository root, use the root wrappers instead—there is no need to change directories:

```bash
PATH="/opt/homebrew/opt/node@20/bin:$PATH" npm run frontend:install
PATH="/opt/homebrew/opt/node@20/bin:$PATH" npm --prefix frontend start -- --port 4201
```

The root package provides frontend wrappers; the explicit start command above passes port `4201` to the frontend's local Angular CLI. An `ENOENT` for `/agentic-ai-agent/package.json` means the checkout predates these wrappers; in that case, `cd frontend` before running npm or update the checkout.

## Summon Jaza

First-time setup, if dependencies have not been installed yet:

```bash
uv sync --dev
cd frontend
npm install
```

For normal daily startup from the repository:

```bash
cd ~/paladin/agentic-ai-agent
./summon_jaza.sh
```

Or summon Jaza from any working directory:

```bash
~/paladin/agentic-ai-agent/summon_jaza.sh
```

The launcher starts the backend at `http://127.0.0.1:5001`, starts the frontend at `http://localhost:4201`, waits for both to become responsive, and opens the frontend in the default browser. Press `Ctrl+C` in the launcher terminal to stop both services. PyCharm does not need to be open.

## Verify

Backend:

```bash
uv run pytest
```

Frontend:

```bash
cd frontend
PATH="/opt/homebrew/opt/node@20/bin:$PATH" npm run build
PATH="/opt/homebrew/opt/node@20/bin:$PATH" npm test
```

## Current capabilities

- Dashboard metrics for Needs My Attention, Active, Ready, Waiting, and Completed Today.
- Seven management programs: Daily Command, Coding Command, Fitness, Nutrition, Gardening, Financial, and Budget.
- Four seeded projects: GuardThisKingdom.App, SafeBite / Allergy Tracker, Agentic AI Agent / Jaza Sentinel, and AutoMatrix.
- Quick creation and editing of goals/tasks with small status and priority sets.
- Human checkpoint states: none, requested, and awaiting direction.
- Notes and check-ins attached to a program or project.
- Optional `scheduled_for` and `review_after` ISO timestamps surfaced on the dashboard.
- Manual provider/tool, token estimate, cost estimate, and usage notes.
- Explicit King Trizzen, Jaza, and Star Reborn assignees. Selecting Star records `prepared_for_star`; it never records execution.
- A global **Hand to Star / Recall Jaza** presence control that switches only Codex Desktop's allowlisted `desktop.selected-avatar-id` between `custom:star-reborn` and `custom:jaza-soulminder`.
- Safe, pretty-printed UTF-8 JSON writes using a same-directory temporary file and atomic replace.
- Read-only GTK status and deterministic reporting inside every Command Domain.
- On-demand, structured Luna insights with facts/interpretation separation, cache control, provenance, and feedback.
- Combined Coding Projects reports that label Jaza JSON as planning state and GTK as historical/activity evidence.

## Codex pet presence

The two presence buttons in the dashboard header are deliberately independent from the work queue:

- **Hand to Star** selects `custom:star-reborn` as the visible Codex pet.
- **Recall Jaza** selects `custom:jaza-soulminder` as the visible Codex pet.
- Switching presence does not launch, stop, reassign, or update a task. Recalling Jaza while a Codex task is running leaves that work undisturbed.

The backend parses `~/.codex/config.toml`, accepts only those two pet identities, replaces only `[desktop].selected-avatar-id`, validates the resulting TOML, preserves the file mode, and saves with an atomic same-directory replace. It never returns or logs the rest of the Codex configuration. For isolated testing, set `JAZA_CODEX_CONFIG_PATH` or use `python main.py --codex-config /path/to/config.toml`.

## Local data safety

Committed seeds live in `data/defaults/*.json`. On first start, Jaza copies them into `data/runtime/*.json`; only the runtime copies change through the API. Runtime state is intentionally ignored by Git while the defaults remain reviewable and reproducible.

Never place API keys, credentials, financial account data, or other secrets in Sentinel JSON. Financial and budget domains are planning surfaces only; there are no financial integrations.

## Intentional v0.2 limits

- No autonomous scheduling daemon. Timestamps are stored and surfaced only.
- No worker process, shell control, background coding loop, or result-ingestion contract.
- No automatic Codex/provider telemetry. Usage entries are manual.
- No multi-user support or authentication; the application binds to localhost by default.
- No database or migration path; JSON is the intentional local persistence contract.
- No database-level read-only guarantee unless the configured GTK credential is itself SELECT-only.
- No automatic import of GTK rows into Jaza work items and no automatic creation of attention work.
- No continuous model polling, autonomous tool calls, self-modifying prompts, or self-modifying code.
- Luna-assisted classifications are returned with the insight for review; v0.2 does not persist them as source truth or retroactively rewrite deterministic statistics.
- Garden reporting reads user-owned plants/history and Garden goals; it deliberately omits location, media, and Garden AI profile data from Luna context.

## Extending the reporting core

A future evidence source should implement a narrow read interface, map external rows into `ActivityFact`, and register its provenance without leaking its ORM objects into reporting. A future Jaza tool should be a separate capability with explicit inputs, authorization, side-effect declaration, and result evidence; it should not be added to the GTK repository or Luna report prompt. This keeps observation, reasoning, management, and eventual Star execution as distinct responsibilities.

## Future Star Reborn delegation layer

The future boundary is narrow by design:

1. Jaza prioritizes and prepares a validated work item.
2. King Trizzen grants any required direction or approval.
3. A future adapter accepts only items with `execution_assignee: "star_reborn"` and `execution_status: "prepared_for_star"`.
4. Star executes through an explicitly bounded runtime and returns a structured result report.
5. Jaza reviews the evidence and updates big-picture state.

Until that adapter and its approval/result contracts are implemented and verified, **Prepared for Star means queued intent only**.

## Legacy Gemini prototype

The previous root application was a Gemini-based coding CLI tied to the `calculator/` sandbox. Its active user changes were preserved in `legacy_gemini/main.py`, while its helper files remain where the original imports expect them. It is not installed in the normal Sentinel dependency set. To study it separately:

```bash
uv run --extra legacy-gemini python -m legacy_gemini.main "your prompt"
```

That command is legacy-only, requires a separately configured `GEMINI_API_KEY`, and is not a Star delegation mechanism.
