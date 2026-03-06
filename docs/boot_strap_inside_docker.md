### Running inside Docker

If you are deploying via Docker Compose, run the bootstrap against the running API container:

```bash
# 1. Bring the stack up
docker compose up -d

# 2. Run migrations
docker exec -it entities_api_container alembic upgrade head

# 3. Bootstrap the admin
docker exec -it entities_api_container entities-api
```
