# DegreeBaba Content Publisher

An end-to-end document parser and WP ACF field mapping system. It extracts structured information from Word documents (`.docx`), resolves field mappings using embeddings and AI, validates the payload quality, and exports ready-to-use WordPress ACF payload JSONs.

---

## Architecture Overview

- **Backend:** FastAPI application utilizing SQLAlchemy, PostgreSQL (Neon database integration), OpenAI, and Anthropic APIs. Background bulk processing runs using FastAPI's native `BackgroundTasks` (completely decoupled from Redis/Celery).
- **Frontend:** React SPA built with Vite and vanilla CSS styling.

---

## Getting Started

### 1. Prerequisites
- Python 3.10+
- Node.js 18+
- Active internet connection (for Neon DB and LLM APIs)

---

### 2. Backend Setup & Run

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Create a configuration file `.env` by copying the example template:
   ```bash
   cp .env.example .env
   ```

3. Open `.env` and fill in the required credentials:
   ```env
   OPENAI_API_KEY=your_openai_api_key
   ANTHROPIC_API_KEY=your_anthropic_api_key
   DATABASE_URL=postgresql://neondb_owner:... (your Neon Postgres URI)
   FRONTEND_URL=http://localhost:5173
   ```

4. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

5. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

6. Start the FastAPI development server:
   ```bash
   python3 main.py
   ```
   The API will be available at `http://localhost:8000`.

---

### 3. Frontend Setup & Run

1. Navigate to the frontend directory:
   ```bash
   cd ../frontend
   ```

2. Create a configuration file `.env` by copying the example template:
   ```bash
   cp .env.example .env
   ```

3. Open `.env` and verify the backend API base URL variable:
   ```env
   VITE_API_BASE=http://localhost:8000
   ```

4. Install the required Node packages:
   ```bash
   npm install
   ```

5. Start the frontend Vite development server:
   ```bash
   npm run dev
   ```
   Open your browser and navigate to the printed address (default: `http://localhost:5173`).

---

## APIs & Endpoints Reference

The backend exposes the following endpoints (relative to `http://localhost:8000`):

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/upload` | `POST` | Upload a single `.docx` file and run the full pipeline |
| `/confirm/{upload_id}` | `POST` | Update field mapping overrides and trigger validation recalculation |
| `/download/{upload_id}` | `GET` | Fetch the final WordPress ACF JSON payload |
| `/bulk` | `POST` | Upload a `.zip` containing multiple `.docx` files to process in the background |
| `/bulk/{job_id}/progress` | `GET` | Query progress/results status of a bulk upload job |
| `/history` | `GET` | List metadata of all past uploads (paginated) |
| `/history/{upload_id}` | `DELETE` | Delete an upload record and its associated field mappings |
| `/upload-image` | `POST` | Upload an image associated with a specific upload and slot |
| `/parse` | `POST` | Debug endpoint to return raw document parse output only |
| `/health` | `GET` | Service health status ping |

---

## Development Notes

- **Database:** Uses PostgreSQL (integrated with Neon Serverless Postgres). Tables are automatically created/synced at backend startup via SQLAlchemy.
- **Background Workers:** Bulk zip files are processed sequentially in-process via FastAPI's `BackgroundTasks` helper. No Redis server or Celery worker execution is needed.
