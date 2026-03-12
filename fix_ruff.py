"""
fix_ruff.py v4 — Fixes what `ruff --fix` cannot handle automatically:

  E722  bare `except:` -> `except Exception:`
  E402  module-level import not at top of file

Run AFTER:
    python -m ruff check tests/integration/ --fix

Usage:
    python fix_ruff.py
"""

import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# E722 — bare except
# These are the violations still outstanding after ruff --fix
# ---------------------------------------------------------------------------
E722_TARGETS: dict[str, list[int]] = {
    "tests/integration/raw_fc_tg.py": [108, 213],
    "tests/integration/raw_fc_hermes_detection_tg.py": [126, 340],
    "tests/integration/raw_fc_hb_2.py": [237, 283],
    "tests/integration/raw_fc_hb.py": [212, 258],
    "tests/integration/project_web_browser.py": [161],
    "tests/integration/unified_inference_test.py": [75],
}

# ---------------------------------------------------------------------------
# E402 — import not at top of file
#
# Strategy per file:
#   "hoist"  — move the offending import(s) above the non-import statement
#              that triggered E402
#   "remove" — the import is also F401 (unused), so just delete it
# ---------------------------------------------------------------------------
E402_TARGETS: dict[str, str] = {
    # `import os` comes after `dotenv.load_dotenv()` and is also unused (F401)
    # ruff --fix removes it; nothing left to do — listed for documentation only.
    # "tests/integration/config_orc_prompt.py": "remove",
    # `import dotenv` comes after `load_dotenv()` and is also unused (F401)
    # ruff --fix removes it; nothing left to do.
    # "tests/integration/create_assistant_with_platform_tools.py": "remove",
    # `from config_orc_fc import config` comes after load_dotenv()
    "tests/integration/vector_store_pipeline.py": "hoist",
    # `from urllib.parse import urlparse` is buried mid-file
    "tests/integration/user_erasure_test.py": "hoist",
}

SEARCH_WINDOW = 20
BARE_EXCEPT = re.compile(r"^(\s*)except\s*:\s*$")
IMPORT_LINE = re.compile(r"^\s*(import |from \S+ import )")


# ---------------------------------------------------------------------------
# E722 helpers
# ---------------------------------------------------------------------------


def find_bare_except(lines: list[str], hint: int) -> int | None:
    lo = max(0, hint - SEARCH_WINDOW)
    hi = min(len(lines), hint + SEARCH_WINDOW + 1)
    for i in range(lo, hi):
        if BARE_EXCEPT.match(lines[i]):
            return i
    # whole-file fallback — pick closest
    candidates = [i for i, l in enumerate(lines) if BARE_EXCEPT.match(l)]
    return min(candidates, key=lambda i: abs(i - hint)) if candidates else None


def fix_e722_file(path: str, hints: list[int]) -> int:
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()

    changed = 0
    # process highest line-number first so indices stay stable
    for hint in sorted(hints, reverse=True):
        idx = find_bare_except(lines, hint - 1)
        if idx is None:
            print(f"  !! E722 not found near line {hint} in {path}")
            continue
        m = BARE_EXCEPT.match(lines[idx])
        fixed = f"{m.group(1)}except Exception:\n"
        if fixed == lines[idx]:
            print(f"  -- :{idx+1} already fixed")
            continue
        print(f"  [E722] :{idx+1}  {lines[idx].rstrip()!r} -> {fixed.rstrip()!r}")
        lines[idx] = fixed
        changed += 1

    if changed:
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)

    return changed


# ---------------------------------------------------------------------------
# E402 helpers
# ---------------------------------------------------------------------------


def hoist_imports(path: str) -> int:
    """
    Move any import lines that appear after non-import, non-comment,
    non-blank lines to just below the last 'legitimate' top-of-file import.
    Simple heuristic — safe for the two files flagged here.
    """
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()

    # Split into header imports and the rest
    header: list[str] = []
    rest: list[str] = []
    in_header = True

    for line in lines:
        stripped = line.strip()
        if in_header:
            if stripped == "" or stripped.startswith("#") or IMPORT_LINE.match(line):
                header.append(line)
            else:
                in_header = False
                rest.append(line)
        else:
            rest.append(line)

    # Pull any stray import lines out of `rest` and collect them
    stray_imports: list[str] = []
    clean_rest: list[str] = []
    for line in rest:
        if IMPORT_LINE.match(line):
            stray_imports.append(line)
            print(f"  [E402 hoisted] {line.rstrip()!r}")
        else:
            clean_rest.append(line)

    if not stray_imports:
        print(f"  -- no stray imports found in {path}")
        return 0

    # Insert stray imports right after the header block
    new_lines = header + stray_imports + clean_rest
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(new_lines)

    return len(stray_imports)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_ruff_fix() -> None:
    print("\n" + "=" * 60)
    print("  Step 1: python -m ruff check tests/integration/ --fix")
    print("=" * 60)
    subprocess.run(
        [sys.executable, "-m", "ruff", "check", "tests/integration/", "--fix"],
        capture_output=False,
    )


def run_ruff_check() -> int:
    print("\n" + "=" * 60)
    print("  Final check: python -m ruff check tests/integration/")
    print("=" * 60)
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "tests/integration/"],
        capture_output=False,
    )
    return result.returncode


def main() -> None:
    print("=" * 60)
    print("  Ruff auto-fixer v4  (post --fix cleanup)")
    print("=" * 60)

    # Step 1: let ruff handle the 49 auto-fixable violations
    run_ruff_fix()

    # Step 2: fix E722
    print("\n" + "─" * 60)
    print("  Step 2: E722 bare except")
    print("─" * 60)
    total_e722 = 0
    for path, hints in E722_TARGETS.items():
        print(f"\n-> {path}")
        try:
            total_e722 += fix_e722_file(path, hints)
        except FileNotFoundError:
            print(f"  !! not found — skipping")
    print(f"\n  E722 fixes applied: {total_e722}")

    # Step 3: fix E402
    print("\n" + "─" * 60)
    print("  Step 3: E402 import order")
    print("─" * 60)
    total_e402 = 0
    for path, strategy in E402_TARGETS.items():
        print(f"\n-> {path}  [{strategy}]")
        try:
            if strategy == "hoist":
                total_e402 += hoist_imports(path)
            # "remove" cases are handled by ruff --fix in step 1
        except FileNotFoundError:
            print(f"  !! not found — skipping")
    print(f"\n  E402 fixes applied: {total_e402}")

    # Step 4: final verification
    rc = run_ruff_check()
    if rc == 0:
        print("\n  ✅  All clean!")
    else:
        print("\n  !! Some violations remain — check output above.")
        print("     The invalid-syntax errors in raw_fc_hermes_detection_tg.py")
        print("     require manual repair (restore headers dict via git checkout).")


if __name__ == "__main__":
    main()
