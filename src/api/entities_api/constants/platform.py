import os

from dotenv import load_dotenv

load_dotenv()
PLATFORM_TOOLS = ["code_interpreter", "web_search", "vector_store_search", "computer"]
TOOLS_ID_MAP = {
    "code_interpreter": "tool_79YkQEz5cDwpJjnR7oJ80D",
    "web_search": "tool_BiIwycpLo1n5Dh6BHN01v8",
    "vector_store_search": "tool_MCaJpXJU3eW6vaMUybEf6i",
    "computer": "tool_PJQ6VcnkmRCMankObjtRcn",
}
SPECIAL_CASE_TOOL_HANDLING = ["computer", "code_interpreter"]
ERROR_NO_CONTENT = "ERROR: The Tool has failed to return any content. The current stage of the workflow is tool submission. Please inform the user."
DIRECT_DATABASE_URL = (
    "mysql+pymysql://ollama:3e4Qv5uo2Cg31zC1@localhost:3307/cosmic_catalyst"
)
MODEL_MAP = {
    "deepseek-ai/deepseek-reasoner": "deepseek-reasoner",
    "deepseek-ai/deepseek-chat": "deepseek-chat",
    "together-ai/deepseek-ai/DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
    "together-ai/deepseek-ai/DeepSeek-V3": "deepseek-ai/DeepSeek-V3",
    "together-ai/meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8": "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
    "together-ai/meta-llama/Llama-4-Scout-17B-16E-Instruct": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    "hyperbolic/deepseek-ai/deepseek-ai/DeepSeek-V3-0324": "deepseek-ai/DeepSeek-V3-0324",
    "hyperbolic/deepseek-ai/DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
    "hyperbolic/deepseek-ai/DeepSeek-V3": "deepseek-ai/DeepSeek-V3",
    "hyperbolic/meta-llama/Llama-3.3-70B-Instruct": "meta-llama/Llama-3.3-70B-Instruct",
    "hyperbolic/meta-llama/Llama-3.2-3B-Instruct": "meta-llama/Llama-3.2-3B-Instruct",
    "hyperbolic/meta-llama/Meta-Llama-3.1-405B-Instruct": "meta-llama/Meta-Llama-3.1-405B-Instruct",
    "hyperbolic/meta-llama/Meta-Llama-3.1-8B-Instruct": "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "hyperbolic/meta-llama/Meta-Llama-3.1-70B-Instruct": "meta-llama/Meta-Llama-3.1-70B-Instruct",
    "hyperbolic/meta-llama/Meta-Llama-3-70B-Instruct": "meta-llama/Meta-Llama-3-70B-Instruct",
}
WEB_SEARCH_BASE_URL = "http://localhost:8080/"
SUPPORTED_MIME_TYPES = {
    ".c": "text/x-c",
    ".cpp": "text/x-c++",
    ".cs": "text/x-csharp",
    ".css": "text/css",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".go": "text/x-golang",
    ".html": "text/html",
    ".java": "text/x-java",
    ".js": "text/javascript",
    ".json": "application/json",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".php": "text/x-php",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".py": "text/x-python",
    ".pyx": "text/x-script.python",
    ".rb": "text/x-ruby",
    ".sh": "application/x-sh",
    ".tex": "text/x-tex",
    ".ts": "application/typescript",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".zip": "application/zip",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".rar": "application/vnd.rar",
    ".7z": "application/x-7z-compressed",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
}


def get_mime_type(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    return SUPPORTED_MIME_TYPES.get(ext.lower())


BROWSER_RENDERABLE_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".html",
    ".htm",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
}
ALLOWED_TEXT_ENCODINGS = ["utf-8", "utf-16", "ascii"]
