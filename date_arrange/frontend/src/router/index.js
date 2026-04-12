import { createRouter, createWebHistory } from 'vue-router'
import SchedulePlanner from '../views/SchedulePlanner.vue'
import TaskManager from '../views/TaskManager.vue'

const routes = [
  {
    path: '/',
    name: 'SchedulePlanner',
    component: SchedulePlanner
  },
  {
    path: '/tasks',
    name: 'TaskManager',
    component: TaskManager
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router