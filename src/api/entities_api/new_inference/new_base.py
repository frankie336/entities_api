import os

import httpx
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.new_inference.base_class import ClientInitMixin

logging_utility = LoggingUtility()


class BaseClient(ClientInitMixin):
    """
    Example subclass that uses ClientInitMixin for client setup,
    then exercises each client in a simple `health_check` method.
    """

    def __init__(self):
        # 0) initialize mixin defaults
        super().__init__()
        # 1) read your URLs/keys from env
        self.base_url = os.getenv("BASE_URL", "http://localhost:9000")
        # 2) now populate the actual client instances
        self.init_default_clients()

    def health_check(self):
        """Attempt a simple call on each client to verify connectivity."""
        # TogetherAI
        if self.together_client is not None:
            try:
                status = self.together_client.health.check()  # hypothetical endpoint
                logging_utility.info(f"TogetherAI health: {status}")
            except Exception as e:
                logging_utility.error("TogetherAI health check failed: %s", e)

        # OpenAI
        if self.openai_client is not None:
            try:
                resp = self.openai_client.models.list()
                logging_utility.info("OpenAI returned %d models", len(resp.data))
            except Exception as e:
                logging_utility.error("OpenAI model list failed: %s", e)

        # Project David
        if self.project_david_client is not None:
            try:
                me = self.project_david_client.users.get_user("me")
                logging_utility.info("Project David user email: %s", me.email)
            except Exception as e:
                logging_utility.error("Project David user lookup failed: %s", e)

        # And demonstrate httpx usage directly
        try:
            timeout = httpx.Timeout(5.0, read=5.0)
            r = httpx.get(f"{self.base_url}/status", timeout=timeout)
            logging_utility.info("Raw HTTP GET /status -> %d", r.status_code)
        except Exception as e:
            logging_utility.error("HTTP GET /status failed: %s", e)


if __name__ == "__main__":
    client = BaseClient()
    client.health_check()
