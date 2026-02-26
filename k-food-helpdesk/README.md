# K-Food Helpdesk

A bilingual (Korean/English) AI-powered helpdesk system for a Korean food-delivery startup. This application uses RAG (Retrieval-Augmented Generation) to provide accurate, context-aware responses about policies, restaurants, delivery areas, allergens, and more.

## Architecture

The project consists of four main components:

- **Database (PostgreSQL + pgvector)**: Stores document embeddings and metadata for semantic search
- **Indexer**: Ingests policy documents and restaurant data, generates embeddings, and stores them in the database
- **Server (FastAPI)**: Provides safe-RAG API endpoints with structured outputs, citations, PII redaction, and trace logging
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

- `POST /chat` - Safe-RAG chat endpoint (strict structured response)
  ```json
  {
    "message": "What is your refund policy?",
    "session_id": "optional-session-id"
  }
  ```
  Response shape:
  ```json
  {
    "request_id": "uuid",
    "answer": "string",
    "language": "ko",
    "confidence": 0.93,
    "citations": [
      {
        "doc_id": 12,
        "source": "refund_policy.md",
        "chunk": 0,
        "quote": "We accept refund requests within 24 hours..."
      }
    ],
    "refusal": { "is_refusal": false, "reason": null },
    "pii": { "detected": false, "redacted": false },
    "retrieval_trace": {
      "k": 4,
      "results": [
        { "doc_id": 12, "source": "refund_policy.md", "score": 0.89, "chunk": 0 }
      ]
    },
    "usage": {
      "model": "gpt-4o-mini",
      "input_tokens": 312,
      "output_tokens": 142,
      "latency_ms": 1280
    }
  }
  ```
  Notes:
  - Questions outside available references should return `refusal.is_refusal=true` with reason `INSUFFICIENT_CONTEXT`.
  - Input text is redacted for supported PII patterns (email/phone) before retrieval and generation.
  - Citations are strictly validated server-side: each `citation.quote` must match the cited retrieved chunk content.
  - For non-refusal answers, citation count must cover answer paragraphs (`max(1, min(paragraph_count, 3))`), otherwise the server falls back to refusal.
  - `session_id` is optional; if provided, retrieval cache is session-aware.
  
- `POST /search` - Structured retrieval output (for RAG debugging/testing)
  ```json
  {
    "message": "delivery areas",
    "session_id": "optional-session-id"
  }
  ```
  Response includes `doc_id`, `source`, `content`, `score`, and `chunk`.

- `GET /metrics` - Returns performance metrics
  Returns metrics about API usage and performance:
  ```json
  {
    "total_requests": 42,
    "total_tokens": 12500,
    "total_input_tokens": 8000,
    "total_output_tokens": 4500,
    "tokens_per_request": 297.62,
    "p95_latency_seconds": 2.3456,
    "p95_latency_ms": 2345.6
  }
  ```
  Metrics are tracked automatically for all `/chat` requests and include:
  - Total request count
  - Token usage (input, output, and total)
  - Average tokens per request
  - 95th percentile latency (in seconds and milliseconds)

- `GET /debug/trace/{request_id}` - Returns per-request debug trace
  - Includes retrieval trace and response metadata
  - Stores only redacted user text (not raw user input)

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
│   ├── pii.py              # Lightweight PII detect/redact hooks
│   ├── rag.py              # RAG retrieval logic
│   ├── prompts.py          # System prompts
│   └── requirements.txt
├── evals/
│   ├── README.md
│   ├── run.py              # Offline eval runner for /chat contract
│   └── datasets/
│       └── rag_eval.jsonl  # Eval dataset (positive + refusal cases)
├── .github/
│   └── workflows/
│       └── evals.yml       # CI gate for offline evals
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
- **Strict Structured Output**: `/chat` always returns a typed JSON payload with confidence, citations, refusal, and usage fields
- **Strict Verifiable Citations**: Citations are accepted only when `quote` is present verbatim in the retrieved `(doc_id, source, chunk)` content
- **Grounded Safe-RAG**: The model is instructed to use only retrieved REFERENCE snippets and refuse when context is insufficient
- **Prompt-Injection Resistance**: Retrieved snippets are treated as untrusted REFERENCE data
- **PII Redaction Hook**: Email/phone patterns are redacted before embedding and generation
- **Structured Retrieval Trace**: Retrieval outputs include `doc_id`, `source`, `score`, and `chunk`
- **Session-Aware Caching**: Reuses retrieval results for similar queries (cosine similarity > 0.9) within the same session, reducing API calls and improving response time
- **Per-Request Observability**: JSON request logs and trace lookup endpoint by `request_id`
- **Offline Eval Suite + CI Gate**: Local eval script and GitHub Action workflow for gating changes
- **Expanded Eval Coverage**: `evals/datasets/rag_eval.jsonl` includes 25 checks across positive and refusal scenarios, including Korean/English coverage and source-specific assertions
- **Performance Metrics**: Built-in metrics endpoint tracking request counts, token usage, and p95 latency
- **Restaurant Information**: Includes restaurant data (name, district, categories, hours, delivery areas, allergens)
- **Policy Documents**: Supports multiple policy documents (refunds, delivery, allergens, account help, hours & fees)

## Development

### Rebuilding Services

To rebuild a specific service after code changes:
```bash
docker compose up -d --build <service-name>
```

### Running Offline Evals

```bash
# Start API + DB
docker compose up -d --build db server

# Ensure docs are indexed
docker compose run --rm indexer

# Run eval suite (fails non-zero on contract violations)
API_BASE_URL=http://localhost:8010 python evals/run.py
```

If your API is exposed on a different host/port:
```bash
API_BASE_URL=http://localhost:8000 python evals/run.py
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
- **AI/ML**: OpenAI API (embeddings: `text-embedding-3-small`, chat model: env `MODEL_NAME`, default `gpt-4o-mini`)
- **Containerization**: Docker, Docker Compose

## Environment Variables

The project uses environment variables for configuration. The `.env` file is gitignored to prevent committing sensitive information like API keys.

- **`.env`**: Your actual environment variables (not committed to git)
- **`.env.example`**: Template file showing required variables (committed to git)

When setting up the project:
1. Copy `.env.example` to `.env`
2. Fill in your actual values (especially `OPENAI_API_KEY`)
3. The `.env` file will persist locally and won't be pushed to git

Common server vars:
- `OPENAI_API_KEY` (required)
- `MODEL_NAME` (optional, default: `gpt-4o-mini`)
- `CHAT_TEMPERATURE` (optional, default: `0.1`)

## Notes

- The database uses pgvector for efficient similarity search on embeddings
- Documents are chunked (800 chars for policies, 600 chars for restaurants) for better retrieval
- The system uses cosine distance (`<->`) for vector similarity search
- Retrieval metadata parsing handles both JSON objects and JSON-encoded strings in `meta` to preserve `chunk` reliably
- CORS is configured to allow requests from `localhost:3001` and `localhost:3000`

### Session-Aware Retrieval Caching

The system implements intelligent caching to reduce API calls and improve performance:

- **How it works**: When a user asks a question, the system checks if a similar query (cosine similarity > 0.9) exists in that session's cache
- **Cache hit**: If a similar query is found, cached retrieval results are returned (skips embedding API call and database query)
- **Cache miss**: If no similar query exists, the system performs the retrieval and caches the result for future use
- **Session management**: Each browser session gets its own cache that persists until the tab is closed (managed via `sessionStorage`)
- **Cache limits**: Each session caches up to the last 50 queries to prevent unbounded memory growth
- **Note**: The cache is in-memory and resets when the server restarts. For production deployments, consider using Redis or a database-backed cache for persistence across restarts

### Performance Metrics

The system automatically tracks performance metrics for monitoring and optimization:

- **Request tracking**: Total number of `/chat` requests processed
- **Token usage**: Tracks input tokens, output tokens, and calculates average tokens per request
- **Latency monitoring**: Tracks end-to-end latency for each request and calculates the 95th percentile (p95)
- **Metrics storage**: Metrics are stored in-memory and reset when the server restarts
- **Latency window**: P95 calculation uses the last 1000 requests to provide accurate percentile metrics

Access metrics at `GET /metrics` to monitor API usage, token consumption, and response times. This is useful for:
- Monitoring API costs (token usage)
- Performance optimization (identifying slow requests via p95 latency)
- Capacity planning (understanding request patterns)

### CI Eval Gate

The repository includes `.github/workflows/evals.yml` for `k-food-helpdesk`.
On pull requests and pushes to `main`, it:
- Starts the compose services
- Runs ingestion
- Executes `python evals/run.py`
- Fails the workflow if eval checks fail
