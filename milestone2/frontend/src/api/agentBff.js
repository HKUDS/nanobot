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
  request.post('/merge', data)

export const deleteConversation = (id) =>
  request.delete(`/conversations/${id}`)

export default request
