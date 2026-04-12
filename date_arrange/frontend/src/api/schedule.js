import axios from 'axios'

// 创建axios实例
const api = axios.create({
  baseURL: '/api/schedule',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    console.log('API Request:', config.method?.toUpperCase(), config.url)
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    console.error('API Error:', error.response?.data || error.message)
    return Promise.reject(error.response?.data || error)
  }
)

// API方法
export const scheduleApi = {
  // 解析用户输入
  async parseUserInput(userInput, context = {}) {
    const response = await api.post('/parse', {
      user_input: userInput,
      context
    })
    return response
  },

  // 创建日程
  async createSchedule(tasks, date, constraints = {}) {
    const response = await api.post('/create', {
      tasks,
      date,
      constraints
    })
    return response
  },

  // 获取所有任务
  async getTasks() {
    const response = await api.get('/tasks')
    return response
  },

  // 获取所有日程
  async getSchedules() {
    const response = await api.get('/schedules')
    return response
  },

  // 根据日期获取日程
  async getScheduleByDate(date) {
    const response = await api.get(`/schedules/${date}`)
    return response
  },

  // 更新日程
  async updateSchedule(date, updates) {
    const response = await api.put(`/schedules/${date}`, updates)
    return response
  },

  // 删除日程
  async deleteSchedule(date) {
    const response = await api.delete(`/schedules/${date}`)
    return response
  },

  // 健康检查
  async healthCheck() {
    const response = await api.get('/health')
    return response
  }
}

export default scheduleApi