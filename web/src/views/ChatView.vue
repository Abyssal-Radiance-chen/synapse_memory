<template>
  <div class="container">
    <!-- Header -->
    <div class="header">
      <div class="header-left">
        <button class="menu-btn" @click="$emit('toggleHistory')" title="历史记录">
          📋
        </button>
      </div>
      <div class="header-center">
        <h1>记忆对话</h1>
        <div class="subtitle">智能对话，记住每一刻</div>
      </div>
      <div class="header-right"></div>
    </div>

    <!-- History view banner -->
    <div v-if="viewingHistoryEvent" class="history-banner">
      <span>📖 正在查看历史对话: {{ viewingHistoryEvent }}</span>
      <button class="banner-close" @click="$emit('closeHistoryView')">✕ 返回</button>
    </div>

    <!-- Toolbar -->
    <ToolBar
      v-if="!viewingHistoryEvent"
      @reset-topic="handleResetTopic"
      @clear-history="handleClearHistory"
    />

    <!-- Chat Area -->
    <div class="chat-area" ref="chatAreaRef">
      <!-- History view mode -->
      <template v-if="viewingHistoryEvent && historyConversation.length > 0">
        <template v-for="(round, index) in historyConversation" :key="'h-' + index">
          <MessageBubble
            :message="{ role: 'user', content: round.user_message, timestamp: round.created_at }"
            :animate="false"
          />
          <MessageBubble
            :message="{ role: 'assistant', content: round.assistant_message, timestamp: round.created_at }"
            :animate="false"
          />
        </template>
      </template>

      <!-- Live chat mode -->
      <template v-else>
        <!-- Empty state -->
        <div v-if="messages.length === 0" class="empty-state">
          <div class="emoji">💬</div>
          <div class="text">开始我们的对话吧</div>
        </div>

        <!-- Messages -->
        <template v-for="(msg, index) in messages" :key="index">
          <MessageBubble
            :message="msg"
            :is-last-assistant="msg.role === 'assistant' && index === lastAssistantIndex"
            :show-regenerate="msg.role === 'assistant' && index === lastAssistantIndex && !isLoading"
            :show-edit="msg.role === 'user' && msg.roundIndex !== undefined && !isLoading"
            @regenerate="handleRegenerate"
            @edit-and-regenerate="handleEditAndRegenerate"
          />
        </template>

        <!-- Typing Indicator -->
        <TypingIndicator v-if="isLoading && messages[messages.length - 1]?.content === ''" />
      </template>
    </div>

    <!-- Input Area -->
    <InputArea
      v-if="!viewingHistoryEvent"
      :is-loading="isLoading"
      @send="handleSend"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import MessageBubble from '../components/MessageBubble.vue'
import ToolBar from '../components/ToolBar.vue'
import InputArea from '../components/InputArea.vue'
import TypingIndicator from '../components/TypingIndicator.vue'
import { useChat } from '@/composables/useChat'
import { useHistory } from '@/composables/useHistory'

const props = defineProps<{
  viewingHistoryEvent: string
}>()

defineEmits<{
  (e: 'toggleHistory'): void
  (e: 'closeHistoryView'): void
}>()

const chatAreaRef = ref<HTMLElement>()

const {
  messages,
  isLoading,
  loadHistory,
  sendMessage,
  regenerateResponse,
  editAndRegenerate,
  clearHistory,
  resetTopic,
} = useChat()

const { selectedConversation: historyConversation, fetchConversationByEvent } = useHistory()

const lastAssistantIndex = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === 'assistant') return i
  }
  return -1
})

function scrollToBottom() {
  nextTick(() => {
    if (chatAreaRef.value) {
      chatAreaRef.value.scrollTop = chatAreaRef.value.scrollHeight
    }
  })
}

// Watch messages for auto-scroll
watch(() => messages.value.length, scrollToBottom)
watch(() => messages.value[messages.value.length - 1]?.content, scrollToBottom)

// Watch history event selection
watch(() => props.viewingHistoryEvent, async (eventId) => {
  if (eventId) {
    await fetchConversationByEvent(eventId)
    scrollToBottom()
  }
})

async function handleSend(text: string) {
  await sendMessage(text)
  scrollToBottom()
}

async function handleRegenerate() {
  await regenerateResponse()
  scrollToBottom()
}

async function handleEditAndRegenerate(payload: { roundIndex: number, newContent: string }) {
  await editAndRegenerate(payload.roundIndex, payload.newContent)
  scrollToBottom()
}

function handleResetTopic() {
  if (confirm('确定要重新开始话题吗？\n⚠️ 前端显示的对话将被清空')) {
    resetTopic()
  }
}

function handleClearHistory() {
  if (confirm('确定要清空所有对话记录吗？\n这将清空前端显示的所有对话，但不影响已归档的记忆。')) {
    clearHistory()
  }
}

onMounted(() => {
  loadHistory()
  scrollToBottom()
})
</script>

<style scoped>
.container {
  width: 100%;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 30px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.header {
  background: linear-gradient(135deg, #2c3e50 0%, #3498db 100%);
  padding: 20px 30px;
  display: flex;
  align-items: center;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
}

.header-left, .header-right {
  width: 50px;
  flex-shrink: 0;
}

.header-center {
  flex: 1;
  text-align: center;
}

.header h1 {
  color: #fff;
  font-size: 26px;
  font-weight: 600;
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  letter-spacing: 2px;
}

.header .subtitle {
  color: rgba(255, 255, 255, 0.9);
  font-size: 13px;
  margin-top: 6px;
  font-weight: 300;
}

.menu-btn {
  background: rgba(255, 255, 255, 0.3);
  border: none;
  border-radius: 12px;
  width: 42px;
  height: 42px;
  font-size: 20px;
  cursor: pointer;
  transition: all 0.3s;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(5px);
}

.menu-btn:hover {
  background: rgba(255, 255, 255, 0.5);
  transform: scale(1.05);
}

.history-banner {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 10px 30px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  animation: slideIn 0.3s ease-out;
}

.banner-close {
  background: rgba(255, 255, 255, 0.2);
  border: none;
  color: white;
  padding: 6px 16px;
  border-radius: 15px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.3s;
}

.banner-close:hover {
  background: rgba(255, 255, 255, 0.35);
}

.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 30px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #999;
}

.empty-state .emoji {
  font-size: 64px;
  margin-bottom: 20px;
}

.empty-state .text {
  font-size: 16px;
  color: #bbb;
}

@media (max-width: 768px) {
  .container {
    border-radius: 0;
  }

  .header h1 {
    font-size: 22px;
  }
}
</style>
