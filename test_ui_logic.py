import sys
from PyQt6.QtWidgets import QApplication
from datetime import datetime
from jarvis_ui import CommandTab
import jarvis_todoist

app = QApplication(sys.argv)
tab = CommandTab()

# Let's mock a _show_msg and _add_agenda_header so we can trace
tab._show_msg = lambda msg: print("SHOW_MSG:", msg)
tab._add_agenda_header = lambda msg: print("HEADER:", msg)
tab._add_task_row = lambda tid, c, p: print("TASK:", tid, c, p)

events = []
tasks = jarvis_todoist.get_tasks()
projects = jarvis_todoist.get_projects()
now = datetime.now().strftime("%H:%M:%S")

try:
    print("Testing All Tasks mode...")
    tab._apply_results(events, "", tasks, "", projects, now, -2)
    print("All Tasks mode SUCCESS.")
except Exception as e:
    import traceback
    traceback.print_exc()

try:
    print("Testing Chrono mode...")
    tab._apply_results(events, "", tasks, "", projects, now, 0)
    print("Chrono mode SUCCESS.")
except Exception as e:
    import traceback
    traceback.print_exc()

