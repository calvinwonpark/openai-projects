# K-Food Helpdesk

A bilingual (Korean/English) AI-powered helpdesk system for a Korean food-delivery startup. This application uses RAG (Retrieval-Augmented Generation) to provide accurate, context-aware responses about policies, restaurants, delivery areas, allergens, and more.

## Architecture

The project consists of four main components:

- **Database (PostgreSQL + pgvector)**: Stores document embeddings and metadata for semantic search
- **Indexer**: Ingests policy documents and restaurant data, generates embeddings, and stores them in the database
- **Server (FastAPI)**: Provides REST API endpoints for chat and search functionality using OpenAI embeddings and GPT-4
- **Web (Next.js)**: React-based frontend for user interaction

## Prerequisites

- Docker and Docker Compose
- OpenAI API key
- PostgreSQL credentials (or use defaults)

## Setup

1. **Clone the repository** (if applicable) or navigate to the project directory:
   ```bash
   cd k-food-helpdesk
   ```

2. **Create a `.env` file** from the example template:
   ```bash
   cp .env.example .env
   ```
   
   Then edit `.env` and replace `your_openai_api_key_here` with your actual OpenAI API key.
   
   **Note**: The `.env` file is gitignored and will never be committed to the repository. The `.env.example` file serves as a template for required environment variables.

3. **Build and start all services**:
   ```bash
   docker compose up -d --build
   ```

4. **Index the documents**:
   ```bash
   docker compose run --rm indexer
   ```

   This will:
   - Read all markdown files from `data/policies/`
   - Read restaurant data from `data/policies/restaurants.csv`
   - Generate embeddings using OpenAI's `text-embedding-3-small` model
   - Store them in the PostgreSQL database

## Running the Application

Once all services are running:

- **Web Interface**: http://localhost:3001
- **API Server**: http://localhost:8010
- **Database**: localhost:5433 (host port)

### API Endpoints

- `GET /health` - Health check endpoint
- `POST /chat` - Chat with the AI assistant
  ```json
  {
    "message": "What is your refund policy?",
    "session_id": "optional-session-id"
  }
  ```
- `POST /search` - Search for relevant documents
  ```json
  {
    "message": "delivery areas",
    "session_id": "optional-session-id"
  }
  ```

## Project Structure

```
k-food-helpdesk/
├── data/
│   └── policies/
│       ├── account_help.md
│       ├── allergens.md
│       ├── delivery_areas.md
│       ├── hours_and_fees.md
│       ├── refund_policy.md
│       └── restaurants.csv
├── db/
│   └── schema.sql          # Database schema with pgvector setup
├── indexer/
│   ├── Dockerfile
│   ├── ingest.py           # Document ingestion script
│   └── requirements.txt
├── server/
│   ├── Dockerfile
│   ├── main.py             # FastAPI application
│   ├── rag.py              # RAG retrieval logic
│   ├── prompts.py          # System prompts
│   └── requirements.txt
├── web/
│   ├── Dockerfile
│   ├── app/
│   │   └── page.tsx        # Next.js frontend
│   ├── next.config.js
│   └── package.json
├── docker-compose.yml
└── README.md
```

## Features

- **Bilingual Support**: Automatically detects and responds in Korean or English
- **Semantic Search**: Uses vector embeddings for contextually relevant document retrieval
- **Source Citation**: Shows which documents were used to generate each response
- **Restaurant Information**: Includes restaurant data (name, district, categories, hours, delivery areas, allergens)
- **Policy Documents**: Supports multiple policy documents (refunds, delivery, allergens, account help, hours & fees)

## Development

### Rebuilding Services

To rebuild a specific service after code changes:
```bash
docker compose up -d --build <service-name>
```

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f server
```

### Stopping Services

```bash
docker compose down
```

To also remove volumes (database data):
```bash
docker compose down -v
```

## Adding New Documents

1. Add markdown files to `data/policies/` or update `restaurants.csv`
2. Re-run the indexer:
   ```bash
   docker compose run --rm indexer
   ```

## Technology Stack

- **Backend**: FastAPI, Python 3.11
- **Frontend**: Next.js 14, React 18
- **Database**: PostgreSQL with pgvector extension
- **AI/ML**: OpenAI API (embeddings: `text-embedding-3-small`, chat: `gpt-4-turbo`)
- **Containerization**: Docker, Docker Compose

## Environment Variables

The project uses environment variables for configuration. The `.env` file is gitignored to prevent committing sensitive information like API keys.

- **`.env`**: Your actual environment variables (not committed to git)
- **`.env.example`**: Template file showing required variables (committed to git)

When setting up the project:
1. Copy `.env.example` to `.env`
2. Fill in your actual values (especially `OPENAI_API_KEY`)
3. The `.env` file will persist locally and won't be pushed to git

## Notes

- The database uses pgvector for efficient similarity search on embeddings
- Documents are chunked (800 chars for policies, 600 chars for restaurants) for better retrieval
- The system uses cosine distance (`<->`) for vector similarity search
- CORS is configured to allow requests from `localhost:3001` and `localhost:3000`

