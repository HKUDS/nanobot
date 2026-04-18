<template>
  <div class="h-screen flex flex-col bg-gray-50">
    <!-- 顶部导航栏（现代化） -->
    <div class="bg-white border-b border-gray-200 px-6 py-3 flex justify-between items-center shadow-sm">
      <div class="flex items-center gap-4">
        <div class="w-8 h-8 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-xl flex items-center justify-center">
          <span class="text-white text-lg">🐈</span>
        </div>
        <div>
          <h1 class="text-base font-semibold text-gray-800">Nanobot 容器化智能体管理系统</h1>
          <p class="text-xs text-gray-500">基于 AgentLoop 的对话系统 | 轨迹追踪 · 分支管理</p>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <el-tag :type="healthOk ? 'success' : 'danger'" effect="dark" size="small" round>
          {{ healthOk ? '服务正常' : '服务异常' }}
        </el-tag>
        <el-tag :type="activeCount >= 50 ? 'warning' : 'success'" effect="dark" size="small" round>
          活跃：{{ activeCount }}/50
        </el-tag>
        <el-button type="primary" size="small" @click="handleCreateConv" :disabled="activeCount >= 50" class="!rounded-lg">
          <el-icon class="mr-1"><Plus /></el-icon>
          新建对话
        </el-button>
      </div>
    </div>

    <!-- 主体：三栏布局 -->
    <div class="flex-1 flex overflow-hidden p-4 gap-4">
      <!-- 左侧：对话列表 -->
      <div class="w-96 bg-white rounded-2xl shadow-sm border border-gray-100 flex flex-col overflow-hidden">
        <div class="px-5 py-3 bg-white border-b border-gray-100 flex justify-between items-center">
          <div class="flex items-center gap-2">
            <el-icon class="text-gray-500 text-lg"><Files /></el-icon>
            <span class="font-medium text-gray-700">对话历史</span>
            <el-tag v-if="currentConvId" size="small" type="info" effect="plain" round>
              {{ currentBranchName }}
            </el-tag>
          </div>
          <div class="flex items-center gap-1">
            <el-button v-if="currentConvId" type="success" size="small" @click="handleFork" :loading="loading" circle plain>
              <el-icon><Share /></el-icon>
            </el-button>
            <el-button v-if="currentConvId" type="warning" size="small" @click="showMergeDialog = true" :disabled="convList.length < 2" circle plain>
              <el-icon><Switch /></el-icon>
            </el-button>
            <el-button v-if="currentConvId" type="danger" size="small" @click="handleDelete" :loading="loading" circle plain>
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>

        <div class="flex-1 overflow-y-auto p-3 space-y-2">
          <!-- 悬赏市场 -->
          <BountyMarket v-if="currentConvId" :conversation-id="currentConvId" />

          <!-- 对话列表头部：显示当前对话的Power信息 -->
          <div v-if="currentConvId" class="mb-4 p-4 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-xl border border-blue-100">
            <div class="flex items-center justify-between">
              <div>
                <div class="text-sm font-medium text-blue-800">当前对话状态</div>
                <div class="text-xs text-blue-600 mt-1">ID: {{ currentConvId }}</div>
              </div>
              <div class="text-right">
                <div class="text-lg font-bold text-blue-700">{{ currentPower }}<span class="text-xs font-normal">/100</span></div>
                <div class="text-xs text-blue-600">Power值</div>
              </div>
            </div>
            <div class="mt-2 flex items-center justify-between text-xs">
              <span class="text-blue-600">标注次数: {{ totalAnnotations }}</span>
              <span class="text-blue-600 cursor-pointer hover:text-blue-800" @click="toggleFileStatsPanel">文件监控: {{ fileStatsStatus }}</span>
            </div>
            <!-- Power进度条 -->
            <div class="mt-2">
              <el-progress
                :percentage="Math.round(currentPower)"
                :color="powerColor"
                :show-text="false"
                stroke-width="6"
                class="power-progress"
              />
            </div>
            <!-- 文件监控详情面板 -->
            <div v-if="showFileStatsPanel" class="mt-2 p-2 bg-gray-50 rounded-lg text-xs">
              <div class="font-medium text-gray-600 mb-1">文件详情：</div>
              <div v-for="file in fileStatsDetails" :key="file.name" class="flex items-center gap-2 py-1">
                <el-tag :type="file.exists ? 'success' : 'danger'" size="small" effect="plain">
                  {{ file.status }}
                </el-tag>
                <span class="text-gray-700 font-mono">{{ file.name }}</span>
                <span v-if="file.exists" class="text-gray-400">({{ file.size }}B, {{ file.lines }}行)</span>
              </div>
              <div v-if="fileStatsDetails.length === 0" class="text-gray-400">暂无数据</div>
            </div>
          </div>
          
          <div v-if="!currentConvId" class="p-8 text-center text-gray-400">
            <el-icon size="48" class="mb-2"><Folder /></el-icon>
            <p class="text-sm">请选择或创建对话</p>
          </div>
          
          <div v-else class="space-y-3">
            <div
              v-for="(item, idx) in chatList"
              :key="idx"
              class="bg-gray-50 rounded-xl border border-gray-100 transition-all hover:shadow-sm"
            >
              <div 
                class="px-4 py-2 cursor-pointer flex items-center gap-2"
                @click="toggleExpand(idx)"
              >
                <el-icon :class="['text-gray-400 transition-transform', expandedIdx === idx ? 'rotate-90' : '']">
                  <CaretRight />
                </el-icon>
                <el-icon class="text-blue-500"><ChatDotRound /></el-icon>
                <span class="text-sm font-medium text-gray-700 flex-1">第 {{ idx + 1 }} 轮对话</span>
                <el-tag size="small" effect="plain" round>U</el-tag>
              </div>

              <div v-show="expandedIdx === idx" class="px-4 pb-4 space-y-3 border-t border-gray-100 pt-3">
                <!-- 用户消息 -->
                <div>
                  <div class="text-xs font-semibold text-gray-400 mb-1 flex items-center gap-1">
                    <el-icon><User /></el-icon> 用户消息
                  </div>
                  <div class="bg-white p-3 rounded-xl border border-gray-200 text-sm text-gray-700">
                    {{ item.user }}
                  </div>
                </div>

                <!-- Agent 回复（支持 Markdown 渲染） -->
                <div>
                  <div class="text-xs font-semibold text-gray-400 mb-1 flex items-center gap-1">
                    <el-icon><ChatDotSquare /></el-icon> Agent 回复
                    <span class="flex-1"></span>
                    <!-- 反馈按钮 -->
                    <el-button
                      :type="feedbackStatus[item.step] === 'good' ? 'primary' : 'default'"
                      size="small"
                      circle
                      @click="submitFeedback(item.step, 'Good')"
                      class="ml-2"
                    >👍</el-button>
                    <el-button
                      :type="feedbackStatus[item.step] === 'bad' ? 'danger' : 'default'"
                      size="small"
                      circle
                      @click="submitFeedback(item.step, 'Bad')"
                    >👎</el-button>
                  </div>
                  <div class="bg-white p-3 rounded-xl border border-gray-200 text-sm text-gray-700 markdown-body" v-html="renderMarkdown(item.assistant || '...')">
                  </div>
                </div>

                <!-- 轨迹卡片网格（el-tree 方案 + 原始 JSON 原文） -->
                <div class="trajectory-grid mt-2">
                  <!-- State 卡片 -->
                  <div class="trajectory-card card-state">
                    <div class="card-header"><el-icon><Document /></el-icon> STATE (s_t)</div>
                    <div class="card-content">
                      <el-tree
                        :data="objectToTreeData(item.s || {})"
                        :props="{ label: 'label', children: 'children' }"
                        default-expand-all
                        indent="16"
                        class="json-tree"
                      />
                      <div class="json-raw">
                        <div class="json-raw-header">原始 JSON：</div>
                        <pre class="json-raw-content">{{ formatJSON(item.s) }}</pre>
                      </div>
                    </div>
                  </div>

                  <!-- Action 卡片 -->
                  <div class="trajectory-card card-action">
                    <div class="card-header"><el-icon><Promotion /></el-icon> ACTION (a_t)</div>
                    <div class="card-content">
                      <el-tree
                        :data="objectToTreeData(item.a || {})"
                        :props="{ label: 'label', children: 'children' }"
                        default-expand-all
                        indent="16"
                        class="json-tree"
                      />
                      <div class="json-raw">
                        <div class="json-raw-header">原始 JSON：</div>
                        <pre class="json-raw-content">{{ formatJSON(item.a) }}</pre>
                      </div>
                    </div>
                  </div>

                  <!-- Observation 卡片 -->
                  <div class="trajectory-card card-obs">
                    <div class="card-header"><el-icon><ChatDotRound /></el-icon> OBSERVATION (o_t)</div>
                    <div class="card-content">
                      <el-tree
                        :data="objectToTreeData(item.o || {})"
                        :props="{ label: 'label', children: 'children' }"
                        default-expand-all
                        indent="16"
                        class="json-tree"
                      />
                      <div class="json-raw">
                        <div class="json-raw-header">原始 JSON：</div>
                        <pre class="json-raw-content">{{ formatJSON(item.o) }}</pre>
                      </div>
                    </div>
                  </div>

                  <!-- Reward 卡片 -->
                  <div class="trajectory-card card-reward">
                    <div class="card-header"><el-icon><Star /></el-icon> REWARD (r_t)</div>
                    <div class="card-content flex justify-center items-center">
                      <div class="text-center">
                        <span class="reward-number">{{ item.r ?? 0 }}</span>
                        <div class="text-xs text-gray-400 mt-1">奖励值</div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="chatList.length === 0" class="p-8 text-center text-gray-400">
              <el-icon size="48" class="mb-2"><ChatLineSquare /></el-icon>
              <p class="text-sm">暂无对话，发送第一条消息开始对话</p>
            </div>
          </div>
        </div>
      </div>

      <!-- 中间：图区域（DAG，支持拖拽缩放） -->
      <div class="flex-1 bg-white rounded-2xl shadow-sm border border-gray-100 flex flex-col overflow-hidden">
        <div class="px-5 py-3 bg-white border-b border-gray-100 flex justify-between items-center">
          <div class="flex items-center gap-2">
            <el-icon class="text-gray-500 text-lg"><Connection /></el-icon>
            <span class="font-medium text-gray-700">分支图</span>
          </div>
          <div class="flex items-center gap-2">
            <el-tag size="small" type="primary" effect="plain" round>{{ convList.length }} 个分支</el-tag>
            <el-button type="primary" size="small" @click="resetGraphView" :loading="loading" circle plain>
              <el-icon><Refresh /></el-icon>
            </el-button>
          </div>
        </div>
        <div class="flex-1 bg-gray-50 relative" ref="graphContainer">
          <div v-if="convList.length === 0" class="absolute inset-0 flex items-center justify-center text-gray-400">
            <div class="text-center">
              <el-icon size="64" class="mb-2"><Connection /></el-icon>
              <p class="text-sm">暂无分支</p>
              <p class="text-xs">创建对话后显示分支历史</p>
            </div>
          </div>
          <svg v-else ref="svgCanvas" class="w-full h-full"></svg>
        </div>
      </div>
    </div>

    <!-- 底部输入栏 -->
    <div class="bg-white border-t border-gray-200 p-4 shadow-sm">
      <div class="flex gap-3 max-w-5xl mx-auto">
        <el-input
          v-model="msgContent"
          type="textarea"
          :rows="2"
          placeholder="输入消息发送给 Nanobot... (Ctrl+Enter 发送)"
          @keyup.enter.ctrl="handleSend"
          :disabled="!currentConvId || loading"
          class="flex-1"
          :class="{ '!bg-gray-100': !currentConvId }"
        >
          <template #prefix>
            <el-icon class="text-blue-500 ml-2"><ChatDotSquare /></el-icon>
          </template>
        </el-input>
        <el-button 
          type="primary" 
          @click="handleSend" 
          :loading="loading" 
          :disabled="!currentConvId"
          class="!rounded-xl px-6"
        >
          <el-icon v-if="!loading"><Promotion /></el-icon>
          {{ loading ? '发送中...' : '发送' }}
        </el-button>
      </div>
    </div>

    <!-- 合并对话框 -->
    <el-dialog v-model="showMergeDialog" title="合并分支" width="500px" :close-on-click-modal="false">
      <div class="mb-4">
        <p class="text-sm text-gray-600 mb-2">选择要合并到的目标分支：</p>
        <el-select v-model="mergeTargetId" placeholder="选择目标分支" class="w-full">
          <el-option
            v-for="conv in availableMergeTargets"
            :key="conv.conversation_id"
            :label="`${conv.title} (${conv.conversation_id})`"
            :value="conv.conversation_id"
          />
        </el-select>
        <div class="mt-3">
          <el-checkbox v-model="autoMerge" label="自动合并（检测到冲突时使用LLM智能融合）" />
        </div>
      </div>
      <template #footer>
        <el-button @click="showMergeDialog = false">取消</el-button>
        <el-button type="primary" @click="handleMerge" :loading="loading">确认合并</el-button>
      </template>
    </el-dialog>

    <!-- 冲突解决对话框 -->
    <el-dialog v-model="showConflictDialog" title="合并冲突解决" width="800px" :close-on-click-modal="false">
      <div v-if="currentConflicts && currentConflicts.length > 0">
        <p class="text-sm text-gray-600 mb-4">检测到 {{ currentConflicts.length }} 个冲突，请选择解决方式：</p>
        
        <el-tabs type="border-card">
          <el-tab-pane v-for="(conflict, index) in currentConflicts" :key="index" :label="`冲突 ${index + 1}`">
            <div class="p-4">
              <p class="text-sm font-medium mb-2">位置: {{ conflict.position }}</p>
              
              <div class="grid grid-cols-2 gap-4">
                <!-- 源分支内容 -->
                <div class="border rounded-lg p-3">
                  <div class="text-sm font-medium text-blue-600 mb-2">源分支内容</div>
                  <div class="text-xs bg-blue-50 p-2 rounded">
                    <pre>{{ formatConflictContent(conflict.source_content || conflict.source_step) }}</pre>
                  </div>
                  <el-button 
                    size="small" 
                    type="primary" 
                    @click="resolveConflict(index, 'source')"
                    class="mt-2"
                  >
                    保留此内容
                  </el-button>
                </div>
                
                <!-- 目标分支内容 -->
                <div class="border rounded-lg p-3">
                  <div class="text-sm font-medium text-green-600 mb-2">目标分支内容</div>
                  <div class="text-xs bg-green-50 p-2 rounded">
                    <pre>{{ formatConflictContent(conflict.target_content || conflict.target_step) }}</pre>
                  </div>
                  <el-button 
                    size="small" 
                    type="success" 
                    @click="resolveConflict(index, 'target')"
                    class="mt-2"
                  >
                    保留此内容
                  </el-button>
                </div>
              </div>
              
              <div class="mt-4">
                <el-button 
                  size="small" 
                  type="warning" 
                  @click="resolveConflict(index, 'merge')"
                >
                  智能合并（使用LLM）
                </el-button>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>

      <template #footer>
        <el-button @click="showConflictDialog = false">取消合并</el-button>
        <el-button type="primary" @click="applyConflictResolutions" :loading="loading">
          应用所有解决方案
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Connection, User, Plus, Folder, Share, Switch, Delete,
  ChatDotRound, ChatLineSquare, Document, CaretRight,
  ChatDotSquare, Promotion, Files, Star, Refresh
} from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useConvStore } from './stores/conversation'
import {
  healthCheck, listConversations, createConversation, sendMessage,
  getTrajectory, getHistory, forkConversation, mergeConversation,
  deleteConversation, getConversationsStatus
} from './api/agentBff'
import BountyMarket from './components/BountyMarket.vue'
import * as d3 from 'd3'
import dagre from 'dagre'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

// 配置 marked（可选）
marked.setOptions({
  breaks: true,
  gfm: true,
  headerIds: false,
  mangle: false
})

// 渲染 Markdown 并净化 HTML
function renderMarkdown(text) {
  if (!text) return ''
  const rawHtml = marked.parse(text, { async: false })
  return DOMPurify.sanitize(rawHtml)
}

const store = useConvStore()
const { activeCount, currentConvId, convList, chatList } = storeToRefs(store)

const healthOk = ref(false)
const msgContent = ref('')
const loading = ref(false)
const showMergeDialog = ref(false)
const showConflictDialog = ref(false)
const mergeTargetId = ref('')
const autoMerge = ref(true)
const expandedIdx = ref(-1)
const graphContainer = ref(null)
const svgCanvas = ref(null)
const currentConflicts = ref([])
const conflictResolutions = ref({})

let currentZoom = null

// Power机制相关响应式数据
const currentPower = ref(50.0)
const totalAnnotations = ref(0)
const fileStatsStatus = ref('正常')
const fileStatsDetails = ref([])
const showFileStatsPanel = ref(false)
const feedbackStatus = ref({})

const currentBranchName = computed(() => {
  const conv = convList.value.find(c => c.conversation_id === currentConvId.value)
  return conv?.title || 'main'
})

const availableMergeTargets = computed(() => {
  return convList.value.filter(c => c.conversation_id !== currentConvId.value)
})

// 边权数据
let edgeWeightsMap = new Map()

// 获取边权数据
async function fetchEdgeWeights() {
  try {
    const response = await fetch('http://localhost:8000/node-relations/all')
    if (response.ok) {
      const data = await response.json()
      edgeWeightsMap.clear()
      data.relations.forEach(r => {
        edgeWeightsMap.set(`${r.source}-${r.target}`, r.weight)
        edgeWeightsMap.set(`${r.target}-${r.source}`, r.weight)  // 双向关系
      })
      console.log('[EdgeWeights] 已加载边权数据:', edgeWeightsMap.size)
    } else {
      // 降级方案：使用默认边权
      console.warn('[EdgeWeights] API 返回失败，使用默认边权')
      edgeWeightsMap.clear()
    }
  } catch (error) {
    console.error('获取边权数据失败:', error)
    // 降级方案：使用默认边权
    edgeWeightsMap.clear()
  }
}

// 获取边权的函数
function getEdgeWeight(sourceId, targetId) {
  const key = `${sourceId}-${targetId}`
  return edgeWeightsMap.get(key) || 1  // 默认值为 1
}

// Power相关计算属性
const powerColor = computed(() => {
  const power = currentPower.value
  if (power >= 80) return '#10b981' // 绿色
  if (power >= 60) return '#f59e0b' // 黄色
  if (power >= 40) return '#f97316' // 橙色
  return '#ef4444' // 红色
})

// 获取Power信息的函数
async function fetchPowerInfo() {
  if (!currentConvId.value) return
  
  try {
    const response = await fetch(`http://localhost:8000/conversations/${currentConvId.value}/power`)
    if (response.ok) {
      const data = await response.json()
      currentPower.value = data.power || 50.0
      totalAnnotations.value = data.total_annotations || 0
    }
  } catch (error) {
    console.error('获取Power信息失败:', error)
  }
}

// 获取文件状态信息的函数
async function fetchFileStats() {
  if (!currentConvId.value) return

  try {
    const response = await fetch(`http://localhost:8000/conversations/${currentConvId.value}/files`)
    if (response.ok) {
      const data = await response.json()
      const stats = data.file_stats || {}

      // 构建文件详情列表
      const files = [
        { name: 'trajectory.jsonl', path: '/app/workspace/conv_xxx/trajectory.jsonl' },
        { name: 'MEMORY.md', path: '/app/workspace/memory/MEMORY.md' },
        { name: 'conversation_history.json', path: '/app/workspace/sessions/container_xxx.jsonl' }
      ]

      fileStatsDetails.value = files.map(f => {
        const stat = stats[f.name] || { exists: false, size: 0, lines: 0 }
        return {
          name: f.name,
          path: f.path.replace('xxx', currentConvId.value),
          exists: stat.exists,
          size: stat.size,
          lines: stat.lines,
          status: stat.exists ? '正常' : '缺失'
        }
      })

      // 检查文件状态
      const missingFiles = fileStatsDetails.value.filter(f => !f.exists)
      if (missingFiles.length === 0) {
        fileStatsStatus.value = '正常'
      } else {
        fileStatsStatus.value = `${missingFiles.length}个异常`
      }
    }
  } catch (error) {
    console.error('获取文件状态失败:', error)
    fileStatsStatus.value = '获取失败'
    fileStatsDetails.value = []
  }
}

// 切换文件详情面板显示
function toggleFileStatsPanel() {
  showFileStatsPanel.value = !showFileStatsPanel.value
  if (showFileStatsPanel.value) {
    fetchFileStats()
  }
}

// 将对象转换为 el-tree 的 data 格式（安全版本）
function objectToTreeData(obj) {
  if (obj === null || obj === undefined) return []
  if (typeof obj !== 'object') {
    return [{ label: String(obj) }]
  }
  try {
    return Object.keys(obj).map(key => {
      const value = obj[key]
      let children = []
      if (typeof value === 'object' && value !== null) {
        children = objectToTreeData(value)
      } else {
        children = [{ label: String(value) }]
      }
      return {
        label: key,
        children: children
      }
    })
  } catch (error) {
    console.error('Error converting object to tree data:', error, obj)
    return [{ label: '数据格式错误，无法显示' }]
  }
}

// 格式化 JSON 为字符串（安全版本）
function formatJSON(obj) {
  try {
    if (typeof obj === 'string') {
      try {
        const parsed = JSON.parse(obj)
        return JSON.stringify(parsed, null, 2)
      } catch {
        return obj
      }
    }
    return JSON.stringify(obj, null, 2)
  } catch (error) {
    console.error('Error formatting JSON:', error, obj)
    return '数据格式错误，无法显示'
  }
}

// 轮询定时器
let pollingTimer = null

onMounted(async () => {
  await checkHealth()
  await loadConversations()
  window.addEventListener('resize', handleResize)
  // 启动轮询，每 5 秒刷新一次（包括边权数据）
  pollingTimer = setInterval(async () => {
    await loadConversations()
    await fetchEdgeWeights()  // 同时刷新边权数据
  }, 5000)
})

onUnmounted(() => {
  // 清除轮询定时器
  if (pollingTimer) {
    clearInterval(pollingTimer)
  }
  window.removeEventListener('resize', handleResize)
})

function handleResize() {
  drawGraph()
}

async function checkHealth() {
  try {
    const res = await healthCheck()
    healthOk.value = res.data?.status === 'ok'
  } catch (e) {
    healthOk.value = false
    ElMessage.error('BFF 服务未启动')
  }
}

async function loadConversations() {
  try {
    const statusRes = await getConversationsStatus()
    const statusList = statusRes.data?.conversations || []
    const healthyConversations = statusList
      .filter(conv => conv.healthy)
      .map(conv => ({
        conversation_id: conv.conversation_id,
        title: conv.title,
        model: conv.model,
        parent_id: conv.parent_id,
        created_at: conv.created_at,
        balance: conv.balance || 0  // 保留余额字段
      }))
    const invalidCount = statusList.length - healthyConversations.length
    if (invalidCount > 0) {
      console.log(`清理了 ${invalidCount} 个无效对话`)
    }
    store.setConvList(healthyConversations)
    store.setActiveCount(healthyConversations.length)
    if (healthyConversations.length > 0 && !currentConvId.value) {
      handleSwitchConv(healthyConversations[0])
    }
    // 获取边权数据
    await fetchEdgeWeights()
    drawGraph()
  } catch (e) {
    console.error('加载对话失败:', e)
    try {
      const res = await listConversations()
      const list = res.data?.conversations || []
      store.setConvList(list)
      store.setActiveCount(list.length)
      if (list.length > 0 && !currentConvId.value) {
        handleSwitchConv(list[0])
      }
      drawGraph()
    } catch (fallbackError) {
      console.error('回退加载也失败:', fallbackError)
    }
  }
}

function toggleExpand(idx) {
  expandedIdx.value = expandedIdx.value === idx ? -1 : idx
}

function resetGraphView() {
  if (svgCanvas.value && currentZoom) {
    const svg = d3.select(svgCanvas.value)
    svg.transition().duration(500).call(currentZoom.transform, d3.zoomIdentity)
  } else {
    drawGraph()
  }
}

async function handleCreateConv() {
  if (activeCount.value >= 10) {
    ElMessage.warning('已达到 10 个会话上限')
    return
  }
  loading.value = true
  try {
    const res = await createConversation({
      title: `对话-${new Date().toLocaleTimeString('zh-CN', {hour: '2-digit', minute:'2-digit'})}`,
      model: 'deepseek-chat',
      agent_type: 'km'
    })
    const conv = res.data
    conv.parent_id = null
    store.addConv(conv)
    store.setActiveCount(convList.value.length)
    store.setCurrentConv(conv.conversation_id)
    store.setChatList([])
    expandedIdx.value = -1
    ElMessage.success('创建成功')
    await nextTick()
    drawGraph()
  } catch (e) {
    ElMessage.error('创建失败')
  } finally {
    loading.value = false
  }
}

async function handleSwitchConv(conv) {
  store.setCurrentConv(conv.conversation_id)
  expandedIdx.value = -1
  await loadTrajectory(conv.conversation_id)
  await loadHistory(conv.conversation_id)

  // 获取Power信息、文件状态和反馈状态
  await fetchPowerInfo()
  await fetchFileStats()
  await loadFeedbackStatus(conv.conversation_id)
}

async function loadTrajectoryWithRetry(convId, retries = 3, delay = 1000) {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await getTrajectory(convId)
      store.setTrajectory(res.data?.trajectory || [])
      return true
    } catch (e) {
      if (i === retries - 1) {
        console.error(`加载轨迹失败 (convId=${convId}):`, e)
        ElMessage.warning(`对话 ${convId} 的轨迹暂不可用，请稍后刷新`)
        store.setTrajectory([])
        return false
      }
      await new Promise(resolve => setTimeout(resolve, delay))
    }
  }
}

async function loadHistoryWithRetry(convId, retries = 3, delay = 1000) {
  for (let i = 0; i < retries; i++) {
    try {
      const [historyRes, trajectoryRes] = await Promise.all([
        getHistory(convId),
        getTrajectory(convId)
      ])
      const history = historyRes.data?.history || []
      const trajectory = trajectoryRes.data?.trajectory || []
      
      const formatted = []
      let currentUserMsg = null
      let turnIndex = 0

      for (let i = 0; i < history.length; i++) {
        const msg = history[i]
        if (msg.role === 'user') {
          if (currentUserMsg) {
            console.log('跳过不完整的对话轮次')
          }
          currentUserMsg = msg
        } else if (msg.role === 'assistant' && currentUserMsg) {
          const trajRecord = trajectory[turnIndex] || {}
          formatted.push({
            step: turnIndex,
            user: currentUserMsg.content,
            assistant: msg.content || '...',
            s: trajRecord.s_t || {},
            a: trajRecord.a_t || {},
            o: trajRecord.o_t || {},
            r: trajRecord.r_t || 0
          })
          currentUserMsg = null
          turnIndex++
        }
      }
      store.setChatList(formatted)
      console.log(`过滤后消息轮次: ${formatted.length}, 原始消息数: ${history.length}`)
      return true
    } catch (e) {
      if (i === retries - 1) {
        console.error(`加载历史失败 (convId=${convId}):`, e)
        ElMessage.warning(`对话 ${convId} 的历史暂不可用，请稍后刷新`)
        store.setChatList([])
        return false
      }
      await new Promise(resolve => setTimeout(resolve, delay))
    }
  }
}

async function loadTrajectory(convId) {
  await loadTrajectoryWithRetry(convId)
}
async function loadHistory(convId) {
  await loadHistoryWithRetry(convId)
}

async function handleSend() {
  if (!msgContent.value || !currentConvId.value) return
  loading.value = true
  const content = msgContent.value
  msgContent.value = ''
  try {
      // 使用增强的Power集成版本发送消息（使用正确的baseURL）
      const response = await fetch(`http://localhost:8000/conversations/${currentConvId.value}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content })
      })
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      
      const data = await response.json()
    const chatItem = {
      user: content,
      assistant: data.content || '...',
      s: data.trajectory?.[data.trajectory.length - 1]?.s_t || {},
      a: data.trajectory?.[data.trajectory.length - 1]?.a_t || {},
      o: data.trajectory?.[data.trajectory.length - 1]?.o_t || {},
      r: data.trajectory?.[data.trajectory.length - 1]?.r_t || 0
    }
    store.appendChat(chatItem)
    expandedIdx.value = chatList.value.length - 1
    
    // 发送消息后更新Power信息
    await fetchPowerInfo()
    await fetchFileStats()
    
    ElMessage.success('消息发送成功，Power已更新')
  } catch (e) {
    ElMessage.error('发送失败：' + (e.message || '未知错误'))
    msgContent.value = content
  } finally {
    loading.value = false
  }
}

// 提交反馈函数
async function submitFeedback(stepIndex, label) {
  const convId = currentConvId.value
  if (!convId) return

  const current = feedbackStatus.value[stepIndex]
  const expectedKey = label === 'Good' ? 'good' : 'bad'

  if (current === expectedKey) {
    ElMessage.info('已取消反馈')
    delete feedbackStatus.value[stepIndex]
    return
  }

  try {
    const response = await fetch('http://localhost:8000/annotations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversation_id: convId,
        step: stepIndex,
        target_type: 'action',
        label: label
      })
    })
    if (!response.ok) throw new Error('提交失败')
    const data = await response.json()
    feedbackStatus.value[stepIndex] = label === 'Good' ? 'good' : 'bad'
    ElMessage.success(`反馈已提交，Power ${data.power_delta > 0 ? '提升' : '下降'} ${Math.abs(data.power_delta)}`)
    await fetchPowerInfo()
  } catch (e) {
    ElMessage.error('反馈提交失败：' + e.message)
  }
}

// 加载已有反馈状态
async function loadFeedbackStatus(convId) {
  try {
    const res = await fetch(`http://localhost:8000/conversations/${convId}/annotations`)
    if (res.ok) {
      const data = await res.json()
      const newStatus = {}
      data.annotations.forEach(ann => {
        if (ann.label === 'Good') newStatus[ann.step] = 'good'
        if (ann.label === 'Bad') newStatus[ann.step] = 'bad'
      })
      feedbackStatus.value = newStatus
    }
  } catch (e) {
    console.error('加载反馈状态失败', e)
  }
}

async function handleFork() {
  if (!currentConvId.value) return
  const branchName = prompt('请输入分支名称：', `分支-${new Date().toLocaleTimeString()}`)
  if (!branchName) return
  loading.value = true
  try {
    const res = await forkConversation(currentConvId.value, { new_branch_name: branchName })
    const currentConv = convList.value.find(c => c.conversation_id === currentConvId.value)
    const newConv = {
      conversation_id: res.data.new_conversation_id,
      title: branchName,
      parent_id: currentConvId.value,
      status: 'active',
      model: currentConv?.model || 'deepseek-chat',
      agent_type: 'collab'
    }
    store.addConv(newConv)
    store.setActiveCount(convList.value.length)
    ElMessage.success(`分支创建成功: ${branchName}`)
    await new Promise(resolve => setTimeout(resolve, 3000))
    await loadHistoryWithRetry(newConv.conversation_id, 5, 2000)
    await nextTick()
    drawGraph()
  } catch (e) {
    console.error('Fork error:', e)
    ElMessage.error('分支创建失败：' + (e.response?.data?.detail || e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

async function handleMerge() {
  if (!currentConvId.value || !mergeTargetId.value) return
  loading.value = true
  try {
    const res = await mergeConversation({
      source_conversation_id: currentConvId.value,
      target_conversation_id: mergeTargetId.value,
      auto_merge: autoMerge.value
    })
    
    if (res.data.status === 'conflict') {
      // 显示冲突解决界面
      currentConflicts.value = res.data.conflicts || []
      conflictResolutions.value = {}
      showConflictDialog.value = true
      ElMessage.warning('检测到合并冲突，请手动解决')
    } else if (res.data.status === 'merged') {
      // 合并成功
      ElMessage.success(res.data.message || '合并成功')
      showMergeDialog.value = false
      store.setCurrentConv(mergeTargetId.value)
      await loadConversations()
      const targetConv = convList.value.find(c => c.conversation_id === mergeTargetId.value)
      if (targetConv) {
        await loadHistory(mergeTargetId.value)
      }
      await nextTick()
      drawGraph()
    } else {
      // 合并失败
      ElMessage.error(res.data.message || '合并失败')
    }
  } catch (e) {
    ElMessage.error('合并失败：' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

function formatConflictContent(content) {
  if (typeof content === 'object') {
    return JSON.stringify(content, null, 2)
  }
  return String(content || '')
}

function resolveConflict(index, resolution) {
  conflictResolutions.value[index] = resolution
  ElMessage.success(`冲突 ${index + 1} 已标记为 ${resolution === 'source' ? '保留源分支' : resolution === 'target' ? '保留目标分支' : '智能合并'}`)
}

async function applyConflictResolutions() {
  if (Object.keys(conflictResolutions.value).length === 0) {
    ElMessage.warning('请先为所有冲突选择解决方案')
    return
  }
  
  loading.value = true
  try {
    // 将用户选择的冲突解决方案发送给后端
    const res = await mergeConversation({
      source_conversation_id: currentConvId.value,
      target_conversation_id: mergeTargetId.value,
      auto_merge: false,  // 不使用自动合并，使用用户选择的方案
      conflict_resolutions: conflictResolutions.value
    })
    
    if (res.data.status === 'merged') {
      ElMessage.success('冲突已解决，合并成功')
      showConflictDialog.value = false
      showMergeDialog.value = false
      store.setCurrentConv(mergeTargetId.value)
      await loadConversations()
      const targetConv = convList.value.find(c => c.conversation_id === mergeTargetId.value)
      if (targetConv) {
        await loadHistory(mergeTargetId.value)
      }
      await nextTick()
      drawGraph()
    } else {
      ElMessage.error('冲突解决失败：' + (res.data.message || '未知错误'))
    }
  } catch (e) {
    ElMessage.error('冲突解决失败：' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

async function handleDelete() {
  if (!currentConvId.value) return
  try {
    await ElMessageBox.confirm('确定要删除这个对话吗？此操作不可恢复。', '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }
  loading.value = true
  try {
    await deleteConversation(currentConvId.value)
    store.removeConv(currentConvId.value)
    store.setActiveCount(convList.value.length)
    if (convList.value.length > 0) {
      store.setCurrentConv(convList.value[0].conversation_id)
      await loadHistory(convList.value[0].conversation_id)
    } else {
      store.setCurrentConv('')
      store.setChatList([])
    }
    ElMessage.success('删除成功')
    await nextTick()
    drawGraph()
  } catch (e) {
    ElMessage.error('删除失败')
  } finally {
    loading.value = false
  }
}

function drawGraph() {
  if (!svgCanvas.value || convList.value.length === 0) return
  const container = graphContainer.value
  const width = container.clientWidth
  const height = container.clientHeight
  const svg = d3.select(svgCanvas.value)
  svg.selectAll('*').remove()
  const zoom = d3.zoom()
    .scaleExtent([0.2, 5])
    .on('zoom', (event) => {
      svgGroup.attr('transform', event.transform)
    })
  currentZoom = zoom
  svg.call(zoom)
  const svgGroup = svg.append('g').attr('class', 'graph-group')
  
  // 构建节点映射
  const nodeMap = new Map()
  convList.value.forEach(conv => {
    nodeMap.set(conv.conversation_id, {
      id: conv.conversation_id,
      title: conv.title,
      parent_id: conv.parent_id || null,
      balance: conv.balance || 0,
      agent_type: conv.agent_type || 'km'
    })
  })
  
  // 创建 dagre 图
  const g = new dagre.graphlib.Graph()
  g.setGraph({
    rankdir: 'TB',  // 从上到下
    nodesep: 50,
    ranksep: 80,
    marginx: 20,
    marginy: 20
  })
  g.setDefaultEdgeLabel(() => ({}))
  
  // 添加节点
  nodeMap.forEach((node, id) => {
    // 计算节点宽度，基于标题长度
    const titleLength = node.title.length
    const nodeWidth = Math.max(120, titleLength * 8)
    g.setNode(id, {
      label: node.title,
      width: nodeWidth,
      height: 50,
      agentType: node.agent_type
    })
  })
  
  // 添加边
  nodeMap.forEach((node, id) => {
    if (node.parent_id && nodeMap.has(node.parent_id)) {
      g.setEdge(node.parent_id, id)
    }
  })

  // 运行布局
  dagre.layout(g)

  // 绘制边
  svgGroup.selectAll('.link')
    .data(g.edges())
    .enter()
    .append('path')
    .attr('class', 'link')
    .attr('d', d => {
      const source = g.node(d.v)
      const target = g.node(d.w)
      return d3.linkVertical()
        .x(d => d.x)
        .y(d => d.y)({
          source: { x: source.x, y: source.y + source.height / 2 },
          target: { x: target.x, y: target.y - target.height / 2 }
        })
    })
    .attr('fill', 'none')
    .attr('stroke', '#999')
    .attr('stroke-width', d => {
      // 根据边权设置线宽
      const weight = getEdgeWeight(d.v, d.w)
      return Math.max(1, weight)
    })
  
  // 添加边权标签
  svgGroup.selectAll('.edge-label')
    .data(g.edges())
    .enter()
    .append('text')
    .attr('class', 'edge-label')
    .attr('x', d => {
      const source = g.node(d.v)
      const target = g.node(d.w)
      return (source.x + target.x) / 2
    })
    .attr('y', d => {
      const source = g.node(d.v)
      const target = g.node(d.w)
      return (source.y + target.y) / 2 - 10
    })
    .text(d => {
      const weight = getEdgeWeight(d.v, d.w)
      return weight
    })
    .attr('font-size', '10px')
    .attr('fill', '#666')
  
  // 绘制节点
  const nodeGroups = svgGroup.selectAll('.node')
    .data(g.nodes())
    .enter()
    .append('g')
    .attr('class', 'node')
    .attr('transform', d => {
      const node = g.node(d)
      return `translate(${node.x}, ${node.y})`
    })
    .on('click', (event, d) => {
      event.stopPropagation()
      const conv = convList.value.find(c => c.conversation_id === d)
      if (conv) handleSwitchConv(conv)
    })
    .style('cursor', 'pointer')
  
  nodeGroups.append('circle')
    .attr('r', 8)
    .attr('fill', d => {
      const nodeData = g.node(d)
      const agentType = nodeData ? nodeData.agentType : 'km'
      if (d === currentConvId.value) return '#007acc'  // 当前选中：蓝色
      return agentType === 'km' ? '#9c27b0' : '#ff9800'  // KM：紫色，协作者：橙色
    })
    .attr('stroke', '#fff')
    .attr('stroke-width', 2)

  // 添加Agent类型标签
  nodeGroups.append('text')
    .attr('x', 15)
    .attr('y', -12)
    .text(d => {
      const nodeData = g.node(d)
      const agentType = nodeData ? nodeData.agentType : 'km'
      return agentType === 'km' ? '[KM]' : '[Collab]'
    })
    .attr('font-size', '10px')
    .attr('fill', d => {
      const nodeData = g.node(d)
      const agentType = nodeData ? nodeData.agentType : 'km'
      return agentType === 'km' ? '#9c27b0' : '#ff9800'
    })
  
  nodeGroups.append('text')
    .attr('x', 15)
    .attr('y', 5)
    .text(d => g.node(d).label)
    .attr('font-size', '12px')
    .attr('fill', '#333')
  
  // 添加钱包余额显示
  nodeGroups.append('text')
    .attr('x', 15)
    .attr('y', 20)
    .text(d => {
      const node = nodeMap.get(d)
      return node ? `Token: ${node.balance || 0}` : 'Token: 0'
    })
    .attr('font-size', '10px')
    .attr('fill', d => {
      const node = nodeMap.get(d)
      const balance = node ? (node.balance || 0) : 0
      if (balance > 1000) return '#4caf50' // 绿色：余额充足
      if (balance > 0) return '#ff9800' // 橙色：余额较少
      return '#f44336' // 红色：无余额
    })
}
</script>

<style scoped>
/* 基础滚动条样式 */
* {
  scrollbar-width: thin;
}

/* 轨迹卡片网格布局 */
.trajectory-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.75rem;
}

@media (max-width: 768px) {
  .trajectory-grid {
    grid-template-columns: 1fr;
  }
}

/* 卡片通用样式 */
.trajectory-card {
  background: white;
  border-radius: 1rem;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
  border: 1px solid #f0f0f0;
  transition: all 0.2s ease;
  overflow: hidden;
}
.trajectory-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 20px rgba(0,0,0,0.08);
  border-color: #e2e8f0;
}

/* 卡片头部 */
.card-header {
  padding: 0.5rem 0.75rem;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: #fafafa;
  border-bottom: 1px solid #f0f0f0;
}
.card-state .card-header { background: #eff6ff; color: #1e40af; }
.card-action .card-header { background: #f0fdf4; color: #166534; }
.card-obs .card-header { background: #fffbeb; color: #b45309; }
.card-reward .card-header { background: #faf5ff; color: #6b21a5; }

/* 卡片内容区 */
.card-content {
  padding: 0.75rem;
  overflow-x: auto;
  word-break: break-word;
}

/* el-tree 样式 */
.json-tree {
  background: transparent;
  font-size: 0.7rem;
  font-family: 'SF Mono', 'Fira Code', monospace;
}
.json-tree .el-tree-node__content {
  height: auto !important;
  min-height: 28px;
  white-space: normal !important;
  word-break: break-word !important;
  overflow-wrap: break-word !important;
  padding: 4px 0;
  align-items: flex-start;
}
.json-tree .el-tree-node__label {
  white-space: normal !important;
  word-break: break-word !important;
  overflow-wrap: break-word !important;
  line-height: 1.4;
  display: inline-block;
  max-width: 100%;
  width: 100%;
}
.json-tree .el-tree-node__expand-icon {
  margin-top: 2px;
  flex-shrink: 0;
}
.json-tree .el-tree-node__children {
  padding-left: 16px;
}

/* 原始 JSON 展示 */
.json-raw {
  margin-top: 12px;
  border-top: 1px dashed #e2e8f0;
  padding-top: 8px;
}
.json-raw-header {
  font-size: 0.65rem;
  font-weight: 600;
  color: #6b7280;
  margin-bottom: 6px;
  letter-spacing: 0.3px;
}
.json-raw-content {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px;
  font-size: 0.7rem;
  font-family: 'SF Mono', 'Fira Code', monospace;
  line-height: 1.4;
  color: #1e293b;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  margin: 0;
}

/* Reward 数字样式 */
.reward-number {
  font-size: 2.5rem;
  font-weight: 800;
  background: linear-gradient(135deg, #a855f7, #d946ef);
  background-clip: text;
  -webkit-background-clip: text;
  color: transparent;
  transition: transform 0.1s ease;
}
.reward-number:hover {
  transform: scale(1.02);
}

/* Markdown 渲染样式 */
.markdown-body {
  line-height: 1.6;
}
.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  margin-top: 1em;
  margin-bottom: 0.5em;
  font-weight: 600;
}
.markdown-body h1 { font-size: 1.5em; }
.markdown-body h2 { font-size: 1.3em; }
.markdown-body h3 { font-size: 1.1em; }
.markdown-body p {
  margin-bottom: 0.8em;
}
.markdown-body ul,
.markdown-body ol {
  margin: 0.5em 0;
  padding-left: 1.5em;
}
.markdown-body li {
  margin: 0.2em 0;
}
.markdown-body code {
  background-color: #f3f4f6;
  padding: 0.2em 0.4em;
  border-radius: 4px;
  font-family: 'SF Mono', monospace;
  font-size: 0.85em;
}
.markdown-body pre {
  background-color: #f3f4f6;
  padding: 0.8em;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 0.85em;
}
.markdown-body pre code {
  background: none;
  padding: 0;
}
.markdown-body blockquote {
  border-left: 4px solid #d1d5db;
  margin: 0.5em 0;
  padding-left: 1em;
  color: #4b5563;
}
.markdown-body a {
  color: #3b82f6;
  text-decoration: none;
}
.markdown-body a:hover {
  text-decoration: underline;
}
.markdown-body img {
  max-width: 100%;
  height: auto;
}
</style>