# SIMRS API

Backend API untuk Sistem Informasi Manajemen Rumah Sakit (SIMRS) menggunankan NoSQL .

## 1. Instalasi

### Requirements

Pastikan sudah menginstal tools berikut:

- **Docker Desktop**: https://www.docker.com/products/docker-desktop/
- **Visual Studio Code**: https://code.visualstudio.com/

Untuk pengguna Windows, disarankan menggunakan Docker Desktop dengan WSL2.

### Clone Repository

```bash
git clone <repository-url>
```

Masuk ke direktori project:

```bash
cd simrs-api-nosql
```

### Menjalankan Aplikasi

Pastikan Docker Desktop sudah berjalan, kemudian jalankan:

```bash
docker compose up -d --build
```

Periksa status container:

```bash
docker compose ps
```

### Access API

Jika aplikasi berhasil berjalan, akses melalui:

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| Health Check | http://localhost:8000/health |

### Docker Commands

Menjalankan aplikasi:

```bash
docker compose up -d
```

Menghentikan aplikasi:

```bash
docker compose down
```

Melihat status container:

```bash
docker compose ps
```

Melihat log API:

```bash
docker compose logs -f api
```

Restart API:

```bash
docker compose restart api
```

Build ulang aplikasi:

```bash
docker compose up -d --build
```

## 2. Konfigurasi Environment

Salin file `.env.example` menjadi `.env`.

**macOS / Linux:**

```bash
cp .env.example .env
```

**Windows PowerShell:**

```powershell
Copy-Item .env.example .env
```

Sesuaikan konfigurasi di dalam file `.env`:

```env
APP_ENV=development

MONGO_ROOT_USER=mongo_admin
MONGO_ROOT_PASSWORD=your_password

MONGODB_URL=mongodb://mongo_admin:your_password@mongodb:27017/simrs?authSource=admin

UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
```

### Environment Variables

| Variable | Description |
|---|---|
| `APP_ENV` | Application environment |
| `MONGO_ROOT_USER` | MongoDB username |
| `MONGO_ROOT_PASSWORD` | MongoDB password |
| `MONGODB_URL` | MongoDB connection string |
| `UPSTASH_REDIS_REST_URL` | Upstash Redis URL |
| `UPSTASH_REDIS_REST_TOKEN` | Upstash Redis token |


## 3. Git Workflow

Developer diperbolehkan membuat branch masing-masing untuk pengembangan fitur.


### 4. Live Server Deployment

**PENTING:** Setiap perubahan yang berhasil masuk ke branch `main` akan otomatis di-pull dan diterapkan pada live server melalui mekanisme auto-deployment.

Deployment akan memperbarui aplikasi pada direktori:

```text
simrs-api-nosql/
```

Alur deployment:

```text
Developer
    |
    v
Create Feature Branch
    |
    v
Development & Testing
    |
    v
Merge to Main
    |
    v
Git Push (main)
    |
    v
Auto Deployment
    |
    v
Live Server
    |
    v
simrs-api-nosql/
```

### Ketentuan Git

- Developer bebas membuat branch sesuai kebutuhan.
- Contoh branch `feature/nama-fitur` untuk pengembangan fitur.
- Pastikan fitur sudah diuji sebelum digabungkan ke `main`.
- Branch `main` merupakan production branch.
- Setiap perubahan yang masuk ke `main` akan memicu deployment live server.
- Hindari memasukkan kode yang belum siap digunakan ke `main`.
- Koordinasikan perubahan dengan anggota tim untuk menghindari konflik.

## Seeding Data

Jalankan perintah dari root project:

```bash
chmod +x scripts/seed.sh
./scripts/seed.sh
```
