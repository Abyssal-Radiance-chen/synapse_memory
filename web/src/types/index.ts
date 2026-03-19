/** Chat message displayed in the UI */
export interface ChatMessage {
    role: 'user' | 'assistant'
    content: string
    timestamp: string
    roundIndex?: number
}

/** Conversation round from PostgreSQL */
export interface ConversationRound {
    id: number
    message_id: string
    event_id: string
    round_in_event: number
    global_round: number
    user_message: string
    assistant_message: string
    created_at: string
}

/** Event summary from PostgreSQL */
export interface EventSummary {
    event_id: string
    summary_text: string
    event_date: string
    weather: string
    start_round: number
    end_round: number
    round_count: number
    created_at: string
}

/** System state from PostgreSQL */
export interface SystemState {
    current_event_id: string
    current_event_round: number
    global_round: number
    event_start_time: string | null
    event_start_weather: string | null
    updated_at: string
}

/** Rolling summary */
export interface RollingSummary {
    event_id: string
    summary_text: string
    event_date: string
    position: number
    created_at: string
}

/** Event group (from conversations/events endpoint) */
export interface EventGroup {
    event_id: string
    round_count: string
    first_message_at: string
    last_message_at: string
    first_user_message: string
}

/** SSE chunk in OpenAI format */
export interface SSEChunk {
    id?: string
    object?: string
    choices?: Array<{
        index: number
        delta: { content?: string }
        finish_reason: string | null
    }>
    // metadata chunk
    type?: string
    usage?: Record<string, any>
    total_duration_ms?: number
    context?: {
        current_topic?: {
            event_id: string
            rounds: number[]
            event_date: string
            weather: string
        }
        rolling_summaries?: Array<{
            event_id: string
            summary: string
            event_date: string
            position: number
        }>
        retrieved_memories?: Array<{
            event_id: string
            event_date: string
            summary_preview: string
        }>
    }
}
