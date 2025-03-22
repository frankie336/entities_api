import os
import platform
import subprocess
import sys
import argparse

def main():
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(
        description="Run Docker Compose with optional build toggle"
    )
    parser.add_argument(
        "--mode",
        choices=["up", "build", "both"],
        default="up",
        help="Select mode: 'up' for docker-compose up, 'build' for docker-compose build, 'both' for build then up"
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

    # Execute Docker Compose commands based on the mode
    try:
        if args.mode == "up":
            print("Running docker-compose up")
            subprocess.run(["docker-compose", "up"], check=True)
        elif args.mode == "build":
            print("Running docker-compose build")
            subprocess.run(["docker-compose", "build"], check=True)
        elif args.mode == "both":
            print("Running docker-compose build then up")
            subprocess.run(["docker-compose", "build"], check=True)
            subprocess.run(["docker-compose", "up"], check=True)
    except subprocess.CalledProcessError as e:
        print("Error running docker-compose:", e)
        sys.exit(e.returncode)

if __name__ == "__main__":
    main()
