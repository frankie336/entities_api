from entities_api.platform_tools.computer.shell_command_interface import run_shell_commands

# List of commands to execute on the remote shell.
commands_list = [
    "whoami",              # Identify current user
    "pwd",                 # Print working directory
    "ls -la",              # List files in detail
    "nmap -v localhost"    # Perform an nmap scan on localhost with verbose output
]

# Execute commands with proper elevation flag.
# The idle_timeout parameter is logged for backward compatibility, but the updated client
# waits for explicit "command_complete" signals.
result = run_shell_commands(
    commands_list,
    thread_id="your_explicit_test_thread_room",
    idle_timeout=3000,  # This value is logged only; explicit completion signals are used.
    elevated=False
)

print("\nCommand results:")
print(result)
