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

# Added import for json parsing in _tag_images
import json

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
            "__DEFAULT_API_KEY__": self._generate_secret(40),
            "__TOOL_CODE_INTERPRETER__": f"tool_{self._generate_secret(22)}",
            "__TOOL_WEB_SEARCH__": f"tool_{self._generate_secret(22)}",
            "__TOOL_COMPUTER__": f"tool_{self._generate_secret(22)}",
            "__TOOL_VECTOR_STORE_SEARCH__": f"tool_{self._generate_secret(22)}",
            "__SMBCLIENT_SERVER__": "samba_server",
            "__SMBCLIENT_SHARE__": "cosmic_share",
            "__SMBCLIENT_USERNAME__": "samba_user",
            "__SMBCLIENT_PASSWORD__": "default",
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
                    if "__DEFAULT_API_KEY__" not in content and output_file == ".env.docker":
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
            elif system == 'darwin': # macOS
                shared_path = os.path.join(default_base, "Library", "Application Support", "entities_share")
            else:
                self.log.error("Unsupported OS detected: %s. Cannot determine default shared path.", system)
                raise RuntimeError("Unsupported OS detected.")
            self.log.info("Defaulting SHARED_PATH to: %s", shared_path)
            os.environ['SHARED_PATH'] = shared_path

        try:
            if not os.path.exists(shared_path):
                os.makedirs(shared_path, exist_ok=True)
                self.log.info("Created shared directory: %s", shared_path)
            else:
                self.log.info("Shared directory already exists: %s", shared_path)
        except OSError as e:
            self.log.error(f"Failed to create shared directory {shared_path}: {e}. Check permissions.")

    # --- Ollama Integration ---
    def _has_docker(self):
        """Checks if the 'docker' command is available in the system PATH."""
        return shutil.which("docker") is not None

    def _is_container_running(self, container_name):
        """Checks if a Docker container with the given name is currently running."""
        try:
            result = self._run_command(
                ["docker", "ps", "--filter", f"name=^{container_name}$", "--quiet"],
                capture_output=True, text=True, check=False, suppress_logs=True
            )
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(f"Could not check if container '{container_name}' is running: {e}")
            return False

    def _is_image_present(self, image_name):
        """Checks if a Docker image with the given name exists locally."""
        try:
             result = self._run_command(
                 ["docker", "images", image_name, "--quiet"],
                 capture_output=True, text=True, check=False, suppress_logs=True
             )
             return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(f"Could not check if image '{image_name}' is present: {e}")
            return False

    def _has_nvidia_support(self):
        """Checks if 'nvidia-smi' command is available, indicating NVIDIA drivers."""
        has_smi = shutil.which("nvidia-smi") is not None
        if has_smi:
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
            return False

        container_name = self._OLLAMA_CONTAINER
        if self._is_container_running(container_name):
            self.log.info(f"✅ Ollama container '{container_name}' is already running.")
            return True

        image_name = self._OLLAMA_IMAGE
        if not self._is_image_present(image_name):
            self.log.info(f"📦 Pulling Ollama image '{image_name}'...")
            try:
                self._run_command(["docker", "pull", image_name], check=True)
            except (subprocess.CalledProcessError, Exception) as e:
                 self.log.error(f"❌ Failed to pull Ollama image: {e}")
                 return False

        self.log.info(f"🚀 Starting Ollama container '{container_name}'...")
        cmd = [
            "docker", "run", "-d",
            "--rm",
            "-v", "ollama:/root/.ollama",
            "-p", f"{self._OLLAMA_PORT}:{self._OLLAMA_PORT}",
            "--name", container_name
        ]
        if not cpu_only:
             if self._has_nvidia_support():
                 self.log.info("   Adding --gpus=all flag.")
                 cmd.insert(2, "--gpus=all")
             else:
                 self.log.warning("   GPU requested, but nvidia-smi check failed just before launch. Starting in CPU mode.")

        cmd.append(image_name)

        try:
            self._run_command(cmd, check=True)
            time.sleep(3)
            if self._is_container_running(container_name):
                self.log.info(f"✅ Ollama container '{container_name}' started successfully.")
                return True
            else:
                self.log.error(f"❌ Ollama container '{container_name}' failed to start. Check Docker logs: docker logs {container_name}")
                try:
                    self._run_command(["docker", "logs", container_name], check=False, suppress_logs=False)
                except Exception:
                    pass
                return False
        except (subprocess.CalledProcessError, Exception) as e:
            self.log.error(f"❌ Failed to start Ollama container: {e}")
            return False

    def _ensure_ollama(self, opt_in=False, use_gpu=False):
        """Ensures Ollama is set up based on user flags and system capabilities."""
        if not opt_in:
            self.log.info("ℹ️ Ollama integration is opt-in. Skipping setup.")
            return True

        self.log.info("--- Ollama Setup ---")
        system = platform.system()

        if os.path.exists("/.dockerenv") or os.environ.get("DOCKER_HOST"):
             self.log.warning("🛰 Detected running inside a container. Skipping external Ollama setup.")
             self.log.warning("   If you need Ollama, include it in your docker-compose.yml file.")
             self.log.info("--- End Ollama Setup ---")
             return True

        if system == "Darwin": # macOS
            self.log.warning("⚠️ macOS detected. Docker containers do not support GPU acceleration on Mac.")
            self.log.warning("👉 For best performance, please install and run the native Ollama app: https://ollama.com/download")
            self.log.info("   Skipping Docker-based Ollama setup on macOS.")
            self.log.info("--- End Ollama Setup ---")
            return True

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
                    if not islink(fp):
                        total_size += getsize(fp)
                except OSError as e:
                    self.log.debug("Could not get size of file %s: %s", fp, e)
                    continue
                except Exception as e:
                    self.log.warning("Unexpected error getting size of file %s: %s", fp, e)
                    continue
        return total_size / (1024 * 1024)

    def _run_docker_cache_diagnostics(self):
        """Runs diagnostics to understand Docker build cache usage."""
        self.log.info("--- Docker Cache Diagnostics ---")
        try:
            context_size_mb = self._get_directory_size()
            self.log.info("Approximate Docker build context size: %.2f MB", context_size_mb)

            ps_config = self._run_command(
                ["docker", "compose", "config", "--services"],
                capture_output=True, text=True, check=False
            )
            if ps_config.returncode != 0:
                self.log.warning("Could not get services from docker-compose config. Is docker-compose.yml valid?")
                services = []
            else:
                services = ps_config.stdout.strip().splitlines()
                self.log.info("Services defined in docker-compose config: %s", ", ".join(services))

            for service in services:
                image_name = service
                self.log.info(f"Inspecting image history for potential image '{image_name}':")
                try:
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
        except EOFError:
             self.log.error("Nuke requires interactive confirmation. Aborting.")
             sys.exit(1)

        if confirm != "yes":
            self.log.info("Nuke cancelled.")
            sys.exit(0)

        self.log.info("Proceeding with Docker nuke...")
        try:
            self.log.info("Stopping and removing compose services and volumes...")
            self._run_command(["docker", "compose", "down", "--volumes", "--remove-orphans"], check=False)

            self.log.info("Pruning all Docker resources (images, containers, volumes, networks)...")
            self._run_command(["docker", "system", "prune", "-a", "--volumes", "--force"], check=True)

            self.log.info("Docker environment nuked successfully.")
        except (subprocess.CalledProcessError, Exception) as e:
            self.log.critical("Nuke operation failed: %s", e)
            sys.exit(1)

    def _handle_down(self):
        """Handles --down and --clear-volumes operations."""
        target_services = self.args.services or []
        target_desc = f" for services: {', '.join(target_services)}" if target_services else ""
        action = "Stopping containers and removing volumes" if self.args.clear_volumes else "Stopping containers"
        self.log.info(f"{action}{target_desc}...")

        if self.args.clear_volumes and not target_services: # Only prompt for full volume clear
            try:
                confirm = input("This will delete ALL Docker volumes associated with this project. Proceed? (yes/no): ").lower()
            except EOFError:
                self.log.error("Volume clearing requires interactive confirmation. Aborting.")
                sys.exit(1)
            if confirm != "yes":
                self.log.info("Volume deletion cancelled.")
                sys.exit(0)
        elif self.args.clear_volumes and target_services:
             self.log.warning("Note: '--clear-volumes' with specific services might not remove all related volumes if they are shared or defined externally.")


        down_cmd = ["docker", "compose", "down", "--remove-orphans"]
        if self.args.clear_volumes:
            down_cmd.append("--volumes")

        # Add specific services to the command if provided
        if target_services:
            down_cmd.extend(target_services)

        try:
            self._run_command(down_cmd, check=False)
            self.log.info(f"{action} complete.")
        except Exception as e:
            self.log.error(f"Failed during docker-compose down: {e}")
            sys.exit(1)


    def _handle_build(self):
        """Handles building the Docker images using docker-compose build."""

        load_dotenv(dotenv_path=".env.docker")
        env_values = dotenv_values(dotenv_path=".env.docker")
        self.log.info(f".env.docker loaded with %d variables: %s", len(env_values), ', '.join(env_values.keys()))

        target_services = self.args.services or []
        target_desc = f" for services: {', '.join(target_services)}" if target_services else ""
        cache_desc = " (no cache)" if self.args.no_cache else ""
        self.log.info(f"Building containers{target_desc}{cache_desc}...")

        build_cmd = ["docker", "compose", "build"]
        if self.args.no_cache:
            build_cmd.append("--no-cache")

        # Add specific services to the command if provided
        if target_services:
            build_cmd.extend(target_services)

        t_start = time.time()
        try:
            self._run_command(build_cmd, check=True)
            t_end = time.time()
            self.log.info("Build completed in %.2f seconds.", t_end - t_start)

            if self.args.tag:
                self.log.info(f"Applying tag: {self.args.tag} to built images (target services: {target_services if target_services else 'all'})")
                # Pass the targeted services to the tagging function
                self._tag_images(self.args.tag, targeted_services=target_services)

        except (subprocess.CalledProcessError, Exception) as e:
            self.log.critical(f"Docker build failed: {e}")
            sys.exit(1)

    # --- Updated _tag_images to respect targeted services ---
    def _tag_images(self, tag, targeted_services=None):
        """
        Tags built images from docker-compose with the given tag.

        Args:
            tag (str): The tag to apply.
            targeted_services (list, optional): List of service names that were built.
                                                If None or empty, attempts to tag all services.
        """
        try:
            self.log.info("Inspecting docker-compose config to determine service image mappings...")

            service_config_json = self._run_command(
                ["docker", "compose", "config", "--format", "json"],
                capture_output=True, check=True
            ).stdout

            parsed = json.loads(service_config_json)
            services = parsed.get("services", {})

            if not services:
                self.log.warning("No services found in docker-compose config.")
                return

            tagged_count = 0
            for service_name, config in services.items():
                 # --- Logic to only tag specified services if provided ---
                if targeted_services and service_name not in targeted_services:
                    self.log.debug(f"Skipping tagging for service '{service_name}' as it was not in the build target list.")
                    continue
                # --- End targeting logic ---

                image_name = config.get("image")

                # Only tag images we likely built locally (adjust prefix if needed)
                if not image_name or not image_name.startswith("entities_api/") and not image_name.startswith("entities_"): # Adjust prefix if your naming is different
                    self.log.debug(f"Skipping external or potentially unnamed image for service '{service_name}': {image_name}")
                    continue

                # Assuming the built image defaults to :latest if no tag specified in compose
                base_image_parts = image_name.split(":")
                base_image = base_image_parts[0]
                original_image_ref = f"{base_image}:latest" # Assume latest if tag unspecified

                # Check if the assumed 'latest' image actually exists before tagging
                check_image_cmd = ["docker", "image", "inspect", original_image_ref]
                inspect_result = self._run_command(check_image_cmd, check=False, capture_output=True, suppress_logs=True)

                if inspect_result.returncode != 0:
                    self.log.warning(f"Could not find image '{original_image_ref}' to tag for service '{service_name}'. Skipping.")
                    # Maybe the image name in compose already has a tag? Try that.
                    if len(base_image_parts) > 1:
                         original_image_ref = image_name # Use the full name from compose
                         inspect_result_alt = self._run_command(["docker", "image", "inspect", original_image_ref], check=False, capture_output=True, suppress_logs=True)
                         if inspect_result_alt.returncode != 0:
                              self.log.warning(f"Also could not find image '{original_image_ref}' specified in compose file for service '{service_name}'. Definitely skipping tagging.")
                              continue
                         else:
                              self.log.info(f"Found image '{original_image_ref}' (from compose file) for service '{service_name}'.")
                    else:
                         continue # Skip if latest wasn't found and no tag in compose

                new_tag = f"{base_image}:{tag}"

                self.log.info(f"Tagging {original_image_ref} -> {new_tag}")
                try:
                    self._run_command(["docker", "tag", original_image_ref, new_tag], check=True)
                    tagged_count += 1
                except (subprocess.CalledProcessError, Exception) as tag_e:
                     self.log.error(f"Failed to tag {original_image_ref} for service {service_name}: {tag_e}")


            self.log.info(f"Tagging complete. {tagged_count} images tagged.")

        except json.JSONDecodeError as e:
            self.log.error("Failed to parse docker-compose config as JSON: %s", e)
        except subprocess.CalledProcessError as e:
            self.log.error("Failed to run 'docker compose config --format json': %s", e)
        except Exception as e:
            self.log.error(f"Image tagging failed: {e}", exc_info=self.args.verbose)


    def _handle_up(self):
        """Handles starting the Docker containers using docker-compose up."""
        mode = "attached" if self.args.attached else "detached"
        target_services = self.args.services or []
        target_desc = f" for services: {', '.join(target_services)}" if target_services else ""

        self.log.info(f"Starting containers{target_desc} ({mode} mode)...")
        up_cmd = ["docker", "compose", "up"]
        if not self.args.attached:
            up_cmd.append("-d")

        # Add specific services to the command if provided
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
        except (subprocess.CalledProcessError, Exception) as e:
            self.log.critical(f"Docker up failed: {e}")
            if not self.args.attached:
                self.log.info("Attempting to show logs from failed startup...")
                try:
                    # Show logs only from the targeted services if specified
                    logs_cmd = ["docker", "compose", "logs", "--tail=100"]
                    if target_services:
                        logs_cmd.extend(target_services)
                    self._run_command(logs_cmd, check=False)
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
            sys.exit(0)

        ollama_ok = self._ensure_ollama(opt_in=self.args.with_ollama, use_gpu=self.args.ollama_gpu)
        if not ollama_ok and self.args.with_ollama:
             self.log.error("Ollama setup failed. Check logs above.")
             # sys.exit(1) # Decide if fatal

        # --- Handle down/clear-volumes first ---
        # Combine down and clear_volumes flags for the condition
        # Execute if --down or --clear-volumes is specified
        if self.args.down or self.args.clear_volumes:
            self._handle_down()
            # If *only* down/clear was requested (mode is not build/both), exit.
            if self.args.mode not in ["build", "both"]:
                sys.exit(0)

        # --- Handle Build and Up ---
        if self.args.mode in ["build", "both"]:
            # Check for invalid flag combination
            if self.args.no_cache and self.args.mode == "up":
               self.log.critical("Invalid flag combination: --no-cache requires --mode 'build' or 'both'.")
               sys.exit(1)
            # Check if --no-cache or --tag used without specifying services (could be slow/unintended)
            if (self.args.no_cache or self.args.tag) and not self.args.services:
                 self.log.warning("Using --no-cache or --tag without --services will affect ALL services defined in compose file.")
                 # Optional: Add confirmation prompt here if desired
                 # try:
                 #     confirm = input("Proceed? (yes/no): ").lower()
                 #     if confirm != 'yes': sys.exit(0)
                 # except EOFError: sys.exit(1)

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
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )
        # Docker Compose Actions
        parser.add_argument(
            "--mode",
            choices=["up", "build", "both", "down_only"], # Added down_only for clarity if needed
            default="up",
            help="Compose action: 'build' images, 'up' containers, 'both' build then up, or 'down_only'."
        )
        parser.add_argument(
            "--down",
            action="store_true",
            help="Stop and remove containers defined in the compose file (can be combined with --mode or run standalone)."
        )
        parser.add_argument(
            "--clear-volumes",
            action="store_true",
            help="When running 'down', also remove associated named volumes (prompts for confirmation unless --services specified)."
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
        # --- NEW ARGUMENT ---
        parser.add_argument(
            "--services",
            nargs='+', # Expect one or more service names
            metavar='SERVICE_NAME',
            help="Target specific service(s) for build, up, or down actions."
        )
        # --- END NEW ARGUMENT ---


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
            help="Optional tag to apply to built image(s) (e.g. '0.3.0-alpha.1'). Applied to services specified by --services, or all if --services not used."
        )

        # Small logic adjustment for clarity on standalone --down / --clear-volumes
        args = parser.parse_args()
        if (args.down or args.clear_volumes) and args.mode not in ['build', 'both']:
             args.mode = 'down_only' # Set mode explicitly if down/clear is the primary action

        return args


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
        log.critical("A critical command failed. See logs above.")
        sys.exit(1)
    except Exception as e:
        log.critical("An unexpected error occurred: %s", e, exc_info=log.level == logging.DEBUG)
        sys.exit(1)
