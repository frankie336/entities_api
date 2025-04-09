#!/usr/bin/env python
import argparse
import json
import logging
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
from os.path import getsize, islink
from pathlib import Path
from urllib.parse import quote_plus  # Needed for password escaping in URL

# Third-party import
try:
    import yaml
except ImportError:
    print(
        "Error: PyYAML is required. Please install it: pip install PyYAML",
        file=sys.stderr,
    )
    sys.exit(1)

from dotenv import load_dotenv  # Keep for loading existing .env if needed

# Standard Python logging setup
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)

# --- Constants ---
DEFAULT_DB_CONTAINER_PORT = "3306"
DEFAULT_DB_SERVICE_NAME = "db"  # Default service name for database in compose


class DockerManager:
    """Manages Docker Compose stack operations, env setup, and optional Ollama integration."""

    # --- Class Attributes ---
    _ENV_EXAMPLE_FILE = ".env.example"  # Keep example for reference
    _ENV_FILE = ".env"
    _DOCKER_COMPOSE_FILE = "docker-compose.yml"

    _OLLAMA_IMAGE = "ollama/ollama"
    _OLLAMA_CONTAINER = "ollama"
    _OLLAMA_PORT = "11434"

    # Mapping: .env key -> (docker-compose service name, compose env var name)
    # Define which INDIVIDUAL .env vars should primarily come from docker-compose.yml environment section
    _COMPOSE_ENV_MAPPING = {
        # --- Database Components (Source these first) ---
        "MYSQL_ROOT_PASSWORD": (DEFAULT_DB_SERVICE_NAME, "MYSQL_ROOT_PASSWORD"),
        "MYSQL_DATABASE": (DEFAULT_DB_SERVICE_NAME, "MYSQL_DATABASE"),
        "MYSQL_USER": (
            DEFAULT_DB_SERVICE_NAME,
            "MYSQL_USER",
        ),  # User for the application
        "MYSQL_PASSWORD": (
            DEFAULT_DB_SERVICE_NAME,
            "MYSQL_PASSWORD",
        ),  # Password for the application user
        # --- Other secrets/configs potentially defined directly in compose env: ---
        # 'API_KEY': ('fastapi_cosmic_catalyst', 'API_KEY'), # Example if API_KEY was in compose
        "SMBCLIENT_SERVER": ("fastapi_cosmic_catalyst", "SMBCLIENT_SERVER"),
        "SMBCLIENT_SHARE": ("fastapi_cosmic_catalyst", "SMBCLIENT_SHARE"),
        "SMBCLIENT_USERNAME": ("fastapi_cosmic_catalyst", "SMBCLIENT_USERNAME"),
        "SMBCLIENT_PASSWORD": ("fastapi_cosmic_catalyst", "SMBCLIENT_PASSWORD"),
        "SMBCLIENT_PORT": ("fastapi_cosmic_catalyst", "SMBCLIENT_PORT"),
        "DISABLE_FIREJAIL": (
            "sandbox_api",
            "DISABLE_FIREJAIL",
        ),  # Example if set in sandbox service
    }

    # Define keys that should always be generated using secrets module if not found elsewhere
    _GENERATED_SECRETS = [
        "SIGNED_URL_SECRET",
        "API_KEY",
    ]  # SECRET_KEY is often app-specific, handle separately?

    # Define Tool IDs to be generated
    _GENERATED_TOOL_IDS = [
        "TOOL_CODE_INTERPRETER",
        "TOOL_WEB_SEARCH",
        "TOOL_COMPUTER",
        "TOOL_VECTOR_STORE_SEARCH",
    ]

    # Define default values for keys if they aren't sourced from compose or generated
    # These are fallbacks or standard configurations.
    _DEFAULT_VALUES = {
        # --- Base URLs ---
        "ASSISTANTS_BASE_URL": "http://localhost:9000/",
        "SANDBOX_SERVER_URL": "http://localhost:9000",  # Or maybe 'http://sandbox_api:8000'? Check usage.
        "DOWNLOAD_BASE_URL": "http://localhost:9000/v1/files/download",
        "HYPERBOLIC_BASE_URL": "https://api.hyperbolic.xyz/v1",  # <--- Added new value
        # --- Database Components Fallbacks (if not in compose) ---
        "MYSQL_HOST": DEFAULT_DB_SERVICE_NAME,  # Usually the service name
        "MYSQL_PORT": DEFAULT_DB_CONTAINER_PORT,
        "MYSQL_DATABASE": "cosmic_catalyst",  # Default DB name
        "MYSQL_USER": "ollama",  # Default app user name
        # --- API Keys & External Services Fallbacks ---
        # 'API_KEY': 'your_default_api_key', # Set a default if needed, otherwise _GENERATED_SECRETS handles it
        # --- Platform Settings ---
        "BASE_URL_HEALTH": "http://localhost:9000/v1/health",
        "SHELL_SERVER_URL": "ws://sandbox_api:8000/ws/computer",  # Assumes service name 'sandbox_api'
        "CODE_EXECUTION_URL": "ws://sandbox_api:8000/ws/execute",  # Assumes service name 'sandbox_api'
        "DISABLE_FIREJAIL": "true",  # Default value
        # --- SMB Client Fallbacks ---
        "SMBCLIENT_SERVER": "samba_server",
        "SMBCLIENT_SHARE": "cosmic_share",
        "SMBCLIENT_USERNAME": "samba_user",
        "SMBCLIENT_PASSWORD": "default",  # Default password
        "SMBCLIENT_PORT": "445",
        # --- Other Standard Vars ---
        "LOG_LEVEL": "INFO",
        "PYTHONUNBUFFERED": "1",
        # --- App Specific Secrets (Example: Fallback generation) ---
        "SECRET_KEY": secrets.token_hex(32),  # Generate app's SECRET_KEY if not found
    }

    # Define the structure and order of the final .env file
    _ENV_STRUCTURE = {
        "Base URLs": ["ASSISTANTS_BASE_URL", "SANDBOX_SERVER_URL", "DOWNLOAD_BASE_URL"],
        "Database Configuration": [
            "DATABASE_URL",
            "SPECIAL_DB_URL",  # Composite URLs first
            "MYSQL_ROOT_PASSWORD",
            "MYSQL_DATABASE",
            "MYSQL_USER",
            "MYSQL_PASSWORD",  # Individual components
            # Add MYSQL_HOST, MYSQL_PORT if needed explicitly in .env
        ],
        "API Keys & External Services": [  # Renamed section slightly
            "API_KEY",
            # Add QDRANT/OLLAMA URLs here if needed by the application from .env
            # 'QDRANT_URL': 'http://qdrant:6333',
            # 'OLLAMA_URL': 'http://ollama:11434',
        ],
        "Platform Settings": [
            "BASE_URL_HEALTH",
            "SHELL_SERVER_URL",
            "CODE_EXECUTION_URL",
            "SIGNED_URL_SECRET",
            "DISABLE_FIREJAIL",
            "SECRET_KEY",  # App's main secret key
        ],
        "SMB Client Configuration": [
            "SMBCLIENT_SERVER",
            "SMBCLIENT_SHARE",
            "SMBCLIENT_USERNAME",
            "SMBCLIENT_PASSWORD",
            "SMBCLIENT_PORT",
        ],
        "Tool Identifiers": [
            "TOOL_CODE_INTERPRETER",
            "TOOL_WEB_SEARCH",
            "TOOL_COMPUTER",
            "TOOL_VECTOR_STORE_SEARCH",
        ],
        "Other": [  # Catch-all for anything not categorized
            "LOG_LEVEL",
            "PYTHONUNBUFFERED",
        ],
    }

    # --- Initialization ---
    def __init__(self, args):
        """Initializes the DockerManager."""
        self.args = args
        self.is_windows = platform.system() == "Windows"
        self.log = log

        if self.args.verbose:
            self.log.setLevel(logging.DEBUG)
        self.log.debug("DockerManager initialized with args: %s", args)

        self.compose_config = self._load_compose_config()  # Load config early

        # Initial setup steps
        # self._ensure_env_example_file() # Example file generation might be less critical now
        self._check_for_required_env_file()  # Check/generate the actual .env file
        self._configure_shared_path()
        self._ensure_dockerignore()

    # --- Core Docker/System Command Execution ---
    def _run_command(
        self,
        cmd_list,
        check=True,
        capture_output=False,
        text=True,
        suppress_logs=False,
        **kwargs,
    ):
        """Helper method to run shell commands using subprocess."""
        # ... (no changes needed in this method) ...
        if not suppress_logs:
            self.log.info("Running command: %s", " ".join(cmd_list))
        try:
            result = subprocess.run(
                cmd_list,
                check=check,
                capture_output=capture_output,
                text=text,
                shell=self.is_windows,
                **kwargs,
            )
            if not suppress_logs:
                self.log.debug("Command finished: %s", " ".join(cmd_list))
                if result.stdout:
                    self.log.debug("Command stdout:\n%s", result.stdout.strip())
                if result.stderr and result.stderr.strip():
                    self.log.debug("Command stderr:\n%s", result.stderr.strip())
            return result
        except subprocess.CalledProcessError as e:
            self.log.error(f"Command failed: {' '.join(cmd_list)}")
            self.log.error(f"Return Code: {e.returncode}")
            if e.stdout:
                self.log.error("STDOUT:\n%s", e.stdout.strip())
            if e.stderr:
                self.log.error("STDERR:\n%s", e.stderr.strip())
            if check:
                raise
            return e
        except Exception as e:
            self.log.error(
                f"Error running command {' '.join(cmd_list)}: {e}",
                exc_info=self.args.verbose,
            )
            raise

    # --- .dockerignore Generation ---
    def _ensure_dockerignore(self):
        """Generates a default .dockerignore file if it doesn't exist."""
        # ... (no changes needed in this method) ...
        dockerignore = Path(".dockerignore")
        if not dockerignore.exists():
            self.log.warning(".dockerignore not found. Generating default...")
            # Added .env to default ignore
            dockerignore.write_text(
                "__pycache__/\n.venv/\nnode_modules/\n*.log\n*.pyc\n.git/\n.env*\n.env\n*.sqlite\ndist/\nbuild/\ncoverage/\ntmp/\n*.egg-info/\n"
            )
            self.log.info("Generated default .dockerignore.")

    # --- Environment File Generation ---
    def _load_compose_config(self):
        """Loads and parses the docker-compose.yml file."""
        compose_path = Path(self._DOCKER_COMPOSE_FILE)
        if not compose_path.is_file():
            self.log.warning(
                f"Docker compose file '{self._DOCKER_COMPOSE_FILE}' not found. Cannot extract env vars or ports."
            )
            return None
        try:
            self.log.debug(f"Reading docker compose file: {compose_path}")
            compose_content = compose_path.read_text(encoding="utf-8")
            config = yaml.safe_load(compose_content)
            self.log.debug(f"Successfully parsed {self._DOCKER_COMPOSE_FILE}")
            return config
        except yaml.YAMLError as e:
            self.log.error(f"Error parsing {self._DOCKER_COMPOSE_FILE}: {e}")
            return None
        except Exception as e:
            self.log.error(f"Unexpected error reading {self._DOCKER_COMPOSE_FILE}: {e}")
            return None

    def _get_env_from_compose_service(self, service_name, env_var_name):
        """Safely extracts an environment variable value from a specific service in the loaded compose data."""
        if not self.compose_config:
            return None
        # ... (implementation from previous version is fine) ...
        try:
            service_data = self.compose_config.get("services", {}).get(service_name)
            if not service_data:
                self.log.debug(f"Service '{service_name}' not found in compose config.")
                return None

            environment = service_data.get("environment")
            if not environment:
                self.log.debug(
                    f"No 'environment' section found for service '{service_name}'."
                )
                return None

            if isinstance(environment, dict):
                return environment.get(env_var_name)
            elif isinstance(environment, list):
                pattern = re.compile(rf"^{re.escape(env_var_name)}(?:=(.*))?$")
                for item in environment:
                    match = pattern.match(item)
                    if match:
                        return match.group(1) if match.group(1) is not None else ""
                return None
            else:
                self.log.warning(
                    f"Unexpected format for 'environment' in service '{service_name}': {type(environment)}"
                )
                return None
        except Exception as e:
            self.log.error(
                f"Error accessing compose env for {service_name}/{env_var_name}: {e}"
            )
            return None

    def _get_host_port_from_compose_service(self, service_name, container_port):
        """Finds the host port mapped to a specific container port for a service."""
        if not self.compose_config:
            return None
        try:
            service_data = self.compose_config.get("services", {}).get(service_name)
            if not service_data:
                return None
            ports = service_data.get("ports", [])
            if not ports:
                return None

            container_port_str = str(container_port)  # Ensure string comparison

            for port_mapping in ports:
                # Format examples: "host:container", "container", "ip:host:container"
                parts = str(port_mapping).split(":")
                if len(parts) == 1:
                    # Only container port specified (e.g., "3000") - no host mapping
                    continue
                elif len(parts) == 2:
                    # "host:container" format
                    host_port, cont_port = parts
                    if cont_port == container_port_str:
                        self.log.debug(
                            f"Found host port mapping: {host_port}:{cont_port} for service {service_name}"
                        )
                        return host_port.strip()
                elif len(parts) == 3:
                    # "ip:host:container" format
                    _, host_port, cont_port = parts
                    if cont_port == container_port_str:
                        self.log.debug(
                            f"Found host port mapping: {host_port}:{cont_port} (with IP) for service {service_name}"
                        )
                        return host_port.strip()

            self.log.debug(
                f"No host port found mapped to container port {container_port_str} for service {service_name}"
            )
            return None
        except Exception as e:
            self.log.error(f"Error parsing ports for service {service_name}: {e}")
            return None

    def _generate_dot_env_file(self):
        """
        Generates the .env file based on compose, defaults, and generated values,
        including constructing database URLs and formatting according to _ENV_STRUCTURE.
        """
        self.log.info(f"Generating '{self._ENV_FILE}'...")
        env_values = {}
        generation_log = {}  # Use dict for easier checking {key: comment}

        # 1. Populate from docker-compose environment sections based on mapping
        for env_key, (service_name, compose_key) in self._COMPOSE_ENV_MAPPING.items():
            value = self._get_env_from_compose_service(service_name, compose_key)
            if value is not None:
                env_values[env_key] = str(value)
                generation_log[env_key] = (
                    f"Value sourced from {self._DOCKER_COMPOSE_FILE} ({service_name}/{compose_key})"
                )
            # else: Value not found, will try defaults/generation later

        # 2. Fill in missing values with defaults, respecting already found values
        for key, default_value in self._DEFAULT_VALUES.items():
            if key not in env_values:
                env_values[key] = default_value
                generation_log[key] = "Using default value"

        # 3. Generate required secrets if not already set (e.g., from compose or defaults)
        for key in self._GENERATED_SECRETS:
            if key not in env_values:
                env_values[key] = secrets.token_hex(16 if key == "API_KEY" else 32)
                generation_log[key] = "Generated new secret value"

        # 4. Generate Tool IDs if not already set
        for key in self._GENERATED_TOOL_IDS:
            if key not in env_values:
                env_values[key] = (
                    f"tool_{secrets.token_hex(10)}"  # Made slightly longer
                )
                generation_log[key] = "Generated new tool ID"

        # --- 5. Construct Composite Database URLs ---
        db_user = env_values.get("MYSQL_USER")
        db_pass = env_values.get("MYSQL_PASSWORD")
        db_host = env_values.get(
            "MYSQL_HOST", DEFAULT_DB_SERVICE_NAME
        )  # Use default service name if host missing
        db_port = env_values.get(
            "MYSQL_PORT", DEFAULT_DB_CONTAINER_PORT
        )  # Use default port if missing
        db_name = env_values.get("MYSQL_DATABASE")

        if all(
            [db_user, db_pass is not None, db_host, db_port, db_name]
        ):  # Check all components exist
            # Escape password for URL
            escaped_pass = quote_plus(str(db_pass))
            env_values["DATABASE_URL"] = (
                f"mysql+pymysql://{db_user}:{escaped_pass}@{db_host}:{db_port}/{db_name}"
            )
            generation_log["DATABASE_URL"] = "Constructed from DB components"

            # Construct SPECIAL_DB_URL using host port mapping
            host_db_port = self._get_host_port_from_compose_service(
                DEFAULT_DB_SERVICE_NAME, DEFAULT_DB_CONTAINER_PORT
            )
            if host_db_port:
                env_values["SPECIAL_DB_URL"] = (
                    f"mysql+pymysql://{db_user}:{escaped_pass}@localhost:{host_db_port}/{db_name}"
                )
                generation_log["SPECIAL_DB_URL"] = (
                    f"Constructed using host port ({host_db_port}) from compose"
                )
            else:
                log.warning(
                    f"Could not find host port mapped to {DEFAULT_DB_CONTAINER_PORT} for service '{DEFAULT_DB_SERVICE_NAME}'. Cannot generate SPECIAL_DB_URL."
                )
                generation_log["SPECIAL_DB_URL"] = (
                    "Skipped: Could not find host port mapping in compose"
                )
                # Optionally set a placeholder or omit the key entirely
                # env_values['SPECIAL_DB_URL'] = "# NOT_CONFIGURED"
        else:
            log.warning(
                "Missing one or more database components (user, password, host, port, name). Cannot construct DATABASE_URL/SPECIAL_DB_URL."
            )
            generation_log["DATABASE_URL"] = "Skipped: Missing DB components"
            generation_log["SPECIAL_DB_URL"] = "Skipped: Missing DB components"

        # --- 6. Format the output .env file ---
        env_lines = [f"# Auto-generated .env file by {os.path.basename(__file__)}", ""]
        processed_keys = set()

        for section_name, keys_in_section in self._ENV_STRUCTURE.items():
            env_lines.append(f"#############################")
            env_lines.append(f"# {section_name}")
            env_lines.append(f"#############################")
            found_key_in_section = False
            for key in keys_in_section:
                if key in env_values:
                    value = env_values[key]
                    comment = generation_log.get(key, "Source unknown")
                    # Basic quoting logic
                    if any(c in value for c in [" ", "#", "="]):
                        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
                        env_lines.append(f'{key}="{escaped_value}" # {comment}')
                    else:
                        env_lines.append(f"{key}={value} # {comment}")
                    processed_keys.add(key)
                    found_key_in_section = True
                # else: Key defined in structure but not found in generated values - skip silently
            if not found_key_in_section:
                env_lines.append(
                    f"# (No variables configured for this section)"
                )  # Indicate empty section
            env_lines.append("")  # Add blank line after section

        # Add any remaining keys that were generated but not in the defined structure
        remaining_keys = sorted(list(set(env_values.keys()) - processed_keys))
        if remaining_keys:
            env_lines.append(f"#############################")
            env_lines.append(f"# Other (Uncategorized)")
            env_lines.append(f"#############################")
            for key in remaining_keys:
                value = env_values[key]
                comment = generation_log.get(key, "Source unknown")
                if any(c in value for c in [" ", "#", "="]):
                    escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
                    env_lines.append(f'{key}="{escaped_value}" # {comment}')
                else:
                    env_lines.append(f"{key}={value} # {comment}")
            env_lines.append("")

        content = "\n".join(env_lines)

        try:
            with open(self._ENV_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            self.log.info(f"Successfully generated '{self._ENV_FILE}'.")
            if self.args.verbose:
                self.log.debug(
                    f"Generated {self._ENV_FILE} content:\n---\n{content}\n---"
                )
        except IOError as e:
            self.log.error(f"Failed to write generated {self._ENV_FILE}: {e}")
            sys.exit(1)

    def _check_for_required_env_file(self):
        """Checks if the actual .env file exists; if not, generates it."""
        self.log.debug(f"[ENV SCAN] Checking for required '{self._ENV_FILE}' file...")
        if not os.path.exists(self._ENV_FILE):
            self.log.warning(
                f"[ENV SCAN] Required environment file '{self._ENV_FILE}' is missing."
            )
            self._generate_dot_env_file()  # Generate using the new logic
        else:
            self.log.info(
                f"[ENV SCAN] Required environment file '{self._ENV_FILE}' exists. NOT overwriting."
            )
            # Optionally load it if needed by other parts of the script immediately
            # load_dotenv(dotenv_path=self._ENV_FILE)
            # self.log.debug(f"Loaded existing environment variables from '{self._ENV_FILE}'.")

    # --- Shared Path Configuration ---
    # ... (no changes needed) ...
    def _configure_shared_path(self):
        system = platform.system().lower()
        shared_path_env = os.environ.get("SHARED_PATH")
        if shared_path_env:
            shared_path = shared_path_env
            self.log.info(
                "Using existing SHARED_PATH from environment: %s", shared_path
            )
        else:
            default_base = os.path.expanduser("~")
            if system == "windows":
                shared_path = os.path.join(default_base, "entities_share")
            elif system == "linux":
                shared_path = os.path.join(
                    default_base, ".local", "share", "entities_share"
                )
            elif system == "darwin":
                shared_path = os.path.join(
                    default_base, "Library", "Application Support", "entities_share"
                )
            else:
                self.log.error(
                    "Unsupported OS: %s. Cannot set default SHARED_PATH.", system
                )
                raise RuntimeError("Unsupported OS")
            self.log.info("Defaulting SHARED_PATH to: %s", shared_path)
            # Set it in the current process environment so compose can potentially pick it up if needed
            os.environ["SHARED_PATH"] = shared_path
        try:
            Path(shared_path).mkdir(parents=True, exist_ok=True)
            self.log.info("Ensured shared directory exists: %s", shared_path)
        except OSError as e:
            self.log.error(
                f"Failed to create shared directory {shared_path}: {e}. Check permissions."
            )

    # --- Ollama Integration ---
    # ... (no changes needed) ...
    def _has_docker(self):
        return shutil.which("docker") is not None

    def _is_container_running(self, container_name):
        try:
            result = self._run_command(
                ["docker", "ps", "--filter", f"name=^{container_name}$", "--quiet"],
                capture_output=True,
                text=True,
                check=False,
                suppress_logs=True,
            )
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(
                f"Could not check container '{container_name}' status: {e}"
            )
            return False

    def _is_image_present(self, image_name):
        try:
            result = self._run_command(
                ["docker", "images", image_name, "--quiet"],
                capture_output=True,
                text=True,
                check=False,
                suppress_logs=True,
            )
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(f"Could not check image '{image_name}' presence: {e}")
            return False

    def _has_nvidia_support(self):
        has_smi = shutil.which("nvidia-smi") is not None
        if has_smi:
            try:
                self._run_command(
                    ["nvidia-smi"], check=True, capture_output=True, suppress_logs=True
                )
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                self.log.debug(
                    "nvidia-smi command failed or not found. Assuming no NVIDIA GPU available via Docker."
                )
                return False
        return False

    def _start_ollama(self, cpu_only=True):
        # ... (no changes needed) ...
        if not self._has_docker():
            self.log.error("❌ Docker command not found. Cannot start external Ollama.")
            return False
        container_name = self._OLLAMA_CONTAINER
        if self._is_container_running(container_name):
            self.log.info(
                f"✅ External Ollama container '{container_name}' is already running."
            )
            return True
        image_name = self._OLLAMA_IMAGE
        if not self._is_image_present(image_name):
            self.log.info(f"📦 Pulling Ollama image '{image_name}'...")
            try:
                self._run_command(["docker", "pull", image_name], check=True)
            except Exception as e:
                self.log.error(f"❌ Failed to pull Ollama image '{image_name}': {e}")
                return False
        self.log.info(f"🚀 Starting external Ollama container '{container_name}'...")
        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "-v",
            "ollama:/root/.ollama",
            "-p",
            f"{self._OLLAMA_PORT}:{self._OLLAMA_PORT}",
            "--name",
            container_name,
        ]
        if not cpu_only and self._has_nvidia_support():
            self.log.info(
                "   Attempting to add --gpus=all flag for NVIDIA GPU support."
            )
            cmd.insert(2, "--gpus=all")  # Insert after 'run'
        elif not cpu_only:
            self.log.warning(
                "   GPU requested but NVIDIA support check failed or OS incompatible. Starting in CPU mode."
            )
        cmd.append(image_name)  # Add image name at the end
        try:
            self._run_command(cmd, check=True)
            self.log.info(f"   Waiting briefly for '{container_name}' to initialize...")
            time.sleep(3)  # Give container a moment
            if self._is_container_running(container_name):
                self.log.info(
                    f"✅ External Ollama container '{container_name}' started successfully."
                )
                return True
            else:
                self.log.error(
                    f"❌ External Ollama container '{container_name}' failed to start or exited quickly. Checking logs..."
                )
                try:
                    self._run_command(
                        ["docker", "logs", container_name],
                        check=False,
                        suppress_logs=False,
                    )
                except Exception as log_err:
                    self.log.error(
                        f"Could not retrieve logs for '{container_name}': {log_err}"
                    )
                return False
        except Exception as e:
            self.log.error(f"❌ Failed to execute docker run command for Ollama: {e}")
            return False

    def _ensure_ollama(self, opt_in=False, use_gpu=False):
        # ... (no changes needed) ...
        if not opt_in:
            self.log.info(
                "ℹ️ External Ollama management not requested via --with-ollama. Skipping."
            )
            return True

        self.log.info("--- External Ollama Setup ---")
        if os.path.exists("/.dockerenv") or os.environ.get("DOCKER_HOST"):
            self.log.warning(
                "🛰 Running inside a container or connected to remote Docker daemon. Skipping external Ollama management."
            )
            return True
        if platform.system() == "Darwin":
            self.log.warning(
                "⚠️ macOS detected. GPU passthrough for Docker Desktop is limited/experimental. Native Ollama app recommended for GPU."
            )
            # Continue with CPU Docker Ollama attempt, but warn.
            # use_gpu = False # Force CPU on Mac? Or let it try? Let's let it try for now.

        if not self._has_docker():
            self.log.error(
                "❌ Docker command not found. Cannot manage external Ollama container."
            )
            return False

        gpu_available = self._has_nvidia_support()
        attempt_gpu = use_gpu and gpu_available
        mode_str = "GPU" if attempt_gpu else "CPU"

        if use_gpu and not gpu_available and platform.system() != "Darwin":
            self.log.warning(
                "⚠️ GPU mode requested (--ollama-gpu), but NVIDIA support check failed. Proceeding in CPU mode."
            )

        self.log.info(
            f"Attempting to start external Ollama container in {mode_str} mode..."
        )
        success = self._start_ollama(cpu_only=not attempt_gpu)
        self.log.info("--- End External Ollama Setup ---")
        return success

    # --- Docker Cache Diagnostics ---
    # ... (no changes needed) ...
    def _get_directory_size(self, path="."):
        # ... (implementation from previous version) ...
        total_size = 0
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                try:
                    fp = os.path.join(dirpath, f)
                    # Check if it's a file and not a symbolic link before getting size
                    if Path(fp).is_file() and not islink(fp):
                        total_size += getsize(fp)
                except OSError as e:
                    self.log.debug("Could not get size for %s: %s", fp, e)
                except Exception as e:
                    self.log.warning("Unexpected error getting size for %s: %s", fp, e)
        return total_size / (1024 * 1024)  # Return size in MB

    def _run_docker_cache_diagnostics(self):
        # ... (implementation from previous version) ...
        self.log.info("--- Docker Cache Diagnostics ---")
        try:
            context_size_mb = self._get_directory_size()
            self.log.info("Approximate build context size: %.2f MB", context_size_mb)
            if context_size_mb > 500:  # Example threshold
                self.log.warning(
                    "Context size is large (> 500MB). Review .dockerignore for unnecessary files."
                )

            self.log.info("Inspecting services defined in docker-compose.yml...")
            ps_config = self._run_command(
                ["docker", "compose", "config", "--services"],
                capture_output=True,
                text=True,
                check=False,
                suppress_logs=True,
            )
            if ps_config.returncode != 0 or not ps_config.stdout.strip():
                self.log.warning(
                    "Could not reliably get services from 'docker compose config'. Diagnostics limited."
                )
                services = []
            else:
                services = ps_config.stdout.strip().splitlines()
                self.log.info("Services found: %s", ", ".join(services))

            if services:
                self.log.info(
                    "Checking potential image history (using service names as guess)..."
                )
                for service in services:
                    image_name_guess = service
                    self.log.info(
                        f"--- History for potential image '{image_name_guess}' ---"
                    )
                    try:
                        history_cmd = [
                            "docker",
                            "history",
                            image_name_guess,
                            "--no-trunc",
                            "--format",
                            '{{.ID}}: {{.Size | printf "%-10s"}} {{.CreatedBy}}',
                        ]
                        history = self._run_command(
                            history_cmd,
                            check=False,
                            capture_output=True,
                            text=True,
                            suppress_logs=True,
                        )
                        if history.returncode == 0 and history.stdout.strip():
                            self.log.info("History:\n%s", history.stdout.strip())
                        elif history.returncode == 0:
                            self.log.info(
                                "No history found (image might not exist locally with this name)."
                            )
                        else:
                            log_func = (
                                self.log.warning
                                if "No such image" in history.stderr
                                else self.log.error
                            )
                            log_func(
                                f"Could not get history for '{image_name_guess}'. Error:\n{history.stderr.strip()}"
                            )
                    except Exception as e:
                        self.log.error(
                            f"Error running docker history for '{image_name_guess}': {e}"
                        )
            else:
                self.log.info("Skipping image history check.")

        except Exception as e:
            self.log.error(
                "An error occurred during Docker cache diagnostics: %s",
                e,
                exc_info=self.args.verbose,
            )
        finally:
            self.log.info("--- End Docker Cache Diagnostics ---")

    # --- Docker Compose Actions ---
    # ... (no significant changes needed in build/up/down/nuke/tag logic itself) ...
    def _handle_nuke(self):
        # ... (implementation from previous version) ...
        self.log.warning("!!! NUKE MODE ACTIVATED !!!")
        self.log.warning(
            "This will: 1) Stop/remove this project's containers/volumes. 2) Prune ALL unused Docker data on your system (containers, networks, images, build cache, VOLUMES)."
        )
        try:
            confirm = input("Type 'confirm nuke' to proceed: ")
        except EOFError:
            self.log.error("Nuke requires interactive confirmation. Aborting.")
            sys.exit(1)

        if confirm != "confirm nuke":
            self.log.info("Nuke operation cancelled.")
            sys.exit(0)

        self.log.info("Proceeding with Docker nuke...")
        self.log.info("Step 1: Bringing down compose stack...")
        try:
            self._run_command(
                ["docker", "compose", "down", "--volumes", "--remove-orphans"],
                check=False,
            )
        except Exception as e:
            self.log.warning(
                f"Error during 'docker compose down': {e}. Continuing nuke."
            )

        self.log.warning("Step 2: Pruning ALL Docker system resources...")
        try:
            self._run_command(
                ["docker", "system", "prune", "-a", "--volumes", "--force"], check=True
            )
        except Exception as e:
            self.log.critical(f"Critical error during 'docker system prune': {e}")
            sys.exit(1)

        self.log.info("Docker environment nuke completed.")

    def _handle_down(self):
        # ... (implementation from previous version) ...
        target_services = self.args.services or []
        target_desc = (
            f" for services: {', '.join(target_services)}"
            if target_services
            else " for all services in this project"
        )
        action = (
            "Stopping containers & removing associated volumes"
            if self.args.clear_volumes
            else "Stopping containers"
        )
        self.log.info(f"{action}{target_desc}...")

        if self.args.clear_volumes:
            prompt_msg = f"Remove volumes associated with{' these services' if target_services else ' ALL services'}? (yes/no): "
            try:
                confirm = input(prompt_msg).lower().strip()
            except EOFError:
                self.log.error("Confirmation required for volume deletion. Aborting.")
                sys.exit(1)
            if confirm != "yes":
                self.log.info(
                    "Volume deletion cancelled. Proceeding to stop containers only."
                )
                self.args.clear_volumes = False
            elif target_services:
                self.log.warning(
                    "Note: --clear-volumes with specific services might not remove anonymously shared volumes."
                )

        down_cmd = ["docker", "compose", "down"]
        if self.args.clear_volumes:
            down_cmd.append("--volumes")
        down_cmd.append("--remove-orphans")
        if target_services:
            down_cmd.extend(target_services)
        try:
            self._run_command(down_cmd, check=False)
            final_action = (
                "Stopping containers & removing volumes"
                if self.args.clear_volumes
                else "Stopping containers"
            )
            self.log.info(f"{final_action} command completed.")
        except Exception as e:
            self.log.error(f"Error during 'docker compose down': {e}")

    def _handle_build(self):
        # ... (implementation from previous version) ...
        target_services = self.args.services or []
        target_desc = (
            f" for services: {', '.join(target_services)}"
            if target_services
            else " all services"
        )
        cache_desc = " (using --no-cache)" if self.args.no_cache else ""
        parallel_desc = " (using --parallel)" if self.args.parallel else ""
        self.log.info(f"Building images{target_desc}{cache_desc}{parallel_desc}...")

        build_cmd = ["docker", "compose", "build"]
        if self.args.no_cache:
            build_cmd.append("--no-cache")
        if self.args.parallel:
            build_cmd.append("--parallel")
        if target_services:
            build_cmd.extend(target_services)

        t_start = time.time()
        try:
            self._run_command(build_cmd, check=True)
            t_end = time.time()
            self.log.info(
                "Build completed successfully in %.2f seconds.", t_end - t_start
            )
            if self.args.tag:
                self.log.info(f"Applying tag '{self.args.tag}'...")
                self._tag_images(self.args.tag, targeted_services=target_services)
        except Exception as e:
            self.log.critical(f"Docker build failed: {e}", exc_info=self.args.verbose)
            sys.exit(1)

    def _tag_images(self, tag, targeted_services=None):
        # ... (implementation from previous version) ...
        if not tag:
            return
        self.log.info(f"Attempting to tag images with tag: '{tag}'")
        try:
            config_json_output = self._run_command(
                ["docker", "compose", "config", "--format", "json"],
                capture_output=True,
                check=True,
                text=True,
                suppress_logs=True,
            ).stdout
            compose_config = json.loads(config_json_output)
            services = compose_config.get("services", {})
            if not services:
                self.log.warning("No services found in compose config. Cannot tag.")
                return

            tagged_count, skipped_count = 0, 0
            for service_name, service_config in services.items():
                if targeted_services and service_name not in targeted_services:
                    continue
                image_name = service_config.get("image")
                if not image_name:
                    self.log.debug(
                        f"Skipping service '{service_name}': No explicit 'image:' name defined."
                    )
                    skipped_count += 1
                    continue

                base_image = image_name.split(":")[0]
                source_tag_options = [image_name] if ":" in image_name else []
                source_tag_options.append(f"{base_image}:latest")

                source_image_ref = None
                for option in source_tag_options:
                    inspect_res = self._run_command(
                        ["docker", "image", "inspect", option],
                        check=False,
                        capture_output=True,
                        suppress_logs=True,
                    )
                    if inspect_res.returncode == 0:
                        source_image_ref = option
                        break

                if not source_image_ref:
                    self.log.warning(
                        f"Skipping tag for service '{service_name}': Could not find built source image matching '{source_tag_options}'."
                    )
                    skipped_count += 1
                    continue

                new_image_tag = f"{base_image}:{tag}"
                self.log.info(f"Tagging: {source_image_ref} -> {new_image_tag}")
                try:
                    self._run_command(
                        ["docker", "tag", source_image_ref, new_image_tag], check=True
                    )
                    tagged_count += 1
                except Exception as tag_e:
                    self.log.error(f"Failed to tag {source_image_ref}: {tag_e}")

            self.log.info(
                f"Tagging complete. {tagged_count} tagged, {skipped_count} skipped."
            )
        except Exception as e:
            self.log.error(f"Error during tagging: {e}", exc_info=self.args.verbose)

    def _handle_up(self):
        # ... (implementation from previous version) ...
        if not os.path.exists(self._ENV_FILE):
            self.log.error(
                f"Required environment file '{self._ENV_FILE}' is missing. Generate it first."
            )
            sys.exit(1)
        self.log.debug(f"Verified '{self._ENV_FILE}' exists.")

        mode = "attached" if self.args.attached else "detached (-d)"
        target_services = self.args.services or []
        target_desc = (
            f" for services: {', '.join(target_services)}"
            if target_services
            else " all services"
        )
        build_opt = " (with --build)" if self.args.build_before_up else ""
        force_recreate_opt = (
            " (with --force-recreate)" if self.args.force_recreate else ""
        )
        self.log.info(
            f"Starting containers{target_desc} in {mode} mode{build_opt}{force_recreate_opt}..."
        )

        up_cmd = ["docker", "compose", "up"]
        if not self.args.attached:
            up_cmd.append("-d")
        if self.args.build_before_up:
            up_cmd.append("--build")
        if self.args.force_recreate:
            up_cmd.append("--force-recreate")
        if target_services:
            up_cmd.extend(target_services)

        try:
            self._run_command(up_cmd, check=True)
            self.log.info("Containers started successfully.")
            if not self.args.attached:
                logs_cmd_base = ["docker", "compose", "logs", "-f", "--tail=50"]
                if target_services:
                    logs_cmd_base.extend(target_services)
                self.log.info(f"View logs: {' '.join(logs_cmd_base)}")
        except subprocess.CalledProcessError as e:
            self.log.critical(f"'docker compose up' failed (Code: {e.returncode}).")
            self.log.info("Attempting to show logs...")
            try:
                logs_cmd_fail = ["docker", "compose", "logs", "--tail=100"]
                if target_services:
                    logs_cmd_fail.extend(target_services)
                self._run_command(logs_cmd_fail, check=False, suppress_logs=False)
            except Exception as log_e:
                self.log.error(f"Could not fetch logs: {log_e}")
            sys.exit(1)
        except Exception as e:
            self.log.critical(
                f"Unexpected error during 'up': {e}", exc_info=self.args.verbose
            )
            sys.exit(1)

    def run(self):
        """Main execution logic based on parsed arguments."""
        # ... (implementation from previous version - validation logic is in parse_args now) ...
        if self.args.debug_cache:
            self._run_docker_cache_diagnostics()
            sys.exit(0)
        if self.args.nuke:
            self._handle_nuke()
            sys.exit(0)  # Nuke exits itself

        # Handle Ollama setup if requested
        if self.args.with_ollama:
            ollama_ok = self._ensure_ollama(opt_in=True, use_gpu=self.args.ollama_gpu)
            if not ollama_ok:
                self.log.warning(
                    "External Ollama setup failed or skipped. Continuing..."
                )

        mode = self.args.mode

        # Down action (if requested)
        if self.args.down or self.args.clear_volumes:  # Down flag checked directly now
            self._handle_down()
            if mode == "down_only":
                sys.exit(0)

        # Build action
        if mode in ["build", "both"]:
            self._handle_build()
            if mode == "build":
                sys.exit(0)

        # Up action
        if mode in ["up", "both"]:
            self._handle_up()

        self.log.info("Docker management script finished.")

    @staticmethod
    def parse_args():
        """Parses command-line arguments with validation."""
        # ... (using the improved parser from the previous version) ...
        parser = argparse.ArgumentParser(
            description="Manage Docker Compose stack: build, run, setup .env, and optionally manage external Ollama.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        # Core Actions
        parser.add_argument(
            "--mode",
            choices=["up", "build", "both", "down_only"],
            default="up",
            help="Primary action",
        )
        parser.add_argument(
            "--services",
            nargs="+",
            metavar="SERVICE",
            help="Target specific service(s)",
        )
        # Build Options
        parser.add_argument(
            "--no-cache", action="store_true", help="Build without cache"
        )
        parser.add_argument(
            "--parallel", action="store_true", help="Build images in parallel"
        )
        parser.add_argument("--tag", type=str, metavar="TAG", help="Tag built image(s)")
        # Up Options
        parser.add_argument("--attached", action="store_true", help="Run 'up' attached")
        parser.add_argument(
            "--build-before-up",
            "--build",
            dest="build_before_up",
            action="store_true",
            help="Run 'up --build'",
        )
        parser.add_argument(
            "--force-recreate", action="store_true", help="Run 'up --force-recreate'"
        )
        # Down/Cleanup Options
        parser.add_argument(
            "--down", action="store_true", help="Run 'down' before other actions"
        )
        parser.add_argument(
            "--clear-volumes",
            "-v",
            action="store_true",
            help="With --down, remove volumes (prompts)",
        )
        parser.add_argument(
            "--nuke", action="store_true", help="DANGER: Prune ALL Docker resources!"
        )
        # Ollama Management
        parser.add_argument(
            "--with-ollama",
            action="store_true",
            help="Manage external Ollama container",
        )
        parser.add_argument(
            "--ollama-gpu", action="store_true", help="Attempt GPU for external Ollama"
        )
        # Utility/Debugging
        parser.add_argument(
            "--verbose",
            "--debug",
            dest="verbose",
            action="store_true",
            help="Enable debug logging",
        )
        parser.add_argument(
            "--debug-cache", action="store_true", help="Run cache diagnostics and exit"
        )

        args = parser.parse_args()

        # --- Argument Validation and Implied Actions ---
        if args.clear_volumes:
            args.down = True
        if (
            args.down
            and args.mode == "up"
            and not (
                args.build_before_up
                or args.tag
                or args.no_cache
                or args.parallel
                or args.attached
                or args.force_recreate
            )
        ):
            args.mode = "down_only"
            log.debug("Implied mode 'down_only' from --down/--clear-volumes flags.")
        build_flags_set = args.tag or args.no_cache or args.parallel
        if build_flags_set and args.mode == "up" and not args.build_before_up:
            log.warning(
                f"Build flags used with --mode=up without --build-before-up/--build. Build flags ignored unless build step occurs."
            )
        if args.build_before_up and args.mode in ["build", "down_only"]:
            parser.error(f"--build-before-up flag is invalid with --mode={args.mode}")
        if args.nuke and (
            args.mode != "up"
            or args.down
            or args.clear_volumes
            or build_flags_set
            or args.with_ollama
        ):
            log.debug(
                "--nuke is exclusive. Other mode/build/down/ollama flags ignored."
            )
        if args.debug_cache and (
            args.mode != "up"
            or args.down
            or args.clear_volumes
            or build_flags_set
            or args.with_ollama
            or args.nuke
        ):
            log.debug("--debug-cache is exclusive. Other flags ignored.")

        return args


# --- Main Execution ---
if __name__ == "__main__":
    manager = None
    try:
        arguments = DockerManager.parse_args()
        if arguments.verbose:
            log.setLevel(logging.DEBUG)
        log.debug("Parsed arguments: %s", arguments)

        manager = DockerManager(arguments)
        manager.run()

    except KeyboardInterrupt:
        log.info("\nOperation cancelled by user.")
        sys.exit(130)
    except subprocess.CalledProcessError as e:
        log.critical(f"Command failed (Return Code: {e.returncode}).")
        sys.exit(e.returncode or 1)
    except FileNotFoundError as e:
        log.critical(f"Required command or file not found: {e}")
        sys.exit(1)
    except Exception as e:
        log.critical(
            "An unexpected error occurred: %s", e, exc_info=log.level == logging.DEBUG
        )
        sys.exit(1)
