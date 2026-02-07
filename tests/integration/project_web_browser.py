import platform
import subprocess
import asyncio
import math
import logging
import requests
import html2text
from playwright.async_api import async_playwright

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebReader")

class UniversalWebReader:
    def __init__(self):
        # Configure HTML to Markdown converter
        self.converter = html2text.HTML2Text()
        self.converter.ignore_links = False      # Keep links (useful for citations)
        self.converter.ignore_images = True      # Strip images (save tokens)
        self.converter.ignore_tables = False
        self.converter.body_width = 0            # No wrap

        # Heuristics: If the text contains these, the "Fast" fetch failed.
        self.garbage_triggers = [
            "enable javascript", "please wait", "loading...",
            "cookie settings", "browser not supported",
            "javascript is required", "checking your browser"
        ]

    async def read(self, url: str) -> str:
        """
        The Main Tool for the Agent.
        Returns: A Markdown string (chunked if too long).
        """
        logger.info(f"📖 Reading: {url}")

        # --- PHASE 1: The "Speed Run" (Static Request) ---
        # 1. Try to fetch raw HTML without a browser (Cheap/Fast)
        content = self._fetch_static(url)

        # 2. Check if the content is valid (not a JS stub)
        if self._is_valid_content(content):
            logger.info("⚡ Static fetch successful.")
            return self._format_output(content, source="Static (Fast)")

        # --- PHASE 2: The "Heavy Lift" (Headless Browser) ---
        # 3. If static failed, launch the browser
        logger.info("⚠️  Static fetch failed/garbage. Switching to Headless Browser...")
        content = await self._fetch_dynamic(url)

        return self._format_output(content, source="Dynamic (High-Fidelity)")

    def _fetch_static(self, url: str) -> str:
        """
        Attempts to fetch content without launching a full browser.
        Adapts automatically between Windows (requests) and Linux (w3m).
        """
        try:
            # WINDOWS DEV MODE: Use Python Requests
            if platform.system() == "Windows":
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                return self.converter.handle(response.text)

            # LINUX / DOCKER MODE: Use w3m (Faster, native)
            else:
                result = subprocess.run(
                    ["w3m", "-dump", "-T", "text/html", url],
                    capture_output=True, text=True, timeout=10
                )
                return result.stdout.strip()

        except Exception as e:
            logger.error(f"Static fetch error: {e}")
            return ""

    async def _fetch_dynamic(self, url: str) -> str:
        """
        Launches Playwright to render JavaScript and extract content.
        """
        async with async_playwright() as p:
            try:
                # Launch Chromium (Headless)
                browser = await p.chromium.launch(headless=True)

                # Context with User Agent (Avoids basic bot detection)
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                )
                page = await context.new_page()

                # Navigate and wait for network to settle (JS loaded)
                await page.goto(url, timeout=60000, wait_until="networkidle")

                # Get the HTML and convert to Markdown
                html = await page.content()
                await browser.close()

                return self.converter.handle(html)

            except Exception as e:
                return f"Error reading page: {e}"

    def _is_valid_content(self, text: str) -> bool:
        """Checks if the fetched text is actual content or just a 'Loading' screen."""
        if not text or len(text) < 300: # Too short? Probably garbage.
            return False

        # Check for specific "JS Required" phrases in the first 1000 chars
        header = text.lower()[:1000]
        if any(trigger in header for trigger in self.garbage_triggers):
            return False
        return True

    def _format_output(self, text: str, source: str) -> str:
        """
        Prepares the text for the LLM.
        - Adds Metadata
        - Truncates if huge (Context Window Safety)
        """
        token_estimate = len(text) // 4

        # Hard cap for "Phase 1": If it's huge, just give the first 10k chars (approx 2500 tokens)
        # In the future, you can implement the "Scroll" tool here.
        limit = 10000
        is_truncated = len(text) > limit
        clean_text = text[:limit]

        output = f"--- WEB SOURCE: {source} ---\n"
        output += f"--- LENGTH: {len(text)} chars (~{token_estimate} tokens) ---\n"
        if is_truncated:
            output += "--- NOTICE: Content truncated. (Ask to read more if needed) ---\n\n"

        output += clean_text
        return output

# --- TEST BLOCK (Run this file directly) ---
if __name__ == "__main__":
    async def main():
        reader = UniversalWebReader()

        # Test 1: Static Site (Fast)
        print(await reader.read("http://example.com"))

        # Test 2: Dynamic Site (Slow) - Requires Playwright
        print("\n" + "="*50 + "\n")
        print(await reader.read("https://react.dev"))

    asyncio.run(main())
