docker compose exec api alembic revision --autogenerate -m "add engineer column to assistants"


docker compose exec api alembic revision --autogenerate -m "add BatfishSnapshot to models"


docker compose exec api alembic revision --autogenerate -m "add ID to BatfishSnapshot to models"

docker compose exec api alembic revision --autogenerate -m "add owner_id to Thread table"


docker compose exec api alembic revision --autogenerate -m "Remove assistant ---> vector_store relationship"


docker compose exec api alembic revision --autogenerate -m "Remove thread ---> vector_store relationship"


docker compose exec api alembic revision --autogenerate -m "Add soft delete to Files"