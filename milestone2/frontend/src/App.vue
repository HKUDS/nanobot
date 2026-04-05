<template>
  <div class="h-screen flex flex-col bg-gray-50">
    <!-- 顶部导航栏（现代化） -->
    <div class="bg-red-500 border-b border-gray-200 px-6 py-3 flex justify-between items-center shadow-sm">
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
      <!-- 左侧：对话列表（新风格） -->
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
                <div>
                  <div class="text-xs font-semibold text-gray-400 mb-1 flex items-center gap-1">
                    <el-icon><User /></el-icon> 用户消息
                  </div>
                  <div class="bg-white p-3 rounded-xl border border-gray-200 text-sm text-gray-700">
                    {{ item.user }}
                  </div>
                </div>

                <div>
                  <div class="text-xs font-semibold text-gray-400 mb-1 flex items-center gap-1">
                    <el-icon><ChatDotSquare /></el-icon> Agent 回复
                  </div>
                  <div class="bg-white p-3 rounded-xl border border-gray-200 text-sm text-gray-700">
                    {{ item.assistant || '...' }}
                  </div>
                </div>

                <div class="trajectory-grid mt-2">
                  <div class="trajectory-card card-state">
                    <div class="card-header"><el-icon><Document /></el-icon> STATE (s_t)</div>
                    <div class="card-content"><div class="json-view">{{ formatJSON(item.s || {}) }}</div></div>
                  </div>
                  <div class="trajectory-card card-action">
                    <div class="card-header"><el-icon><Promotion /></el-icon> ACTION (a_t)</div>
                    <div class="card-content"><div class="json-view">{{ formatJSON(item.a || {}) }}</div></div>
                  </div>
                  <div class="trajectory-card card-obs">
                    <div class="card-header"><el-icon><ChatDotRound /></el-icon> OBSERVATION (o_t)</div>
                    <div class="card-content"><div class="json-view">{{ formatJSON(item.o || {}) }}</div></div>
                  </div>
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

      <!-- 中间：图区域（DAG）新风格 -->
      <div class="flex-1 bg-white rounded-2xl shadow-sm border border-gray-100 flex flex-col overflow-hidden">
        <div class="px-5 py-3 bg-white border-b border-gray-100 flex justify-between items-center">
          <div class="flex items-center gap-2">
            <el-icon class="text-gray-500 text-lg"><Connection /></el-icon>
            <span class="font-medium text-gray-700">分支图</span>
          </div>
          <el-tag size="small" type="primary" effect="plain" round>{{ convList.length }} 个分支</el-tag>
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
      </div>
      <template #footer>
        <el-button @click="showMergeDialog = false">取消</el-button>
        <el-button type="primary" @click="handleMerge" :loading="loading">确认合并</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { 
  Connection, Plus, Folder, Share, Switch, 
  ChatDotRound, ChatLineSquare, Document, CaretRight,
  ChatDotSquare, Promotion, Files, Star, User
} from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useConvStore } from './stores/conversation'
import {
  healthCheck,
  listConversations,
  createConversation,
  sendMessage,
  getTrajectory,
  getHistory,
  forkConversation,
  mergeConversation,
  deleteConversation
} from './api/agentBff'
import * as d3 from 'd3'

const store = useConvStore()
const { activeCount, currentConvId, convList, chatList } = storeToRefs(store)

const healthOk = ref(false)
const msgContent = ref('')
const loading = ref(false)
const showMergeDialog = ref(false)
const mergeTargetId = ref('')
const expandedIdx = ref(-1)
const graphContainer = ref(null)
const svgCanvas = ref(null)

const currentBranchName = computed(() => {
  const conv = convList.value.find(c => c.conversation_id === currentConvId.value)
  return conv?.title || 'main'
})

const availableMergeTargets = computed(() => {
  return convList.value.filter(c => c.conversation_id !== currentConvId.value)
})

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
    const res = await listConversations()
    const list = res.data?.conversations || []
    store.setConvList(list)
    store.setActiveCount(list.length)
    if (list.length > 0 && !currentConvId.value) {
      handleSwitchConv(list[0])
    }
    drawGraph()
  } catch (e) {
    console.error('加载对话失败:', e)
  }
}

function toggleExpand(idx) {
  expandedIdx.value = expandedIdx.value === idx ? -1 : idx
}

function formatJSON(obj) {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
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
    store.addConv(conv)
    store.setActiveCount(convList.value.length)
    store.setCurrentConv(conv.conversation_id)
    store.setChatList([])
    expandedIdx.value = -1
    ElMessage.success('创建成功')
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

async function loadTrajectory(convId) {
  try {
    const res = await getTrajectory(convId)
    store.setTrajectory(res.data?.trajectory || [])
  } catch (e) {
    console.error('加载轨迹失败:', e)
  }
}

async function loadHistory(convId) {
  try {
    const [historyRes, trajectoryRes] = await Promise.all([
      getHistory(convId),
      getTrajectory(convId)
    ])
    
    const history = historyRes.data?.history || []
    const trajectory = trajectoryRes.data?.trajectory || []
    
    const formatted = []
    for (let i = 0; i < history.length; i += 2) {
      const userMsg = history[i]
      const assistantMsg = history[i + 1]
      const trajIndex = Math.floor(i / 2)
      const trajRecord = trajectory[trajIndex] || {}
      
      if (userMsg) {
        formatted.push({
          user: userMsg.content,
          assistant: assistantMsg?.content || '...',
          s: trajRecord.s_t || {},
          a: trajRecord.a_t || {},
          o: trajRecord.o_t || {},
          r: trajRecord.r_t || 0
        })
      }
    }
    store.setChatList(formatted)
  } catch (e) {
    console.error('加载历史失败:', e)
  }
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

  loading.value = true
  try {
    const res = await forkConversation(currentConvId.value, {
      parent_conversation_id: currentConvId.value,
      new_branch_name: '分支'
    })
    const currentConv = convList.value.find(c => c.conversation_id === currentConvId.value)
    const newConv = {
      conversation_id: res.data.new_conversation_id,
      title: `${currentConv?.title || '对话'} (fork)`,
      status: 'active',
      model: currentConv?.model || 'deepseek-chat'
    }
    store.addConv(newConv)
    store.setActiveCount(convList.value.length)
    ElMessage.success('Fork 成功')
    drawGraph()
  } catch (e) {
    ElMessage.error('Fork 失败')
  } finally {
    loading.value = false
  }
}

async function handleMerge() {
  if (!currentConvId.value || !mergeTargetId.value) return

  loading.value = true
  try {
    await mergeConversation({
      source_conversation_id: currentConvId.value,
      target_conversation_id: mergeTargetId.value
    })
    ElMessage.success('合并成功')
    showMergeDialog.value = false
    
    store.setCurrentConv(mergeTargetId.value)
    await loadConversations()
    
    const targetConv = convList.value.find(c => c.conversation_id === mergeTargetId.value)
    if (targetConv) {
      await loadHistory(mergeTargetId.value)
    }
  } catch (e) {
    ElMessage.error('合并失败')
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

  d3.select(svgCanvas.value).selectAll('*').remove()

  const svg = d3.select(svgCanvas.value)
    .attr('width', width)
    .attr('height', height)

  const nodes = convList.value.map((conv, i) => ({
    id: conv.conversation_id,
    title: conv.title,
    y: (i + 1) * (height / (convList.value.length + 1))
  }))

  const links = nodes.slice(1).map((node, i) => ({
    source: nodes[i].id,
    target: node.id
  }))

  svg.selectAll('.link')
    .data(links)
    .enter()
    .append('line')
    .attr('class', 'link')
    .attr('x1', 50)
    .attr('y1', d => nodes.find(n => n.id === d.source).y)
    .attr('x2', 50)
    .attr('y2', d => nodes.find(n => n.id === d.target).y)
    .attr('stroke', '#999')
    .attr('stroke-width', 2)

  const nodeGroups = svg.selectAll('.node')
    .data(nodes)
    .enter()
    .append('g')
    .attr('class', 'node')
    .attr('transform', d => `translate(50, ${d.y})`)
    .on('click', (event, d) => {
      const conv = convList.value.find(c => c.conversation_id === d.id)
      if (conv) handleSwitchConv(conv)
    })
    .style('cursor', 'pointer')

  nodeGroups.append('circle')
    .attr('r', 8)
    .attr('fill', d => d.id === currentConvId.value ? '#007acc' : '#4caf50')
    .attr('stroke', '#fff')
    .attr('stroke-width', 2)

  nodeGroups.append('text')
    .attr('x', 15)
    .attr('y', 5)
    .text(d => d.title)
    .attr('font-size', '12px')
    .attr('fill', '#333')
}
</script>

<style scoped>
* {
  scrollbar-width: thin;
}

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

.card-content {
  padding: 0.75rem;
}

.json-view {
  background: #f9fafb;
  border-radius: 0.75rem;
  padding: 0.5rem;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 0.65rem;
  line-height: 1.4;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: #1f2937;
  border: 1px solid #eef2f6;
}

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
</style>