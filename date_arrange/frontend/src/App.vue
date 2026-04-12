<template>
  <div id="app">
    <!-- 顶部导航栏 -->
    <el-header class="app-header">
      <div class="header-content">
        <div class="logo">
          <el-icon class="logo-icon"><Calendar /></el-icon>
          <span class="logo-text">Date Arrange</span>
        </div>
        <div class="nav-menu">
          <router-link to="/" class="nav-item">
            <el-icon><Calendar /></el-icon>
            <span>日程规划</span>
          </router-link>
          <router-link to="/tasks" class="nav-item">
            <el-icon><List /></el-icon>
            <span>任务管理</span>
          </router-link>
        </div>
        <div class="header-actions">
          <el-tag :type="healthStatus ? 'success' : 'danger'" effect="dark" size="small">
            {{ healthStatus ? '服务正常' : '服务异常' }}
          </el-tag>
          <el-button type="primary" size="small" @click="refreshHealth">
            <el-icon><Refresh /></el-icon>
            刷新状态
          </el-button>
        </div>
      </div>
    </el-header>

    <!-- 主要内容区域 -->
    <el-main class="app-main">
      <router-view />
    </el-main>

    <!-- 全局加载状态 -->
    <el-dialog
      v-model="globalLoading"
      title="处理中"
      width="300px"
      :show-close="false"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
    >
      <div style="text-align: center;">
        <el-icon class="is-loading" size="24">
          <Loading />
        </el-icon>
        <p style="margin-top: 10px;">正在处理您的请求...</p>
      </div>
    </el-dialog>

    <!-- 全局错误提示 -->
    <el-dialog
      v-model="showError"
      title="错误提示"
      width="400px"
    >
      <p>{{ errorMessage }}</p>
      <template #footer>
        <el-button @click="showError = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { scheduleApi } from './api/schedule'

// 响应式数据
const healthStatus = ref(false)
const globalLoading = ref(false)
const showError = ref(false)
const errorMessage = ref('')

// 生命周期
onMounted(() => {
  checkHealth()
})

// 方法
const checkHealth = async () => {
  try {
    const result = await scheduleApi.healthCheck()
    healthStatus.value = result.status === 'healthy'
  } catch (error) {
    healthStatus.value = false
    showErrorDialog('无法连接到后端服务，请检查服务是否启动')
  }
}

const refreshHealth = () => {
  checkHealth()
}

const showErrorDialog = (message) => {
  errorMessage.value = message
  showError.value = true
}

// 暴露给子组件的方法
const setGlobalLoading = (loading) => {
  globalLoading.value = loading
}

const setError = (message) => {
  showErrorDialog(message)
}

// 提供全局方法给子组件使用
defineExpose({
  setGlobalLoading,
  setError
})
</script>

<style scoped>
.app-header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  height: 60px;
  display: flex;
  align-items: center;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}

.header-content {
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 20px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 20px;
  font-weight: bold;
}

.logo-icon {
  font-size: 24px;
}

.nav-menu {
  display: flex;
  gap: 30px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 5px;
  color: white;
  text-decoration: none;
  padding: 8px 16px;
  border-radius: 6px;
  transition: background-color 0.3s;
}

.nav-item:hover {
  background-color: rgba(255, 255, 255, 0.1);
}

.nav-item.router-link-active {
  background-color: rgba(255, 255, 255, 0.2);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.app-main {
  min-height: calc(100vh - 60px);
  background-color: #f5f7fa;
  padding: 0;
}
</style>