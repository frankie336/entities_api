import os

import dotenv
from models import HYPERBOLIC_MODELS, TOGETHER_AI_MODELS

dotenv.load_dotenv()

config = {
    "base_url": "http://localhost:9000",
    "entities_api_key": os.getenv("ENTITIES_API_KEY"),
    "together_api_key": os.getenv("TOGETHER_API_KEY"),
    "hyperbolic_api_key": os.getenv("HYPERBOLIC_API_KEY"),
    "entities_user_id": os.getenv("ENTITIES_USER_ID"),
    "report_file_name": "model_compatibility_report.md",
    "models_to_run": TOGETHER_AI_MODELS,
}
