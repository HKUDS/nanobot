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
        <el-tag :type="activeCount >= 10 ? 'warning' : 'success'" effect="dark" size="small" round>
          活跃：{{ activeCount }}/10
        </el-tag>
        <el-button type="primary" size="small" @click="handleCreateConv" :disabled="activeCount >= 10" class="!rounded-lg">
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
import { ref, computed, onMounted, nextTick } from 'vue'
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
import * as d3 from 'd3'
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

const currentBranchName = computed(() => {
  const conv = convList.value.find(c => c.conversation_id === currentConvId.value)
  return conv?.title || 'main'
})

const availableMergeTargets = computed(() => {
  return convList.value.filter(c => c.conversation_id !== currentConvId.value)
})

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

onMounted(async () => {
  await checkHealth()
  await loadConversations()
  window.addEventListener('resize', handleResize)
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
        created_at: conv.created_at
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
      model: 'deepseek-chat'
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
    const res = await sendMessage(currentConvId.value, { content })
    const data = res.data
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
  } catch (e) {
    ElMessage.error('发送失败：' + (e.message || '未知错误'))
    msgContent.value = content
  } finally {
    loading.value = false
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
      model: currentConv?.model || 'deepseek-chat'
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
  const nodeMap = new Map()
  convList.value.forEach(conv => {
    nodeMap.set(conv.conversation_id, {
      id: conv.conversation_id,
      title: conv.title,
      parent_id: conv.parent_id || null,
      children: []
    })
  })
  nodeMap.forEach(node => {
    if (node.parent_id && nodeMap.has(node.parent_id)) {
      nodeMap.get(node.parent_id).children.push(node)
    }
  })
  const rootNodes = Array.from(nodeMap.values()).filter(n => !n.parent_id)
  if (rootNodes.length === 0) return
  const root = d3.hierarchy(rootNodes[0])
  const treeLayout = d3.tree().size([width - 100, height - 100])
  treeLayout(root)
  svgGroup.selectAll('.link')
    .data(root.links())
    .enter()
    .append('path')
    .attr('class', 'link')
    .attr('d', d3.linkVertical()
      .x(d => d.x)
      .y(d => d.y)
    )
    .attr('fill', 'none')
    .attr('stroke', '#999')
    .attr('stroke-width', 2)
  const nodeGroups = svgGroup.selectAll('.node')
    .data(root.descendants())
    .enter()
    .append('g')
    .attr('class', 'node')
    .attr('transform', d => `translate(${d.x}, ${d.y})`)
    .on('click', (event, d) => {
      event.stopPropagation()
      const conv = convList.value.find(c => c.conversation_id === d.data.id)
      if (conv) handleSwitchConv(conv)
    })
    .style('cursor', 'pointer')
  nodeGroups.append('circle')
    .attr('r', 8)
    .attr('fill', d => d.data.id === currentConvId.value ? '#007acc' : '#4caf50')
    .attr('stroke', '#fff')
    .attr('stroke-width', 2)
  nodeGroups.append('text')
    .attr('x', 15)
    .attr('y', 5)
    .text(d => d.data.title)
    .attr('font-size', '12px')
    .attr('fill', '#333')
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