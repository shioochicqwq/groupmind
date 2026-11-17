/**
 * The host's plugin in the harness: the people table in the system prompt, and, with session handoff, the group's
 * sessions (opened, prompted, copied, cancelled and closed here).
 *
 * People table: a system-prompt section whose text the host sets (`set_people`). The host sets it when the process
 * starts, when a new session starts and after a compaction, the moments the cached prefix is lost anyway; what it learns
 * in between it appends to later turns instead, so the prompt does not change under a warm cache.
 *
 * The SDK protocol (stdio JSON-RPC) has no fork, no cancel and no close, and keeps every session it opened for the
 * life of the process. With handoff a group goes through many sessions, so this plugin owns them instead and the
 * host uses the SDK only for `initialize` and for the notifications, which the SDK server sends for every session
 * in the process (`session.event`, `session.status`), not only its own.
 *
 * It listens on 127.0.0.1:QQBOT_HANDOFF_PORT (loopback TCP, so the same on Windows), one JSON request per line,
 * each carrying "token": QQBOT_HANDOFF_TOKEN:
 *   {"op": "open", "session": S}                      resume S from disk, or start it; -> {"new": bool}
 *   {"op": "prompt", "session": S, "text": T, "blocks": [...]}   queue a user message, as the SDK's session/prompt does;
 *                                                     blocks (optional) are text and {type: image, data, mimeType} parts
 *   {"op": "fork", "source": S, "child": C, "callId": X}
 *       C gets S's events up to just before the model message that made call X, the open step and turn closed by
 *       the harness's own fork closers: same prefix, no tool call without a result. S keeps running; X returns to S.
 *   {"op": "cancel", "session": S}                    stop S's current turn (what dsh's web API does on cancel)
 *   {"op": "close", "session": S}                     dispose S: it leaves memory; its log stays on disk
 *   {"op": "set_people", "text": T}                   the people section of the system prompt, from the next request on
 */
import { createRequire } from 'node:module'
import { realpathSync } from 'node:fs'
import { timingSafeEqual } from 'node:crypto'
import { pathToFileURL } from 'node:url'
import net from 'node:net'

const require = createRequire(realpathSync(process.argv[1]))
const load = (name) => import(pathToFileURL(require.resolve(name)).href)
const { buildForkSeed } = await load('@deepseek-ai/dsh-session/fork')
const { createUserMessage } = await load('@deepseek-ai/dsh-llm')
const { admitEncodedImages } = await load('@deepseek-ai/dsh-attachment')

export const name = 'qq-handoff'
export const inject = ['agents', 'sessions', 'systemPrompt']

/** The last event to copy: the one before the model message that holds the call. */
export function cutBefore(events, callId) {
  const call = events.findLast((e) => e.type === 'tool/call' && e.data?.callId === callId)
  if (call === undefined) throw new Error(`no tool call ${callId} in the source session`)
  const said = events.findLast((e) => e.type === 'assistant/message' && e.seq < call.seq)
  if (said === undefined || said.seq === 0) throw new Error(`no model message before tool call ${callId}`)
  return said.seq - 1
}

export function apply(ctx, config) {
  const port = Number(process.env.QQBOT_HANDOFF_PORT)
  const token = Buffer.from(process.env.QQBOT_HANDOFF_TOKEN ?? '')
  if (!port || token.length < 16) return
  const allowed = (given) => {
    const b = Buffer.from(String(given ?? ''))
    return b.length === token.length && timingSafeEqual(b, token)
  }
  const handles = new Map()   // session id -> agent handle owned here
  let people = ''
  ctx.systemPrompt.section({
    name: 'qq:people',
    order: ctx.systemPrompt.getSectionOrder('DEPLOYMENT_PERSONA_PREFIX') + 0.5,   // right after the persona and the group rules
    text: () => people,
  })
  const agentOptions = { provider: config.provider, model: config.model }
  const live = (session) => {
    const h = handles.get(session)
    if (h === undefined) throw new Error(`session ${session} is not open`)
    return h
  }
  const ops = {
    async open({ session }) {
      if (handles.has(session)) return { new: false }
      try {
        handles.set(session, await ctx.agents.resume({ resumeSessionId: session, agentOptions }))
        return { new: false }
      } catch {
        // nothing stored under this id (a real conflict surfaces on the first prompt)
      }
      handles.set(session, await ctx.agents.create({ sessionId: session, meta: { cwd: process.cwd() }, agentOptions }))
      return { new: true }
    },
    async prompt({ session, text, blocks }) {
      let content = blocks?.length ? blocks : [{ type: 'text', text }]
      const images = content.filter((b) => b.type === 'image' && 'data' in b)
      if (images.length) {   // stored as attachments first, as the SDK server does
        const refs = await admitEncodedImages(ctx.get('attachments'), images.map((b) => ({ data: b.data, mediaType: b.mimeType })))
        let next = 0
        content = content.map((b) => (b.type === 'image' && 'data' in b ? { type: 'image', attachment: refs[next++] } : b))
      }
      const message = createUserMessage({ content, source: { kind: 'user' } })
      live(session).agent.followup(message)
      return { messageId: message.id }
    },
    async fork({ source, child, callId }) {
      if (handles.has(child)) throw new Error(`session ${child} already exists`)
      const src = live(source).agent.session
      const events = src.snapshotEvents()
      const boundary = cutBefore(events, callId)
      handles.set(child, await ctx.agents.create({
        sessionId: child,
        seed: buildForkSeed(events, boundary),
        inheritedEventCount: boundary + 1,
        meta: { ...(src.header.cwd === undefined ? {} : { cwd: src.header.cwd }), parentSession: src.id, isSeeded: true },
        agentOptions,
      }))
      return { boundary, inherited: boundary + 1, sourceEvents: events.length }
    },
    async cancel({ session }) {
      live(session).agent.cancel({ kind: 'user' }, { keepInbox: false })
      return {}
    },
    async close({ session }) {
      const h = handles.get(session)
      if (h === undefined) return { open: false }
      handles.delete(session)
      await h.dispose()
      return { open: true, left: handles.size }
    },
    async set_people({ text }) {
      people = String(text ?? '')
      return { chars: people.length }
    },
    async stats() {
      const m = process.memoryUsage()
      return { open: [...handles.keys()], rssMB: Math.round(m.rss / 1048576), heapMB: Math.round(m.heapUsed / 1048576), sessions: ctx.sessions.list().length }
    },
  }
  const server = net.createServer((sock) => {
    let buf = ''
    sock.on('data', async (chunk) => {
      buf += chunk
      for (let i; (i = buf.indexOf('\n')) >= 0;) {
        const row = buf.slice(0, i)
        buf = buf.slice(i + 1)
        let out
        try {
          const m = JSON.parse(row)
          if (!allowed(m.token)) throw new Error('bad token')
          if (!Object.hasOwn(ops, m.op)) throw new Error(`unknown op ${m.op}`)
          out = { ok: await ops[m.op](m) }
        } catch (e) {
          out = { error: String(e?.message ?? e) }
        }
        sock.write(JSON.stringify(out) + '\n')
      }
    })
    sock.on('error', () => {})
  })
  server.listen(port, '127.0.0.1')
  ctx.effect(() => async () => {
    server.close()
    await Promise.allSettled([...handles.values()].map((h) => h.dispose()))   // final events reach the log before exit
    handles.clear()
  }, 'qq-handoff.listen')
}
