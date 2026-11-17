/**
 * Compaction where the summary is written by the bot itself, in character: the model that has been talking in the
 * group (same system prompt, same history) is asked to note down, for itself, what it will want to remember.
 * The built-in engine does the same call with an instruction written for a coding assistant.
 */
import { createRequire } from 'node:module'
import { realpathSync, readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

// These packages live in the dsh install, not next to this file.
const require = createRequire(realpathSync(process.argv[1]))
const load = (name) => import(pathToFileURL(require.resolve(name)).href)
const { BasicCompactionEngine } = await load('@deepseek-ai/dsh-compaction-basic')
const { BlockAssembler } = await load('@deepseek-ai/dsh-llm')

/** The engine with the note asked for by the given instruction file. */
const withInstruction = (file) => {
  const INSTRUCTION = readFileSync(file, 'utf8')
  return class PersonaCompaction extends BasicCompactionEngine {
    async summarize(input, agent, signal) {
      const target = agent.session.requestHeader()?.config
      if (!target) return super.summarize(input, agent, signal)
      const assembler = new BlockAssembler()
      const options = {
        provider: target.provider, model: target.model,
        messages: [...input.messages, { role: 'user', content: [{ type: 'text', text: INSTRUCTION }] }],
        toolHistory: agent.session.toolHistory(),
        ...(input.tools === undefined ? {} : { tools: [...input.tools] }),   // same prefix as a normal turn, so the cache is hit
        maxTokens: this.config.maxTokens, sessionId: agent.session.id, purpose: 'compaction',
        ...(signal === undefined ? {} : { signal }),
      }
      for await (const chunk of this.ctx.llm.stream(options)) assembler.push(chunk)
      const finish = assembler.finish
      if (finish.kind === 'error' || finish.kind === 'aborted') throw new Error(finish.failure.message)
      const rawOutput = assembler.blocks()   // a note cut off at the token cap is still used; failing would leave the context growing
      const summary = rawOutput.filter((b) => b.type === 'text')
      if (!summary.some((b) => b.text.trim())) throw new Error('the model wrote no note')
      return { summary, rawOutput, llmStreamCall: true, provider: options.provider, model: options.model,
               maxTokens: this.config.maxTokens, ...(assembler.usage === undefined ? {} : { usage: assembler.usage }) }
    }
  }
}

const PersonaCompaction = withInstruction(new URL('./compaction-persona.md', import.meta.url))

export { withInstruction, PersonaCompaction, PersonaCompaction as default }
