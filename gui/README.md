# EL Pipeline Desktop GUI

A Windows desktop application that lets you run the EL pipeline with a single click. It is a **thin wrapper** around Docker — it does **not** reimplement any pipeline logic.

## How it works

1. You click **Run Pipeline**.
2. The app runs `docker compose up -d` (with `EL_ENV_FILE=.env`).
3. It polls `http://localhost:8000/healthz` until the API is ready.
4. It runs `docker compose run --rm worker python -m el run`.
5. A friendly stage checklist advances as the pipeline streams log output.

## Requirements

- **Windows 10 / 11**
- **Docker Desktop** installed and running
- The **project repository** cloned locally (this folder's parent must contain `docker-compose.yml`, `.env`, and the built Docker image)
- The Docker image must be built at least once:
  ```powershell
  cd <project-root>
  docker compose build
  ```

## Quick Start

### 1. Install build dependencies

```powershell
cd <project-root>
.venv\Scripts\pip.exe install customtkinter pyinstaller requests
```

### 2. Build the .exe

```powershell
.\gui\build.ps1
```

This produces `dist\EL Pipeline.exe`.

### 3. Run it

**Copy `dist\EL Pipeline.exe` to the project root** (next to `docker-compose.yml` and `.env`), then double-click it.

> The `.exe` resolves its project root from its own location via `sys.executable.parent`, so it **must** sit in the project root.

## Building Manually (without the script)

```powershell
cd <project-root>
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name "EL Pipeline" gui/app.py
```

Output: `dist\EL Pipeline.exe`

## Usage

1. Ensure Docker Desktop is running.
2. Double-click **EL Pipeline.exe**.
3. Click **\u25b6 Run Pipeline**.
4. Watch the stage checklist advance:

   | Stage | Description |
   |-------|-------------|
   | \U0001f50d | Discovering trends across India |
   | \U0001f4ca | Fenix ranking & scoring |
   | \U0001f9e0 | AI scoring trends (Gemini) |
   | \U0001f3af | Selecting top trends |
   | \U0001f3ed | Forge — finding suppliers |
   | \U0001f6e1\ufe0f | Sentinel — vetting products |
   | \U0001f4dd | Building the approval queue |
   | \U0001f6d2 | Sourcing product details |
   | \U0001f4f2 | Sending approval cards to Telegram |
   | \U0001f4e7 | Email digest & notifications |
   | \U0001f3c1 | Done |

5. Click **\u25b8 Show technical log** to see raw output.
6. When done, check **Telegram** and **Supabase Dashboard** for results.

## Error Handling

| Problem | What you see |
|---------|-------------|
| Docker Desktop not running | Red banner: *Docker Desktop isn't running\u2026* |
| API never starts | Red banner: *The app couldn't start\u2026* + log panel |
| Pipeline exits with error | Red banner + last 20 lines shown in log |
| Any unexpected exception | Caught and routed to the log panel (no crash) |

## File Structure

```
gui/
  app.py        — The GUI application source
  build.ps1     — One-click PowerShell build script
  README.md     — This file
dist/
  EL Pipeline.exe — Built executable (after running build.ps1)
```

## Limitations

- The `.exe` only works on a machine that has Docker Desktop and this project folder present — it is a front-end, not a standalone installer.
- The Docker image must be built beforehand (`docker compose build`).
- Environment variables come from the existing `.env` file — the app reads nothing secret and prints nothing sensitive.
