read_web_page = {
    "type": "function",
    "function": {
        "name": "read_web_page",
        "description": "Visits a website URL, converts the content to Markdown, and returns the first text chunk (Page 0). If the content is long, it is split into 4000-character pages. HINT: If you are looking for specific information (like 'pricing' or 'email'), use 'search_web_page' immediately after this instead of scrolling.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The valid HTTP/HTTPS URL to visit. Must include protocol (e.g., https://).",
                },
                "force_refresh": {
                    "type": "boolean",
                    "description": "If true, bypasses the internal cache and forces a fresh scrape of the website. Use this if the content seems outdated or missing.",
                    "default": False,
                },
            },
            "required": ["url"],
        },
    },
}
