<template>
  <div class="schedule-planner">
    <!-- 顶部控制栏 -->
    <div class="control-panel">
      <div class="panel-header">
        <h2>智能日程规划</h2>
        <p>使用自然语言描述您的任务，系统将自动创建优化日程</p>
      </div>
      
      <div class="input-section">
        <el-input
          v-model="userInput"
          type="textarea"
          :rows="3"
          placeholder="请输入您的日程安排需求，例如：需要准备下周的学术报告，还要完成代码review，另外要安排健身时间"
          resize="none"
        />
        <div class="input-actions">
          <el-button 
            type="primary" 
            @click="parseInput" 
            :loading="loading"
            :disabled="!userInput.trim()"
          >
            <el-icon><Search /></el-icon>
            解析任务
          </el-button>
          <el-button @click="clearAll">
            <el-icon><Delete /></el-icon>
            清空
          </el-button>
        </div>
      </div>
    </div>

    <!-- 任务列表 -->
    <div v-if="tasks.length > 0" class="tasks-section">
      <div class="section-header">
        <h3>解析出的任务 ({{ tasks.length }} 个)</h3>
        <el-button type="success" @click="createSchedule" :loading="scheduleLoading">
          <el-icon><Calendar /></el-icon>
          创建日程
        </el-button>
      </div>
      
      <div class="tasks-grid">
        <el-card 
          v-for="task in tasks" 
          :key="task.id"
          class="task-card"
          :class="getPriorityClass(task.priority)"
        >
          <template #header>
            <div class="task-header">
              <span class="task-name">{{ task.name }}</span>
              <el-tag :type="getPriorityTagType(task.priority)" size="small">
                {{ getPriorityText(task.priority) }}
              </el-tag>
            </div>
          </template>
          
          <div class="task-content">
            <p class="task-description">{{ task.description }}</p>
            <div class="task-meta">
              <span class="duration">
                <el-icon><Clock /></el-icon>
                {{ task.duration_minutes }} 分钟
              </span>
              <span v-if="task.deadline" class="deadline">
                <el-icon><Timer /></el-icon>
                {{ formatDate(task.deadline) }}
              </span>
            </div>
          </div>
        </el-card>
      </div>
    </div>

    <!-- 日程展示 -->
    <div v-if="currentSchedule" class="schedule-section">
      <div class="section-header">
        <h3>优化日程安排</h3>
        <div class="schedule-stats">
          <el-tag type="info">日期: {{ currentSchedule.date }}</el-tag>
          <el-tag type="success">总耗时: {{ currentSchedule.total_duration }}分钟</el-tag>
          <el-tag :type="getEfficiencyType(currentSchedule.efficiency_score)">
            效率评分: {{ currentSchedule.efficiency_score }}
          </el-tag>
        </div>
      </div>
      
      <el-card class="schedule-card">
        <div class="time-slots">
          <div 
            v-for="slot in currentSchedule.time_slots" 
            :key="`${slot.start_time}-${slot.end_time}`"
            class="time-slot"
            :class="{ 'assigned': slot.task_id }"
          >
            <div class="slot-time">
              {{ slot.start_time }} - {{ slot.end_time }}
            </div>
            <div v-if="slot.task_id" class="slot-task">
              {{ getTaskName(slot.task_id) }}
            </div>
            <div v-else class="slot-free">
              空闲时间
            </div>
          </div>
        </div>
      </el-card>

      <!-- 改进建议 -->
      <div v-if="suggestions.length > 0" class="suggestions-section">
        <h4>改进建议</h4>
        <ul class="suggestions-list">
          <li v-for="(suggestion, index) in suggestions" :key="index">
            <el-icon><InfoFilled /></el-icon>
            {{ suggestion }}
          </li>
        </ul>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="!tasks.length && !currentSchedule" class="empty-state">
      <el-empty description="请输入您的日程安排需求开始规划">
        <template #image>
          <el-icon size="64"><Calendar /></el-icon>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useScheduleStore } from '../stores/schedule'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'

// Store
const scheduleStore = useScheduleStore()

// 响应式数据
const userInput = ref('')
const loading = ref(false)
const scheduleLoading = ref(false)
const suggestions = ref([])

// 计算属性
const tasks = computed(() => scheduleStore.tasks)
const currentSchedule = computed(() => scheduleStore.currentSchedule)

// 方法
const parseInput = async () => {
  if (!userInput.value.trim()) {
    ElMessage.warning('请输入日程安排需求')
    return
  }

  loading.value = true
  try {
    await scheduleStore.parseUserInput(userInput.value)
    ElMessage.success('任务解析成功')
  } catch (error) {
    ElMessage.error(error.message || '任务解析失败')
  } finally {
    loading.value = false
  }
}

const createSchedule = async () => {
  if (tasks.value.length === 0) {
    ElMessage.warning('请先解析任务')
    return
  }

  scheduleLoading.value = true
  try {
    const result = await scheduleStore.createSchedule(
      dayjs().format('YYYY-MM-DD'),
      { available_time: 480 }
    )
    suggestions.value = result.suggestions || []
    ElMessage.success('日程创建成功')
  } catch (error) {
    ElMessage.error(error.message || '日程创建失败')
  } finally {
    scheduleLoading.value = false
  }
}

const clearAll = () => {
  userInput.value = ''
  scheduleStore.clearTasks()
  scheduleStore.currentSchedule = null
  suggestions.value = []
}

const getPriorityClass = (priority) => {
  const classes = {
    'urgent_important': 'priority-urgent-important',
    'important': 'priority-important',
    'urgent': 'priority-urgent',
    'normal': 'priority-normal',
    'low': 'priority-low'
  }
  return classes[priority] || 'priority-normal'
}

const getPriorityTagType = (priority) => {
  const types = {
    'urgent_important': 'danger',
    'important': 'warning',
    'urgent': 'warning',
    'normal': 'info',
    'low': ''
  }
  return types[priority] || 'info'
}

const getPriorityText = (priority) => {
  const texts = {
    'urgent_important': '紧急重要',
    'important': '重要',
    'urgent': '紧急',
    'normal': '普通',
    'low': '低优先级'
  }
  return texts[priority] || '普通'
}

const formatDate = (dateString) => {
  return dayjs(dateString).format('MM月DD日 HH:mm')
}

const getEfficiencyType = (score) => {
  if (score >= 0.8) return 'success'
  if (score >= 0.6) return 'warning'
  return 'danger'
}

const getTaskName = (taskId) => {
  const task = tasks.value.find(t => t.id === taskId)
  return task ? task.name : '未知任务'
}
</script>

<style scoped>
.schedule-planner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}

.control-panel {
  background: white;
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}

.panel-header {
  margin-bottom: 20px;
}

.panel-header h2 {
  margin: 0 0 8px 0;
  color: #303133;
  font-size: 24px;
}

.panel-header p {
  margin: 0;
  color: #606266;
  font-size: 14px;
}

.input-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.input-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.tasks-section, .schedule-section {
  background: white;
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.section-header h3 {
  margin: 0;
  color: #303133;
  font-size: 18px;
}

.schedule-stats {
  display: flex;
  gap: 8px;
}

.tasks-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.task-card {
  transition: transform 0.2s, box-shadow 0.2s;
}

.task-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px 0 rgba(0, 0, 0, 0.15);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.task-name {
  font-weight: 600;
  color: #303133;
}

.task-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-description {
  margin: 0;
  color: #606266;
  font-size: 14px;
  line-height: 1.4;
}

.task-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #909399;
}

.task-meta span {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 优先级样式 */
.priority-urgent-important {
  border-left: 4px solid #f56c6c;
}

.priority-important {
  border-left: 4px solid #e6a23c;
}

.priority-urgent {
  border-left: 4px solid #e6a23c;
}

.priority-normal {
  border-left: 4px solid #409eff;
}

.priority-low {
  border-left: 4px solid #909399;
}

/* 时间段样式 */
.time-slots {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.time-slot {
  padding: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  text-align: center;
  transition: all 0.3s;
}

.time-slot.assigned {
  background: #f0f9ff;
  border-color: #409eff;
}

.slot-time {
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.slot-task {
  color: #409eff;
  font-weight: 500;
}

.slot-free {
  color: #909399;
  font-style: italic;
}

/* 建议列表 */
.suggestions-section {
  margin-top: 24px;
  padding: 16px;
  background: #f8f9fa;
  border-radius: 6px;
}

.suggestions-section h4 {
  margin: 0 0 12px 0;
  color: #303133;
}

.suggestions-list {
  margin: 0;
  padding-left: 20px;
}

.suggestions-list li {
  margin-bottom: 8px;
  color: #606266;
  display: flex;
  align-items: center;
  gap: 8px;
}

.empty-state {
  background: white;
  border-radius: 12px;
  padding: 60px 20px;
  text-align: center;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}
</style>