import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

export interface ApiResponse<T = unknown> {
  success: boolean
  message?: string
  data: T
  total?: number
  pagination?: {
    total: number
    page: number
    page_size: number
  }
}

export const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error?.response?.data?.message || error.message || '请求失败'
    ElMessage.error(message)
    if (error?.response?.status === 401) {
      useAuthStore().logout()
    }
    return Promise.reject(error)
  },
)

export async function apiGet<T>(url: string, params?: Record<string, unknown>) {
  return http.get<unknown, ApiResponse<T>>(url, { params })
}

export async function apiPost<T>(url: string, data?: unknown) {
  return http.post<unknown, ApiResponse<T>>(url, data)
}

export async function apiPut<T>(url: string, data?: unknown) {
  return http.put<unknown, ApiResponse<T>>(url, data)
}

export async function apiDelete<T>(url: string, data?: unknown) {
  return http.delete<unknown, ApiResponse<T>>(url, { data })
}
