from new_clients.new_ollama_client import OllamaClient

__all__ = ['OllamaClient']

try:
    from setuptools_scm import get_version
    __version__ = get_version(root='..', relative_to=__file__)
except Exception:
    __version__ = "unknown"