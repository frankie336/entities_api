#!/usr/bin/env python3
import secrets
import uuid
from pathlib import Path


def generate_dev_docker_compose():
    # Get project root (assume script is in /scripts)
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    output_path = project_root / "docker-compose.yml"

    # ✅ Skip if docker-compose.yml already exists
    if output_path.exists():
        print(f"⚠️  {output_path.name} already exists. Generation skipped.")
        return

    # 🔐 Generate dynamic secrets
    unique_network_secret = str(uuid.uuid4())
    unique_root_password = secrets.token_urlsafe(32)
    unique_mysql_password = secrets.token_urlsafe(32)
    unique_default_secret = secrets.token_urlsafe(32)

    # 🧱 Compose content
    compose_yaml = f"""version: '3.8'

services:
  db:
    image: mysql:8.0
    container_name: my_mysql_cosmic_catalyst
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: {unique_root_password}
      MYSQL_DATABASE: entities_db
      MYSQL_USER: api_user
      MYSQL_PASSWORD: {unique_mysql_password}
    volumes:
      - mysql_data:/var/lib/mysql
    ports:
      - "3307:3306"
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - my_custom_network

  qdrant:
    image: qdrant/qdrant:latest
    container_name: qdrant_server
    restart: always
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_storage:/qdrant/storage
    environment:
      QDRANT__STORAGE__STORAGE_PATH: "/qdrant/storage"
      QDRANT__SERVICE__GRPC_PORT: "6334"
      QDRANT__LOG_LEVEL: "INFO"
    networks:
      - my_custom_network

  api:
    build:
      context: .
      dockerfile: docker/api/Dockerfile
    container_name: fastapi_cosmic_catalyst
    restart: always
    env_file:
      - .env
    environment:
      - DATABASE_URL=mysql+pymysql://api_user:{unique_mysql_password}@db:3306/entities_db
      - SANDBOX_SERVER_URL=http://sandbox:8000
      - QDRANT_URL=http://qdrant:6333
      - DEFAULT_SECRET_KEY={unique_default_secret}
    ports:
      - "9000:9000"
    depends_on:
      db:
        condition: service_healthy
      sandbox:
        condition: service_started
      qdrant:
        condition: service_started
    command: ["./wait-for-it.sh", "db:3306", "--", "uvicorn", "entities_api.app:app", "--host", "0.0.0.0", "--port", "9000"]
    networks:
      - my_custom_network

  sandbox:
    build:
      context: .
      dockerfile: docker/sandbox/Dockerfile
    container_name: sandbox_api
    restart: always
    cap_add:
      - SYS_ADMIN
    security_opt:
      - seccomp:unconfined
    devices:
      - /dev/fuse
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - /tmp/sandbox_logs:/app/logs
    env_file:
      - .env
    networks:
      - my_custom_network

  samba:
    image: dperson/samba
    container_name: samba_server
    restart: unless-stopped
    environment:
      USERID: 1000
      GROUPID: 1000
      TZ: UTC
      USER: "samba_user;default"
      SHARE: "cosmic_share;/samba/share;yes;no;no;samba_user"
      GLOBAL: "server min protocol = NT1\\nserver max protocol = SMB3"
    ports:
      - "139:139"
      - "1445:445"
    volumes:
      - ${{SHARED_PATH}}:/samba/share
    networks:
      - my_custom_network

volumes:
  mysql_data:
    driver: local
  qdrant_storage:
    driver: local

networks:
  my_custom_network:
    driver: bridge
    driver_opts:
      unique_secret: "{unique_network_secret}"
"""

    # 💾 Write to project root
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(compose_yaml)

    print("\n✅ docker-compose.yml generated at project root with:")
    print(f"  - MYSQL_ROOT_PASSWORD:  {unique_root_password}")
    print(f"  - MYSQL_PASSWORD:       {unique_mysql_password}")
    print(f"  - DEFAULT_SECRET_KEY:   {unique_default_secret}")
    print(f"  - Network Unique ID:    {unique_network_secret}\n")


if __name__ == "__main__":
    generate_dev_docker_compose()
