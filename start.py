#!/usr/bin/env python
import argparse
import os
import platform
import subprocess
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()
# Adjust sys.path so that the 'entities' package is found
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), "src", "api"))

from src.api.entities.services.assistant_set_up_service import AssistantSetupService

def wait_for_health(health_url, timeout=300, interval=5):
    """
    Polls the health endpoint until the service is healthy or the timeout is exceeded.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(health_url)
            if response.status_code == 200:
                health_data = response.json()
                if health_data.get("status") == "healthy":
                    print("Health check passed – service is healthy.")
                    return
        except Exception as e:
            print("Health check not ready yet, retrying... (", e, ")")
        print("Waiting for service health...")
        time.sleep(interval)
    raise Exception("Health check timed out; service did not become healthy in time.")

def main():
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(
        description="Manage Docker Compose with optional build toggle, clear volumes, no-cache, attached mode, refresh package, and assistant orchestration"
    )
    parser.add_argument(
        "--mode",
        choices=["up", "build", "both"],
        default="up",
        help="Select mode: 'up' for docker-compose up, 'build' for docker-compose build, 'both' for build then up"
    )
    parser.add_argument(
        "--down",
        action="store_true",
        help="Stop and remove Docker containers"
    )
    parser.add_argument(
        "--clear-volumes",
        action="store_true",
        help="Clear Docker volumes before starting the containers"
    )
    parser.add_argument(
        "--orchestrate",
        action="store_true",
        help="Run assistant orchestration after services are healthy"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Build Docker images without using the cache"
    )
    parser.add_argument(
        "--attached",
        action="store_true",
        help="Run docker-compose up in attached mode (without -d)"
    )
    parser.add_argument(
        "--refresh-package",
        action="store_true",
        help="Refresh the entities_common package from GitHub without rebuilding containers"
    )
    args = parser.parse_args()

    # Set up environment variables and shared path
    system = platform.system().lower()
    if system == 'windows':
        shared_path = r"C:\ProgramData\entities\samba_share"
    elif system == 'linux':
        shared_path = "/srv/entities/samba_share"
    elif system == 'darwin':
        shared_path = "/Users/Shared/entities/samba_share"
    else:
        print("Unsupported OS detected. Exiting...")
        sys.exit(1)

    os.environ['SHARED_PATH'] = shared_path
    print(f"SHARED_PATH set to: {os.environ.get('SHARED_PATH')}")

    if not os.path.exists(shared_path):
        os.makedirs(shared_path, exist_ok=True)
        print(f"Created directory: {shared_path}")
    else:
        print(f"Directory already exists: {shared_path}")

    env = os.environ.copy()  # Ensure subprocesses inherit our environment

    # If the refresh-package flag is used, update the package and exit.
    if args.refresh_package:
        print("Refreshing entities_common package from GitHub using --no-cache-dir...")
        try:
            subprocess.run(
                [
                    "pip",
                    "install",
                    "--no-cache-dir",
                    "--upgrade",
                    "git+https://github.com/frankie336/entities_common.git#egg=entities_common"
                ],
                check=True,
                env=env
            )
            print("Package refresh complete.")
        except subprocess.CalledProcessError as e:
            print("Error refreshing entities_common package:", e)
            sys.exit(e.returncode)
        sys.exit(0)

    if args.down:
        print("Stopping and removing Docker containers...")
        try:
            subprocess.run(["docker-compose", "down"], check=True, env=env)
        except subprocess.CalledProcessError as e:
            print("Error stopping Docker containers:", e)
            sys.exit(e.returncode)
        return

    try:
        if args.clear_volumes:
            print("Clearing Docker volumes...")
            subprocess.run(["docker-compose", "down", "-v"], check=True, env=env)
    except subprocess.CalledProcessError as e:
        print("Error clearing Docker volumes:", e)
        sys.exit(e.returncode)

    build_command = ["docker-compose", "build", "--no-cache"] if args.no_cache else ["docker-compose", "build"]

    try:
        if args.mode == "up":
            if args.attached:
                print("Running docker-compose up in attached mode")
                subprocess.run(["docker-compose", "up"], check=True, env=env)
            else:
                print("Running docker-compose up in detached mode")
                subprocess.run(["docker-compose", "up", "-d"], check=True, env=env)
        elif args.mode == "build":
            print("Running docker-compose build")
            subprocess.run(build_command, check=True, env=env)
        elif args.mode == "both":
            print("Running docker-compose build then up")
            subprocess.run(build_command, check=True, env=env)
            if args.attached:
                print("Running docker-compose up in attached mode")
                subprocess.run(["docker-compose", "up"], check=True, env=env)
            else:
                print("Running docker-compose up in detached mode")
                subprocess.run(["docker-compose", "up", "-d"], check=True, env=env)
    except subprocess.CalledProcessError as e:
        print("Error running docker-compose:", e)
        sys.exit(e.returncode)

    health_endpoint = os.getenv("BASE_URL_HEALTH")
    try:
        wait_for_health(health_endpoint, timeout=300, interval=5)
    except Exception as e:
        print("Service did not become healthy:", e)
        sys.exit(1)

    if args.orchestrate:
        print("Initiating Assistant orchestration.")
        service = AssistantSetupService()
        service.orchestrate_default_assistant()
    else:
        print("Skipping assistant orchestration.")

if __name__ == "__main__":
    main()
