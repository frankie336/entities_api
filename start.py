#!/usr/bin/env python3
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
from pathlib import Path
from urllib.parse import quote_plus

from scripts.generate_docker_compose import generate_dev_docker_compose

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
    _DOCKER_COMPOSE_FILE = (
        "docker-compose.yml"  # Updated to read the generated file in the project root
    )

    _OLLAMA_IMAGE = "ollama/ollama"
    _OLLAMA_CONTAINER = "ollama"
    _OLLAMA_PORT = "11434"

    # Mapping: .env key -> (docker-compose service name, compose env var name)
    # Define which INDIVIDUAL .env vars should primarily come from the docker-compose.yml environment section.
    _COMPOSE_ENV_MAPPING = {
        # --- Database Components (Source these first) ---
        "MYSQL_ROOT_PASSWORD": (DEFAULT_DB_SERVICE_NAME, "MYSQL_ROOT_PASSWORD"),
        "MYSQL_DATABASE": (DEFAULT_DB_SERVICE_NAME, "MYSQL_DATABASE"),
        "MYSQL_USER": (DEFAULT_DB_SERVICE_NAME, "MYSQL_USER"),
        "MYSQL_PASSWORD": (DEFAULT_DB_SERVICE_NAME, "MYSQL_PASSWORD"),
        # --- Other secrets/configs potentially defined directly in compose env: ---
        "SMBCLIENT_SERVER": ("fastapi_cosmic_catalyst", "SMBCLIENT_SERVER"),
        "SMBCLIENT_SHARE": ("fastapi_cosmic_catalyst", "SMBCLIENT_SHARE"),
        "SMBCLIENT_USERNAME": ("fastapi_cosmic_catalyst", "SMBCLIENT_USERNAME"),
        "SMBCLIENT_PASSWORD": ("fastapi_cosmic_catalyst", "SMBCLIENT_PASSWORD"),
        "SMBCLIENT_PORT": ("fastapi_cosmic_catalyst", "SMBCLIENT_PORT"),
        # NEW → automatically pick up the flag we just added in compose
        "AUTO_MIGRATE": ("fastapi_cosmic_catalyst", "AUTO_MIGRATE"),
        "DISABLE_FIREJAIL": ("sandbox_api", "DISABLE_FIREJAIL"),
    }

    # Define keys that should always be generated using the secrets module if not found elsewhere.
    # These will overwrite any values sourced from compose if they exist.
    _GENERATED_SECRETS = [
        "SIGNED_URL_SECRET",
        "API_KEY",
        "MYSQL_ROOT_PASSWORD",  # Ensures this is always generated uniquely
        "MYSQL_PASSWORD",  # Ensures this is always generated uniquely
        "TOGETHER_API_KEY",
        "HYPERBOLIC_API_KEY",
        "ADMIN_API_KEY",
        "ENTITIES_API_KEY",
        "ENTITIES_USER_ID",
        "DEEP_SEEK_API_KEY",
        "SECRET_KEY",  # Ensure the FastAPI/Starlette secret key is unique
    ]

    # Define Tool IDs to be generated.
    _GENERATED_TOOL_IDS = [
        "TOOL_CODE_INTERPRETER",
        "TOOL_WEB_SEARCH",
        "TOOL_COMPUTER",
        "TOOL_VECTOR_STORE_SEARCH",
    ]

    # Define default values for keys if they aren't sourced from compose or generated.
    # Note: SECRET_KEY is removed from here as it's now in _GENERATED_SECRETS
    _DEFAULT_VALUES = {
        # --- Base URLs ---
        "ASSISTANTS_BASE_URL": "http://localhost:9000",
        "SANDBOX_SERVER_URL": "http://localhost:9000",
        "DOWNLOAD_BASE_URL": "http://localhost:9000/v1/files/download",
        "HYPERBOLIC_BASE_URL": "https://api.hyperbolic.xyz/v1",
        # --- Database Components Fallbacks (passwords are generated) ---
        "MYSQL_HOST": DEFAULT_DB_SERVICE_NAME,
        "MYSQL_PORT": DEFAULT_DB_CONTAINER_PORT,
        "MYSQL_DATABASE": "cosmic_catalyst",  # Default name, can be overridden by compose
        "MYSQL_USER": "ollama",  # Default user, can be overridden by compose
        # --- Alembic migration Settings ---
        "AUTO_MIGRATE": "1",
        # --- Platform Settings ---
        "BASE_URL_HEALTH": "http://localhost:9000/v1/health",
        "SHELL_SERVER_URL": "ws://sandbox_api:8000/ws/computer",
        "CODE_EXECUTION_URL": "ws://sandbox_api:8000/ws/execute",
        "DISABLE_FIREJAIL": "true",  # Default, can be overridden by compose
        "REDIS_URL": "redis://redis:6379/0",
        # --- SMB Client Fallbacks ---
        "SMBCLIENT_SERVER": "samba_server",  # Default, can be overridden by compose
        "SMBCLIENT_SHARE": "cosmic_share",  # Default, can be overridden by compose
        "SMBCLIENT_USERNAME": "samba_user",  # Default, can be overridden by compose
        "SMBCLIENT_PASSWORD": "default",  # Default, can be overridden by compose
        "SMBCLIENT_PORT": "445",  # Default, can be overridden by compose
        # --- Other Standard Vars ---
        "LOG_LEVEL": "INFO",
        "PYTHONUNBUFFERED": "1",
    }

    # Define the structure and order of the final .env file.
    _ENV_STRUCTURE = {
        "Base URLs": ["ASSISTANTS_BASE_URL", "SANDBOX_SERVER_URL", "DOWNLOAD_BASE_URL"],
        "Database Configuration": [
            "DATABASE_URL",
            "SPECIAL_DB_URL",
            "MYSQL_ROOT_PASSWORD",
            "MYSQL_DATABASE",
            "MYSQL_USER",
            "MYSQL_PASSWORD",
        ],
        "API Keys & External Services": [
            "API_KEY",
            "TOGETHER_API_KEY",
            "HYPERBOLIC_API_KEY",
            "ADMIN_API_KEY",
            "ENTITIES_API_KEY",
            "ENTITIES_USER_ID",
            "DEEP_SEEK_API_KEY",
        ],
        "Platform Settings": [
            "BASE_URL_HEALTH",
            "SHELL_SERVER_URL",
            "CODE_EXECUTION_URL",
            "SIGNED_URL_SECRET",
            "DISABLE_FIREJAIL",
            "SECRET_KEY",  # Moved here from defaults/generated
            "AUTO_MIGRATE",
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
        "Other": [
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

        self.compose_config = self._load_compose_config()  # Load compose config early.

        # Initial setup steps.
        self._check_for_required_env_file()  # Ensure .env exists (or generate it).
        self._configure_shared_path()
        self._ensure_dockerignore()

    def _run_command(
        self,
        cmd_list,
        check=True,
        capture_output=False,
        text=True,
        suppress_logs=False,
        **kwargs,
    ):
        """Runs shell commands using subprocess."""
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

    def _ensure_dockerignore(self):
        """Generates a default .dockerignore file if missing."""
        dockerignore = Path(".dockerignore")
        if not dockerignore.exists():
            self.log.warning(".dockerignore not found. Generating default...")
            dockerignore.write_text(
                "__pycache__/\n.venv/\nnode_modules/\n*.log\n*.pyc\n.git/\n.env*\n.env\n*.sqlite\ndist/\nbuild/\ncoverage/\ntmp/\n*.egg-info/\n"
            )
            self.log.info("Generated default .dockerignore.")

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
        """Extracts an environment variable's value from a specific service in the compose data."""
        if not self.compose_config:
            return None
        try:
            service_data = self.compose_config.get("services", {}).get(service_name)
            if not service_data:
                # self.log.debug(f"Service '{service_name}' not found in compose config.") # Too noisy
                return None

            environment = service_data.get("environment")
            if not environment:
                # self.log.debug(f"No 'environment' section found for service '{service_name}'.") # Too noisy
                return None

            if isinstance(environment, dict):
                return environment.get(env_var_name)
            elif isinstance(environment, list):
                pattern = re.compile(rf"^{re.escape(env_var_name)}(?:=(.*))?$")
                for item in environment:
                    match = pattern.match(item)
                    if match:
                        # Return the value part, or an empty string if only the key is present (e.g., "MY_VAR=")
                        return match.group(1) if match.group(1) is not None else ""
                return None  # Variable not found in the list
            else:
                self.log.warning(
                    f"Unexpected format for 'environment' in service '{service_name}': {type(environment)}"
                )
                return None
        except Exception as e:
            self.log.error(
                f"Error accessing compose env for {service_name}/{env_var_name}: {e}",
                exc_info=self.args.verbose,
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

            container_port_str = str(container_port)
            # Handle potential variations like "8000", "8000/tcp", "8000/udp"
            container_port_base = container_port_str.split("/")[0]

            for port_mapping in ports:
                # Format: "HOST:CONTAINER" or "IP:HOST:CONTAINER"
                parts = str(port_mapping).split(":")
                host_port = None
                cont_port_part = None

                if len(parts) == 1:  # e.g., "8000" -> implies host:8000, container:8000
                    if parts[0].split("/")[0] == container_port_base:
                        host_port = parts[0].split("/")[0]  # Use the same port for host
                        cont_port_part = parts[0]
                elif len(parts) == 2:  # e.g., "8080:80"
                    host_port = parts[0]
                    cont_port_part = parts[1]
                elif len(parts) == 3:  # e.g., "127.0.0.1:8080:80"
                    host_port = parts[1]
                    cont_port_part = parts[2]

                if host_port and cont_port_part:
                    cont_port_base_map = cont_port_part.split("/")[0]
                    if cont_port_base_map == container_port_base:
                        self.log.debug(
                            f"Found host port mapping: {host_port}:{cont_port_part} for service {service_name}"
                        )
                        return host_port.strip()

            self.log.debug(
                f"No host port found mapped to container port {container_port_str} for service {service_name}"
            )
            return None
        except Exception as e:
            self.log.error(
                f"Error parsing ports for service {service_name}: {e}",
                exc_info=self.args.verbose,
            )
            return None

    # --- .env Generation ---
    def _generate_dot_env_file(self):
        """Generates the .env file based on defaults, compose, and generated secrets."""
        self.log.info(f"Generating '{self._ENV_FILE}'...")
        env_values = {}
        generation_log = {}

        # Step 1: Start with default values
        for key, default_value in self._DEFAULT_VALUES.items():
            env_values[key] = default_value
            generation_log[key] = "Default value"
        self.log.debug(f"Initialized with {len(env_values)} default values.")

        # Step 2: Override defaults with values from docker-compose.yml environment sections
        # Only consider keys defined in _COMPOSE_ENV_MAPPING
        compose_overrides = 0
        for env_key, (service_name, compose_key) in self._COMPOSE_ENV_MAPPING.items():
            value = self._get_env_from_compose_service(service_name, compose_key)
            if value is not None and not value.startswith(
                "${"
            ):  # Ignore placeholders from compose for now
                original_value = env_values.get(env_key)
                env_values[env_key] = str(value)  # Ensure it's a string
                if original_value != value:
                    generation_log[env_key] = (
                        f"Value from {self._DOCKER_COMPOSE_FILE} ({service_name}/{compose_key})"
                    )
                    compose_overrides += 1
                else:
                    # Keep original log if value didn't change (e.g., default matched compose)
                    pass
            elif value is not None and value.startswith("${"):
                self.log.debug(
                    f"Ignoring placeholder '{value}' from compose for key '{env_key}' - will be generated if needed."
                )
        self.log.debug(
            f"Applied {compose_overrides} overrides from {self._DOCKER_COMPOSE_FILE}."
        )

        # Step 3: Force generation of REQUIRED secrets (overwrites defaults AND compose placeholders)
        secrets_generated = 0
        for key in self._GENERATED_SECRETS:
            # Special handling for API_KEY length, others default to 32 hex chars (64 length)
            token_length = 16 if key == "API_KEY" else 32
            new_secret = secrets.token_hex(token_length)
            # Always overwrite existing value for these keys
            env_values[key] = new_secret
            generation_log[key] = "Generated new secret (forced)"
            secrets_generated += 1
        self.log.debug(f"Generated/Forced {secrets_generated} required secrets.")

        # Step 4: Generate Tool IDs if they are still missing
        tool_ids_generated = 0
        for key in self._GENERATED_TOOL_IDS:
            if key not in env_values:
                env_values[key] = f"tool_{secrets.token_hex(10)}"
                generation_log[key] = "Generated new tool ID"
                tool_ids_generated += 1
        self.log.debug(f"Generated {tool_ids_generated} missing tool IDs.")

        # Step 5: Construct Composite DB URLs using the FINAL values
        db_user = env_values.get("MYSQL_USER")
        db_pass = env_values.get("MYSQL_PASSWORD")  # Should be the generated one now
        db_host = env_values.get("MYSQL_HOST", DEFAULT_DB_SERVICE_NAME)
        db_port = env_values.get("MYSQL_PORT", DEFAULT_DB_CONTAINER_PORT)
        db_name = env_values.get("MYSQL_DATABASE")

        if all([db_user, db_pass is not None, db_host, db_port, db_name]):
            try:
                escaped_pass = quote_plus(
                    str(db_pass)
                )  # Ensure password is URL encoded
                # Internal URL (container-to-container)
                env_values["DATABASE_URL"] = (
                    f"mysql+pymysql://{db_user}:{escaped_pass}@{db_host}:{db_port}/{db_name}"
                )
                generation_log["DATABASE_URL"] = (
                    "Constructed from DB components (for internal use)"
                )

                # External/Host URL (for accessing DB from host machine)
                host_db_port = self._get_host_port_from_compose_service(
                    DEFAULT_DB_SERVICE_NAME, DEFAULT_DB_CONTAINER_PORT
                )
                if host_db_port:
                    env_values["SPECIAL_DB_URL"] = (
                        f"mysql+pymysql://{db_user}:{escaped_pass}@localhost:{host_db_port}/{db_name}"
                    )
                    generation_log["SPECIAL_DB_URL"] = (
                        f"Constructed using host port ({host_db_port}) (for host access)"
                    )
                else:
                    log.warning(
                        f"Could not find host port mapping for DB service '{DEFAULT_DB_SERVICE_NAME}'. "
                        f"SPECIAL_DB_URL cannot be constructed."
                    )
                    if "SPECIAL_DB_URL" in env_values:
                        del env_values[
                            "SPECIAL_DB_URL"
                        ]  # Remove if present but cannot be built
                    generation_log["SPECIAL_DB_URL"] = "Skipped: Host port not found"
            except Exception as db_url_err:
                log.error(
                    f"Error constructing database URLs: {db_url_err}",
                    exc_info=self.args.verbose,
                )
                generation_log["DATABASE_URL"] = "Error during construction"
                generation_log["SPECIAL_DB_URL"] = "Error during construction"

        else:
            missing_db_parts = [
                k
                for k, v in {
                    "MYSQL_USER": db_user,
                    "MYSQL_PASSWORD": db_pass,
                    "MYSQL_HOST": db_host,
                    "MYSQL_PORT": db_port,
                    "MYSQL_DATABASE": db_name,
                }.items()
                if v is None
            ]
            log.warning(
                f"Missing one or more DB components ({', '.join(missing_db_parts)}); "
                f"skipping DATABASE_URL/SPECIAL_DB_URL construction."
            )
            if "DATABASE_URL" in env_values:
                del env_values["DATABASE_URL"]
            if "SPECIAL_DB_URL" in env_values:
                del env_values["SPECIAL_DB_URL"]
            generation_log["DATABASE_URL"] = "Skipped: Missing DB components"
            generation_log["SPECIAL_DB_URL"] = "Skipped: Missing DB components"

        # Step 6: Write the final values to the .env file, ordered by _ENV_STRUCTURE
        env_lines = [
            f"# Auto-generated .env file by {os.path.basename(__file__)} at {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            "",
        ]
        processed_keys = set()

        # Write structured sections
        for section_name, keys_in_section in self._ENV_STRUCTURE.items():
            env_lines.append(f"#############################")
            env_lines.append(f"# {section_name}")
            env_lines.append(f"#############################")
            found_in_section = False
            for key in keys_in_section:
                if key in env_values:
                    value = str(env_values[key])  # Ensure string conversion
                    # Quote if value contains spaces, '#', or '='
                    if any(c in value for c in [" ", "#", "="]):
                        # Basic quoting: escape backslashes and double quotes
                        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
                        env_lines.append(f'{key}="{escaped_value}"')
                    else:
                        env_lines.append(f"{key}={value}")
                    processed_keys.add(key)
                    found_in_section = True
            if not found_in_section:
                env_lines.append("# (No variables configured for this section)")
            env_lines.append("")  # Add blank line after section

        # Write any remaining keys (uncategorized)
        remaining_keys = sorted(list(set(env_values.keys()) - processed_keys))
        if remaining_keys:
            env_lines.append(f"#############################")
            env_lines.append(f"# Other (Uncategorized)")
            env_lines.append(f"#############################")
            for key in remaining_keys:
                value = str(env_values[key])
                if any(c in value for c in [" ", "#", "="]):
                    escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
                    env_lines.append(f'{key}="{escaped_value}"')
                else:
                    env_lines.append(f"{key}={value}")
                processed_keys.add(
                    key
                )  # Add to processed to avoid duplication if logic changes
            env_lines.append("")

        # Final content and write to file
        content = "\n".join(env_lines)
        try:
            with open(self._ENV_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            self.log.info(f"Successfully generated '{self._ENV_FILE}'.")
            if self.args.verbose:
                self.log.debug("--- .env Generation Sources ---")
                # Sort by key for consistent debug output
                for key in sorted(env_values.keys()):
                    source = generation_log.get(key, "Unknown source")
                    self.log.debug(f"  - {key}: {source}")
                self.log.debug("--- End .env Generation Sources ---")
                # Optionally log the generated content (can be verbose)
                # self.log.debug(f"Generated {self._ENV_FILE} content:\n---\n{content}\n---")
        except IOError as e:
            self.log.error(f"Failed to write {self._ENV_FILE}: {e}")
            sys.exit(1)

    def _check_for_required_env_file(self):
        """Checks if .env exists; if not, generates it."""
        self.log.debug(f"[ENV SCAN] Checking for '{self._ENV_FILE}' file...")
        if not os.path.exists(self._ENV_FILE):
            self.log.warning(f"[ENV SCAN] '{self._ENV_FILE}' missing. Generating...")
            self._generate_dot_env_file()
        else:
            self.log.info(
                f"[ENV SCAN] '{self._ENV_FILE}' exists. Loading existing values (generation logic only runs if file is missing)."
            )
            # Load existing .env file into environment variables for potential use by compose up
            load_dotenv(dotenv_path=self._ENV_FILE, override=True)

    def _configure_shared_path(self):
        system = platform.system().lower()
        shared_path = os.environ.get("SHARED_PATH")
        if shared_path:
            self.log.info("Using SHARED_PATH from env: %s", shared_path)
        else:
            default_base = os.path.expanduser("~")
            if system == "windows":
                shared_path = os.path.join(default_base, "entities_share")
            elif system == "linux":
                shared_path = os.path.join(
                    default_base, ".local", "share", "entities_share"
                )
            elif system == "darwin":  # macOS
                shared_path = os.path.join(
                    default_base, "Library", "Application Support", "entities_share"
                )
            else:
                self.log.warning(
                    "Unsupported OS: %s. Defaulting SHARED_PATH to './entities_share'",
                    system,
                )
                shared_path = os.path.abspath("./entities_share")

            self.log.info("Defaulting SHARED_PATH to: %s", shared_path)
            # Set it in the environment so subsequent processes (like docker-compose) can see it
            os.environ["SHARED_PATH"] = shared_path

        # Ensure the directory exists
        try:
            Path(shared_path).mkdir(parents=True, exist_ok=True)
            self.log.info("Ensured shared directory exists: %s", shared_path)
        except OSError as e:
            self.log.error("Failed to create shared directory %s: %s", shared_path, e)
            # Depending on requirements, you might want to exit here
            # sys.exit(1)

    def _has_docker(self):
        """Checks if the 'docker' command is available in the system PATH."""
        has_cmd = shutil.which("docker") is not None
        if not has_cmd:
            self.log.error("Docker command not found in PATH. Please install Docker.")
        return has_cmd

    def _is_container_running(self, container_name):
        """Checks if a container with the exact name is currently running."""
        if not self._has_docker():
            return False
        try:
            # Use exact name matching with anchors ^ and $
            cmd = [
                "docker",
                "ps",
                "--filter",
                f"name=^{container_name}$",
                "--format",
                "{{.Names}}",
            ]
            result = self._run_command(
                cmd,
                capture_output=True,
                text=True,
                check=False,  # Don't raise error if container not found
                suppress_logs=True,
            )
            # Check if the output exactly matches the container name
            return result.stdout.strip() == container_name
        except Exception as e:
            self.log.warning(
                "Could not check container '%s' status: %s",
                container_name,
                e,
                exc_info=self.args.verbose,
            )
            return False

    def _is_image_present(self, image_name):
        """Checks if a specific Docker image (including tag) is present locally."""
        if not self._has_docker():
            return False
        try:
            # Use --quiet to just get the image ID if present
            cmd = ["docker", "images", image_name, "--quiet"]
            result = self._run_command(
                cmd,
                capture_output=True,
                text=True,
                check=False,  # Don't raise error if image not found
                suppress_logs=True,
            )
            # If output is not empty, the image exists
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(
                "Could not check for image '%s': %s",
                image_name,
                e,
                exc_info=self.args.verbose,
            )
            return False

    def _has_nvidia_support(self):
        """Checks for NVIDIA GPU support by running nvidia-smi."""
        if platform.system() == "Windows":
            nvidia_smi_cmd = shutil.which("nvidia-smi.exe") or shutil.which(
                "nvidia-smi"
            )  # Check both .exe and no extension
        else:
            nvidia_smi_cmd = shutil.which("nvidia-smi")

        if nvidia_smi_cmd:
            self.log.debug(f"Found nvidia-smi at: {nvidia_smi_cmd}")
            try:
                # Run nvidia-smi, capture output, suppress logs unless verbose
                self._run_command(
                    [nvidia_smi_cmd],
                    check=True,
                    capture_output=True,
                    suppress_logs=not self.args.verbose,
                )
                self.log.debug(
                    "nvidia-smi executed successfully, NVIDIA support detected."
                )
                return True
            except subprocess.CalledProcessError as e:
                self.log.debug(
                    f"nvidia-smi failed (Return Code: {e.returncode}). Assuming no NVIDIA GPU support."
                )
                if self.args.verbose and e.stderr:
                    self.log.debug(f"nvidia-smi stderr:\n{e.stderr.strip()}")
                return False
            except FileNotFoundError:
                # Should be caught by shutil.which, but as a fallback
                self.log.debug(
                    "nvidia-smi command found by which but failed with FileNotFoundError."
                )
                return False
            except Exception as e:
                self.log.warning(
                    f"Unexpected error running nvidia-smi: {e}",
                    exc_info=self.args.verbose,
                )
                return False
        else:
            self.log.debug(
                "nvidia-smi command not found in PATH. Assuming no NVIDIA GPU support."
            )
            return False

    def _start_ollama(self, cpu_only=True):
        """Starts the external Ollama container."""
        if not self._has_docker():
            self.log.error("Docker command not found. Cannot start external Ollama.")
            return False

        container_name = self._OLLAMA_CONTAINER
        if self._is_container_running(container_name):
            self.log.info(
                "External Ollama container '%s' is already running.", container_name
            )
            return True

        image_name = self._OLLAMA_IMAGE
        if not self._is_image_present(image_name):
            self.log.info(
                "Pulling Ollama image '%s' (this may take a moment)...", image_name
            )
            try:
                # Run pull command without suppressing logs to show progress
                self._run_command(
                    ["docker", "pull", image_name], check=True, suppress_logs=False
                )
                self.log.info("Successfully pulled image '%s'.", image_name)
            except Exception as e:
                self.log.error(
                    "Failed to pull Ollama image '%s': %s",
                    image_name,
                    e,
                    exc_info=self.args.verbose,
                )
                return False

        self.log.info("Starting external Ollama container '%s'...", container_name)
        # Base command
        cmd = [
            "docker",
            "run",
            "-d",  # Run detached
            "--rm",  # Remove container when it exits
            "-v",
            "ollama:/root/.ollama",  # Persist models/data in a named volume
            "-p",
            f"{self._OLLAMA_PORT}:{self._OLLAMA_PORT}",  # Map the default Ollama port
            "--name",
            container_name,
        ]

        # Add GPU support if requested and available
        gpu_support_added = False
        if not cpu_only:
            if self._has_nvidia_support():
                # Check for nvidia-container-toolkit or older nvidia-docker2
                # Simple check: add --gpus=all, let Docker handle it
                self.log.info("Adding '--gpus=all' flag for NVIDIA GPU support.")
                cmd.extend(["--gpus", "all"])
                gpu_support_added = True
            else:
                self.log.warning(
                    "GPU requested (--ollama-gpu) but NVIDIA support (nvidia-smi) not detected. Starting Ollama in CPU-only mode."
                )
                # Fallback to CPU mode
                cpu_only = True  # Ensure consistency

        # Add the image name at the end
        cmd.append(image_name)

        # Execute the docker run command
        try:
            self._run_command(
                cmd, check=True, suppress_logs=False
            )  # Show the command being run
            self.log.info("Ollama container '%s' starting...", container_name)

            # Basic check to see if it started - wait a few seconds
            time.sleep(5)  # Give Ollama some time to initialize
            if self._is_container_running(container_name):
                mode = "GPU" if gpu_support_added else "CPU"
                self.log.info(
                    "External Ollama container '%s' started successfully in %s mode.",
                    container_name,
                    mode,
                )
                return True
            else:
                # If it failed to start, show logs
                self.log.error(
                    "External Ollama container '%s' failed to start or exited quickly. Checking logs...",
                    container_name,
                )
                try:
                    # Use docker logs command
                    self._run_command(
                        ["docker", "logs", container_name],
                        check=False,  # Don't fail script if logs command fails
                        suppress_logs=False,  # Display the logs
                    )
                except Exception as le:
                    self.log.error(
                        "Could not retrieve logs for failed container '%s': %s",
                        container_name,
                        le,
                    )
                return False
        except subprocess.CalledProcessError as e:
            self.log.error(
                f"Failed to execute 'docker run' for Ollama (Return Code: {e.returncode})."
            )
            if e.stderr:
                self.log.error(f"Docker run stderr:\n{e.stderr.strip()}")
            return False
        except Exception as e:
            self.log.error(
                "Unexpected error starting Ollama container: %s",
                e,
                exc_info=self.args.verbose,
            )
            return False

    def _ensure_ollama(self, opt_in=False, use_gpu=False):
        """Ensures the external Ollama container is running if opted in."""
        if not opt_in:
            self.log.info(
                "External Ollama management not requested via --with-ollama; skipping."
            )
            return True  # Indicate success (or rather, no action needed)

        self.log.info("--- External Ollama Setup ---")

        # Check if running inside Docker already
        if os.path.exists("/.dockerenv") or "DOCKER_HOST" in os.environ:
            self.log.warning(
                "Running inside a Docker container or using a remote Docker daemon. "
                "Skipping management of external Ollama container to avoid conflicts."
            )
            return (
                True  # Assume Ollama might be managed elsewhere or not needed directly
            )

        # Check OS specifics (e.g., macOS GPU limitations)
        if platform.system() == "Darwin":
            if use_gpu:
                self.log.warning(
                    "macOS detected. GPU passthrough for Docker on Mac has limitations "
                    "and might not work as expected with '--ollama-gpu'. Proceeding with CPU mode is recommended."
                )
                # Optionally force CPU mode: use_gpu = False
                # For now, let the user try, but warn them.

        # Check if Docker is available
        if not self._has_docker():
            # Error already logged by _has_docker()
            return False

        # Determine mode (CPU or attempt GPU)
        attempt_gpu = use_gpu  # Respect the --ollama-gpu flag initially
        mode_str = "GPU" if attempt_gpu else "CPU"
        self.log.info(
            "Attempting to start external Ollama container in %s mode...", mode_str
        )

        # Call the start function, passing whether to force CPU only
        # Note: _start_ollama handles the actual check for NVIDIA support if attempt_gpu is True
        success = self._start_ollama(cpu_only=not attempt_gpu)

        if not success:
            self.log.error("Failed to start the external Ollama container.")

        self.log.info("--- End External Ollama Setup ---")
        return success

    def _get_directory_size(self, path_str="."):
        """Calculates the total size of files in a directory recursively."""
        total_size = 0
        start_path = Path(path_str).resolve()  # Ensure absolute path
        self.log.debug(f"Calculating directory size for: {start_path}")
        try:
            for item in start_path.rglob("*"):  # Recursively glob all items
                if (
                    item.is_file() and not item.is_symlink()
                ):  # Ensure it's a file and not a symlink
                    try:
                        total_size += item.stat().st_size
                    except FileNotFoundError:
                        # File might have been deleted between rglob and stat
                        self.log.debug(
                            f"File not found during size calculation: {item}"
                        )
                        continue
                    except OSError as e:
                        self.log.debug(f"Could not get size for {item}: {e}")
                        continue
        except Exception as e:
            self.log.warning(
                f"Error calculating directory size for {start_path}: {e}",
                exc_info=self.args.verbose,
            )
            return 0  # Return 0 on error

        size_mb = total_size / (1024 * 1024)
        self.log.debug(f"Calculated size for {start_path}: {size_mb:.2f} MB")
        return size_mb

    def _run_docker_cache_diagnostics(self):
        """Runs diagnostics related to Docker build cache and context."""
        self.log.info("--- Docker Cache Diagnostics ---")
        if not self._has_docker():
            self.log.warning("Docker not found. Skipping diagnostics.")
            return

        try:
            # 1. Check Build Context Size
            context_size_mb = self._get_directory_size(".")  # Check current directory
            self.log.info(f"Approximate build context size: {context_size_mb:.2f} MB")
            if context_size_mb > 500:
                self.log.warning(
                    "Build context size is large (> 500MB). "
                    "Ensure your '.dockerignore' file includes large directories/files "
                    "(like .git, venv, node_modules, build artifacts, data files) "
                    "to speed up builds and reduce image size."
                )
            elif context_size_mb > 100:
                self.log.info(
                    "Build context size is moderate. Review '.dockerignore' for potential improvements."
                )

            # 2. Check Services Defined in Compose
            try:
                services_cmd = [
                    "docker",
                    "compose",
                    "-f",
                    self._DOCKER_COMPOSE_FILE,
                    "config",
                    "--services",
                ]
                result = self._run_command(
                    services_cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    suppress_logs=True,
                )
                services = result.stdout.strip().splitlines()
                if services:
                    self.log.info(
                        f"Services defined in '{self._DOCKER_COMPOSE_FILE}': {', '.join(services)}"
                    )
                else:
                    self.log.info(
                        f"No services found in '{self._DOCKER_COMPOSE_FILE}'."
                    )
                    services = []  # Ensure it's a list
            except Exception as e:
                self.log.warning(
                    f"Could not retrieve services from '{self._DOCKER_COMPOSE_FILE}': {e}. Diagnostics limited."
                )
                services = []

            # 3. Check Image History for Build Cache Layers (if services found)
            # Note: This requires images to have been built previously.
            if services:
                self.log.info(
                    "Checking image history for potential cache issues (requires images to be built)..."
                )
                # Get image names from compose config (more reliable than service names)
                try:
                    config_cmd = [
                        "docker",
                        "compose",
                        "-f",
                        self._DOCKER_COMPOSE_FILE,
                        "config",
                        "--format",
                        "json",
                    ]
                    config_res = self._run_command(
                        config_cmd,
                        capture_output=True,
                        text=True,
                        check=True,
                        suppress_logs=True,
                    )
                    compose_data = json.loads(config_res.stdout)
                    service_configs = compose_data.get("services", {})
                except Exception as e:
                    self.log.warning(
                        f"Could not parse compose config JSON: {e}. Cannot check image history reliably."
                    )
                    service_configs = {}

                for service_name in services:
                    service_info = service_configs.get(service_name, {})
                    image_name = service_info.get(
                        "image"
                    )  # Check for explicitly defined image name first
                    if not image_name:
                        # Fallback to default naming convention if image not specified (depends on compose version/project name)
                        # This part is less reliable; might need project name context. Sticking to defined images.
                        # image_name = f"{Path('.').name}_{service_name}" # Example guess
                        self.log.debug(
                            f"Service '{service_name}' has no explicit 'image' defined. Skipping history check."
                        )
                        continue

                    self.log.info(
                        f"--- History for image '{image_name}' (service: {service_name}) ---"
                    )
                    try:
                        # Format: Layer ID (short), Size, Command that created the layer
                        history_cmd = [
                            "docker",
                            "history",
                            image_name,
                            "--no-trunc=false",  # Show full command
                            "--format",
                            '{{printf "%.12s" .ID}} | {{.Size | printf "%-12s"}} | {{.CreatedBy}}',
                        ]
                        history_res = self._run_command(
                            history_cmd,
                            check=False,
                            capture_output=True,
                            text=True,
                            suppress_logs=True,
                        )

                        if history_res.returncode == 0 and history_res.stdout.strip():
                            self.log.info(
                                "Layer ID     | Size         | Created By Command"
                            )
                            self.log.info(
                                "------------ | ------------ | ------------------"
                            )
                            # Print history line by line for better readability
                            for line in history_res.stdout.strip().splitlines():
                                self.log.info(line)
                            # Look for large layers or redundant commands
                            large_layers = [
                                line
                                for line in history_res.stdout.strip().splitlines()
                                if "MB" in line.split("|")[1]
                                or "GB" in line.split("|")[1]
                            ]

                            if len(large_layers) > 5:
                                self.log.warning(
                                    f"Image '{image_name}' has several large layers (> 1MB). Consider multi-stage builds or optimizing Dockerfile instructions."
                                )
                        elif history_res.returncode != 0:
                            self.log.warning(
                                f"Could not retrieve history for image '{image_name}'. It might not be built yet. Error:\n{history_res.stderr.strip()}"
                            )
                        else:
                            self.log.info(
                                f"No history found for image '{image_name}'. It might not be built yet."
                            )

                    except Exception as e:
                        self.log.error(
                            f"Error getting history for image '{image_name}': {e}",
                            exc_info=self.args.verbose,
                        )
            else:
                self.log.info("No services found; skipping image history checks.")

        except Exception as e:
            self.log.error(
                "An unexpected error occurred during Docker cache diagnostics: %s",
                e,
                exc_info=self.args.verbose,
            )
        finally:
            self.log.info("--- End Docker Cache Diagnostics ---")

    def _handle_nuke(self):
        """Handles the '--nuke' command to remove all project and unused Docker resources."""
        self.log.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        self.log.warning("!!!    NUKE MODE ACTIVATED   !!!")
        self.log.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        self.log.warning("This action is IRREVERSIBLE and will:")
        self.log.warning(
            f"  1. Stop and remove all containers defined in '{self._DOCKER_COMPOSE_FILE}'."
        )
        self.log.warning("  2. Remove volumes associated with these services.")
        self.log.warning("  3. Prune ALL unused Docker data on your system, including:")
        self.log.warning("     - Stopped containers (from ANY project)")
        self.log.warning("     - Dangling images (images without tags)")
        self.log.warning("     - Unused networks")
        self.log.warning(
            "     - Unused volumes (from ANY project, unless explicitly excluded by prune)"
        )
        self.log.warning("     - Build cache")
        self.log.warning("This can potentially remove data from other Docker projects.")

        try:
            # Prompt for confirmation
            confirm = input(">>> Type 'confirm nuke' exactly to proceed: ")
        except EOFError:  # Handle non-interactive environments
            self.log.error(
                "Nuke operation requires interactive confirmation. Aborting."
            )
            sys.exit(1)

        if confirm.strip() != "confirm nuke":
            self.log.info("Nuke operation cancelled.")
            sys.exit(0)

        self.log.info("Proceeding with Docker nuke operation...")

        # Step 1: Take down the current project defined by docker-compose.yml
        self.log.info(
            f"Running 'docker compose down --volumes --remove-orphans' for '{self._DOCKER_COMPOSE_FILE}'..."
        )
        try:
            down_cmd = [
                "docker",
                "compose",
                "-f",
                self._DOCKER_COMPOSE_FILE,
                "down",
                "--volumes",
                "--remove-orphans",
            ]
            self._run_command(
                down_cmd, check=False, suppress_logs=False
            )  # Show output for this step
            self.log.info("Project stack stopped and volumes removed.")
        except Exception as e:
            self.log.warning(
                f"Error during 'docker compose down' (attempting to continue): {e}",
                exc_info=self.args.verbose,
            )

        # Step 2: Prune the entire Docker system
        self.log.info("Running 'docker system prune -a --volumes --force'...")
        self.log.warning("This will prune ALL unused Docker resources system-wide.")
        try:
            prune_cmd = ["docker", "system", "prune", "-a", "--volumes", "--force"]
            self._run_command(
                prune_cmd, check=True, suppress_logs=False
            )  # Show output, check for success
            self.log.info("Docker system prune completed.")
        except subprocess.CalledProcessError as e:
            self.log.critical(
                f"Critical error during 'docker system prune' (Return Code: {e.returncode}). Nuke partially failed."
            )
            if e.stderr:
                self.log.error(f"Prune stderr:\n{e.stderr.strip()}")
            sys.exit(1)  # Exit on prune failure, as it's the critical part
        except Exception as e:
            self.log.critical(
                f"Critical unexpected error during 'docker system prune': {e}",
                exc_info=self.args.verbose,
            )
            sys.exit(1)

        self.log.info("******************************")
        self.log.info("*** Docker Nuke Complete ***")
        self.log.info("******************************")

    def _handle_down(self):
        """Handles the 'down' command, optionally clearing volumes."""
        target_services = self.args.services or []
        target_desc = (
            f" for services: {', '.join(target_services)}"
            if target_services
            else " for all project services"
        )
        action = "Stopping containers"
        volume_flag = False

        if self.args.clear_volumes:
            action += " and removing associated volumes"
            volume_flag = True
            self.log.warning(f"Volume removal requested{target_desc}.")
            try:
                # Confirmation prompt for volume removal
                service_list = ", ".join(target_services) if target_services else "ALL"
                prompt = f">>> Are you sure you want to remove volumes for '{service_list}' services? (yes/no): "
                confirm = input(prompt).lower().strip()
            except EOFError:
                self.log.error(
                    "Volume deletion confirmation requires interactive input. Aborting 'down --volumes'."
                )
                sys.exit(1)

            if confirm != "yes":
                self.log.info(
                    "Volume deletion cancelled. Proceeding to stop containers only."
                )
                volume_flag = False  # Revert to stopping containers only
                action = "Stopping containers"  # Update action description
            else:
                self.log.info("Confirmed volume removal.")

        self.log.info(f"{action}{target_desc}...")

        # Construct docker compose down command
        down_cmd = ["docker", "compose", "-f", self._DOCKER_COMPOSE_FILE, "down"]
        if volume_flag:
            down_cmd.append("--volumes")
        down_cmd.append("--remove-orphans")  # Good practice to remove orphans

        # Add specific services if provided
        if target_services:
            # Docker Compose V2 expects services at the end without specific flags
            down_cmd.extend(target_services)
            self.log.debug(f"Targeting specific services for down: {target_services}")

        # Execute command
        try:
            self._run_command(
                down_cmd, check=False, suppress_logs=False
            )  # Show command output, don't fail script on error
            self.log.info(
                f"Docker compose down command ({'with volumes' if volume_flag else 'without volumes'}) executed."
            )
        except Exception as e:
            # Log error but don't necessarily exit, as 'down' might be part of a larger workflow
            self.log.error(
                f"Error during 'docker compose down': {e}", exc_info=self.args.verbose
            )

    def _handle_build(self):
        """Handles the 'build' command."""
        target_services = self.args.services or []
        target_desc = (
            f" for services: {', '.join(target_services)}"
            if target_services
            else " for all buildable services"
        )
        cache_desc = (
            " without cache (--no-cache)" if self.args.no_cache else " using cache"
        )
        parallel_desc = " in parallel (--parallel)" if self.args.parallel else ""
        pull_desc = " (will attempt to pull base_workers images)"  # Default behavior

        self.log.info(
            f"Building images{target_desc}{cache_desc}{parallel_desc}{pull_desc}..."
        )

        # Construct build command
        build_cmd = ["docker", "compose", "-f", self._DOCKER_COMPOSE_FILE, "build"]
        if self.args.no_cache:
            build_cmd.append("--no-cache")
        if self.args.parallel:
            # Note: Parallel builds can make logs harder to read if errors occur
            build_cmd.append("--parallel")
        # build_cmd.append("--pull") # Explicitly pull base_workers images (often default, but can ensure latest)

        # Add specific services if provided
        if target_services:
            build_cmd.extend(target_services)
            self.log.debug(f"Targeting specific services for build: {target_services}")

        # Execute build command
        t_start = time.time()
        try:
            # Run build, show output, check for errors
            self._run_command(build_cmd, check=True, suppress_logs=False)
            t_end = time.time()
            self.log.info(
                "Build completed successfully in %.2f seconds.", t_end - t_start
            )

            # Tag images if requested
            if self.args.tag:
                self.log.info(f"Tagging built images with tag '{self.args.tag}'...")
                # Pass only the services that were targeted for the build (or None for all)
                self._tag_images(
                    self.args.tag, targeted_services=target_services or None
                )

        except subprocess.CalledProcessError as e:
            # Build failed
            self.log.critical(
                f"Docker build failed (Return Code: {e.returncode}). Check the build logs above for errors."
            )
            # No need to print stderr again, _run_command already did if capture_output=False
            sys.exit(1)  # Exit script on build failure
        except Exception as e:
            self.log.critical(
                f"An unexpected error occurred during build: {e}",
                exc_info=self.args.verbose,
            )
            sys.exit(1)

    def _tag_images(self, tag, targeted_services=None):
        """Tags images built by docker compose."""
        if not tag:
            self.log.warning("No tag provided, skipping tagging.")
            return
        if not self._has_docker():
            self.log.error("Docker not found, cannot tag images.")
            return

        self.log.info(f"Attempting to tag images with tag: '{tag}'")
        if targeted_services:
            self.log.info(f"(Targeting services: {', '.join(targeted_services)})")

        try:
            # Get the fully resolved compose configuration including image names
            config_cmd = [
                "docker",
                "compose",
                "-f",
                self._DOCKER_COMPOSE_FILE,
                "config",
                "--format",
                "json",
            ]
            config_res = self._run_command(
                config_cmd,
                capture_output=True,
                check=True,
                text=True,
                suppress_logs=True,
            )
            compose_config = json.loads(config_res.stdout)
            services_data = compose_config.get("services", {})

            if not services_data:
                self.log.warning(
                    "No services found in resolved compose config. Cannot determine images to tag."
                )
                return

            tagged_count = 0
            skipped_count = 0
            error_count = 0

            for service_name, service_config in services_data.items():
                # Skip if specific services were targeted and this isn't one of them
                if targeted_services and service_name not in targeted_services:
                    continue

                # Get the image name defined or inferred by compose config
                image_name = service_config.get("image")
                if not image_name:
                    # If 'image' isn't specified, compose might use project_service format.
                    # This requires knowing the project name, hard to infer reliably here.
                    # Best effort: skip services without an explicit 'image' key.
                    self.log.debug(
                        f"Skipping tagging for service '{service_name}': No explicit 'image' name found in resolved config."
                    )
                    skipped_count += 1
                    continue

                # We assume the image 'image_name' (e.g., 'myrepo/myimage:latest' or 'myimage') exists locally
                # as it should have just been built or was specified.
                source_image_ref = image_name

                # Construct the new tag: replace existing tag or append if none exists
                if ":" in source_image_ref:
                    base_image = source_image_ref.split(":", 1)[0]
                else:
                    base_image = source_image_ref
                new_image_tag = f"{base_image}:{tag}"

                self.log.info(f"Tagging: {source_image_ref}  ->  {new_image_tag}")
                try:
                    # Execute docker tag command
                    tag_cmd = ["docker", "tag", source_image_ref, new_image_tag]
                    self._run_command(
                        tag_cmd, check=True, suppress_logs=True
                    )  # Suppress logs for tag, log intent above
                    tagged_count += 1
                except subprocess.CalledProcessError as tag_e:
                    self.log.error(
                        f"Failed to tag '{source_image_ref}' as '{new_image_tag}'. Error (Code {tag_e.returncode}):"
                    )
                    if tag_e.stderr:
                        self.log.error(f"Stderr:\n{tag_e.stderr.strip()}")
                    error_count += 1
                except Exception as tag_e:
                    self.log.error(
                        f"Unexpected error tagging {source_image_ref}: {tag_e}",
                        exc_info=self.args.verbose,
                    )
                    error_count += 1

            # Summary
            log_level = logging.WARNING if error_count > 0 else logging.INFO
            self.log.log(
                log_level,
                f"Tagging complete. {tagged_count} tagged, {skipped_count} skipped, {error_count} errors.",
            )

        except subprocess.CalledProcessError as e:
            self.log.error(
                f"Failed to get resolved compose config for tagging (Code: {e.returncode}). Cannot tag images."
            )
            if e.stderr:
                self.log.error(f"Stderr:\n{e.stderr.strip()}")
        except json.JSONDecodeError as e:
            self.log.error(f"Failed to parse compose config JSON for tagging: {e}")
        except Exception as e:
            self.log.error(
                f"An unexpected error occurred during image tagging: {e}",
                exc_info=self.args.verbose,
            )

    def _handle_up(self):
        """Handles the 'up' command to start services."""
        # Crucial check: .env file must exist before 'up'
        if not os.path.exists(self._ENV_FILE):
            self.log.error(
                f"Required '{self._ENV_FILE}' file is missing. "
                f"Cannot run 'docker compose up'. Please ensure the file is generated or exists."
            )
            # Suggest generating it if the script is capable
            self.log.info(
                f"You might need to run this script without the 'up' command first, or ensure '{self._ENV_FILE}' is present."
            )
            sys.exit(1)
        self.log.debug(f"Verified '{self._ENV_FILE}' exists.")

        # Load .env into the current environment IF it wasn't loaded earlier (e.g., if file existed)
        # This ensures compose can read the variables. Override ensures current values are used.
        load_dotenv(dotenv_path=self._ENV_FILE, override=True)
        self.log.debug(f"Loaded environment variables from '{self._ENV_FILE}'.")

        mode = "attached (logs will stream)" if self.args.attached else "detached (-d)"
        target_services = self.args.services or []
        target_desc = (
            f" services: {', '.join(target_services)}"
            if target_services
            else " all services"
        )
        build_opt = " with build (--build)" if self.args.build_before_up else ""
        force_recreate_opt = (
            " with force-recreate (--force-recreate)"
            if self.args.force_recreate
            else ""
        )

        self.log.info(
            f"Starting {target_desc} in {mode} mode{build_opt}{force_recreate_opt}..."
        )

        # Construct docker compose up command
        up_cmd = ["docker", "compose", "-f", self._DOCKER_COMPOSE_FILE, "up"]

        if not self.args.attached:
            up_cmd.append("-d")
        if self.args.build_before_up:
            # Build options should ideally be handled by a separate 'build' step,
            # but '--build' flag on 'up' is common.
            up_cmd.append("--build")
            if self.args.no_cache:
                up_cmd.append("--no-cache")  # Pass no-cache to build during up
        if self.args.force_recreate:
            up_cmd.append("--force-recreate")
        # Add specific services if provided
        if target_services:
            up_cmd.extend(target_services)
            self.log.debug(f"Targeting specific services for up: {target_services}")

        # Execute command
        try:
            # Run 'up'. If attached, logs stream directly. If detached, command returns quickly.
            # Check=True ensures an exception is raised if 'up' fails.
            self._run_command(
                up_cmd, check=True, suppress_logs=self.args.attached
            )  # Don't log command if attached (clutters logs)
            self.log.info("Docker compose up command executed successfully.")

            # If detached, suggest how to view logs
            if not self.args.attached:
                logs_cmd_base = [
                    "docker",
                    "compose",
                    "-f",
                    self._DOCKER_COMPOSE_FILE,
                    "logs",
                    "-f",
                    "--tail=50",
                ]
                if target_services:
                    logs_cmd_base.extend(target_services)
                self.log.info(
                    f"Containers started in detached mode. To view logs, run: {' '.join(logs_cmd_base)}"
                )

        except subprocess.CalledProcessError as e:
            # 'docker compose up' command failed
            self.log.critical(
                f"'docker compose up' failed (Return Code: {e.returncode})."
            )
            # Attempt to show logs for diagnostics, even if detached
            self.log.info("Attempting to show recent logs for failed services...")
            try:
                logs_cmd_fail = [
                    "docker",
                    "compose",
                    "-f",
                    self._DOCKER_COMPOSE_FILE,
                    "logs",
                    "--tail=100",
                ]
                if target_services:
                    logs_cmd_fail.extend(target_services)
                # Run logs command, don't check=True, show its output
                self._run_command(logs_cmd_fail, check=False, suppress_logs=False)
            except Exception as log_e:
                self.log.error(
                    f"Could not fetch logs after failure: {log_e}",
                    exc_info=self.args.verbose,
                )
            sys.exit(1)  # Exit script due to 'up' failure
        except Exception as e:
            self.log.critical(
                f"An unexpected error occurred during 'docker compose up': {e}",
                exc_info=self.args.verbose,
            )
            sys.exit(1)

    def run(self):
        """Main execution logic based on parsed arguments."""
        start_time = time.time()
        self.log.info(f"Docker Manager script started. Mode: {self.args.mode}")

        # Handle exclusive diagnostic/nuke modes first
        if self.args.debug_cache:
            self._run_docker_cache_diagnostics()
            sys.exit(0)
        if self.args.nuke:
            self._handle_nuke()  # This exits upon completion or cancellation
            sys.exit(0)  # Should be unreachable if nuke runs

        # Ensure Docker is available early
        if not self._has_docker():
            sys.exit(1)  # Error logged in _has_docker

        # Handle optional external Ollama setup
        if self.args.with_ollama:
            ollama_ok = self._ensure_ollama(opt_in=True, use_gpu=self.args.ollama_gpu)
            if not ollama_ok:
                # Logged as error/warning inside _ensure_ollama
                # Decide if this should be fatal - for now, just warn and continue
                self.log.warning(
                    "External Ollama setup encountered issues. Continuing script execution..."
                )
                # Consider adding: if not ollama_ok and self.args.mode != 'down_only': sys.exit(1) if Ollama is critical

        # --- Main workflow based on mode ---
        mode = self.args.mode

        # Handle 'down' action first if requested or implied
        if self.args.down or self.args.clear_volumes:
            self._handle_down()
            if mode == "down_only":
                self.log.info(
                    "Mode 'down_only' selected. Script finished after 'down' operation."
                )
                sys.exit(0)  # Exit after down if mode is down_only

        # Handle 'build' action
        if mode in ["build", "both"]:
            self._handle_build()
            if mode == "build":
                self.log.info(
                    "Mode 'build' selected. Script finished after 'build' operation."
                )
                sys.exit(0)  # Exit after build if mode is build

        # Handle 'up' action (implicit in 'up' and 'both' modes)
        if mode in ["up", "both"]:
            # Note: _handle_up checks for .env file existence
            self._handle_up()

        end_time = time.time()
        self.log.info(
            f"Docker management script finished in {end_time - start_time:.2f} seconds."
        )

    @staticmethod
    def parse_args():
        parser = argparse.ArgumentParser(
            description="Manage Docker Compose stack: build, run, set up .env, and optionally manage external Ollama.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            epilog="Example: './run.py --mode both --no-cache --tag v1.0' -> down, build (no cache), tag, up",
        )

        # --- Main Operation Mode ---
        parser.add_argument(
            "--mode",
            choices=["up", "build", "both", "down_only"],
            default="up",
            help="Primary action: 'up' (start services), 'build' (build images), 'both' (down, build, up), 'down_only' (just stop/remove services).",
        )

        # --- Targeting Services ---
        parser.add_argument(
            "--services",
            nargs="+",
            metavar="SERVICE_NAME",
            default=[],  # Explicitly default to empty list
            help="Target specific service(s) defined in docker-compose.yml for the selected action (build, up, down). If omitted, action applies to all services.",
        )

        # --- Build Options ---
        build_group = parser.add_argument_group(
            "Build Options (used with --mode build/both or --build-before-up)"
        )
        build_group.add_argument(
            "--no-cache",
            action="store_true",
            help="Perform the build without using Docker's cache.",
        )
        build_group.add_argument(
            "--parallel",
            action="store_true",
            help="Build images in parallel (can make logs harder to follow).",
        )
        build_group.add_argument(
            "--tag",
            type=str,
            metavar="TAG",
            help="Tag the successfully built image(s) with the specified tag (e.g., 'latest', 'v1.2.0').",
        )

        # --- Up Options ---
        up_group = parser.add_argument_group("Up Options (used with --mode up/both)")
        up_group.add_argument(
            "--attached",
            "-a",  # Common shortcut
            action="store_true",
            help="Run 'docker compose up' in the foreground, attaching to container logs.",
        )
        up_group.add_argument(
            "--build-before-up",
            "--build",  # Allow '--build' as alias for convenience
            dest="build_before_up",
            action="store_true",
            help="Run 'docker compose build' before 'up'. Equivalent to '--mode both' but implies starting point is 'up'.",
        )
        up_group.add_argument(
            "--force-recreate",
            action="store_true",
            help="Force recreation of containers even if their configuration hasn't changed.",
        )

        # --- Down Options / Cleanup ---
        down_group = parser.add_argument_group("Down / Cleanup Options")
        down_group.add_argument(
            "--down",
            action="store_true",
            help="Run 'docker compose down' before other actions (build/up). If mode is 'up', this implies '--mode down_only' unless other actions like build/tag are specified.",
        )
        down_group.add_argument(
            "--clear-volumes",
            "-v",  # Common shortcut
            action="store_true",
            help="When running 'down' (explicitly via --down or implicitly via --mode both/nuke), also remove associated named volumes. Requires interactive confirmation.",
        )
        down_group.add_argument(
            "--nuke",
            action="store_true",
            help="DANGER ZONE! Stops project stack, removes its volumes, AND runs 'docker system prune -a --volumes --force' to remove ALL unused Docker data system-wide. Requires interactive confirmation.",
        )

        # --- External Ollama Management ---
        ollama_group = parser.add_argument_group(
            "External Ollama Management (Optional)"
        )
        ollama_group.add_argument(
            "--with-ollama",
            action="store_true",
            help="Attempt to start/manage an external Ollama container using Docker.",
        )
        ollama_group.add_argument(
            "--ollama-gpu",
            action="store_true",
            help="If using --with-ollama, attempt to start the Ollama container with GPU support (--gpus=all). Requires NVIDIA Docker toolkit.",
        )

        # --- Diagnostics & Verbosity ---
        diag_group = parser.add_argument_group("Diagnostics & Verbosity")
        diag_group.add_argument(
            "--verbose",
            "--debug",
            dest="verbose",
            action="store_true",
            help="Enable detailed debug logging output.",
        )
        diag_group.add_argument(
            "--debug-cache",
            action="store_true",
            help="Run Docker build cache diagnostics (context size, image history) and exit. Overrides other modes.",
        )

        args = parser.parse_args()

        # --- Post-processing and Validation ---

        # --clear-volumes implies --down
        if args.clear_volumes:
            args.down = True
            log.debug("--clear-volumes implies --down.")

        # If only --down or --clear-volumes is specified with default mode 'up', change mode to 'down_only'
        build_flags_set = (
            args.tag or args.no_cache or args.parallel or args.build_before_up
        )
        up_flags_set = args.attached or args.force_recreate
        if args.down and args.mode == "up" and not (build_flags_set or up_flags_set):
            args.mode = "down_only"
            log.debug(
                "Only --down/--clear-volumes specified with default mode 'up'. Setting effective mode to 'down_only'."
            )

        # Warn if build flags used without build context
        build_context_present = args.mode in ["build", "both"] or args.build_before_up
        if (args.tag or args.no_cache or args.parallel) and not build_context_present:
            log.warning(
                f"Build flags (--tag, --no-cache, --parallel) used without a build context (--mode build/both or --build-before-up). These flags will be ignored for mode '{args.mode}'."
            )

        # Disallow --build-before-up with modes that already include build or only down
        if args.build_before_up and args.mode in ["build", "down_only", "both"]:
            parser.error(
                f"--build-before-up flag is redundant or invalid with --mode={args.mode}"
            )

        # Handle exclusive modes (--nuke, --debug-cache)
        exclusive_flags = []
        if args.nuke:
            exclusive_flags.append("--nuke")
        if args.debug_cache:
            exclusive_flags.append("--debug-cache")

        if len(exclusive_flags) > 1:
            parser.error(
                f"Cannot use {' and '.join(exclusive_flags)} together. They are exclusive actions."
            )

        if exclusive_flags:
            exclusive_flag = exclusive_flags[0]
            # Check if other operational flags were also set unnecessarily
            other_flags_set = any(
                [
                    args.mode != "up",  # Check if mode was changed from default
                    args.down,
                    args.clear_volumes,
                    build_flags_set,
                    up_flags_set,
                    args.with_ollama,
                    args.ollama_gpu,
                    args.services,  # Services list is okay though
                ]
            )
            if other_flags_set:
                log.warning(
                    f"{exclusive_flag} is an exclusive action. Other operational flags will be ignored."
                )
            # No need to change args.mode here, the main run() handles these flags first.

        return args


if __name__ == "__main__":
    # Step 0: Ensure the docker-compose.yml exists by generating it if needed.
    # Assumes generate_dev_docker_compose handles its own logic about overwriting etc.
    try:
        generate_dev_docker_compose()
        # Give filesystem a moment to settle, especially on slower systems or network drives
        time.sleep(0.5)
    except Exception as gen_e:
        # Make failure to generate compose file fatal
        log.critical(
            f"Failed to generate '{DockerManager._DOCKER_COMPOSE_FILE}' using generate_dev_docker_compose script: {gen_e}",
            exc_info=True,
        )
        sys.exit(1)

    # Step 1: Parse arguments
    try:
        arguments = DockerManager.parse_args()
    except Exception as parse_err:
        # argparse usually handles errors and exits, but catch unexpected ones
        log.critical(
            f"Error parsing command line arguments: {parse_err}", exc_info=True
        )
        sys.exit(1)

    # Step 2: Set logging level based on args
    if arguments.verbose:
        log.setLevel(logging.DEBUG)
        # Also set level for root logger if needed, or configure specific module loggers
        # logging.getLogger().setLevel(logging.DEBUG)
    log.debug("Debug logging enabled.")
    log.debug("Parsed arguments: %s", arguments)

    # Step 3: Initialize and run the manager
    try:
        manager = DockerManager(arguments)
        manager.run()
        sys.exit(0)  # Explicitly exit with success code
    except KeyboardInterrupt:
        log.info("\nOperation cancelled by user (Ctrl+C).")
        sys.exit(130)  # Standard exit code for Ctrl+C
    except subprocess.CalledProcessError as e:
        # Errors from _run_command with check=True that weren't handled locally
        log.critical(
            f"A critical command failed (Return Code: {e.returncode}). See logs above for details."
        )
        # Avoid printing stderr again if _run_command already did
        sys.exit(e.returncode or 1)
    except FileNotFoundError as e:
        # Errors like 'docker' command not found
        log.critical(f"Required command or file not found: {e}")
        sys.exit(1)
    except RuntimeError as e:
        # Catch specific runtime errors raised in the script (e.g., unsupported OS)
        log.critical(f"Runtime error: {e}")
        sys.exit(1)
    except Exception as e:
        # Catch-all for unexpected errors
        log.critical(
            "An unexpected error occurred: %s", e, exc_info=log.level == logging.DEBUG
        )
        sys.exit(1)
