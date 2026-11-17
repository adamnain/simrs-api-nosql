import os
from pymongo import MongoClient

MONGODB_URL = os.getenv("MONGODB_URL")

client = MongoClient(
    MONGODB_URL,
    serverSelectionTimeoutMS=5000
)

db = client["simrs"]


def check_mongodb():
    client.admin.command("ping")
    return True