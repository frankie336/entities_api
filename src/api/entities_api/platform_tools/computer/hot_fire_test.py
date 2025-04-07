from entities_api.platform_tools.computer.shell_command_interface import run_shell_commands

# List of commands to execute on the remote shell.
commands_list = [
    # Identify current user
    # Print working directory
    # List files in detail
    "telnet host.docker.internal 9001"
]

# Execute commands with proper elevation flag.
# The idle_timeout parameter is logged for backward compatibility, but the updated client
# waits for explicit "command_complete" signals.
result = run_shell_commands(
    commands_list,
    thread_id="your_explicit_test_thread_room",
    idle_timeout=3000,  # This value is logged only; explicit completion signals are used.
    elevated=False,
)

print("\nCommand results:")
print(result)
