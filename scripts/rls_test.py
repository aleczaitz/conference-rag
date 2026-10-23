"""Step 03 RLS demo: query both tables using only the public (anon/publishable) key."""
from supabase import create_client
import json

with open('config.public.json') as f:
    public = json.load(f)

# Connect with the PUBLIC key (not the secret/service key!)
client = create_client(public['SUPABASE_URL'], public['SUPABASE_ANON_KEY'])

# page_views has a public SELECT policy
result = client.table('page_views').select('*').limit(5).execute()
print(f"page_views: {len(result.data)} rows")

# sentence_embeddings only has a SELECT policy for authenticated users
result = client.table('sentence_embeddings').select('*').limit(5).execute()
print(f"sentence_embeddings: {len(result.data)} rows")
