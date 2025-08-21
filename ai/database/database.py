from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import settings
from sqlalchemy import text

# SQLAlchemy Base class for models
Base = declarative_base()

# Create engine from .env DATABASE_URL
engine = create_engine(settings.DATABASE_URL, echo=True)  # echo=True logs SQL queries

# Create a session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependency for FastAPI routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# testing connection

# if __name__ == "__main__":
#     try:
#         with engine.connect() as conn:
#             result = conn.execute(text("SELECT 1"))
#             print("✅ Database connected! Result:", result.scalar())
#     except Exception as e:
#         print("❌ Database connection failed:", e)