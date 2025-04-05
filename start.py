#!/usr/bin/env python
import argparse
import logging
import os
import platform
import secrets
import shutil
import subprocess
import sys
import time
from os.path import getsize, islink
from pathlib import Path

from dotenv import dotenv_values
from dotenv import load_dotenv

# Standard Python logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


class DockerManager:
    """Manages Docker Compose stack operations, env setup, and optional Ollama integration."""

    # --- Class Attributes ---
    _TEMPLATE_FILES = {
        ".env.dev": ".env.dev.example",
        ".env.docker": ".env.docker.example",
    }
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
        self.log = log # Use the module-level logger

        if self.args.verbose:
            self.log.setLevel(logging.DEBUG)
        self.log.debug("DockerManager initialized with args: %s", args)

        # Initial setup steps
        self._ensure_env_files() # Ensures .env files exist using templates
        self._configure_shared_path() # Configure and create SHARED_PATH
        self._ensure_dockerignore()

    # --- Core Docker/System Command Execution ---
    def _run_command(self, cmd_list, check=True, capture_output=False, text=True, suppress_logs=False, **kwargs):
        """
        Helper method to run shell commands using subprocess.

        Args:
            cmd_list (list): The command and its arguments as a list.
            check (bool): If True, raise CalledProcessError on non-zero exit code.
            capture_output (bool): If True, capture stdout and stderr.
            text (bool): If True, decode stdout/stderr as text.
            suppress_logs (bool): If True, don't log command execution/output unless error.
            **kwargs: Additional arguments passed to subprocess.run.

        Returns:
            subprocess.CompletedProcess: The result object from subprocess.run.

        Raises:
            subprocess.CalledProcessError: If the command fails and check is True.
            Exception: For other execution errors.
        """
        if not suppress_logs:
            self.log.info("Running command: %s", " ".join(cmd_list))
        try:
            result = subprocess.run(
                cmd_list,
                check=check,
                capture_output=capture_output,
                text=text,
                shell=self.is_windows,
                **kwargs
            )
            if not suppress_logs:
                self.log.debug("Command finished: %s", " ".join(cmd_list))
                if result.stdout:
                    self.log.debug("Command stdout:\n%s", result.stdout.strip())
                if result.stderr:
                     # Log stderr even on success if captured and not empty
                     if result.stderr.strip():
                         self.log.debug("Command stderr:\n%s", result.stderr.strip())
            return result
        except subprocess.CalledProcessError as e:
            self.log.error(f"Command failed: {' '.join(cmd_list)}")
            self.log.error(f"Return Code: {e.returncode}")
            # Ensure output is logged even if suppress_logs was True on error
            if e.stdout:
                self.log.error("STDOUT:\n%s", e.stdout.strip())
            if e.stderr:
                self.log.error("STDERR:\n%s", e.stderr.strip())
            if check:
                raise
            return e # Return error object if check=False
        except Exception as e:
            self.log.error(f"Error running command {' '.join(cmd_list)}: {e}", exc_info=self.args.verbose)
            raise

    # --- .dockerignore Generation ---
    def _ensure_dockerignore(self):
        """Generates a default .dockerignore file if it doesn't exist."""
        dockerignore = Path(".dockerignore")
        if not dockerignore.exists():
            self.log.warning(".dockerignore not found. Generating default to improve cache efficiency...")
            dockerignore.write_text("""__pycache__/
.venv/
node_modules/
*.log
*.pyc
.git/
.env*
*.sqlite
dist/
build/
coverage/
tmp/
*.egg-info/
""")
            self.log.info("Generated default .dockerignore.")

    # --- Environment File Generation ---
    def _generate_secret(self, length=32):
        """Generates a URL-safe secret token."""
        return secrets.token_urlsafe(length)[:length]

    def _generate_env_file_templates(self):
        """Generates .env files from .env.example templates with secrets."""
        self.log.info("Generating environment file templates...")
        # Shared values across all .env.* files
        mysql_root_password = self._generate_secret(16)
        mysql_password = self._generate_secret(16)
        mysql_database = "cosmic_catalyst"  # Example name, adjust if needed

        generated_values = {
            "__MYSQL_ROOT_PASSWORD__": mysql_root_password,
            "__MYSQL_DATABASE__": mysql_database,
            "__MYSQL_PASSWORD__": mysql_password,
            "__DEFAULT_SECRET_KEY__": self._generate_secret(48),
            "__SIGNED_URL_SECRET__": self._generate_secret(48),

            # --- Added Default API Key Generation ---
            # Assuming the placeholder in your .env.*.example files is __DEFAULT_API_KEY__
            # Adjust the length (e.g., 40) as needed for your application's requirements.
            "__DEFAULT_API_KEY__": self._generate_secret(40),
            # --- End Added Key ---

            # Example tool IDs - adjust if your app uses these placeholders
            "__TOOL_CODE_INTERPRETER__": f"tool_{self._generate_secret(22)}",
            "__TOOL_WEB_SEARCH__": f"tool_{self._generate_secret(22)}",
            "__TOOL_COMPUTER__": f"tool_{self._generate_secret(22)}",
            "__TOOL_VECTOR_STORE_SEARCH__": f"tool_{self._generate_secret(22)}",

            # Hardcoded SMB values from original script
            "__SMBCLIENT_SERVER__": "samba_server",
            "__SMBCLIENT_SHARE__": "cosmic_share",
            "__SMBCLIENT_USERNAME__": "samba_user",
            "__SMBCLIENT_PASSWORD__": "default",  # Consider making this generated too
            "__SMBCLIENT_PORT__": "445",
        }

        for output_file, template_file in self._TEMPLATE_FILES.items():
            if not os.path.exists(output_file):
                if not os.path.exists(template_file):
                    self.log.warning(f"[ENV] Template file {template_file} not found. Cannot generate {output_file}.")
                    continue
                try:
                    with open(template_file, "r", encoding="utf-8") as f:
                        content = f.read()
                    for placeholder, value in generated_values.items():
                        content = content.replace(placeholder, value)
                    # Ensure the placeholder exists in the template before writing
                    if "__DEFAULT_API_KEY__" not in content and output_file == ".env.docker":
                        # Add a check specifically for the docker env, as it was the one failing
                        self.log.warning(f"Placeholder '__DEFAULT_API_KEY__' not found in template '{template_file}'. "
                                         f"The generated '{output_file}' might be missing this value.")

                    with open(output_file, "w", encoding="utf-8") as f:
                        f.write(content)
                    self.log.info(f"[ENV] Generated {output_file} from {template_file}")
                except IOError as e:
                    self.log.error(f"[ENV] Failed to read/write file during generation of {output_file}: {e}")
                except Exception as e:
                    self.log.error(f"[ENV] Unexpected error generating {output_file}: {e}")
            else:
                self.log.debug(f"[ENV] {output_file} already exists. Skipping generation.")

    def _ensure_env_files(self):
        """Checks for required .env files and generates them if missing."""
        missing = []
        for file in self._TEMPLATE_FILES.keys():
            if not os.path.exists(file):
                missing.append(file)

        if missing:
            self.log.info("[ENV SCAN] Missing env files: %s. Generating defaults...", missing)
            self._generate_env_file_templates()
        else:
            self.log.info("[ENV SCAN] All required environment files already present.")

    # --- Shared Path Configuration ---
    def _configure_shared_path(self):
        """Configures the SHARED_PATH environment variable based on OS and creates the directory."""
        system = platform.system().lower()
        # Use environment variable if already set, otherwise determine default
        shared_path_env = os.environ.get('SHARED_PATH')
        if shared_path_env:
             shared_path = shared_path_env
             self.log.info("Using existing SHARED_PATH from environment: %s", shared_path)
        else:
            if system == 'windows':
                # Using a more user-accessible default path for Windows
                default_base = os.path.expanduser("~")
                shared_path = os.path.join(default_base, "entities_share")
                # shared_path = r"C:\\ProgramData\\entities\\samba_share" # Original path
            elif system == 'linux':
                # Ensure the user running this script has permissions for /srv
                # Consider using a path within user's home dir for broader compatibility
                 default_base = os.path.expanduser("~")
                 shared_path = os.path.join(default_base, ".local", "share", "entities_share")
                # shared_path = "/srv/entities_api/samba_share" # Original path
            elif system == 'darwin': # macOS
                default_base = os.path.expanduser("~")
                shared_path = os.path.join(default_base, "Library", "Application Support", "entities_share")
                # shared_path = "/Users/Shared/entities_api/samba_share" # Original path
            else:
                self.log.error("Unsupported OS detected: %s. Cannot determine default shared path.", system)
                raise RuntimeError("Unsupported OS detected.")
            self.log.info("Defaulting SHARED_PATH to: %s", shared_path)
            os.environ['SHARED_PATH'] = shared_path

        # Ensure the directory exists
        try:
            if not os.path.exists(shared_path):
                os.makedirs(shared_path, exist_ok=True)
                self.log.info("Created shared directory: %s", shared_path)
            else:
                self.log.info("Shared directory already exists: %s", shared_path)
        except OSError as e:
            self.log.error(f"Failed to create shared directory {shared_path}: {e}. Check permissions.")
            # Decide if this is fatal. For now, log error and continue.
            # raise # Uncomment to make it fatal

    # --- Ollama Integration ---
    def _has_docker(self):
        """Checks if the 'docker' command is available in the system PATH."""
        return shutil.which("docker") is not None

    def _is_container_running(self, container_name):
        """Checks if a Docker container with the given name is currently running."""
        try:
            # Use --quiet to only output IDs, simpler check
            result = self._run_command(
                ["docker", "ps", "--filter", f"name=^{container_name}$", "--quiet"], # Use exact name match
                capture_output=True, text=True, check=False, suppress_logs=True
            )
            # If output is not empty, a container with that exact name is running
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(f"Could not check if container '{container_name}' is running: {e}")
            return False # Assume not running on error

    def _is_image_present(self, image_name):
        """Checks if a Docker image with the given name exists locally."""
        try:
            # Use --quiet to only output IDs
             result = self._run_command(
                 ["docker", "images", image_name, "--quiet"],
                 capture_output=True, text=True, check=False, suppress_logs=True
             )
             # If output is not empty, the image exists
             return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(f"Could not check if image '{image_name}' is present: {e}")
            return False # Assume not present on error

    def _has_nvidia_support(self):
        """Checks if 'nvidia-smi' command is available, indicating NVIDIA drivers."""
        has_smi = shutil.which("nvidia-smi") is not None
        if has_smi:
            # Optional: Add a check to actually run nvidia-smi to see if it errors
            try:
                self._run_command(["nvidia-smi"], check=True, capture_output=True, suppress_logs=True)
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                 self.log.warning("nvidia-smi found but failed to execute. Assuming no GPU support.")
                 return False
        return False

    def _start_ollama(self, cpu_only=True):
        """Pulls the Ollama image if needed and starts the Ollama container."""
        if not self._has_docker():
            self.log.error("❌ Docker command not found in PATH. Cannot start Ollama.")
            return False # Indicate failure

        container_name = self._OLLAMA_CONTAINER
        if self._is_container_running(container_name):
            self.log.info(f"✅ Ollama container '{container_name}' is already running.")
            return True # Indicate success (already running)

        image_name = self._OLLAMA_IMAGE
        if not self._is_image_present(image_name):
            self.log.info(f"📦 Pulling Ollama image '{image_name}'...")
            try:
                self._run_command(["docker", "pull", image_name], check=True)
            except (subprocess.CalledProcessError, Exception) as e:
                 self.log.error(f"❌ Failed to pull Ollama image: {e}")
                 return False # Indicate failure

        self.log.info(f"🚀 Starting Ollama container '{container_name}'...")
        cmd = [
            "docker", "run", "-d", # Run detached
            "--rm", # Remove container when it stops
            "-v", "ollama:/root/.ollama", # Persist models in a named volume
            "-p", f"{self._OLLAMA_PORT}:{self._OLLAMA_PORT}",
            "--name", container_name
        ]
        # Add GPU flag if requested and supported
        if not cpu_only:
            # Check again right before launch in case something changed
             if self._has_nvidia_support():
                 self.log.info("   Adding --gpus=all flag.")
                 # Insert after 'run' but before other flags like -d
                 cmd.insert(2, "--gpus=all")
             else:
                 self.log.warning("   GPU requested, but nvidia-smi check failed just before launch. Starting in CPU mode.")

        cmd.append(image_name) # The image name goes last

        try:
            self._run_command(cmd, check=True)
            # Add a small delay and check if it actually started
            time.sleep(3)
            if self._is_container_running(container_name):
                self.log.info(f"✅ Ollama container '{container_name}' started successfully.")
                return True # Indicate success
            else:
                self.log.error(f"❌ Ollama container '{container_name}' failed to start. Check Docker logs: docker logs {container_name}")
                # Attempt to show logs
                try:
                    self._run_command(["docker", "logs", container_name], check=False, suppress_logs=False)
                except Exception:
                    pass # Ignore errors fetching logs if container didn't start properly
                return False # Indicate failure
        except (subprocess.CalledProcessError, Exception) as e:
            self.log.error(f"❌ Failed to start Ollama container: {e}")
            return False # Indicate failure

    def _ensure_ollama(self, opt_in=False, use_gpu=False):
        """
        Ensures Ollama is set up based on user flags and system capabilities.

        Args:
            opt_in (bool): True if the user explicitly requested Ollama via --with-ollama.
            use_gpu (bool): True if the user explicitly requested GPU via --ollama-gpu.

        Returns:
            bool: True if Ollama setup was successful or skipped appropriately, False on failure.
        """
        if not opt_in:
            self.log.info("ℹ️ Ollama integration is opt-in. Skipping setup.")
            return True # Skipped successfully

        self.log.info("--- Ollama Setup ---")
        system = platform.system()

        # Avoid running inside a Docker container if this script itself is containerized
        # Check for /.dockerenv file or DOCKER_HOST environment variable as indicators
        # Note: RUNNING_IN_DOCKER env var check might not be reliable unless explicitly set in the parent Dockerfile
        if os.path.exists("/.dockerenv") or os.environ.get("DOCKER_HOST"):
             self.log.warning("🛰 Detected running inside a container. Skipping external Ollama setup.")
             self.log.warning("   If you need Ollama, include it in your docker-compose.yml file.")
             self.log.info("--- End Ollama Setup ---")
             return True # Skipped successfully in this context

        if system == "Darwin": # macOS
            self.log.warning("⚠️ macOS detected. Docker containers do not support GPU acceleration on Mac.")
            self.log.warning("👉 For best performance, please install and run the native Ollama app: https://ollama.com/download")
            # Decide whether to proceed with CPU Docker container or just warn. Let's warn and skip.
            self.log.info("   Skipping Docker-based Ollama setup on macOS.")
            self.log.info("--- End Ollama Setup ---")
            return True # Skipped intentionally

        gpu_mode_possible = False
        if use_gpu:
            if self._has_nvidia_support():
                self.log.info("✅ NVIDIA GPU support detected via nvidia-smi.")
                gpu_mode_possible = True
            else:
                self.log.warning("⚠️ GPU mode requested (--ollama-gpu), but NVIDIA support ('nvidia-smi') not found or not working.")
                self.log.warning("   Falling back to CPU mode for Ollama.")
        else:
             self.log.info("💡 Ollama GPU mode not requested (--ollama-gpu not used). Using CPU mode.")

        mode_string = "GPU" if gpu_mode_possible else "CPU"
        self.log.info(f"Attempting to start Ollama in {mode_string} mode...")

        success = self._start_ollama(cpu_only=not gpu_mode_possible)

        self.log.info("--- End Ollama Setup ---")
        return success


    # --- Docker Cache Diagnostics ---
    def _get_directory_size(self, path="."):
        """Calculates the total size of files in a directory (MB)."""
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                try:
                    fp = os.path.join(dirpath, f)
                    if not islink(fp): # skip symbolic links
                        total_size += getsize(fp)
                except OSError as e:
                    self.log.debug("Could not get size of file %s: %s", fp, e)
                    continue # Skip files we can't access
                except Exception as e:
                    self.log.warning("Unexpected error getting size of file %s: %s", fp, e)
                    continue # Skip on other errors
        return total_size / (1024 * 1024)  # Convert bytes to MB

    def _run_docker_cache_diagnostics(self):
        """Runs diagnostics to understand Docker build cache usage."""
        self.log.info("--- Docker Cache Diagnostics ---")
        try:
            context_size_mb = self._get_directory_size()
            self.log.info("Approximate Docker build context size: %.2f MB", context_size_mb)

            # Get list of services defined in docker-compose.yml
            ps_config = self._run_command(
                ["docker", "compose", "config", "--services"],
                capture_output=True, text=True, check=False # Allow failure if compose file invalid
            )
            if ps_config.returncode != 0:
                self.log.warning("Could not get services from docker-compose config. Is docker-compose.yml valid?")
                services = []
            else:
                services = ps_config.stdout.strip().splitlines()
                self.log.info("Services defined in docker-compose config: %s", ", ".join(services))

            # Inspect image history for each service (this assumes image names match service names)
            for service in services:
                image_name = service # Default assumption
                # TODO: Could potentially parse docker-compose config to get actual image name if different
                self.log.info(f"Inspecting image history for potential image '{image_name}':")
                try:
                    # Format for concise output: Image ID and the command that created the layer
                    # Use check=False as image might not exist yet
                    history_result = self._run_command(
                        ["docker", "history", image_name, "--no-trunc", "--format", "{{.ID}}: {{.CreatedBy}}"],
                        check=False, capture_output=True, text=True
                    )
                    if history_result.returncode == 0:
                         if history_result.stdout.strip():
                            self.log.info("History:\n%s", history_result.stdout.strip())
                         else:
                             self.log.info("No history found (image might not be built or uses a different name).")
                    else:
                        self.log.warning(f"Could not get history for image '{image_name}'. Error:\n{history_result.stderr.strip()}")

                except Exception as e:
                     self.log.warning(f"Unexpected error getting history for image '{image_name}': {e}")

        except Exception as e:
            self.log.error("Failed during Docker diagnostics: %s", e)
        self.log.info("--- End Docker Cache Diagnostics ---")

    # --- Docker Compose Actions ---
    def _handle_nuke(self):
        """Handles the --nuke operation (full Docker prune)."""
        self.log.warning("!!! NUKE MODE: ALL DOCKER DATA WILL BE WIPED (containers, volumes, networks, images) !!!")
        try:
            confirm = input("Are you absolutely sure you want to nuke the Docker environment? (yes/no): ").lower()
        except EOFError: # Handle non-interactive environments
             self.log.error("Nuke requires interactive confirmation. Aborting.")
             sys.exit(1)

        if confirm != "yes":
            self.log.info("Nuke cancelled.")
            sys.exit(0)

        self.log.info("Proceeding with Docker nuke...")
        try:
            # Stop and remove all containers, volumes, orphans from the compose project first
            self.log.info("Stopping and removing compose services and volumes...")
            self._run_command(["docker", "compose", "down", "--volumes", "--remove-orphans"], check=False) # Allow failure if not up

            # Perform a full system prune
            self.log.info("Pruning all Docker resources (images, containers, volumes, networks)...")
            self._run_command(["docker", "system", "prune", "-a", "--volumes", "--force"], check=True)

            self.log.info("Docker environment nuked successfully.")
        except (subprocess.CalledProcessError, Exception) as e:
            self.log.critical("Nuke operation failed: %s", e)
            sys.exit(1)

    def _handle_down(self):
        """Handles --down and --clear-volumes operations."""
        action = "Stopping containers and removing volumes" if self.args.clear_volumes else "Stopping containers"
        self.log.info(f"{action} for the current project...")

        if self.args.clear_volumes:
            try:
                confirm = input("This will delete Docker volumes associated with this project. Proceed? (yes/no): ").lower()
            except EOFError:
                self.log.error("Volume clearing requires interactive confirmation. Aborting.")
                sys.exit(1)
            if confirm != "yes":
                self.log.info("Volume deletion cancelled.")
                sys.exit(0)

        down_cmd = ["docker", "compose", "down", "--remove-orphans"]
        if self.args.clear_volumes:
            down_cmd.append("--volumes")

        try:
            # Use check=False because 'down' might fail if services aren't running, which is acceptable.
            self._run_command(down_cmd, check=False)
            self.log.info(f"{action} complete.")
        except Exception as e: # Catch broader exceptions from _run_command if needed
            self.log.error(f"Failed during docker-compose down: {e}")
            sys.exit(1)



    def _handle_build(self):
        """Handles building the Docker images using docker-compose build."""

        # Load environment variables from .env.docker
        load_dotenv(dotenv_path=".env.docker")
        env_values = dotenv_values(dotenv_path=".env.docker")

        # Log only the keys, not values, for security
        self.log.info(f".env.docker loaded with %d variables: %s", len(env_values), ', '.join(env_values.keys()))

        self.log.info("Building containers%s...", " (no cache)" if self.args.no_cache else "")
        build_cmd = ["docker", "compose", "build"]
        if self.args.no_cache:
            build_cmd.append("--no-cache")

        t_start = time.time()
        try:
            self._run_command(build_cmd, check=True)
            t_end = time.time()
            self.log.info("Build completed in %.2f seconds.", t_end - t_start)

            if self.args.tag:
                self.log.info(f"Applying tag: {self.args.tag} to all built images")
                self._tag_images(self.args.tag)

        except (subprocess.CalledProcessError, Exception) as e:
            self.log.critical(f"Docker build failed: {e}")
            sys.exit(1)

    def _tag_images(self, tag):
        """Tags all locally built images from docker-compose with the given tag."""
        try:
            self.log.info("Inspecting docker-compose config to determine service image mappings...")

            # Get the full compose config in JSON format
            service_config_json = self._run_command(
                ["docker", "compose", "config", "--format", "json"],
                capture_output=True, check=True
            ).stdout

            import json
            parsed = json.loads(service_config_json)
            services = parsed.get("services", {})

            if not services:
                self.log.warning("No services found in docker-compose config.")
                return

            for service_name, config in services.items():
                image_name = config.get("image")

                # We only want to tag our own local images
                if not image_name or not image_name.startswith("entities_api/"):
                    self.log.debug(f"Skipping external or unnamed image for service '{service_name}': {image_name}")
                    continue

                base_image = image_name.split(":")[0]
                original_tag = f"{base_image}:latest"
                new_tag = f"{base_image}:{tag}"

                self.log.info(f"Tagging {original_tag} → {new_tag}")
                self._run_command(["docker", "tag", original_tag, new_tag])

        except json.JSONDecodeError as e:
            self.log.error("Failed to parse docker-compose config as JSON: %s", e)
        except subprocess.CalledProcessError as e:
            self.log.error("Failed to run 'docker compose config --format json': %s", e)
        except Exception as e:
            self.log.error(f"Image tagging failed: {e}", exc_info=self.args.verbose)

    def _handle_up(self):
        """Handles starting the Docker containers using docker-compose up."""
        mode = "attached" if self.args.attached else "detached"
        self.log.info(f"Starting containers ({mode} mode)...")
        up_cmd = ["docker", "compose", "up"]
        if not self.args.attached:
            up_cmd.append("-d") # Run in detached mode

        try:
            self._run_command(up_cmd, check=True)
            self.log.info("Containers started successfully.")
            if not self.args.attached:
                 self.log.info("View logs with: docker compose logs -f")
        except (subprocess.CalledProcessError, Exception) as e:
            self.log.critical(f"Docker up failed: {e}")
            if not self.args.attached:
                self.log.info("Attempting to show logs from failed startup...")
                try:
                    # Show logs from all services
                    self._run_command(["docker", "compose", "logs", "--tail=100"], check=False)
                except Exception as log_e:
                    self.log.error(f"Could not fetch logs: {log_e}")
            sys.exit(1)

    # --- Main Execution Logic ---
    def run(self):
        """Main execution logic based on parsed arguments."""

        if self.args.debug_cache:
            self._run_docker_cache_diagnostics()
            sys.exit(0)

        if self.args.nuke:
            self._handle_nuke()
            sys.exit(0) # Nuke is a terminal action

        # Handle Ollama setup if requested - run before compose actions
        ollama_ok = self._ensure_ollama(opt_in=self.args.with_ollama, use_gpu=self.args.ollama_gpu)
        if not ollama_ok and self.args.with_ollama:
             # Decide if Ollama failure should stop the script if it was requested
             self.log.error("Ollama setup failed. Check logs above.")
             # sys.exit(1) # Uncomment if Ollama failure should be fatal when requested


        # Handle down/clear-volumes first if requested
        if self.args.down or self.args.clear_volumes:
            self._handle_down()
            # If only down/clear was requested (not build/up afterwards), exit now.
            if self.args.mode not in ["build", "both"]:
                sys.exit(0)

        # --- Handle Build and Up ---
        if self.args.mode in ["build", "both"]:
            if self.args.no_cache and self.args.mode == "up":
               self.log.critical("Invalid flag combination: --no-cache requires --mode 'build' or 'both'.")
               sys.exit(1)
            self._handle_build()

        if self.args.mode in ["up", "both"]:
            self._handle_up()

        self.log.info("Docker management script finished.")


    # --- Argument Parsing (Static Method) ---
    @staticmethod
    def parse_args():
        """Parses command-line arguments."""
        parser = argparse.ArgumentParser(
            description="Manage Docker Compose stack, environment setup, and optional Ollama.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter # Show defaults in help
        )
        # Docker Compose Actions
        parser.add_argument(
            "--mode",
            choices=["up", "build", "both"],
            default="up",
            help="Compose action: 'build' images, 'up' containers, or 'both'."
        )
        parser.add_argument(
            "--down",
            action="store_true",
            help="Stop and remove containers defined in the compose file."
        )
        parser.add_argument(
            "--clear-volumes",
            action="store_true",
            help="Stop containers AND remove associated named volumes (prompts for confirmation)."
        )
        parser.add_argument(
            "--no-cache",
            action="store_true",
            help="Build images without using the Docker cache (requires --mode build or both)."
        )
        parser.add_argument(
            "--attached",
            action="store_true",
            help="Run 'docker compose up' in attached mode (foreground, streaming logs)."
        )

        # Ollama Options
        parser.add_argument(
            "--with-ollama",
            action="store_true",
            help="Ensure an external Ollama service is running (pulls/starts Docker container if needed, outside compose)."
        )
        parser.add_argument(
            "--ollama-gpu",
            action="store_true",
            help="Attempt to run the external Ollama container with GPU acceleration (if --with-ollama is used and NVIDIA GPU is detected)."
        )

        # Maintenance & Debugging
        parser.add_argument(
            "--nuke",
            action="store_true",
            help="DANGER: Stop all containers, remove all volumes, networks, and images on the system! Requires confirmation."
        )
        parser.add_argument(
            "--verbose", "-v",
            action="store_true",
            help="Enable debug logging for this script."
        )
        parser.add_argument(
            "--debug-cache",
            action="store_true",
            help="Show Docker build context size and image history diagnostics, then exit."
        )

        parser.add_argument(
            "--tag",
            type=str,
            help="Optional tag to apply to each built image (e.g. '0.3.0-alpha.1')"
        )

        return parser.parse_args()


# --- Script Entry Point ---
if __name__ == "__main__":
    try:
        arguments = DockerManager.parse_args()
        manager = DockerManager(arguments)
        manager.run()
    except KeyboardInterrupt:
        log.info("\nOperation cancelled by user.")
        sys.exit(130) # Standard exit code for Ctrl+C
    except subprocess.CalledProcessError:
        # Error is already logged by _run_command
        log.critical("A critical command failed. See logs above.")
        sys.exit(1)
    except Exception as e:
        # Log the exception traceback if verbose mode is on, otherwise just the message
        log.critical("An unexpected error occurred: %s", e, exc_info=log.level == logging.DEBUG)
        sys.exit(1)