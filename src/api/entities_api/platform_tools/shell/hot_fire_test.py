from entities_api.platform_tools.shell.shell_commands_service import run_shell_commands

commands_list = [
    "echo 'Hello, explicitly aligned client!'",
    "uname -a",
    "df -h",
    "ping -c 4 google.com"
]


result = run_shell_commands(commands_list, thread_id="your_explicit_test_thread_room")


print(result)