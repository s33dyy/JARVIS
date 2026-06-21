import jarvis_todoist
tasks = jarvis_todoist.get_tasks()
projects = jarvis_todoist.get_projects()
print(f"Tasks: {len(tasks)}")
print(f"Projects: {len(projects)}")
