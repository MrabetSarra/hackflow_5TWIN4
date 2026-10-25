# HackFlow repositories

GitHub stores repository objects and history. Django stores repository identity, team ownership, and collaboration metadata in the configured database. The bare repositories under `REPOS_ROOT` are disposable caches that are fetched from GitHub and rebuilt after a restart. Git must be installed and available on `PATH`.

## Configuration

- `GITHUB_TOKEN`: server-only GitHub credential. Use a GitHub App installation token where practical, or a fine-grained token with repository creation permission and Contents read/write on repositories it manages. Never expose it to templates, JavaScript, or API responses.
- `GITHUB_OWNER`: GitHub user or organization that owns HackFlow repositories. Remote names are generated as `hackflow-<team-id>-<slug>` to avoid team name collisions.
- `GITHUB_PRIVATE_REPOSITORIES`: defaults to `true`; set to `false` only if all HackFlow repositories should be public.
- `HACKFLOW_REPOS_ROOT`: optional local/cache and upload-staging root; defaults to `.repository-data` in the project. On Render, repository history is recovered from GitHub and does not require this path to persist.
- `REPOSITORY_AI_PROVIDER`: `ollama` (default), `openai`, `anthropic`, or a dotted Python class path implementing `complete(prompt)`.
- Ollama defaults: `OLLAMA_BASE_URL=http://127.0.0.1:11434` and `OLLAMA_MODEL=qwen2.5-coder:3b`. Ollama runs locally and needs no API key.
- OpenAI: set `OPENAI_API_KEY`; `OPENAI_MODEL` defaults to `gpt-5-mini`.
- Anthropic: set `ANTHROPIC_API_KEY`; `ANTHROPIC_MODEL` defaults to `claude-haiku-4-5-20251001`.
- Upload limits are configured in `hackflow/settings.py`: total size 50 MB, individual files 10 MB, 500 accepted files, ZIP uncompressed size 100 MB, compression ratio 100, and binary files 2 MB maximum. Django's multipart parser accepts up to 50,000 submitted file parts so ignored folders can be filtered before the application limits are applied.
- Private keys are blocked by default with `REPOSITORY_BLOCK_PRIVATE_KEYS`.

AI suggestions are optional. They use only selected diffs, recent commit messages, or a README excerpt, redact detected secrets, truncate large input, and never commit or merge automatically.

For local development, copy `.env.example` to `.env` in the project root and select a provider there. `.env` is ignored by Git. Restart Django after changing it. Do not commit or share the `.env` file.

### GitHub credential setup

1. Choose the GitHub user or organization that will own all HackFlow remotes. For an organization, confirm the credential owner can create repositories there.
2. In GitHub, open **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**. Select that resource owner and grant **Repository creation / Administration: write** plus **Contents: read and write**. Select repository access broad enough to include repositories created by HackFlow. Organization policy may require an administrator to approve the token.
3. Copy the token once. In Render, open the HackFlow web service's **Environment** settings and add `GITHUB_TOKEN` (secret) and `GITHUB_OWNER` (the exact account or organization name). Optionally set `GITHUB_PRIVATE_REPOSITORIES=true`; this is already the default in `render.yaml`.
4. Save the Render environment and deploy. Create a test repository through HackFlow and verify the corresponding private repository appears under the selected GitHub owner. Do not paste credentials into chat, commit them, or put them in a populated `.env` file.

The integration currently uses a static fine-grained token from the server environment; GitHub App installation-token renewal is not implemented. The token is used only by server-side REST requests and Git transport, never returned to the browser. Missing configuration produces an actionable error instead of falling back to local storage. HackFlow team membership and reviewer rules continue to authorize each operation; all remotes are owned by the configured GitHub account/organization.

## Recover local repository history

Existing Git history can only be recovered where the old bare Git directory still exists. This checkout currently contains three valid bare repositories with real commits under `.repository-data/1` and `.repository-data/2`; the current SQLite database has three repository metadata rows. Render's former `/tmp/.repository-data` may have disappeared during a restart and is separate from this local copy. Metadata by itself cannot recreate commits or branches.

Apply the additive metadata migration first, against the same database that
contains the repository records. It does not change existing ownership or Git
history:

```powershell
python manage.py migrate
```

Then run a read-only inventory:

```powershell
python manage.py migrate_local_repositories --dry-run
```

Then configure GitHub credentials privately and run the import from an environment that can access both the original database and the recovered bare repository directory:

```powershell
python manage.py migrate_local_repositories --source-root .repository-data
```

The command preserves HackFlow primary keys and local Git history, creates one GitHub repository for each recoverable record, and pushes existing branches and tags without force-updating or deleting remote refs. If GitHub rejects a conflicting ref, inspect both histories and resolve it manually before rerunning. Re-running after a partial import retries pushes to the already linked remote. The command does not initialize empty repositories when history is missing and never deletes remote repositories. Back up the database and source directory before importing.

New repositories are created on GitHub first and then populated through real Git operations. Branches, commits, history, file browsing, diffs, and merges are read or written against the fetched Git object graph; successful writes are pushed before HackFlow reports success. A provider refusal or branch protection rejection is shown as a failed operation. Removing a HackFlow record leaves the GitHub repository intact.

Production will not initialize or replace a repository path when local Git data already exists without a GitHub link. It leaves that data untouched and directs the operator to the migration command.

To use local Ollama on Windows, install it from [ollama.com/download/windows](https://ollama.com/download/windows), then run `ollama pull qwen2.5-coder:3b`. Keep Ollama running while using AI suggestions. The local API uses Ollama's `/api/chat` endpoint. To use OpenAI instead, set `REPOSITORY_AI_PROVIDER=openai` and configure an OpenAI API key with API access; a ChatGPT subscription does not provide API credits.

## Commands

Run from the project root:

```powershell
python manage.py migrate
python manage.py seed_repositories
python manage.py seed_ai_demo
python manage.py runserver
python manage.py test repositories student
```

The seed command creates an EcoTrack sample only if that team exists and has no repository. It never overwrites an existing repository.

`seed_ai_demo` adds an `feature/ai-summary-demo` branch to the EcoTrack repository if it does not already exist. Select that branch as the source and `main` as the target in the merge request form to try the AI summary with a sample dashboard and CSV export diff.

## Manual verification

1. Sign in as a student on a team, create a repository, create a feature branch, upload a folder or ZIP, review the diff, and commit it. The default branch must reject a direct push.
2. Open **History**, inspect a commit and colored per-file diff, compare branches, and download a branch or commit ZIP.
3. Create a merge request, assign a reviewer, verify a non-captain author cannot approve their own request, approve it as the reviewer or the captain, then preview and confirm a clean merge. The team captain can always approve, including on a request they opened themselves.
4. Create conflicting edits on two branches, open and approve a merge request, resolve conflicts in the saved session, save and return, and finish the merge. Verify conflict markers are rejected and Abort removes the session.
5. Create a task branch from a task card and verify its branch badge. Select a HackFlow repository and branch on Project Submission and verify the stored commit remains fixed and its ZIP link downloads that commit.
6. Accept a mentor request assignment and visit `/mentor/repositories/`. Confirm the mentor can browse, download, view history and diffs, and comment on files, while Git write actions return 404.
7. With Ollama running and the configured model installed, use an AI button. Alternatively, configure a cloud provider. Verify suggestions can be edited and are never applied automatically. Check that local safety warnings require acknowledgement and private keys are blocked.
