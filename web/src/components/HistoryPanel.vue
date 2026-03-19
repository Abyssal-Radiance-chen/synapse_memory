<template>
  <transition name="slide">
    <div v-if="visible" class="history-panel">
      <div class="panel-header">
        <h3>📋 历史记录</h3>
        <button class="close-btn" @click="$emit('toggle')">✕</button>
      </div>

      <div class="panel-tabs">
        <button
          :class="['tab', { active: activeTab === 'summaries' }]"
          @click="switchTab('summaries')"
        >
          📝 摘要
        </button>
        <button
          :class="['tab', { active: activeTab === 'events' }]"
          @click="switchTab('events')"
        >
          💬 对话
        </button>
      </div>

      <div class="panel-content">
        <!-- Loading -->
        <div v-if="loading" class="loading-state">
          <div class="loading-dot"></div>
          <span>加载中...</span>
        </div>

        <!-- Error -->
        <div v-else-if="error" class="error-state">
          <span>⚠️ {{ error }}</span>
          <button class="retry-btn" @click="loadData">重试</button>
        </div>

        <!-- Summaries Tab -->
        <template v-else-if="activeTab === 'summaries'">
          <div v-if="summaries.length === 0" class="empty-panel">
            暂无事件摘要
          </div>
          <div
            v-for="summary in summaries"
            :key="summary.event_id"
            class="summary-card"
            @click="$emit('selectEvent', summary.event_id)"
          >
            <div class="card-header">
              <span class="event-id">{{ summary.event_id }}</span>
              <span class="event-date">{{ summary.event_date || '未知日期' }}</span>
            </div>
            <div class="card-body">
              {{ truncate(summary.summary_text, 120) }}
            </div>
            <div class="card-footer">
              <span v-if="summary.weather">🌤️ {{ summary.weather }}</span>
              <span>💬 {{ summary.round_count }} 轮</span>
            </div>
          </div>
        </template>

        <!-- Events Tab -->
        <template v-else-if="activeTab === 'events'">
          <div v-if="events.length === 0" class="empty-panel">
            暂无对话记录
          </div>
          <div
            v-for="evt in events"
            :key="evt.event_id"
            class="event-card"
            @click="$emit('selectEvent', evt.event_id)"
          >
            <div class="card-header">
              <span class="event-id">{{ evt.event_id }}</span>
              <span class="round-count">{{ evt.round_count }} 轮</span>
            </div>
            <div class="card-body">
              {{ truncate(evt.first_user_message, 80) }}
            </div>
            <div class="card-footer">
              <span>{{ formatDate(evt.last_message_at) }}</span>
            </div>
          </div>
        </template>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useHistory } from '@/composables/useHistory'

const props = defineProps<{
  visible: boolean
}>()

defineEmits<{
  (e: 'toggle'): void
  (e: 'selectEvent', eventId: string): void
}>()

const activeTab = ref<'summaries' | 'events'>('summaries')
const { summaries, events, loading, error, fetchSummaries, fetchEvents } = useHistory()

function switchTab(tab: 'summaries' | 'events') {
  activeTab.value = tab
  loadData()
}

function loadData() {
  if (activeTab.value === 'summaries') {
    fetchSummaries()
  } else {
    fetchEvents()
  }
}

function truncate(text: string, maxLen: number): string {
  return text.length > maxLen ? text.slice(0, maxLen) + '...' : text
}

function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

watch(() => props.visible, (val) => {
  if (val) loadData()
})

onMounted(() => {
  if (props.visible) loadData()
})
</script>

<style scoped>
.history-panel {
  width: 320px;
  height: 100%;
  background: rgba(255, 255, 255, 0.98);
  border-radius: 30px 0 0 30px;
  box-shadow: 5px 0 30px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}

.panel-header {
  background: linear-gradient(135deg, #2c3e50 0%, #3498db 100%);
  padding: 20px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-header h3 {
  color: white;
  font-size: 18px;
  font-weight: 600;
}

.close-btn {
  background: rgba(255, 255, 255, 0.2);
  border: none;
  color: white;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  cursor: pointer;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.35);
}

.panel-tabs {
  display: flex;
  padding: 10px 16px;
  gap: 8px;
  border-bottom: 1px solid #e1e5eb;
}

.tab {
  flex: 1;
  padding: 10px;
  border: none;
  border-radius: 12px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  background: transparent;
  color: #888;
  transition: all 0.3s;
}

.tab.active {
  background: #e4e8f0;
  color: #2c3e50;
}

.tab:hover:not(.active) {
  background: rgba(0, 0, 0, 0.05);
}

.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.summary-card, .event-card {
  background: #fff;
  border: 1px solid #e1e5eb;
  border-radius: 16px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.3s;
}

.summary-card:hover, .event-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.05);
  border-color: #3498db;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.event-id {
  font-size: 12px;
  color: #a1c4fd;
  font-weight: 600;
  background: rgba(161, 196, 253, 0.1);
  padding: 2px 8px;
  border-radius: 8px;
}

.event-date, .round-count {
  font-size: 12px;
  color: #999;
}

.card-body {
  font-size: 13px;
  color: #555;
  line-height: 1.5;
  margin-bottom: 8px;
}

.card-footer {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: #aaa;
}

.empty-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #bbb;
  font-size: 14px;
}

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #999;
  padding: 40px 0;
}

.loading-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #3498db;
  animation: pulse 1.4s infinite;
}

.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: #e88;
  padding: 40px 0;
  font-size: 13px;
}

.retry-btn {
  background: #f8f9fa;
  border: 1px solid #d1d8e0;
  color: #e88;
  padding: 6px 16px;
  border-radius: 12px;
  cursor: pointer;
  font-size: 13px;
}

/* Slide transition */
.slide-enter-active, .slide-leave-active {
  transition: all 0.3s ease;
}

.slide-enter-from, .slide-leave-to {
  transform: translateX(-100%);
  opacity: 0;
}

@media (max-width: 768px) {
  .history-panel {
    position: absolute;
    left: 0;
    top: 0;
    z-index: 100;
    width: 85%;
    border-radius: 0;
  }
}
</style>
