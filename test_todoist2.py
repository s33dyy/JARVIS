import jarvis_todoist
tasks = jarvis_todoist.get_tasks()
print(f"URL: {jarvis_todoist.BASE_URL}/tasks")
print(f"Token: {jarvis_todoist.TODOIST_TOKEN}")
print(f"Tasks: {len(tasks)}")
