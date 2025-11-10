# Founder Copilot

An AI-powered assistant for startup founders, built with OpenAI's Assistant API. Get personalized advice on fundraising, B2B strategies, and startup best practices using a knowledge base of curated startup resources.

## Features

- 🤖 **AI Assistant** - Powered by GPT-4 with retrieval-augmented generation (RAG)
- 📚 **Knowledge Base** - Vector store containing startup resources (YC advice, checklists, scenarios)
- 💬 **Modern Chat Interface** - Beautiful, responsive web UI with structured responses
- 🔍 **File Search** - Automatic retrieval of relevant information from knowledge base
- 📝 **Source Citations** - Automatic extraction and display of source files with quotes
- 📊 **Metrics Dashboard** - Track token usage, latency (P95), and request statistics
- 🚦 **Rate Limiting** - Redis-based rate limiting to protect API endpoints
- 🐳 **Docker Support** - Easy deployment with Docker Compose

## OpenAI API Usage

This project uses **OpenAI's Assistants API (Beta)** to create an intelligent assistant with retrieval capabilities. Here's how each API component is used:

### 1. Vector Stores API (Beta)

**Purpose**: Store and manage knowledge base files for retrieval

**Usage**:
- **`vector_stores.create()`** - Creates a new vector store to hold knowledge base files
- **`vector_stores.file_batches.upload_and_poll()`** - Uploads multiple files in a batch and polls for completion
  - Supports `.md`, `.txt`, and `.json` files
  - Automatically chunks and indexes files for semantic search

**Implementation**:
```python
# Create vector store
vs = client.beta.vector_stores.create(name="founder_copilot_knowledge")

# Upload files in batch
batch = client.beta.vector_stores.file_batches.upload_and_poll(
    vector_store_id=vs.id,
    files=[open("data/file1.md", "rb"), open("data/file2.md", "rb")]
)
```

### 2. Assistants API (Beta)

**Purpose**: Create and manage AI assistants with tools and knowledge

**Usage**:
- **`assistants.create()`** - Creates an assistant with:
  - Custom instructions (YC-style startup advisor persona)
  - Model selection (configurable via `OPENAI_MODEL`, defaults to `gpt-4.1`)
  - File search tool for retrieval from vector stores
  - Vector store integration for knowledge base access

**Implementation**:
```python
assistant = client.beta.assistants.create(
    name="FounderCopilot",
    model="gpt-4.1",
    instructions="You are a YC-style startup advisor...",
    tools=[{"type": "file_search"}],
    tool_resources={
        "file_search": {
            "vector_store_ids": [vector_store_id]
        }
    }
)
```

### 3. Threads API (Beta)

**Purpose**: Manage conversation threads for multi-turn dialogues

**Usage**:
- **`threads.create()`** - Creates a new conversation thread
- **`threads.messages.create()`** - Adds messages to a thread (user or assistant)
- **`threads.runs.create()`** - Executes the assistant on a thread
- **`threads.runs.retrieve()`** - Polls run status until completion
- **`threads.messages.list()`** - Retrieves conversation history

**Implementation**:
```python
# Create thread
thread = client.beta.threads.create()

# Add user message
client.beta.threads.messages.create(
    thread_id=thread.id,
    role="user",
    content="How do I raise pre-seed funding?"
)

# Run assistant
run = client.beta.threads.runs.create(
    thread_id=thread.id,
    assistant_id=assistant.id
)

# Poll for completion
while run.status not in ("completed", "failed"):
    run = client.beta.threads.runs.retrieve(
        thread_id=thread.id,
        run_id=run.id
    )
```

### 4. File Search Tool

**Purpose**: Enable the assistant to retrieve relevant information from the vector store

**How it works**:
- When a user asks a question, the assistant automatically uses the `file_search` tool
- The tool searches the vector store for semantically similar content
- Relevant snippets are retrieved and included in the assistant's response
- The assistant cites sources when referencing knowledge base content
- Source citations are automatically extracted from message annotations

**Benefits**:
- Up-to-date information without retraining models
- Ability to add/update knowledge base files without changing the assistant
- Automatic relevance ranking and retrieval
- Citation of sources for transparency
- Structured output with answer, bullets, and source references

## Project Structure

```
founder-copilot/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── openai_client.py     # OpenAI API wrapper
│   ├── storage.py           # Local state management
│   ├── metrics.py           # Metrics tracking
│   └── static/
│       ├── index.html        # Web UI
│       └── metrics.html      # Metrics dashboard
├── data/                     # Knowledge base files
│   ├── yc_do_things_dont_scale.md
│   ├── preseed_checklist.md
│   └── founder_scenario_b2b.md
├── scripts/
│   ├── seed_knowledge.py      # Initialize vector store and assistant
│   └── update_assistant.py    # Update existing assistant instructions
├── .env.example
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## Setup

### Prerequisites

- Python 3.11+
- Docker and Docker Compose (optional)
- OpenAI API key

### 1. Clone and Configure

```bash
cd founder-copilot
cp .env.example .env
```

Edit `.env` and add your OpenAI API key:
```
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4.1  # Optional, defaults to gpt-4.1
COPILOT_NAME=FounderCopilot  # Optional, defaults to FounderCopilot
REDIS_URL=redis://localhost:6379/0  # Optional, defaults to redis://localhost:6379/0
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Seed the Knowledge Base

This creates the vector store, uploads knowledge base files, and creates the assistant:

```bash
python scripts/seed_knowledge.py
```

This will:
- Create a vector store named "founder_copilot_knowledge"
- Upload all `.md`, `.txt`, and `.json` files from the `data/` directory
- Create an assistant with access to the vector store and enforced file_search usage
- Save IDs to `.copilot_state.json`

**Note**: The assistant is configured to always use the file_search tool for every question, ensuring knowledge base retrieval.

**Updating Assistant Instructions**:
If you need to update the assistant's instructions without recreating it:
```bash
python scripts/update_assistant.py
```

### 4. Start Redis (Required for Rate Limiting)

**With Docker Compose** (recommended):
Redis is automatically started - no action needed.

**Local Development**:
```bash
# macOS
brew services start redis

# Linux
sudo systemctl start redis

# Or use Docker
docker run -d -p 6379:6379 redis:7-alpine
```

### 5. Run the Application

**Local Development**:
```bash
python -m uvicorn app.main:app --reload --port 8000
```

**Docker**:
```bash
docker compose up --build
```

The application will be available at `http://localhost:8000`

**Note**: If Redis is not available, the application will fail to start. Make sure Redis is running before starting the application.

## Usage

### Web Interface

1. Open `http://localhost:8000` in your browser
2. Start chatting with the assistant
3. Ask questions about startups, fundraising, B2B strategies, etc.

### API Endpoints

- `GET /` - Web UI
- `GET /health` - Health check (no rate limit)
- `POST /reset` - Create a new conversation thread (10 requests/minute per IP)
- `POST /chat` - Send a message to the assistant (3 requests/minute per IP)
  ```json
  {
    "message": "How do I raise pre-seed funding?"
  }
  ```
  
  **Response** (structured format):
  ```json
  {
    "thread_id": "thread_abc123",
    "answer": "Pre-seed funding typically involves...",
    "bullets": [
      "Point 1: ...",
      "Point 2: ..."
    ],
    "sources": [
      {
        "file_id": "file_xyz789",
        "filename": "preseed_checklist.md",
        "quote": "Relevant quote from the source"
      }
    ],
    "raw_text": "Full response text...",
    "usage": {
      "input_tokens": 150,
      "output_tokens": 200,
      "total_tokens": 350
    }
  }
  ```
  
  **Note**: The response includes structured data with:
  - `answer`: Main response text (citation markers cleaned)
  - `bullets`: Array of bullet points (if provided by assistant)
  - `sources`: Array of source citations with file IDs, filenames, and quotes
  - `raw_text`: Original response text before processing
  - `usage`: Token usage statistics
- `GET /metrics` - Metrics dashboard (web UI, no rate limit)
- `GET /api/metrics` - Metrics data (JSON API, no rate limit)
- `POST /api/metrics/reset` - Reset all metrics (no rate limit)

**Note**: Rate limits are enforced per IP address. When rate limits are exceeded, the API returns a `429 Too Many Requests` status code.

### Adding Knowledge

To add more knowledge to the assistant:

1. Add markdown, text, or JSON files to the `data/` directory
2. Re-run the seed script:
   ```bash
   python scripts/seed_knowledge.py
   ```
   Or in Docker:
   ```bash
   docker compose exec foundercopilot python scripts/seed_knowledge.py
   ```

**Note**: Re-running the seed script creates a new vector store and assistant. If you want to keep the same assistant ID, you can manually add files to the existing vector store using the OpenAI API, or update the assistant instructions using `update_assistant.py`.

## Metrics & Monitoring

The application includes built-in metrics tracking to monitor performance and usage.

### Metrics Dashboard

Access the metrics dashboard at `http://localhost:8000/metrics` to view:

- **Request Statistics**
  - Total requests
  - Success count and error count
  - Success rate percentage

- **Latency Metrics** (in milliseconds)
  - **P95 Latency** - 95th percentile (highlighted)
  - P50 (median) latency
  - P99 latency
  - Average, minimum, and maximum latency
  - Sample count

- **Token Usage**
  - Total input tokens
  - Total output tokens
  - Total tokens consumed
  - Average tokens per request (input, output, total)
  - Number of tracked requests

### Features

- **Real-time Updates** - Dashboard auto-refreshes every 5 seconds
- **Reset Functionality** - Clear all metrics with confirmation
- **JSON API** - Access metrics programmatically via `/api/metrics`
- **Automatic Tracking** - All chat requests are automatically tracked

### API Usage

**Get Metrics (JSON)**:
```bash
curl http://localhost:8000/api/metrics
```

Response:
```json
{
  "request_count": 42,
  "error_count": 1,
  "success_count": 41,
  "latency": {
    "p50": 1250.5,
    "p95": 2850.3,
    "p99": 3200.1,
    "avg": 1450.2,
    "min": 850.0,
    "max": 3500.0,
    "count": 41
  },
  "tokens": {
    "total_input": 12500,
    "total_output": 8500,
    "total": 21000,
    "avg_input": 304.9,
    "avg_output": 207.3,
    "avg_total": 512.2,
    "count": 41
  }
}
```

**Reset Metrics**:
```bash
curl -X POST http://localhost:8000/api/metrics/reset
```

### How Metrics Work

1. **Automatic Tracking**: Every `/chat` request is automatically tracked
2. **Latency Measurement**: Time from request start to response completion
3. **Token Extraction**: Token usage is extracted from OpenAI API responses
4. **In-Memory Storage**: Metrics are stored in memory (resets on server restart)
5. **Efficient Storage**: Uses deque for latency tracking (configurable max samples, default 1000)

## Rate Limiting

The application uses **FastAPI Limiter with Redis** to enforce rate limits on API endpoints. This protects the service from abuse and helps manage costs.

### Rate Limits

- **`/chat` endpoint**: 3 requests per 60 seconds per IP address
- **`/reset` endpoint**: 10 requests per 60 seconds per IP address
- **Other endpoints**: No rate limits applied

### How It Works

1. **Redis-Based**: Rate limiting state is stored in Redis, enabling distributed rate limiting across multiple instances
2. **IP-Based Identification**: Rate limits are enforced per IP address
3. **Proxy Support**: Automatically handles `X-Forwarded-For` and `CF-Connecting-IP` headers for accurate IP detection behind proxies
4. **Automatic Enforcement**: Rate limits are automatically enforced via FastAPI dependencies

### Rate Limit Responses

When a rate limit is exceeded, the API returns:

```json
{
  "detail": "Rate limit exceeded: 3 per 60 seconds"
}
```

With HTTP status code `429 Too Many Requests`.

### Configuration

Rate limiting requires Redis to be running. The application connects to Redis using the `REDIS_URL` environment variable:

- **Default**: `redis://localhost:6379/0`
- **Docker**: Automatically configured via `docker-compose.yml`

### Redis Setup

**With Docker Compose** (recommended):
Redis is automatically started when you run `docker compose up`. No additional configuration needed.

**Local Development**:
```bash
# Install and start Redis
# macOS
brew install redis
brew services start redis

# Linux
sudo apt-get install redis-server
sudo systemctl start redis

# Or use Docker
docker run -d -p 6379:6379 redis:7-alpine
```

### Customizing Rate Limits

To modify rate limits, edit the `RateLimiter` decorators in `app/main.py`:

```python
# Current: 3 requests per 60 seconds
@app.post("/chat", dependencies=[Depends(RateLimiter(times=3, seconds=60))])

# Example: 10 requests per minute
@app.post("/chat", dependencies=[Depends(RateLimiter(times=10, seconds=60))])

# Example: 100 requests per hour
@app.post("/chat", dependencies=[Depends(RateLimiter(times=100, seconds=3600))])
```

## Configuration

### Environment Variables

- `OPENAI_API_KEY` (required) - Your OpenAI API key
- `OPENAI_MODEL` (optional) - Model to use, defaults to `gpt-4.1`
- `COPILOT_NAME` (optional) - Assistant name, defaults to `FounderCopilot`
- `APP_PORT` (optional) - Server port, defaults to `8000`
- `REDIS_URL` (optional) - Redis connection URL, defaults to `redis://localhost:6379/0`

### State Management

The application stores assistant and vector store IDs in a state file:
- **Local development**: `.copilot_state.json` in the project root
- **Docker**: `state/copilot_state.json` (persisted via Docker volume)

This file is:
- Created automatically when you run `seed_knowledge.py`
- Used by the application to connect to the correct assistant
- Should be committed to version control (or ignored if you prefer)
- In Docker, the `state/` directory is mounted as a volume for persistence

## Docker Commands

```bash
# Build and start (includes Redis)
docker compose up --build

# Run seed script in container
docker compose exec foundercopilot python scripts/seed_knowledge.py

# Update assistant instructions (keeps same assistant ID)
docker compose exec foundercopilot python scripts/update_assistant.py

# View logs (all services)
docker compose logs -f

# View logs (specific service)
docker compose logs -f foundercopilot
docker compose logs -f redis

# Stop all services
docker compose down

# Stop and remove volumes
docker compose down -v
```

**Note**: The `docker-compose.yml` includes both the application and Redis services. When you run `docker compose up`, both services start automatically.

## How It Works

1. **Knowledge Base Setup**: Files in `data/` are uploaded to a vector store, where they're chunked and indexed for semantic search.

2. **Assistant Creation**: An assistant is created with:
   - Access to the vector store via file search tool
   - Custom instructions for YC-style startup advice
   - Ability to retrieve and cite relevant information

3. **Conversation Flow**:
   - User sends a message via the web UI or API
   - Message is added to a conversation thread
   - Assistant runs on the thread, automatically using file search for every question
   - Relevant knowledge base snippets are retrieved and included in the response
   - Source citations are extracted from message annotations
   - Citation markers are cleaned from the response text
   - Structured response (answer, bullets, sources) is returned to the user

4. **Retrieval Process**:
   - When the assistant needs information, it uses the file search tool
   - The tool searches the vector store for semantically similar content
   - Top relevant chunks are retrieved and provided as context
   - The assistant synthesizes the information into a helpful response
   - File citations are automatically added as annotations in the message

5. **Source Extraction**:
   - Source citations are extracted from message annotations (primary method)
   - Fallback extraction from run steps if annotations aren't available
   - File IDs are enriched with filenames by querying the OpenAI Files API
   - Citation markers (e.g., `【4:0†filename.md】`) are automatically cleaned from text
   - Sources are displayed in the UI with filenames and quotes

## Requirements

- `openai==1.51.2` - OpenAI Python SDK
- `fastapi==0.115.5` - Web framework
- `uvicorn[standard]==0.32.0` - ASGI server
- `python-dotenv==1.0.1` - Environment variable management
- `redis==5.0.6` - Redis client for rate limiting
- `fastapi-limiter==0.1.6` - Rate limiting for FastAPI
- `httpx==0.27.2` - HTTP client (dependency)
- `jinja2==3.1.4` - Template engine (dependency)

## License

MIT
