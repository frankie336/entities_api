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
from os.path import getsize, islink
from pathlib import Path
import secrets

from dotenv import load_dotenv, dotenv_values

# Standard Python logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


class DockerManager:
    """Manages Docker Compose stack operations, env setup, and optional Ollama integration."""

    # --- Class Attributes ---
    # Define the SINGLE example file we want to ensure exists
    _ENV_EXAMPLE_FILE = ".env.example"
    # Define the SINGLE actual .env file needed by compose commands
    _ENV_FILE = ".env"

    _OLLAMA_IMAGE = "ollama/ollama"
    _OLLAMA_CONTAINER = "ollama"
    _OLLAMA_PORT = "11434"

    # --- Initialization ---
    def __init__(self, args):
        """
        Initializes the DockerManager.

        Args:
            args (argparse.Namespace): Parsed command-line arguments.
        """
        self.args = args
        self.is_windows = platform.system() == "Windows"
        self.log = log  # Use the module-level logger

        if self.args.verbose:
            self.log.setLevel(logging.DEBUG)
        self.log.debug("DockerManager initialized with args: %s", args)

        # Initial setup steps
        self._ensure_env_example_file()  # Ensure example file exists
        self._check_for_required_env_file()  # Check (and create if missing) the actual .env file
        self._configure_shared_path()  # Configure and create SHARED_PATH
        self._ensure_dockerignore()

    # --- Core Docker/System Command Execution ---
    def _run_command(self, cmd_list, check=True, capture_output=False, text=True, suppress_logs=False, **kwargs):
        """Helper method to run shell commands using subprocess."""
        if not suppress_logs:
            self.log.info("Running command: %s", " ".join(cmd_list))
        try:
            result = subprocess.run(
                cmd_list, check=check, capture_output=capture_output, text=text,
                shell=self.is_windows, **kwargs
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
            self.log.error(f"Error running command {' '.join(cmd_list)}: {e}", exc_info=self.args.verbose)
            raise

    # --- .dockerignore Generation ---
    def _ensure_dockerignore(self):
        """Generates a default .dockerignore file if it doesn't exist."""
        dockerignore = Path(".dockerignore")
        if not dockerignore.exists():
            self.log.warning(".dockerignore not found. Generating default...")
            dockerignore.write_text(
                "__pycache__/\n.venv/\nnode_modules/\n*.log\n*.pyc\n.git/\n.env*\n.env\n*.sqlite\ndist/\nbuild/\ncoverage/\ntmp/\n*.egg-info/\n"
            )
            self.log.info("Generated default .dockerignore.")

    # --- Environment File Generation ---
    def _generate_dot_env_example_file(self):
        """Generates the .env.example file with default placeholder content."""
        target_example_file = self._ENV_EXAMPLE_FILE
        self.log.info(f"Generating default example environment file: {target_example_file}...")
        default_content = """# .env - Environment variables for Entities API Docker setup
# Copy this file to .env and replace placeholder values (__PLACEHOLDER__)

# --- Database ---
MYSQL_HOST=db
MYSQL_PORT=3306
MYSQL_USER=root
# !! IMPORTANT: Replace __MYSQL_ROOT_PASSWORD__ with a strong password !!
MYSQL_ROOT_PASSWORD=__MYSQL_ROOT_PASSWORD__
MYSQL_DATABASE=__MYSQL_DATABASE__
# !! IMPORTANT: Replace __MYSQL_PASSWORD__ with a strong password for the app user !!
MYSQL_USER_APP=app_user
MYSQL_PASSWORD=__MYSQL_PASSWORD__

# --- Application Settings ---
# !! IMPORTANT: Replace __DEFAULT_SECRET_KEY__ with a long random string (e.g., openssl rand -hex 32) !!
SECRET_KEY=__DEFAULT_SECRET_KEY__
# !! IMPORTANT: Replace __SIGNED_URL_SECRET__ with a different long random string !!
SIGNED_URL_SECRET=__SIGNED_URL_SECRET__
# !! IMPORTANT: Replace __DEFAULT_API_KEY__ with the key clients will use !!
API_KEY=__DEFAULT_API_KEY__
API_BASE_URL=http://localhost:9000
# Optionally, set API_BASE_URL_INTERNAL for Docker network communication:
# API_BASE_URL_INTERNAL=http://fastapi_cosmic_catalyst:9000

# --- External Services (Docker Service Names) ---
QDRANT_HOST=qdrant_server
QDRANT_PORT=6333
OLLAMA_HOST=ollama
OLLAMA_PORT=11434

# --- File Storage (Samba Example) ---
# Set SHARED_PATH externally if needed
SMBCLIENT_SERVER=samba_server
SMBCLIENT_SHARE=cosmic_share
SMBCLIENT_USERNAME=samba_user
SMBCLIENT_PASSWORD=default
SMBCLIENT_PORT=445

# --- Tool IDs (Generated placeholders, replace if needed) ---
TOOL_CODE_INTERPRETER=tool___TOOL_CODE_INTERPRETER__
TOOL_WEB_SEARCH=tool___TOOL_WEB_SEARCH__
TOOL_COMPUTER=tool___TOOL_COMPUTER__
TOOL_VECTOR_STORE_SEARCH=tool___TOOL_VECTOR_STORE_SEARCH__

# --- Other ---
LOG_LEVEL=INFO
PYTHONUNBUFFERED=1
"""
        try:
            with open(target_example_file, "w", encoding="utf-8") as f:
                f.write(default_content)
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
            self.log.info("[ENV SCAN] Generated missing example file. Please copy it to .env and fill in the necessary values.")
        else:
            self.log.info(f"[ENV SCAN] Example environment file {self._ENV_EXAMPLE_FILE} is present.")

    def _generate_dot_env_file(self):
        """Generates a new .env file with secure, randomly generated real values."""
        self.log.info("Generating a new .env file with fresh real values...")
        content = (
            f"# Auto-generated .env file with real values\n"
            f"MYSQL_ROOT_PASSWORD={secrets.token_hex(16)}\n"
            f"MYSQL_DATABASE=cosmic_catalyst\n"
            f"MYSQL_USER=ollama\n"
            f"MYSQL_PASSWORD={secrets.token_hex(16)}\n\n"
            f"SECRET_KEY={secrets.token_hex(32)}\n"
            f"SIGNED_URL_SECRET={secrets.token_hex(32)}\n"
            f"API_KEY={secrets.token_hex(16)}\n\n"
            f"ASSISTANTS_BASE_URL=http://localhost:9000/\n"
            f"SANDBOX_SERVER_URL=http://sandbox:8000\n"
            f"DOWNLOAD_BASE_URL=http://localhost:9000/v1/files/download\n\n"
            f"QDRANT_URL=http://qdrant:6333\n\n"
            f"SMBCLIENT_SERVER=samba_server\n"
            f"SMBCLIENT_SHARE=cosmic_share\n"
            f"SMBCLIENT_USERNAME=samba_user\n"
            f"SMBCLIENT_PASSWORD=default\n"
            f"SMBCLIENT_PORT=445\n\n"
            f"TOOL_CODE_INTERPRETER=tool_{secrets.token_hex(4)}\n"
            f"TOOL_WEB_SEARCH=tool_{secrets.token_hex(4)}\n"
            f"TOOL_COMPUTER=tool_{secrets.token_hex(4)}\n"
            f"TOOL_VECTOR_STORE_SEARCH=tool_{secrets.token_hex(4)}\n"
        )
        try:
            with open(self._ENV_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            self.log.info("Generated new .env file with real values.")
        except Exception as e:
            self.log.error(f"Failed to generate .env file: {e}")
            sys.exit(1)

    def _check_for_required_env_file(self):
        """Checks if the actual .env file needed for compose exists; if not, generate it."""
        self.log.debug(f"[ENV SCAN] Checking for required '{self._ENV_FILE}' file...")
        if not os.path.exists(self._ENV_FILE):
            self.log.warning(f"[ENV SCAN] Required environment file '{self._ENV_FILE}' is missing.")
            self._generate_dot_env_file()
        else:
            self.log.debug(f"[ENV SCAN] Required environment file '{self._ENV_FILE}' exists; not modifying it.")

    # --- Shared Path Configuration ---
    def _configure_shared_path(self):
        """Configures the SHARED_PATH environment variable based on OS and creates the directory."""
        system = platform.system().lower()
        shared_path_env = os.environ.get('SHARED_PATH')
        if shared_path_env:
            shared_path = shared_path_env
            self.log.info("Using existing SHARED_PATH from environment: %s", shared_path)
        else:
            default_base = os.path.expanduser("~")
            if system == 'windows':
                shared_path = os.path.join(default_base, "entities_share")
            elif system == 'linux':
                shared_path = os.path.join(default_base, ".local", "share", "entities_share")
            elif system == 'darwin':
                shared_path = os.path.join(default_base, "Library", "Application Support", "entities_share")
            else:
                self.log.error("Unsupported OS: %s. Cannot set default SHARED_PATH.", system)
                raise RuntimeError("Unsupported OS")
            self.log.info("Defaulting SHARED_PATH to: %s", shared_path)
            os.environ['SHARED_PATH'] = shared_path
        try:
            Path(shared_path).mkdir(parents=True, exist_ok=True)
            self.log.info("Ensured shared directory exists: %s", shared_path)
        except OSError as e:
            self.log.error(f"Failed to create shared directory {shared_path}: {e}. Check permissions.")

    # --- Ollama Integration ---
    def _has_docker(self):
        return shutil.which("docker") is not None

    def _is_container_running(self, container_name):
        try:
            result = self._run_command(["docker", "ps", "--filter", f"name=^{container_name}$", "--quiet"],
                                       capture_output=True, text=True, check=False, suppress_logs=True)
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(f"Could not check container '{container_name}' status: {e}")
            return False

    def _is_image_present(self, image_name):
        try:
            result = self._run_command(["docker", "images", image_name, "--quiet"],
                                       capture_output=True, text=True, check=False, suppress_logs=True)
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(f"Could not check image '{image_name}' presence: {e}")
            return False

    def _has_nvidia_support(self):
        has_smi = shutil.which("nvidia-smi") is not None
        if has_smi:
            try:
                self._run_command(["nvidia-smi"], check=True, capture_output=True, suppress_logs=True)
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                self.log.warning("nvidia-smi failed. Assuming no GPU.")
                return False
        return False

    def _start_ollama(self, cpu_only=True):
        if not self._has_docker():
            self.log.error("❌ Docker not found.")
            return False
        container_name = self._OLLAMA_CONTAINER
        if self._is_container_running(container_name):
            self.log.info(f"✅ Ollama '{container_name}' running.")
            return True
        image_name = self._OLLAMA_IMAGE
        if not self._is_image_present(image_name):
            self.log.info(f"📦 Pulling Ollama image '{image_name}'...")
            try:
                self._run_command(["docker", "pull", image_name], check=True)
            except Exception as e:
                self.log.error(f"❌ Failed to pull Ollama image: {e}")
                return False
        self.log.info(f"🚀 Starting Ollama container '{container_name}'...")
        cmd = ["docker", "run", "-d", "--rm", "-v", "ollama:/root/.ollama", "-p", f"{self._OLLAMA_PORT}:{self._OLLAMA_PORT}", "--name", container_name]
        if not cpu_only and self._has_nvidia_support():
            self.log.info("   Adding --gpus=all flag.")
            cmd.insert(2, "--gpus=all")
        elif not cpu_only:
            self.log.warning("   GPU requested but support check failed. CPU mode.")
        cmd.append(image_name)
        try:
            self._run_command(cmd, check=True)
            time.sleep(3)
            if self._is_container_running(container_name):
                self.log.info(f"✅ Ollama '{container_name}' started.")
                return True
            else:
                self.log.error(f"❌ Ollama '{container_name}' failed to start. Logs:")
                try:
                    self._run_command(["docker", "logs", container_name], check=False, suppress_logs=False)
                except Exception:
                    pass
                return False
        except Exception as e:
            self.log.error(f"❌ Failed to start Ollama container: {e}")
            return False

    def _ensure_ollama(self, opt_in=False, use_gpu=False):
        if not opt_in:
            self.log.info("ℹ️ Ollama opt-in. Skipping.")
            return True
        self.log.info("--- Ollama Setup ---")
        if os.path.exists("/.dockerenv") or os.environ.get("DOCKER_HOST"):
            self.log.warning("🛰 Running inside container? Skipping external Ollama.")
            return True
        if platform.system() == "Darwin":
            self.log.warning("⚠️ macOS: Docker GPU unsupported. Install native Ollama app.")
            return True
        gpu_mode = use_gpu and self._has_nvidia_support()
        if use_gpu and not gpu_mode:
            self.log.warning("⚠️ GPU requested, but support not found. CPU mode.")
        mode_str = "GPU" if gpu_mode else "CPU"
        self.log.info(f"Attempting to start Ollama in {mode_str} mode...")
        success = self._start_ollama(cpu_only=not gpu_mode)
        self.log.info("--- End Ollama Setup ---")
        return success

    # --- Docker Cache Diagnostics ---
    def _get_directory_size(self, path="."):
        total_size = 0
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                try:
                    fp = os.path.join(dirpath, f)
                    if not islink(fp):
                        total_size += getsize(fp)
                except OSError as e:
                    self.log.debug("Skip size check for %s: %s", fp, e)
                except Exception as e:
                    self.log.warning("Skip size check for %s: %s", fp, e)
        return total_size / (1024 * 1024)

    def _run_docker_cache_diagnostics(self):
        self.log.info("--- Docker Cache Diagnostics ---")
        try:
            self.log.info("Approx context size: %.2f MB", self._get_directory_size())
            ps_config = self._run_command(["docker", "compose", "config", "--services"],
                                          capture_output=True, text=True, check=False)
            services = ps_config.stdout.strip().splitlines() if ps_config.returncode == 0 else []
            if not services:
                self.log.warning("Could not get services from docker-compose config.")
                return
            self.log.info("Services: %s", ", ".join(services))
            for service in services:
                self.log.info(f"History for potential image '{service}':")
                try:
                    history = self._run_command(["docker", "history", service, "--no-trunc", "--format", "{{.ID}}: {{.CreatedBy}}"],
                                                check=False, capture_output=True, text=True)
                    if history.returncode == 0 and history.stdout.strip():
                        self.log.info("History:\n%s", history.stdout.strip())
                    elif history.returncode == 0:
                        self.log.info("No history found.")
                    else:
                        self.log.warning(f"Could not get history. Error:\n{history.stderr.strip()}")
                except Exception as e:
                    self.log.warning(f"Error getting history: {e}")
        except Exception as e:
            self.log.error("Failed during Docker diagnostics: %s", e)
        self.log.info("--- End Docker Cache Diagnostics ---")

    # --- Docker Compose Actions ---
    def _handle_nuke(self):
        self.log.warning("!!! NUKE MODE: ALL DOCKER DATA WIPED (containers, volumes, networks, images) !!!")
        try:
            confirm = input("Are you absolutely sure? (yes/no): ").lower()
        except EOFError:
            self.log.error("Nuke needs interactive confirm.")
            sys.exit(1)
        if confirm != "yes":
            self.log.info("Nuke cancelled.")
            sys.exit(0)
        self.log.info("Proceeding with Docker nuke...")
        try:
            self._run_command(["docker", "compose", "down", "--volumes", "--remove-orphans"], check=False)
            self._run_command(["docker", "system", "prune", "-a", "--volumes", "--force"], check=True)
            self.log.info("Docker environment nuked successfully.")
        except Exception as e:
            self.log.critical("Nuke failed: %s", e)
            sys.exit(1)

    def _handle_down(self):
        target_services = self.args.services or []
        target_desc = f" for services: {', '.join(target_services)}" if target_services else ""
        action = "Stopping containers & removing volumes" if self.args.clear_volumes else "Stopping containers"
        self.log.info(f"{action}{target_desc}...")
        if self.args.clear_volumes and not target_services:
            try:
                confirm = input("Delete ALL project volumes? (yes/no): ").lower()
            except EOFError:
                self.log.error("Confirm needed.")
                sys.exit(1)
            if confirm != "yes":
                self.log.info("Volume delete cancelled.")
                sys.exit(0)
        elif self.args.clear_volumes and target_services:
            self.log.warning("Note: --clear-volumes + services might not remove shared volumes.")
        down_cmd = ["docker", "compose", "down", "--remove-orphans"]
        if self.args.clear_volumes:
            down_cmd.append("--volumes")
        if target_services:
            down_cmd.extend(target_services)
        try:
            self._run_command(down_cmd, check=False)
            self.log.info(f"{action} complete.")
        except Exception as e:
            self.log.error(f"docker-compose down failed: {e}")
            sys.exit(1)

    def _handle_build(self):
        """Handles building the Docker images using docker-compose build."""
        env_file = self._ENV_FILE
        if not os.path.exists(env_file):
            self.log.error(f"Required environment file '{env_file}' is missing.")
            self.log.error(f"Please create it (e.g., copy '{self._ENV_EXAMPLE_FILE}') and fill in values.")
            sys.exit(1)
        load_dotenv(dotenv_path=env_file)
        self.log.info(f"Loaded environment variables from '{env_file}'.")
        target_services = self.args.services or []
        target_desc = f" for services: {', '.join(target_services)}" if target_services else " all services"
        cache_desc = " (no cache)" if self.args.no_cache else ""
        self.log.info(f"Building images{target_desc}{cache_desc}...")
        build_cmd = ["docker", "compose", "build"]
        if self.args.no_cache:
            build_cmd.append("--no-cache")
        if target_services:
            build_cmd.extend(target_services)
        t_start = time.time()
        try:
            self._run_command(build_cmd, check=True)
            t_end = time.time()
            self.log.info("Build completed in %.2f seconds.", t_end - t_start)
            if self.args.tag:
                self.log.info(f"Applying tag: {self.args.tag} (targets: {target_services if target_services else 'all'})")
                self._tag_images(self.args.tag, targeted_services=target_services)
        except Exception as e:
            self.log.critical(f"Docker build failed: {e}")
            sys.exit(1)

    def _tag_images(self, tag, targeted_services=None):
        """Tags built images from docker-compose with the given tag."""
        try:
            self.log.info("Inspecting compose config for image mappings...")
            service_config_json = self._run_command(["docker", "compose", "config", "--format", "json"],
                                                    capture_output=True, check=True).stdout
            services = json.loads(service_config_json).get("services", {})
            if not services:
                self.log.warning("No services found in compose config.")
                return
            tagged_count = 0
            for service_name, config in services.items():
                if targeted_services and service_name not in targeted_services:
                    continue
                image_name = config.get("image")
                if not image_name or not (image_name.startswith("entities_api/") or image_name.startswith("entities_")):
                    continue
                base_image_parts = image_name.split(":")
                base_image = base_image_parts[0]
                original_ref = f"{base_image}:latest"
                inspect_res = self._run_command(["docker", "image", "inspect", original_ref],
                                                check=False, capture_output=True, suppress_logs=True)
                if inspect_res.returncode != 0:
                    self.log.debug(f"Image '{original_ref}' not found for '{service_name}'. Trying full name from compose...")
                    if len(base_image_parts) > 1:
                        original_ref = image_name
                    else:
                        self.log.warning(f"Skipping tag for '{service_name}': base image '{original_ref}' not found.")
                        continue
                    inspect_res_alt = self._run_command(["docker", "image", "inspect", original_ref],
                                                        check=False, capture_output=True, suppress_logs=True)
                    if inspect_res_alt.returncode != 0:
                        self.log.warning(f"Skipping tag for '{service_name}': compose image '{original_ref}' not found.")
                        continue
                    else:
                        self.log.debug(f"Found image '{original_ref}' (from compose).")
                new_tag = f"{base_image}:{tag}"
                self.log.info(f"Tagging {original_ref} -> {new_tag}")
                try:
                    self._run_command(["docker", "tag", original_ref, new_tag], check=True)
                    tagged_count += 1
                except Exception as tag_e:
                    self.log.error(f"Failed to tag {original_ref}: {tag_e}")
            self.log.info(f"Tagging complete. {tagged_count} images tagged.")
        except json.JSONDecodeError as e:
            self.log.error("Failed to parse compose config: %s", e)
        except subprocess.CalledProcessError as e:
            self.log.error("Failed to run 'docker compose config': %s", e)
        except Exception as e:
            self.log.error(f"Image tagging failed: {e}", exc_info=self.args.verbose)

    def _handle_up(self):
        """Handles starting the Docker containers using docker-compose up."""
        env_file = self._ENV_FILE
        if not os.path.exists(env_file):
            self.log.error(f"Required environment file '{env_file}' is missing for 'up' command.")
            self.log.error(f"Please create it (e.g., copy '{self._ENV_EXAMPLE_FILE}') and fill in values.")
            sys.exit(1)
        load_dotenv(dotenv_path=env_file)
        self.log.debug(f"Ensured environment variables loaded from '{env_file}'.")
        mode = "attached" if self.args.attached else "detached"
        target_services = self.args.services or []
        target_desc = f" for services: {', '.join(target_services)}" if target_services else ""
        self.log.info(f"Starting containers{target_desc} ({mode} mode)...")
        up_cmd = ["docker", "compose", "up"]
        if not self.args.attached:
            up_cmd.append("-d")
        if target_services:
            up_cmd.extend(target_services)
        try:
            self._run_command(up_cmd, check=True)
            self.log.info("Containers started successfully.")
            if not self.args.attached:
                logs_cmd = ["docker", "compose", "logs", "-f"]
                if target_services:
                    logs_cmd.extend(target_services)
                self.log.info(f"View logs with: {' '.join(logs_cmd)}")
        except Exception as e:
            self.log.critical(f"Docker up failed: {e}")
            if not self.args.attached:
                self.log.info("Attempting to show logs from failed startup...")
                try:
                    logs_cmd = ["docker", "compose", "logs", "--tail=100"]
                    if target_services:
                        logs_cmd.extend(target_services)
                    self._run_command(logs_cmd, check=False)
                except Exception as log_e:
                    self.log.error(f"Could not fetch logs: {log_e}")
            sys.exit(1)

    def run(self):
        """Main execution logic based on parsed arguments."""
        if self.args.debug_cache:
            self._run_docker_cache_diagnostics()
            sys.exit(0)
        if self.args.nuke:
            self._handle_nuke()
            sys.exit(0)
        ollama_ok = self._ensure_ollama(opt_in=self.args.with_ollama, use_gpu=self.args.ollama_gpu)
        if not ollama_ok and self.args.with_ollama:
            self.log.error("Ollama setup failed.")
        if self.args.down or self.args.clear_volumes:
            self._handle_down()
            if self.args.mode == 'down_only':
                sys.exit(0)
        if self.args.mode in ["build", "both"]:
            if self.args.no_cache and self.args.mode not in ["build", "both"]:
                self.log.critical("--no-cache requires --mode 'build' or 'both'.")
                sys.exit(1)
            if (self.args.no_cache or self.args.tag) and not self.args.services:
                self.log.warning("Using --no-cache or --tag without --services affects ALL services.")
            self._handle_build()
        if self.args.mode in ["up", "both"]:
            self._handle_up()
        self.log.info("Docker management script finished.")

    @staticmethod
    def parse_args():
        """Parses command-line arguments."""
        parser = argparse.ArgumentParser(
            description="Manage Docker Compose stack, env setup, Ollama.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )
        parser.add_argument("--mode", choices=["up", "build", "both", "down_only"], default="up",
                            help="Action: 'build' images, 'up' containers, 'both', or 'down_only'.")
        parser.add_argument("--down", action="store_true", help="Stop and remove containers.")
        parser.add_argument("--clear-volumes", action="store_true",
                            help="With --down, also remove volumes (prompts unless --services used).")
        parser.add_argument("--no-cache", action="store_true", help="Build without cache (needs --mode build/both).")
        parser.add_argument("--attached", action="store_true", help="Run 'up' in attached mode.")
        parser.add_argument("--services", nargs='+', metavar='SERVICE',
                            help="Target specific service(s) for build/up/down.")
        parser.add_argument("--tag", type=str, help="Tag built image(s) (use with --mode build/both).")
        parser.add_argument("--with-ollama", action="store_true", help="Ensure external Ollama container runs.")
        parser.add_argument("--ollama-gpu", action="store_true", help="Attempt GPU for external Ollama.")
        parser.add_argument("--nuke", action="store_true", help="DANGER: Prune ALL Docker resources!")
        parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging.")
        parser.add_argument("--debug-cache", action="store_true", help="Run cache diagnostics and exit.")
        args = parser.parse_args()
        if (args.down or args.clear_volumes) and args.mode not in ['build', 'both']:
            args.mode = 'down_only'
        return args


if __name__ == "__main__":
    try:
        arguments = DockerManager.parse_args()
        manager = DockerManager(arguments)
        manager.run()
    except KeyboardInterrupt:
        log.info("\nOperation cancelled.")
        sys.exit(130)
    except subprocess.CalledProcessError:
        log.critical("Command failed.")
        sys.exit(1)
    except Exception as e:
        log.critical("Unexpected error: %s", e, exc_info=(log.level == logging.DEBUG))
        sys.exit(1)
