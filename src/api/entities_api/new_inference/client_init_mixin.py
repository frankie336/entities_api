import os

import httpx
from openai import OpenAI
from projectdavid import Entity
from projectdavid_common.utilities.logging_service import LoggingUtility
from together import Together

logging_utility = LoggingUtility()


class ClientInitMixin:
    """Handles initialization of various API clients."""

    def __init__(self, *args, **kwargs):
        # Ensure these attributes always exist on the instance
        self.together_client = None
        self.openai_client = None
        self.project_david_client = None
        # Forward to next initializer in MRO
        super().__init__(*args, **kwargs)

    def init_default_clients(self):
        """Initialize OpenAI, Together, and Project David clients."""
        # Together default client
        try:
            self.together_client = Together(api_key=os.getenv("TOGETHER_API_KEY"))
            logging_utility.debug("Default TogetherAI client initialized.")
        except Exception as e:
            logging_utility.error(
                "Failed to initialize default TogetherAI client: %s", e, exc_info=True
            )
            self.together_client = None

        # OpenAI default client
        try:
            self.openai_client = OpenAI(
                api_key=os.getenv("TOGETHER_API_KEY"),
                base_url=os.getenv("OPENAI_API_URL"),
                timeout=httpx.Timeout(30.0, read=30.0),
            )
            logging_utility.debug("Default OpenAI client initialized.")
        except Exception as e:
            logging_utility.error(
                "Failed to initialize default OpenAI client: %s", e, exc_info=True
            )
            self.openai_client = None

        # Project David default client
        project_key = os.getenv("ADMIN_API_KEY")
        if not project_key:
            logging_utility.error(
                "ADMIN_API_KEY not set; skipping Project David client init."
            )
            self.project_david_client = None
        else:
            try:
                self.project_david_client = Entity(
                    api_key=project_key, base_url=self.base_url
                )
                logging_utility.debug("Default Project David client initialized.")
            except Exception as e:
                logging_utility.error(
                    "Failed to initialize default Project David client: %s",
                    e,
                    exc_info=True,
                )
                self.project_david_client = None


class BaseClient(ClientInitMixin):
    """
    Example subclass that uses ClientInitMixin for client setup,
    then exercises each client in a simple `health_check` method.
    """

    def __init__(self):
        # Explicitly invoke mixin initializer to set default attributes
        ClientInitMixin.__init__(self)
        # Read your service base URL from env (fallback to localhost)
        self.base_url = os.getenv("BASE_URL", "http://localhost:9000")
        # Populate the actual client instances
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
        if self.projectdavid_client is not None:
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
