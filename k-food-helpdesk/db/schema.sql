CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS docs (
  id BIGSERIAL PRIMARY KEY,
  source TEXT,
  content TEXT,
  embedding VECTOR(1536),
  meta JSONB
);

CREATE INDEX IF NOT EXISTS docs_embedding_idx
  ON docs USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);