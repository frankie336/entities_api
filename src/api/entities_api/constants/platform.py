

ERROR_NO_CONTENT = (
    "ERROR: The Tool has failed to return any content. The current stage of the workflow is tool submission. "
    "Please inform the user."
)


DIRECT_DATABASE_URL = "mysql+pymysql://ollama:3e4Qv5uo2Cg31zC1@localhost:3307/cosmic_catalyst"
#---------------------------------------------------------------
# Vendors sometimes have clashing model names.
# This can interfere with routing logic
#________________________________________________________________
MODEL_MAP = {"deepseek-ai/deepseek-reasoner": "deepseek-reasoner",
             "deepseek-ai/deepseek-chat": "deepseek-chat",

             "together-ai/deepseek-ai/DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
             "together-ai/deepseek-ai/DeepSeek-V3": "deepseek-ai/DeepSeek-V3",

             "hyperbolic/deepseek-ai/DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
             "hyperbolic/deepseek-ai/DeepSeek-V3": "deepseek-ai/DeepSeek-V3",

             }

