<template>
  <el-dialog v-model="visible" title="Skill 详情" width="700px">
    <el-descriptions :column="1" border v-if="skill">
      <el-descriptions-item label="技能名称">{{ skill.title }}</el-descriptions-item>
      <el-descriptions-item label="能力描述">{{ skill.content || '（未填写）' }}</el-descriptions-item>
      <el-descriptions-item label="使用方法">{{ skill.usage || '（未填写）' }}</el-descriptions-item>
      <el-descriptions-item label="Skill 代码">
        <pre class="skill-code" v-if="skill.skill_code">{{ skill.skill_code }}</pre>
        <span v-else class="text-gray-400">（无）</span>
      </el-descriptions-item>
      <el-descriptions-item label="导出路径">
        <code v-if="exportPath">{{ exportPath }}</code>
        <span v-else class="text-gray-400">（未导出或导出失败）</span>
      </el-descriptions-item>
      <el-descriptions-item label="创建时间">{{ formatDate(skill.created_at) }}</el-descriptions-item>
    </el-descriptions>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false
  },
  skill: {
    type: Object,
    default: null
  },
  exportPath: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue'])

const visible = ref(props.modelValue)

watch(() => props.modelValue, (val) => {
  visible.value = val
})

watch(visible, (val) => {
  emit('update:modelValue', val)
})

function formatDate(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}
</script>

<style scoped>
.skill-code {
  background-color: #f5f5f5;
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 12px;
  max-height: 300px;
  overflow-y: auto;
}

.text-gray-400 {
  color: #999;
}
</style>
