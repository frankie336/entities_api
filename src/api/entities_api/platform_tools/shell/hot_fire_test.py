from entities_api.platform_tools.shell.shell_commands_service import run_shell_commands

commands_list = [
    "echo 'Hello, explicitly aligned client!'",
    "uname -a",
    "df -h",
    "traceroute google.com"
]

# Execute with an explicit idle timeout value
result = run_shell_commands(commands_list, thread_id="your_explicit_test_thread_room", idle_timeout=255)

