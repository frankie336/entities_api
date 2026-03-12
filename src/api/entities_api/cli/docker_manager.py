# src/api/entities_api/cli/docker_manager.py
#
# Run via:
#   python -m entities_api docker-manager --mode up
#   python -m entities_api docker-manager --mode both --no-cache --tag v1.0
#   entities-api docker-manager --mode logs --follow
#   entities-api docker-manager --mode up --exclude ollama --exclude vllm
#
from __future__ import annotations

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
from types import SimpleNamespace
from typing import List, Optional
from urllib.parse import quote_plus

import typer

# ---------------------------------------------------------------------------
# Container guard — this script manages Docker from the HOST only.
# Running it inside a container would cause Docker-in-Docker chaos.
# ---------------------------------------------------------------------------


def _running_in_docker() -> bool:
    return os.getenv("RUNNING_IN_DOCKER") == "1" or Path("/.dockerenv").exists()


if _running_in_docker():
    print(
        "[error] docker_manager.py cannot be run inside a container.\n"
        "This script manages the Docker Compose stack from the HOST machine only.\n"
        "Exiting to prevent Docker-in-Docker chaos."
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Optional third-party imports — graceful failure with clear guidance
# ---------------------------------------------------------------------------
try:
    import yaml
except ImportError:
    typer.echo(
        "[error] PyYAML is required. Please install it: pip install PyYAML",
        err=True,
    )
    raise SystemExit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    typer.echo(
        "[error] python-dotenv is required. Please install it: pip install python-dotenv",
        err=True,
    )
    raise SystemExit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_DB_CONTAINER_PORT = "3306"
DEFAULT_DB_SERVICE_NAME = "db"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Typer app
# ---------------------------------------------------------------------------
app = typer.Typer(
    name="docker-manager",
    help="Manage Docker Compose stack: build, run, set up .env, and optionally manage external Ollama.",
    add_completion=False,
)


# ---------------------------------------------------------------------------
# DockerManager class
# ---------------------------------------------------------------------------
class DockerManager:
    """Manages Docker Compose stack operations, env setup, and optional Ollama integration."""

    _ENV_EXAMPLE_FILE = ".env.example"
    _ENV_FILE = ".env"
    _DOCKER_COMPOSE_FILE = "docker-compose.yml"

    _OLLAMA_IMAGE = "ollama/ollama"
    _OLLAMA_CONTAINER = "ollama"
    _OLLAMA_PORT = "11434"

    _COMPOSE_ENV_MAPPING = {
        "MYSQL_ROOT_PASSWORD": (DEFAULT_DB_SERVICE_NAME, "MYSQL_ROOT_PASSWORD"),
        "MYSQL_DATABASE": (DEFAULT_DB_SERVICE_NAME, "MYSQL_DATABASE"),
        "MYSQL_USER": (DEFAULT_DB_SERVICE_NAME, "MYSQL_USER"),
        "MYSQL_PASSWORD": (DEFAULT_DB_SERVICE_NAME, "MYSQL_PASSWORD"),
        "SMBCLIENT_SERVER": ("fastapi_cosmic_catalyst", "SMBCLIENT_SERVER"),
        "SMBCLIENT_SHARE": ("fastapi_cosmic_catalyst", "SMBCLIENT_SHARE"),
        "SMBCLIENT_USERNAME": ("fastapi_cosmic_catalyst", "SMBCLIENT_USERNAME"),
        "SMBCLIENT_PASSWORD": ("fastapi_cosmic_catalyst", "SMBCLIENT_PASSWORD"),
        "SMBCLIENT_PORT": ("fastapi_cosmic_catalyst", "SMBCLIENT_PORT"),
        "AUTO_MIGRATE": ("fastapi_cosmic_catalyst", "AUTO_MIGRATE"),
        "DISABLE_FIREJAIL": ("sandbox_api", "DISABLE_FIREJAIL"),
    }

    _GENERATED_SECRETS = [
        "SIGNED_URL_SECRET",
        "API_KEY",
        "MYSQL_ROOT_PASSWORD",
        "MYSQL_PASSWORD",
        "SECRET_KEY",
        "SANDBOX_AUTH_SECRET",
    ]

    _GENERATED_TOOL_IDS = [
        "TOOL_CODE_INTERPRETER",
        "TOOL_WEB_SEARCH",
        "TOOL_COMPUTER",
        "TOOL_VECTOR_STORE_SEARCH",
    ]

    _DEFAULT_VALUES = {
        "ASSISTANTS_BASE_URL": "http://localhost:9000",
        "SANDBOX_SERVER_URL": "http://localhost:9000",
        "DOWNLOAD_BASE_URL": "http://localhost:9000/v1/files/download",
        "HYPERBOLIC_BASE_URL": "https://api.hyperbolic.xyz/v1",
        "TOGETHER_BASE_URL": "https://api.together.xyz/v1",
        "OLLAMA_BASE_URL": "http://ollama:11434",
        "TOGETHER_API_KEY": "",
        "HYPERBOLIC_API_KEY": "",
        "ADMIN_API_KEY": "",
        "ENTITIES_API_KEY": "",
        "ENTITIES_USER_ID": "",
        "DEEP_SEEK_API_KEY": "",
        "BASE_URL_HEALTH": "http://localhost:9000/v1/health",
        "SHELL_SERVER_URL": "ws://sandbox_api:8000/ws/computer",
        "SHELL_SERVER_EXTERNAL_URL": "ws://localhost:8000/ws/computer",
        "CODE_EXECUTION_URL": "ws://sandbox_api:8000/ws/execute",
        "DISABLE_FIREJAIL": "true",
        "DEFAULT_SECRET_KEY": "your_secret_key_here",
        "SHARED_PATH": "./shared_data",
        "AUTO_MIGRATE": "1",
        "MYSQL_HOST": DEFAULT_DB_SERVICE_NAME,
        "MYSQL_PORT": DEFAULT_DB_CONTAINER_PORT,
        "MYSQL_DATABASE": "entities_db",
        "MYSQL_USER": "api_user",
        "REDIS_URL": "redis://redis:6379/0",
        "ADMIN_USER_EMAIL": "admin@example.com",
        "ADMIN_USER_ID": "",
        "ADMIN_KEY_PREFIX": "",
        "SMBCLIENT_SERVER": "samba_server",
        "SMBCLIENT_SHARE": "cosmic_share",
        "SMBCLIENT_USERNAME": "samba_user",
        "SMBCLIENT_PASSWORD": "default",
        "SMBCLIENT_PORT": "445",
        "LOG_LEVEL": "INFO",
        "PYTHONUNBUFFERED": "1",
    }

    _ENV_STRUCTURE = {
        "Base URLs": [
            "ASSISTANTS_BASE_URL",
            "SANDBOX_SERVER_URL",
            "DOWNLOAD_BASE_URL",
            "HYPERBOLIC_BASE_URL",
            "TOGETHER_BASE_URL",
            "OLLAMA_BASE_URL",
        ],
        "Database Configuration": [
            "DATABASE_URL",
            "SPECIAL_DB_URL",
            "MYSQL_ROOT_PASSWORD",
            "MYSQL_DATABASE",
            "MYSQL_USER",
            "MYSQL_PASSWORD",
            "MYSQL_HOST",
            "MYSQL_PORT",
            "REDIS_URL",
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
            "SHELL_SERVER_EXTERNAL_URL",
            "CODE_EXECUTION_URL",
            "SIGNED_URL_SECRET",
            "SANDBOX_AUTH_SECRET",
            "DISABLE_FIREJAIL",
            "SECRET_KEY",
            "DEFAULT_SECRET_KEY",
            "SHARED_PATH",
            "AUTO_MIGRATE",
        ],
        "Admin Configuration": [
            "ADMIN_USER_EMAIL",
            "ADMIN_USER_ID",
            "ADMIN_KEY_PREFIX",
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

    # ------------------------------------------------------------------
    def __init__(self, args: SimpleNamespace) -> None:
        self.args = args
        self.is_windows = platform.system() == "Windows"
        self.log = log

        if self.args.verbose:
            self.log.setLevel(logging.DEBUG)
        self.log.debug("DockerManager initialised with args: %s", vars(args))

        self.compose_config = self._load_compose_config()
        self._check_for_required_env_file()
        self._configure_shared_path()
        self._ensure_dockerignore()

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------

    def _run_command(
        self,
        cmd_list,
        check=True,
        capture_output=False,
        text=True,
        suppress_logs=False,
        **kwargs,
    ):
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
            self.log.error("Command failed: %s", " ".join(cmd_list))
            self.log.error("Return Code: %s", e.returncode)
            if e.stdout:
                self.log.error("STDOUT:\n%s", e.stdout.strip())
            if e.stderr:
                self.log.error("STDERR:\n%s", e.stderr.strip())
            if check:
                raise
            return e
        except Exception as e:
            self.log.error(
                "Error running command %s: %s",
                " ".join(cmd_list),
                e,
                exc_info=self.args.verbose,
            )
            raise

    def _ensure_dockerignore(self):
        dockerignore = Path(".dockerignore")
        if not dockerignore.exists():
            self.log.warning(".dockerignore not found. Generating default...")
            dockerignore.write_text(
                "__pycache__/\n.venv/\nnode_modules/\n*.log\n*.pyc\n.git/\n"
                ".env*\n.env\n*.sqlite\ndist/\nbuild/\ncoverage/\ntmp/\n*.egg-info/\n"
            )
            self.log.info("Generated default .dockerignore.")

    def _load_compose_config(self):
        compose_path = Path(self._DOCKER_COMPOSE_FILE)
        if not compose_path.is_file():
            self.log.warning(
                "Docker compose file '%s' not found. Cannot extract env vars or ports.",
                self._DOCKER_COMPOSE_FILE,
            )
            return None
        try:
            config = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
            self.log.debug("Successfully parsed %s", self._DOCKER_COMPOSE_FILE)
            return config
        except yaml.YAMLError as e:
            self.log.error("Error parsing %s: %s", self._DOCKER_COMPOSE_FILE, e)
            return None
        except Exception as e:
            self.log.error("Unexpected error reading %s: %s", self._DOCKER_COMPOSE_FILE, e)
            return None

    def _get_all_services(self) -> List[str]:
        """Return every service name declared in docker-compose.yml."""
        if not self.compose_config:
            return []
        return list(self.compose_config.get("services", {}).keys())

    def _get_env_from_compose_service(self, service_name, env_var_name):
        if not self.compose_config:
            return None
        try:
            service_data = self.compose_config.get("services", {}).get(service_name)
            if not service_data:
                return None
            environment = service_data.get("environment")
            if not environment:
                return None
            if isinstance(environment, dict):
                return environment.get(env_var_name)
            if isinstance(environment, list):
                pattern = re.compile(rf"^{re.escape(env_var_name)}(?:=(.*))?$")
                for item in environment:
                    match = pattern.match(item)
                    if match:
                        return match.group(1) if match.group(1) is not None else ""
                return None
            self.log.warning(
                "Unexpected format for 'environment' in service '%s': %s",
                service_name,
                type(environment),
            )
            return None
        except Exception as e:
            self.log.error(
                "Error accessing compose env for %s/%s: %s",
                service_name,
                env_var_name,
                e,
                exc_info=self.args.verbose,
            )
            return None

    def _get_host_port_from_compose_service(self, service_name, container_port):
        if not self.compose_config:
            return None
        try:
            service_data = self.compose_config.get("services", {}).get(service_name)
            if not service_data:
                return None
            ports = service_data.get("ports", [])
            if not ports:
                return None
            container_port_base = str(container_port).split("/")[0]
            for port_mapping in ports:
                parts = str(port_mapping).split(":")
                host_port = cont_port_part = None
                if len(parts) == 1:
                    if parts[0].split("/")[0] == container_port_base:
                        host_port = cont_port_part = parts[0]
                elif len(parts) == 2:
                    host_port, cont_port_part = parts
                elif len(parts) == 3:
                    host_port, cont_port_part = parts[1], parts[2]
                if host_port and cont_port_part:
                    if cont_port_part.split("/")[0] == container_port_base:
                        return host_port.strip()
            return None
        except Exception as e:
            self.log.error(
                "Error parsing ports for service %s: %s",
                service_name,
                e,
                exc_info=self.args.verbose,
            )
            return None

    # ------------------------------------------------------------------
    # .env generation
    # ------------------------------------------------------------------

    def _generate_dot_env_file(self):
        self.log.info("Generating '%s'...", self._ENV_FILE)
        env_values = dict(self._DEFAULT_VALUES)
        generation_log = {k: "Default value" for k in env_values}

        # Step 2 — compose overrides
        for env_key, (service_name, compose_key) in self._COMPOSE_ENV_MAPPING.items():
            value = self._get_env_from_compose_service(service_name, compose_key)
            if value is not None and not str(value).startswith("${"):
                if env_values.get(env_key) != value:
                    generation_log[env_key] = (
                        f"Value from {self._DOCKER_COMPOSE_FILE} ({service_name}/{compose_key})"
                    )
                env_values[env_key] = str(value)

        # Step 3 — force-generate secrets
        for key in self._GENERATED_SECRETS:
            token_length = 16 if key == "API_KEY" else 32
            env_values[key] = secrets.token_hex(token_length)
            generation_log[key] = "Generated new secret (forced)"

        # Step 4 — tool IDs
        for key in self._GENERATED_TOOL_IDS:
            if key not in env_values:
                env_values[key] = f"tool_{secrets.token_hex(10)}"
                generation_log[key] = "Generated new tool ID"

        # Step 5 — composite DB URLs
        db_user = env_values.get("MYSQL_USER")
        db_pass = env_values.get("MYSQL_PASSWORD")
        db_host = env_values.get("MYSQL_HOST", DEFAULT_DB_SERVICE_NAME)
        db_port = env_values.get("MYSQL_PORT", DEFAULT_DB_CONTAINER_PORT)
        db_name = env_values.get("MYSQL_DATABASE")

        if all([db_user, db_pass is not None, db_host, db_port, db_name]):
            try:
                escaped_pass = quote_plus(str(db_pass))
                env_values["DATABASE_URL"] = (
                    f"mysql+pymysql://{db_user}:{escaped_pass}@{db_host}:{db_port}/{db_name}"
                )
                generation_log["DATABASE_URL"] = "Constructed from DB components (internal)"
                host_db_port = self._get_host_port_from_compose_service(
                    DEFAULT_DB_SERVICE_NAME, DEFAULT_DB_CONTAINER_PORT
                )
                if host_db_port:
                    env_values["SPECIAL_DB_URL"] = (
                        f"mysql+pymysql://{db_user}:{escaped_pass}@localhost:{host_db_port}/{db_name}"
                    )
                    generation_log["SPECIAL_DB_URL"] = (
                        f"Constructed using host port ({host_db_port})"
                    )
                else:
                    self.log.warning(
                        "Could not find host port for DB service; SPECIAL_DB_URL omitted."
                    )
                    env_values.pop("SPECIAL_DB_URL", None)
            except Exception as e:
                self.log.error(
                    "Error constructing database URLs: %s", e, exc_info=self.args.verbose
                )

        # Step 6 — write
        env_lines = [
            f"# Auto-generated .env file by entities-api docker-manager at {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            "",
        ]
        processed_keys: set = set()

        for section_name, keys_in_section in self._ENV_STRUCTURE.items():
            env_lines += [
                "#############################",
                f"# {section_name}",
                "#############################",
            ]
            found = False
            for key in keys_in_section:
                if key in env_values:
                    value = str(env_values[key])
                    if any(c in value for c in [" ", "#", "="]):
                        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                        env_lines.append(f'{key}="{escaped}"')
                    else:
                        env_lines.append(f"{key}={value}")
                    processed_keys.add(key)
                    found = True
            if not found:
                env_lines.append("# (No variables configured for this section)")
            env_lines.append("")

        remaining = sorted(set(env_values.keys()) - processed_keys)
        if remaining:
            env_lines += [
                "#############################",
                "# Other (Uncategorized)",
                "#############################",
            ]
            for key in remaining:
                value = str(env_values[key])
                if any(c in value for c in [" ", "#", "="]):
                    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                    env_lines.append(f'{key}="{escaped}"')
                else:
                    env_lines.append(f"{key}={value}")
            env_lines.append("")

        content = "\n".join(env_lines)
        try:
            Path(self._ENV_FILE).write_text(content, encoding="utf-8")
            self.log.info("Successfully generated '%s'.", self._ENV_FILE)
            if self.args.verbose:
                self.log.debug("--- .env Generation Sources ---")
                for key in sorted(env_values.keys()):
                    self.log.debug("  - %s: %s", key, generation_log.get(key, "Unknown"))
                self.log.debug("--- End .env Generation Sources ---")
        except IOError as e:
            self.log.error("Failed to write %s: %s", self._ENV_FILE, e)
            raise SystemExit(1)

    def _check_for_required_env_file(self):
        if not os.path.exists(self._ENV_FILE):
            self.log.warning("[ENV SCAN] '%s' missing. Generating...", self._ENV_FILE)
            self._generate_dot_env_file()
        else:
            self.log.info("[ENV SCAN] '%s' exists. Loading existing values.", self._ENV_FILE)
            load_dotenv(dotenv_path=self._ENV_FILE, override=True)

    def _configure_shared_path(self):
        system = platform.system().lower()
        shared_path = os.environ.get("SHARED_PATH")
        if not shared_path:
            base = os.path.expanduser("~")
            shared_path = {
                "windows": os.path.join(base, "entities_share"),
                "linux": os.path.join(base, ".local", "share", "entities_share"),
                "darwin": os.path.join(base, "Library", "Application Support", "entities_share"),
            }.get(system, os.path.abspath("./entities_share"))
            os.environ["SHARED_PATH"] = shared_path
            self.log.info("Defaulting SHARED_PATH to: %s", shared_path)
        try:
            Path(shared_path).mkdir(parents=True, exist_ok=True)
            self.log.info("Ensured shared directory exists: %s", shared_path)
        except OSError as e:
            self.log.error("Failed to create shared directory %s: %s", shared_path, e)

    # ------------------------------------------------------------------
    # Docker helpers
    # ------------------------------------------------------------------

    def _has_docker(self):
        has_cmd = shutil.which("docker") is not None
        if not has_cmd:
            self.log.error("Docker command not found in PATH. Please install Docker.")
        return has_cmd

    def _is_container_running(self, container_name):
        if not self._has_docker():
            return False
        try:
            result = self._run_command(
                ["docker", "ps", "--filter", f"name=^{container_name}$", "--format", "{{.Names}}"],
                capture_output=True,
                check=False,
                suppress_logs=True,
            )
            return result.stdout.strip() == container_name
        except Exception as e:
            self.log.warning("Could not check container '%s' status: %s", container_name, e)
            return False

    def _is_image_present(self, image_name):
        if not self._has_docker():
            return False
        try:
            result = self._run_command(
                ["docker", "images", image_name, "--quiet"],
                capture_output=True,
                check=False,
                suppress_logs=True,
            )
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning("Could not check for image '%s': %s", image_name, e)
            return False

    def _has_nvidia_support(self):
        nvidia_smi_cmd = shutil.which("nvidia-smi.exe" if self.is_windows else "nvidia-smi") or (
            shutil.which("nvidia-smi") if self.is_windows else None
        )
        if not nvidia_smi_cmd:
            nvidia_smi_cmd = shutil.which("nvidia-smi")
        if nvidia_smi_cmd:
            try:
                self._run_command(
                    [nvidia_smi_cmd],
                    check=True,
                    capture_output=True,
                    suppress_logs=not self.args.verbose,
                )
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                return False
        return False

    def _start_ollama(self, cpu_only=True):
        if not self._has_docker():
            return False
        container_name = self._OLLAMA_CONTAINER
        if self._is_container_running(container_name):
            self.log.info("External Ollama container '%s' is already running.", container_name)
            return True
        if not self._is_image_present(self._OLLAMA_IMAGE):
            self.log.info("Pulling Ollama image '%s'...", self._OLLAMA_IMAGE)
            try:
                self._run_command(["docker", "pull", self._OLLAMA_IMAGE], check=True)
            except Exception as e:
                self.log.error("Failed to pull Ollama image: %s", e)
                return False
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
        gpu_support_added = False
        if not cpu_only and self._has_nvidia_support():
            cmd.extend(["--gpus", "all"])
            gpu_support_added = True
        cmd.append(self._OLLAMA_IMAGE)
        try:
            self._run_command(cmd, check=True)
            time.sleep(5)
            if self._is_container_running(container_name):
                mode = "GPU" if gpu_support_added else "CPU"
                self.log.info("External Ollama container started in %s mode.", mode)
                return True
            self.log.error("Ollama container failed to start. Checking logs...")
            self._run_command(["docker", "logs", container_name], check=False)
            return False
        except Exception as e:
            self.log.error("Error starting Ollama container: %s", e)
            return False

    def _ensure_ollama(self, opt_in=False, use_gpu=False):
        if not opt_in:
            self.log.info("External Ollama management not requested; skipping.")
            return True
        self.log.info("--- External Ollama Setup ---")
        if os.path.exists("/.dockerenv") or "DOCKER_HOST" in os.environ:
            self.log.warning("Running inside Docker; skipping external Ollama management.")
            return True
        if platform.system() == "Darwin" and use_gpu:
            self.log.warning(
                "macOS detected; GPU passthrough has limitations. CPU mode recommended."
            )
        if not self._has_docker():
            return False
        success = self._start_ollama(cpu_only=not use_gpu)
        if not success:
            self.log.error("Failed to start the external Ollama container.")
        self.log.info("--- End External Ollama Setup ---")
        return success

    def _get_directory_size(self, path_str="."):
        total = 0
        for item in Path(path_str).resolve().rglob("*"):
            if item.is_file() and not item.is_symlink():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
        return total / (1024 * 1024)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _run_docker_cache_diagnostics(self):
        self.log.info("--- Docker Cache Diagnostics ---")
        if not self._has_docker():
            return
        try:
            size_mb = self._get_directory_size(".")
            self.log.info("Approximate build context size: %.2f MB", size_mb)
            if size_mb > 500:
                self.log.warning(
                    "Build context > 500 MB. Review .dockerignore to exclude large files."
                )
            try:
                result = self._run_command(
                    ["docker", "compose", "-f", self._DOCKER_COMPOSE_FILE, "config", "--services"],
                    capture_output=True,
                    check=True,
                    suppress_logs=True,
                )
                services = result.stdout.strip().splitlines()
                self.log.info(
                    "Services in '%s': %s", self._DOCKER_COMPOSE_FILE, ", ".join(services)
                )
            except Exception as e:
                self.log.warning("Could not retrieve services: %s", e)
                services = []

            if services:
                try:
                    config_res = self._run_command(
                        [
                            "docker",
                            "compose",
                            "-f",
                            self._DOCKER_COMPOSE_FILE,
                            "config",
                            "--format",
                            "json",
                        ],
                        capture_output=True,
                        check=True,
                        suppress_logs=True,
                    )
                    service_configs = json.loads(config_res.stdout).get("services", {})
                except Exception:
                    service_configs = {}

                for svc in services:
                    image_name = service_configs.get(svc, {}).get("image")
                    if not image_name:
                        continue
                    self.log.info("--- History for image '%s' (service: %s) ---", image_name, svc)
                    try:
                        history_res = self._run_command(
                            [
                                "docker",
                                "history",
                                image_name,
                                "--no-trunc=false",
                                "--format",
                                '{{printf "%.12s" .ID}} | {{.Size | printf "%-12s"}} | {{.CreatedBy}}',
                            ],
                            check=False,
                            capture_output=True,
                            suppress_logs=True,
                        )
                        if history_res.returncode == 0 and history_res.stdout.strip():
                            for line in history_res.stdout.strip().splitlines():
                                self.log.info(line)
                        else:
                            self.log.warning(
                                "Image '%s' not yet built or history unavailable.", image_name
                            )
                    except Exception as e:
                        self.log.error("Error getting history for '%s': %s", image_name, e)
        except Exception as e:
            self.log.error("Unexpected error during diagnostics: %s", e)
        finally:
            self.log.info("--- End Docker Cache Diagnostics ---")

    def _handle_nuke(self):
        self.log.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        self.log.warning("!!!    NUKE MODE ACTIVATED   !!!")
        self.log.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        self.log.warning(
            "This will stop all compose services, remove their volumes, AND prune ALL unused Docker data system-wide."
        )
        try:
            confirm = input(">>> Type 'confirm nuke' exactly to proceed: ")
        except EOFError:
            self.log.error("Nuke requires interactive confirmation. Aborting.")
            raise SystemExit(1)
        if confirm.strip() != "confirm nuke":
            self.log.info("Nuke operation cancelled.")
            raise SystemExit(0)
        self.log.info("Proceeding with Docker nuke...")
        try:
            self._run_command(
                [
                    "docker",
                    "compose",
                    "-f",
                    self._DOCKER_COMPOSE_FILE,
                    "down",
                    "--volumes",
                    "--remove-orphans",
                ],
                check=False,
            )
        except Exception as e:
            self.log.warning("Error during compose down (continuing): %s", e)
        try:
            self._run_command(
                ["docker", "system", "prune", "-a", "--volumes", "--force"],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            self.log.critical("docker system prune failed (code %s).", e.returncode)
            raise SystemExit(1)
        self.log.info("*** Docker Nuke Complete ***")

    def _handle_down(self):
        target_services = self.args.services or []
        volume_flag = False
        if self.args.clear_volumes:
            self.log.warning("Volume removal requested.")
            try:
                confirm = (
                    input(
                        f">>> Remove volumes for {'ALL' if not target_services else ', '.join(target_services)} services? (yes/no): "
                    )
                    .lower()
                    .strip()
                )
            except EOFError:
                self.log.error("Volume deletion confirmation requires interactive input. Aborting.")
                raise SystemExit(1)
            if confirm == "yes":
                volume_flag = True
                self.log.info("Confirmed volume removal.")
            else:
                self.log.info("Volume deletion cancelled. Stopping containers only.")
        down_cmd = ["docker", "compose", "-f", self._DOCKER_COMPOSE_FILE, "down"]
        if volume_flag:
            down_cmd.append("--volumes")
        down_cmd.append("--remove-orphans")
        if target_services:
            down_cmd.extend(target_services)
        try:
            self._run_command(down_cmd, check=False)
        except Exception as e:
            self.log.error("Error during docker compose down: %s", e)

    def _handle_build(self):
        target_services = self.args.services or []
        build_cmd = ["docker", "compose", "-f", self._DOCKER_COMPOSE_FILE, "build"]
        if self.args.no_cache:
            build_cmd.append("--no-cache")
        if self.args.parallel:
            build_cmd.append("--parallel")
        if target_services:
            build_cmd.extend(target_services)
        t_start = time.time()
        try:
            self._run_command(build_cmd, check=True)
            self.log.info("Build completed in %.2f seconds.", time.time() - t_start)
            if self.args.tag:
                self._tag_images(self.args.tag, targeted_services=target_services or None)
        except subprocess.CalledProcessError as e:
            self.log.critical("Docker build failed (code %s). Check logs above.", e.returncode)
            raise SystemExit(1)

    def _handle_logs(self):
        logs_cmd = ["docker", "compose", "-f", self._DOCKER_COMPOSE_FILE, "logs"]
        if self.args.follow:
            logs_cmd.append("-f")
        if self.args.tail:
            logs_cmd.extend(["--tail", str(self.args.tail)])
        if self.args.timestamps:
            logs_cmd.append("-t")
        if self.args.no_log_prefix:
            logs_cmd.append("--no-log-prefix")
        if self.args.services:
            logs_cmd.extend(self.args.services)
        try:
            self._run_command(logs_cmd, check=False)
        except KeyboardInterrupt:
            self.log.info("\nLog streaming interrupted by user (Ctrl+C).")
        except Exception as e:
            self.log.error("Error fetching logs: %s", e)

    def _tag_images(self, tag, targeted_services=None):
        if not (tag and self._has_docker()):
            return
        try:
            config_res = self._run_command(
                [
                    "docker",
                    "compose",
                    "-f",
                    self._DOCKER_COMPOSE_FILE,
                    "config",
                    "--format",
                    "json",
                ],
                capture_output=True,
                check=True,
                suppress_logs=True,
            )
            services_data = json.loads(config_res.stdout).get("services", {})
            tagged = skipped = errors = 0
            for svc_name, svc_config in services_data.items():
                if targeted_services and svc_name not in targeted_services:
                    continue
                image_name = svc_config.get("image")
                if not image_name:
                    skipped += 1
                    continue
                base_image = image_name.split(":")[0]
                new_tag = f"{base_image}:{tag}"
                self.log.info("Tagging: %s  ->  %s", image_name, new_tag)
                try:
                    self._run_command(
                        ["docker", "tag", image_name, new_tag], check=True, suppress_logs=True
                    )
                    tagged += 1
                except Exception as e:
                    self.log.error("Failed to tag '%s': %s", image_name, e)
                    errors += 1
            self.log.log(
                logging.WARNING if errors else logging.INFO,
                "Tagging complete. %d tagged, %d skipped, %d errors.",
                tagged,
                skipped,
                errors,
            )
        except Exception as e:
            self.log.error("Error during image tagging: %s", e)

    def _handle_up(self):
        if not os.path.exists(self._ENV_FILE):
            self.log.error(
                "Required '%s' file is missing. Cannot run 'docker compose up'.", self._ENV_FILE
            )
            raise SystemExit(1)
        load_dotenv(dotenv_path=self._ENV_FILE, override=True)

        up_cmd = ["docker", "compose", "-f", self._DOCKER_COMPOSE_FILE, "up"]
        if not self.args.attached:
            up_cmd.append("-d")
        if self.args.build_before_up:
            up_cmd.append("--build")
            if self.args.no_cache:
                up_cmd.append("--no-cache")
        if self.args.force_recreate:
            up_cmd.append("--force-recreate")

        # ── Resolve which services to actually start ───────────────────
        exclude = set(self.args.exclude or [])
        target = list(self.args.services or [])

        if exclude:
            all_svcs = self._get_all_services()
            unknown = exclude - set(all_svcs)
            if unknown:
                self.log.warning(
                    "Excluded service(s) not found in compose file (typo?): %s",
                    ", ".join(sorted(unknown)),
                )
            if target:
                # Honour explicit --services list, just filter out excluded ones
                target = [s for s in target if s not in exclude]
            else:
                target = [s for s in all_svcs if s not in exclude]
            self.log.info(
                "Starting services (excluding %s): %s",
                ", ".join(sorted(exclude)),
                ", ".join(target),
            )
        # ───────────────────────────────────────────────────────────────

        if target:
            up_cmd.extend(target)

        try:
            self._run_command(up_cmd, check=True, suppress_logs=self.args.attached)
            self.log.info("docker compose up executed successfully.")
            if not self.args.attached:
                logs_hint = [
                    "docker",
                    "compose",
                    "-f",
                    self._DOCKER_COMPOSE_FILE,
                    "logs",
                    "-f",
                    "--tail=50",
                ]
                if target:
                    logs_hint.extend(target)
                self.log.info("To view logs, run: %s", " ".join(logs_hint))
        except subprocess.CalledProcessError as e:
            self.log.critical("'docker compose up' failed (code %s).", e.returncode)
            try:
                logs_cmd = [
                    "docker",
                    "compose",
                    "-f",
                    self._DOCKER_COMPOSE_FILE,
                    "logs",
                    "--tail=100",
                ]
                if target:
                    logs_cmd.extend(target)
                self._run_command(logs_cmd, check=False)
            except Exception:
                pass
            raise SystemExit(1)

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    def run(self):
        start = time.time()
        self.log.info("Docker Manager started. Mode: %s", self.args.mode)

        if self.args.debug_cache:
            self._run_docker_cache_diagnostics()
            raise SystemExit(0)
        if self.args.nuke:
            self._handle_nuke()
            raise SystemExit(0)

        if not self._has_docker():
            raise SystemExit(1)

        if self.args.with_ollama:
            if not self._ensure_ollama(opt_in=True, use_gpu=self.args.ollama_gpu):
                self.log.warning("External Ollama setup had issues. Continuing...")

        mode = self.args.mode

        if mode == "logs":
            self._handle_logs()
            raise SystemExit(0)

        if self.args.down or self.args.clear_volumes:
            self._handle_down()
            if mode == "down_only":
                self.log.info("Mode 'down_only' complete.")
                raise SystemExit(0)

        if mode in ("build", "both"):
            self._handle_build()
            if mode == "build":
                self.log.info("Mode 'build' complete.")
                raise SystemExit(0)

        if mode in ("up", "both"):
            self._handle_up()

        self.log.info("Docker Manager finished in %.2f seconds.", time.time() - start)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def docker_manager(
    # --- Mode ---
    mode: str = typer.Option(
        "up",
        "--mode",
        help="Primary action: up | build | both | down_only | logs",
        show_default=True,
    ),
    # --- Targeting ---
    services: Optional[List[str]] = typer.Option(
        None,
        "--services",
        help="Target specific service(s) defined in docker-compose.yml.",
    ),
    exclude: Optional[List[str]] = typer.Option(
        None,
        "--exclude",
        "-x",
        help=(
            "Exclude one or more services from 'up'. "
            "Useful to skip heavy services like 'ollama' or 'vllm' locally. "
            "Repeat for multiple: --exclude ollama --exclude vllm"
        ),
    ),
    # --- Build ---
    no_cache: bool = typer.Option(False, "--no-cache", help="Build without Docker cache."),
    parallel: bool = typer.Option(False, "--parallel", help="Build images in parallel."),
    tag: Optional[str] = typer.Option(None, "--tag", help="Tag built images with this label."),
    # --- Up ---
    attached: bool = typer.Option(False, "--attached", "-a", help="Run 'up' in foreground."),
    build_before_up: bool = typer.Option(
        False, "--build-before-up", help="Build before running 'up'."
    ),
    force_recreate: bool = typer.Option(
        False, "--force-recreate", help="Force-recreate containers even if unchanged."
    ),
    # --- Down / Cleanup ---
    down: bool = typer.Option(
        False, "--down", help="Run 'docker compose down' before other actions."
    ),
    clear_volumes: bool = typer.Option(
        False, "--clear-volumes", "-v", help="Remove volumes when running 'down'."
    ),
    nuke: bool = typer.Option(
        False,
        "--nuke",
        help="DANGER: Stop stack, remove volumes, and prune ALL unused Docker data system-wide.",
    ),
    # --- Logs ---
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream log output."),
    tail: Optional[int] = typer.Option(None, "--tail", help="Number of log lines to show."),
    timestamps: bool = typer.Option(False, "--timestamps", "-t", help="Show timestamps in logs."),
    no_log_prefix: bool = typer.Option(
        False, "--no-log-prefix", help="Omit service name prefix in logs."
    ),
    # --- Ollama ---
    with_ollama: bool = typer.Option(
        False, "--with-ollama", help="Start/manage an external Ollama container."
    ),
    ollama_gpu: bool = typer.Option(
        False,
        "--ollama-gpu",
        help="Start Ollama with GPU support (requires NVIDIA toolkit).",
    ),
    # --- Diagnostics ---
    verbose: bool = typer.Option(False, "--verbose", "--debug", help="Enable debug logging."),
    debug_cache: bool = typer.Option(
        False, "--debug-cache", help="Run build-cache diagnostics and exit."
    ),
) -> None:
    """
    Manage Docker Compose stack: build, run, configure .env, and optionally
    manage an external Ollama container.

    Safe for repeated use — generates .env only when missing, never overwrites
    an existing one automatically.

    Examples:
      entities-api docker-manager --mode up --exclude ollama --exclude vllm
      entities-api docker-manager --mode up -x ollama -x vllm
    """
    # --- Validate mode choice ---
    valid_modes = {"up", "build", "both", "down_only", "logs"}
    if mode not in valid_modes:
        typer.echo(
            f"[error] Invalid --mode '{mode}'. Choose from: {', '.join(sorted(valid_modes))}",
            err=True,
        )
        raise SystemExit(1)

    # --- Validate exclusive flags ---
    exclusive = [f for f, v in [("--nuke", nuke), ("--debug-cache", debug_cache)] if v]
    if len(exclusive) > 1:
        typer.echo(
            f"[error] {' and '.join(exclusive)} are exclusive. Use only one at a time.", err=True
        )
        raise SystemExit(1)

    # --- Validate build-before-up combinations ---
    if build_before_up and mode in ("build", "down_only", "both"):
        typer.echo(
            f"[error] --build-before-up is redundant / invalid with --mode={mode}.", err=True
        )
        raise SystemExit(1)

    # --- Validate --exclude is only meaningful for 'up' / 'both' ---
    if exclude and mode not in ("up", "both"):
        typer.echo(
            f"[error] --exclude is only applicable with --mode=up or --mode=both (got '{mode}').",
            err=True,
        )
        raise SystemExit(1)

    # --- Implied behaviours ---
    if clear_volumes:
        down = True  # --clear-volumes implies --down

    # If only --down/--clear-volumes given with default mode 'up', treat as down_only
    build_flags = any([tag, no_cache, parallel, build_before_up])
    up_flags = any([attached, force_recreate])
    if down and mode == "up" and not (build_flags or up_flags):
        mode = "down_only"

    # --- Assemble args namespace for DockerManager ---
    args = SimpleNamespace(
        mode=mode,
        services=services or [],
        exclude=exclude or [],
        no_cache=no_cache,
        parallel=parallel,
        tag=tag,
        attached=attached,
        build_before_up=build_before_up,
        force_recreate=force_recreate,
        down=down,
        clear_volumes=clear_volumes,
        nuke=nuke,
        follow=follow,
        tail=tail,
        timestamps=timestamps,
        no_log_prefix=no_log_prefix,
        with_ollama=with_ollama,
        ollama_gpu=ollama_gpu,
        verbose=verbose,
        debug_cache=debug_cache,
    )

    # --- Ensure docker-compose.yml exists before DockerManager initialises ---
    try:
        from entities_api.cli.generate_docker_compose import \
            generate_dev_docker_compose  # noqa: PLC0415

        generate_dev_docker_compose()
        time.sleep(0.5)
    except ImportError as exc:
        typer.echo(
            f"[error] Could not import generate_dev_docker_compose: {exc}\n"
            "Ensure the package is installed (`pip install -e .`) or run from the project root.",
            err=True,
        )
        raise SystemExit(1)
    except Exception as exc:
        typer.echo(f"[error] Failed to generate docker-compose.yml: {exc}", err=True)
        raise SystemExit(1)

    # --- Run ---
    try:
        manager = DockerManager(args)
        manager.run()
    except KeyboardInterrupt:
        typer.echo("\nOperation cancelled by user (Ctrl+C).")
        raise SystemExit(130)
    except SystemExit:
        raise
    except subprocess.CalledProcessError as exc:
        typer.echo(
            f"[error] A critical command failed (code {exc.returncode}). See logs above.", err=True
        )
        raise SystemExit(exc.returncode or 1)
    except Exception as exc:
        typer.echo(f"[error] Unexpected error: {exc}", err=True)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Allow `python -m entities_api.cli.docker_manager` as a fallback
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app()
