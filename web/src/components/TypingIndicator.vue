<template>
  <div class="message assistant">
    <div class="avatar assistant">🤖</div>
    <div class="message-content">
      <div class="bubble typing-indicator">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.message {
  display: flex;
  gap: 15px;
  animation: fadeIn 0.5s;
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
  background: linear-gradient(135deg, #e4e8f0 0%, #d1d8e0 100%);
}

.message-content {
  display: flex;
  flex-direction: column;
}

.bubble {
  padding: 15px 20px;
  border-radius: 20px;
  border-bottom-left-radius: 5px;
  background: #f8f9fa;
  border: 1px solid #e1e5eb;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
}

.typing-indicator {
  display: flex;
  gap: 5px;
}

.typing-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #3498db;
  animation: typing 1.4s infinite;
}

.typing-dot:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.7;
  }
  30% {
    transform: translateY(-10px);
    opacity: 1;
  }
}
</style>
