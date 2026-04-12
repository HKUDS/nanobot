import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { scheduleApi } from '../api/schedule'

export const useScheduleStore = defineStore('schedule', () => {
  // 状态
  const tasks = ref([])
  const schedules = ref([])
  const currentSchedule = ref(null)
  const loading = ref(false)
  const error = ref(null)

  // 计算属性
  const totalTasks = computed(() => tasks.value.length)
  const completedTasks = computed(() => tasks.value.filter(t => t.status === 'completed').length)
  const totalDuration = computed(() => tasks.value.reduce((sum, t) => sum + t.duration_minutes, 0))

  // 动作
  const parseUserInput = async (userInput, context = {}) => {
    loading.value = true
    error.value = null
    
    try {
      const result = await scheduleApi.parseUserInput(userInput, context)
      tasks.value = result.tasks
      return result
    } catch (err) {
      error.value = err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  const createSchedule = async (date, constraints = {}) => {
    loading.value = true
    error.value = null
    
    try {
      const result = await scheduleApi.createSchedule(tasks.value, date, constraints)
      currentSchedule.value = result.schedule
      schedules.value.push(result.schedule)
      return result
    } catch (err) {
      error.value = err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  const addTask = (task) => {
    tasks.value.push({
      ...task,
      id: `task_${Date.now()}`,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    })
  }

  const updateTask = (taskId, updates) => {
    const taskIndex = tasks.value.findIndex(t => t.id === taskId)
    if (taskIndex !== -1) {
      tasks.value[taskIndex] = {
        ...tasks.value[taskIndex],
        ...updates,
        updated_at: new Date().toISOString()
      }
    }
  }

  const deleteTask = (taskId) => {
    tasks.value = tasks.value.filter(t => t.id !== taskId)
  }

  const clearTasks = () => {
    tasks.value = []
  }

  const clearError = () => {
    error.value = null
  }

  return {
    // 状态
    tasks,
    schedules,
    currentSchedule,
    loading,
    error,
    
    // 计算属性
    totalTasks,
    completedTasks,
    totalDuration,
    
    // 动作
    parseUserInput,
    createSchedule,
    addTask,
    updateTask,
    deleteTask,
    clearTasks,
    clearError
  }
})