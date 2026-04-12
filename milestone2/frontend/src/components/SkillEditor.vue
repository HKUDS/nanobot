<template>
  <div class="skill-editor">
    <el-dialog v-model="showDialog" :title="dialogTitle" width="900px">

      <!-- 来源信息（固定为邻居节点的 submission） -->
      <el-alert type="info" :closable="false" style="margin-bottom: 15px;" v-if="selectedSubmissionId">
        <template #default>
          <div style="display: flex; align-items: center; gap: 10px;">
            <span>📋 当前参考的反馈来源：</span>
            <el-tag type="success" effect="dark">{{ selectedNeighborName }}</el-tag>
            <span v-if="selectedScore !== null" style="margin-left: 10px;">评分：</span>
            <el-tag v-if="selectedScore !== null" :type="scoreTagType(selectedScore)" effect="dark">
              {{ selectedScore }}分
            </el-tag>
          </div>
        </template>
      </el-alert>

      <!-- 邻居节点反馈内容（只读） -->
      <el-form-item label="邻居节点反馈内容">
        <el-input type="textarea" :value="neighborContent" readonly rows="5"
          placeholder="邻居节点执行任务后的反馈内容..." />
      </el-form-item>

      <!-- 技能名称 -->
      <el-form-item label="技能名称" required>
        <el-input v-model="skillForm.name" placeholder="例如：图片处理、邮件发送、数据分析" />
      </el-form-item>

      <!-- 能力描述 -->
      <el-form-item label="能力描述" required>
        <el-input type="textarea" v-model="skillForm.capability" rows="3"
          placeholder="描述这个技能能做什么，例如：能够识别图片中的文字、自动裁剪白边、压缩图片大小" />
      </el-form-item>

      <!-- 使用方法 -->
      <el-form-item label="使用方法">
        <el-input type="textarea" v-model="skillForm.usage" rows="4"
          placeholder="描述如何使用这个技能，例如：1. 调用 process_image() 函数&#10;2. 传入图片路径和参数&#10;3. 获取处理结果" />
      </el-form-item>

      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button @click="previewSkill">预览</el-button>
        <el-button type="primary" @click="saveSkill">保存到公共知识库</el-button>
      </template>
    </el-dialog>

    <!-- 预览弹窗 -->
    <el-dialog v-model="showPreview" title="Skill 预览" width="800px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="技能名称">{{ skillForm.name }}</el-descriptions-item>
        <el-descriptions-item label="能力描述">{{ skillForm.capability }}</el-descriptions-item>
        <el-descriptions-item label="使用方法">{{ skillForm.usage }}</el-descriptions-item>
        <el-descriptions-item label="来源">邻居节点反馈 (ID: {{ selectedSubmissionId }})</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import request, { getBountySubmissions, curateSkill } from '../api/agentBff.js'

const props = defineProps({
  bountyId: String,
  issuerId: String,
  submissionId: String
})

const emit = defineEmits(['saved'])

const showDialog = ref(false)
const showPreview = ref(false)
const neighborContent = ref('')
const selectedSubmissionId = ref('')
const selectedNeighborName = ref('')
const selectedScore = ref(null)

const dialogTitle = computed(() => {
  return selectedSubmissionId.value 
    ? `整理 Skill（基于: ${selectedNeighborName.value || '邻居反馈'}）` 
    : '整理 Skill'
})

const skillForm = reactive({
  name: '',
  capability: '',
  usage: ''
})

function scoreTagType(score) {
  if (score === null || score === undefined) return 'info'
  if (score >= 80) return 'success'
  if (score >= 60) return 'warning'
  return 'danger'
}

async function openDialog() {
  showDialog.value = true

  if (props.submissionId) {
    selectedSubmissionId.value = props.submissionId

    try {
      const res = await getBountySubmissions(props.bountyId)
      const submissions = res.data.submissions || []

      const submission = submissions.find(s => s.id === props.submissionId)
      if (submission) {
        neighborContent.value = submission.content || '（无内容）'
        selectedNeighborName.value = submission.agent_id || '邻居节点'
        selectedScore.value = submission.score
      } else {
        neighborContent.value = '（未找到反馈内容）'
        selectedNeighborName.value = '未知节点'
        selectedScore.value = null
      }
    } catch (e) {
      console.error('获取 submission 详情失败:', e)
      neighborContent.value = '（加载失败）'
      selectedNeighborName.value = '未知节点'
      selectedScore.value = null
    }
  } else {
    selectedSubmissionId.value = ''
    neighborContent.value = '（暂无邻居节点反馈）'
    selectedNeighborName.value = ''
    selectedScore.value = null
  }

  skillForm.name = ''
  skillForm.capability = ''
  skillForm.usage = ''
}

function previewSkill() {
  if (!skillForm.name || !skillForm.capability) {
    ElMessage.error('请填写技能名称和能力描述')
    return
  }
  showPreview.value = true
}

async function saveSkill() {
  if (!skillForm.name || !skillForm.capability) {
    ElMessage.error('请填写技能名称和能力描述')
    return
  }

  try {
    const res = await curateSkill(props.bountyId, {
      issuer_id: props.issuerId,
      submission_id: selectedSubmissionId.value || props.submissionId,
      name: skillForm.name,
      capability: skillForm.capability,
      usage: skillForm.usage
    })

    if (res.status === 200 || res.status === 201) {
      ElMessage.success('Skill 已保存到公共知识库')
      showDialog.value = false
      emit('saved')
    } else {
      const errData = await res.json()
      ElMessage.error('保存失败: ' + (errData.detail || '未知错误'))
    }
  } catch (e) {
    console.error('保存 Skill 失败:', e)
    ElMessage.error('保存失败: ' + e.message)
  }
}

defineExpose({ openDialog })
</script>