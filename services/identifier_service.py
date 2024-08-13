import random
import string


class IdentifierService:
    @staticmethod
    def generate_id(prefix: str, length: int = 22) -> str:
        """Generate a prefixed ID with a specified length of random alphanumeric characters."""
        characters = string.ascii_letters + string.digits
        random_string = ''.join(random.choice(characters) for _ in range(length))
        return f"{prefix}_{random_string}"

    @staticmethod
    def generate_thread_id() -> str:
        """Generate a thread ID."""
        return IdentifierService.generate_id("thread")

    @staticmethod
    def generate_user_id() -> str:
        """Generate a user ID."""
        return IdentifierService.generate_id("user")

    @staticmethod
    def generate_message_id() -> str:
        """Generate a message ID."""
        return IdentifierService.generate_id("message")

    @staticmethod
    def generate_project_id() -> str:
        """Generate a project ID."""
        return IdentifierService.generate_id("project")

    @staticmethod
    def generate_task_id() -> str:
        """Generate a task ID."""
        return IdentifierService.generate_id("task")

    @staticmethod
    def generate_custom_id(prefix: str) -> str:
        """Generate a custom ID with a given prefix."""
        return IdentifierService.generate_id(prefix)

    @staticmethod
    def generate_assistant_id() -> str:
        """Generate an assistant ID in the specified format."""
        return IdentifierService.generate_id("asst")

    @staticmethod
    def generate_run_id() -> str:
        """Generate an assistant ID in the specified format."""
        return IdentifierService.generate_id("run")


# Example usage:
if __name__ == "__main__":
    print(IdentifierService.generate_thread_id())
    print(IdentifierService.generate_user_id())
    print(IdentifierService.generate_message_id())
    print(IdentifierService.generate_project_id())
    print(IdentifierService.generate_task_id())
    print(IdentifierService.generate_custom_id("custom"))
    print(IdentifierService.generate_assistant_id())
