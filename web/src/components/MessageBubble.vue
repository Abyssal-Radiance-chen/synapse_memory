<template>
  <div :class="['message', message.role]">
    <div :class="['avatar', message.role]">
      {{ message.role === 'user' ? '👤' : '🤖' }}
    </div>
    <div class="message-content">
      <template v-if="isEditing">
        <textarea 
          v-model="editContent" 
          class="edit-textarea" 
          rows="3"
        ></textarea>
        <div class="edit-actions">
          <button class="action-btn save-btn" @click="saveEdit">✓ 保存并重新生成</button>
          <button class="action-btn cancel-btn" @click="cancelEdit">✕ 取消</button>
        </div>
      </template>

      <template v-else>
        <div class="bubble">{{ message.content }}</div>
        <div class="timestamp" v-if="message.timestamp">
          {{ formatTime(message.timestamp) }}
        </div>
        
        <div class="actions-row">
          <button
            v-if="showRegenerate"
            class="regenerate-btn"
            @click="$emit('regenerate')"
          >
            🔄 重新生成
          </button>
          <button
            v-if="showEdit"
            class="edit-btn"
            @click="startEdit"
          >
            ✏️ 编辑
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { ChatMessage } from '@/types'

const props = defineProps<{
  message: ChatMessage
  isLastAssistant?: boolean
  showRegenerate?: boolean
  showEdit?: boolean
  animate?: boolean
}>()

const emit = defineEmits<{
  (e: 'regenerate'): void
  (e: 'edit-and-regenerate', payload: { roundIndex: number, newContent: string }): void
}>()

const isEditing = ref(false)
const editContent = ref('')

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function startEdit() {
  editContent.value = props.message.content
  isEditing.value = true
}

function cancelEdit() {
  isEditing.value = false
}

function saveEdit() {
  if (props.message.roundIndex && editContent.value.trim() !== props.message.content) {
    emit('edit-and-regenerate', {
      roundIndex: props.message.roundIndex,
      newContent: editContent.value.trim()
    })
  }
  isEditing.value = false
}
</script>

<style scoped>
.message {
  display: flex;
  gap: 15px;
  animation: fadeIn 0.5s;
}

.message.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 45px;
  height: 45px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  flex-shrink: 0;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
}

.avatar.user {
  background: linear-gradient(135deg, #a1c4fd 0%, #c2e9fb 100%);
}

.avatar.assistant {
  background: linear-gradient(135deg, #e4e8f0 0%, #d1d8e0 100%);
}

.message-content {
  max-width: 70%;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.bubble {
  padding: 15px 20px;
  border-radius: 20px;
  font-size: 15px;
  line-height: 1.6;
  word-wrap: break-word;
  white-space: pre-wrap;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
}

.message.user .bubble {
  background: linear-gradient(135deg, #3498db 0%, #2980b9 100%);
  color: #fff;
  border-bottom-right-radius: 5px;
}

.message.assistant .bubble {
  background: #f8f9fa;
  color: #333;
  border-bottom-left-radius: 5px;
  border: 1px solid #e1e5eb;
}

.timestamp {
  font-size: 12px;
  color: #999;
  padding: 0 10px;
}

.message.user .timestamp {
  text-align: right;
}

.regenerate-btn {
  background: #f8f9fa;
  border: 1px solid #d1d8e0;
  color: #2c3e50;
  padding: 6px 15px;
  border-radius: 15px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.3s;
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.regenerate-btn:hover {
  background: #e4e8f0;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

.actions-row {
  display: flex;
  gap: 10px;
  align-self: flex-start;
  margin-top: 5px;
}

.message.user .actions-row {
  align-self: flex-end;
}

.edit-textarea {
  width: 100%;
  min-width: 250px;
  padding: 10px;
  border-radius: 10px;
  border: 1px solid #ccc;
  font-family: inherit;
  font-size: 14px;
  resize: vertical;
  outline: none;
}

.edit-textarea:focus {
  border-color: #3498db;
  box-shadow: 0 0 5px rgba(52, 152, 219, 0.5);
}

.edit-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 5px;
}

.action-btn {
  padding: 6px 12px;
  border-radius: 15px;
  border: none;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.save-btn {
  background: linear-gradient(135deg, #3498db 0%, #2980b9 100%);
  color: white;
}

.save-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 3px 10px rgba(52, 152, 219, 0.3);
}

.cancel-btn {
  background: #f0f0f0;
  color: #666;
}

.cancel-btn:hover {
  background: #e0e0e0;
}

.edit-btn {
  background: #f8f9fa;
  border: 1px solid #d1d8e0;
  color: #2980b9;
  padding: 6px 15px;
  border-radius: 15px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.3s;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.edit-btn:hover {
  background: #e4e8f0;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

@media (max-width: 768px) {
  .message-content {
    max-width: 85%;
  }
}
</style>
