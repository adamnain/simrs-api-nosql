
#!/bin/bash
set -euo pipefail

COMPOSE_FILE="compose.yaml"
DB_NAME="${DB_NAME:-simrs}"

# Pastikan direktori selalu mengacu ke root project
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$PROJECT_DIR/seed-data"

cd "$PROJECT_DIR"

echo "=== SIMRS DEV DATABASE SEEDING ==="

# Start MongoDB
docker compose -f "$COMPOSE_FILE" up -d mongodb

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
        docker compose logs mongodb
        exit 1
    fi

    sleep 2
done

# Ambil credential
MONGO_USER=$(docker compose exec -T mongodb printenv MONGO_INITDB_ROOT_USERNAME | tr -d '\r')
MONGO_PASSWORD=$(docker compose exec -T mongodb printenv MONGO_INITDB_ROOT_PASSWORD | tr -d '\r')

# Ambil network
NETWORK=$(docker inspect "$MONGO_ID" \
    --format='{{range $name, $config := .NetworkSettings.Networks}}{{$name}}{{end}}')

echo "Database : $DB_NAME"
echo "Network  : $NETWORK"
echo "Data dir : $DATA_DIR"

# Periksa file JSON
shopt -s nullglob
FILES=("$DATA_DIR"/*.json)

if [ ${#FILES[@]} -eq 0 ]; then
    echo "ERROR: Tidak ada file JSON di $DATA_DIR"
    exit 1
fi

# Import semua JSON
for file in "${FILES[@]}"; do
    collection=$(basename "$file" .json)

    echo "Importing collection: $collection"

    MSYS_NO_PATHCONV=1 docker run --rm \
        --network "$NETWORK" \
        -v "$DATA_DIR:/seed:ro" \
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
