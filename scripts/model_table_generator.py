# -------------------------------------------------------------
#  model_table_generator.py   (unchanged everything else)
# -------------------------------------------------------------
import argparse
import sys
from pathlib import Path  # <‑‑ NEW import

from projectdavid_common.constants.ai_model_map import MODEL_MAP


# --------------------------------------------------------------------
# Helper: build the markdown table
# --------------------------------------------------------------------
def build_markdown_table(model_map: dict) -> str:
    """
    Returns a markdown string where:
        - inference_provider = first segment of the original key
        - entities_route      = the original key itself
    """
    rows = []
    for full_key in model_map.keys():
        provider = full_key.split("/", 1)[0] if "/" in full_key else full_key
        entities_route = full_key  # key becomes the route
        rows.append((provider, entities_route))

    rows.sort(key=lambda x: (x[0].lower(), x[1].lower()))

    header = "| inference_provider | route |\n|---|---|"
    lines = [header] + [f"| {prov} | {route} |" for prov, route in rows]
    return "\n".join(lines)


# --------------------------------------------------------------------
# CLI handling – lets you optionally pass a custom output filename
# --------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a Markdown table of model identifiers."
    )
    parser.add_argument(
        "output_file",
        nargs="?",
        default="model_map.md",
        help="Name of the Markdown file to write (default: model_map.md). "
        "If you give a plain filename it will be placed in the "
        "`docs` folder next to this script.",
    )
    return parser.parse_args()


# --------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------
def main():
    args = parse_args()

    # ---------- 1️⃣  Resolve the *docs* folder relative to this file ----------
    #   script_path = C:\Users\franc\PycharmProjects\entities_api\scripts\model_table_generator.py
    #   project_root = script_path.parent.parent   # <-- entities_api
    #   docs_dir    = project_root / "docs"
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent  # ..\entities_api
    docs_dir = project_root / "docs"

    # Make sure the docs folder exists (creates it if it doesn’t)
    docs_dir.mkdir(parents=True, exist_ok=True)

    # ---------- 2️⃣  Build the full output path ----------
    # If the user supplied a path that already looks like a directory (ends with '/' or '\\')
    # we keep it; otherwise we treat the argument as a *filename* and put it inside docs_dir.
    output_name = args.output_file
    # If the user gave an absolute or relative path that contains a directory separator,
    # we respect it – otherwise we join it with docs_dir.
    if Path(output_name).parent == Path("."):
        output_path = docs_dir / output_name
    else:
        output_path = Path(output_name).expanduser().resolve()

    # ---------- 3️⃣  Generate markdown and write ----------
    markdown = build_markdown_table(MODEL_MAP)

    try:
        with output_path.open("w", encoding="utf-8") as f:
            f.write(markdown + "\n")
        print(f"✅ Markdown table written to '{output_path}'")
    except OSError as exc:
        print(f"❌ Failed to write file: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
