import { ref, type Ref } from 'vue'
import type { ChatMessage, SSEChunk } from '@/types'

const STORAGE_KEY = 'sweet_chat_history'

export function useChat() {
    const messages: Ref<ChatMessage[]> = ref([])
    const isLoading = ref(false)
    const lastUserMessage = ref('')
    const metadata: Ref<SSEChunk | null> = ref(null)

    // ========== localStorage History ==========
    function saveHistory() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(messages.value))
        } catch (e) {
            console.warn('localStorage save failed:', e)
        }
    }

    function loadHistory() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY)
            if (stored) {
                const parsed = JSON.parse(stored) as ChatMessage[]
                messages.value = parsed.slice(-50)
                // Restore last user message for regeneration
                for (let i = parsed.length - 1; i >= 0; i--) {
                    if (parsed[i].role === 'user') {
                        lastUserMessage.value = parsed[i].content
                        break
                    }
                }
            }
        } catch {
            messages.value = []
        }
    }

    function addMessage(msg: ChatMessage) {
        messages.value.push(msg)
        if (messages.value.length > 50) {
            messages.value.splice(0, messages.value.length - 50)
        }
        saveHistory()
    }

    function removeLastAssistant() {
        for (let i = messages.value.length - 1; i >= 0; i--) {
            if (messages.value[i].role === 'assistant') {
                messages.value.splice(i, 1)
                break
            }
        }
        saveHistory()
    }

    // ========== SSE Streaming ==========
    async function streamChat(
        userMessage: string,
        onChunk: (text: string) => void,
        onDone: (fullText: string) => void,
        onError: (err: Error) => void,
        targetRound?: number
    ) {
        try {
            const endpoint = (targetRound !== undefined) ? '/v1/chat/regenerate' : '/v1/chat/completions'
            const bodyPayload: any = {
                messages: [{ role: 'user', content: userMessage }],
            }
            if (targetRound !== undefined) {
                bodyPayload.target_round = targetRound
            } else {
                bodyPayload.model = 'default'
                bodyPayload.stream = true
            }

            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(bodyPayload),
            })

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`)
            }

            const reader = response.body!.getReader()
            const decoder = new TextDecoder()
            let buffer = ''
            let fullText = ''

            while (true) {
                const { done, value } = await reader.read()
                if (done) break

                buffer += decoder.decode(value, { stream: true })
                const lines = buffer.split('\n')
                buffer = lines.pop() || ''

                for (const line of lines) {
                    const trimmed = line.trim()
                    if (!trimmed || !trimmed.startsWith('data: ')) continue

                    const dataStr = trimmed.slice(6)
                    if (dataStr === '[DONE]') continue

                    try {
                        const data: SSEChunk = JSON.parse(dataStr)

                        // Handle metadata chunk
                        if (data.type === 'metadata') {
                            metadata.value = data
                            continue
                        }

                        // Handle error chunk
                        if ((data as any).error) {
                            throw new Error((data as any).error)
                        }

                        // Handle content chunk
                        const content = data.choices?.[0]?.delta?.content
                        if (content) {
                            fullText += content
                            onChunk(fullText)
                        }
                    } catch (e: any) {
                        if (e.message && !e.message.includes("Unexpected token")) {
                            throw e
                        }
                        // ignore parse errors
                    }
                }
            }

            onDone(fullText)
            return fullText
        } catch (err: any) {
            onError(err)
            throw err
        }
    }

    // ========== Send Message ==========
    async function sendMessage(userInput: string): Promise<void> {
        if (isLoading.value || !userInput.trim()) return

        isLoading.value = true
        const userMessage: ChatMessage = {
            role: 'user',
            content: userInput.trim(),
            timestamp: new Date().toISOString(),
        }
        addMessage(userMessage)
        lastUserMessage.value = userInput.trim()

        // Add placeholder assistant message for streaming
        const assistantMessage: ChatMessage = {
            role: 'assistant',
            content: '',
            timestamp: new Date().toISOString(),
        }
        messages.value.push(assistantMessage)

        try {
            await streamChat(
                userInput.trim(),
                (text) => {
                    // Update the last assistant message reactively
                    const lastMsg = messages.value[messages.value.length - 1]
                    if (lastMsg.role === 'assistant') {
                        lastMsg.content = text
                    }
                },
                (fullText) => {
                    const lastMsg = messages.value[messages.value.length - 1]
                    const userMsg = messages.value[messages.value.length - 2]
                    if (lastMsg?.role === 'assistant') {
                        lastMsg.content = fullText
                    }
                    if (metadata.value?.context?.current_topic?.rounds?.length) {
                        const rounds = metadata.value.context.current_topic.rounds
                        const currentRound = rounds[rounds.length - 1]
                        if (currentRound) {
                            if (lastMsg) lastMsg.roundIndex = currentRound
                            if (userMsg) userMsg.roundIndex = currentRound
                        }
                    }
                    saveHistory()
                },
                (err) => {
                    // Remove the empty assistant message on error
                    const lastIdx = messages.value.length - 1
                    if (messages.value[lastIdx]?.role === 'assistant' && !messages.value[lastIdx].content) {
                        messages.value.splice(lastIdx, 1)
                    }
                    console.error('Send failed:', err)
                }
            )
        } finally {
            isLoading.value = false
        }
    }

    // ========== Regenerate ==========
    async function regenerateResponse(): Promise<void> {
        if (isLoading.value || !lastUserMessage.value) return

        isLoading.value = true
        removeLastAssistant()

        let lastRoundIndex: number = -1
        for (let i = messages.value.length - 1; i >= 0; i--) {
            if (messages.value[i].role === 'user') {
                lastRoundIndex = messages.value[i].roundIndex || -1
                break
            }
        }

        const assistantMessage: ChatMessage = {
            role: 'assistant',
            content: '',
            timestamp: new Date().toISOString(),
        }
        messages.value.push(assistantMessage)

        try {
            await streamChat(
                lastUserMessage.value,
                (text) => {
                    const lastMsg = messages.value[messages.value.length - 1]
                    if (lastMsg.role === 'assistant') {
                        lastMsg.content = text
                    }
                },
                (fullText) => {
                    const lastMsg = messages.value[messages.value.length - 1]
                    const userMsg = messages.value[messages.value.length - 2]
                    if (lastMsg?.role === 'assistant') {
                        lastMsg.content = fullText
                    }
                    if (metadata.value?.context?.current_topic?.rounds?.length) {
                        const rounds = metadata.value.context.current_topic.rounds
                        const currentRound = rounds[rounds.length - 1]
                        if (currentRound) {
                            if (lastMsg) lastMsg.roundIndex = currentRound
                            if (userMsg) userMsg.roundIndex = currentRound
                        }
                    }
                    saveHistory()
                },
                (err) => {
                    const lastIdx = messages.value.length - 1
                    if (messages.value[lastIdx]?.role === 'assistant' && !messages.value[lastIdx].content) {
                        messages.value.splice(lastIdx, 1)
                    }
                    console.error('Regenerate failed:', err)
                },
                lastRoundIndex
            )
        } finally {
            isLoading.value = false
        }
    }

    // ========== Edit & Regenerate ==========
    async function editAndRegenerate(targetRound: number, newUserMessage: string): Promise<void> {
        if (isLoading.value || !newUserMessage.trim()) return

        isLoading.value = true

        // Remove all messages starting from the target round
        // We look for the first message that has roundIndex >= targetRound
        let cutIndex = -1
        for (let i = 0; i < messages.value.length; i++) {
            if (messages.value[i].roundIndex !== undefined && messages.value[i].roundIndex! >= targetRound) {
                cutIndex = i
                break
            }
        }

        if (cutIndex !== -1) {
            messages.value.splice(cutIndex)
        } else {
            messages.value.splice(messages.value.length - 2)
        }

        const userMsg: ChatMessage = {
            role: 'user',
            content: newUserMessage.trim(),
            timestamp: new Date().toISOString(),
        }
        messages.value.push(userMsg)
        lastUserMessage.value = newUserMessage.trim()

        const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: '',
            timestamp: new Date().toISOString(),
        }
        messages.value.push(assistantMsg)

        try {
            await streamChat(
                newUserMessage.trim(),
                (text) => {
                    const lastMsg = messages.value[messages.value.length - 1]
                    if (lastMsg.role === 'assistant') {
                        lastMsg.content = text
                    }
                },
                (fullText) => {
                    const lastMsg = messages.value[messages.value.length - 1]
                    const userMsg = messages.value[messages.value.length - 2]
                    if (lastMsg?.role === 'assistant') {
                        lastMsg.content = fullText
                    }
                    if (metadata.value?.context?.current_topic?.rounds?.length) {
                        const rounds = metadata.value.context.current_topic.rounds
                        const currentRound = rounds[rounds.length - 1]
                        if (currentRound) {
                            if (lastMsg) lastMsg.roundIndex = currentRound
                            if (userMsg) userMsg.roundIndex = currentRound
                        }
                    }
                    saveHistory()
                },
                (err) => {
                    const lastIdx = messages.value.length - 1
                    if (messages.value[lastIdx]?.role === 'assistant' && !messages.value[lastIdx].content) {
                        messages.value.splice(lastIdx, 1)
                    }
                    console.error('Edit & Regenerate failed:', err)
                },
                targetRound
            )
        } finally {
            isLoading.value = false
        }
    }

    // ========== Clear / Reset ==========
    function clearHistory() {
        messages.value = []
        lastUserMessage.value = ''
        saveHistory()
    }

    function resetTopic() {
        messages.value = []
        lastUserMessage.value = ''
        saveHistory()
    }

    return {
        messages,
        isLoading,
        lastUserMessage,
        metadata,
        loadHistory,
        sendMessage,
        regenerateResponse,
        editAndRegenerate,
        clearHistory,
        resetTopic,
    }
}
