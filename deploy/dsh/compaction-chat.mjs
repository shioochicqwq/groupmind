/** The same compaction for a one-on-one chat (the test session in dsh web), where what was said is not in the chat record. */
import { withInstruction } from './compaction-persona.mjs'

const ChatCompaction = withInstruction(new URL('./compaction-chat.md', import.meta.url))

export { ChatCompaction, ChatCompaction as default }
