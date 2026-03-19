<template>
  <div class="input-area">
    <div class="input-container">
      <div class="input-wrapper">
        <textarea
          ref="textareaRef"
          v-model="inputText"
          placeholder="输入消息..."
          rows="1"
          @keydown="handleKeyDown"
          @input="adjustHeight"
        ></textarea>
      </div>
      <button
        class="send-btn"
        :disabled="isLoading || !inputText.trim()"
        @click="handleSend"
      >
        {{ isLoading ? '发送中...' : '💌 发送' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const props = defineProps<{
  isLoading: boolean
}>()

const emit = defineEmits<{
  (e: 'send', text: string): void
}>()

const inputText = ref('')
const textareaRef = ref<HTMLTextAreaElement>()

function adjustHeight() {
  const textarea = textareaRef.value
  if (textarea) {
    textarea.style.height = 'auto'
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px'
  }
}

function handleKeyDown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    handleSend()
  }
}

function handleSend() {
  if (props.isLoading || !inputText.value.trim()) return
  emit('send', inputText.value)
  inputText.value = ''
  // Reset textarea height
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
  }
}

onMounted(() => {
  textareaRef.value?.focus()
})
</script>

<style scoped>
.input-area {
  padding: 20px 30px;
  background: rgba(255, 255, 255, 0.8);
  border-top: 1px solid #e1e5eb;
  backdrop-filter: blur(10px);
}

.input-container {
  display: flex;
  gap: 15px;
  align-items: flex-end;
}

.input-wrapper {
  flex: 1;
  position: relative;
}

textarea {
  width: 100%;
  padding: 15px 20px;
  border: 2px solid #e1e5eb;
  border-radius: 25px;
  font-size: 15px;
  resize: none;
  font-family: inherit;
  transition: all 0.3s;
  background: rgba(255, 255, 255, 0.9);
  max-height: 120px;
  outline: none;
}

textarea:focus {
  border-color: #3498db;
  box-shadow: 0 0 20px rgba(52, 152, 219, 0.3);
}

.send-btn {
  background: linear-gradient(135deg, #3498db 0%, #2980b9 100%);
  color: white;
  border: none;
  padding: 15px 30px;
  border-radius: 25px;
  cursor: pointer;
  font-size: 16px;
  font-weight: 600;
  transition: all 0.3s;
  box-shadow: 0 4px 15px rgba(52, 152, 219, 0.3);
  white-space: nowrap;
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(52, 152, 219, 0.4);
}

.send-btn:disabled {
  background: linear-gradient(135deg, #ddd 0%, #ccc 100%);
  cursor: not-allowed;
  box-shadow: none;
}
</style>
