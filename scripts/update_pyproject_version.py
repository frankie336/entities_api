# scripts/update_pyproject_versions.py
import re
import sys
from pathlib import Path
from typing import List


def update_version(file_path_str: str, new_version: str) -> bool:
    """
    Updates the version = "..." line in a single pyproject.toml file.
    Returns True on success, False on failure for this specific file.
    """
    file_path = Path(file_path_str)
    print(f"Processing: {file_path}...")  # Keep progress on stdout
    if not file_path.is_file():
        print(f"❌ Error: File not found at {file_path}", file=sys.stderr)
        return False  # Indicate failure

    try:
        content = file_path.read_text(encoding="utf-8")

        # Regex to find version = "..." or version = '...' (more robust)
        # Captures: group 1 = 'version = "', group 2 = '"' (or single quotes)
        # This finds the line regardless of the current version format (e.g., '1.2.3-dev')
        version_pattern = r'(version\s*=\s*["\']).*?(["\'])'
        # Replacement uses the captured quotes (\g<1>, \g<2>) and inserts the new version
        replacement = rf"\g<1>{new_version}\g<2>"

        new_content, num_replacements = re.subn(
            version_pattern,
            replacement,
            content,
            count=1,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        if num_replacements == 1:
            # Version found and replaced successfully
            if new_content != content:
                file_path.write_text(new_content, encoding="utf-8")
                print(f'✅ Patched {file_path.name} -> version = "{new_version}"')
            else:
                # Regex matched but content didn't change (likely already correct version)
                print(f'ℹ️  Version in {file_path.name} is already "{new_version}"')
            return True
        else:
            # Version line not found with the expected pattern, attempt to add it
            print(
                f"⚠️ Warning: Version line like 'version = \"...\"' not found/matched in {file_path}. Attempting to add.",
                file=sys.stderr,
            )

            # Define patterns to find the relevant sections, anchored to the start of a line
            project_pattern = r"^\s*\[project\]"  # Prefer PEP 621 standard
            tool_poetry_pattern = r"^\s*\[tool\.poetry\]"

            added = False
            # Try adding under [project] first
            if re.search(project_pattern, content, re.MULTILINE):
                target_pattern = project_pattern
                section_name = "[project]"
            # Fallback to [tool.poetry]
            elif re.search(tool_poetry_pattern, content, re.MULTILINE):
                target_pattern = tool_poetry_pattern
                section_name = "[tool.poetry]"
            else:
                target_pattern = None
                section_name = None

            if target_pattern:
                # Add the version line immediately after the section header
                new_content = re.sub(
                    target_pattern,
                    rf'\1\nversion = "{new_version}"',  # \1 is the matched section header
                    content,
                    count=1,
                    flags=re.MULTILINE,
                )
                if new_content != content:  # Check if substitution actually happened
                    file_path.write_text(new_content, encoding="utf-8")
                    print(
                        f'✅ Added version = "{new_version}" under {section_name} in {file_path.name}'
                    )
                    added = True
                else:
                    print(
                        f"❌ Error: Failed to insert version under {section_name} in {file_path}.",
                        file=sys.stderr,
                    )

            if not added:
                print(
                    f"❌ Error: Could not find a suitable '[project]' or '[tool.poetry]' section header "
                    f"to add the version line in {file_path}.",
                    file=sys.stderr,
                )
                return False  # Indicate failure: Could not find or add

            return True  # Return True if we successfully added the version

    except Exception as e:
        print(f"❌ Error processing file {file_path}: {e}", file=sys.stderr)
        return False  # Indicate failure


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("❌ Error: Missing arguments.", file=sys.stderr)
        print(
            "Usage: python scripts/update_pyproject_versions.py <new_version> <path/to/pyproject1.toml> [path/to/pyproject2.toml ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    new_version_arg: str = sys.argv[1]
    file_paths_to_update: List[str] = sys.argv[2:]

    # Comprehensive Semantic Versioning 2.0.0 regex from https://semver.org/
    # (slightly modified to handle common script usage)
    semver_pattern = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
    if not re.match(semver_pattern, new_version_arg):
        print(
            f"❌ Error: Invalid semantic version format provided: '{new_version_arg}'",
            file=sys.stderr,
        )
        print(
            "   Version must conform to Semantic Versioning 2.0.0 (e.g., 1.2.3, 1.0.0-alpha.1).",
            file=sys.stderr,
        )
        sys.exit(1)

    all_successful: bool = True
    failed_files: List[str] = []

    print(f"\n🚀 Attempting to update version to '{new_version_arg}' in files:")
    for proj_file in file_paths_to_update:
        print(f"   - {proj_file}")
    print("-" * 30)  # Separator

    for proj_file in file_paths_to_update:
        if not update_version(proj_file, new_version_arg):
            all_successful = False
            failed_files.append(proj_file)  # Track failures

    print("-" * 30)  # Separator
    if not all_successful:
        print("\n❌ Finished with errors. Failed to update:")
        for failed_file in failed_files:
            print(f"   - {failed_file}")
        sys.exit(1)  # Exit with error code

    print("\n✅ All specified pyproject.toml files processed successfully.")
