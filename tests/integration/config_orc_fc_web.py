import dotenv

dotenv.load_dotenv()


# hyperbolic/meta-llama/Llama-3.3-70B-Instruct
# hyperbolic/deepseek-ai/DeepSeek-V3
# hyperbolic/Qwen/Qwen3-235B-A22B
# hyperbolic/Qwen/Qwen2.5-VL-7B-Instruct
# hyperbolic/openai/gpt-oss-120b
# together-ai/deepcogito/cogito-v2-1-671b
# together-ai/ServiceNow-AI/Apriel-1.6-15b-Thinker


# together-ai/deepcogito/cogito-v2-preview-llama-109B-MoE <-- Model not available
# together-ai/deepcogito/cogito-v2-preview-llama-405B <-- model not available
# together-ai/deepcogito/cogito-v2-preview-llama-70B < -- model not available

# together-ai/deepseek-ai/DeepSeek-R1-0528-tput < -- model not available
# together-ai/deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free < -- model not available

# together-ai/google/gemma-2b-it-Ishan <---Input validation error: `inputs` tokens + `max_new_tokens` must be <= 8193

# together-ai/meta-llama/Llama-3-70b-hf < -- Not entities appropved list
# together-ai/meta-llama/Llama-3.1-405B-Instruct < -- Not in approved list
# together-ai/meta-llama/Llama-3.2-1B-Instruct < -- Not in approved list


TEST_PROMPTS = {
    # 1. Paul Graham / Context Extraction
    # Tests ability to read a specific URL and extract granular details.
    "deep_reading": (
        "Go to https://www.paulgraham.com/ds.html and find out exactly what he "
        "says about 'Brian Chesky' and 'air mattresses'."
    ),
    # 2. Technical Documentation / Versioning
    # Tests basic lookup and formatting of technical data.
    "simple_lookup": (
        "Go to https://pypi.org/project/pandas/ and tell me the latest version "
        "number and the exact command to install it."
    ),
    # 3. Structured Data / Tables
    # Tests the agent's ability to parse table data from Wikipedia.
    "markdown_table": (
        "Go to https://en.wikipedia.org/wiki/List_of_highest-grossing_films and "
        "tell me which movie is ranked #1, how much it made worldwide, and what "
        "year it was released."
    ),
    # 4. Horizontal Batching (Parallelism)
    # Tests if the agent can handle multiple URLs in one request (Level 3 requirement).
    "horizontal_batching": (
        "I want to compare the main headline on https://www.cnn.com/ vs "
        "https://www.foxnews.com/. Go to both right now and tell me how their "
        "top stories differ."
    ),
    # 5. Narrative Flow / Scrolling
    # Tests if the agent can read, realize it needs more context, and scroll/read next page.
    "narrative_flow": (
        "Go to https://www.gutenberg.org/cache/epub/11/pg11-images.html (Alice in Wonderland). "
        "Read the beginning of 'CHAPTER I'. Tell me what the White Rabbit takes out "
        "of his waistcoat-pocket and what he says immediately after."
    ),
    # 6. Needle in a Haystack / Internal Search
    # Tests if the agent uses 'search_web_page' when the answer isn't on Page 0.
    "needle_in_haystack": (
        "Go to https://www.ycombinator.com/library and find out exactly what they "
        "recommend regarding 'Cap Tables'. I need the specific advice they give."
    ),
    # 7. Dynamic Content (SPA)
    # Tests handling of sites that might update frequently or look different.
    "dynamic_content": (
        "Go to https://pypi.org/project/langchain/ and tell me the exact version "
        "number of the latest release and the date it was released."
    ),
    # 8. Bot Protection / Error Handling
    # Tests if the agent correctly identifies a 403/Block and reports it without crashing.
    "bot_protection_403": (
        "Go to https://www.reddit.com/r/technology/ and tell me the title of the "
        "top pinned post."
    ),
    # 9. SERP Discovery / No URL Provided
    # Tests the "Discovery" loop: Search -> Select URL -> Read -> Synthesize.
    # The agent must realize it lacks a URL and initiate a search.
    # "serp_discovery": (
    #    "I don't have a link, but I need to know the latest status of the "
    #    "SpaceX Starship program. Search for recent news or the official page "
    #    "and summarize the outcome of the last major test flight."
    # ),
    "serp_discovery": (
        "I don't have a link, but I need to know the latest results of the "
        "olympic women speed skating event. "
    ),
}


config = {
    "together_api_key": "",
    "entities_api_key": "",
    "entities_user_id": "",
    "base_url": "http://localhost:9000",
    "url": "https://api.together.xyz/v1/chat/completions",
    "model": "together-ai/Qwen/Qwen3-Next-80B-A3B-Instruct",
    "provider": "together",
    # "provider": "hyperbolic",
    "assistant_id": "asst_13HyDgBnZxVwh5XexYu74F",
    "test_prompt": TEST_PROMPTS["serp_discovery"],
}
