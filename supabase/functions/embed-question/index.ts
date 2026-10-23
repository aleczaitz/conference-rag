import { withSupabase } from 'npm:@supabase/server@^1'

// auth: 'user' rejects any request without a valid signed-in user JWT (401)
// before this handler runs. withSupabase also answers CORS preflights.
export default {
  fetch: withSupabase({ auth: 'user' }, async (req) => {
    const { question } = await req.json()
    if (typeof question !== 'string' || !question.trim()) {
      return Response.json({ error: 'question is required' }, { status: 400 })
    }

    const res = await fetch('https://api.openai.com/v1/embeddings', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${Deno.env.get('OPENAI_API_KEY')}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ model: 'text-embedding-3-small', input: question }),
    })
    if (!res.ok) {
      // Log details server-side only; OpenAI error bodies can include key fragments
      console.error('OpenAI error', res.status, await res.text())
      return Response.json({ error: 'Embedding request failed' }, { status: 502 })
    }

    const { data } = await res.json()
    return Response.json({ embedding: data[0].embedding })
  }),
}
