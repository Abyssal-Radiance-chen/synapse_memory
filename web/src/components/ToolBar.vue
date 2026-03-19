<template>
  <div class="toolbar">
    <div class="toggle-group">
      <label class="toggle-label">
        <span>⏰ 时间信息</span>
        <label class="toggle-switch">
          <input type="checkbox" v-model="timeEnabled" />
          <span class="slider"></span>
        </label>
      </label>
    </div>
    <div class="toolbar-actions">
      <button class="btn-clear" @click="$emit('resetTopic')">🔄 重新开始话题</button>
      <button class="btn-clear" @click="$emit('clearHistory')">🗑️ 清空记录</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineEmits<{
  (e: 'resetTopic'): void
  (e: 'clearHistory'): void
}>()

const timeEnabled = ref(true)
</script>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 30px;
  background: #f8f9fa;
  border-bottom: 1px solid #e1e5eb;
}

.toggle-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toggle-label {
  font-size: 14px;
  color: #666;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.toggle-switch {
  position: relative;
  width: 50px;
  height: 26px;
  display: inline-block;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, #d1d8e0 0%, #e4e8f0 100%);
  transition: 0.4s;
  border-radius: 34px;
}

.slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 4px;
  bottom: 4px;
  background-color: white;
  transition: 0.4s;
  border-radius: 50%;
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.2);
}

.toggle-switch input:checked + .slider {
  background: linear-gradient(135deg, #3498db 0%, #2980b9 100%);
}

.toggle-switch input:checked + .slider:before {
  transform: translateX(24px);
}

.toolbar-actions {
  display: flex;
  gap: 10px;
}

.btn-clear {
  background: #f8f9fa;
  border: 1px solid #d1d8e0;
  color: #2c3e50;
  padding: 8px 20px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
  font-weight: 500;
}

.btn-clear:hover {
  background: #e4e8f0;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

@media (max-width: 768px) {
  .toolbar {
    flex-direction: column;
    gap: 10px;
    align-items: flex-start;
  }
}
</style>
