#!/usr/bin/env python
#! start.py
import argparse
import json
import logging
import os
import platform
import re # Import re module for substitution if needed later, not strictly needed now
import secrets
import shutil
import subprocess
import sys
import time
from os.path import join as path_join
from pathlib import Path

import yaml  # Needs: pip install PyYAML
from dotenv import load_dotenv, dotenv_values

# --- Custom YAML Dumper to preserve formatting ---
class PreserveQuoteDumper(yaml.Dumper):
    # Force block style for sequences (lists)
    def represent_sequence(self, tag, sequence, flow_style=None):
        return super().represent_sequence(tag, sequence, flow_style=False)

    # Try to preserve multiline strings with '|'
    def represent_scalar(self, tag, value, style=None):
        if isinstance(value, str):
            if '\n' in value:
                # Ensure it ends with a newline for proper block scalar formatting
                if not value.endswith('\n'):
                    value += '\n'
                return super().represent_scalar(tag, value, style='|')
            # Optional: Force double quotes for simple strings if desired
            # return super().represent_scalar(tag, value, style='"')
        return super().represent_scalar(tag, value, style=style)

# Standard Python logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Load initial .env if present, primarily for SHARED_PATH from system env
load_dotenv()


class DockerManager:
    """
    Manages Docker Compose stack operations, generates .env files,
    and creates a runtime docker-compose file by substituting ${VAR} placeholders
    from .env into a template file.
    Optional Ollama integration.
    """

    # --- Class Attributes ---
    _ENV_EXAMPLE_FILE = ".env.example"
    _ENV_FILE = ".env"
    _TEMPLATE_COMPOSE_FILE = "docker-compose.template.yml"  # Source template
    _RUNTIME_COMPOSE_FILE = "docker-compose.runtime.yml"  # Generated file

    _OLLAMA_IMAGE = "ollama/ollama"
    _OLLAMA_CONTAINER = "ollama"
    _OLLAMA_PORT = "11434"

    # --- Initialization ---
    def __init__(self, args):
        self.args = args
        self.is_windows = platform.system() == "Windows"
        self.log = log
        self.env_values = {}
        if self.args.verbose:
            self.log.setLevel(logging.DEBUG)
        self.log.debug("DockerManager initialized with args: %s", args)
        self._ensure_env_example_file()
        self._ensure_required_env_file_and_load()
        # Configure shared path AFTER loading env, as .env might contain it
        self._configure_shared_path()
        # Generate runtime compose AFTER loading env and configuring shared path
        self._generate_runtime_compose_file()
        self._ensure_dockerignore()

    # --- Core Docker/System Command Execution ---
    def _run_command(self, cmd_list, check=True, capture_output=False, text=True,
                     suppress_logs=False, **kwargs):
        processed_cmd_list = list(cmd_list)
        # Ensure we always use the generated runtime file for compose commands
        if processed_cmd_list[0] == "docker" and len(processed_cmd_list) > 1 and processed_cmd_list[1] == "compose":
            # Inject '-f <runtime_file>' right after 'compose' if not already present
            if "-f" not in processed_cmd_list:
                compose_subcommand_index = 2 # Index after 'docker' and 'compose'
                processed_cmd_list.insert(compose_subcommand_index, "-f")
                processed_cmd_list.insert(compose_subcommand_index + 1, self._RUNTIME_COMPOSE_FILE)
            # Replace any occurrence of a different compose file arg with the runtime one
            try:
                f_index = processed_cmd_list.index("-f")
                if f_index + 1 < len(processed_cmd_list) and processed_cmd_list[f_index+1] != self._RUNTIME_COMPOSE_FILE:
                   log.warning(f"Overriding specified compose file '{processed_cmd_list[f_index+1]}' with '{self._RUNTIME_COMPOSE_FILE}'")
                   processed_cmd_list[f_index+1] = self._RUNTIME_COMPOSE_FILE
            except ValueError:
                pass # -f was not found, handled by injection logic above
            log.debug(f"Using runtime compose file flag: {' '.join(processed_cmd_list)}")

        cmd_str = " ".join(map(str,processed_cmd_list)) # Ensure all elements are strings for join
        if not suppress_logs:
            self.log.info("Running command: %s", cmd_str)
        try:
            result = subprocess.run(processed_cmd_list, check=check, capture_output=capture_output,
                                    text=text, shell=self.is_windows, **kwargs) # shell=True needed on Windows for commands like docker
            if not suppress_logs:
                self.log.debug("Command finished: %s", cmd_str)
                if result.stdout:
                    self.log.debug("Command stdout:\n%s", result.stdout.strip())
                if result.stderr and result.stderr.strip():
                    # Log stderr as warning if non-empty, even on success, as it might contain important info
                    self.log.warning("Command stderr:\n%s", result.stderr.strip())
            return result
        except subprocess.CalledProcessError as e:
            self.log.error(f"Command failed: {cmd_str}\nReturn Code: {e.returncode}")
            if e.stdout:
                self.log.error("STDOUT:\n%s", e.stdout.strip())
            if e.stderr:
                self.log.error("STDERR:\n%s", e.stderr.strip())
            if check:
                raise
            return e
        except Exception as e:
            self.log.error(f"Error running command {cmd_str}: {e}", exc_info=self.args.verbose)
            raise

    # --- .dockerignore Generation ---
    def _ensure_dockerignore(self):
        dockerignore = Path(".dockerignore")
        runtime_ignore_line = self._RUNTIME_COMPOSE_FILE
        # Add template file to ignore as well
        template_ignore_line = self._TEMPLATE_COMPOSE_FILE
        ignore_content_base = [
            "__pycache__/", ".venv/", "*.pyc", ".git/", ".env*", "!.env.example",
             "*.sqlite", "dist/", "build/", ".idea/", ".vscode/", "shared/", # Also ignore shared dir content by default
             "*.log", "logs/"
            ]
        full_ignore_content = ignore_content_base + [runtime_ignore_line, template_ignore_line]

        if not dockerignore.exists():
            self.log.warning(".dockerignore not found. Generating default...")
            dockerignore.write_text("\n".join(full_ignore_content) + "\n")
        else:
            try:
                current_ignores = dockerignore.read_text().splitlines()
                needs_update = False
                content_to_add = ""
                if runtime_ignore_line not in current_ignores:
                    self.log.info(f"Adding '{runtime_ignore_line}' to existing .dockerignore")
                    content_to_add += f"\n{runtime_ignore_line}"
                    needs_update = True
                if template_ignore_line not in current_ignores:
                    self.log.info(f"Adding '{template_ignore_line}' to existing .dockerignore")
                    content_to_add += f"\n{template_ignore_line}"
                    needs_update = True

                if needs_update:
                     with open(dockerignore, "a", encoding="utf-8") as f:
                        f.write(content_to_add + "\n")
            except Exception as e:
                log.warning(f"Could not read/update .dockerignore: {e}")

    # --- Environment File Generation ---
    def _generate_dot_env_example_file(self):
        target_example_file = Path(self._ENV_EXAMPLE_FILE)
        if target_example_file.exists():
            log.debug(f"Example env file '{self._ENV_EXAMPLE_FILE}' already exists.")
            return
        self.log.info(f"Generating default example env file: {target_example_file}...")
        # Use placeholders that are less likely to conflict with shell syntax if used directly
        default_content = """# .env.example - Configuration for entities_api stack
# Service URLs (adjust if using different hostnames/ports locally)
ASSISTANTS_BASE_URL=http://localhost:9000/
SANDBOX_SERVER_URL=http://sandbox:8000
DOWNLOAD_BASE_URL=http://localhost:9000/v1/files/download
BASE_URL_HEALTH=http://localhost:9000/v1/health
SHELL_SERVER_URL=ws://sandbox_api:8000/ws/computer
CODE_EXECUTION_URL=ws://sandbox_api:8000/ws/execute

# Database Credentials (Generate new secrets for .env)
MYSQL_ROOT_PASSWORD=__MYSQL_ROOT_PASSWORD__
MYSQL_DATABASE=cosmic_catalyst
MYSQL_USER=ollama
MYSQL_PASSWORD=__MYSQL_PASSWORD__
MYSQL_EXTERNAL_PORT=3307 # Host port mapping for external access
DATABASE_URL=mysql+pymysql://${MYSQL_USER}:${MYSQL_PASSWORD}@db:3306/${MYSQL_DATABASE}
SPECIAL_DB_URL=mysql+pymysql://${MYSQL_USER}:${MYSQL_PASSWORD}@localhost:${MYSQL_EXTERNAL_PORT}/${MYSQL_DATABASE}

# API / Application Secrets (Generate new secrets for .env)
API_KEY=__DEFAULT_API_KEY__
DEFAULT_SECRET_KEY=__DEFAULT_SECRET_KEY__
SIGNED_URL_SECRET=__SIGNED_URL_SECRET__
SECRET_KEY=__SECRET_KEY__ # General Flask/FastAPI secret key if needed

# Qdrant Configuration
QDRANT_HOST=qdrant
QDRANT_PORT=6333
QDRANT_URL=http://${QDRANT_HOST}:${QDRANT_PORT}

# Ollama Configuration (Optional, if used)
OLLAMA_HOST=ollama
OLLAMA_PORT=11434

# Sandbox Configuration
DISABLE_FIREJAIL=true

# Samba Configuration (Credentials here are defaults, can be overridden)
SMBCLIENT_SERVER=samba_server
SMBCLIENT_SHARE=cosmic_share
SMBCLIENT_USERNAME=samba_user
SMBCLIENT_PASSWORD=default # Change this in your actual .env if needed
SMBCLIENT_PORT=1445 # Host port mapping for Samba
SAMBA_USERID=1000
SAMBA_GROUPID=1000
SAMBA_TZ=UTC

# Tool IDs (Generate new unique IDs for .env)
TOOL_CODE_INTERPRETER=tool___TOOL_CODE_INTERPRETER__
TOOL_WEB_SEARCH=tool___TOOL_WEB_SEARCH__
TOOL_COMPUTER=tool___TOOL_COMPUTER__
TOOL_VECTOR_STORE_SEARCH=tool___TOOL_VECTOR_STORE_SEARCH__

# General Settings
LOG_LEVEL=INFO
PYTHONUNBUFFERED=1 # Ensures Python logs appear correctly in Docker
SHARED_PATH=./shared # Relative path for the shared volume mount
"""
        try:
            target_example_file.write_text(default_content, encoding="utf-8")
            log.info(f"Successfully created '{self._ENV_EXAMPLE_FILE}'. Please review and fill your '.env' file.")
        except Exception as e:
            self.log.error(f"Failed to generate {target_example_file}: {e}")

    def _ensure_env_example_file(self):
        if not os.path.exists(self._ENV_EXAMPLE_FILE):
            self.log.warning(f"Missing example env file: {self._ENV_EXAMPLE_FILE}. Generating.")
            self._generate_dot_env_example_file()

    def _generate_dot_env_file_content(self):
        """Generates a dictionary of default values for a new .env file."""
        self.log.info("Generating NEW default values for '.env' file...")
        # Generate secure random values for secrets
        db_user = "ollama" # Keep username fixed if required by migrations/setup
        db_password = secrets.token_hex(16)
        db_root_password = secrets.token_hex(16)
        db_name = "cosmic_catalyst" # Keep fixed if needed
        secret_key_val = secrets.token_hex(32) # General purpose secret key
        signed_url_secret_val = secrets.token_hex(32)
        api_key_val = f"sk-{secrets.token_urlsafe(32)}" # Example format for API Key
        default_secret_key_val = secrets.token_urlsafe(32) # Often used by Flask/FastAPI

        # Generate unique tool IDs
        tool_code = f"tool_{secrets.token_hex(8)}"
        tool_web = f"tool_{secrets.token_hex(8)}"
        tool_comp = f"tool_{secrets.token_hex(8)}"
        tool_vec = f"tool_{secrets.token_hex(8)}"

        # Default ports and hosts (can be overridden in .env)
        mysql_external_port = "3307"
        qdrant_port = "6333"
        qdrant_host = "qdrant"
        ollama_port = "11434"
        smb_port = "1445"
        smb_user = "samba_user"
        smb_password = "default" # Use a default, user should change if sensitive

        # Construct URLs using other values
        database_url_val = f"mysql+pymysql://{db_user}:{db_password}@db:3306/{db_name}"
        special_db_url_val = f"mysql+pymysql://{db_user}:{db_password}@localhost:{mysql_external_port}/{db_name}"
        qdrant_url = f"http://{qdrant_host}:{qdrant_port}"

        env_dict = {
            # Service URLs
            "ASSISTANTS_BASE_URL": "http://localhost:9000/",
            "SANDBOX_SERVER_URL": "http://sandbox:8000",
            "DOWNLOAD_BASE_URL": "http://localhost:9000/v1/files/download",
            "BASE_URL_HEALTH": "http://localhost:9000/v1/health",
            "SHELL_SERVER_URL": "ws://sandbox_api:8000/ws/computer",
            "CODE_EXECUTION_URL": "ws://sandbox_api:8000/ws/execute",
            # Database
            "MYSQL_ROOT_PASSWORD": db_root_password,
            "MYSQL_DATABASE": db_name,
            "MYSQL_USER": db_user,
            "MYSQL_PASSWORD": db_password,
            "MYSQL_EXTERNAL_PORT": mysql_external_port,
            "DATABASE_URL": database_url_val,
            "SPECIAL_DB_URL": special_db_url_val,
            # API/App Secrets
            "API_KEY": api_key_val,
            "DEFAULT_SECRET_KEY": default_secret_key_val,
            "SIGNED_URL_SECRET": signed_url_secret_val,
            "SECRET_KEY": secret_key_val,
            # Qdrant
            "QDRANT_HOST": qdrant_host,
            "QDRANT_PORT": qdrant_port,
            "QDRANT_URL": qdrant_url,
            # Ollama
            "OLLAMA_HOST": "ollama", # Usually service name
            "OLLAMA_PORT": ollama_port,
            # Sandbox
            "DISABLE_FIREJAIL": "true",
            # Samba
            "SMBCLIENT_SERVER": "samba_server",
            "SMBCLIENT_SHARE": "cosmic_share",
            "SMBCLIENT_USERNAME": smb_user,
            "SMBCLIENT_PASSWORD": smb_password, # User should ideally change this
            "SMBCLIENT_PORT": smb_port,
            "SAMBA_USERID": "1000",
            "SAMBA_GROUPID": "1000",
            "SAMBA_TZ": "UTC",
            # Tool IDs
            "TOOL_CODE_INTERPRETER": tool_code,
            "TOOL_WEB_SEARCH": tool_web,
            "TOOL_COMPUTER": tool_comp,
            "TOOL_VECTOR_STORE_SEARCH": tool_vec,
            # General
            "LOG_LEVEL": "INFO",
            "PYTHONUNBUFFERED": "1",
            "SHARED_PATH": "./shared" # Default relative path
        }
        return env_dict

    def _write_dot_env_file(self, env_dict):
        self.log.info(f"Writing generated default values to '{self._ENV_FILE}'...")
        lines = [f"# Auto-generated .env file on: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                 "# Please review and adjust values, especially secrets and paths."]
        lines.extend([f"{key}={value}" for key, value in env_dict.items()])
        try:
            Path(self._ENV_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.log.info(f"✅ Successfully created '{self._ENV_FILE}'.")
        except Exception as e:
            self.log.error(f"Failed to write '{self._ENV_FILE}': {e}")
            sys.exit(1)

    def _ensure_required_env_file_and_load(self):
        """Ensures .env file exists (generating if not) and loads values into self.env_values."""
        self.log.debug(f"Ensuring '{self._ENV_FILE}' exists and loading values...")
        env_file_path = Path(self._ENV_FILE)
        if not env_file_path.exists():
            self.log.warning(f"Required env file '{self._ENV_FILE}' missing. Generating default values.")
            generated_values = self._generate_dot_env_file_content()
            self._write_dot_env_file(generated_values)
            # Load the just-written file to ensure consistency
            loaded_values = dotenv_values(self._ENV_FILE)
        else:
            self.log.info(f"Loading environment variables from existing '{self._ENV_FILE}'.")
            loaded_values = dotenv_values(self._ENV_FILE)

        # Store loaded values, filtering out None values potentially caused by empty entries
        self.env_values = {k: v for k, v in loaded_values.items() if v is not None}

        if not self.env_values:
            self.log.critical(f"Failed to load or generate environment variables from '{self._ENV_FILE}'. Exiting.")
            sys.exit(1)

        # Check for presence of *some* essential keys (adjust list as needed)
        required_for_operation = ["MYSQL_ROOT_PASSWORD", "MYSQL_PASSWORD", "DATABASE_URL", "SHARED_PATH", "DEFAULT_SECRET_KEY"]
        missing = [k for k in required_for_operation if k not in self.env_values or not self.env_values[k]]
        if missing:
            self.log.warning(f"!!! Check '{self._ENV_FILE}': Missing or empty required keys: {', '.join(missing)}")
        self.log.debug(f"Loaded/Generated {len(self.env_values)} environment variables.")

    # --- Shared Path Configuration ---
    def _configure_shared_path(self):
        """Determines and configures the absolute path for SHARED_PATH."""
        # Prioritize SHARED_PATH from the loaded .env file
        shared_path = self.env_values.get('SHARED_PATH')
        source = f"'{self._ENV_FILE}'"

        if not shared_path:
            # Fallback to system environment variable if not in .env
            shared_path = os.environ.get('SHARED_PATH')
            source = "system environment"

        if shared_path:
            self.log.info(f"Using SHARED_PATH defined in {source}: '{shared_path}'")
        else:
            # If not defined anywhere, generate an OS-specific default
            source = "generated OS default"
            default_base = Path.home() # Use pathlib for home directory
            system = platform.system().lower()
            app_data_dir_name = "EntitiesApiShare" # Consistent naming

            if system == 'windows':
                # Use LocalAppData for user-specific, non-roaming data
                local_app_data = Path(os.environ.get('LOCALAPPDATA', default_base / 'AppData' / 'Local'))
                shared_path = local_app_data / app_data_dir_name
            elif system == 'darwin': # macOS
                # Use Application Support directory
                shared_path = default_base / "Library" / "Application Support" / app_data_dir_name
            elif system == 'linux':
                 # Use ~/.local/share adhering to XDG Base Directory Specification
                 shared_path = default_base / ".local" / "share" / app_data_dir_name
            else:
                # Fallback for other systems (less common)
                shared_path = default_base / f".{app_data_dir_name.lower()}" # e.g., ~/.entitiesapishare

            self.log.info(f"SHARED_PATH not defined. Defaulting to {source}: '{shared_path}'")

        # Ensure the path is absolute and the directory exists
        try:
            abs_shared_path = Path(shared_path).resolve()
            abs_shared_path.mkdir(parents=True, exist_ok=True)
            self.log.info(f"Ensured shared directory exists: {abs_shared_path}")
        except Exception as e:
            self.log.error(f"Error creating or resolving shared path '{shared_path}': {e}. Check permissions or path validity.")
            # Decide if this is critical - perhaps exit if the path is essential?
            # sys.exit(1)
            abs_shared_path = Path(shared_path) # Keep original if resolve/create failed

        # Update env_values and os.environ for consistency during script execution
        # Convert Path object back to string for environment variables
        shared_path_str = str(abs_shared_path)
        self.env_values['SHARED_PATH'] = shared_path_str
        os.environ['SHARED_PATH'] = shared_path_str # Make available to subprocesses if needed

        self.log.debug(f"Final absolute SHARED_PATH set to: {shared_path_str}")


    # --- Runtime Compose File Generation ---
    def _substitute_variables(self, data):
        """Recursively substitutes ${VAR} or $VAR from self.env_values in strings within data."""
        if isinstance(data, str):
            # Use regex to find ${VAR} or $VAR patterns
            # It handles cases where VAR might contain underscores
            # It avoids matching $$VAR (escaped)
            def replace_match(match):
                # Determine if curly braces were used: ${VAR} vs $VAR
                var_name_group1 = match.group(1) # Inside ${...}
                var_name_group2 = match.group(2) # After bare $

                if var_name_group1:
                    var_name = var_name_group1
                elif var_name_group2:
                    var_name = var_name_group2
                else:
                    # This case should ideally not happen with the regex, but handle defensively
                    return match.group(0) # Return original match if extraction fails

                # Handle default values like ${VAR:-default}
                default_val = None
                if ":-" in var_name:
                    var_name, default_val = var_name.split(":-", 1)

                # Get value from loaded .env or the default
                sub_value = self.env_values.get(var_name)

                if sub_value is not None:
                    log.debug(f"Substituting '{match.group(0)}' with value from .env for '{var_name}'")
                    return str(sub_value) # Ensure value is a string
                elif default_val is not None:
                     log.debug(f"Substituting '{match.group(0)}' with default value '{default_val}' for '{var_name}'")
                     return str(default_val) # Ensure value is a string
                else:
                    # Variable not found in .env and no default provided
                    self.log.warning(f"Variable '{var_name}' not found in .env and no default value provided for substitution in '{match.group(0)}'. Keeping placeholder.")
                    return match.group(0) # Keep the original placeholder if var not found

            # Regex explained:
            # \$(\{([^}:]+)(?::-(.*?))?\})  # Matches ${VAR} or ${VAR:-default}
            # |                               # OR
            # (?<!\$)\$([A-Za-z_][A-Za-z0-9_]*) # Matches $VAR (but not $$VAR)
            pattern = r'\$(\{([^}:]+)(?::-([^}]*?))?\})|(?<!\$)\$([A-Za-z_][A-Za-z0-9_]*)'
            # Use re.sub with the replacement function
            return re.sub(pattern, replace_match, data)

        elif isinstance(data, dict):
            return {key: self._substitute_variables(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._substitute_variables(item) for item in data]
        else:
            # Return data unchanged if it's not a string, dict, or list (e.g., int, bool)
            return data

    def _generate_runtime_compose_file(self):
        """Loads template, substitutes variables, removes version key, and writes runtime file."""
        self.log.info(f"Generating runtime compose file: '{self._RUNTIME_COMPOSE_FILE}' from template '{self._TEMPLATE_COMPOSE_FILE}'")
        template_path = Path(self._TEMPLATE_COMPOSE_FILE)
        runtime_path = Path(self._RUNTIME_COMPOSE_FILE)

        if not template_path.exists():
            self.log.error(f"Template Docker Compose file not found at '{template_path}'. Cannot generate runtime file.")
            sys.exit(1)

        try:
            # Load the template using standard YAML loader
            with open(template_path, 'r', encoding='utf-8') as f_template:
                # Use SafeLoader for security if template isn't fully trusted,
                # but FullLoader might be needed for complex tags (less likely here).
                compose_data = yaml.load(f_template, Loader=yaml.FullLoader)

            if not compose_data or not isinstance(compose_data, dict):
                self.log.error(f"Invalid or empty template file: '{template_path}'.")
                sys.exit(1)

            # **Explicitly remove the top-level 'version' key if it exists**
            if 'version' in compose_data:
                log.warning(f"Removing obsolete 'version: {compose_data['version']}' key from compose data.")
                del compose_data['version']

            # Perform variable substitution using the loaded .env values
            substituted_data = self._substitute_variables(compose_data)
            self.log.debug("Completed variable substitutions.")

            # Write the final runtime compose file using the custom dumper
            with open(runtime_path, 'w', encoding='utf-8') as f_runtime:
                # default_flow_style=False favors block style
                # indent=2 for standard YAML indentation
                # allow_unicode=True for broader character support
                # sort_keys=False preserves the order from the template
                yaml.dump(substituted_data, f_runtime, Dumper=PreserveQuoteDumper,
                          default_flow_style=False, sort_keys=False, indent=2, allow_unicode=True)

            self.log.info(f"✅ Successfully generated runtime compose file: '{runtime_path}'")

        except yaml.YAMLError as e:
             self.log.critical(f"Error parsing template file '{template_path}': {e}", exc_info=self.args.verbose)
             sys.exit(1)
        except Exception as e:
            self.log.critical(f"Error generating runtime compose file '{runtime_path}': {e}", exc_info=self.args.verbose)
            sys.exit(1)


    # --- Ollama Integration ---
    # ... (Ollama methods remain unchanged, assuming they are working as intended)
    def _has_docker(self):
        return shutil.which("docker") is not None

    def _is_container_running(self, container_name):
        try:
            result = self._run_command(
                ["docker", "ps", "--filter", f"name=^{container_name}$", "--quiet"],
                capture_output=True, text=True, check=False, suppress_logs=True)
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(f"Check container '{container_name}' failed: {e}")
            return False

    def _is_image_present(self, image_name):
        try:
            result = self._run_command(["docker", "images", image_name, "--quiet"],
                                       capture_output=True, text=True, check=False,
                                       suppress_logs=True)
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(f"Check image '{image_name}' failed: {e}")
            return False

    def _has_nvidia_support(self):
        if shutil.which("nvidia-smi") is None:
            self.log.debug("nvidia-smi not found.")
            return False
        try:
            self._run_command(["nvidia-smi"], check=True, capture_output=True, suppress_logs=True)
            self.log.debug("nvidia-smi check passed.")
            return True
        except Exception as e:
            self.log.warning(f"nvidia-smi check failed: {e}.")
            return False

    def _start_ollama(self, cpu_only=True):
        if not self._has_docker():
            self.log.error("❌ Docker not found.")
            return False
        c_name = self._OLLAMA_CONTAINER
        i_name = self._OLLAMA_IMAGE
        port = self._OLLAMA_PORT
        if self._is_container_running(c_name):
            self.log.info(f"✅ Ollama '{c_name}' already running.")
            return True
        if not self._is_image_present(i_name):
            self.log.info(f"📦 Pulling Ollama image '{i_name}'...")
            try:
                self._run_command(["docker", "pull", i_name], check=True)
            except Exception as e:
                self.log.error(f"❌ Pull failed: {e}")
                return False
        self.log.info(f"🚀 Starting Ollama container '{c_name}'...")
        cmd = ["docker", "run", "-d", "--rm", "-v", "ollama:/root/.ollama", "-p", f"{port}:{port}",
               "--name", c_name]
        if not cpu_only and self._has_nvidia_support():
            # Note: Ensure docker daemon is configured for NVIDIA runtime
            cmd.insert(2, "--gpus=all")
            self.log.info("   Attempting to start Ollama with GPU support (--gpus=all)")
        elif not cpu_only:
            self.log.warning("   GPU requested for Ollama, but NVIDIA support check failed. Starting in CPU mode.")
        else:
             self.log.info("   Starting Ollama in CPU mode.")

        cmd.append(i_name)

        try:
            self._run_command(cmd, check=True)
            self.log.info(f"   Waiting a few seconds for Ollama container '{c_name}' to initialize...")
            time.sleep(5) # Give Ollama a moment to start up
            if self._is_container_running(c_name):
                self.log.info(f"✅ Ollama container '{c_name}' started successfully on port {port}.")
                return True
            else:
                self.log.error(f"❌ Ollama container '{c_name}' failed to start or stay running.")
                # Attempt to get logs to help diagnose
                try:
                    log.info(f"   Fetching recent logs for failed container '{c_name}':")
                    self._run_command(["docker", "logs", "--tail", "50", c_name], check=False, suppress_logs=False) # Show logs
                except Exception as le:
                    log.error(f"   Failed to retrieve logs for '{c_name}': {le}")
                return False
        except Exception as e:
            self.log.error(f"❌ Failed 'docker run' command for Ollama: {e}")
            return False

    def _ensure_ollama(self, opt_in=False, use_gpu=False):
        if not opt_in:
            self.log.info("ℹ️ Ollama integration not requested via --with-ollama.")
            return True # Not requested is considered success for this step
        self.log.info("--- Ollama Setup ---")
        run_gpu = use_gpu
        if platform.system() == "Darwin" and run_gpu:
            # GPU support on macOS via Docker Desktop is complex/limited
            self.log.warning("⚠️ macOS detected. GPU support for Ollama via Docker is experimental/unreliable. Forcing CPU mode.")
            run_gpu = False

        start_gpu_mode = False
        if run_gpu:
            self.log.info("   Checking for NVIDIA GPU support...")
            if self._has_nvidia_support():
                self.log.info("   NVIDIA GPU support detected.")
                start_gpu_mode = True
            else:
                 self.log.warning("   NVIDIA GPU support not detected (nvidia-smi check failed or command not found).")

        if run_gpu and not start_gpu_mode:
            self.log.warning("   GPU mode requested (--ollama-gpu), but support not available. Starting Ollama in CPU mode.")

        mode = "GPU" if start_gpu_mode else "CPU"
        self.log.info(f"Attempting Ollama start ({mode} mode)...")
        success = self._start_ollama(cpu_only=not start_gpu_mode)
        self.log.info("--- End Ollama Setup ---")
        return success


    # --- Docker Cache Diagnostics ---
    # ... (Cache diagnostic methods remain unchanged)
    def _get_directory_size(self, path_str="."):
        ignore_patterns = set()
        dockerignore_path = Path(".dockerignore")
        if dockerignore_path.exists():
            try:
                patterns = dockerignore_path.read_text(encoding='utf-8').splitlines()
                ignore_patterns = {p.strip() for p in patterns if
                                   p.strip() and not p.startswith('#')}
                log.debug(f"Read {len(ignore_patterns)} patterns from .dockerignore")
            except Exception as e:
                log.warning(f"Could not read or parse .dockerignore: {e}")
        total_size = 0
        root_path = Path(path_str).resolve()
        try:
            for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
                current_rel_path = Path(dirpath).relative_to(root_path)
                dirs_to_remove = []
                for i, dirname in enumerate(dirnames):
                    dir_rel_path = current_rel_path / dirname
                    if (dirname in ignore_patterns or f"{dirname}/" in ignore_patterns or
                        any(p.name in ignore_patterns or f"{p.name}/" in ignore_patterns for p in
                            dir_rel_path.parents)):
                        dirs_to_remove.append(dirname)
                for d in reversed(dirs_to_remove):
                    dirnames.remove(d)
                for filename in filenames:
                    file_rel_path = current_rel_path / filename
                    if (filename in ignore_patterns or
                        (Path(
                            filename).suffix and f"*{Path(filename).suffix}" in ignore_patterns) or
                        any(p.name in ignore_patterns or f"{p.name}/" in ignore_patterns for p in
                            file_rel_path.parents)):
                        continue
                    try:
                        fp = Path(dirpath) / filename
                        if fp.is_file() and not fp.is_symlink():
                            total_size += fp.stat().st_size
                    except Exception:
                        continue
        except Exception as e:
            self.log.error(f"Error walking {root_path}: {e}")
        return total_size / (1024 * 1024)  # MB

    def _run_docker_cache_diagnostics(self):
        self.log.info("--- Docker Cache Diagnostics ---")
        try:
            context_size_mb = self._get_directory_size()
            self.log.info(f"Estimated build context size (respecting .dockerignore): {context_size_mb:.2f} MB")
            if context_size_mb > 500: # Threshold can be adjusted
                self.log.warning("Build context size > 500MB. Review .dockerignore for unneeded files/dirs to potentially speed up builds.")

            # Use compose config to list services reliably
            ps_config = self._run_command(["docker", "compose", "config", "--services"],
                                          capture_output=True, text=True, check=False,
                                          suppress_logs=True)
            if ps_config.returncode != 0 or not ps_config.stdout:
                 self.log.warning("Could not list services using 'docker compose config --services'. Skipping image history.")
                 self.log.info("--- End Docker Cache Diagnostics ---")
                 return

            services = ps_config.stdout.strip().splitlines()
            self.log.info("Services defined in compose file: %s", ", ".join(services))

            # Get image names from parsed config
            image_names = {}
            try:
                # Use --format json for structured output
                config_json_output = self._run_command(["docker", "compose", "config", "--format", "json"],
                                                capture_output=True, text=True, check=True,
                                                suppress_logs=True).stdout
                config_data = json.loads(config_json_output)
                # Extract image names for services that have an 'image' key defined
                # Note: Services using only 'build' won't have a fixed 'image' name here unless specified in compose
                image_names = {s_name: s_cfg.get("image") for s_name, s_cfg in
                               config_data.get("services", {}).items() if s_cfg.get("image")}
            except Exception as e:
                log.warning(f"Could not parse compose config JSON to get defined image names: {e}. History might be incomplete.")

            # Display history for images explicitly named in the compose file
            built_services_with_no_image_tag = []
            for service_name in services:
                # Check if service is built locally (has a build section)
                service_config = config_data.get("services", {}).get(service_name, {})
                has_build_section = "build" in service_config

                # Get the potential image name (explicitly set or default generated by compose)
                image_name = image_names.get(service_name) # Get explicitly defined image name first

                if not image_name and has_build_section:
                     # If only 'build' is specified, compose generates a default name (e.g., project_service)
                     # We can try to infer it, but it's less reliable than an explicit 'image' tag
                     # For now, just note the services being built without explicit image names
                     built_services_with_no_image_tag.append(service_name)
                     continue # Skip history check if image name is not explicitly defined

                if not image_name:
                     log.debug(f"Service '{service_name}' does not have an 'image' tag defined. Skipping history.")
                     continue

                self.log.info(f"--- History for image '{image_name}' (Service: '{service_name}') ---")
                try:
                    history_cmd = ["docker", "history", image_name, "--no-trunc", "--format",
                                   "{{.ID}} | {{.Size}} | {{.CreatedBy}}"]
                    history = self._run_command(history_cmd, check=False, capture_output=True, text=True, suppress_logs=True)

                    if history.returncode == 0 and history.stdout:
                        self.log.info(f"History (Layer ID | Size | Command):\n{history.stdout.strip()}")
                    elif history.returncode != 0:
                        err_msg = history.stderr.strip() if history.stderr else "Unknown error retrieving history."
                        # Common error is image not found locally
                        if "No such object" in err_msg or "image not found" in err_msg:
                             self.log.warning(f"Image '{image_name}' not found locally. Cannot display history. (Perhaps needs building or pulling?)")
                        else:
                             self.log.warning(f"Failed to get history for '{image_name}':\n{err_msg}")
                    else:
                         self.log.info("No history found for this image (or image is empty).")

                except Exception as e:
                    self.log.warning(f"Error running 'docker history' for '{image_name}': {e}")
                self.log.info(f"--- End History for {image_name} ---")

            if built_services_with_no_image_tag:
                log.info(f"Note: Services built locally without an explicit 'image' tag in compose: {', '.join(built_services_with_no_image_tag)}. History not shown.")

        except Exception as e:
            self.log.error("Docker cache diagnostics failed unexpectedly: %s", e, exc_info=self.args.verbose)
        self.log.info("--- End Docker Cache Diagnostics ---")


    # --- Docker Compose Actions ---
    # ... (Compose action methods like _handle_down, _handle_build, _handle_up remain largely unchanged,
    #      as they correctly use _run_command which now injects the runtime file path)
    def _handle_nuke(self):
        self.log.warning("!!! NUKE MODE ACTIVATED !!! This will stop and remove all containers, networks, volumes, and images associated with this project AND potentially prune dangling Docker resources.")
        try:
            confirm = input("This is highly destructive. Type 'NUKE DOCKER' to confirm: ")
        except EOFError: # Handle case where input stream is closed (e.g., in non-interactive environment)
            self.log.error("Nuke confirmation could not be obtained (non-interactive?). Aborting.")
            sys.exit(1)

        if confirm != "NUKE DOCKER":
            self.log.info("Nuke cancelled.")
            sys.exit(0)

        self.log.info("Proceeding with Docker Nuke...")
        errors = False
        try:
            # 1. Stop and remove project containers, networks, volumes
            self.log.info("Step 1: Running 'docker compose down --volumes --remove-orphans'...")
            self._run_command(["docker", "compose", "down", "--volumes", "--remove-orphans", "--timeout", "30"], check=False) # Don't stop on error here
            log.info("   Compose down completed.")
        except Exception as e:
            log.error(f"   Error during compose down: {e}")
            errors = True # Continue pruning even if down fails partially

        try:
            # 2. Prune dangling Docker resources (optional but thorough)
            self.log.info("Step 2: Running 'docker system prune -a --volumes --force'...")
            # Use check=True here as prune failure might indicate bigger Docker issues
            self._run_command(["docker", "system", "prune", "-a", "--volumes", "--force"], check=True)
            self.log.info("   System prune completed.")
        except Exception as e:
             self.log.critical(f"   Error during system prune: {e}")
             errors = True

        if errors:
             self.log.error("❌ Nuke encountered errors. Please check Docker status and logs.")
             sys.exit(1)
        else:
             self.log.info("✅ Nuke complete.")

    def _handle_down(self):
        target_services = self.args.services or [] # Currently unused by 'down', but kept for consistency
        action = "Stopping project containers"
        if self.args.clear_volumes:
            action += " and removing associated volumes"
            # Add confirmation if clearing ALL volumes for the project
            if not target_services: # If no specific services targeted, 'down -v' removes all project volumes
                 try:
                    confirm = input(f"Delete ALL volumes defined in '{self._RUNTIME_COMPOSE_FILE}'? (yes/no): ").lower().strip()
                 except EOFError:
                    self.log.error("Volume deletion confirmation could not be obtained (non-interactive?). Aborting.")
                    sys.exit(1)
                 if confirm != 'yes':
                    self.log.info("Volume deletion cancelled. Running 'down' without --volumes.")
                    self.args.clear_volumes = False # Prevent adding --volumes flag
            else:
                 # Note: 'docker compose down --volumes service_a' currently doesn't exist.
                 # 'down --volumes' affects all volumes listed in the compose file.
                 self.log.warning("Targeting services with '--clear-volumes' is not directly supported by 'docker compose down'. "
                                  "The '--volumes' flag will affect ALL volumes in the compose file if used.")
                 # Ask for confirmation anyway, making the scope clear
                 try:
                    confirm = input(f"Running 'down --volumes' will remove ALL volumes in '{self._RUNTIME_COMPOSE_FILE}', even though services were targeted. Proceed? (yes/no): ").lower().strip()
                 except EOFError:
                    self.log.error("Confirmation could not be obtained. Aborting 'down --volumes'.")
                    sys.exit(1)
                 if confirm != 'yes':
                     self.log.info("Volume deletion cancelled. Running 'down' without --volumes.")
                     self.args.clear_volumes = False

        self.log.info(f"{action}...")
        down_cmd = ["docker", "compose", "down", "--remove-orphans", "--timeout", "30"]
        if self.args.clear_volumes:
            down_cmd.append("--volumes")
        # Note: 'down' command doesn't take service names as arguments typically
        # if target_services:
        #     down_cmd.extend(target_services) # This usually doesn't work as expected for 'down'

        try:
            # Use check=True to ensure the command executes successfully
            self._run_command(down_cmd, check=True)
            self.log.info("✅ Docker compose down complete.")
        except Exception as e:
            # Catch potential errors during the down process
            self.log.error(f"'docker compose down' command failed: {e}")
            # Exit with error code 1 if down fails
            sys.exit(1)

    def _handle_build(self):
        self.log.info(f"Building images using compose file: '{self._RUNTIME_COMPOSE_FILE}'")
        target_services = self.args.services or []
        build_cmd = ["docker", "compose", "build"]
        t_start = time.time()

        if self.args.no_cache:
            build_cmd.append("--no-cache")
            log.info("   (Build cache disabled)")
        if self.args.pull:
            build_cmd.append("--pull")
            log.info("   (Attempting to pull newer base images)")
        if target_services:
            build_cmd.extend(target_services)
            log.info(f"Building specific services: {', '.join(target_services)}...")
        else:
             log.info("Building all services defined in compose file...")

        try:
            # Execute the build command, checking for errors
            self._run_command(build_cmd, check=True)
            t_end = time.time()
            self.log.info(f"✅ Build complete in {t_end - t_start:.2f} seconds.")

            # Optional tagging if --tag argument was provided
            if self.args.tag:
                self._tag_images(self.args.tag, targeted_services=target_services)

        except Exception as e:
            # Catch errors during the build process
            self.log.critical(f"Build failed: {e}")
            # Exit with error code 1 if build fails
            sys.exit(1)

    def _tag_images(self, tag, targeted_services=None):
        """Tags images built by compose, based on 'image' tag in compose file."""
        if not tag:
            log.warning("Tagging requested but no tag provided.")
            return
        self.log.info(f"Attempting to tag images with tag '{tag}'...")

        try:
            # Get the configuration to find the 'image' tags
            config_json_output = self._run_command(["docker", "compose", "config", "--format", "json"],
                                            capture_output=True, check=True, suppress_logs=True).stdout
            config_data = json.loads(config_json_output)
            services_config = config_data.get("services", {})

            services_to_tag = targeted_services if targeted_services else list(services_config.keys())
            count = 0
            skipped_no_image = []
            skipped_not_targeted = []

            for s_name, s_cfg in services_config.items():
                if s_name not in services_to_tag:
                     skipped_not_targeted.append(s_name)
                     continue

                image_name = s_cfg.get("image")
                if not image_name:
                    skipped_no_image.append(s_name)
                    continue # Cannot tag if no 'image' name is defined in compose

                # Assuming image name might have a default tag like 'latest', split it
                base_image_name = image_name.split(":", 1)[0]
                new_image_ref = f"{base_image_name}:{tag}"

                self.log.info(f"  Attempting to tag '{image_name}' -> '{new_image_ref}' (Service: {s_name})")
                try:
                    # Run 'docker tag' command
                    self._run_command(["docker", "tag", image_name, new_image_ref], check=True,
                                      suppress_logs=not self.args.verbose) # Only show tag command in verbose mode
                    count += 1
                except Exception as e:
                    # Log specific tagging errors, e.g., source image not found
                    self.log.error(f"    Failed to tag '{image_name}': {e}")
                    self.log.error(f"    (Ensure the image '{image_name}' exists locally after the build)")

            if skipped_no_image:
                log.warning(f"Skipped tagging for services without an explicit 'image' tag: {', '.join(skipped_no_image)}")
            if skipped_not_targeted:
                 log.debug(f"Services not targeted for tagging: {', '.join(skipped_not_targeted)}")

            self.log.info(f"Image tagging process complete ({count} images tagged).")

        except Exception as e:
            # Catch errors during config parsing or the tagging loop
            self.log.error(f"Tagging process failed: {e}")


    def _handle_up(self):
        self.log.info(f"Bringing up stack using compose file: '{self._RUNTIME_COMPOSE_FILE}'")
        target_services = self.args.services or []
        up_cmd = ["docker", "compose", "up"]
        mode = "detached (-d)" if not self.args.attached else "attached (foreground)"

        if not self.args.attached:
            up_cmd.append("-d")
        if self.args.build_before_up:
            up_cmd.append("--build")
            log.info("   (Will build images before starting)")
        if self.args.force_recreate:
            up_cmd.append("--force-recreate")
            log.info("   (Will force recreation of containers)")
        # Add specific services if provided
        if target_services:
            up_cmd.extend(target_services)
            log.info(f"Starting specific services: {', '.join(target_services)} in {mode} mode...")
        else:
             log.info(f"Starting all services in {mode} mode...")

        try:
            # Execute the 'up' command
            self._run_command(up_cmd, check=True)
            self.log.info("✅ Docker compose up completed successfully.")

            # If running detached, provide hint for viewing logs
            if not self.args.attached:
                log_cmd_display = ["docker", "compose", "-f", self._RUNTIME_COMPOSE_FILE, "logs", "-f"]
                if target_services:
                    log_cmd_display.extend(target_services)
                else:
                     # Maybe show only API/Sandbox logs by default if no services specified?
                     log_cmd_display.extend(["api", "sandbox"]) # Example: Tail api/sandbox logs

                log_cmd_str = " ".join(log_cmd_display)
                self.log.info(f"👀 Containers running in detached mode. View logs with: {log_cmd_str}")

        except subprocess.CalledProcessError as e:
             # Handle failures specifically for 'up' command
             self.log.critical(f"'docker compose up' command failed with return code {e.returncode}.")
             # Attempt to show recent logs from relevant containers to aid debugging
             try:
                log.info("Attempting to fetch recent logs for debugging...")
                # Fetch logs for services that were targeted, or default to api/sandbox if all were started
                services_to_log = target_services if target_services else ["api", "sandbox", "db", "qdrant", "samba"] # Log more on failure
                logs_cmd = ["docker", "compose", "logs", "--tail=100"] + services_to_log
                self._run_command(logs_cmd, check=False, suppress_logs=False) # Show logs on failure
             except Exception as log_e:
                 log.error(f"Could not fetch logs after failure: {log_e}")
             # Exit with the original error code from the failed 'up' command
             sys.exit(e.returncode)
        except Exception as e:
            # Catch other potential exceptions during 'up'
            self.log.critical(f"An unexpected error occurred during 'docker compose up': {e}")
            sys.exit(1)


    # --- Main Execution Logic ---
    def run(self):
        """Parses arguments and executes the requested Docker actions."""
        if self.args.debug_cache:
            self._run_docker_cache_diagnostics()
            sys.exit(0)

        if self.args.nuke:
            self._handle_nuke() # Nuke handles its own exit

        # Handle Ollama setup if requested
        if self.args.with_ollama:
            if not self._ensure_ollama(opt_in=True, use_gpu=self.args.ollama_gpu):
                # Decide if Ollama failure should stop the script
                self.log.error("Ollama setup failed. Continuing without Ollama...")
                # Or uncomment below to exit if Ollama is critical
                # self.log.critical("Ollama setup failed. Exiting.")
                # sys.exit(1)

        # Handle 'down' actions first if requested
        # --down flag OR --clear-volumes flag OR mode is down_only triggers down
        run_down = self.args.down or self.args.clear_volumes or self.args.mode == 'down_only'
        if run_down:
            self._handle_down() # Down handles its own exit on failure
            # If mode was specifically 'down_only', exit now
            if self.args.mode == 'down_only':
                self.log.info("Mode was 'down_only'. Exiting after 'down' operation.")
                sys.exit(0)

        # Handle 'build' action if mode requires it
        if self.args.mode in ["build", "both"]:
            self._handle_build() # Build handles its own exit on failure

        # Handle 'up' action if mode requires it
        # Note: --build-before-up is handled by the 'up' command itself if mode is 'up' or 'both'
        if self.args.mode in ["up", "both"]:
            self._handle_up() # Up handles its own exit on failure

        self.log.info("✅ Script finished successfully.")


    # --- Argument Parsing ---
    @staticmethod
    def parse_args():
        parser = argparse.ArgumentParser(
            description="Manage the Entities API Docker stack using a runtime compose file.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
            )

        # Core modes
        parser.add_argument(
            "--mode",
            choices=["up", "build", "both", "down_only"],
            default="up",
            help="Main operation mode: 'up' (start containers), 'build' (build images), "
                 "'both' (build then up), 'down_only' (stop and potentially clean containers/volumes)."
            )

        # Build options
        parser.add_argument("--no-cache", action="store_true", help="Disable cache during 'docker compose build'.")
        parser.add_argument("--pull", action="store_true", help="Always attempt to pull newer base images during 'build'.")
        parser.add_argument("--tag", type=str, metavar="TAG", help="Tag the built images with TAG (only works with '--mode build' or '--mode both'). Requires 'image' tag in compose service.")

        # Up options
        parser.add_argument("--attached", "-a", action="store_true", help="Run 'docker compose up' in attached (foreground) mode instead of detached.")
        parser.add_argument("--build-before-up", action="store_true", help="Force build before 'up' (equivalent to 'docker compose up --build'). Implicit in '--mode both'.")
        parser.add_argument("--force-recreate", action="store_true", help="Force recreation of containers during 'up', even if configuration hasn't changed.")

        # Down options
        parser.add_argument("--down", action="store_true", help="Run 'docker compose down' before other actions (except nuke/debug). Useful with '--mode up' or '--mode both' to ensure clean start.")
        parser.add_argument("--clear-volumes", "-cv", action="store_true", help="Remove volumes during 'down' operation (triggers 'down' if not already active). Prompts for confirmation if applied to all services.")

        # Targeting
        parser.add_argument("--services", nargs='+', metavar='SERVICE', help="Target specific services for 'build' or 'up' actions.")

        # Integrations / Utils
        parser.add_argument("--with-ollama", action="store_true", help="Attempt to manage (start/check) an Ollama container.")
        parser.add_argument("--ollama-gpu", action="store_true", help="Attempt to start Ollama with GPU support (requires NVIDIA drivers and Docker setup).")
        parser.add_argument("--nuke", action="store_true", help="Highly destructive: Stop/remove project containers/volumes AND prune system Docker resources.")
        parser.add_argument("--debug-cache", action="store_true", help="Run diagnostics on Docker build context size and image history.")
        parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug logging.")

        args = parser.parse_args()

        # --- Post-parsing validation and info ---
        if args.tag and args.mode not in ['build', 'both']:
            log.warning("--tag argument provided but mode is not 'build' or 'both'. Tagging will be skipped.")
        if args.build_before_up and args.mode == 'build':
             log.info("--build-before-up is redundant when --mode=build.")
        # Clarify interaction between --down/--clear-volumes and modes
        if (args.down or args.clear_volumes) and args.mode not in ['down_only']:
            log.info(f"Note: --down or --clear-volumes specified with --mode={args.mode}. 'Down' action will run *before* '{args.mode}' actions.")

        return args


# --- Main Entry Point ---
if __name__ == "__main__":
    try:
        arguments = DockerManager.parse_args()
        manager = DockerManager(arguments)
        manager.run()
    except KeyboardInterrupt:
        log.info("\n🛑 Operation cancelled by user (Ctrl+C).")
        sys.exit(130) # Standard exit code for SIGINT
    except subprocess.CalledProcessError as e:
        # Errors from _run_command with check=True are caught here if not handled by specific methods
        log.critical(f"❌ A critical command failed execution (Return Code: {e.returncode}). See logs above for details.")
        sys.exit(e.returncode or 1) # Exit with the command's return code
    except SystemExit as e:
         # Allow sys.exit calls within the script to propagate naturally
         raise e
    except Exception as e:
        # Catch any other unexpected exceptions
        log.critical("❌ An unexpected error occurred:", exc_info=(log.level <= logging.DEBUG)) # Show traceback if verbose
        sys.exit(1) # General error exit code
