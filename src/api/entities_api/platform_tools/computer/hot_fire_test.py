from entities_api.platform_tools.computer.shell_command_interface import run_shell_commands

# Commands that need sudo but no need to add sudo prefix
commands_list = [
    "whoami",  # No sudo prefix needed
    "nmap -v localhost"  # Test nmap with verbose mode on localhost
]

# Execute commands with proper elevation flag
result = run_shell_commands(
    commands_list,
    thread_id="your_explicit_test_thread_room",
    idle_timeout=3000,  # Increase timeout to give commands more time to complete
    elevated=False
)

print("\nCommand results:")
print(result)
