#!/usr/bin/env python
import argparse
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from os.path import getsize, islink, join as path_join
from pathlib import Path
import secrets
import yaml # Needs: pip install PyYAML

from dotenv import load_dotenv, dotenv_values

# Standard Python logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Load initial .env if present, primarily for SHARED_PATH from system env
load_dotenv()

class DockerManager:
    """
    Manages Docker Compose stack operations, generates .env files,
    and creates a runtime docker-compose file by injecting specific values
    from .env directly into a template, mimicking a target configuration.
    Optional Ollama integration.
    """

    # --- Class Attributes ---
    _ENV_EXAMPLE_FILE = ".env.example"
    _ENV_FILE = ".env"
    _TEMPLATE_COMPOSE_FILE = "docker-compose.template.yml" # Source template
    _RUNTIME_COMPOSE_FILE = "docker-compose.runtime.yml" # Generated file

    _OLLAMA_IMAGE = "ollama/ollama"
    _OLLAMA_CONTAINER = "ollama"
    _OLLAMA_PORT = "11434"

    # --- Initialization ---
    def __init__(self, args):
        """Initializes the DockerManager."""
        self.args = args
        self.is_windows = platform.system() == "Windows"
        self.log = log
        self.env_values = {} # Store loaded/generated env values

        if self.args.verbose:
            self.log.setLevel(logging.DEBUG)
        self.log.debug("DockerManager initialized with args: %s", args)

        # --- Critical Setup Order ---
        self._ensure_env_example_file()
        self._ensure_required_env_file_and_load()
        self._configure_shared_path()
        self._generate_runtime_compose_file() # Generate file based on loaded env
        self._ensure_dockerignore()

    # --- Core Docker/System Command Execution ---
    def _run_command(self, cmd_list, check=True, capture_output=False, text=True, suppress_logs=False, **kwargs):
        """
        Helper method to run shell commands using subprocess.
        Injects '-f <runtime_compose_file>' into 'docker compose' commands.
        """
        processed_cmd_list = list(cmd_list) # Make a copy

        # Inject the runtime compose file path into docker compose commands
        if processed_cmd_list[0] == "docker" and len(processed_cmd_list) > 1 and processed_cmd_list[1] == "compose":
            if "-f" not in processed_cmd_list: # Avoid duplicate flags
                compose_subcommand_index = 2
                processed_cmd_list.insert(compose_subcommand_index, "-f")
                processed_cmd_list.insert(compose_subcommand_index + 1, self._RUNTIME_COMPOSE_FILE)
                log.debug(f"Injecting runtime compose file flag: {' '.join(processed_cmd_list)}")

        cmd_str = " ".join(processed_cmd_list)
        if not suppress_logs:
            self.log.info("Running command: %s", cmd_str)
        try:
            result = subprocess.run(
                processed_cmd_list, check=check, capture_output=capture_output, text=text,
                shell=self.is_windows, **kwargs
            )
            if not suppress_logs:
                self.log.debug("Command finished: %s", cmd_str)
                if result.stdout:
                    self.log.debug("Command stdout:\n%s", result.stdout.strip())
                if result.stderr and result.stderr.strip():
                    self.log.debug("Command stderr:\n%s", result.stderr.strip())
            return result
        except subprocess.CalledProcessError as e:
            self.log.error(f"Command failed: {cmd_str}")
            self.log.error(f"Return Code: {e.returncode}")
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
        """Ensures .dockerignore exists and ignores the runtime compose file."""
        dockerignore = Path(".dockerignore")
        ignore_content_base = [
            "__pycache__/", ".venv/", "venv/", "env/", "node_modules/", "*.log",
            "*.pyc", "*.pyo", "*.pyd", ".git/", ".env*", "!.env.example", "*.sqlite",
            "dist/", "build/", "wheels/", "*.egg-info/", ".coverage", "htmlcov/",
            "tmp/", ".idea/", ".vscode/", "*.iml", ".DS_Store", "Thumbs.db"
        ]
        runtime_ignore_line = self._RUNTIME_COMPOSE_FILE

        if not dockerignore.exists():
            self.log.warning(".dockerignore not found. Generating default...")
            full_ignore_content = ignore_content_base + [runtime_ignore_line]
            dockerignore.write_text("\n".join(full_ignore_content) + "\n")
            self.log.info("Generated default .dockerignore.")
        else:
            # Ensure runtime file is in existing ignore file
            try:
                current_ignores = dockerignore.read_text().splitlines()
                if runtime_ignore_line not in current_ignores:
                    self.log.info(f"Adding '{runtime_ignore_line}' to existing .dockerignore")
                    with open(dockerignore, "a", encoding="utf-8") as f:
                        f.write(f"\n{runtime_ignore_line}\n")
            except Exception as e:
                 log.warning(f"Could not read or update .dockerignore: {e}")


    # --- Environment File Generation ---
    def _generate_dot_env_example_file(self):
        """Generates the .env.example file with default placeholder content."""
        target_example_file = Path(self._ENV_EXAMPLE_FILE)
        if target_example_file.exists():
             log.debug(f"Example env file {target_example_file} already exists.")
             return
        self.log.info(f"Generating default example environment file: {target_example_file}...")
        default_content = """# .env.example - Environment variables for Entities API Docker setup
# Copy this file to .env and replace placeholder values (__PLACEHOLDER__) or run the script to generate a .env

#############################
# Base URLs
#############################
ASSISTANTS_BASE_URL="http://localhost:9000/"
SANDBOX_SERVER_URL="http://sandbox:8000" # Use internal service name for compose links
DOWNLOAD_BASE_URL="http://localhost:9000/v1/files/download"

#############################
# Database Configuration
#############################
DATABASE_URL="mysql+pymysql://__MYSQL_USER__:__MYSQL_PASSWORD__@db:3306/__MYSQL_DATABASE__"
SPECIAL_DB_URL="mysql+pymysql://__MYSQL_USER__:__MYSQL_PASSWORD__@localhost:__MYSQL_EXTERNAL_PORT__/__MYSQL_DATABASE__" # For host access
MYSQL_ROOT_PASSWORD="__MYSQL_ROOT_PASSWORD__"
MYSQL_DATABASE="__MYSQL_DATABASE__"
MYSQL_USER="__MYSQL_USER__"
MYSQL_PASSWORD="__MYSQL_PASSWORD__"
MYSQL_EXTERNAL_PORT="3307" # Default external port mapping

#############################
# API Keys & External Services
#############################
API_KEY="__DEFAULT_API_KEY__" # Key used by clients to access your API
QDRANT_HOST="qdrant"
QDRANT_PORT="6333"
QDRANT_URL="http://${QDRANT_HOST}:${QDRANT_PORT}" # URL used by API service
OLLAMA_HOST="ollama"
OLLAMA_PORT="11434"
DEFAULT_SECRET_KEY="__DEFAULT_SECRET_KEY__" # Another key used by the API?

#############################
# Platform Settings
#############################
BASE_URL_HEALTH="http://localhost:9000/v1/health"
SHELL_SERVER_URL="ws://sandbox_api:8000/ws/computer"
CODE_EXECUTION_URL="ws://sandbox_api:8000/ws/execute"
SIGNED_URL_SECRET="__SIGNED_URL_SECRET__" # For signing URLs (e.g., file downloads)
SECRET_KEY="__SECRET_KEY__" # For session/cookie security in API
DISABLE_FIREJAIL="true" # Sandbox setting

#############################
# SMB Client Configuration (Used by API/Sandbox to connect to Samba)
#############################
SMBCLIENT_SERVER="samba_server"
SMBCLIENT_SHARE="cosmic_share" # Must match SHARE definition below
SMBCLIENT_USERNAME="samba_user" # Must match USER definition below
SMBCLIENT_PASSWORD="default" # Must match USER definition below
SMBCLIENT_PORT="445"

#############################
# Tool Identifiers (Example random placeholders)
#############################
TOOL_CODE_INTERPRETER="tool___TOOL_CODE_INTERPRETER__"
TOOL_WEB_SEARCH="tool___TOOL_WEB_SEARCH__"
TOOL_COMPUTER="tool___TOOL_COMPUTER__"
TOOL_VECTOR_STORE_SEARCH="tool___TOOL_VECTOR_STORE_SEARCH__"

#############################
# Other / Development
#############################
LOG_LEVEL="INFO"
PYTHONUNBUFFERED="1" # Recommended for Docker logs
SHARED_PATH="./shared" # Default path for Samba volume mount (relative to project root)
"""
        try:
            target_example_file.write_text(default_content, encoding="utf-8")
            self.log.info(f"[ENV] Generated default {target_example_file}")
        except IOError as e:
            self.log.error(f"[ENV] Failed to write file {target_example_file}: {e}")
        except Exception as e:
            self.log.error(f"[ENV] Unexpected error generating {target_example_file}: {e}")

    def _ensure_env_example_file(self):
        """Checks for the required .env.example file and generates it if missing."""
        self.log.info(f"[ENV SCAN] Checking for example environment file: {self._ENV_EXAMPLE_FILE}...")
        if not os.path.exists(self._ENV_EXAMPLE_FILE):
            self.log.warning(f"[ENV SCAN] Missing example env file: {self._ENV_EXAMPLE_FILE}.")
            self._generate_dot_env_example_file()
        else:
            self.log.info(f"[ENV SCAN] Example environment file {self._ENV_EXAMPLE_FILE} is present.")

    def _generate_dot_env_file_content(self):
        """Generates the content dictionary for a new .env file with random secrets."""
        self.log.info("Generating real values for new .env file...")
        db_user = "ollama"; db_password = secrets.token_hex(16)
        db_root_password = secrets.token_hex(16); db_name = "cosmic_catalyst"
        secret_key_val = secrets.token_hex(32); signed_url_secret_val = secrets.token_hex(32)
        api_key_val = secrets.token_hex(16); default_secret_key_val = secrets.token_urlsafe(32)
        qdrant_host = "qdrant"; qdrant_port = "6333"; qdrant_url = f"http://{qdrant_host}:{qdrant_port}"
        sandbox_server_url = "http://sandbox:8000"; mysql_external_port = "3307"
        database_url_val = f"mysql+pymysql://{db_user}:{db_password}@db:3306/{db_name}"
        special_db_url_val = f"mysql+pymysql://{db_user}:{db_password}@localhost:{mysql_external_port}/{db_name}"
        smb_user = "samba_user"; smb_password = "default"; smb_share = "cosmic_share"
        tool_code = f"tool_{secrets.token_hex(8)}"; tool_web = f"tool_{secrets.token_hex(8)}"
        tool_comp = f"tool_{secrets.token_hex(8)}"; tool_vec = f"tool_{secrets.token_hex(8)}"
        env_dict = {
            "ASSISTANTS_BASE_URL": "http://localhost:9000/", "SANDBOX_SERVER_URL": sandbox_server_url,
            "DOWNLOAD_BASE_URL": "http://localhost:9000/v1/files/download", "DATABASE_URL": database_url_val,
            "SPECIAL_DB_URL": special_db_url_val, "MYSQL_ROOT_PASSWORD": db_root_password,
            "MYSQL_DATABASE": db_name, "MYSQL_USER": db_user, "MYSQL_PASSWORD": db_password,
            "MYSQL_EXTERNAL_PORT": mysql_external_port, "API_KEY": api_key_val, "QDRANT_HOST": qdrant_host,
            "QDRANT_PORT": qdrant_port, "QDRANT_URL": qdrant_url, "OLLAMA_HOST": "ollama",
            "OLLAMA_PORT": self._OLLAMA_PORT, "DEFAULT_SECRET_KEY": default_secret_key_val,
            "BASE_URL_HEALTH": "http://localhost:9000/v1/health", "SHELL_SERVER_URL": "ws://sandbox_api:8000/ws/computer",
            "CODE_EXECUTION_URL": "ws://sandbox_api:8000/ws/execute", "SIGNED_URL_SECRET": signed_url_secret_val,
            "SECRET_KEY": secret_key_val, "DISABLE_FIREJAIL": "true", "SMBCLIENT_SERVER": "samba_server",
            "SMBCLIENT_SHARE": smb_share, "SMBCLIENT_USERNAME": smb_user, "SMBCLIENT_PASSWORD": smb_password,
            "SMBCLIENT_PORT": "445", "TOOL_CODE_INTERPRETER": tool_code, "TOOL_WEB_SEARCH": tool_web,
            "TOOL_COMPUTER": tool_comp, "TOOL_VECTOR_STORE_SEARCH": tool_vec, "LOG_LEVEL": "INFO",
            "PYTHONUNBUFFERED": "1", "SHARED_PATH": "./shared"
        }
        return env_dict

    def _write_dot_env_file(self, env_dict):
        """Writes the given dictionary to the .env file."""
        self.log.info(f"Writing generated values to {self._ENV_FILE}...")
        lines = [f"# Auto-generated .env file on: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"]
        lines.extend([f"{key}={value}" for key, value in env_dict.items()])
        content = "\n".join(lines)
        try:
            Path(self._ENV_FILE).write_text(content, encoding="utf-8")
            self.log.info(f"Successfully wrote {self._ENV_FILE}")
        except Exception as e:
            self.log.error(f"Failed to write {self._ENV_FILE} file: {e}")
            sys.exit(1)

    def _ensure_required_env_file_and_load(self):
        """Checks for .env, generates if missing, and loads values into self.env_values."""
        self.log.debug(f"[ENV SCAN] Ensuring '{self._ENV_FILE}' exists and loading values...")
        env_file_path = Path(self._ENV_FILE)
        if not env_file_path.exists():
            self.log.warning(f"[ENV SCAN] Required environment file '{self._ENV_FILE}' is missing.")
            generated_values = self._generate_dot_env_file_content()
            self._write_dot_env_file(generated_values)
            self.env_values = generated_values
        else:
            self.log.info(f"[ENV SCAN] Required environment file '{self._ENV_FILE}' exists. Loading values.")
            loaded_values = dotenv_values(self._ENV_FILE)
            self.env_values = {k: v for k, v in loaded_values.items() if v is not None}

        if not self.env_values:
             self.log.critical(f"Failed to load or generate environment variables from '{self._ENV_FILE}'. Aborting.")
             sys.exit(1)

        required_keys = [
            "MYSQL_ROOT_PASSWORD", "MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD",
            "API_KEY", "SECRET_KEY", "SIGNED_URL_SECRET", "DEFAULT_SECRET_KEY", "DATABASE_URL",
            "SANDBOX_SERVER_URL", "QDRANT_URL", "SMBCLIENT_USERNAME", "SMBCLIENT_PASSWORD",
            "SMBCLIENT_SHARE", "SHARED_PATH"
        ]
        missing_keys = [key for key in required_keys if key not in self.env_values or not self.env_values[key]]
        if missing_keys:
            self.log.warning(f"!!! Environment check: Missing or empty required keys: {', '.join(missing_keys)}")
            self.log.warning(f"!!! Check your '{self._ENV_FILE}' or the generation logic.")
        self.log.debug(f"Loaded/Generated {len(self.env_values)} environment variables.")

    # --- Shared Path Configuration ---
    def _configure_shared_path(self):
        """
        Configures SHARED_PATH (Priority: System Env > .env > OS Default),
        creates dir, ensures absolute path is in os.environ and self.env_values.
        """
        system = platform.system().lower()
        shared_path = os.environ.get('SHARED_PATH') # Check system env first

        if shared_path:
            self.log.info("Using SHARED_PATH from system environment: %s", shared_path)
        elif 'SHARED_PATH' in self.env_values and self.env_values['SHARED_PATH']:
             shared_path = self.env_values['SHARED_PATH']
             self.log.info(f"Using SHARED_PATH from '{self._ENV_FILE}': %s", shared_path)
        else:
            # Generate default based on OS
            default_base = os.path.expanduser("~")
            if system == 'windows':
                shared_path_base = os.environ.get('LOCALAPPDATA', path_join(default_base, 'AppData', 'Local'))
                shared_path = path_join(shared_path_base, "EntitiesApi", "Share") # Slightly adjusted name
            elif system == 'linux':
                shared_path = path_join(default_base, ".local", "share", "entities_api_share")
            elif system == 'darwin': # macOS
                shared_path = path_join(default_base, "Library", "Application Support", "entities_api_share")
            else:
                self.log.error("Unsupported OS: %s. Cannot set default SHARED_PATH.", system)
                raise RuntimeError(f"Unsupported OS: {system}")
            self.log.info("Defaulting SHARED_PATH to: %s", shared_path)

        # Resolve to absolute path for clarity and consistency
        shared_path = os.path.abspath(shared_path)

        # Ensure the directory exists
        try:
            Path(shared_path).mkdir(parents=True, exist_ok=True)
            self.log.info("Ensured shared directory exists: %s", shared_path)
        except OSError as e:
            self.log.error(f"Failed to create shared directory {shared_path}: {e}. Check permissions.")
        except Exception as e:
            self.log.error(f"Unexpected error configuring shared path {shared_path}: {e}")

        # --- IMPORTANT ---
        # Set in os.environ for the current script AND store in self.env_values
        os.environ['SHARED_PATH'] = shared_path
        self.env_values['SHARED_PATH'] = shared_path
        self.log.debug(f"Final SHARED_PATH set to: {shared_path}")

    # --- Runtime Compose File Generation ---
    def _substitute_variables(self, value):
        """
        Recursively substitute ${VAR} and ${VAR:-default} syntax in
        strings, lists, dicts using self.env_values.
        **Specifically avoids substituting '${SHARED_PATH}'**.
        """
        if isinstance(value, str) and value.strip() == '${SHARED_PATH}':
            log.debug("Skipping substitution for literal ${SHARED_PATH}")
            return value # Return the placeholder itself

        if isinstance(value, str):
            original_value = value
            max_substitutions = 10
            count = 0
            while count < max_substitutions:
                start_index = value.find("${")
                if start_index == -1:
                    break
                end_index = value.find("}", start_index)
                if end_index == -1:
                    self.log.warning(f"Malformed variable placeholder found in '{original_value}'. Stopping substitution.")
                    break

                var_content = value[start_index + 2:end_index]
                var_name = var_content
                default_val = None
                if ":-" in var_content:
                    parts = var_content.split(":-", 1)
                    var_name = parts[0]
                    default_val = parts[1]

                sub_value = self.env_values.get(var_name, default_val) # Use default if var not found

                if sub_value is not None:
                    value = value[:start_index] + str(sub_value) + value[end_index + 1:]
                else:
                    self.log.warning(f"Variable '{var_name}' not found for substitution in '{original_value}'. Removing placeholder.")
                    # Remove the placeholder if not found and no default
                    value = value[:start_index] + value[end_index + 1:]
                count += 1
            if count == max_substitutions:
                 self.log.warning(f"Reached maximum substitution depth for '{original_value}'. Check for circular references.")
            return value
        elif isinstance(value, list):
            return [self._substitute_variables(item) for item in value]
        elif isinstance(value, dict):
            return {key: self._substitute_variables(val) for key, val in value.items()}
        else:
            return value

    def _generate_runtime_compose_file(self):
        """Loads template, substitutes variables, injects specific env vars, and writes runtime file."""
        self.log.info(f"Generating runtime compose file: {self._RUNTIME_COMPOSE_FILE}")
        template_path = Path(self._TEMPLATE_COMPOSE_FILE)
        runtime_path = Path(self._RUNTIME_COMPOSE_FILE)

        if not template_path.exists():
             self.log.critical(f"Template compose file not found: {template_path}. Did you rename it?")
             sys.exit(1)

        try:
            # --- Load Template ---
            with open(template_path, 'r', encoding='utf-8') as f_template:
                # Use FullLoader to better preserve structure like explicit nulls/drivers
                compose_data = yaml.load(f_template, Loader=yaml.FullLoader)

            if not compose_data or 'services' not in compose_data:
                self.log.error(f"Invalid template file: {template_path}. Missing 'services'.")
                sys.exit(1)

            # --- Step 1: Perform ${VAR} substitutions (skips ${SHARED_PATH}) ---
            compose_data = self._substitute_variables(compose_data)
            self.log.debug("Completed ${VAR} substitutions.")

            # --- Step 2: Inject specific 'environment' variables to match gold standard ---
            services_to_inject = {
                "api": ["DATABASE_URL", "SANDBOX_SERVER_URL", "QDRANT_URL", "DEFAULT_SECRET_KEY"],
                "db": ["MYSQL_ROOT_PASSWORD", "MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD"],
                "qdrant": ["QDRANT__STORAGE__STORAGE_PATH", "QDRANT__SERVICE__GRPC_PORT", "QDRANT__LOG_LEVEL"],
                "samba": ["USER", "SHARE", "GLOBAL", "TZ", "USERID", "GROUPID"]
            }

            for service_name, env_vars_to_inject in services_to_inject.items():
                if service_name in compose_data.get('services', {}):
                    service_config = compose_data['services'][service_name]
                    if 'environment' not in service_config: service_config['environment'] = []
                    if isinstance(service_config['environment'], dict):
                       service_config['environment'] = [f"{k}={v}" for k,v in service_config['environment'].items()]

                    existing_env_keys = {item.split("=", 1)[0].lower(): i for i, item in enumerate(service_config['environment']) if isinstance(item, str) and "=" in item}

                    for var_name in env_vars_to_inject:
                        value_to_set = None
                        # Special Handling
                        if service_name == "samba":
                            if var_name == "USER": value_to_set = f"{self.env_values.get('SMBCLIENT_USERNAME', 'samba_user')};{self.env_values.get('SMBCLIENT_PASSWORD', 'default')}"
                            elif var_name == "SHARE": value_to_set = f"{self.env_values.get('SMBCLIENT_SHARE', 'cosmic_share')};/samba/share;yes;no;no;{self.env_values.get('SMBCLIENT_USERNAME', 'samba_user')}"
                            elif var_name == "GLOBAL": value_to_set = self.env_values.get(var_name, "server min protocol = NT1\\nserver max protocol = SMB3")
                            elif var_name == "TZ": value_to_set = self.env_values.get(var_name, "UTC")
                            elif var_name == "USERID": value_to_set = self.env_values.get(var_name, "1000")
                            elif var_name == "GROUPID": value_to_set = self.env_values.get(var_name, "1000")
                            else: value_to_set = self.env_values.get(var_name)
                        elif service_name == "qdrant":
                             static_values = {"QDRANT__STORAGE__STORAGE_PATH": "/qdrant/storage", "QDRANT__SERVICE__GRPC_PORT": "6334"}
                             value_to_set = self.env_values.get(var_name, static_values.get(var_name))
                        else: value_to_set = self.env_values.get(var_name) # Default lookup

                        # Injection/Override
                        if value_to_set is not None:
                            env_string = f"{var_name}={value_to_set}"
                            # Handle literal newline for Samba GLOBAL
                            if service_name == "samba" and var_name == "GLOBAL":
                                env_string = f"{var_name}={value_to_set.replace('\\n', '\n')}"

                            var_name_lower = var_name.lower()
                            if var_name_lower in existing_env_keys:
                                idx = existing_env_keys[var_name_lower]
                                service_config['environment'][idx] = env_string
                                self.log.debug(f"Overriding '{var_name}' in '{service_name}'.")
                            else:
                                service_config['environment'].append(env_string)
                                existing_env_keys[var_name_lower] = len(service_config['environment']) - 1
                                self.log.debug(f"Injecting '{var_name}' into '{service_name}'.")
                        else:
                            self.log.warning(f"Var '{var_name}' for injection into '{service_name}' not found.")

            # --- Step 3: Ensure 'sandbox' service has no 'environment' section (as per gold standard) ---
            if 'sandbox' in compose_data.get('services', {}):
                 if 'environment' in compose_data['services']['sandbox']:
                     log.debug("Removing potentially existing 'environment' section from 'sandbox' service to match gold standard.")
                     del compose_data['services']['sandbox']['environment']

            # --- Step 4: Ensure top-level volumes/networks retain structure from template ---
            # This relies on FullLoader and the template being correct.
            # If template has `volumes: {mysql_data: {driver: local}}`, it should be preserved.
            # If template just has `volumes: [mysql_data]`, it might get simplified.

            # --- Write the runtime file ---
            with open(runtime_path, 'w', encoding='utf-8') as f_runtime:
                yaml.dump(compose_data, f_runtime, default_flow_style=False, sort_keys=False, indent=2, allow_unicode=True)

            self.log.info(f"Successfully generated {runtime_path}")

        except FileNotFoundError:
             self.log.critical(f"Template compose file not found: {template_path}. Did you rename it?")
             sys.exit(1)
        except yaml.YAMLError as e:
            self.log.critical(f"Error parsing YAML file {template_path}: {e}")
            sys.exit(1)
        except Exception as e:
            self.log.critical(f"Unexpected error generating runtime compose file: {e}", exc_info=self.args.verbose)
            sys.exit(1)


    # --- Ollama Integration ---
    def _has_docker(self):
        """Check if Docker command exists."""
        return shutil.which("docker") is not None

    def _is_container_running(self, container_name):
        """Check if a container with the exact name is running."""
        try:
            result = self._run_command(["docker", "ps", "--filter", f"name=^{container_name}$", "--quiet"],
                                       capture_output=True, text=True, check=False, suppress_logs=True)
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(f"Could not check container '{container_name}' status: {e}")
            return False

    def _is_image_present(self, image_name):
        """Check if a Docker image exists locally."""
        try:
            result = self._run_command(["docker", "images", image_name, "--quiet"],
                                       capture_output=True, text=True, check=False, suppress_logs=True)
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(f"Could not check image '{image_name}' presence: {e}")
            return False

    def _has_nvidia_support(self):
        """Check for nvidia-smi command and successful execution."""
        if shutil.which("nvidia-smi") is None:
            self.log.debug("nvidia-smi command not found in PATH.")
            return False
        self.log.debug("nvidia-smi found. Checking execution...")
        try:
            self._run_command(["nvidia-smi"], check=True, capture_output=True, suppress_logs=True)
            self.log.debug("nvidia-smi executed successfully. GPU support detected.")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.log.warning(f"nvidia-smi check failed ({type(e).__name__}). Assuming no GPU support.")
            return False
        except Exception as e:
             self.log.warning(f"Unexpected error running nvidia-smi: {e}. Assuming no GPU support.")
             return False

    def _start_ollama(self, cpu_only=True):
        """Pulls and starts the Ollama container if not already running."""
        if not self._has_docker():
            self.log.error("❌ Docker command not found. Cannot manage Ollama container.")
            return False

        container_name = self._OLLAMA_CONTAINER
        image_name = self._OLLAMA_IMAGE
        ollama_port = self._OLLAMA_PORT

        if self._is_container_running(container_name):
            self.log.info(f"✅ Ollama container '{container_name}' is already running.")
            return True

        # Pull image if missing
        if not self._is_image_present(image_name):
            self.log.info(f"📦 Pulling Ollama image '{image_name}'...")
            # *** CORRECTED SYNTAX ***
            try:
                # Use _run_command for consistency (no -f needed for direct docker pull)
                self._run_command(["docker", "pull", image_name], check=True)
                self.log.info(f"✅ Successfully pulled Ollama image '{image_name}'.")
            except Exception as e:
                self.log.error(f"❌ Failed to pull Ollama image '{image_name}': {e}")
                return False
        else:
             self.log.info(f"ℹ️ Found Ollama image '{image_name}' locally.")


        self.log.info(f"🚀 Starting Ollama container '{container_name}'...")
        # Base 'docker run' command - does NOT use compose
        cmd = [
            "docker", "run", "-d", "--rm",
            "-v", "ollama:/root/.ollama", # Named volume for models
            "-p", f"{ollama_port}:{ollama_port}",
            "--name", container_name
        ]

        # Add GPU flag if requested and supported
        if not cpu_only and self._has_nvidia_support():
            self.log.info("   Adding Docker --gpus=all flag.")
            cmd.insert(2, "--gpus=all") # Insert after 'docker run'
        elif not cpu_only:
            self.log.warning("   GPU mode requested, but nvidia support check failed. Starting Ollama in CPU-only mode.")

        cmd.append(image_name) # Add image name at the end

        # *** CORRECTED SYNTAX & STRUCTURE ***
        try:
            # Run directly, no -f flag needed for 'docker run'
            self._run_command(cmd, check=True)
            time.sleep(5) # Wait briefly for container startup

            if self._is_container_running(container_name):
                self.log.info(f"✅ Ollama container '{container_name}' started successfully on port {ollama_port}.")
                return True
            else:
                # If it failed to start, try showing logs
                self.log.error(f"❌ Ollama container '{container_name}' failed to start after 'docker run'. Checking logs...")
                try:
                    # Use _run_command, suppress its info log but show output
                    self._run_command(["docker", "logs", "--tail", "50", container_name], check=False, suppress_logs=True)
                except Exception as log_e:
                    self.log.error(f"   Could not retrieve logs for failed container '{container_name}': {log_e}")
                return False # Indicate failure
        except Exception as e:
            self.log.error(f"❌ Failed to execute 'docker run' for Ollama: {e}")
            return False # Indicate failure

    def _ensure_ollama(self, opt_in=False, use_gpu=False):
        """Ensures the external Ollama container is running if opted in."""
        if not opt_in:
            self.log.info("ℹ️ Ollama management not requested via --with-ollama. Skipping.")
            return True # Not requested is not a failure

        self.log.info("--- Ollama Setup ---")
        # Check if running inside Docker is typically problematic for this
        if os.path.exists("/.dockerenv"):
            self.log.warning("🛰 Script appears to be running inside a container. Skipping management of external Ollama container.")
            return True

        # Handle OS specifics
        run_gpu = use_gpu # User's request
        if platform.system() == "Darwin":
            self.log.warning("⚠️ Running on macOS. Docker Desktop doesn't support --gpus flag. Use native Ollama app for GPU.")
            run_gpu = False # Force CPU for Docker on Mac

        # Check hardware support if GPU is still requested
        gpu_available = False
        if run_gpu:
            gpu_available = self._has_nvidia_support()
            if not gpu_available:
                self.log.warning("⚠️ GPU mode requested (--ollama-gpu), but NVIDIA support not detected. Falling back to CPU mode.")
        else:
             self.log.debug("GPU mode not requested or not applicable.")


        start_with_gpu = run_gpu and gpu_available # Final decision
        mode_str = "GPU" if start_with_gpu else "CPU"
        self.log.info(f"Attempting to start external Ollama container in {mode_str} mode...")

        # Call the start function with cpu_only flag inverted from start_with_gpu
        success = self._start_ollama(cpu_only=not start_with_gpu)

        self.log.info("--- End Ollama Setup ---")
        return success


    # --- Docker Cache Diagnostics ---
    def _get_directory_size(self, path_str="."):
        """Calculates directory size in MB, respecting basic .dockerignore patterns."""
        ignore_patterns = set()
        dockerignore_path = Path(".dockerignore")
        if dockerignore_path.exists():
            try:
                 patterns = dockerignore_path.read_text(encoding='utf-8').splitlines()
                 ignore_patterns = {p.strip() for p in patterns if p.strip() and not p.startswith('#')}
                 log.debug(f"Read {len(ignore_patterns)} patterns from .dockerignore")
            except Exception as e:
                 log.warning(f"Could not read or parse .dockerignore: {e}")

        total_size = 0
        root_path = Path(path_str).resolve()
        try:
            # Use os.walk for better control over skipping directories
            for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
                current_rel_path = Path(dirpath).relative_to(root_path)

                # Filter dirnames in-place to prevent descending into ignored directories
                dirs_to_remove = []
                for i, dirname in enumerate(dirnames):
                    dir_rel_path = current_rel_path / dirname
                    # Simple ignore checks (add more complex pattern matching if needed)
                    if dirname in ignore_patterns or f"{dirname}/" in ignore_patterns or \
                       any(p.name in ignore_patterns or f"{p.name}/" in ignore_patterns for p in dir_rel_path.parents):
                        dirs_to_remove.append(dirname)
                        # log.debug(f"Skipping descend into ignored dir: {dir_rel_path}")

                # Remove ignored directories from list so os.walk doesn't enter them
                for d in reversed(dirs_to_remove): # Iterate backwards when removing
                     dirnames.remove(d)


                # Process files in the current directory
                for filename in filenames:
                    file_rel_path = current_rel_path / filename
                    # Simple ignore checks for files
                    if filename in ignore_patterns or \
                       (Path(filename).suffix and f"*{Path(filename).suffix}" in ignore_patterns) or \
                       any(p.name in ignore_patterns or f"{p.name}/" in ignore_patterns for p in file_rel_path.parents):
                        # log.debug(f"Ignoring file: {file_rel_path}")
                        continue

                    try:
                        fp = Path(dirpath) / filename
                        if fp.is_file() and not fp.is_symlink():
                            total_size += fp.stat().st_size
                    except FileNotFoundError:
                        log.debug("File disappeared during size check: %s", fp)
                    except OSError as e:
                        log.debug("OS error getting size/info for %s: %s", fp, e)
                    except Exception as e:
                        log.warning("Unexpected error processing file %s: %s", fp, e)

        except Exception as e:
            self.log.error(f"Error walking directory {root_path} for size calculation: {e}")

        return total_size / (1024 * 1024) # Bytes to MB

    def _run_docker_cache_diagnostics(self):
        """Runs diagnostics to help understand Docker build cache issues."""
        self.log.info("--- Docker Cache Diagnostics ---")
        try:
            context_size_mb = self._get_directory_size()
            self.log.info(f"Approximate build context size (respecting basic .dockerignore): {context_size_mb:.2f} MB")
            if context_size_mb > 500:
                self.log.warning("Context size > 500MB. Ensure .dockerignore is comprehensive.")

            self.log.info("Listing services defined in compose file...")
            # _run_command adds -f flag automatically
            ps_config = self._run_command(["docker", "compose", "config", "--services"],
                                          capture_output=True, text=True, check=False, suppress_logs=True)
            services = []
            if ps_config.returncode == 0 and ps_config.stdout.strip():
                services = ps_config.stdout.strip().splitlines()
                self.log.info("Services found: %s", ", ".join(services))
            else:
                self.log.warning("Could not determine services from 'docker compose config'.")

            # Get image names from config for history check
            image_names = {}
            if services:
                 try:
                     # _run_command adds -f flag
                     config_json = self._run_command(["docker", "compose", "config", "--format", "json"],
                                                     capture_output=True, text=True, check=True, suppress_logs=True).stdout
                     config_data = json.loads(config_json)
                     image_names = {s_name: s_cfg.get("image")
                                    for s_name, s_cfg in config_data.get("services", {}).items()
                                    if s_cfg.get("image")} # Get image name if defined
                 except Exception as e:
                      log.warning(f"Could not parse compose config for image names: {e}")

            # Show history for each image found
            for service_name in services:
                image_name = image_names.get(service_name)
                if not image_name:
                    log.debug(f"No explicit image name found for service '{service_name}', skipping history.")
                    continue

                self.log.info(f"--- History for image '{image_name}' (service: {service_name}) ---")
                try:
                    # Use direct docker history, no -f needed
                    history = self._run_command(
                        ["docker", "history", image_name, "--no-trunc", "--format", "{{.ID}} | {{.Size}} | {{.CreatedBy}}"],
                        check=False, capture_output=True, text=True, suppress_logs=True
                    )
                    if history.returncode == 0:
                        output = history.stdout.strip() if history.stdout else "No history found (image might not exist locally)."
                        self.log.info(f"History:\n{output}")
                    else:
                        self.log.warning(f"Could not get history. Error:\n{history.stderr.strip() if history.stderr else 'Unknown error'}")
                except Exception as e:
                    self.log.warning(f"Error running docker history: {e}")
                self.log.info(f"--- End History for {image_name} ---")

            self.log.info("Common cache busters: COPY/ADD commands before dependency installs (e.g., requirements.txt), changing file metadata/permissions, using ARG with changing values.")
            self.log.info("Tip: Structure Dockerfile layers from least to most frequently changing.")

        except Exception as e:
            self.log.error("Failed during Docker cache diagnostics: %s", e, exc_info=self.args.verbose)
        self.log.info("--- End Docker Cache Diagnostics ---")


    # --- Docker Compose Actions ---
    def _handle_nuke(self):
        """Completely removes ALL Docker containers, volumes, networks, and images."""
        self.log.warning("!!! NUKE MODE ACTIVATED !!!")
        self.log.warning("This will permanently delete ALL Docker resources.")
        try:
            confirm = input("Type 'NUKE DOCKER' to confirm this action: ")
        except EOFError: # Handle non-interactive environments
            self.log.error("Nuke requires interactive confirmation. Aborting.")
            sys.exit(1)

        if confirm != "NUKE DOCKER":
            self.log.info("Nuke confirmation failed. Aborting.")
            sys.exit(0)

        self.log.info("Proceeding with Docker nuke...")
        try:
            # Step 1: Stop project first (uses runtime file via _run_command)
            self.log.info("Step 1: Stopping and removing project containers/volumes (best effort)...")
            self._run_command(["docker", "compose", "down", "--volumes", "--remove-orphans", "--timeout", "10"], check=False)

            # Step 2: Prune system (does NOT use compose, no -f needed)
            self.log.info("Step 2: Pruning Docker system (containers, volumes, networks, images)...")
            self._run_command(["docker", "system", "prune", "-a", "--volumes", "--force"], check=True)

            self.log.info("✅ Docker environment nuke completed successfully.")
        except subprocess.CalledProcessError as e:
            self.log.critical(f"Nuke command failed during execution: {e}")
            sys.exit(1)
        except Exception as e:
            self.log.critical(f"An unexpected error occurred during nuke: {e}")
            sys.exit(1)

    def _handle_down(self):
        """Stops containers and optionally removes volumes for the project (using runtime file)."""
        target_services = self.args.services or []
        target_desc = f" specified services: {', '.join(target_services)}" if target_services else " all services"
        action = "Stopping containers"
        volume_action = ""

        if self.args.clear_volumes:
            action += " and removing associated volumes"
            # Only prompt for full volume removal if no specific services targeted
            if not target_services:
                volume_action = "ALL project volumes"
                try:
                    confirm = input(f"This will delete {volume_action}. Are you sure? (yes/no): ").lower().strip()
                except EOFError:
                    self.log.error("Volume deletion requires interactive confirmation. Aborting.")
                    sys.exit(1)
                if confirm != "yes":
                    self.log.info("Volume deletion cancelled.")
                    self.args.clear_volumes = False # Update flag to prevent deletion
            else:
                 # Warn about potential limitations when targeting services
                 self.log.warning(f"Note: Removing volumes for specific services ({target_desc}) might not remove shared named volumes unless they become orphaned.")

        self.log.info(f"{action} for {target_desc}...")
        down_cmd = ["docker", "compose", "down", "--remove-orphans", "--timeout", "30"]
        if self.args.clear_volumes: # Check flag again in case it was cancelled
            down_cmd.append("--volumes")
        # Service names are implicitly handled by the compose file context used by _run_command

        try:
            # _run_command adds -f flag automatically
            self._run_command(down_cmd, check=True)
            self.log.info(f"✅ {action} for {target_desc} completed.")
        except subprocess.CalledProcessError as e:
            self.log.error(f"'docker compose down' command failed: {e}")
            if e.stderr: self.log.error("Error details:\n%s", e.stderr)
            sys.exit(1)
        except Exception as e:
            self.log.error(f"An unexpected error occurred during 'down': {e}")
            sys.exit(1)

    def _handle_build(self):
        """Handles building the Docker images using the runtime compose file."""
        # .env check/load and runtime file generation happens in __init__
        self.log.info(f"Using generated compose file: {self._RUNTIME_COMPOSE_FILE}")

        target_services = self.args.services or []
        target_desc = f" specified services: {', '.join(target_services)}" if target_services else " all services"
        cache_desc = " without using cache" if self.args.no_cache else " using cache"
        pull_desc = " (will attempt to pull newer base images)" if self.args.pull else ""

        self.log.info(f"Building images for {target_desc}{cache_desc}{pull_desc}...")
        build_cmd = ["docker", "compose", "build"]
        if self.args.no_cache: build_cmd.append("--no-cache")
        if self.args.pull: build_cmd.append("--pull")
        if target_services: build_cmd.extend(target_services)

        t_start = time.time()
        try:
            # _run_command adds -f flag automatically
            self._run_command(build_cmd, check=True)
            t_end = time.time()
            self.log.info("✅ Build completed successfully in %.2f seconds.", t_end - t_start)

            if self.args.tag:
                self.log.info(f"Applying tag '{self.args.tag}' to built images...")
                self._tag_images(self.args.tag, targeted_services=target_services)

        except subprocess.CalledProcessError as e:
            self.log.critical(f"Docker build failed: {e}")
            if e.stderr: self.log.error("Error details:\n%s", e.stderr)
            if e.stdout: self.log.error("Output log:\n%s", e.stdout)
            sys.exit(1)
        except Exception as e:
            self.log.critical(f"An unexpected error during build: {e}", exc_info=self.args.verbose)
            sys.exit(1)

    def _tag_images(self, tag, targeted_services=None):
        """Tags built images specified in the runtime compose config."""
        if not tag:
            self.log.warning("No tag provided. Skipping image tagging.")
            return

        self.log.info(f"Attempting to tag images with tag: '{tag}'")
        try:
            # Use runtime config to find image names (_run_command adds -f)
            config_json = self._run_command(["docker", "compose", "config", "--format", "json"],
                                            capture_output=True, check=True, suppress_logs=True).stdout
            config_data = json.loads(config_json)
            services = config_data.get("services", {}) # Use .get for safety

            if not services:
                self.log.warning("No services found in compose configuration. Cannot tag.")
                return

            tagged_count = 0
            skipped_count = 0
            for service_name, config in services.items():
                # Skip if specific services were targeted for build/tag
                if targeted_services and service_name not in targeted_services:
                    self.log.debug(f"Skipping tag for '{service_name}' (not targeted).")
                    skipped_count += 1
                    continue

                image_name_from_config = config.get("image")
                if not image_name_from_config:
                    self.log.debug(f"Service '{service_name}' has no explicit 'image:' definition. Skipping tag.")
                    skipped_count += 1
                    continue

                # Assumes image defined in config is the one just built
                original_ref = image_name_from_config
                base_image = original_ref.split(":", 1)[0] # Name without tag
                new_tag_ref = f"{base_image}:{tag}"

                self.log.info(f"Attempting tag: {original_ref} -> {new_tag_ref} (for service '{service_name}')")
                try:
                    # Check if source exists (direct docker command, no -f)
                    # Suppress logs for inspect command unless verbose
                    inspect_res = self._run_command(["docker", "image", "inspect", original_ref],
                                                    check=False, capture_output=True, suppress_logs=not self.args.verbose)
                    if inspect_res.returncode != 0:
                         self.log.warning(f"  Source image '{original_ref}' not found. Cannot apply tag '{tag}'. (Was it built successfully?)")
                         skipped_count +=1
                         continue

                    # Tag command (direct docker command, no -f)
                    # Suppress logs unless verbose
                    self._run_command(["docker", "tag", original_ref, new_tag_ref], check=True, suppress_logs=not self.args.verbose)
                    self.log.info(f"  Successfully tagged {original_ref} as {new_tag_ref}")
                    tagged_count += 1
                except subprocess.CalledProcessError as tag_e:
                    self.log.error(f"  Failed to tag {original_ref}: {tag_e}")
                    if tag_e.stderr: self.log.error("  Error details: %s", tag_e.stderr.strip())
                except Exception as tag_e:
                     self.log.error(f"  Unexpected error tagging {original_ref}: {tag_e}")

            self.log.info(f"Image tagging complete. Tagged: {tagged_count}, Skipped: {skipped_count}.")

        except json.JSONDecodeError as e:
            self.log.error(f"Failed to parse 'docker compose config' output: {e}")
        except subprocess.CalledProcessError as e:
            self.log.error(f"Command 'docker compose config' failed: {e}")
            if e.stderr: self.log.error("Error details:\n%s", e.stderr)
        except Exception as e:
            self.log.error(f"An unexpected error during image tagging: {e}", exc_info=self.args.verbose)

    def _handle_up(self):
        """Handles starting the Docker containers using the runtime compose file."""
        self.log.info(f"Using generated compose file: {self._RUNTIME_COMPOSE_FILE}")

        mode = "attached" if self.args.attached else "detached"
        target_services = self.args.services or []
        target_desc = f" specified services: {', '.join(target_services)}" if target_services else " all services"

        self.log.info(f"Starting containers for {target_desc} in {mode} mode...")
        up_cmd = ["docker", "compose", "up"]
        if not self.args.attached: up_cmd.append("-d")
        if self.args.build_before_up:
             self.log.info("   (Will attempt build before starting if necessary)")
             up_cmd.append("--build")
        if self.args.force_recreate:
            self.log.info("   (Forcing recreation of containers)")
            up_cmd.append("--force-recreate")
        if target_services: up_cmd.extend(target_services)

        try:
            # _run_command adds -f flag automatically
            self._run_command(up_cmd, check=True)
            self.log.info("✅ Containers started successfully.")
            if not self.args.attached:
                 # Show command with the -f flag for user clarity
                 log_cmd_display = ["docker", "compose", "-f", self._RUNTIME_COMPOSE_FILE, "logs", "-f", "--tail", "50"]
                 if target_services: log_cmd_display.extend(target_services)
                 self.log.info(f"👀 To view logs, run: {' '.join(log_cmd_display)}")

        except subprocess.CalledProcessError as e:
            self.log.critical(f"'docker compose up' failed (Return Code: {e.returncode}).")
            if not self.args.attached:
                 self.log.info("Attempting to show recent logs from failed startup...")
                 try:
                     logs_fail_cmd = ["docker", "compose", "logs", "--tail=100"]
                     if target_services: logs_fail_cmd.extend(target_services)
                     # _run_command adds -f flag
                     self._run_command(logs_fail_cmd, check=False)
                 except Exception as log_e:
                     self.log.error(f"Could not fetch logs after failed 'up': {log_e}")
            sys.exit(e.returncode or 1) # Exit with error code
        except Exception as e:
            self.log.critical(f"An unexpected error occurred during 'up': {e}", exc_info=self.args.verbose)
            sys.exit(1)


    # --- Main Execution Logic ---
    def run(self):
        """Main execution logic based on parsed arguments."""
        # Initialization handles .env and runtime compose generation

        if self.args.debug_cache:
            self._run_docker_cache_diagnostics()
            sys.exit(0)
        if self.args.nuke:
            self._handle_nuke() # Exits script if confirmed
            sys.exit(0) # Should be unreachable

        if self.args.with_ollama:
             if not self._ensure_ollama(opt_in=True, use_gpu=self.args.ollama_gpu):
                 self.log.error("Ollama setup failed. Continuing script...")

        # Sequence: Down (if requested) -> Build (if requested) -> Up (if requested)
        if self.args.down or self.args.clear_volumes or self.args.mode == 'down_only':
             self._handle_down() # Uses runtime file
             if self.args.mode == 'down_only':
                 self.log.info("Down action complete. Exiting as requested.")
                 sys.exit(0)

        if self.args.mode in ["build", "both"]:
            self._handle_build() # Uses runtime file

        if self.args.mode in ["up", "both"]:
            self._handle_up() # Uses runtime file

        self.log.info("Script finished.")

    # --- Argument Parsing ---
    @staticmethod
    def parse_args():
        """Parses command-line arguments."""
        parser = argparse.ArgumentParser(
            description="Manage Entities API Docker Compose stack via a runtime-generated compose file.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )
        parser.add_argument("--mode", choices=["up", "build", "both", "down_only"], default="up", help="Primary action.")
        parser.add_argument("--no-cache", action="store_true", help="Build without cache.")
        parser.add_argument("--pull", action="store_true", help="Pull base images.")
        parser.add_argument("--tag", type=str, metavar="TAG", help="Tag built images.")
        parser.add_argument("--attached", action="store_true", help="Run 'up' attached.")
        parser.add_argument("--build-before-up", action="store_true", help="Force build before 'up'.")
        parser.add_argument("--force-recreate", action="store_true", help="Force recreate containers.")
        parser.add_argument("--down", action="store_true", help="Run 'down' first.")
        parser.add_argument("--clear-volumes", "-cv", action="store_true", help="Remove volumes with 'down'.")
        parser.add_argument("--services", nargs='+', metavar='SERVICE', help="Target specific service(s).")
        parser.add_argument("--with-ollama", action="store_true", help="Ensure Ollama runs.")
        parser.add_argument("--ollama-gpu", action="store_true", help="Try Ollama with GPU.")
        parser.add_argument("--nuke", action="store_true", help="DANGER! Prune Docker system.")
        parser.add_argument("--debug-cache", action="store_true", help="Run cache diagnostics.")
        parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging.")

        args = parser.parse_args()

        # --- Argument validation/warning logic ---
        if (args.down or args.clear_volumes) and args.mode == 'up':
            log.warning("--down or --clear-volumes used with default mode 'up'. Down actions run first only if mode is 'both' or 'down_only'. Use --mode=down_only to only run down actions.")

        if args.build_before_up and args.mode not in ['up', 'both']:
            log.warning("--build-before-up specified, but mode is not 'up' or 'both'. Flag ignored.")

        if args.tag and args.mode not in ['build', 'both']:
             log.warning(f"--tag '{args.tag}' specified, but mode is '{args.mode}'. Tagging only happens after a build (mode 'build' or 'both').")

        return args

# --- Main Entry Point ---
if __name__ == "__main__":
    try:
        arguments = DockerManager.parse_args()
        manager = DockerManager(arguments) # Initialization does the main setup now
        manager.run()
    except KeyboardInterrupt:
        log.info("\n🛑 Operation cancelled by user.")
        sys.exit(130) # Standard exit code for Ctrl+C
    except subprocess.CalledProcessError as e:
        # Error should have been logged by _run_command
        log.critical("❌ A critical command failed during execution.")
        sys.exit(e.returncode or 1) # Exit with command's return code or 1
    except Exception as e:
        log.critical("❌ An unexpected error occurred: %s", e, exc_info=(log.level == logging.DEBUG))
        sys.exit(1)
