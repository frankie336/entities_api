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

load_dotenv()

class DockerManager:
    """Manages Docker Compose stack operations, env setup, and optional Ollama integration."""

    # --- Class Attributes ---
    # Define the SINGLE example file we want to ensure exists
    _ENV_EXAMPLE_FILE = ".env.example"
    # Define the SINGLE actual .env file needed by compose commands
    _ENV_FILE = ".env"

    _OLLAMA_IMAGE = "ollama/ollama"
    _OLLAMA_CONTAINER = "ollama"
    _OLLAMA_PORT = "11434" # Keep consistent port definition

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
        # Use the more comprehensive set of variables from the reference .env
        default_content = """# .env.example - Environment variables for Entities API Docker setup
# Copy this file to .env and replace placeholder values (__PLACEHOLDER__) or run the script to generate a .env

#############################
# Base URLs
#############################
# Base URL for the main API, accessible from the host machine
ASSISTANTS_BASE_URL="http://localhost:9000/"
# URL for the sandbox service, usually accessed internally by the API
SANDBOX_SERVER_URL="http://sandbox:8000"
# Base URL for file downloads, accessible from the host machine
DOWNLOAD_BASE_URL="http://localhost:9000/v1/files/download"

#############################
# Database Configuration
#############################
# Internal database connection URL used by the API service
DATABASE_URL="mysql+pymysql://__MYSQL_USER__:__MYSQL_PASSWORD__@db:3306/__MYSQL_DATABASE__"
# Optional: Database connection URL for accessing from the host machine (port might differ, e.g., 3307)
SPECIAL_DB_URL="mysql+pymysql://__MYSQL_USER__:__MYSQL_PASSWORD__@localhost:__MYSQL_EXTERNAL_PORT__/__MYSQL_DATABASE__"
# !! IMPORTANT: Replace __MYSQL_ROOT_PASSWORD__ with a strong password !!
MYSQL_ROOT_PASSWORD="__MYSQL_ROOT_PASSWORD__"
MYSQL_DATABASE="__MYSQL_DATABASE__"
# !! IMPORTANT: Replace __MYSQL_USER__ with the desired application username !!
MYSQL_USER="__MYSQL_USER__"
# !! IMPORTANT: Replace __MYSQL_PASSWORD__ with a strong password for the app user !!
MYSQL_PASSWORD="__MYSQL_PASSWORD__"
# Optional: Define the external port mapping if needed for SPECIAL_DB_URL
# MYSQL_EXTERNAL_PORT=3307

#############################
# API Keys & External Services
#############################
# !! IMPORTANT: Replace __DEFAULT_API_KEY__ with the key clients will use !!
API_KEY="__DEFAULT_API_KEY__"
# Hostname for the Qdrant vector database service
QDRANT_HOST="qdrant"
# Port for the Qdrant vector database service
QDRANT_PORT="6333"
# Hostname for the Ollama service (if used)
OLLAMA_HOST="ollama"
# Port for the Ollama service (if used)
OLLAMA_PORT="11434"

#############################
# Platform Settings
#############################
# URL for the health check endpoint
BASE_URL_HEALTH="http://localhost:9000/v1/health"
# WebSocket URL for the shell/computer tool service
SHELL_SERVER_URL="ws://sandbox_api:8000/ws/computer"
# WebSocket URL for the code execution service
CODE_EXECUTION_URL="ws://sandbox_api:8000/ws/execute"
# !! IMPORTANT: Replace __SIGNED_URL_SECRET__ with a different long random string !!
SIGNED_URL_SECRET="__SIGNED_URL_SECRET__"
# !! IMPORTANT: Replace __SECRET_KEY__ with a long random string for session/cookie security !!
SECRET_KEY="__SECRET_KEY__"
# Disable Firejail sandboxing (true/false) - Set to true if issues arise or not needed
DISABLE_FIREJAIL="true"

#############################
# SMB Client Configuration
#############################
SMBCLIENT_SERVER="samba_server"
SMBCLIENT_SHARE="cosmic_share"
SMBCLIENT_USERNAME="samba_user"
SMBCLIENT_PASSWORD="default"
SMBCLIENT_PORT="445"

#############################
# Tool Identifiers (Generated placeholders, replace if needed)
#############################
TOOL_CODE_INTERPRETER="tool___TOOL_CODE_INTERPRETER__"
TOOL_WEB_SEARCH="tool___TOOL_WEB_SEARCH__"
TOOL_COMPUTER="tool___TOOL_COMPUTER__"
TOOL_VECTOR_STORE_SEARCH="tool___TOOL_VECTOR_STORE_SEARCH__"

#############################
# Other
#############################
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
            self.log.info("[ENV SCAN] Generated missing example file. You might need to copy it to .env and fill in values, or let the script generate .env.")
        else:
            self.log.info(f"[ENV SCAN] Example environment file {self._ENV_EXAMPLE_FILE} is present.")

    def _generate_dot_env_file(self):
        """Generates a new .env file with secure, randomly generated real values based on reference."""
        self.log.info("Generating a new .env file with fresh real values...")

        # Generate secrets
        db_user = "ollama" # Using the user from reference
        db_password = secrets.token_hex(16)
        db_root_password = secrets.token_hex(16)
        db_name = "cosmic_catalyst"
        secret_key_val = secrets.token_hex(32)
        signed_url_secret_val = secrets.token_hex(32)
        api_key_val = secrets.token_hex(16) # Or use 'your_api_key' if that's intended as a placeholder

        # Construct DB URLs
        database_url_val = f"mysql+pymysql://{db_user}:{db_password}@db:3306/{db_name}"
        # Assuming external port mapping is 3307 for host access
        special_db_url_val = f"mysql+pymysql://{db_user}:{db_password}@localhost:3307/{db_name}"

        content = f"""# Auto-generated .env file with real values
# Generated on: {time.strftime("%Y-%m-%d %H:%M:%S %Z")}

#############################
# Base URLs
#############################
ASSISTANTS_BASE_URL="http://localhost:9000/"
SANDBOX_SERVER_URL="http://sandbox:8000" # Internal Docker service name
DOWNLOAD_BASE_URL="http://localhost:9000/v1/files/download"

#############################
# Database Configuration
#############################
DATABASE_URL="{database_url_val}"
SPECIAL_DB_URL="{special_db_url_val}"
MYSQL_ROOT_PASSWORD="{db_root_password}"
MYSQL_DATABASE="{db_name}"
MYSQL_USER="{db_user}"
MYSQL_PASSWORD="{db_password}"
# MYSQL_EXTERNAL_PORT=3307 # Uncomment if needed and differs from default

#############################
# API Keys & External Services
#############################
API_KEY="{api_key_val}"
QDRANT_HOST="qdrant"
QDRANT_PORT="6333"
OLLAMA_HOST="ollama"
OLLAMA_PORT="{self._OLLAMA_PORT}" # Use class attribute

#############################
# Platform Settings
#############################
BASE_URL_HEALTH="http://localhost:9000/v1/health"
SHELL_SERVER_URL="ws://sandbox_api:8000/ws/computer"
CODE_EXECUTION_URL="ws://sandbox_api:8000/ws/execute"
SIGNED_URL_SECRET="{signed_url_secret_val}"
SECRET_KEY="{secret_key_val}"
DISABLE_FIREJAIL="true"

#############################
# SMB Client Configuration
#############################
SMBCLIENT_SERVER="samba_server"
SMBCLIENT_SHARE="cosmic_share"
SMBCLIENT_USERNAME="samba_user"
SMBCLIENT_PASSWORD="default" # Keeping default as per reference
SMBCLIENT_PORT="445"

#############################
# Tool Identifiers
#############################
TOOL_CODE_INTERPRETER="tool_{secrets.token_hex(8)}"
TOOL_WEB_SEARCH="tool_{secrets.token_hex(8)}"
TOOL_COMPUTER="tool_{secrets.token_hex(8)}"
TOOL_VECTOR_STORE_SEARCH="tool_{secrets.token_hex(8)}"

#############################
# Other
#############################
LOG_LEVEL=INFO
PYTHONUNBUFFERED=1
"""
        try:
            with open(self._ENV_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            self.log.info(f"Generated new {self._ENV_FILE} file with real values.")
        except Exception as e:
            self.log.error(f"Failed to generate {self._ENV_FILE} file: {e}")
            sys.exit(1)

    def _check_for_required_env_file(self):
        """Checks if the actual .env file needed for compose exists; if not, generate it."""
        self.log.debug(f"[ENV SCAN] Checking for required '{self._ENV_FILE}' file...")
        if not os.path.exists(self._ENV_FILE):
            self.log.warning(f"[ENV SCAN] Required environment file '{self._ENV_FILE}' is missing.")
            self._generate_dot_env_file()
        else:
            self.log.info(f"[ENV SCAN] Required environment file '{self._ENV_FILE}' exists. Will use it.")
            # Optionally add a check here to see if essential variables are missing from the existing file
            # config = dotenv_values(self._ENV_FILE)
            # required_vars = ["DATABASE_URL", "API_KEY", "SECRET_KEY", "SIGNED_URL_SECRET"]
            # missing = [var for var in required_vars if var not in config or not config[var]]
            # if missing:
            #    self.log.warning(f"Existing '{self._ENV_FILE}' is missing essential variables: {', '.join(missing)}. Consider regenerating or updating it.")


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
                # Use a path less likely to cause issues with Docker volume mounting
                # Avoid spaces, special chars if possible.
                shared_path_base = os.environ.get('LOCALAPPDATA', os.path.join(default_base, 'AppData', 'Local'))
                shared_path = os.path.join(shared_path_base, "Entities", "Share")
                # Convert to forward slashes for Docker consistency if needed, although os.path.join handles it
                # shared_path = shared_path.replace('\\', '/')
            elif system == 'linux':
                shared_path = os.path.join(default_base, ".local", "share", "entities_share")
            elif system == 'darwin': # macOS
                shared_path = os.path.join(default_base, "Library", "Application Support", "entities_share")
            else:
                self.log.error("Unsupported OS: %s. Cannot set default SHARED_PATH.", system)
                raise RuntimeError("Unsupported OS")
            self.log.info("Defaulting SHARED_PATH to: %s", shared_path)
            # Set it in the environment for the current script run AND potentially for compose
            os.environ['SHARED_PATH'] = shared_path

        # Ensure the directory exists
        try:
            Path(shared_path).mkdir(parents=True, exist_ok=True)
            self.log.info("Ensured shared directory exists: %s", shared_path)
            # Optional: Check permissions on Linux/macOS if issues arise
            # if system != 'windows':
            #    st = os.stat(shared_path)
            #    self.log.debug(f"Shared path permissions: {oct(st.st_mode)[-3:]}")
        except OSError as e:
            self.log.error(f"Failed to create shared directory {shared_path}: {e}. Check permissions.")
            # Decide if this is critical
            # sys.exit(1)
        except Exception as e:
            self.log.error(f"Unexpected error configuring shared path {shared_path}: {e}")


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
            self.log.debug("nvidia-smi found. Checking execution...")
            try:
                # Run with check=True to ensure it doesn't error out
                self._run_command(["nvidia-smi"], check=True, capture_output=True, suppress_logs=True)
                self.log.debug("nvidia-smi executed successfully. GPU support detected.")
                return True
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                self.log.warning(f"nvidia-smi failed ({type(e).__name__}). Assuming no GPU support for Docker.")
                return False
            except Exception as e:
                 self.log.warning(f"Unexpected error running nvidia-smi: {e}. Assuming no GPU support.")
                 return False
        else:
             self.log.debug("nvidia-smi command not found in PATH.")
             return False


    def _start_ollama(self, cpu_only=True):
        if not self._has_docker():
            self.log.error("❌ Docker command not found. Cannot manage Ollama container.")
            return False

        container_name = self._OLLAMA_CONTAINER
        image_name = self._OLLAMA_IMAGE
        ollama_port = self._OLLAMA_PORT

        if self._is_container_running(container_name):
            self.log.info(f"✅ Ollama container '{container_name}' is already running.")
            return True

        if not self._is_image_present(image_name):
            self.log.info(f"📦 Ollama image '{image_name}' not found locally. Pulling...")
            try:
                self._run_command(["docker", "pull", image_name], check=True)
                self.log.info(f"✅ Successfully pulled Ollama image '{image_name}'.")
            except Exception as e:
                self.log.error(f"❌ Failed to pull Ollama image '{image_name}': {e}")
                return False
        else:
            self.log.info(f"ℹ️ Found Ollama image '{image_name}' locally.")

        self.log.info(f"🚀 Attempting to start Ollama container '{container_name}'...")
        # Base docker run command
        cmd = [
            "docker", "run", "-d", "--rm",
            "-v", "ollama:/root/.ollama", # Persist models in a named volume
            "-p", f"{ollama_port}:{ollama_port}",
            "--name", container_name
        ]

        # Add GPU flag if requested and supported
        if not cpu_only and self._has_nvidia_support():
            self.log.info("    nvidia-smi check passed. Adding Docker --gpus=all flag.")
            # Insert --gpus flag right after 'docker run'
            cmd.insert(2, "--gpus=all")
        elif not cpu_only:
            self.log.warning("   GPU mode requested, but nvidia-smi check failed or command not found. Starting Ollama in CPU-only mode.")

        # Add the image name at the end
        cmd.append(image_name)

        try:
            self._run_command(cmd, check=True)
            # Wait a moment for the container to initialize
            time.sleep(5)
            if self._is_container_running(container_name):
                self.log.info(f"✅ Ollama container '{container_name}' started successfully on port {ollama_port}.")
                return True
            else:
                self.log.error(f"❌ Ollama container '{container_name}' failed to start after 'docker run'. Checking logs...")
                try:
                    # Attempt to show recent logs
                    self._run_command(["docker", "logs", "--tail", "50", container_name], check=False, suppress_logs=False)
                except Exception as log_e:
                    self.log.error(f"   Could not retrieve logs for failed container '{container_name}': {log_e}")
                return False
        except Exception as e:
            self.log.error(f"❌ Failed to execute 'docker run' for Ollama container '{container_name}': {e}")
            return False

    def _ensure_ollama(self, opt_in=False, use_gpu=False):
        """Ensures the external Ollama container is running if opted in."""
        if not opt_in:
            self.log.info("ℹ️ Ollama management not requested via --with-ollama. Skipping.")
            return True # Not requested is not a failure

        self.log.info("--- Ollama Setup ---")

        # Check if running inside Docker - managing external Docker from within Docker is tricky
        if os.path.exists("/.dockerenv") or os.environ.get("DOCKER_HOST"):
            self.log.warning("🛰 Script appears to be running inside a container. Skipping management of external Ollama container.")
            return True # Cannot manage external from internal easily

        # Specific check for macOS Docker Desktop limitations
        if platform.system() == "Darwin":
            self.log.warning("⚠️ Running on macOS. Docker Desktop on Mac does not support --gpus flag.")
            self.log.warning("   Please install and run the native Ollama macOS application separately if GPU support is desired.")
            # Proceed with CPU attempt, but warn user
            use_gpu = False # Force CPU mode for Docker on Mac

        # Determine desired mode (GPU or CPU)
        attempt_gpu = use_gpu # Store user's preference
        if attempt_gpu and not self._has_nvidia_support():
            self.log.warning("⚠️ GPU mode requested (--ollama-gpu), but nvidia-smi check failed or command not found.")
            self.log.warning("   Will attempt to start Ollama in CPU mode instead.")
            gpu_mode = False
        elif attempt_gpu:
             gpu_mode = True
        else:
             gpu_mode = False

        mode_str = "GPU" if gpu_mode else "CPU"
        self.log.info(f"Attempting to start external Ollama container in {mode_str} mode...")

        # Call the start function with cpu_only flag inverted from gpu_mode
        success = self._start_ollama(cpu_only=not gpu_mode)

        self.log.info("--- End Ollama Setup ---")
        return success


    # --- Docker Cache Diagnostics ---
    def _get_directory_size(self, path="."):
        """Calculates directory size in MB, handling errors."""
        total_size = 0
        try:
            for dirpath, _, filenames in os.walk(path, topdown=True):
                # Skip common large/problematic directories early
                # Convert dirpath parts to lowercase for comparison robustness
                dir_parts = set(p.lower() for p in Path(dirpath).parts)
                if any(skip in dir_parts for skip in ['.git', '.venv', 'node_modules', '__pycache__']):
                    continue

                for f in filenames:
                    try:
                        fp = os.path.join(dirpath, f)
                        # Important: Check if it's a symbolic link *before* getting size
                        if not islink(fp):
                            total_size += getsize(fp)
                    except FileNotFoundError:
                        # File might disappear between listing and sizing
                        self.log.debug("File not found during size check: %s", fp)
                        continue
                    except OSError as e:
                        # Permissions errors, etc.
                        self.log.debug("OS error getting size for %s: %s", fp, e)
                        continue
                    except Exception as e:
                        # Catch any other unexpected errors
                        self.log.warning("Unexpected error getting size for %s: %s", fp, e)
                        continue
        except Exception as e:
            self.log.error(f"Error walking directory {path} for size calculation: {e}")
        return total_size / (1024 * 1024) # Convert bytes to MB

    def _run_docker_cache_diagnostics(self):
        """Runs diagnostics to help understand Docker build cache issues."""
        self.log.info("--- Docker Cache Diagnostics ---")
        try:
            # 1. Approximate Build Context Size
            context_size_mb = self._get_directory_size()
            self.log.info("Approximate build context size: %.2f MB", context_size_mb)
            if context_size_mb > 500: # Threshold can be adjusted
                self.log.warning("Context size is large (>500MB). Ensure .dockerignore is effective.")

            # 2. List Services from Compose Config
            self.log.info("Listing services defined in docker-compose...")
            ps_config = self._run_command(["docker", "compose", "config", "--services"],
                                          capture_output=True, text=True, check=False, suppress_logs=True)
            if ps_config.returncode == 0 and ps_config.stdout.strip():
                services = ps_config.stdout.strip().splitlines()
                self.log.info("Services found: %s", ", ".join(services))
            else:
                self.log.warning("Could not determine services from 'docker compose config'. Skipping history check.")
                services = []

            # 3. Show Image History for Each Service (if possible)
            for service in services:
                # Try to determine the likely image name (this can be complex)
                # We'll just use the service name as a potential image name/tag base
                potential_image_name = service # This is often NOT the actual image name
                self.log.info(f"Attempting history check for potential image related to service '{service}':")
                # It's better to inspect the config for the actual image name if possible
                # For simplicity here, we just try the service name. A more robust solution
                # would parse `docker compose config --format json` to get the image name.
                try:
                    history = self._run_command(
                        ["docker", "history", potential_image_name, "--no-trunc", "--format", "{{.ID}}: {{.Size}} {{.CreatedBy}}"],
                        check=False, capture_output=True, text=True, suppress_logs=True
                    )
                    if history.returncode == 0 and history.stdout.strip():
                        self.log.info("History for '%s':\n%s", potential_image_name, history.stdout.strip())
                    elif history.returncode == 0:
                        self.log.info("No history found for image '%s' (may not exist or name mismatch).", potential_image_name)
                    else:
                        # Log stderr if history command failed
                        self.log.warning(f"Could not get history for '{potential_image_name}'. Error:\n{history.stderr.strip()}")
                except Exception as e:
                    self.log.warning(f"Error running docker history for '{potential_image_name}': {e}")

            # 4. Suggest common cache-busting culprits
            self.log.info("Common cache busters: COPY commands before dependency installation, changing file metadata.")
            self.log.info("Ensure frequently changing files are copied LATER in your Dockerfile.")

        except Exception as e:
            self.log.error("Failed during Docker cache diagnostics: %s", e, exc_info=self.args.verbose)
        self.log.info("--- End Docker Cache Diagnostics ---")


    # --- Docker Compose Actions ---
    def _handle_nuke(self):
        """Completely removes all Docker containers, volumes, networks, and images."""
        self.log.warning("!!! NUKE MODE ACTIVATED !!!")
        self.log.warning("This will permanently delete:")
        self.log.warning("  - ALL Docker containers (not just for this project)")
        self.log.warning("  - ALL Docker volumes (including database data)")
        self.log.warning("  - ALL Docker networks")
        self.log.warning("  - ALL Docker images")
        self.log.warning("This action is irreversible and affects your entire Docker environment.")

        try:
            # Prompt for confirmation
            confirm = input("Type 'NUKE DOCKER' to confirm this action: ")
        except EOFError: # Handle non-interactive environments
            self.log.error("Nuke requires interactive confirmation. Aborting.")
            sys.exit(1)

        if confirm != "NUKE DOCKER":
            self.log.info("Nuke confirmation failed. Aborting.")
            sys.exit(0)

        self.log.info("Proceeding with Docker nuke...")
        try:
            # Step 1: Stop and remove containers associated with the current project (best effort)
            self.log.info("Step 1: Stopping and removing project containers/volumes...")
            self._run_command(["docker", "compose", "down", "--volumes", "--remove-orphans", "--timeout", "10"], check=False) # Don't fail if project isn't up

            # Step 2: Prune the entire Docker system
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
        """Stops containers and optionally removes volumes for the project."""
        target_services = self.args.services or []
        target_desc = f" specified services: {', '.join(target_services)}" if target_services else " all services"
        action = "Stopping containers"
        volume_action = ""

        if self.args.clear_volumes:
            action += " and removing associated volumes"
            if not target_services:
                volume_action = "ALL project volumes"
                try:
                    confirm = input(f"This will delete {volume_action}. Are you sure? (yes/no): ").lower().strip()
                except EOFError:
                    self.log.error("Volume deletion requires interactive confirmation. Aborting.")
                    sys.exit(1)
                if confirm != "yes":
                    self.log.info("Volume deletion cancelled.")
                    # If only volume clear was requested with down, exit. Otherwise, proceed without --volumes.
                    if self.args.mode == 'down_only': # Check if the intent was just to clear volumes
                        sys.exit(0)
                    self.args.clear_volumes = False # Cancel volume deletion for this run
            else:
                volume_action = f"volumes potentially associated with {target_desc}"
                self.log.warning(f"Note: Removing volumes for specific services ({volume_action}) might not remove shared named volumes unless they become orphaned.")

        self.log.info(f"{action} for {target_desc}...")

        down_cmd = ["docker", "compose", "down", "--remove-orphans", "--timeout", "30"] # Add timeout
        if self.args.clear_volumes: # Check again in case it was cancelled interactively
            down_cmd.append("--volumes")

        # docker-compose down doesn't accept service names directly in most versions
        # If targeting specific services, we stop them first, then run down for cleanup.
        # However, `down` itself should handle stopping. Let's rely on `down` behavior.
        # If specific services needed stopping ONLY, we'd use `docker compose stop <services>`

        try:
            self._run_command(down_cmd, check=True) # Use check=True to catch failures
            self.log.info(f"✅ {action} for {target_desc} completed.")
        except subprocess.CalledProcessError as e:
            self.log.error(f"'docker compose down' command failed: {e}")
            # Provide more context if possible
            if e.stderr: self.log.error("Error details:\n%s", e.stderr)
            sys.exit(1)
        except Exception as e:
            self.log.error(f"An unexpected error occurred during 'down' operation: {e}")
            sys.exit(1)


    def _handle_build(self):
        """Handles building the Docker images using docker-compose build."""
        env_file = self._ENV_FILE
        if not os.path.exists(env_file):
            self.log.error(f"Required environment file '{env_file}' is missing for build.")
            self.log.error("Attempting to generate one...")
            self._generate_dot_env_file()
            # Check again after generation
            if not os.path.exists(env_file):
                 self.log.critical("Failed to generate or find required .env file. Aborting build.")
                 sys.exit(1)
            self.log.info(f"Generated '{env_file}'. Proceeding with build.")
        else:
            self.log.info(f"Using existing environment file '{env_file}'.")

        # Load env vars from the file to make them available to compose if needed directly by the script
        # Although compose reads the .env file itself, loading here can be useful for script logic
        load_dotenv(dotenv_path=env_file, override=True)
        self.log.debug(f"Environment variables potentially loaded from '{env_file}' into script context.")

        target_services = self.args.services or []
        target_desc = f" specified services: {', '.join(target_services)}" if target_services else " all services"
        cache_desc = " without using cache" if self.args.no_cache else " using cache"
        pull_desc = " (will attempt to pull newer base images)" if self.args.pull else ""

        self.log.info(f"Building images for {target_desc}{cache_desc}{pull_desc}...")

        build_cmd = ["docker", "compose", "build"]
        if self.args.no_cache:
            build_cmd.append("--no-cache")
        if self.args.pull:
            build_cmd.append("--pull") # Add the pull flag if requested
        if target_services:
            # Add service names at the end
            build_cmd.extend(target_services)

        t_start = time.time()
        try:
            # Run the build command
            self._run_command(build_cmd, check=True)
            t_end = time.time()
            self.log.info("✅ Build completed successfully in %.2f seconds.", t_end - t_start)

            # Tag images if requested
            if self.args.tag:
                self.log.info(f"Applying tag '{self.args.tag}' to built images (targets: {target_desc})...")
                self._tag_images(self.args.tag, targeted_services=target_services)

        except subprocess.CalledProcessError as e:
            self.log.critical(f"Docker build failed with return code {e.returncode}.")
            if e.stderr: self.log.error("Error details:\n%s", e.stderr)
            if e.stdout: self.log.error("Output log:\n%s", e.stdout)
            sys.exit(1)
        except Exception as e:
            self.log.critical(f"An unexpected error occurred during build: {e}", exc_info=self.args.verbose)
            sys.exit(1)


    def _tag_images(self, tag, targeted_services=None):
        """Tags built images specified in docker-compose config with the given tag."""
        if not tag:
            self.log.warning("No tag provided. Skipping image tagging.")
            return

        self.log.info(f"Attempting to tag images with tag: '{tag}'")
        try:
            self.log.debug("Fetching service configuration using 'docker compose config'...")
            # Get config in JSON format
            service_config_json = self._run_command(["docker", "compose", "config", "--format", "json"],
                                                    capture_output=True, check=True, suppress_logs=True).stdout
            config_data = json.loads(service_config_json)
            services = config_data.get("services")

            if not services:
                self.log.warning("No services found in the parsed compose configuration. Cannot tag.")
                return

            tagged_count = 0
            skipped_count = 0

            for service_name, config in services.items():
                # Skip if specific services were targeted for build and this isn't one of them
                if targeted_services and service_name not in targeted_services:
                    self.log.debug(f"Skipping tag for service '{service_name}' as it was not targeted in the build command.")
                    skipped_count += 1
                    continue

                # Get the image name defined in the compose file for this service
                # Handles cases like: image: myrepo/myimage:sometag or build: context: . image: myrepo/myimage
                image_name_from_config = config.get("image")

                if not image_name_from_config:
                    # If no explicit image name, compose might generate one based on project/service name
                    # This heuristic is less reliable. We'll skip for now.
                    # A better approach might involve inspecting the built image ID if available.
                    self.log.debug(f"Service '{service_name}' has no explicit 'image:' definition in compose file. Skipping automatic tagging.")
                    skipped_count += 1
                    continue

                # Determine the base image name (without tag) and the source reference (usually :latest or the built tag)
                base_image_parts = image_name_from_config.split(":")
                base_image = base_image_parts[0]
                # Assume the source image to tag is the one defined in the compose file OR :latest if no tag specified there
                original_ref = image_name_from_config if len(base_image_parts) > 1 else f"{base_image}:latest"

                # Construct the new tag
                new_tag_ref = f"{base_image}:{tag}"

                self.log.info(f"Attempting to tag image for service '{service_name}': {original_ref} -> {new_tag_ref}")

                try:
                    # Check if the source image exists before tagging
                    inspect_res = self._run_command(["docker", "image", "inspect", original_ref],
                                                    check=False, capture_output=True, suppress_logs=True)
                    if inspect_res.returncode != 0:
                        self.log.warning(f"  Source image '{original_ref}' not found. Cannot apply tag '{tag}'. (Was it built successfully?)")
                        skipped_count +=1
                        continue

                    # Execute the docker tag command
                    self._run_command(["docker", "tag", original_ref, new_tag_ref], check=True, suppress_logs=True)
                    self.log.info(f"  Successfully tagged {original_ref} as {new_tag_ref}")
                    tagged_count += 1
                except subprocess.CalledProcessError as tag_e:
                    self.log.error(f"  Failed to tag {original_ref} as {new_tag_ref}: {tag_e}")
                    if tag_e.stderr: self.log.error("  Error details: %s", tag_e.stderr.strip())
                except Exception as tag_e:
                    self.log.error(f"  An unexpected error occurred while tagging {original_ref}: {tag_e}")

            self.log.info(f"Image tagging complete. {tagged_count} images tagged, {skipped_count} skipped.")

        except json.JSONDecodeError as e:
            self.log.error(f"Failed to parse 'docker compose config' JSON output: {e}")
        except subprocess.CalledProcessError as e:
            self.log.error(f"Command 'docker compose config' failed: {e}")
            if e.stderr: self.log.error("Error details:\n%s", e.stderr)
        except Exception as e:
            self.log.error(f"An unexpected error occurred during image tagging: {e}", exc_info=self.args.verbose)


    def _handle_up(self):
        """Handles starting the Docker containers using docker-compose up."""
        env_file = self._ENV_FILE
        if not os.path.exists(env_file):
            self.log.error(f"Required environment file '{env_file}' is missing for 'up' command.")
            self.log.info("Attempting to generate one...")
            self._generate_dot_env_file()
            if not os.path.exists(env_file):
                 self.log.critical(f"Failed to find or generate required environment file '{env_file}'. Aborting 'up'.")
                 sys.exit(1)
            self.log.info(f"Generated '{env_file}'. Proceeding with 'up'.")
        else:
             self.log.info(f"Using existing environment file '{env_file}' for 'up' command.")

        # Load .env variables into the script's environment (optional, but can be useful)
        load_dotenv(dotenv_path=env_file, override=True)
        self.log.debug(f"Environment variables potentially loaded from '{env_file}' into script context.")

        mode = "attached" if self.args.attached else "detached"
        target_services = self.args.services or []
        target_desc = f" specified services: {', '.join(target_services)}" if target_services else " all services"

        self.log.info(f"Starting containers for {target_desc} in {mode} mode...")

        up_cmd = ["docker", "compose", "up"]
        if not self.args.attached:
            up_cmd.append("-d") # Detached mode

        # Add --build flag if requested
        if self.args.build_before_up:
             self.log.info("   (Will build images before starting if necessary)")
             up_cmd.append("--build")

        # Add --force-recreate flag if requested
        if self.args.force_recreate:
            self.log.info("   (Forcing recreation of containers)")
            up_cmd.append("--force-recreate")

        # Add specific services if provided
        if target_services:
            up_cmd.extend(target_services)

        try:
            # Execute the docker compose up command
            self._run_command(up_cmd, check=True) # Check=True will raise error on failure
            self.log.info("✅ Containers started successfully.")

            # If running detached, provide command to view logs
            if not self.args.attached:
                logs_cmd_base = ["docker", "compose", "logs", "-f", "--tail", "50"] # Follow and show recent history
                if target_services:
                    logs_cmd_base.extend(target_services)
                self.log.info(f"👀 To view logs, run: {' '.join(logs_cmd_base)}")

        except subprocess.CalledProcessError as e:
            self.log.critical(f"'docker compose up' command failed with return code {e.returncode}.")
            if not self.args.attached:
                 self.log.info("Attempting to show recent logs from failed startup...")
                 try:
                     logs_fail_cmd = ["docker", "compose", "logs", "--tail=100"]
                     if target_services:
                         logs_fail_cmd.extend(target_services)
                     # Run without check=True as the containers might not exist
                     self._run_command(logs_fail_cmd, check=False)
                 except Exception as log_e:
                     self.log.error(f"Could not fetch logs after failed 'up' attempt: {log_e}")
            sys.exit(1) # Exit with error code
        except Exception as e:
            self.log.critical(f"An unexpected error occurred during 'up' operation: {e}", exc_info=self.args.verbose)
            sys.exit(1) # Exit with error code


    def run(self):
        """Main execution logic based on parsed arguments."""
        if self.args.debug_cache:
            self._run_docker_cache_diagnostics()
            sys.exit(0)

        if self.args.nuke:
            self._handle_nuke() # Nuke exits on its own
            sys.exit(0) # Should be unreachable if nuke confirms

        # Handle Ollama setup before potentially modifying the stack
        # Only run if --with-ollama is specified
        if self.args.with_ollama:
            ollama_ok = self._ensure_ollama(opt_in=True, use_gpu=self.args.ollama_gpu)
            if not ollama_ok:
                self.log.error("Ollama setup failed. Continuing script, but Ollama container might not be available.")
                # Decide if this should be fatal:
                # sys.exit(1)

        # Handle 'down' actions first if requested
        if self.args.down or self.args.clear_volumes:
            self._handle_down()
            # If the mode was specifically 'down_only', exit now
            if self.args.mode == 'down_only':
                self.log.info("Down action complete. Exiting as requested.")
                sys.exit(0)

        # Handle 'build' actions
        if self.args.mode in ["build", "both"]:
            # Sanity checks for build-related flags
            if (self.args.no_cache or self.args.pull) and self.args.mode not in ["build", "both"]:
                 self.log.warning(f"--no-cache or --pull specified but mode is '{self.args.mode}'. Flag will be ignored unless mode is 'build' or 'both'.")
            # Build uses --no-cache and --pull internally based on args
            self._handle_build()
            # Tagging happens within _handle_build if self.args.tag is set

        # Handle 'up' actions
        if self.args.mode in ["up", "both"]:
            # Up uses --build-before-up and --force-recreate internally based on args
            self._handle_up()

        self.log.info("Docker management script finished.")


    @staticmethod
    def parse_args():
        """Parses command-line arguments."""
        parser = argparse.ArgumentParser(
            description="Manage Entities API Docker Compose stack, .env setup, and optional external Ollama.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )

        # Core Action Modes
        parser.add_argument(
            "--mode", choices=["up", "build", "both", "down_only"], default="up",
            help="Primary action: 'up' starts containers, 'build' builds images, 'both' builds then starts, 'down_only' just stops/removes."
        )

        # Build Options (apply when mode is 'build' or 'both')
        parser.add_argument(
            "--no-cache", action="store_true",
            help="Build images without using Docker's cache."
        )
        parser.add_argument(
            "--pull", action="store_true",
            help="Always attempt to pull newer base images during build."
        )
        parser.add_argument(
            "--tag", type=str, metavar="TAG",
            help="Apply a custom tag to the built images (e.g., 'dev', 'v1.2')."
        )

        # Up Options (apply when mode is 'up' or 'both')
        parser.add_argument(
            "--attached", action="store_true",
            help="Run 'docker compose up' in attached mode (foreground) instead of detached."
        )
        parser.add_argument(
            "--build-before-up", action="store_true",
            help="Force running build before 'up', even if mode is 'up'. (Equivalent to 'docker compose up --build')"
        )
        parser.add_argument(
            "--force-recreate", action="store_true",
            help="Force recreation of containers even if configuration hasn't changed during 'up'."
        )

        # Down Options (can be combined with modes or used with 'down_only')
        parser.add_argument(
            "--down", action="store_true",
            help="Stop and remove containers before other actions (or as the only action if --mode=down_only)."
        )
        parser.add_argument(
            "--clear-volumes", "-cv", action="store_true",
            help="When bringing the stack down (with --down or --mode=down_only), also remove associated volumes (prompts for confirmation unless --services is used)."
        )

        # Service Targeting
        parser.add_argument(
            "--services", nargs='+', metavar='SERVICE',
            help="Target specific service(s) for build, up, or down actions."
        )

        # External Ollama Management
        parser.add_argument(
            "--with-ollama", action="store_true",
            help="Ensure an external Ollama Docker container is running (pulls image/starts container if needed)."
        )
        parser.add_argument(
            "--ollama-gpu", action="store_true",
            help="If managing external Ollama (--with-ollama), attempt to start it with GPU support (--gpus=all)."
        )

        # Destructive/Diagnostic Actions
        parser.add_argument(
            "--nuke", action="store_true",
            help="DANGER ZONE! Completely prune the entire Docker system (all containers, volumes, networks, images). Requires explicit confirmation."
        )
        parser.add_argument(
            "--debug-cache", action="store_true",
            help="Run Docker build cache diagnostics (context size, image history) and exit."
        )

        # General Options
        parser.add_argument(
            "--verbose", "-v", action="store_true",
            help="Enable verbose debug logging for the script."
        )

        args = parser.parse_args()

        # Consolidate logic: if --down or --clear-volumes is used, ensure mode reflects it if not already build/both
        if (args.down or args.clear_volumes) and args.mode == 'up':
             log.info("Detected --down or --clear-volumes with default --mode=up. Setting mode to 'down_only' to perform down actions first.")
             args.mode = 'down_only'
             # If the user *also* wanted to build/up later, they should use --mode=both or run separately.

        # If --build-before-up is set, ensure the mode implies an 'up' action
        if args.build_before_up and args.mode not in ['up', 'both']:
            log.warning("--build-before-up specified, but mode is not 'up' or 'both'. Flag will be ignored.")
            # Or force mode to 'both'? Let's just warn.
            # args.mode = 'both'

        # If --tag is set, ensure the mode implies a 'build' action
        if args.tag and args.mode not in ['build', 'both']:
             log.warning(f"--tag '{args.tag}' specified, but mode is '{args.mode}'. Tagging only happens after a build (mode 'build' or 'both').")


        return args


if __name__ == "__main__":
    try:
        arguments = DockerManager.parse_args()
        manager = DockerManager(arguments)
        manager.run()
    except KeyboardInterrupt:
        log.info("\n🛑 Operation cancelled by user.")
        sys.exit(130) # Standard exit code for Ctrl+C
    except subprocess.CalledProcessError as e:
        # Already logged in _run_command, just exit
        log.critical("❌ A critical command failed during execution.")
        sys.exit(e.returncode)
    except Exception as e:
        log.critical("❌ An unexpected error occurred: %s", e, exc_info=(log.level == logging.DEBUG))
        sys.exit(1)
