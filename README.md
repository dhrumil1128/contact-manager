# Contact Manager Project

This repository contains a full-stack contact management application designed for deployment on Vercel (frontend) and a containerized environment (backend).

## Project Structure
The project requires two main components: the frontend files (static assets) and the backend application files, plus the configuration file.

```
contact-manager/
├── backend/
│   ├── main.py               # FastAPI application, routes, DB setup
│   └── .env                  # Environment variables (HUNTER_IO_API_KEY)
├── frontend/
│   └── index.html            # HTML structure, embedded CSS/JS logic
└── contacts.db               # SQLite database file (created on first run)
```

## Environment Variables
A `.env` file must be created inside the `backend/` directory to store the required secret key for the external API integration.

| Variable Name | Required By | Purpose |
| :--- | :--- | :--- |
| `HUNTER_IO_API_KEY` | Backend (`main.py`) | Your personal API key for accessing the Hunter.io service. |

**Location:** Create a file named `.env` in the `backend/` directory.

**Example `.env` Content:**
```
HUNTER_IO_API_KEY="YOUR_SECRET_HUNTER_KEY_HERE"
```
*(If this key is missing, the backend will automatically fall back to mock data for enrichment.)*

## API Integration Notes
1.  **Frontend to Backend Communication:**
    *   The frontend communicates with the backend via standard `fetch` calls targeting `http://localhost:8000` during local testing.
    *   **Get Contacts:** `GET http://localhost:8000/contacts` returns the initial list.

2.  **Backend to External API (Hunter.io):**
    *   The FastAPI backend uses `httpx` to make asynchronous requests to Hunter.io, passing the API key.
    *   **Crucial Fallback:** If the Hunter.io request fails (network error, invalid key, 4xx/5xx response), the backend catches the exception and returns pre-defined mock data to the frontend.

## How To Run Locally

### Prerequisites
1.  Ensure Python 3.10+ is installed.
2.  Install backend dependencies:
    ```bash
    cd contact-manager/backend
    pip install fastapi uvicorn sqlalchemy pydantic httpx aiosqlite
    ```

### Step 1: Start the Backend Server
Run the FastAPI application. This initializes the database (`contacts.db`) and seeds initial contacts upon startup.
```bash
# From contact-manager/backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Step 2: Run the Frontend
Open the `frontend/index.html` file directly in your web browser. The JavaScript will connect to the running backend server.