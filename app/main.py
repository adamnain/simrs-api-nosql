import os
from fastapi import FastAPI, HTTPException

from app.database import db, check_mongodb
from app.cache import get_cache, set_cache

APP_ENV = os.getenv("APP_ENV", "development")

app = FastAPI(
    title="SIMRS API",
    description="Hospital Information System API",
    version="1.0.0"
)


@app.get("/")
def root():
    return {
        "application": "SIMRS API",
        "environment": APP_ENV,
        "status": "running"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/health/db")
def database_health():
    try:
        check_mongodb()
        return {"mongodb": "connected"}

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="MongoDB unavailable"
        )


@app.get("/api/unit-layanan")
def get_unit_layanan():
    cache_key = "simrs:master:unit_layanan"

    cached_data = get_cache(cache_key)

    if cached_data is not None:
        return {
            "source": "redis",
            "data": cached_data
        }

    try:
        documents = list(
            db.unit_layanan.find({}, {"_id": 0})
        )

        set_cache(cache_key, documents, ttl=3600)

        return {
            "source": "mongodb",
            "data": documents
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to retrieve unit layanan"
        )
