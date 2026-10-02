# Russian Trainer

A personal, local web app for getting from intermediate to conversational Russian before the trip on 2027-09-30. It combines spaced repetition, feedback on your story translations, grammar drills built from your mistakes, and travel role-play. See [docs/decisions.md](docs/decisions.md) for the setup choices.

## Setup (once)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

### AI: your Claude subscription (default) or an API key

By default the app sends AI requests through Claude Code (`claude -p`), so they count against your Claude plan's usage limits instead of API billing. This is for personal use only. You need the `claude` command installed and logged in:

```powershell
claude        # then type /login, sign in, and /exit
```

To use pay-per-use API billing instead, set your key as a user environment variable and switch the backend under **Settings → AI**:

```powershell
setx ANTHROPIC_API_KEY "sk-ant-..."
```

Open a new terminal afterwards so the variable is picked up. The key is never stored in the project.

## Run

```powershell
.venv\Scripts\app
```

Then open http://127.0.0.1:8000.

Optional environment variables: `RT_DATA_DIR` (database folder, default `data/`), `RT_HOST`, `RT_PORT`.

## Your data and backups

Everything lives in one SQLite file, `data/russian.db`. The app writes a daily backup to `backups/` and keeps the last 14 (added in P1.14).

For a manual backup, stop the app and copy `data/russian.db` somewhere safe, such as cloud storage or an external drive. To restore, stop the app and copy a backup over `data/russian.db`.

## Tests

```powershell
.venv\Scripts\python -m pytest
```
