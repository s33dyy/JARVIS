import jarvis_actions
pending = {}
r1, pending = jarvis_actions.handle_action("add task buy milk", pending)
print("1.", r1, "| pending:", pending)
r2, pending = jarvis_actions.handle_action("yes", pending)
print("2.", r2, "| pending:", pending)
r3, pending = jarvis_actions.handle_action("complete task buy milk", pending)
print("3.", r3, "| pending:", pending)
