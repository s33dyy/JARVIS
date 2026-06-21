import re

with open("jarvis_ui.py", "r") as f:
    content = f.read()

new_class = """class CommandTab(QWidget):
    def __init__(self):
        super().__init__()
        self._days_offset = 0  # 0 is today, -2 is All Tasks
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
            if i == 0:
                b.setChecked(True)
                b.setStyleSheet("background: #4f8ef7; color: white; border: none; font-weight: bold; border-radius: 6px;")
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
                if offset == -2:
                    tasks_result = get_tasks()
                    projects_result = get_projects()
                elif offset == 0:
                    t_filter = "today | overdue"
                    tasks_result = get_tasks(filter_query=t_filter)
                elif offset == 1:
                    t_filter = "tomorrow"
                    tasks_result = get_tasks(filter_query=t_filter)
                else:
                    t_filter = (datetime.now() + timedelta(days=offset)).strftime("%b %d")
                    tasks_result = get_tasks(filter_query=t_filter)
            else:
                tasks_err = "Todoist not configured.\\nAdd token in Settings tab."
        except Exception as e:
            tasks_err = str(e)

        now = datetime.now().strftime("%H:%M:%S")

        # Post results back to main thread
        QTimer.singleShot(0, lambda: self._apply_results(events_result, events_err, tasks_result, tasks_err, projects_result, now, offset))

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
            threading.Thread(target=_do, daemon=True).start()"""

pattern = re.compile(r"class CommandTab\(QWidget\):.*?# ─────────────────────────────────────────────────────────────────────────────\n# Voice Monitor tab", re.DOTALL)
content = pattern.sub(new_class + "\n\n\n# ─────────────────────────────────────────────────────────────────────────────\n# Voice Monitor tab", content)

with open("jarvis_ui.py", "w") as f:
    f.write(content)
