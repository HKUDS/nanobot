import axios from 'axios'

const request = axios.create({
  baseURL: 'http://localhost:8000',
  timeout: 60000
})

export const healthCheck = () => request.get('/health')

export const listConversations = () => request.get('/conversations')

export const createConversation = (data) => request.post('/conversations', data)

export const getConversation = (id) => request.get(`/conversations/${id}`)

export const sendMessage = (conversationId, data) =>
  request.post(`/conversations/${conversationId}/messages`, data)

export const getTrajectory = (conversationId) =>
  request.get(`/conversations/${conversationId}/trajectory`)

export const getHistory = (conversationId) =>
  request.get(`/conversations/${conversationId}/history`)

export const forkConversation = (conversationId, data) =>
  request.post(`/conversations/${conversationId}/fork`, data)

export const mergeConversation = (data) =>
  request.post('/conversations/merge', data)

export const getConversationsStatus = () => request.get('/conversations/status')

export const deleteConversation = (id) =>
  request.delete(`/conversations/${id}`)

export const listBounties = () => request.get('/bounties')

export const getSkill = (skillId) => request.get(`/public-skills/${skillId}`)

export const createBounty = (data) => request.post('/bounties', data)

export const submitSolution = (bountyId, data) =>
  request.post(`/bounties/${bountyId}/submit`, data)

export const getBountySubmissions = (bountyId) =>
  request.get(`/bounties/${bountyId}/submissions`)

export const evaluateBounty = (bountyId, data) =>
  request.post(`/bounties/${bountyId}/evaluate`, data)

export const curateSkill = (bountyId, data) =>
  request.post(`/bounties/${bountyId}/curate-skill`, data)

export const getWalletBalance = (convId) =>
  request.get(`/wallet/${convId}/balance`)

export const transferTokens = (params) =>
  request.post('/wallet/transfer', params)

export const searchKnowledge = (query, top_k = 5) =>
  request.post('/public-space/search', { query, top_k })

export const uploadKnowledge = (data) =>
  request.post('/public-space/upload', data)

export const matchReflex = (state, threshold = 0.85) =>
  request.post('/reflex/match', { state, threshold })

export const learnReflex = (data) =>
  request.post('/reflex/learn', data)

export const listReflexes = () => request.get('/reflex/list')

export const addFriend = (agentA, agentB) =>
  request.post('/social/friend', { agent_a: agentA, agent_b: agentB })

export const getFriends = (agentId) =>
  request.get(`/social/friends/${agentId}`)

export const getFriendsWithTrust = (agentId) =>
  request.get(`/social/friends/${agentId}/with-trust`)

export const updateTrust = (agentA, agentB, delta) =>
  request.post('/social/trust', { agent_a: agentA, agent_b: agentB, delta })

export default request
