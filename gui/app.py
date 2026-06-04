"""
EL Pipeline Desktop GUI
========================
CustomTkinter window that wraps the Docker-based EL pipeline.
Requires Docker Desktop running on the same machine.

Double-click the built .exe (must live next to docker-compose.yml & .env)
and click "Run Pipeline" to:
  1. Bring the stack up (docker compose up -d)
  2. Wait for /healthz to go green
  3. Run the batch worker (docker compose run --rm worker python -m el run)
  4. Show a friendly stage-by-stage progress display
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import requests

try:
    import customtkinter as ctk
except ImportError:
    ctk = None

# ────────────────────────────────────────────────────────────────────────
#  Stage definitions
# ────────────────────────────────────────────────────────────────────────
# Each stage has a friendly label and a list of substrings.  When a
# streamed log line contains any of the substrings, that stage plus all
# earlier stages advance.
_STAGES = [
    ("\U0001f50d  Discovering trends across India", [
        "_fetch_all_sources:", "ai_trend_discovery:", "youtube_trending:",
        "rss_india:", "google_news_india:", "EL pipeline: loaded",
    ]),
    ("\U0001f4ca  Fenix ranking & scoring", [
        "Fenix Rank:",
    ]),
    ("\U0001f9e0  AI scoring trends (Gemini)", [
        "ai_score_trends: enriched",
    ]),
    ("\U0001f3af  Selecting top trends", [
        "Filter Top 30:",
    ]),
    ("\U0001f3ed  Forge — finding suppliers", [
        "supplier_search", "marketplace:",
    ]),
    ("\U0001f6e1\ufe0f  Sentinel — vetting products", [
        "sentinel_vetting:",
    ]),
    ("\U0001f4dd  Building the approval queue", [
        "Phase 4 Candidate Selection:", "stochastic_logger:",
        "Supabase Insert (HIL Reviews)",
    ]),
    ("\U0001f6d2  Sourcing product details", [
        "CJ Get Token:", "CJ Product List:", "embed_candidate_products:",
        "Create Day Tab:", "Prepare Sheet Rows:", "Write Rows to Sheet:",
        "Drive Upload:", "curate_picks:", "Build Search Query:",
        "Write Curated Picks:", "Prepare JSON File:", "Create Curated Picks",
        "Sheet Append (Scraped):", "Bundle JSON (Scraped):",
    ]),
    ("\U0001f4f2  Sending approval cards to Telegram", [
        "Prepare Telegram Card:", "Download Product Image:",
        "Send HIL Telegram Photo:", "Send HIL Telegram Text Fallback:",
        "Mark Telegram Photo Sent:", "Mark Telegram Text Fallback:",
    ]),
    ("\U0001f4e7  Email digest & notifications", [
        "email_digest: sent", "email_product_detail:", "notify_business",
        "record_niche_performance:", "upload_shopify_", "generate_shopify_",
    ]),
    ("\U0001f3c1  Done", [
        "EL pipeline: batch done",
    ]),
]

# Spinner frames (braille dots)
_SPINNER_FRAMES = ["\u28fe", "\u28fd", "\u28fb", "\u28bf", "\u287f", "\u28df", "\u28ef", "\u28f7"]

# Status constants
_PENDING = 0      # gray
_RUNNING = 1      # animated spinner
_DONE = 2         # green checkmark
_FAILED = 3       # red x


# ────────────────────────────────────────────────────────────────────────
#  Runtime / path helpers
# ────────────────────────────────────────────────────────────────────────
def _project_root() -> Path:
    """Return the directory containing docker-compose.yml."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).resolve().parent.parent


def _docker_available() -> tuple[bool, str]:
    """Check whether Docker Desktop is reachable."""
    try:
        r = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return True, r.stdout.strip()
        err = (r.stderr or "").strip()
        return False, err or "docker info returned non-zero"
    except FileNotFoundError:
        return False, "docker command not found on PATH"
    except subprocess.TimeoutExpired:
        return False, "docker info timed out (Docker Desktop may be starting)"
    except OSError as exc:
        return False, str(exc)


def _wait_for_healthz(timeout: float = 90.0) -> tuple[bool, str]:
    """Poll /healthz until it returns {"ok": true}."""
    start = time.monotonic()
    last_err = ""
    while time.monotonic() - start < timeout:
        try:
            r = requests.get("http://localhost:8000/healthz", timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get("ok"):
                    return True, ""
                last_err = f"healthz returned {data!r}"
            else:
                last_err = f"HTTP {r.status_code}"
        except requests.ConnectionError:
            last_err = "connection refused"
        except Exception as exc:
            last_err = str(exc)
        time.sleep(2)
    return False, f"healthz not green after {timeout:.0f}s — last: {last_err}"


# ────────────────────────────────────────────────────────────────────────
#  GUI Application
# ────────────────────────────────────────────────────────────────────────
class ELPipelineApp(ctk.CTk):
    """Desktop GUI for the EL pipeline."""

    def __init__(self) -> None:
        super().__init__()
        self.title("EL Pipeline — One-click Run")
        self.geometry("780x680")
        self.minsize(640, 540)
        self._setup_theme()

        # state
        self._running = False
        self._current_stage = -1          # index of running stage
        self._stage_statuses: list[int] = [_PENDING] * len(_STAGES)
        self._stage_labels: list[ctk.CTkLabel] = []
        self._log_lines: list[str] = []
        self._spinner_after_id: str | None = None
        self._spinner_frame = 0

        # child threads
        self._pipeline_thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None

        self._build_ui()

        # graceful shutdown
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── theme ───────────────────────────────────────────────────────────
    @staticmethod
    def _setup_theme() -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

    # ── UI construction ─────────────────────────────────────────────────
    def _build_ui(self) -> None:
        # outer frame with padding
        outer = ctk.CTkFrame(self)
        outer.pack(fill="both", expand=True, padx=16, pady=16)

        # ── header ──────────────────────────────────────────────────────
        header = ctk.CTkFrame(outer, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            header, text="EL Pipeline",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(side="left")

        self._status_label = ctk.CTkLabel(
            header, text="Ready",
            font=ctk.CTkFont(size=13),
            text_color=("gray60", "gray60"),
        )
        self._status_label.pack(side="right")

        # ── run button ──────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(outer, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(0, 12))

        self._run_btn = ctk.CTkButton(
            btn_frame, text="\u25b6  Run Pipeline",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=42,
            command=self._on_run_click,
        )
        self._run_btn.pack(fill="x")

        # ── progress panel (scrollable checklist) ───────────────────────
        progress_frame = ctk.CTkFrame(outer)
        progress_frame.pack(fill="both", expand=True, pady=(0, 8))

        ctk.CTkLabel(
            progress_frame, text="Progress",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=8, pady=(8, 2))

        canvas = ctk.CTkScrollableFrame(progress_frame, fg_color="transparent")
        canvas.pack(fill="both", expand=True, padx=4, pady=4)

        for label_text, _markers in _STAGES:
            frame = ctk.CTkFrame(canvas, fg_color="transparent")
            frame.pack(fill="x", pady=2)

            lbl = ctk.CTkLabel(
                frame, text=f"  {label_text}",
                font=ctk.CTkFont(size=13),
                anchor="w",
                text_color=("gray50", "gray50"),
            )
            lbl.pack(fill="x", padx=8, pady=2)
            self._stage_labels.append(lbl)

        # ── collapsible technical log ───────────────────────────────────
        self._log_expanded = False
        log_frame = ctk.CTkFrame(outer)
        log_frame.pack(fill="x", pady=(0, 0))

        self._log_toggle = ctk.CTkButton(
            log_frame, text="\u25b8  Show technical log",
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            hover_color=("gray85", "gray25"),
            anchor="w",
            command=self._toggle_log,
            height=28,
        )
        self._log_toggle.pack(fill="x")

        self._log_textbox = ctk.CTkTextbox(
            outer, height=160,
            font=ctk.CTkFont(family="Consolas", size=11),
            state="disabled",
        )
        # hidden by default — shown when _log_expanded toggles

        # ── error/info banner ───────────────────────────────────────────
        self._banner = ctk.CTkLabel(
            outer, text="", font=ctk.CTkFont(size=12),
            fg_color="transparent", corner_radius=6,
        )
        self._banner.pack(fill="x", pady=(6, 0))

    # ── actions ─────────────────────────────────────────────────────────
    def _on_run_click(self) -> None:
        if self._running:
            return
        self._reset_state()
        self._run_btn.configure(state="disabled", text="\u23f3  Starting\u2026")
        self._status_label.configure(text="Starting\u2026")
        self._banner.configure(text="", fg_color="transparent")

        self._pipeline_thread = threading.Thread(
            target=self._run_pipeline_safe, daemon=True,
        )
        self._pipeline_thread.start()

    def _reset_state(self) -> None:
        self._current_stage = -1
        self._stage_statuses = [_PENDING] * len(_STAGES)
        self._log_lines.clear()
        if self._spinner_after_id:
            self.after_cancel(self._spinner_after_id)
            self._spinner_after_id = None
        for i, (label_text, _markers) in enumerate(_STAGES):
            self._stage_labels[i].configure(
                text=f"  {label_text}",
                text_color=("gray50", "gray50"),
            )

    def _toggle_log(self) -> None:
        self._log_expanded = not self._log_expanded
        if self._log_expanded:
            self._log_toggle.configure(text="\u25be  Hide technical log")
            self._log_textbox.pack(fill="x", pady=(4, 0))
        else:
            self._log_toggle.configure(text="\u25b8  Show technical log")
            self._log_textbox.pack_forget()

    # ── main pipeline runner (runs on background thread) ────────────────
    def _run_pipeline_safe(self) -> None:
        """Run pipeline with all errors caught and shown in the log panel."""
        try:
            self._run_pipeline_inner()
        except Exception as exc:
            self._after_ui(lambda: self._show_banner(
                f"Internal error: {exc}", "error"
            ))
            self._append_log_line(f"[GUI ERROR] {exc}")
        finally:
            self._after_ui(self._finish_run)

    def _run_pipeline_inner(self) -> None:
        root = _project_root()

        # 1. Check Docker availability ───────────────────────────────────
        ok, version = _docker_available()
        if not ok:
            self._after_ui(lambda: self._show_banner(
                "Docker Desktop isn't running. "
                "Please open Docker Desktop and try again.",
                "error",
            ))
            self._append_log_line(
                f"[ERROR] Docker not available: {version}"
            )
            return

        self._append_log_line(f"[INFO] Docker {version} detected")
        self._after_ui(lambda: self._status_label.configure(
            text=f"Docker {version} — starting stack\u2026"
        ))

        # 2. docker compose up -d ────────────────────────────────────────
        self._append_log_line("[STEP] docker compose up -d")
        self._after_ui(lambda: self._run_btn.configure(text="\U0001f4e1  Starting stack\u2026"))

        env = os.environ.copy()
        env["EL_ENV_FILE"] = ".env"
        try:
            r = subprocess.run(
                ["docker", "compose", "up", "-d"],
                capture_output=True, text=True, timeout=120,
                env=env, cwd=root,
            )
            self._append_log_line(r.stdout or "")
            if r.stderr:
                self._append_log_line(f"[STDERR] {r.stderr.strip()}")
            if r.returncode != 0:
                self._after_ui(lambda: self._show_banner(
                    "docker compose up failed. See technical log.",
                    "error",
                ))
                return
        except subprocess.TimeoutExpired:
            self._after_ui(lambda: self._show_banner(
                "docker compose up timed out. See technical log.",
                "error",
            ))
            self._append_log_line("[ERROR] docker compose up -d timed out (120s)")
            return

        # 3. Wait for health ─────────────────────────────────────────────
        self._append_log_line("[STEP] Waiting for /healthz \u2026")
        self._after_ui(lambda: self._status_label.configure(
            text="Waiting for API health\u2026"
        ))

        healthy, msg = _wait_for_healthz()
        if not healthy:
            self._append_log_line(f"[ERROR] Health check failed: {msg}")
            self._after_ui(lambda: self._show_banner(
                "The app couldn't start. See technical log.",
                "error",
            ))
            return

        self._append_log_line("[OK] /healthz — green")
        self._after_ui(lambda: self._run_btn.configure(
            text="\u25b6  Run Pipeline"
        ))

        # 4. Run pipeline batch ──────────────────────────────────────────
        self._running = True
        self._after_ui(lambda: self._run_btn.configure(
            state="disabled", text="\u2699\ufe0f  Pipeline running\u2026"
        ))
        self._after_ui(lambda: self._status_label.configure(
            text="Pipeline running\u2026"
        ))
        self._after_ui(self._start_spinner)

        cmd = [
            "docker", "compose", "run", "--rm", "-T",
            "-e", "EL_ENV_FILE=.env",
            "worker", "python", "-m", "el", "run",
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env, cwd=root,
            text=True, bufsize=1,
        )

        # Stream stdout line by line ─────────────────────────────────────
        assert self._proc.stdout is not None
        for raw_line in self._proc.stdout:
            line = raw_line.rstrip("\n\r")
            if not line:
                continue
            self._process_log_line(line)
            self._append_log_line(line)

        exit_code = self._proc.wait()
        self._proc = None

        if exit_code == 0:
            self._after_ui(lambda: self._show_banner(
                "\u2705  Pipeline complete! Check Telegram / Supabase for "
                "final results.",
                "success",
            ))
        else:
            tail = self._log_lines[-20:] if len(self._log_lines) >= 20 else self._log_lines
            tail_text = "\n".join(tail)
            self._after_ui(lambda: self._show_banner(
                "The run hit an error. See technical log for details.",
                "error",
            ))
            self._append_log_line(
                f"\n\u2500\u2500\u2500 LAST {min(20, len(self._log_lines))} LINES \u2500\u2500\u2500\n"
                f"{tail_text}"
            )

    # ── log line \u2192 stage advancement ────────────────────────────────────
    def _process_log_line(self, line: str) -> None:
        """Match the log line to a stage; advance the checklist if needed."""
        for idx, (_label, markers) in enumerate(_STAGES):
            if idx <= self._current_stage:
                continue  # already passed
            for marker in markers:
                if marker in line:
                    # Advance to this stage
                    self._advance_to_stage(idx)
                    return

    def _advance_to_stage(self, idx: int) -> None:
        old = self._current_stage
        for i in range(old + 1, idx + 1):
            if i <= old:
                continue
            if i < idx:
                self._stage_statuses[i] = _DONE
            elif i == idx:
                self._stage_statuses[i] = _RUNNING
                self._current_stage = idx

        # Mark any prior pending ones as done too (catch-up)
        for i in range(0, idx):
            if self._stage_statuses[i] == _PENDING:
                self._stage_statuses[i] = _DONE

        self._refresh_stage_labels()

    def _refresh_stage_labels(self) -> None:
        def _update() -> None:
            for i, (label_text, _markers) in enumerate(_STAGES):
                status = self._stage_statuses[i]
                if status == _DONE:
                    text = f"  \u2705  {label_text.strip()}"
                    color = ("green", "#00cc66")
                elif status == _RUNNING:
                    # The spinner frame is updated separately
                    text = f"  \u23f3  {label_text.strip()}"
                    color = ("#3399ff", "#66b3ff")
                elif status == _FAILED:
                    text = f"  \u274c  {label_text.strip()}"
                    color = ("red", "#ff4444")
                else:
                    text = f"  {label_text.strip()}"
                    color = ("gray50", "gray50")
                self._stage_labels[i].configure(text=text, text_color=color)
        self._after_ui(_update)

    # ── spinner animation ───────────────────────────────────────────────
    def _start_spinner(self) -> None:
        self._spinner_frame = 0
        self._tick_spinner()

    def _tick_spinner(self) -> None:
        if not self._running:
            return
        cur = self._current_stage
        if 0 <= cur < len(_STAGES) and self._stage_statuses[cur] == _RUNNING:
            frame = _SPINNER_FRAMES[self._spinner_frame % len(_SPINNER_FRAMES)]
            label_text = _STAGES[cur][0]
            self._stage_labels[cur].configure(
                text=f"  {frame}  {label_text.strip()}",
                text_color=("#3399ff", "#66b3ff"),
            )
        self._spinner_frame += 1
        self._spinner_after_id = self.after(120, self._tick_spinner)

    # ── helpers ─────────────────────────────────────────────────────────
    def _append_log_line(self, line: str) -> None:
        def _do() -> None:
            self._log_lines.append(line)
            if self._log_textbox.winfo_viewable():
                self._log_textbox.configure(state="normal")
                self._log_textbox.insert("end", line + "\n")
                self._log_textbox.see("end")
                self._log_textbox.configure(state="disabled")
        self._after_ui(_do)

    def _show_banner(self, text: str, kind: str = "info") -> None:
        if kind == "error":
            self._banner.configure(
                text=f"  \u26a0  {text}",
                fg_color=("red", "#cc3333"),
                text_color="white",
            )
            self._status_label.configure(text="Error")
            self._run_btn.configure(state="normal", text="\u25b6  Run Pipeline")
        elif kind == "success":
            self._banner.configure(
                text=f"  \u2705  {text}",
                fg_color=("green", "#2e7d32"),
                text_color="white",
            )
            self._status_label.configure(text="Done")
            self._run_btn.configure(state="normal", text="\u25b6  Run Pipeline Again")
        else:
            self._banner.configure(
                text=text,
                fg_color="transparent",
                text_color=("gray40", "gray60"),
            )

    def _finish_run(self) -> None:
        self._running = False
        self._proc = None
        if self._spinner_after_id:
            self.after_cancel(self._spinner_after_id)
            self._spinner_after_id = None
        # Ensure the "Done" stage is marked
        if self._current_stage < len(_STAGES) - 1:
            # If we didn't get to Done via marker, mark the last known
            for i in range(self._current_stage + 1, len(_STAGES)):
                self._stage_statuses[i] = _DONE if i == len(_STAGES) - 1 else _PENDING
        self._refresh_stage_labels()

    def _after_ui(self, fn: Callable[[], None]) -> None:
        """Schedule *fn* on the main (UI) thread."""
        if threading.current_thread() is threading.main_thread():
            fn()
        else:
            self.after(0, fn)

    # ── window close handler ────────────────────────────────────────────
    def _on_close(self) -> None:
        if self._running and self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self.destroy()


# ────────────────────────────────────────────────────────────────────────
#  Entry point
# ────────────────────────────────────────────────────────────────────────
def main() -> None:
    if ctk is None:
        msg = (
            "CustomTkinter is required but not installed.\n\n"
            "Install it with:\n"
            "  pip install customtkinter\n\n"
            "Then rebuild the .exe with:\n"
            "  pyinstaller --noconfirm --onefile --windowed "
            '--name "EL Pipeline" gui/app.py'
        )
        import tkinter.messagebox as mb
        mb.showerror("Missing Dependency", msg)
        sys.exit(1)

    app = ELPipelineApp()
    app.mainloop()


if __name__ == "__main__":
    main()
