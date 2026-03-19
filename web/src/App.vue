<template>
  <div class="app-layout">
    <!-- Left: History Panel -->
    <HistoryPanel
      :visible="showHistory"
      @toggle="showHistory = !showHistory"
      @select-event="onSelectEvent"
    />

    <!-- Right: Main Chat Area -->
    <div class="main-area">
      <ChatView
        :viewing-history-event="viewingHistoryEvent"
        @toggle-history="showHistory = !showHistory"
        @close-history-view="viewingHistoryEvent = ''"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ChatView from './views/ChatView.vue'
import HistoryPanel from './components/HistoryPanel.vue'

const showHistory = ref(false)
const viewingHistoryEvent = ref('')

function onSelectEvent(eventId: string) {
  viewingHistoryEvent.value = eventId
}
</script>

<style scoped>
.app-layout {
  width: 100%;
  max-width: 1200px;
  height: 90vh;
  display: flex;
  gap: 0;
  position: relative;
}

.main-area {
  flex: 1;
  min-width: 0;
  display: flex;
}

@media (max-width: 768px) {
  .app-layout {
    height: 100vh;
    max-height: none;
  }
}
</style>
