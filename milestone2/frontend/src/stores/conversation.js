import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useConvStore = defineStore('conversation', () => {
  const activeCount = ref(0)
  const currentConvId = ref('')
  const convList = ref([])
  const trajectory = ref([])
  const chatList = ref([])
  const loading = ref(false)

  const healthOk = computed(() => activeCount.value >= 0)

  function setActiveCount(num) {
    activeCount.value = Math.min(num, 10)
  }

  function setCurrentConv(id) {
    currentConvId.value = id
  }

  function setConvList(list) {
    convList.value = list
  }

  function addConv(conv) {
    convList.value.push(conv)
  }

  function removeConv(id) {
    const idx = convList.value.findIndex(c => c.conversation_id === id)
    if (idx !== -1) convList.value.splice(idx, 1)
  }

  function setTrajectory(data) {
    trajectory.value = data
  }

  function setChatList(data) {
    chatList.value = data
  }

  function appendChat(chat) {
    chatList.value.push(chat)
  }

  function setLoading(val) {
    loading.value = val
  }

  return {
    activeCount,
    currentConvId,
    convList,
    trajectory,
    chatList,
    loading,
    healthOk,
    setActiveCount,
    setCurrentConv,
    setConvList,
    addConv,
    removeConv,
    setTrajectory,
    setChatList,
    appendChat,
    setLoading
  }
})
