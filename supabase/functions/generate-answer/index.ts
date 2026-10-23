import { withSupabase } from 'npm:@supabase/server@^1'

const SYSTEM_PROMPT = `You answer questions using only the General Conference talks provided.
For each point you make, cite the talk it came from as (Title, Speaker).
If the talks don't answer the question, say so instead of guessing.
Write plain text with no markdown, because the app displays the answer as-is.`

// Caps on client-supplied context. Any signed-in user can call this, so without
// them one request could send a huge prompt and run up the OpenAI bill.
const MAX_TALKS = 3
const MAX_CHARS_PER_TALK = 40_000

export default {
  fetch: withSupabase({ auth: 'user' }, async (req) => {
    const { question, context_talks } = await req.json()
    if (typeof question !== 'string' || !question.trim() || !Array.isArray(context_talks)) {
      return Response.json({ error: 'question and context_talks are required' }, { status: 400 })
    }
    // The app's readiness check sends an empty list. Skip the paid GPT call.
    if (context_talks.length === 0) {
      return Response.json({ answer: 'No talks were provided to answer from.' })
    }

    const context = context_talks
      .slice(0, MAX_TALKS)
      .map((t, i) => `Talk ${i + 1}: "${t.title}" by ${t.speaker}\n${String(t.text).slice(0, MAX_CHARS_PER_TALK)}`)
      .join('\n\n---\n\n')

    const res = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${Deno.env.get('OPENAI_API_KEY')}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: 'gpt-4o',
        temperature: 0.3,
        max_tokens: 1024,
        messages: [
          { role: 'system', content: SYSTEM_PROMPT },
          { role: 'user', content: `${context}\n\nQuestion: ${question}` },
        ],
      }),
    })
    if (!res.ok) {
      // Log details server-side only; OpenAI error bodies can include key fragments
      console.error('OpenAI error', res.status, await res.text())
      return Response.json({ error: 'Answer generation failed' }, { status: 502 })
    }

    const data = await res.json()
    return Response.json({ answer: data.choices[0].message.content })
  }),
}
