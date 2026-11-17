
#!/bin/bash
set -euo pipefail

COMPOSE_FILE="compose.yaml"
DB_NAME="${DB_NAME:-simrs}"
DATA_DIR="${DATA_DIR:-./seed-data}"

echo "=== SIMRS DEV DATABASE SEEDING ==="

# Pastikan dijalankan dari root project
if [ ! -f "$COMPOSE_FILE" ]; then
    echo "ERROR: $COMPOSE_FILE tidak ditemukan."
    echo "Jalankan script dari root project."
    exit 1
fi

# Start MongoDB DEV
docker compose -f "$COMPOSE_FILE" up -d mongodb

# Ambil container ID
MONGO_ID=$(docker compose -f "$COMPOSE_FILE" ps -q mongodb)

if [ -z "$MONGO_ID" ]; then
    echo "ERROR: Container MongoDB tidak ditemukan."
    exit 1
fi

# Tunggu MongoDB healthy
echo "Waiting for MongoDB..."

for i in $(seq 1 30); do
    STATUS=$(docker inspect \
        --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$MONGO_ID")

    if [ "$STATUS" = "healthy" ]; then
        break
    fi

    if [ "$i" -eq 30 ]; then
        echo "ERROR: MongoDB belum healthy."
        docker compose -f "$COMPOSE_FILE" logs mongodb
        exit 1
    fi

    sleep 2
done

# Ambil credential
MONGO_USER=$(docker compose -f "$COMPOSE_FILE" exec -T mongodb \
    printenv MONGO_INITDB_ROOT_USERNAME)

MONGO_PASSWORD=$(docker compose -f "$COMPOSE_FILE" exec -T mongodb \
    printenv MONGO_INITDB_ROOT_PASSWORD)

# Ambil network aktual dari Compose
NETWORK=$(docker inspect "$MONGO_ID" \
    --format='{{range $name, $config := .NetworkSettings.Networks}}{{$name}}{{end}}')

if [ -z "$NETWORK" ]; then
    echo "ERROR: Docker network tidak ditemukan."
    exit 1
fi

echo "Database : $DB_NAME"
echo "Network  : $NETWORK"
echo "Data dir : $DATA_DIR"

# Import semua JSON
shopt -s nullglob
FILES=("$DATA_DIR"/*.json)

if [ ${#FILES[@]} -eq 0 ]; then
    echo "ERROR: Tidak ada file JSON di $DATA_DIR"
    exit 1
fi

for file in "${FILES[@]}"; do
    collection=$(basename "$file" .json)

    echo "Importing collection: $collection"

    docker run --rm \
        --network "$NETWORK" \
        -v "$(cd "$DATA_DIR" && pwd):/seed:ro" \
        mongo:8.0 \
        mongoimport \
        --host simrs-mongodb-dev \
        --username "$MONGO_USER" \
        --password "$MONGO_PASSWORD" \
        --authenticationDatabase admin \
        --db "$DB_NAME" \
        --collection "$collection" \
        --file "/seed/$(basename "$file")" \
        --jsonArray
done

echo "=== SEEDING COMPLETED ==="
