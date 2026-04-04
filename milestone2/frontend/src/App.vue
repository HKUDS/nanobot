<template>
  <div class="h-screen flex flex-col bg-gray-50">
    <!-- 顶部导航 -->
    <div class="bg-indigo-600 text-white px-4 py-3 flex justify-between items-center shadow-md">
      <h2 class="text-lg font-bold flex items-center gap-2">
        <span class="text-2xl">🐈</span>
        Nanobot 容器化智能体管理系统
      </h2>
      <div class="flex items-center gap-4">
        <el-tag :type="healthOk ? 'success' : 'danger'" size="large">
          {{ healthOk ? '服务正常' : '服务异常' }}
        </el-tag>
        <el-tag :type="activeCount >= 10 ? 'danger' : 'success'" size="large">
          活跃会话：{{ activeCount }}/10
        </el-tag>
        <el-button type="primary" size="large" @click="handleCreateConv" :disabled="activeCount >= 10">
          + 新建对话
        </el-button>
      </div>
    </div>

    <!-- 主体布局 -->
    <div class="flex-1 flex overflow-hidden">
      <!-- 左侧：对话列表 -->
      <div class="w-72 bg-white border-r p-4 overflow-y-auto">
        <h3 class="font-semibold mb-3 text-gray-700 flex items-center gap-2">
          <span>📋</span> 对话分支
        </h3>

        <div class="space-y-2">
          <div
            v-for="conv in convList"
            :key="conv.conversation_id"
            :class="[
              'p-3 rounded-lg cursor-pointer transition-all',
              currentConvId === conv.conversation_id
                ? 'bg-indigo-100 border-2 border-indigo-400'
                : 'bg-gray-50 border-2 border-transparent hover:bg-gray-100'
            ]"
            @click="handleSwitchConv(conv)"
          >
            <div class="flex items-center justify-between">
              <span class="font-medium text-gray-800 truncate flex-1">
                {{ conv.title || '未命名对话' }}
              </span>
              <el-tag size="small" :type="conv.status === 'active' ? 'success' : 'info'">
                {{ conv.status === 'active' ? '活跃' : '已合并' }}
              </el-tag>
            </div>
            <div class="text-xs text-gray-500 mt-1">
              ID: {{ conv.conversation_id }}
            </div>
          </div>
        </div>

        <div v-if="convList.length === 0" class="text-center text-gray-400 mt-8">
          暂无对话
        </div>

        <!-- Fork / Merge 按钮 -->
        <div class="mt-6 flex flex-col gap-2" v-if="currentConvId">
          <el-button type="success" @click="handleFork" :loading="loading">
            🔀 Fork当前分支
          </el-button>
          <el-button type="warning" @click="showMergeDialog = true" :disabled="convList.length < 2">
            🔀 合并分支
          </el-button>
          <el-button type="danger" plain @click="handleDelete">
            🗑️ 删除对话
          </el-button>
        </div>
      </div>

      <!-- 中间：对话区域 -->
      <div class="flex-1 flex flex-col p-4 overflow-hidden">
        <!-- 无选中对话提示 -->
        <div v-if="!currentConvId" class="flex-1 flex items-center justify-center text-gray-400">
          <div class="text-center">
            <div class="text-6xl mb-4">💬</div>
            <p class="text-xl">请选择或创建一个对话</p>
          </div>
        </div>

        <!-- 有选中对话 -->
        <template v-else>
          <!-- 对话流 -->
          <div class="flex-1 overflow-y-auto bg-white rounded-lg p-4 mb-3 shadow-inner">
            <div v-if="chatList.length === 0" class="text-center text-gray-400 mt-8">
              开始发送消息...
            </div>

            <div v-for="(item, idx) in chatList" :key="idx" class="mb-6">
              <!-- 用户消息 -->
              <div class="flex justify-end mb-3">
                <div class="bg-indigo-500 text-white px-4 py-2 rounded-2xl rounded-br-sm max-w-[70%] shadow">
                  {{ item.user }}
                </div>
              </div>

              <!-- Agent回复 -->
              <div class="flex justify-start mb-3">
                <div class="bg-gray-100 text-gray-800 px-4 py-2 rounded-2xl rounded-bl-sm max-w-[70%] shadow">
                  {{ item.assistant || item.o || '...' }}
                </div>
              </div>

              <!-- 轨迹面板 (s,a,o,r) -->
              <div class="bg-gray-50 p-4 rounded-lg border border-gray-200 text-sm">
                <div class="font-semibold text-gray-700 mb-2">📊 轨迹数据</div>
                <div class="grid grid-cols-2 gap-2">
                  <div class="bg-blue-50 p-2 rounded">
                    <span class="font-semibold text-blue-600">s:</span>
                    <pre class="text-xs mt-1 whitespace-pre-wrap">{{ JSON.stringify(item.s || {}, null, 2) }}</pre>
                  </div>
                  <div class="bg-green-50 p-2 rounded">
                    <span class="font-semibold text-green-600">a:</span>
                    <pre class="text-xs mt-1 whitespace-pre-wrap">{{ JSON.stringify(item.a || {}, null, 2) }}</pre>
                  </div>
                  <div class="bg-yellow-50 p-2 rounded">
                    <span class="font-semibold text-yellow-600">o:</span>
                    <pre class="text-xs mt-1 whitespace-pre-wrap">{{ JSON.stringify(item.o || {}, null, 2) }}</pre>
                  </div>
                  <div class="bg-purple-50 p-2 rounded">
                    <span class="font-semibold text-purple-600">r:</span>
                    <pre class="text-xs mt-1">{{ item.r || 0 }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 输入框 -->
          <div class="bg-white rounded-lg p-3 shadow-lg flex gap-3">
            <el-input
              v-model="msgContent"
              type="textarea"
              :rows="2"
              placeholder="输入消息发送给 Nanobot..."
              @keyup.enter.ctrl="handleSend"
              :disabled="loading"
            />
            <el-button type="primary" @click="handleSend" :loading="loading" class="self-end">
              发送
            </el-button>
          </div>

          <div class="text-center text-xs text-gray-400 mt-2">
            按 Ctrl+Enter 发送
          </div>
        </template>
      </div>
    </div>

    <!-- Merge 对话框 -->
    <el-dialog v-model="showMergeDialog" title="合并分支" width="500px">
      <div class="mb-4">选择要合并到的目标分支：</div>
      <el-select v-model="mergeTargetId" placeholder="选择目标分支" class="w-full">
        <el-option
          v-for="conv in availableMergeTargets"
          :key="conv.conversation_id"
          :label="`${conv.title} (${conv.conversation_id})`"
          :value="conv.conversation_id"
        />
      </el-select>
      <template #footer>
        <el-button @click="showMergeDialog = false">取消</el-button>
        <el-button type="primary" @click="handleMerge" :loading="loading">确认合并</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
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

const store = useConvStore()
const { activeCount, currentConvId, convList, chatList } = storeToRefs(store)

const healthOk = ref(false)
const msgContent = ref('')
const loading = ref(false)
const showMergeDialog = ref(false)
const mergeTargetId = ref('')

const availableMergeTargets = computed(() => {
  return convList.value.filter(c => c.conversation_id !== currentConvId.value)
})

onMounted(async () => {
  await checkHealth()
  await loadConversations()
})

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
  } catch (e) {
    console.error('加载对话失败:', e)
  }
}

async function handleCreateConv() {
  if (activeCount.value >= 10) {
    ElMessage.warning('已达到10个会话上限')
    return
  }

  loading.value = true
  try {
    const res = await createConversation({
      title: `对话-${Date.now()}`,
      model: 'deepseek-chat'
    })
    const conv = res.data
    store.addConv(conv)
    store.setActiveCount(convList.value.length)
    store.setCurrentConv(conv.conversation_id)
    store.setChatList([])
    ElMessage.success('创建成功')
  } catch (e) {
    ElMessage.error('创建失败')
  } finally {
    loading.value = false
  }
}

async function handleSwitchConv(conv) {
  store.setCurrentConv(conv.conversation_id)
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
    const res = await getHistory(convId)
    const history = res.data?.history || []
    const formatted = []
    for (let i = 0; i < history.length; i += 2) {
      const userMsg = history[i]
      const assistantMsg = history[i + 1]
      if (userMsg) {
        formatted.push({
          user: userMsg.content,
          assistant: assistantMsg?.content || '...'
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
  } catch (e) {
    ElMessage.error('发送失败: ' + (e.message || '未知错误'))
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
    const newConv = {
      conversation_id: res.data.new_conversation_id,
      title: `${convList.value.find(c => c.conversation_id === currentConvId.value)?.title || '对话'} (fork)`,
      status: 'active'
    }
    store.addConv(newConv)
    store.setActiveCount(convList.value.length)
    ElMessage.success('Fork 成功')
    showMergeDialog.value = false
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
    await loadConversations()
  } catch (e) {
    ElMessage.error('合并失败')
  } finally {
    loading.value = false
  }
}

async function handleDelete() {
  if (!currentConvId.value) return

  try {
    await ElMessageBox.confirm('确定要删除这个对话吗?', '确认', {
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
    store.setActiveCount(convList.value.length - 1)
    if (currentConvId.value === convList.value[0]?.conversation_id) {
      store.setCurrentConv('')
      store.setChatList([])
    }
    ElMessage.success('删除成功')
  } catch (e) {
    ElMessage.error('删除失败')
  } finally {
    loading.value = false
  }
}
</script>
