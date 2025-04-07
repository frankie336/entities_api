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
import yaml  # Needs: pip install PyYAML

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
        self._configure_shared_path()
        self._generate_runtime_compose_file()
        self._ensure_dockerignore()

    # --- Core Docker/System Command Execution ---
    def _run_command(self, cmd_list, check=True, capture_output=False, text=True, suppress_logs=False, **kwargs):
        processed_cmd_list = list(cmd_list)
        if processed_cmd_list[0] == "docker" and len(processed_cmd_list) > 1 and processed_cmd_list[1] == "compose":
            if "-f" not in processed_cmd_list:
                compose_subcommand_index = 2
                processed_cmd_list.insert(compose_subcommand_index, "-f")
                processed_cmd_list.insert(compose_subcommand_index + 1, self._RUNTIME_COMPOSE_FILE)
                log.debug(f"Injecting runtime compose file flag: {' '.join(processed_cmd_list)}")
        cmd_str = " ".join(processed_cmd_list)
        if not suppress_logs:
            self.log.info("Running command: %s", cmd_str)
        try:
            result = subprocess.run(processed_cmd_list, check=check, capture_output=capture_output, text=text, shell=self.is_windows, **kwargs)
            if not suppress_logs:
                self.log.debug("Command finished: %s", cmd_str)
                if result.stdout:
                    self.log.debug("Command stdout:\n%s", result.stdout.strip())
                if result.stderr and result.stderr.strip():
                    self.log.debug("Command stderr:\n%s", result.stderr.strip())
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
        ignore_content_base = ["__pycache__/", ".venv/", "*.pyc", ".git/", ".env*", "!.env.example", "*.sqlite", "dist/", "build/", ".idea/", ".vscode/"]
        if not dockerignore.exists():
            self.log.warning(".dockerignore not found. Generating default...")
            full_ignore_content = ignore_content_base + [runtime_ignore_line]
            dockerignore.write_text("\n".join(full_ignore_content) + "\n")
        else:
            try:
                current_ignores = dockerignore.read_text().splitlines()
                if runtime_ignore_line not in current_ignores:
                    self.log.info(f"Adding '{runtime_ignore_line}' to existing .dockerignore")
                    with open(dockerignore, "a", encoding="utf-8") as f:
                        f.write(f"\n{runtime_ignore_line}\n")
            except Exception as e:
                log.warning(f"Could not read/update .dockerignore: {e}")

    # --- Environment File Generation ---
    def _generate_dot_env_example_file(self):
        target_example_file = Path(self._ENV_EXAMPLE_FILE)
        if target_example_file.exists():
            log.debug(f"Example env file exists.")
            return
        self.log.info(f"Generating default example env file: {target_example_file}...")
        default_content = """# .env.example ... (Content as provided previously) ...
ASSISTANTS_BASE_URL="http://localhost:9000/"
SANDBOX_SERVER_URL="http://sandbox:8000"
DOWNLOAD_BASE_URL="http://localhost:9000/v1/files/download"
DATABASE_URL="mysql+pymysql://__MYSQL_USER__:__MYSQL_PASSWORD__@db:3306/__MYSQL_DATABASE__"
SPECIAL_DB_URL="mysql+pymysql://__MYSQL_USER__:__MYSQL_PASSWORD__@localhost:__MYSQL_EXTERNAL_PORT__/__MYSQL_DATABASE__"
MYSQL_ROOT_PASSWORD="__MYSQL_ROOT_PASSWORD__"
MYSQL_DATABASE="__MYSQL_DATABASE__"
MYSQL_USER="__MYSQL_USER__"
MYSQL_PASSWORD="__MYSQL_PASSWORD__"
MYSQL_EXTERNAL_PORT="3307"
API_KEY="__DEFAULT_API_KEY__"
QDRANT_HOST="qdrant"
QDRANT_PORT="6333"
QDRANT_URL="http://${QDRANT_HOST}:${QDRANT_PORT}"
OLLAMA_HOST="ollama"
OLLAMA_PORT="11434"
DEFAULT_SECRET_KEY="__DEFAULT_SECRET_KEY__"
BASE_URL_HEALTH="http://localhost:9000/v1/health"
SHELL_SERVER_URL="ws://sandbox_api:8000/ws/computer"
CODE_EXECUTION_URL="ws://sandbox_api:8000/ws/execute"
SIGNED_URL_SECRET="__SIGNED_URL_SECRET__"
SECRET_KEY="__SECRET_KEY__"
DISABLE_FIREJAIL="true"
SMBCLIENT_SERVER="samba_server"
SMBCLIENT_SHARE="cosmic_share"
SMBCLIENT_USERNAME="samba_user"
SMBCLIENT_PASSWORD="default"
SMBCLIENT_PORT="445"
TOOL_CODE_INTERPRETER="tool___TOOL_CODE_INTERPRETER__"
TOOL_WEB_SEARCH="tool___TOOL_WEB_SEARCH__"
TOOL_COMPUTER="tool___TOOL_COMPUTER__"
TOOL_VECTOR_STORE_SEARCH="tool___TOOL_VECTOR_STORE_SEARCH__"
LOG_LEVEL="INFO"
PYTHONUNBUFFERED="1"
SHARED_PATH="./shared"
SAMBA_USERID="1000"
SAMBA_GROUPID="1000"
SAMBA_TZ="UTC"
"""
        try:
            target_example_file.write_text(default_content, encoding="utf-8")
        except Exception as e:
            self.log.error(f"Failed to generate {target_example_file}: {e}")

    def _ensure_env_example_file(self):
        if not os.path.exists(self._ENV_EXAMPLE_FILE):
            self.log.warning(f"Missing example env file: {self._ENV_EXAMPLE_FILE}. Generating.")
            self._generate_dot_env_example_file()

    def _generate_dot_env_file_content(self):
        self.log.info("Generating real values for new .env file...")
        db_user = "ollama"
        db_password = secrets.token_hex(16)
        db_root_password = secrets.token_hex(16)
        db_name = "cosmic_catalyst"
        secret_key_val = secrets.token_hex(32)
        signed_url_secret_val = secrets.token_hex(32)
        api_key_val = secrets.token_hex(16)
        default_secret_key_val = secrets.token_urlsafe(32)
        qdrant_host = "qdrant"
        qdrant_port = "6333"
        qdrant_url = f"http://{qdrant_host}:{qdrant_port}"
        sandbox_server_url = "http://sandbox:8000"
        mysql_external_port = "3307"
        database_url_val = f"mysql+pymysql://{db_user}:{db_password}@db:3306/{db_name}"
        special_db_url_val = f"mysql+pymysql://{db_user}:{db_password}@localhost:{mysql_external_port}/{db_name}"
        smb_user = "samba_user"
        smb_password = "default"
        smb_share = "cosmic_share"
        tool_code = f"tool_{secrets.token_hex(8)}"
        tool_web = f"tool_{secrets.token_hex(8)}"
        tool_comp = f"tool_{secrets.token_hex(8)}"
        tool_vec = f"tool_{secrets.token_hex(8)}"
        env_dict = {
            "ASSISTANTS_BASE_URL": "http://localhost:9000/",
            "SANDBOX_SERVER_URL": sandbox_server_url,
            "DOWNLOAD_BASE_URL": "http://localhost:9000/v1/files/download",
            "DATABASE_URL": database_url_val,
            "SPECIAL_DB_URL": special_db_url_val,
            "MYSQL_ROOT_PASSWORD": db_root_password,
            "MYSQL_DATABASE": db_name,
            "MYSQL_USER": db_user,
            "MYSQL_PASSWORD": db_password,
            "MYSQL_EXTERNAL_PORT": mysql_external_port,
            "API_KEY": api_key_val,
            "QDRANT_HOST": qdrant_host,
            "QDRANT_PORT": qdrant_port,
            "QDRANT_URL": qdrant_url,
            "OLLAMA_HOST": "ollama",
            "OLLAMA_PORT": self._OLLAMA_PORT,
            "DEFAULT_SECRET_KEY": default_secret_key_val,
            "BASE_URL_HEALTH": "http://localhost:9000/v1/health",
            "SHELL_SERVER_URL": "ws://sandbox_api:8000/ws/computer",
            "CODE_EXECUTION_URL": "ws://sandbox_api:8000/ws/execute",
            "SIGNED_URL_SECRET": signed_url_secret_val,
            "SECRET_KEY": secret_key_val,
            "DISABLE_FIREJAIL": "true",
            "SMBCLIENT_SERVER": "samba_server",
            "SMBCLIENT_SHARE": smb_share,
            "SMBCLIENT_USERNAME": smb_user,
            "SMBCLIENT_PASSWORD": smb_password,
            "SMBCLIENT_PORT": "445",
            "TOOL_CODE_INTERPRETER": tool_code,
            "TOOL_WEB_SEARCH": tool_web,
            "TOOL_COMPUTER": tool_comp,
            "TOOL_VECTOR_STORE_SEARCH": tool_vec,
            "LOG_LEVEL": "INFO",
            "PYTHONUNBUFFERED": "1",
            "SHARED_PATH": "./shared",  # Defaults added
            "SAMBA_USERID": "1000",
            "SAMBA_GROUPID": "1000",
            "SAMBA_TZ": "UTC"
        }
        return env_dict

    def _write_dot_env_file(self, env_dict):
        self.log.info(f"Writing generated values to {self._ENV_FILE}...")
        lines = [f"# Auto-generated .env file on: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"]
        lines.extend([f"{key}={value}" for key, value in env_dict.items()])
        try:
            Path(self._ENV_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as e:
            self.log.error(f"Failed write {self._ENV_FILE}: {e}")
            sys.exit(1)

    def _ensure_required_env_file_and_load(self):
        self.log.debug(f"Ensuring '{self._ENV_FILE}' exists and loading values...")
        env_file_path = Path(self._ENV_FILE)
        if not env_file_path.exists():
            self.log.warning(f"Required env file '{self._ENV_FILE}' missing. Generating.")
            generated_values = self._generate_dot_env_file_content()
            self._write_dot_env_file(generated_values)
            self.env_values = generated_values
        else:
            self.log.info(f"Loading values from existing '{self._ENV_FILE}'.")
            loaded = dotenv_values(self._ENV_FILE)
            self.env_values = {k: v for k, v in loaded.items() if v is not None}
        if not self.env_values:
            self.log.critical(f"Failed load/generate env vars from '{self._ENV_FILE}'.")
            sys.exit(1)
        required = ["MYSQL_ROOT_PASSWORD", "MYSQL_USER", "MYSQL_PASSWORD", "DATABASE_URL", "SHARED_PATH"]
        missing = [k for k in required if k not in self.env_values or not self.env_values[k]]
        if missing:
            self.log.warning(f"!!! Check .env: Missing/empty required keys: {', '.join(missing)}")
        self.log.debug(f"Loaded/Generated {len(self.env_values)} environment variables.")

    # --- Shared Path Configuration ---
    def _configure_shared_path(self):
        system = platform.system().lower()
        shared_path = os.environ.get('SHARED_PATH')
        source = "system environment"
        if not shared_path and 'SHARED_PATH' in self.env_values and self.env_values['SHARED_PATH']:
            shared_path = self.env_values['SHARED_PATH']
            source = f"'{self._ENV_FILE}'"
        if shared_path:
            self.log.info(f"Using SHARED_PATH from {source}: %s", shared_path)
        else:  # Generate default
            source = "OS default"
            default_base = os.path.expanduser("~")
            if system == 'windows':
                shared_path = path_join(os.environ.get('LOCALAPPDATA', path_join(default_base, 'AppData', 'Local')), "EntitiesApi", "Share")
            elif system == 'linux':
                shared_path = path_join(default_base, ".local", "share", "entities_api_share")
            elif system == 'darwin':
                shared_path = path_join(default_base, "Library", "Application Support", "entities_api_share")
            else:
                raise RuntimeError(f"Unsupported OS: {system}")
            self.log.info("Defaulting SHARED_PATH to: %s", shared_path)
        shared_path = os.path.abspath(shared_path)  # Ensure absolute path
        try:
            Path(shared_path).mkdir(parents=True, exist_ok=True)
            self.log.info("Ensured shared directory exists: %s", shared_path)
        except Exception as e:
            self.log.error(f"Error configuring shared path {shared_path}: {e}")
        os.environ['SHARED_PATH'] = shared_path
        self.env_values['SHARED_PATH'] = shared_path
        self.log.debug(f"Final SHARED_PATH set to: {shared_path}")

    # --- Runtime Compose File Generation ---
    def _substitute_variables(self, value):
        if isinstance(value, str):
            if value.strip().startswith('${SHARED_PATH'):
                log.debug(f"Skipping substitution for SHARED_PATH placeholder: {value}")
                return value
            original_value = value
            max_substitutions = 10
            count = 0
            while count < max_substitutions:
                start_index = value.find("${")
                if start_index == -1:
                    break
                end_index = value.find("}", start_index)
                if end_index == -1:
                    self.log.warning(f"Malformed var in '{original_value}'.")
                    break
                var_content = value[start_index + 2:end_index]
                var_name = var_content
                default_val = None
                if ":-" in var_content:
                    var_name, default_val = var_content.split(":-", 1)
                sub_value = self.env_values.get(var_name, default_val)
                if sub_value is not None:
                    value = value[:start_index] + str(sub_value) + value[end_index + 1:]
                else:
                    self.log.warning(f"Var '{var_name}' not found for '{original_value}'. Removing.")
                    value = value[:start_index] + value[end_index + 1:]
                count += 1
            if count == max_substitutions:
                self.log.warning(f"Max substitutions for '{original_value}'.")
            return value
        elif isinstance(value, list):
            return [self._substitute_variables(item) for item in value]
        elif isinstance(value, dict):
            return {key: self._substitute_variables(val) for key, val in value.items()}
        else:
            return value

    def _generate_runtime_compose_file(self):
        self.log.info(f"Generating runtime compose file: {self._RUNTIME_COMPOSE_FILE}")
        template_path = Path(self._TEMPLATE_COMPOSE_FILE)
        runtime_path = Path(self._RUNTIME_COMPOSE_FILE)
        if not template_path.exists():
            self.log.critical(f"Template file not found: {template_path}.")
            sys.exit(1)
        try:
            with open(template_path, 'r', encoding='utf-8') as f_template:
                compose_data = yaml.load(f_template, Loader=yaml.FullLoader)
            if not compose_data or 'services' not in compose_data:
                self.log.error(f"Invalid template: {template_path}.")
                sys.exit(1)
            compose_data = self._substitute_variables(compose_data)
            self.log.debug("Completed ${VAR} substitutions.")
            services_to_inject = {
                "api": ["DATABASE_URL", "SANDBOX_SERVER_URL", "QDRANT_URL", "DEFAULT_SECRET_KEY"],
                "db": ["MYSQL_ROOT_PASSWORD", "MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD"],
                "qdrant": ["QDRANT__STORAGE__STORAGE_PATH", "QDRANT__SERVICE__GRPC_PORT", "QDRANT__LOG_LEVEL"],
                "samba": ["USER", "SHARE", "GLOBAL", "TZ", "USERID", "GROUPID"]
            }
            for service_name, env_vars_to_inject in services_to_inject.items():
                if service_name in compose_data.get('services', {}):
                    service_config = compose_data['services'][service_name]
                    if 'environment' not in service_config:
                        service_config['environment'] = []
                    if isinstance(service_config['environment'], dict):
                        service_config['environment'] = [f"{k}={v}" for k, v in service_config['environment'].items()]
                    existing_env_keys = {item.split("=", 1)[0].lower(): i for i, item in enumerate(service_config['environment']) if isinstance(item, str) and "=" in item}
                    for var_name in env_vars_to_inject:
                        value_to_set = None
                        if service_name == "samba":
                            if var_name == "USER":
                                value_to_set = f"{self.env_values.get('SMBCLIENT_USERNAME', 'samba_user')};{self.env_values.get('SMBCLIENT_PASSWORD', 'default')}"
                            elif var_name == "SHARE":
                                value_to_set = f"{self.env_values.get('SMBCLIENT_SHARE', 'cosmic_share')};/samba/share;yes;no;no;{self.env_values.get('SMBCLIENT_USERNAME', 'samba_user')}"
                            elif var_name == "GLOBAL":
                                value_to_set = self.env_values.get(var_name, "server min protocol = NT1\\nserver max protocol = SMB3")
                            elif var_name == "TZ":
                                value_to_set = self.env_values.get('SAMBA_TZ', 'UTC')
                            elif var_name == "USERID":
                                value_to_set = self.env_values.get('SAMBA_USERID', '1000')
                            elif var_name == "GROUPID":
                                value_to_set = self.env_values.get('SAMBA_GROUPID', '1000')
                            else:
                                value_to_set = self.env_values.get(var_name)
                        elif service_name == "qdrant":
                            static_values = {"QDRANT__STORAGE__STORAGE_PATH": "/qdrant/storage", "QDRANT__SERVICE__GRPC_PORT": "6334"}
                            value_to_set = self.env_values.get(var_name, static_values.get(var_name))
                        else:
                            value_to_set = self.env_values.get(var_name)
                        if value_to_set is not None:
                            env_string = f"{var_name}={value_to_set}"
                            if service_name == "samba" and var_name == "GLOBAL" and '\\n' in value_to_set:
                                value_to_set = value_to_set.replace('\\n', '\n')
                                env_string = f"{var_name}={value_to_set}"
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
            if 'sandbox' in compose_data.get('services', {}):
                if 'environment' in compose_data['services']['sandbox']:
                    log.debug("Removing 'environment' from 'sandbox'.")
                    del compose_data['services']['sandbox']['environment']
            class MultilineLiteralDumper(yaml.Dumper):
                def represent_scalar(self, tag, value, style=None):
                    if isinstance(value, str) and '\n' in value:
                        return super().represent_scalar(tag, value, style='|')  # Check type first
                    return super().represent_scalar(tag, value, style=style)
            with open(runtime_path, 'w', encoding='utf-8') as f_runtime:
                yaml.dump(compose_data, f_runtime, Dumper=MultilineLiteralDumper, default_flow_style=False, sort_keys=False, indent=2, allow_unicode=True)
            self.log.info(f"Successfully generated {runtime_path}")
        except Exception as e:
            self.log.critical(f"Error generating runtime file: {e}", exc_info=self.args.verbose)
            sys.exit(1)

    # --- Ollama Integration ---
    def _has_docker(self):
        return shutil.which("docker") is not None

    def _is_container_running(self, container_name):
        try:
            result = self._run_command(["docker", "ps", "--filter", f"name=^{container_name}$", "--quiet"], capture_output=True, text=True, check=False, suppress_logs=True)
            return bool(result.stdout.strip())
        except Exception as e:
            self.log.warning(f"Check container '{container_name}' failed: {e}")
            return False

    def _is_image_present(self, image_name):
        try:
            result = self._run_command(["docker", "images", image_name, "--quiet"], capture_output=True, text=True, check=False, suppress_logs=True)
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
            self.log.info(f"✅ Ollama '{c_name}' running.")
            return True
        if not self._is_image_present(i_name):
            self.log.info(f"📦 Pulling Ollama image '{i_name}'...")
            try:
                self._run_command(["docker", "pull", i_name], check=True)
            except Exception as e:
                self.log.error(f"❌ Pull failed: {e}")
                return False
        self.log.info(f"🚀 Starting Ollama container '{c_name}'...")
        cmd = ["docker", "run", "-d", "--rm", "-v", "ollama:/root/.ollama", "-p", f"{port}:{port}", "--name", c_name]
        if not cpu_only and self._has_nvidia_support():
            cmd.insert(2, "--gpus=all")
        elif not cpu_only:
            self.log.warning("   GPU requested, none found. CPU mode.")
        cmd.append(i_name)

        try:
            self._run_command(cmd, check=True)
            time.sleep(5)  # Wait a moment
            if self._is_container_running(c_name):
                self.log.info(f"✅ Ollama started on port {port}.")
                return True
            else:
                # Container failed to stay running
                self.log.error(f"❌ Ollama container '{c_name}' failed to start/stay running. Checking logs...")
                try:
                    # Try to get logs
                    self._run_command(["docker", "logs", "--tail", "50", c_name], check=False, suppress_logs=True)
                except Exception as le:
                    self.log.error(f"   Log retrieval failed: {le}")
                return False  # Indicate overall failure
        except Exception as e:
            self.log.error(f"❌ Failed 'docker run' for Ollama: {e}")
            return False  # Indicate overall failure

    def _ensure_ollama(self, opt_in=False, use_gpu=False):
        if not opt_in:
            self.log.info("ℹ️ Ollama not requested.")
            return True
        self.log.info("--- Ollama Setup ---")
        run_gpu = use_gpu
        if platform.system() == "Darwin":
            self.log.warning("⚠️ macOS detected, forcing CPU.")
            run_gpu = False
        gpu_avail = False
        if run_gpu:
            gpu_avail = self._has_nvidia_support()
        if run_gpu and not gpu_avail:
            self.log.warning("⚠️ GPU requested, none found. CPU mode.")
        start_gpu = run_gpu and gpu_avail
        mode = "GPU" if start_gpu else "CPU"
        self.log.info(f"Attempting Ollama start ({mode} mode)...")
        success = self._start_ollama(cpu_only=not start_gpu)
        self.log.info("--- End Ollama Setup ---")
        return success

    # --- Docker Cache Diagnostics ---
    def _get_directory_size(self, path_str="."):
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
            for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
                current_rel_path = Path(dirpath).relative_to(root_path)
                dirs_to_remove = []
                for i, dirname in enumerate(dirnames):
                    dir_rel_path = current_rel_path / dirname
                    if (dirname in ignore_patterns or f"{dirname}/" in ignore_patterns or
                        any(p.name in ignore_patterns or f"{p.name}/" in ignore_patterns for p in dir_rel_path.parents)):
                        dirs_to_remove.append(dirname)
                for d in reversed(dirs_to_remove):
                    dirnames.remove(d)
                for filename in filenames:
                    file_rel_path = current_rel_path / filename
                    if (filename in ignore_patterns or
                        (Path(filename).suffix and f"*{Path(filename).suffix}" in ignore_patterns) or
                        any(p.name in ignore_patterns or f"{p.name}/" in ignore_patterns for p in file_rel_path.parents)):
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
            self.log.info(f"Context size: {context_size_mb:.2f} MB")
            if context_size_mb > 500:
                self.log.warning("Context > 500MB. Check .dockerignore.")
            ps_config = self._run_command(["docker", "compose", "config", "--services"], capture_output=True, text=True, check=False, suppress_logs=True)
            services = ps_config.stdout.strip().splitlines() if ps_config.returncode == 0 and ps_config.stdout else []
            image_names = {}
            if services:
                self.log.info("Services: %s", ", ".join(services))
            else:
                self.log.warning("Could not list services.")
                return  # Exit diagnostic if no services

            try:
                config_json = self._run_command(["docker", "compose", "config", "--format", "json"], capture_output=True, text=True, check=True, suppress_logs=True).stdout
                config_data = json.loads(config_json)
                image_names = {s_name: s_cfg.get("image") for s_name, s_cfg in config_data.get("services", {}).items() if s_cfg.get("image")}
            except Exception as e:
                log.warning(f"Could not parse config for image names: {e}")

            for service_name in services:
                image_name = image_names.get(service_name)
                if not image_name:
                    continue  # Corrected syntax applied here previously

                self.log.info(f"--- History for '{image_name}' ({service_name}) ---")
                try:
                    history = self._run_command(["docker", "history", image_name, "--no-trunc", "--format", "{{.ID}} | {{.Size}} | {{.CreatedBy}}"], check=False, capture_output=True, text=True, suppress_logs=True)
                    if history.returncode == 0:
                        output = history.stdout.strip() if history.stdout else "No history found."
                        self.log.info(f"History:\n{output}")
                    else:
                        err_msg = history.stderr.strip() if history.stderr else "Unknown history error"
                        self.log.warning(f"History command failed:\n{err_msg}")
                except Exception as e:
                    self.log.warning(f"Error running docker history: {e}")
                self.log.info(f"--- End History ---")

        except Exception as e:
            self.log.error("Cache diagnostics failed: %s", e, exc_info=self.args.verbose)
        self.log.info("--- End Docker Cache Diagnostics ---")

    # --- Docker Compose Actions ---
    def _handle_nuke(self):
        self.log.warning("!!! NUKE MODE ACTIVATED !!!")
        try:
            confirm = input("Type 'NUKE DOCKER' to confirm: ")
        except EOFError:
            self.log.error("Nuke confirmation needed.")
            sys.exit(1)
        if confirm != "NUKE DOCKER":
            self.log.info("Nuke cancelled.")
            sys.exit(0)
        self.log.info("Nuking Docker...")
        try:
            self._run_command(["docker", "compose", "down", "--volumes", "--remove-orphans", "--timeout", "10"], check=False)
            self._run_command(["docker", "system", "prune", "-a", "--volumes", "--force"], check=True)
            self.log.info("✅ Nuke complete.")
        except Exception as e:
            self.log.critical(f"Nuke failed: {e}")
            sys.exit(1)

    def _handle_down(self):
        target_services = self.args.services or []
        action = "Stopping containers"
        if self.args.clear_volumes:
            action += " and removing volumes"
            if not target_services:
                try:
                    confirm = input("Delete ALL project volumes? (yes/no): ").lower().strip()
                except EOFError:
                    self.log.error("Confirmation needed.")
                    sys.exit(1)
                if confirm != 'yes':
                    self.log.info("Volume deletion cancelled.")
                    self.args.clear_volumes = False
            else:
                self.log.warning("Targeting services; shared volumes might remain.")
        self.log.info(f"{action}...")
        down_cmd = ["docker", "compose", "down", "--remove-orphans", "--timeout", "30"]
        if self.args.clear_volumes:
            down_cmd.append("--volumes")
        try:
            self._run_command(down_cmd, check=True)
            self.log.info(f"✅ Down complete.")
        except Exception as e:
            self.log.error(f"'down' failed: {e}")
            sys.exit(1)

    def _handle_build(self):
        self.log.info(f"Using compose file: {self._RUNTIME_COMPOSE_FILE}")
        target_services = self.args.services or []
        build_cmd = ["docker", "compose", "build"]
        t_start = time.time()
        if self.args.no_cache:
            build_cmd.append("--no-cache")
        if self.args.pull:
            build_cmd.append("--pull")
        if target_services:
            build_cmd.extend(target_services)
        self.log.info(f"Building images ({' '.join(target_services) or 'all'})...")
        try:
            self._run_command(build_cmd, check=True)
            t_end = time.time()
            self.log.info("✅ Build complete in %.2f sec.", t_end - t_start)
            if self.args.tag:
                self._tag_images(self.args.tag, targeted_services=target_services)
        except Exception as e:
            self.log.critical(f"Build failed: {e}")
            sys.exit(1)

    def _tag_images(self, tag, targeted_services=None):
        if not tag:
            return
        self.log.info(f"Tagging images with '{tag}'...")
        try:
            config_json = self._run_command(["docker", "compose", "config", "--format", "json"], capture_output=True, check=True, suppress_logs=True).stdout
            config_data = json.loads(config_json)
            services = config_data.get("services", {})
            count = 0
            for s_name, s_cfg in services.items():
                if targeted_services and s_name not in targeted_services:
                    continue
                img = s_cfg.get("image")
                if not img:
                    continue
                base_img = img.split(":", 1)[0]
                new_ref = f"{base_img}:{tag}"
                self.log.info(f"  Tagging {img} -> {new_ref} ({s_name})")
                try:
                    self._run_command(["docker", "tag", img, new_ref], check=True, suppress_logs=not self.args.verbose)
                    count += 1
                except Exception as e:
                    self.log.error(f"    Failed tag: {e}")
            self.log.info(f"Tagging complete ({count} tagged).")
        except Exception as e:
            self.log.error(f"Tagging process failed: {e}")

    def _handle_up(self):
        self.log.info(f"Using compose file: {self._RUNTIME_COMPOSE_FILE}")
        target_services = self.args.services or []
        up_cmd = ["docker", "compose", "up"]
        mode = "detached" if not self.args.attached else "attached"
        if not self.args.attached:
            up_cmd.append("-d")
        if self.args.build_before_up:
            up_cmd.append("--build")
        if self.args.force_recreate:
            up_cmd.append("--force-recreate")
        if target_services:
            up_cmd.extend(target_services)
        self.log.info(f"Starting containers ({' '.join(target_services) or 'all'}) in {mode} mode...")
        try:
            self._run_command(up_cmd, check=True)
            self.log.info("✅ Containers started.")
            if not self.args.attached:
                log_cmd_display = ["docker", "compose", "-f", self._RUNTIME_COMPOSE_FILE, "logs", "-f", "--tail", "50"]
                if target_services:
                    log_cmd_display.extend(target_services)
                self.log.info(f"👀 View logs: {' '.join(log_cmd_display)}")
        except subprocess.CalledProcessError as e:
            self.log.critical("'up' failed.")
            try:
                logs_cmd = ["docker", "compose", "logs", "--tail=100"]
                self._run_command(logs_cmd, check=False)
            except Exception:
                pass
            sys.exit(e.returncode or 1)
        except Exception as e:
            self.log.critical(f"'up' error: {e}")
            sys.exit(1)

    # --- Main Execution Logic ---
    def run(self):
        if self.args.debug_cache:
            self._run_docker_cache_diagnostics()
            sys.exit(0)
        if self.args.nuke:
            self._handle_nuke()
            sys.exit(0)  # Nuke exits if confirmed
        if self.args.with_ollama:
            if not self._ensure_ollama(opt_in=True, use_gpu=self.args.ollama_gpu):
                self.log.error("Ollama setup failed.")
        if self.args.down or self.args.clear_volumes or self.args.mode == 'down_only':
            self._handle_down()
            if self.args.mode == 'down_only':
                sys.exit(0)
        if self.args.mode in ["build", "both"]:
            self._handle_build()
        if self.args.mode in ["up", "both"]:
            self._handle_up()
        self.log.info("Script finished.")

    # --- Argument Parsing ---
    @staticmethod
    def parse_args():
        parser = argparse.ArgumentParser(description="Manage stack via runtime compose file.", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser.add_argument("--mode", choices=["up", "build", "both", "down_only"], default="up")
        parser.add_argument("--no-cache", action="store_true")
        parser.add_argument("--pull", action="store_true")
        parser.add_argument("--tag", type=str, metavar="TAG")
        parser.add_argument("--attached", action="store_true")
        parser.add_argument("--build-before-up", action="store_true")
        parser.add_argument("--force-recreate", action="store_true")
        parser.add_argument("--down", action="store_true")
        parser.add_argument("--clear-volumes", "-cv", action="store_true")
        parser.add_argument("--services", nargs='+', metavar='SERVICE')
        parser.add_argument("--with-ollama", action="store_true")
        parser.add_argument("--ollama-gpu", action="store_true")
        parser.add_argument("--nuke", action="store_true")
        parser.add_argument("--debug-cache", action="store_true")
        parser.add_argument("--verbose", "-v", action="store_true")
        args = parser.parse_args()
        if (args.down or args.clear_volumes) and args.mode == 'up':
            log.warning("--down/--clear-volumes with mode=up runs first only if mode=both/down_only.")
        if args.build_before_up and args.mode not in ['up', 'both']:
            log.warning("--build-before-up ignored.")
        if args.tag and args.mode not in ['build', 'both']:
            log.warning("--tag ignored.")
        return args


# --- Main Entry Point ---
if __name__ == "__main__":
    try:
        arguments = DockerManager.parse_args()
        manager = DockerManager(arguments)
        manager.run()
    except KeyboardInterrupt:
        log.info("\n🛑 Cancelled.")
        sys.exit(130)
    except subprocess.CalledProcessError as e:
        log.critical("❌ Command failed.")
        sys.exit(e.returncode or 1)
    except Exception as e:
        log.critical("❌ Error: %s", e, exc_info=(log.level == logging.DEBUG))
        sys.exit(1)
