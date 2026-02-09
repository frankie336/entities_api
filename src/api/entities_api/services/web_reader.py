import logging
import os
import re
from typing import List

import html2text
from playwright.async_api import async_playwright

# Import your cache class
from src.api.entities_api.cache.web_cache import WebSessionCache

logger = logging.getLogger("UniversalWebReader")


class UniversalWebReader:
    """
    The 'Eyes' of the agent.

    ARCHITECTURE CHANGE:
    This service no longer executes local 'curl' or 'requests'.
    It strictly offloads all fetching to the 'browserless/chromium' container
    via WebSocket (CDP). This keeps the API container secure and lightweight.
    """

    def __init__(self, cache_service: WebSessionCache):
        self.cache = cache_service

        # HTML to Markdown Configuration
        self.converter = html2text.HTML2Text()
        self.converter.ignore_links = False
        self.converter.ignore_images = True
        self.converter.ignore_tables = False
        self.converter.body_width = 0

        # Config
        self.CHUNK_SIZE = 4000
        # This matches your docker-compose environment variable
        self.browser_ws = os.getenv("BROWSER_WS_ENDPOINT", "ws://browser:3000")

        self.garbage_triggers = [
            "enable javascript",
            "please wait",
            "loading...",
            "javascript is required",
            "checking your browser",
            "turn on js",
        ]

    async def read(self, url: str, force_refresh: bool = False) -> str:
        """
        Action: Scrape a URL.
        1. Checks Redis.
        2. If missing, offloads fetch to 'browser' container.
        3. Returns Page 0.
        """
        # 1. Check Cache
        if not force_refresh:
            cached_session = await self.cache.get_session(url)
            if cached_session:
                logger.info(f"⚡ Cache Hit for {url}")
                return await self.cache.get_page_view(url, 0)

        # 2. Fetch Content (Strictly Remote)
        logger.info(f"🌐 Offloading fetch to Browser Service: {url}")
        content = await self._fetch_via_browserless(url)

        # 3. Process & Chunk
        clean_text = content.strip()
        if not clean_text or len(clean_text) < 50:
            # Fallback check for empty responses
            return "❌ Error: The browser service returned no content. The site might be blocking headless access."

        chunks = self._chunk_text(clean_text)

        # 4. Save to Redis
        await self.cache.save_session(
            url=url, full_text=clean_text, chunks=chunks, source="Remote Browserless"
        )

        # 5. Return Page 0
        return await self.cache.get_page_view(url, 0)

    async def scroll(self, url: str, page: int) -> str:
        return await self.cache.get_page_view(url, page)

    async def search(self, url: str, query: str) -> str:
        logger.info(f"🔍 Searching {url} for query: '{query}'")
        return await self.cache.search_session(url, query)

    # --- INTERNAL HELPERS ---

    def _chunk_text(self, text: str) -> List[str]:
        return [
            text[i : i + self.CHUNK_SIZE] for i in range(0, len(text), self.CHUNK_SIZE)
        ]

    async def perform_serp_search(self, query: str) -> str:
        """
        Action: Search the Web (DuckDuckGo).
        Returns a numbered list of results with URLs for the Agent to select from.
        """
        # We use the HTML-only version of DDG which is lighter and easier to parse
        search_url = f"https://html.duckduckgo.com/html/?q={query}"

        logger.info(f"🔎 Performing SERP Search: {query}")

        # Reuse your existing browser infrastructure!
        raw_markdown = await self.read(search_url, force_refresh=True)

        # --- PARSE THE MARKDOWN TO CLEAN LIST ---
        # The raw markdown from html2text will be messy. We need to extract the relevant links.
        # This is a heuristic parser for DDG HTML results.

        lines = raw_markdown.split("\n")
        results = []
        count = 0

        # Simple parser logic: look for links that look like external results
        # Note: This is brittle. For production, use an API like Serper.dev or Bing API.
        for i, line in enumerate(lines):
            if count >= 5:
                break  # Top 5 results

            # DDG HTML results usually look like: [Title](url) \n Snippet
            # We filter out internal DDG links
            if "](" in line and "duckduckgo.com" not in line:
                # Extract URL using regex
                match = re.search(r"\((https?://[^)]+)\)", line)
                if match:
                    url = match.group(1)
                    title = line.split("](")[0].strip("[")

                    # Create a clean entry
                    results.append(f"{count+1}. **{title}**\n   LINK: {url}")
                    count += 1

        if not results:
            return "❌ No search results found. Try a broader query."

        header = f"--- 🔎 SEARCH RESULTS FOR: '{query}' ---\n"
        instructions = "\n\n👉 SYSTEM HINT: To read a result, use `read_web_page(url='...')` on one of the links above."
        return header + "\n".join(results) + instructions

    # --- NETWORK LAYER (Remote Only) ---

    async def _fetch_via_browserless(self, url: str) -> str:
        """
        Connects to the `browser` container via WebSocket.
        Includes optimization to BLOCK images/fonts for speed.
        """
        async with async_playwright() as p:
            browser = None
            try:
                # Connect to the remote container
                logger.debug(f"Connecting to CDP at {self.browser_ws}")
                browser = await p.chromium.connect_over_cdp(self.browser_ws)

                # Create context with stealth/user-agent settings
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                )

                page = await context.new_page()

                # --- OPTIMIZATION: Network Interception ---
                # This makes the browser nearly as fast as curl by blocking heavy assets
                await page.route("**/*", lambda route: self._handle_route(route))

                # Navigate with a generous timeout for the container communication
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")

                # Handle "Hydration" (wait for body to actually populate)
                try:
                    await page.wait_for_selector("body", timeout=5000)
                except:
                    pass

                # Extract HTML
                html = await page.content()

                # Convert to Markdown
                return self.converter.handle(html)

            except Exception as e:
                logger.error(f"Remote Browser Error: {e}")
                return f"Error reading page via browser service: {e}"
            finally:
                if browser:
                    await browser.close()

    async def _handle_route(self, route):
        """Block images, fonts, and media to speed up scraping."""
        if route.request.resource_type in ["image", "media", "font", "stylesheet"]:
            await route.abort()
        else:
            await route.continue_()
