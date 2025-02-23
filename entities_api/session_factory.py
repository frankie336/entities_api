from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "mysql+pymysql://ollama:3e4Qv5uo2Cg31zC1@localhost:3307/cosmic_catalyst"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
session = SessionLocal()

try:
    with engine.connect() as connection:
        print("Connection to the database was successful!")
except Exception as e:
    print(f"Failed to connect to the database: {e}")