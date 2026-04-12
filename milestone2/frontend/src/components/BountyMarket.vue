<template>
  <div class="bounty-market p-4">
    <div class="flex justify-between items-center mb-4">
      <h2 class="text-lg font-semibold text-gray-800">悬赏市场</h2>
      <div class="flex items-center gap-4">
        <el-badge :value="unreadNotifications.length" :hidden="unreadNotifications.length === 0">
          <el-button circle @click="showNotificationsDialog = true">
            <el-icon><Bell /></el-icon>
          </el-button>
        </el-badge>
        <el-button type="primary" @click="showCreateDialog = true">
          <el-icon class="mr-1"><Plus /></el-icon>
          发布悬赏
        </el-button>
      </div>
    </div>

    <!-- 邻居列表 -->
    <el-card class="neighbor-list" style="margin-bottom: 20px;">
      <template #header>
        <div class="card-header">
          <span>👥 邻居节点</span>
          <el-button size="small" @click="fetchNeighbors">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </template>
      <el-empty v-if="neighbors.length === 0" description="暂无邻居节点" />
      <el-list v-else>
        <el-list-item v-for="neighbor in neighbors" :key="neighbor.node_id">
          <div class="neighbor-item">
            <span class="neighbor-id">{{ neighbor.node_id }}</span>
            <el-tag type="warning" effect="dark">亲密度: {{ (neighbor.weight || 0).toFixed(2) }}</el-tag>
          </div>
        </el-list-item>
      </el-list>
    </el-card>

    <el-table :data="bounties" style="width: 100%" v-loading="loading" stripe>
      <el-table-column prop="title" label="标题" min-width="150"></el-table-column>
      <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip></el-table-column>
      <el-table-column prop="reward_pool" label="奖励 Token" width="120" align="center">
        <template #default="{ row }">
          <el-tag type="warning" effect="dark">{{ row.reward_pool }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="docker_reward" label="Docker 奖励" width="120" align="center">
        <template #default="{ row }">
          <el-tag type="info" effect="dark">{{ row.docker_reward }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="deadline" label="截止时间" width="160">
        <template #default="{ row }">
          {{ formatDeadline(row.deadline) }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="row.status === 'open' ? 'success' : 'info'" size="small">
            {{ row.status === 'open' ? '开放' : '已结束' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="300" align="center">
        <template #default="{ row }">
          <el-button 
            v-if="row.status === 'open' " 
            size="small" 
            type="primary"
            @click="openSubmitDialog(row)"
          >
            提交方案
          </el-button>
          <el-button 
            v-if="row.status === 'open' && row.issuer_id === props.conversationId" 
            size="small" 
            type="warning"
            @click="closeBounty(row)"
            class="ml-2"
          >
            结束任务并结算
          </el-button>
          <el-button 
            v-else 
            size="small" 
            @click="viewSubmissions(row.id)"
          >
            查看
          </el-button>
          <el-button 
            v-if="row.status === 'completed' && row.issuer_id === props.conversationId" 
            size="small" 
            type="success"
            @click="handleCurateSkill(row.id)"
            class="ml-2"
          >
            整理Skill
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 结算报告 -->
    <el-card v-if="settlementReport" class="settlement-report" style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <span>📊 结算报告</span>
        </div>
      </template>
      <el-table :data="settlementReport.evaluation_results || []" stripe size="small">
        <el-table-column type="index" label="排名" width="60" />
        <el-table-column prop="agent_id" label="节点" width="150" />
        <el-table-column prop="score" label="评分" width="100">
          <template #default="{ row }">
            <el-tag :type="scoreTagType(row.score)">{{ row.score?.toFixed(1) || '0.0' }}分</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="reward_amount" label="获得奖励" width="120" align="center">
          <template #default="{ row }">
            {{ row.reward_amount || 0 }} Token
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="评分理由" min-width="200" show-overflow-tooltip />
      </el-table>

      <div v-if="settlementReport.curation_results" style="margin-top: 16px;">
        <el-alert type="success" :closable="false" show-icon>
          <template #title>
            🎉 已自动沉淀 Skill：{{ settlementReport.curation_results.doc_id }}
          </template>
          <el-button size="small" type="primary" @click="viewSkill(settlementReport.curation_results.doc_id)" style="margin-top: 8px;">
            查看 Skill 详情
          </el-button>
        </el-alert>
      </div>
    </el-card>

    <div v-if="bounties.length === 0 && !loading" class="text-center py-8 text-gray-400">
      <el-icon size="48" class="mb-2"><Files /></el-icon>
      <p>暂无悬赏任务</p>
    </div>

    <el-dialog v-model="showCreateDialog" title="发布悬赏" width="500px">
      <el-form :model="newBounty" label-width="80px">
        <el-form-item label="标题">
          <el-input v-model="newBounty.title" placeholder="请输入悬赏标题"></el-input>
        </el-form-item>
        <el-form-item label="描述">
          <el-input 
            type="textarea" 
            v-model="newBounty.description" 
            :rows="3"
            placeholder="请详细描述问题或任务"
          ></el-input>
        </el-form-item>
        <el-form-item label="奖励 Token">
          <el-input-number v-model="newBounty.reward_pool" :min="1" :max="10000"></el-input-number>
        </el-form-item>
        <el-form-item label="Docker 奖励">
          <el-input-number v-model="newBounty.docker_reward" :min="0" :max="1000"></el-input-number>
        </el-form-item>
        <el-form-item label="截止时间">
          <el-date-picker 
            v-model="newBounty.deadline" 
            type="datetime" 
            placeholder="选择截止时间"
            style="width: 100%"
          ></el-date-picker>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createBounty" :loading="submitting">发布</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showSubmitDialog" title="提交方案" width="500px">
      <el-form :model="submission" label-width="100px">
        <el-form-item label="悬赏标题">
          <span class="text-gray-700">{{ currentBounty?.title }}</span>
        </el-form-item>
        <el-form-item label="方案内容">
          <el-input 
            type="textarea" 
            v-model="submission.content" 
            :rows="4"
            placeholder="请详细描述您的解决方案"
          ></el-input>
        </el-form-item>
        <el-form-item label="Skill 代码">
          <el-input 
            type="textarea" 
            v-model="submission.skill_code" 
            :rows="3"
            placeholder="如果有可执行的 Skill 代码，请粘贴在此（可选）"
          ></el-input>
        </el-form-item>
        <el-form-item label="消耗 Token">
          <el-input-number v-model="submission.cost_tokens" :min="0" :max="1000"></el-input-number>
          <div class="text-xs text-gray-400 mt-1">参与悬赏需要消耗的 Token（不退还）</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSubmitDialog = false">取消</el-button>
        <el-button type="primary" @click="openAIDialog" :disabled="!currentBounty">
          <el-icon class="mr-1"><ChatLineSquare /></el-icon>
          AI 辅助
        </el-button>
        <el-button type="primary" @click="submitSolution" :loading="submitting">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showAIDialog" title="AI 辅助填充" width="600px">
      <div class="ai-assist-container">
        <div class="ai-chat-history" ref="chatHistory">
          <div v-for="(msg, index) in aiChatHistory" :key="index" :class="['ai-message', msg.role]">
            <div class="message-role">{{ msg.role === 'user' ? '我' : 'AI' }}:</div>
            <div class="message-content">{{ msg.content }}</div>
          </div>
        </div>
        <div class="ai-input-container">
          <el-input
            v-model="aiUserInput"
            placeholder="输入您的需求，AI 会帮助您生成解决方案..."
            @keyup.enter="sendAIMessage"
            :disabled="aiLoading"
          >
            <template #append>
              <el-button @click="sendAIMessage" :loading="aiLoading">
                <el-icon><Promotion /></el-icon>
              </el-button>
            </template>
          </el-input>
        </div>
      </div>
      <template #footer>
        <el-button @click="showAIDialog = false">取消</el-button>
        <el-button type="primary" @click="applyAISuggestion" :disabled="!aiSuggestion">
          应用建议
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showSubmissionsDialog" title="方案列表" width="700px">
      <el-table :data="submissions" stripe>
        <el-table-column prop="content" label="方案内容" min-width="200" show-overflow-tooltip></el-table-column>
        <el-table-column prop="agent_id" label="提交者" width="120"></el-table-column>
        <el-table-column prop="cost_tokens" label="消耗" width="80" align="center"></el-table-column>
        <el-table-column prop="score" label="评分" width="80" align="center">
          <template #default="{ row }">
            <span v-if="row.score !== null && row.score !== undefined">{{ row.score.toFixed(2) }}</span>
            <span v-else class="text-gray-400">-</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="submissions.length === 0" class="text-center py-8 text-gray-400">
      暂无提交
    </div>
    </el-dialog>

    <!-- 通知弹窗 -->
    <el-drawer v-model="showNotificationsDialog" title="任务通知" size="400px">
      <el-list>
        <el-list-item v-for="notification in notifications" :key="notification.id">
          <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
            <div>
              <div style="font-weight: bold;">{{ notification.type === 'bounty' ? '新悬赏任务' : '通知' }}</div>
              <div style="color: #666; font-size: 12px;">
                悬赏 ID: {{ notification.bounty_id }}
              </div>
              <div style="color: #999; font-size: 10px;">
                {{ formatDate(notification.created_at) }}
              </div>
            </div>
            <div v-if="notification.status === 'pending'">
              <el-button size="small" type="primary" @click="acceptNotification(notification)">
                接受任务
              </el-button>
            </div>
            <div v-else>
              <el-tag size="small" :type="notification.status === 'processing' ? 'warning' : 'success'">
                {{ notification.status }}
              </el-tag>
            </div>
          </div>
        </el-list-item>
        <el-empty v-if="notifications.length === 0" description="暂无通知" />
      </el-list>
    </el-drawer>

    <!-- 邻居反馈排行榜 -->
    <el-card v-if="currentBounty && rankedSubmissions.length > 0" class="submission-rank" style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <span>🏆 邻居节点反馈排行榜</span>
          <el-tag type="success" size="small">已评分 {{ rankedSubmissions.length }} 个</el-tag>
        </div>
      </template>
      <el-table :data="rankedSubmissions" stripe size="small">
        <el-table-column type="index" label="排名" width="60" align="center">
          <template #default="{ $index }">
            <el-tag :type="$index === 0 ? 'warning' : ''" effect="dark">
              {{ $index + 1 }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="agent_id" label="节点名称" width="150"></el-table-column>
        <el-table-column prop="score" label="评分" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="scoreTagType(row.score)" effect="dark">{{ row.score }}分</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="score_reason" label="评分理由" show-overflow-tooltip></el-table-column>
        <el-table-column label="操作" width="140" align="center">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="openSkillEditor(row)">
              基于此项整理 Skill
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Skill 编辑器 -->
    <SkillEditor
      ref="skillEditorRef"
      :bounty-id="currentBounty?.id"
      :issuer-id="props.conversationId"
      :submission-id="selectedSubmissionId"
      @saved="loadBounties"
    />

    <!-- Skill 详情弹窗 -->
    <SkillViewer
      v-model="showSkillDialog"
      :skill="currentSkill"
      :export-path="currentSkillExportPath"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, computed, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Bell, Files, Plus, ChatLineSquare, Promotion, Refresh } from '@element-plus/icons-vue'
import { listBounties, createBounty as apiCreateBounty, submitSolution as apiSubmitSolution, getBountySubmissions, getSkill } from '../api/agentBff.js'
import request from '../api/agentBff.js'
import SkillEditor from './SkillEditor.vue'
import SkillViewer from './SkillViewer.vue'

const props = defineProps({
  conversationId: {
    type: String,
    required: true
  }
})

const bounties = ref([])
const loading = ref(false)
const showCreateDialog = ref(false)
const showSubmitDialog = ref(false)
const showSubmissionsDialog = ref(false)
const showNotificationsDialog = ref(false)
const submitting = ref(false)
const currentBounty = ref(null)
const submissions = ref([])
const notifications = ref([])
const unreadNotifications = ref([])
const neighbors = ref([])
const skillEditorRef = ref(null)
const selectedSubmissionId = ref(null)

let notificationInterval = null

const newBounty = ref({
  title: '',
  description: '',
  reward_pool: 100,
  docker_reward: 0,
  deadline: ''
})

const submission = ref({
  content: '',
  skill_code: '',
  cost_tokens: 0,
  agent_id: ''
})

const showAIDialog = ref(false)
const aiUserInput = ref('')
const aiChatHistory = ref([])
const aiLoading = ref(false)
const aiSuggestion = ref(null)

const rankedSubmissions = computed(() => {
  return submissions.value
    .filter(s => s.score !== null && s.score !== undefined)
    .sort((a, b) => (b.score || 0) - (a.score || 0))
})

const settlementReport = ref(null)
const showSkillDialog = ref(false)
const currentSkill = ref(null)
const currentSkillExportPath = ref('')

async function fetchBounties() {
  loading.value = true
  try {
    console.log('开始获取悬赏列表...')
    const res = await listBounties()
    console.log('获取悬赏列表响应:', res)
    
    if (!res || !res.data) {
      console.error('响应格式错误:', res)
      ElMessage.error('获取数据失败：响应格式错误')
      bounties.value = []
      return
    }
    
    bounties.value = res.data.bounties || []
    console.log('获取到的悬赏数量:', bounties.value.length)
  } catch (err) {
    console.error('获取悬赏列表失败:', err)
    console.error('错误详情:', err.response?.data || err.message)
    ElMessage.error('获取悬赏列表失败：' + (err.response?.data?.detail || err.message || '网络错误'))
    bounties.value = []
  } finally {
    loading.value = false
  }
}

async function fetchNotifications() {
  try {
    const res = await request.get(`/notifications/${props.conversationId}`)
    const newNotifications = res.data.notifications || []

    // 检查是否有任务完成
    for (const n of newNotifications) {
      if (n.status === 'completed') {
        const wasCompleted = notifications.value.find(old => old.id === n.id && old.status === 'completed')
        if (!wasCompleted) {
          ElMessage.success(`任务已完成！悬赏 ID: ${n.bounty_id.substring(0, 8)}...`)
        }
      }
    }

    notifications.value = newNotifications
    unreadNotifications.value = notifications.value.filter(n => n.status === 'pending')
  } catch (err) {
    console.error('获取通知失败:', err)
  }
}

async function fetchNeighbors() {
  try {
    const res = await request.get(`/node-relations/${props.conversationId}/neighbors`)
    neighbors.value = res.data.neighbors || []
  } catch (err) {
    console.error('获取邻居失败:', err)
    ElMessage.error('获取邻居列表失败')
  }
}

async function acceptNotification(notification) {
  try {
    await request.post(`/notifications/${notification.id}/process`)
    
    const bountyRes = await request.get(`/bounties/${notification.bounty_id}`)
    const bounty = bountyRes.data
    
    await request.post(`/bounties/${notification.bounty_id}/submit`, {
      agent_id: props.conversationId,
      content: `自动接受任务：${bounty?.title || '未知任务'}`,
      skill_code: '',
      cost_tokens: 0
    })
    
    ElMessage.success('已接受任务并提交方案')
    await fetchNotifications()
    await fetchBounties()
  } catch (err) {
    console.error('接受任务失败:', err)
    ElMessage.error('接受任务失败')
  }
}

async function createBounty() {
  if (!newBounty.value.title || !newBounty.value.description || !newBounty.value.deadline) {
    ElMessage.warning('请填写完整信息')
    return
  }
  submitting.value = true
  try {
    await apiCreateBounty({
      ...newBounty.value,
      deadline: newBounty.value.deadline.toISOString(),
      issuer_id: props.conversationId
    })
    ElMessage.success('悬赏发布成功')
    showCreateDialog.value = false
    newBounty.value = { title: '', description: '', reward_pool: 100, deadline: '' }
    await fetchBounties()
  } catch (err) {
    console.error('发布悬赏失败:', err)
    ElMessage.error('发布失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    submitting.value = false
  }
}

function openSubmitDialog(bounty) {
  currentBounty.value = bounty
  submission.value = { content: '', skill_code: '', cost_tokens: 0 }
  showSubmitDialog.value = true
}

async function submitSolution() {
  if (!submission.value.content) {
    ElMessage.warning('请填写方案内容')
    return
  }
  submitting.value = true
  try {
    await apiSubmitSolution(currentBounty.value.id, {
      ...submission.value,
      agent_id: props.conversationId
    })
    ElMessage.success('方案已提交')
    showSubmitDialog.value = false
  } catch (err) {
    console.error('提交方案失败:', err)
    ElMessage.error('提交失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    submitting.value = false
  }
}

async function viewSubmissions(bountyId) {
  try {
    const res = await getBountySubmissions(bountyId)
    submissions.value = res.data.submissions || []
    showSubmissionsDialog.value = true
  } catch (err) {
    console.error('获取方案列表失败:', err)
    ElMessage.error('获取方案列表失败')
  }
}

async function closeBounty(bounty) {
  try {
    await ElMessageBox.confirm(
      `确定要结束"${bounty.title}"吗？结束后将进行结算并发放奖励。`,
      '确认结束并结算',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    submitting.value = true
    const res = await request.post(`/bounties/${bounty.id}/close`, {
      issuer_id: props.conversationId
    })
    settlementReport.value = res.data
    ElMessage.success('任务已结束，奖励已发放！')

    if (res.data.curation_results?.doc_id) {
      ElMessage.info('已自动沉淀 Skill')
    }

    await fetchBounties()
  } catch (err) {
    if (err !== 'cancel') {
      console.error('结束任务失败:', err)
      ElMessage.error('结束任务失败: ' + (err.response?.data?.detail || err.message))
    }
  } finally {
    submitting.value = false
  }
}

async function viewSkill(skillId) {
  try {
    const res = await getSkill(skillId)
    currentSkill.value = res.data
    if (settlementReport.value?.curation_results?.doc_id === skillId) {
      currentSkillExportPath.value = settlementReport.value.curation_results.export_path || ''
    } else {
      currentSkillExportPath.value = ''
    }
    showSkillDialog.value = true
  } catch (err) {
    ElMessage.error('获取 Skill 失败')
  }
}

function openAIDialog() {
  if (!currentBounty.value) return
  
  aiChatHistory.value = []
  aiUserInput.value = ''
  aiSuggestion.value = null
  showAIDialog.value = true
  
  setTimeout(() => {
    aiUserInput.value = `我需要为"${currentBounty.value.title}"生成解决方案`
    sendAIMessage()
  }, 500)
}

async function sendAIMessage() {
  if (!aiUserInput.value.trim() || !currentBounty.value) return
  
  const userMessage = aiUserInput.value.trim()
  aiChatHistory.value.push({ role: 'user', content: userMessage })
  aiUserInput.value = ''
  aiLoading.value = true
  
  try {
    const res = await request.post(`/bounties/${currentBounty.value.id}/ai-assist`, {
      user_input: userMessage,
      conversation_history: aiChatHistory.value
    })
    
    const aiResponse = res.data
    aiChatHistory.value.push({ role: 'assistant', content: aiResponse.assistant_response })
    aiSuggestion.value = aiResponse
    
    setTimeout(() => {
      const chatHistory = document.querySelector('.ai-chat-history')
      if (chatHistory) {
        chatHistory.scrollTop = chatHistory.scrollHeight
      }
    }, 100)
  } catch (err) {
    console.error('AI 辅助失败:', err)
    ElMessage.error('AI 辅助失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    aiLoading.value = false
  }
}

function applyAISuggestion() {
  if (!aiSuggestion.value) return
  
  console.log('Applying AI suggestion:', aiSuggestion.value)
  
  submission.value = {
    ...submission.value,
    content: aiSuggestion.value.content || submission.value.content,
    skill_code: aiSuggestion.value.skill_code || submission.value.skill_code,
    cost_tokens: aiSuggestion.value.cost_tokens || submission.value.cost_tokens
  }
  
  console.log('Updated submission:', submission.value)
  
  showAIDialog.value = false
  ElMessage.success('已应用 AI 建议，内容已填充到表单')
}

async function handleCurateSkill(bountyId) {
  try {
    const res = await getBountySubmissions(bountyId)
    const subs = res.data.submissions || []
    if (subs.length === 0) {
      ElMessage.warning('暂无邻居节点的反馈内容')
      return
    }

    const submissionId = subs[0].id
    skillEditorRef.value?.openDialog()
  } catch (err) {
    console.error('整理 Skill 失败:', err)
    ElMessage.error('整理失败: ' + (err.response?.data?.detail || err.message))
  }
}

function formatDeadline(deadline) {
  if (!deadline) return '-'
  const date = new Date(deadline)
  return date.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

function scoreTagType(score) {
  if (score === null || score === undefined) return 'info'
  if (score >= 80) return 'success'
  if (score >= 60) return 'warning'
  return 'danger'
}

function openSkillEditor(submission) {
  selectedSubmissionId.value = submission.id
  skillEditorRef.value?.openDialog()
}

onMounted(() => {
  fetchBounties()
  fetchNotifications()
  fetchNeighbors()
  notificationInterval = setInterval(fetchNotifications, 5000)
})

onUnmounted(() => {
  if (notificationInterval) {
    clearInterval(notificationInterval)
  }
})
</script>

<style scoped>
.bounty-market {
  padding: 20px;
}

.ai-assist-container {
  height: 400px;
  display: flex;
  flex-direction: column;
}

.ai-chat-history {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  margin-bottom: 10px;
  background-color: #f9f9f9;
}

.ai-message {
  margin-bottom: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  max-width: 80%;
}

.ai-message.user {
  background-color: #e6f7ff;
  align-self: flex-end;
  margin-left: auto;
}

.ai-message.assistant {
  background-color: #f0f0f0;
  align-self: flex-start;
}

.message-role {
  font-size: 12px;
  font-weight: bold;
  margin-bottom: 4px;
  color: #666;
}

.message-content {
  font-size: 14px;
  line-height: 1.4;
}

.ai-input-container {
  margin-top: 10px;
}

.mt-1 {
  margin-top: 4px;
}

.ml-2 {
  margin-left: 8px;
}

.text-xs {
  font-size: 12px;
}

.text-gray-400 {
  color: #999;
}

.neighbor-list .neighbor-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.neighbor-list .neighbor-id {
  font-family: monospace;
  font-size: 12px;
  color: #666;
}

.text-gray-700 {
  color: #333;
}
</style>
