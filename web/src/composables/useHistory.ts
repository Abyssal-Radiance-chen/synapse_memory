import { ref, type Ref } from 'vue'
import type { EventSummary, ConversationRound, EventGroup, SystemState, RollingSummary } from '@/types'

export function useHistory() {
    const summaries: Ref<EventSummary[]> = ref([])
    const events: Ref<EventGroup[]> = ref([])
    const selectedConversation: Ref<ConversationRound[]> = ref([])
    const systemState: Ref<SystemState | null> = ref(null)
    const rollingSummaries: Ref<RollingSummary[]> = ref([])
    const loading = ref(false)
    const error = ref('')

    async function fetchSummaries() {
        try {
            loading.value = true
            const res = await fetch('/pg-api/summaries')
            const json = await res.json()
            summaries.value = json.data || []
        } catch (err: any) {
            error.value = err.message
            console.error('Failed to fetch summaries:', err)
        } finally {
            loading.value = false
        }
    }

    async function fetchEvents() {
        try {
            loading.value = true
            const res = await fetch('/pg-api/conversations/events')
            const json = await res.json()
            events.value = json.data || []
        } catch (err: any) {
            error.value = err.message
            console.error('Failed to fetch events:', err)
        } finally {
            loading.value = false
        }
    }

    async function fetchConversationByEvent(eventId: string) {
        try {
            loading.value = true
            const res = await fetch(`/pg-api/conversations?event_id=${encodeURIComponent(eventId)}&limit=100`)
            const json = await res.json()
            // The conversations endpoint returns in DESC order, reverse for chronological
            const data = json.data || []
            selectedConversation.value = data.sort((a: ConversationRound, b: ConversationRound) => a.round_in_event - b.round_in_event)
        } catch (err: any) {
            error.value = err.message
            console.error('Failed to fetch conversation:', err)
        } finally {
            loading.value = false
        }
    }

    async function fetchSystemState() {
        try {
            const res = await fetch('/pg-api/system-state')
            const json = await res.json()
            systemState.value = json.data
        } catch (err: any) {
            console.error('Failed to fetch system state:', err)
        }
    }

    async function fetchRollingSummaries() {
        try {
            const res = await fetch('/pg-api/rolling-summaries')
            const json = await res.json()
            rollingSummaries.value = json.data || []
        } catch (err: any) {
            console.error('Failed to fetch rolling summaries:', err)
        }
    }

    return {
        summaries,
        events,
        selectedConversation,
        systemState,
        rollingSummaries,
        loading,
        error,
        fetchSummaries,
        fetchEvents,
        fetchConversationByEvent,
        fetchSystemState,
        fetchRollingSummaries,
    }
}
