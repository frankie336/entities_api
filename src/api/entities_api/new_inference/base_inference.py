# orchestrators/base_inference.py  (excerpt)
from entities_api.new_inference.client_cactory_mixin import ClientFactoryMixin


class BaseInference(
        ClientFactoryMixin,
        ServiceRegistryMixin,
        …):
    def __init__(self, *, redis: Redis, assistant_cache: AssistantCache, **kw):
        super().__init__()
        self.redis = redis
        self.assistant_cache = assistant_cache

        # ---- Default external clients built *once* here ----
        self.openai_client = OpenAI(
            api_key=os.getenv("TOGETHER_API_KEY"),
            base_url=os.getenv("BASE_URL"),
            timeout=httpx.Timeout(30, read=30),
        )
        self.together_client = Together(api_key=os.getenv("TOGETHER_API_KEY"))
        self.project_david_client = Entity(
            api_key=os.getenv("ADMIN_API_KEY"),
            base_url=os.getenv("BASE_URL"),
        )
