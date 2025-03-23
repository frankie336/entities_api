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
        description="Run Docker Compose with optional build toggle, clear volumes, no-cache, and assistant orchestration"
    )
    parser.add_argument(
        "--mode",
        choices=["up", "build", "both"],
        default="up",
        help="Select mode: 'up' for docker-compose up, 'build' for docker-compose build, 'both' for build then up"
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
    args = parser.parse_args()

    # Determine OS and set shared_path accordingly
    system = platform.system().lower()  # e.g., 'windows', 'linux', 'darwin'
    if system == 'windows':
        shared_path = r"C:\ProgramData\entities\samba_share"
    elif system == 'linux':
        shared_path = "/srv/entities/samba_share"
    elif system == 'darwin':
        shared_path = "/Users/Shared/entities/samba_share"
    else:
        print("Unsupported OS detected. Exiting...")
        sys.exit(1)

    # Set environment variable (if needed by Docker Compose)
    os.environ['SHARED_PATH'] = shared_path

    # Create the directory if it doesn't exist
    if not os.path.exists(shared_path):
        os.makedirs(shared_path, exist_ok=True)
        print(f"Created directory: {shared_path}")
    else:
        print(f"Directory already exists: {shared_path}")

    # Clear volumes if flag is set
    try:
        if args.clear_volumes:
            print("Clearing Docker volumes...")
            subprocess.run(["docker-compose", "down", "-v"], check=True)
    except subprocess.CalledProcessError as e:
        print("Error clearing Docker volumes:", e)
        sys.exit(e.returncode)

    # Build command with no-cache option if specified
    build_command = ["docker-compose", "build", "--no-cache"] if args.no_cache else ["docker-compose", "build"]

    # Execute Docker Compose commands based on the mode.
    # Run containers in detached mode (using "-d") so that we can poll health endpoint.
    try:
        if args.mode == "up":
            print("Running docker-compose up in detached mode")
            subprocess.run(["docker-compose", "up", "-d"], check=True)
        elif args.mode == "build":
            print("Running docker-compose build")
            subprocess.run(build_command, check=True)
        elif args.mode == "both":
            print("Running docker-compose build then up in detached mode")
            subprocess.run(build_command, check=True)
            subprocess.run(["docker-compose", "up", "-d"], check=True)
    except subprocess.CalledProcessError as e:
        print("Error running docker-compose:", e)
        sys.exit(e.returncode)

    # Monitor the health endpoint until the service is ready.
    # Adjust the URL as needed (assuming your API is hosted at localhost:9000)
    health_endpoint = os.getenv("BASE_URL_HEALTH")
    try:
        wait_for_health(health_endpoint, timeout=300, interval=5)
    except Exception as e:
        print("Service did not become healthy:", e)
        sys.exit(1)

    # Run assistant orchestration if flag is provided.
    if args.orchestrate:
        print("Initiating Assistant orchestration.")
        service = AssistantSetupService()
        service.orchestrate_default_assistant()
    else:
        print("Skipping assistant orchestration.")


if __name__ == "__main__":
    main()
