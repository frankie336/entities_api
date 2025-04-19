from pathlib import Path
import secrets
import uuid

def generate_orchestration_docker_compose():
    # Resolve the project root
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    output_path = project_root / "docker-compose.yml"

    if output_path.exists():
        print(f"⚠️  {output_path.name} already exists. Skipping generation.")
        return

    # Generate unique secrets
    unique_network_secret = str(uuid.uuid4())
    unique_root_password = uuid.uuid4().hex
    unique_mysql_password = uuid.uuid4().hex
    unique_default_secret = secrets.token_urlsafe(32)

    compose_yaml = f"""version: '3.8'

services:
  db:
    image: mysql:8.0
    container_name: my_mysql_cosmic_catalyst
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: {unique_root_password}
      MYSQL_DATABASE: cosmic_catalyst
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
    image: thanosprime/entities-api-api:latest
    container_name: fastapi_cosmic_catalyst
    restart: always
    env_file:
      - .env
    environment:
      - DATABASE_URL=mysql+pymysql://api_user:{unique_mysql_password}@db:3306/cosmic_catalyst
      - DEFAULT_SECRET_KEY={unique_default_secret}
      - SANDBOX_SERVER_URL=http://sandbox:8000
      - QDRANT_URL=http://qdrant:6333
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
    volumes:
      - ./scripts:/app/scripts
    command: ["./wait-for-it.sh", "db:3306", "--", "uvicorn", "entities_api.app:app", "--host", "0.0.0.0", "--port", "9000"]
    networks:
      - my_custom_network

  sandbox:
    image: thanosprime/entities-api-sandbox:latest
    container_name: sandbox_api
    restart: always
    env_file:
      - .env
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
  redis_data:
    driver: local

networks:
  my_custom_network:
    driver: bridge
    driver_opts:
      unique_secret: "{unique_network_secret}"
"""

    output_path.write_text(compose_yaml, encoding="utf-8")

    print("\n✅ docker-compose.yml generated at project root with:")
    print(f"  - MYSQL_ROOT_PASSWORD:  {unique_root_password}")
    print(f"  - MYSQL_PASSWORD:       {unique_mysql_password}")
    print(f"  - DEFAULT_SECRET_KEY:   {unique_default_secret}")
    print(f"  - Network Unique ID:    {unique_network_secret}\n")

generate_orchestration_docker_compose()
