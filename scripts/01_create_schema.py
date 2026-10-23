"""
Step 1: Create Database Schema
================================
Creates the sentence_embeddings table, pgvector extension,
Row Level Security policies, and the match_sentences() function
in your Supabase database.

Usage:
    python scripts/01_create_schema.py

Prerequisites:
    - config.public.json with Supabase URL and anon key
    - config.secret.json with Supabase service key, access token, and project ref
    - Supabase project created
"""

import json
import sys
import time

# Load configuration from both config files
with open('config.public.json', 'r') as f:
    public_config = json.load(f)
with open('config.secret.json', 'r') as f:
    secrets = json.load(f)

SUPABASE_URL = public_config['SUPABASE_URL']
SUPABASE_SERVICE_KEY = secrets['SUPABASE_SERVICE_KEY']
SUPABASE_ACCESS_TOKEN = secrets['SUPABASE_ACCESS_TOKEN']
SUPABASE_PROJECT_REF = secrets['SUPABASE_PROJECT_REF']


def create_schema():
    import requests
    from supabase import create_client

    print("=" * 60)
    print("Creating Database Schema")
    print("=" * 60)

    schema_sql = """
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create sentence_embeddings table
CREATE TABLE IF NOT EXISTS sentence_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    talk_id UUID NOT NULL,
    title TEXT NOT NULL,
    speaker TEXT,
    calling TEXT,
    year INTEGER,
    season TEXT,
    url TEXT,
    sentence_num INTEGER,
    text TEXT NOT NULL,
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index for talk_id grouping
CREATE INDEX IF NOT EXISTS sentence_embeddings_talk_id_idx 
ON sentence_embeddings(talk_id);

-- Enable Row Level Security
ALTER TABLE sentence_embeddings ENABLE ROW LEVEL SECURITY;

-- RLS policy: authenticated users can read
DROP POLICY IF EXISTS "Allow authenticated users to read" ON sentence_embeddings;
CREATE POLICY "Allow authenticated users to read"
ON sentence_embeddings FOR SELECT
TO authenticated
USING (true);

-- ============================================
-- Page Views table (PUBLIC access for RLS demo)
-- ============================================
-- This table intentionally has PUBLIC policies so students can
-- contrast it with sentence_embeddings (auth-only).

CREATE TABLE IF NOT EXISTS page_views (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    visited_at TIMESTAMPTZ DEFAULT NOW(),
    page_url TEXT,
    user_agent TEXT
);

ALTER TABLE page_views ENABLE ROW LEVEL SECURITY;

-- Anyone (including unauthenticated visitors) can insert page views
DROP POLICY IF EXISTS "Allow public inserts" ON page_views;
CREATE POLICY "Allow public inserts"
ON page_views FOR INSERT
TO anon, authenticated
WITH CHECK (true);

-- Anyone can read page views (for the counter)
DROP POLICY IF EXISTS "Allow public reads" ON page_views;
CREATE POLICY "Allow public reads"
ON page_views FOR SELECT
TO anon, authenticated
USING (true);

-- HNSW index for vector search. Without it every search scans all rows and
-- blows past the 8s statement timeout for authenticated users on the free tier.
-- Indexes a half-precision copy (~100 MB instead of ~200 MB) to stay under the
-- 500 MB free-tier limit.
CREATE INDEX IF NOT EXISTS sentence_embeddings_embedding_hnsw_idx
ON sentence_embeddings
USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops);

-- Create function for similarity search
-- DROP first: CREATE OR REPLACE can't change the return columns
DROP FUNCTION IF EXISTS match_sentences(vector, int);
CREATE FUNCTION match_sentences(
  query_embedding vector(1536),
  match_count int DEFAULT 20
)
RETURNS TABLE (
  id uuid,
  talk_id uuid,
  title text,
  speaker text,
  url text,
  text text,
  similarity float
)
LANGUAGE sql STABLE
AS $$
  SELECT
    sentence_embeddings.id,
    sentence_embeddings.talk_id,
    sentence_embeddings.title,
    sentence_embeddings.speaker,
    sentence_embeddings.url,
    sentence_embeddings.text,
    1 - (sentence_embeddings.embedding <=> query_embedding) as similarity
  FROM sentence_embeddings
  -- Must match the index expression exactly, or Postgres falls back to a full scan
  ORDER BY sentence_embeddings.embedding::halfvec(1536) <=> query_embedding::halfvec(1536)
  LIMIT match_count;
$$;

-- ============================================
-- Talk with a speaker (custom feature)
-- ============================================

-- Scraped names vary: 'By Elder Henry B. Eyring', 'By President Henry B. Eyring',
-- 'Presented by ...', some with non-breaking spaces. Reduce them to 'Henry B. Eyring'.
CREATE OR REPLACE FUNCTION clean_speaker(raw text)
RETURNS text
LANGUAGE sql IMMUTABLE
AS $$
  SELECT trim(regexp_replace(replace(raw, chr(160), ' '),
    '^(Presented by|By)\\s+((President|Elder|Sister|Bishop|Brother)\\s+)?', '', 'i'));
$$;

CREATE OR REPLACE FUNCTION list_speakers()
RETURNS TABLE (name text, talk_count int)
LANGUAGE sql STABLE
AS $$
  SELECT clean_speaker(speaker), count(DISTINCT talk_id)::int
  FROM sentence_embeddings
  GROUP BY 1
  ORDER BY 2 DESC, 1;
$$;

CREATE OR REPLACE FUNCTION match_speaker_sentences(
  query_embedding vector(1536),
  speaker_name text,
  match_count int DEFAULT 20
)
RETURNS TABLE (
  id uuid,
  talk_id uuid,
  title text,
  speaker text,
  url text,
  text text,
  similarity float
)
LANGUAGE sql STABLE
AS $$
  SELECT
    sentence_embeddings.id,
    sentence_embeddings.talk_id,
    sentence_embeddings.title,
    sentence_embeddings.speaker,
    sentence_embeddings.url,
    sentence_embeddings.text,
    1 - (sentence_embeddings.embedding <=> query_embedding) as similarity
  FROM sentence_embeddings
  WHERE clean_speaker(sentence_embeddings.speaker) = speaker_name
  -- Exact search on purpose (full precision, so the HNSW index doesn't apply).
  -- One speaker has at most ~1,600 sentences, which scans fast, and HNSW with a
  -- WHERE filter can return fewer matches than asked for.
  ORDER BY sentence_embeddings.embedding <=> query_embedding
  LIMIT match_count;
$$;
"""

    url = f"https://api.supabase.com/v1/projects/{SUPABASE_PROJECT_REF}/database/query"
    headers = {
        "Authorization": f"Bearer {SUPABASE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    resp = requests.post(url, headers=headers, json={"query": schema_sql})
    if resp.status_code in (200, 201):
        print("✅ Database schema created successfully!")
    else:
        print(f"❌ Schema creation failed: {resp.status_code}")
        print(resp.text[:500])
        return False

    # Verify table exists via PostgREST
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    for attempt in range(5):
        try:
            result = client.table('sentence_embeddings').select('id', count='exact').limit(1).execute()
            print(f"✅ Table verified. Current rows: {result.count or 0}")
            return True
        except Exception:
            if attempt < 4:
                print(f"   Waiting for schema cache to refresh... ({attempt + 1}/5)")
                time.sleep(3)
            else:
                print("⚠️  Table created but PostgREST cache hasn't refreshed yet.")
                print("   This is normal — it should be ready by import time.")
                return True


if __name__ == '__main__':
    if not create_schema():
        sys.exit(1)
    print("\n✅ Schema ready! Next: python scripts/02_scrape_data.py")
