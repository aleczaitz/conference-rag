import { withSupabase } from 'npm:@supabase/server@^1'

// Caps on client-supplied input. Any signed-in user can call this, so without
// them one request could send a huge prompt and run up the OpenAI bill.
const MAX_TALKS = 3
const MAX_CHARS_PER_TALK = 40_000
const MAX_MESSAGES = 10
const MAX_CHARS_PER_MESSAGE = 2_000

function systemPrompt(speaker: string, talks: string) {
  return `You are ${speaker}, talking one-on-one with someone after General Conference.
Speak in first person, in your own voice. Your talks below are the best record of how you sound: copy their sentence rhythm, imagery, turns of phrase, and the way you address your listeners. Avoid generic phrasing any speaker could have said.
Where it fits, weave in a short direct quote from your talks, since your own words carry your voice best.
Stay grounded in these talks. When you draw on one, mention it naturally, for example: In my talk "Title," I said...
If your talks don't cover something, say you haven't spoken about it in these talks. Don't invent new teachings, personal stories, or details about your life.
Keep replies conversational, a few short paragraphs at most. Plain text, no markdown.

Your talks:

${talks}`
}

export default {
  fetch: withSupabase({ auth: 'user' }, async (req) => {
    const { speaker, messages, context_talks } = await req.json()
    if (typeof speaker !== 'string' || !speaker.trim() || speaker.length > 100 ||
        !Array.isArray(messages) || !Array.isArray(context_talks)) {
      return Response.json({ error: 'speaker, messages, and context_talks are required' }, { status: 400 })
    }

    // Only pass through user/assistant turns. A client-sent "system" message
    // could otherwise override the persona rules above.
    const history = messages
      .filter((m) => (m?.role === 'user' || m?.role === 'assistant') && typeof m.content === 'string')
      .slice(-MAX_MESSAGES)
      .map((m) => ({ role: m.role, content: m.content.slice(0, MAX_CHARS_PER_MESSAGE) }))
    if (history.at(-1)?.role !== 'user') {
      return Response.json({ error: 'The last message must be from the user' }, { status: 400 })
    }
    if (context_talks.length === 0) {
      return Response.json({ answer: "I couldn't find any of my talks to draw on for that." })
    }

    const talks = context_talks
      .slice(0, MAX_TALKS)
      .map((t) => `"${t.title}"\n${String(t.text).slice(0, MAX_CHARS_PER_TALK)}`)
      .join('\n\n---\n\n')

    const res = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${Deno.env.get('OPENAI_API_KEY')}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: 'gpt-4o',
        // Higher than generate-answer's 0.3 so replies sound like a person, not a summary
        temperature: 0.7,
        max_tokens: 600,
        messages: [{ role: 'system', content: systemPrompt(speaker, talks) }, ...history],
      }),
    })
    if (!res.ok) {
      // Log details server-side only; OpenAI error bodies can include key fragments
      console.error('OpenAI error', res.status, await res.text())
      return Response.json({ error: 'Reply generation failed' }, { status: 502 })
    }

    const data = await res.json()
    return Response.json({ answer: data.choices[0].message.content })
  }),
}
