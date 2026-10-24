# HackFlow repositories

Repositories use real bare Git repositories stored outside `MEDIA_ROOT` and `STATIC_ROOT`. Django stores repository and collaboration metadata only. Git must be installed and available on `PATH`.

## Configuration

- `HACKFLOW_REPOS_ROOT`: private repository storage directory. Defaults to `.repository-data` in the project root.
- `REPOSITORY_AI_PROVIDER`: `ollama` (default), `openai`, `anthropic`, or a dotted Python class path implementing `complete(prompt)`.
- Ollama defaults: `OLLAMA_BASE_URL=http://127.0.0.1:11434` and `OLLAMA_MODEL=qwen2.5-coder:3b`. Ollama runs locally and needs no API key.
- OpenAI: set `OPENAI_API_KEY`; `OPENAI_MODEL` defaults to `gpt-5-mini`.
- Anthropic: set `ANTHROPIC_API_KEY`; `ANTHROPIC_MODEL` defaults to `claude-haiku-4-5-20251001`.
- Upload limits are configured in `hackflow/settings.py`: total size 50 MB, individual files 10 MB, 500 accepted files, ZIP uncompressed size 100 MB, compression ratio 100, and binary files 2 MB maximum. Django's multipart parser accepts up to 50,000 submitted file parts so ignored folders can be filtered before the application limits are applied.
- Private keys are blocked by default with `REPOSITORY_BLOCK_PRIVATE_KEYS`.

AI suggestions are optional. They use only selected diffs, recent commit messages, or a README excerpt, redact detected secrets, truncate large input, and never commit or merge automatically.

For local development, copy `.env.example` to `.env` in the project root and select a provider there. `.env` is ignored by Git. Restart Django after changing it. Do not commit or share the `.env` file.

To use local Ollama on Windows, install it from [ollama.com/download/windows](https://ollama.com/download/windows), then run `ollama pull qwen2.5-coder:3b`. Keep Ollama running while using AI suggestions. The local API uses Ollama's `/api/chat` endpoint. To use OpenAI instead, set `REPOSITORY_AI_PROVIDER=openai` and configure an OpenAI API key with API access; a ChatGPT subscription does not provide API credits.

## Commands

Run from the project root:

```powershell
python manage.py makemigrations repositories student
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
