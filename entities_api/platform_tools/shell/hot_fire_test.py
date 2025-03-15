from entities_api.platform_tools.shell.shell_commands_service import ShellCommandsService

commands = [
    "echo 'Hello from your personal Linux computer'",
    "ls -la",
    "pwd"
]

# Instantiate the service (optionally, you can pass endpoint/default_thread_id to the constructor)
shell_service = ShellCommandsService()

# Pass your desired thread ID as the second argument:
output = shell_service.run_commands(commands, thread_id="thread_cJq1gVLSCpLYI8zzZNRbyc")
print(output)
