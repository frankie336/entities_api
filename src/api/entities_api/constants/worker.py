from entities_api.platform_tools.definitions.perform_web_search import \
    perform_web_search
from entities_api.platform_tools.definitions.read_web_page import read_web_page
from entities_api.platform_tools.definitions.scroll_web_page import \
    scroll_web_page
from entities_api.platform_tools.definitions.search_web_page import \
    search_web_page
from src.api.entities_api.platform_tools.definitions.append_scratchpad import \
    append_scratchpad
from src.api.entities_api.platform_tools.definitions.read_scratchpad import \
    read_scratchpad

WORKER_TOOLS = [
    read_web_page,
    scroll_web_page,
    perform_web_search,
    search_web_page,
    append_scratchpad,
    read_scratchpad,
]
