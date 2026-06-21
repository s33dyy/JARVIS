"""
jarvis_ui.py
────────────
JARVIS Desktop Dashboard — PyQt6 edition.
Replaces customtkinter/Tcl/Tk which has fatal SIGSEGV crashes on macOS 26 Tahoe.

3 tabs:
  1. Command Center  — Google Calendar + Todoist tasks + quick actions
  2. Voice Monitor   — Live scrolling transcript from JARVIS voice engine
  3. Settings        — API keys / integration config, saved to .env
"""

from __future__ import annotations

import os
import sys
import queue
import threading
import time
import subprocess
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta

# ── .env loader (before Qt so env vars are set before any module reads them) ──
def get_env_path():
    if getattr(sys, 'frozen', False):
        # PyInstaller app
        home_env = Path.home() / ".jarvis" / ".env"
        if home_env.exists(): return home_env
        return Path(sys.executable).parent.parent.parent / ".env"
    else:
        return Path(__file__).parent / ".env"

ENV_PATH = get_env_path()
if ENV_PATH.exists():
    try:
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass

# ── Thread-safe log queue (background threads write here only) ────────────────
_LOG_QUEUE: queue.Queue = queue.Queue()

class _QueueWriter:
    """Replaces sys.stdout — background threads ONLY put to a queue, zero Qt calls."""
    def write(self, s: str):
        if not isinstance(s, str):
            s = str(s)
        if s:
            _LOG_QUEUE.put(s)
            try:
                if sys.__stdout__:
                    sys.__stdout__.write(s)
                    sys.__stdout__.flush()
            except Exception:
                pass
    def flush(self):
        try:
            if sys.__stdout__:
                sys.__stdout__.flush()
        except Exception:
            pass

# ── PyQt6 imports ─────────────────────────────────────────────────────────────
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QLineEdit, QTextEdit, QScrollArea,
    QFrame, QSplitter, QInputDialog, QSizePolicy, QSpacerItem,
    QCheckBox, QMessageBox, QComboBox,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QObject, QSize, QThread,
)
from PyQt6.QtGui import (
    QFont, QColor, QPalette, QIcon, QTextCursor, QFontDatabase,
)

# ─────────────────────────────────────────────────────────────────────────────
# Dark stylesheet
# ─────────────────────────────────────────────────────────────────────────────
DARK_QSS = """
QMainWindow, QWidget { background-color: #0f0f0f; color: #f1f5f9; }

/* Sidebar */
#sidebar { background-color: #1a1a1a; border-right: 1px solid #2a2a2a; }
#logo    { font-size: 22px; font-weight: bold; color: #4f8ef7; padding: 20px 16px 8px; }

/* Nav buttons */
QPushButton#nav {
    background: transparent; color: #64748b; border: none;
    text-align: left; padding: 10px 16px; font-size: 13px;
    border-radius: 8px; margin: 2px 8px;
}
QPushButton#nav:hover  { background: #242424; color: #f1f5f9; }
QPushButton#nav:checked { background: #4f8ef7; color: white; font-weight: bold; }

/* Tab content area */
QTabWidget::pane { border: none; background: #0f0f0f; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background: #1a1a1a; color: #64748b; padding: 8px 20px;
               border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #4f8ef7; border-bottom: 2px solid #4f8ef7; }
QTabBar::tab:hover    { color: #f1f5f9; }

/* Cards */
#card {
    background: #1a1a1a; border-radius: 12px;
    border: 1px solid #2a2a2a;
}
#row {
    background: #242424; border-radius: 8px;
    border: 1px solid #2e2e2e;
}

/* Buttons */
QPushButton {
    background: #242424; color: #f1f5f9; border: 1px solid #2a2a2a;
    border-radius: 8px; padding: 6px 14px; font-size: 12px;
}
QPushButton:hover { background: #2e2e2e; }
QPushButton#accent  { background: #4f8ef7; color: white; border: none; font-weight: bold; }
QPushButton#accent:hover { background: #3b72e0; }
QPushButton#success { background: #22c55e; color: white; border: none; }
QPushButton#success:hover { background: #16a34a; }
QPushButton#danger  { background: #ef4444; color: white; border: none; }

/* Text log */
QTextEdit#log {
    background: #0d0d0d; color: #a8e6a3; font-family: "JetBrains Mono", "Courier New";
    font-size: 12px; border: none; border-radius: 10px; padding: 8px;
}

/* Line edit / input */
QLineEdit {
    background: #242424; color: #f1f5f9; border: 1px solid #2a2a2a;
    border-radius: 8px; padding: 8px 12px; font-size: 13px;
}
QLineEdit:focus { border: 1px solid #4f8ef7; }

/* Scroll */
QScrollArea  { border: none; background: transparent; }
QScrollBar:vertical {
    background: #1a1a1a; width: 6px; border-radius: 3px;
}
QScrollBar::handle:vertical { background: #2a2a2a; border-radius: 3px; }

/* Labels */
QLabel#h1   { font-size: 20px; font-weight: bold; color: #f1f5f9; }
QLabel#h2   { font-size: 15px; font-weight: bold; color: #f1f5f9; }
QLabel#muted { color: #64748b; font-size: 12px; }
QLabel#accent { color: #4f8ef7; font-size: 11px; font-family: "Courier New"; }
QLabel#success { color: #22c55e; }
QLabel#warning { color: #f59e0b; }
QLabel#danger  { color: #ef4444; }
"""


def _label(text, obj_name="", parent=None):
    lbl = QLabel(text, parent)
    if obj_name:
        lbl.setObjectName(obj_name)
    return lbl


def _btn(text, obj_name="", parent=None, on_click=None):
    b = QPushButton(text, parent)
    if obj_name:
        b.setObjectName(obj_name)
    if on_click:
        b.clicked.connect(on_click)
    return b


def _sep(parent=None):
    line = QFrame(parent)
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #2a2a2a;")
    return line


# ─────────────────────────────────────────────────────────────────────────────
# Command Center tab
# ─────────────────────────────────────────────────────────────────────────────
class CommandTab(QWidget):
    data_loaded_signal = pyqtSignal(list, str, list, str, list, str, int)

    def __init__(self):
        super().__init__()
        self.data_loaded_signal.connect(self._apply_results)
        self._days_offset = -2  # -2 is All Tasks
        self._init_ui()
        # Refresh every 60 seconds
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(60_000)
        # Initial load after 1 second
        QTimer.singleShot(1000, self._refresh)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        hdr.addWidget(_label("Command Center", "h1"))
        hdr.addStretch()
        self._refresh_btn = _btn("↺  Refresh", on_click=self._refresh)
        self._last_lbl = _label("", "muted")
        hdr.addWidget(self._last_lbl)
        hdr.addWidget(self._refresh_btn)
        root.addLayout(hdr)

        # Quick actions
        qa = QHBoxLayout()
        qa.setSpacing(10)
        for label, fn in [
            ("＋ Add Task",   self._quick_add_task),
            ("📅 New Event",  lambda: webbrowser.open("https://calendar.google.com/calendar/r/eventedit")),
            ("✉ Open Gmail", lambda: webbrowser.open("https://mail.google.com")),
            ("📋 Todoist",    lambda: subprocess.Popen(["open", "-a", "Todoist"])),
        ]:
            b = _btn(label, on_click=fn)
            b.setFixedHeight(36)
            qa.addWidget(b)
        qa.addStretch()
        root.addLayout(qa)
        
        # Date Picker (Leadsy-style calendar shortcuts)
        dp = QHBoxLayout()
        dp.setSpacing(8)
        self._date_btns = []
        
        # Add 'All Tasks' special button
        b_all = _btn("All Tasks", on_click=lambda _, x=-2: self._set_date_offset(x))
        b_all.setCheckable(True)
        b_all.setChecked(True)
        b_all.setStyleSheet("background: #4f8ef7; color: white; border: none; font-weight: bold; border-radius: 6px;")
        self._date_btns.append((-2, b_all))
        dp.addWidget(b_all)
        
        for i in range(-1, 6):
            dt = datetime.now() + timedelta(days=i)
            if i == 0:
                lbl = "Today"
            elif i == 1:
                lbl = "Tomorrow"
            else:
                lbl = dt.strftime("%a %d")
            b = _btn(lbl, on_click=lambda _, x=i: self._set_date_offset(x))
            b.setCheckable(True)
            self._date_btns.append((i, b))
            dp.addWidget(b)
        dp.addStretch()
        root.addLayout(dp)

        root.addWidget(_sep())

        # Single Agenda Area (NO addStretch here!)
        self._agenda_area = QVBoxLayout()
        self._agenda_area.setSpacing(8)
        
        scroll_w = QWidget()
        scroll_w.setLayout(self._agenda_area)
        scroll = QScrollArea()
        scroll.setWidget(scroll_w)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent;border:none;")
        root.addWidget(scroll, stretch=1)

    def _set_date_offset(self, offset):
        self._days_offset = offset
        for idx, btn in self._date_btns:
            btn.setChecked(idx == offset)
            if idx == offset:
                btn.setStyleSheet("background: #4f8ef7; color: white; border: none; font-weight: bold; border-radius: 6px;")
            else:
                btn.setStyleSheet("")
        self._refresh()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
                item.layout().deleteLater()
            elif item.spacerItem():
                pass # Python will GC it

    def _add_agenda_header(self, text):
        l = _label(f"  {text}", "h2")
        l.setStyleSheet("color: #4f8ef7; margin-top: 12px; margin-bottom: 4px;")
        self._agenda_area.addWidget(l)

    def _add_event_row(self, time_str, title, location, meet_url=""):
        row = QWidget()
        row.setObjectName("row")
        row.setStyleSheet("background: #2a2d36; border-radius: 8px;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(16, 12, 16, 12)
        t = _label(time_str, "accent")
        t.setFixedWidth(72)
        rl.addWidget(t)
        
        content_lyt = QVBoxLayout()
        content_lyt.setSpacing(2)
        title_lbl = _label(title)
        title_lbl.setStyleSheet("font-weight: 500; font-size: 14px;")
        content_lyt.addWidget(title_lbl)
        if location and not meet_url:
            content_lyt.addWidget(_label(f"📍 {location[:35]}", "muted"))
        rl.addLayout(content_lyt)
        rl.addStretch()
        
        if meet_url:
            b = _btn("Join ↗", "success", on_click=lambda _, u=meet_url: webbrowser.open(u))
            b.setFixedSize(60, 28)
            rl.addWidget(b)
            
        self._agenda_area.addWidget(row)

    def _add_task_row(self, task_id, content, priority):
        colors = {1: "#64748b", 2: "#f59e0b", 3: "#f97316", 4: "#ef4444"}
        row = QWidget()
        row.setObjectName("row")
        row.setStyleSheet("background: #1e1e1e; border-radius: 8px; border: 1px solid #2a2a2a;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 10, 12, 10)
        
        chk = _btn("○", on_click=lambda _, tid=task_id, r=row: self._complete_task(tid, r))
        chk.setFixedSize(28, 28)
        chk.setStyleSheet("background:transparent;border:1px solid #4a4a4a;border-radius:14px;color:#64748b;")
        rl.addWidget(chk)
        
        dot = _label("●")
        dot.setStyleSheet(f"color: {colors.get(priority, '#64748b')}; font-size: 10px;")
        dot.setFixedWidth(16)
        rl.addWidget(dot)
        
        lbl = _label(content)
        lbl.setStyleSheet("font-size: 13px;")
        rl.addWidget(lbl)
        rl.addStretch()
        self._agenda_area.addWidget(row)

    def _complete_task(self, task_id, row):
        row.deleteLater()
        def _do():
            try:
                from jarvis_todoist import close_task
                close_task(task_id)
            except Exception as e:
                print(f"[UI] Error completing task: {e}")
        threading.Thread(target=_do, daemon=True).start()

    def _show_msg(self, msg):
        l = _label(msg, "muted")
        l.setWordWrap(True)
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._agenda_area.addWidget(l)

    def _refresh(self):
        self._refresh_btn.setText("↺  Refreshing…")
        self._refresh_btn.setEnabled(False)
        threading.Thread(target=self._load_data, daemon=True).start()

    def _load_data(self):
        offset = self._days_offset
        # Calendar
        events_result = []
        events_err = ""
        
        if offset != -2:
            try:
                from jarvis_google import get_events, is_connected
                if is_connected():
                    events, err = get_events(offset)
                    if err:
                        events_err = err
                    else:
                        events_result = events
                else:
                    events_err = "Google not connected.\\nConfigure in Settings tab."
            except Exception as e:
                events_err = str(e)

        # Tasks
        tasks_result = []
        tasks_err = ""
        projects_result = []
        try:
            from jarvis_todoist import get_tasks, get_projects, TODOIST_TOKEN
            if TODOIST_TOKEN:
                raw_tasks = get_tasks()
                if offset == -2:
                    tasks_result = raw_tasks
                    projects_result = get_projects()
                else:
                    today = datetime.now().date()
                    target_date = today + timedelta(days=offset)
                    filtered = []
                    for t in raw_tasks:
                        due = t.get("due")
                        if not due:
                            if offset == 0:
                                filtered.append(t)
                            continue
                        due_date_str = due.get("date")
                        if not due_date_str:
                            if offset == 0:
                                filtered.append(t)
                            continue
                        try:
                            task_date = datetime.strptime(due_date_str[:10], "%Y-%m-%d").date()
                        except Exception:
                            if offset == 0:
                                filtered.append(t)
                            continue
                        if offset == 0:
                            if task_date <= today:
                                filtered.append(t)
                        else:
                            if task_date == target_date:
                                filtered.append(t)
                    tasks_result = filtered
            else:
                tasks_err = "Todoist not configured.\\nAdd token in Settings tab."
        except Exception as e:
            tasks_err = str(e)

        now = datetime.now().strftime("%H:%M:%S")

        # Post results back to main thread safely via signal
        self.data_loaded_signal.emit(events_result, events_err, tasks_result, tasks_err, projects_result, now, offset)

    def _apply_results(self, events, events_err, tasks, tasks_err, projects, now, offset):
        self._clear_layout(self._agenda_area)
        
        if events_err or tasks_err:
            if events_err: self._show_msg(f"Google Calendar Error: {events_err}")
            if tasks_err: self._show_msg(f"Todoist Error: {tasks_err}")
            self._agenda_area.addWidget(_sep())

        # If All Tasks mode
        if offset == -2:
            if not tasks:
                self._show_msg("✨  No active tasks in your workspace!")
            else:
                proj_map = {p["id"]: p.get("name", "Unknown Project") for p in projects}
                # Group tasks by project
                from collections import defaultdict
                grouped = defaultdict(list)
                for t in tasks:
                    grouped[t.get("project_id")].append(t)
                
                # Sort project names alphabetically, but put Inbox first if exists
                def proj_sort_key(pid):
                    name = proj_map.get(pid, "")
                    return (0, "") if name.lower() == "inbox" else (1, name)
                    
                sorted_pids = sorted(grouped.keys(), key=proj_sort_key)
                
                for pid in sorted_pids:
                    p_name = proj_map.get(pid, "Unknown Project")
                    self._add_agenda_header(f"🗂️ {p_name}")
                    for t in sorted(grouped[pid], key=lambda x: x.get("child_order", 0)):
                        pri = t.get("priority", 1)
                        self._add_task_row(t["id"], t["content"], pri)
        else:
            # Chronological mode
            timed_items = []
            anytime_items = []
            
            # Parse events
            for ev in events:
                loc = ev.get("location", "")
                meet = loc if loc and ("meet.google" in loc or "zoom.us" in loc) else ""
                t_str = ev["start"]
                
                if t_str == "All Day":
                    anytime_items.append({"type": "event", "time": "All Day", "title": ev["title"], "loc": loc, "meet": meet, "sort_val": 0})
                else:
                    try:
                        dt = datetime.strptime(t_str, "%I:%M %p")
                        val = dt.hour * 60 + dt.minute
                    except:
                        val = 0
                    timed_items.append({"type": "event", "time": t_str, "title": ev["title"], "loc": loc, "meet": meet, "sort_val": val})

            # Parse Tasks
            for t in tasks:
                due = t.get("due") or {}
                dt_str = due.get("datetime")
                pri = t.get("priority", 1)
                
                if dt_str:
                    try:
                        dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ") # UTC
                        val = dt.hour * 60 + dt.minute
                        t_str = dt.strftime("%I:%M %p").lstrip("0")
                        timed_items.append({"type": "task", "time": t_str, "title": t["content"], "id": t["id"], "pri": pri, "sort_val": val})
                    except:
                        anytime_items.append({"type": "task", "time": "", "title": t["content"], "id": t["id"], "pri": pri, "sort_val": 0})
                else:
                    anytime_items.append({"type": "task", "time": "", "title": t["content"], "id": t["id"], "pri": pri, "sort_val": 0})

            timed_items.sort(key=lambda x: x["sort_val"])
            
            if not timed_items and not anytime_items:
                self._show_msg("✨  No events or tasks for this day. You are totally free!")
                
            if timed_items:
                self._add_agenda_header("Timeline")
                for item in timed_items:
                    if item["type"] == "event":
                        self._add_event_row(item["time"], item["title"], item["loc"], item["meet"])
                    else:
                        self._add_task_row(item["id"], f"{item['time']} — {item['title']}", item["pri"])
                        
            if anytime_items:
                self._add_agenda_header("Anytime")
                for item in anytime_items:
                    if item["type"] == "event":
                        self._add_event_row(item["time"], item["title"], item["loc"], item["meet"])
                    else:
                        self._add_task_row(item["id"], item["title"], item["pri"])

        self._agenda_area.addStretch()

        self._last_lbl.setText(f"Updated {now}")
        self._refresh_btn.setText("↺  Refresh")
        self._refresh_btn.setEnabled(True)

    def _quick_add_task(self):
        text, ok = QInputDialog.getText(self, "Add Task", "New task:")
        if ok and text.strip():
            def _do():
                try:
                    from jarvis_todoist import create_task
                    create_task(text.strip())
                    QTimer.singleShot(500, self._refresh)
                except Exception as e:
                    print(f"[UI] Error adding task: {e}")
            threading.Thread(target=_do, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Voice Monitor tab
# ─────────────────────────────────────────────────────────────────────────────
class VoiceTab(QWidget):
    # Qt signal for safe cross-thread log updates
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.log_signal.connect(self._append_log)
        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        hdr.addWidget(_label("Voice Monitor", "h1"))
        hdr.addStretch()
        self.status_lbl = _label("  ● Initializing…", "warning")
        self.status_lbl.setStyleSheet(
            "background:#242424; border-radius:12px; padding:4px 14px; color:#f59e0b; font-size:13px;"
        )
        hdr.addWidget(self.status_lbl)
        clear_btn = _btn("Clear", on_click=self._clear)
        hdr.addWidget(clear_btn)
        root.addLayout(hdr)

        # Log terminal
        self.log = QTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log.setPlainText("  JARVIS Voice Engine initializing…\n\n")
        root.addWidget(self.log, stretch=1)

    def _clear(self):
        self.log.clear()

    def _append_log(self, text: str):
        """Called on the main thread via log_signal."""
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()
        self._update_status(text)

    def _update_status(self, text: str):
        if "Say 'Hey JARVIS'" in text or "Listening" in text:
            self.status_lbl.setText("  ● Listening  ")
            self.status_lbl.setStyleSheet(
                "background:#052e16;border-radius:12px;padding:4px 14px;color:#22c55e;font-size:13px;"
            )
        elif "Wake word detected" in text:
            self.status_lbl.setText("  ● Awake!  ")
            self.status_lbl.setStyleSheet(
                "background:#431407;border-radius:12px;padding:4px 14px;color:#f59e0b;font-size:13px;"
            )
        elif "Thinking" in text:
            self.status_lbl.setText("  ● Thinking  ")
            self.status_lbl.setStyleSheet(
                "background:#1e1b4b;border-radius:12px;padding:4px 14px;color:#818cf8;font-size:13px;"
            )
        elif "Action:" in text or "JARVIS:" in text:
            self.status_lbl.setText("  ● Speaking  ")
            self.status_lbl.setStyleSheet(
                "background:#2e1065;border-radius:12px;padding:4px 14px;color:#a78bfa;font-size:13px;"
            )

    def set_error(self, msg: str):
        self._append_log(f"\n[JARVIS] Engine error: {msg}\n")
        self.status_lbl.setText("  ● Error  ")
        self.status_lbl.setStyleSheet(
            "background:#450a0a;border-radius:12px;padding:4px 14px;color:#ef4444;font-size:13px;"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Logs tab
# ─────────────────────────────────────────────────────────────────────────────
class LogsTab(QWidget):
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.log_signal.connect(self._append_log)
        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        hdr.addWidget(_label("System Logs & Errors", "h1"))
        hdr.addStretch()
        clear_btn = _btn("Clear", on_click=self._clear)
        hdr.addWidget(clear_btn)
        root.addLayout(hdr)

        # Log terminal
        self.log = QTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log.setPlainText("  System Logs Initializing…\n\n")
        root.addWidget(self.log, stretch=1)

    def _clear(self):
        self.log.clear()

    def _append_log(self, text: str):
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()


# ─────────────────────────────────────────────────────────────────────────────
# Settings tab
# ─────────────────────────────────────────────────────────────────────────────
class SettingsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._entries: dict[str, QLineEdit] = {}
        self._crm_cb: QCheckBox | None = None
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(0)
        outer.addWidget(_label("Settings & Integrations", "h1"))
        outer.addSpacing(16)

        # Scrollable content
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(6)
        layout.setContentsMargins(0, 0, 12, 0)

        def section(title, desc):
            layout.addSpacing(16)
            layout.addWidget(_label(title, "h2"))
            lbl = _label(desc, "muted")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
            layout.addWidget(_sep())
            layout.addSpacing(4)

        def field(env_key, label, placeholder="", secret=False):
            row = QWidget()
            row.setObjectName("row")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(16, 12, 16, 12)
            lbl = _label(label)
            lbl.setFixedWidth(220)
            rl.addWidget(lbl)
            entry = QLineEdit()
            entry.setPlaceholderText(placeholder or f"Enter {label}")
            if secret:
                entry.setEchoMode(QLineEdit.EchoMode.Password)
            current = os.environ.get(env_key, "")
            if current:
                entry.setText(current)
            entry.setMinimumWidth(300)
            rl.addWidget(entry)
            if secret:
                toggle = _btn("👁")
                toggle.setFixedSize(36, 36)
                def _tog(checked=False, e=entry):
                    e.setEchoMode(
                        QLineEdit.EchoMode.Normal
                        if e.echoMode() == QLineEdit.EchoMode.Password
                        else QLineEdit.EchoMode.Password
                    )
                toggle.clicked.connect(_tog)
                rl.addWidget(toggle)
            rl.addStretch()
            layout.addWidget(row)
            self._entries[env_key] = entry

        # ── Gemini ──────────────────────────────────────────
        section("🤖  Gemini AI", "Powers JARVIS's language understanding and responses.")
        field("JARVIS_GEMINI_KEY", "Gemini API Key", secret=True)

        # ── Todoist ─────────────────────────────────────────
        section("✅  Todoist", "Personal task and project management.")
        field("JARVIS_TODOIST_TOKEN", "Todoist API Token", secret=True)

        # ── Google ──────────────────────────────────────────
        section("📅  Google (SSO)", "Calendar, Gmail and Drive — connected via OAuth SSO.")
        google_row = QWidget()
        google_row.setObjectName("row")
        grl = QHBoxLayout(google_row)
        grl.setContentsMargins(16, 12, 16, 12)
        grl.addWidget(_label("Google Auth Status", ""))
        grl.addSpacing(16)
        try:
            from jarvis_google import is_connected
            connected = is_connected()
        except Exception:
            connected = False
        status_dot = _label("● Connected" if connected else "● Not Connected",
                            "success" if connected else "danger")
        grl.addWidget(status_dot)
        if not connected:
            connect_btn = _btn("Connect Google →", "accent")
            connect_btn.clicked.connect(lambda: subprocess.Popen(
                ["uv", "run", "python", "-m", "openjarvis.connectors.oauth", "google"]
            ))
            grl.addWidget(connect_btn)
        grl.addStretch()
        layout.addWidget(google_row)

        # ── Obsidian ────────────────────────────────────────
        section("📝  Obsidian Vault", "Path to your Obsidian vault for note/task integration.")
        field("JARVIS_OBSIDIAN_VAULT", "Vault Path", placeholder="~/Documents/Obsidian Vault")

        # ── Auto-CRM ─────────────────────────────────────────
        section("🗂️  Auto-CRM", "Auto-detect contacts and insights from messaging apps.")
        
        chat_db = Path.home() / "Library" / "Messages" / "chat.db"
        try:
            has_fda = chat_db.exists() and os.access(chat_db, os.R_OK)
        except Exception:
            has_fda = False
            
        if not has_fda:
            fda_row = QWidget()
            fda_row.setObjectName("row")
            fda_row.setStyleSheet("background: #450a0a; border: 1px solid #ef4444;")
            frl = QHBoxLayout(fda_row)
            frl.setContentsMargins(16, 12, 16, 12)
            warning = _label("⚠️ iMessage Database inaccessible. Grant 'Full Disk Access' in System Settings.", "danger")
            warning.setWordWrap(True)
            frl.addWidget(warning)
            frl.addStretch()
            fix_btn = _btn("Open Settings", "accent")
            fix_btn.clicked.connect(lambda: subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"]))
            frl.addWidget(fix_btn)
            layout.addWidget(fda_row)

        crm_row = QWidget()
        crm_row.setObjectName("row")
        crl = QHBoxLayout(crm_row)
        crl.setContentsMargins(16, 12, 16, 12)
        crl.addWidget(_label("Enable Auto-CRM"))
        crl.addSpacing(16)
        self._crm_cb = QCheckBox()
        self._crm_cb.setChecked(os.environ.get("JARVIS_AUTO_CRM", "1") == "1")
        crl.addWidget(self._crm_cb)
        crl.addStretch()
        layout.addWidget(crm_row)

        # ── Profile / Use Case ──────────────────────────────
        section("👤  User Profile & Use Case", "Tailor JARVIS's background scanners to your specific needs.")
        profile_row = QWidget()
        profile_row.setObjectName("row")
        prl = QHBoxLayout(profile_row)
        prl.setContentsMargins(16, 12, 16, 12)
        prl.addWidget(_label("Primary Use Case"))
        prl.addSpacing(16)
        self._use_case_cb = QComboBox()
        self._use_case_cb.addItems(["Developer", "Creator", "Manager", "Personal"])
        current_case = os.environ.get("JARVIS_USE_CASE", "Developer")
        self._use_case_cb.setCurrentText(current_case)
        self._use_case_cb.setMinimumWidth(200)
        prl.addWidget(self._use_case_cb)
        prl.addStretch()
        layout.addWidget(profile_row)

        layout.addSpacing(20)
        save_btn = _btn("💾  Save & Apply", "accent", on_click=self._save)
        save_btn.setFixedHeight(44)
        save_btn.setMinimumWidth(200)
        layout.addWidget(save_btn)
        self._save_lbl = _label("", "success")
        layout.addWidget(self._save_lbl)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(scroll_content)
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, stretch=1)

    def _save(self):
        lines = []
        for key, entry in self._entries.items():
            val = entry.text().strip()
            if val:
                os.environ[key] = val
                lines.append(f"{key}={val}")
        crm_val = "1" if self._crm_cb and self._crm_cb.isChecked() else "0"
        os.environ["JARVIS_AUTO_CRM"] = crm_val
        lines.append(f"JARVIS_AUTO_CRM={crm_val}")
        
        use_case_val = self._use_case_cb.currentText()
        os.environ["JARVIS_USE_CASE"] = use_case_val
        lines.append(f"JARVIS_USE_CASE={use_case_val}")
        
        ENV_PATH.write_text("\n".join(lines) + "\n")
        self._save_lbl.setText("✓  Settings saved to .env")
        QTimer.singleShot(3000, lambda: self._save_lbl.setText(""))


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
class JarvisApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JARVIS")
        self.resize(1080, 720)
        self.setMinimumSize(900, 600)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 16)
        sb_layout.setSpacing(0)

        sb_layout.addWidget(_label("⬡ JARVIS", "logo"))

        self._nav_btns: list[QPushButton] = []
        for i, (icon, label) in enumerate([
            ("📋", "Command Center"),
            ("🎙️", "Voice Monitor"),
            ("⚙️", "Settings"),
            ("📝", "System Logs"),
        ]):
            b = QPushButton(f"{icon}  {label}")
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.clicked.connect(lambda _, idx=i: self._switch_tab(idx))
            sb_layout.addWidget(b)
            self._nav_btns.append(b)

        sb_layout.addStretch()
        self._clock_lbl = _label("", "muted")
        self._clock_lbl.setContentsMargins(16, 0, 16, 0)
        sb_layout.addWidget(self._clock_lbl)
        main_layout.addWidget(sidebar)

        # ── Tab area ─────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.tabBar().setVisible(False)
        self._cmd_tab   = CommandTab()
        self._voice_tab = VoiceTab()
        self._set_tab   = SettingsTab()
        self._logs_tab  = LogsTab()
        self._tabs.addTab(self._cmd_tab,   "Command")
        self._tabs.addTab(self._voice_tab, "Voice")
        self._tabs.addTab(self._set_tab,   "Settings")
        self._tabs.addTab(self._logs_tab,  "Logs")
        main_layout.addWidget(self._tabs, stretch=1)

        # Clock timer
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick)
        self._clock_timer.start(1000)
        self._tick()

        # Log queue poll timer (replaces broken Tcl after())
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_log_queue)
        self._poll_timer.start(80)

        # Start JARVIS engine
        self._start_jarvis()

    def _switch_tab(self, idx: int):
        self._tabs.setCurrentIndex(idx)
        for i, b in enumerate(self._nav_btns):
            b.setChecked(i == idx)

    def _tick(self):
        self._clock_lbl.setText(datetime.now().strftime("%H:%M  %d %b %Y"))

    def _poll_log_queue(self):
        """Drain log queue on the main Qt thread. 100% thread-safe, no Tcl/Tk involved."""
        try:
            while True:
                line = _LOG_QUEUE.get_nowait()
                # Emit to logs tab unconditionally
                self._logs_tab.log_signal.emit(line)
                
                # Emit to voice tab only for voice/status messages
                voice_keywords = ["👤", "🤖", "Say 'Hey JARVIS'", "Listening", "Wake word", "Thinking", "JARVIS Voice"]
                if any(k in line for k in voice_keywords):
                    self._voice_tab.log_signal.emit(line)
        except queue.Empty:
            pass

    def _start_jarvis(self):
        try:
            import jarvis_listen
            sys.stdout = _QueueWriter()
            sys.stderr = sys.stdout
            t = threading.Thread(target=jarvis_listen.main, daemon=True, name="jarvis-engine")
            t.start()
        except Exception as e:
            self._voice_tab.set_error(str(e))

    def closeEvent(self, event):
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        event.accept()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    app.setApplicationName("JARVIS")

    # Use system font as fallback
    font = QFont("SF Pro Display", 13)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)

    window = JarvisApp()
    window.show()
    sys.exit(app.exec())
