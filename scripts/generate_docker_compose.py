#!scripts/generate_docker_compose.py
"""
Generate a development‑friendly docker‑compose.yml.

All sensitive values (DB passwords, DEFAULT_SECRET_KEY, etc.) are expressed as
${ENV_VAR} placeholders.  The orchestration script will create real secrets and
write them into .env on first run.
"""
from pathlib import Path
import uuid


# --------------------------------------------------------------------------- #
# main generator
# --------------------------------------------------------------------------- #
def generate_dev_docker_compose() -> None:
    # project root (this file lives in   scripts/   one level below)
    project_root = Path(__file__).resolve().parent.parent
    output_path = project_root / "docker-compose.yml"

    if output_path.exists():
        print(f"⚠️  {output_path.name} already exists – generation skipped.")
        return

    # A non‑secret UUID for the custom bridge network
    unique_network_secret = str(uuid.uuid4())

    compose_yaml = f"""version: '3.8'

services:
  db:
    image: mysql:8.0
    container_name: my_mysql_cosmic_catalyst
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: ${{MYSQL_ROOT_PASSWORD:-default}}
      MYSQL_DATABASE: entities_db
      MYSQL_USER: api_user
      MYSQL_PASSWORD: ${{MYSQL_PASSWORD:-default}}
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

  redis:
    image: redis:7
    container_name: redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
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
      # DATABASE_URL will be generated into .env (escaped password etc.)
      - DATABASE_URL=${{DATABASE_URL}}
      - SANDBOX_SERVER_URL=http://sandbox:8000
      - QDRANT_URL=http://qdrant:6333
      - DEFAULT_SECRET_KEY=${{DEFAULT_SECRET_KEY}}
      - REDIS_URL=redis://redis:6379/0
    ports:
      - "9000:9000"
    depends_on:
      db:
        condition: service_healthy
      sandbox:
        condition: service_started
      qdrant:
        condition: service_started
      redis:
        condition: service_started
    command:
      - ./wait-for-it.sh
      - "db:3306"
      - --
      - uvicorn
      - entities_api.app:app
      - --host
      - "0.0.0.0"
      - --port
      - "9000"
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
      USERID: ${{SAMBA_USERID:-1000}}
      GROUPID: ${{SAMBA_GROUPID:-1000}}
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
  redis_data:
    driver: local

networks:
  my_custom_network:
    driver: bridge
    driver_opts:
      unique_secret: "{unique_network_secret}"
"""

    output_path.write_text(compose_yaml, encoding="utf-8")
    print(f"✅  Development docker-compose.yml written → {output_path}")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    generate_dev_docker_compose()
