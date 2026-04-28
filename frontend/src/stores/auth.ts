import { defineStore } from 'pinia'
import { apiPost } from '@/api/http'

export interface AdminUser {
  id: number
  username: string
  nickname?: string
  role?: string
  is_superadmin?: number
}

interface LoginPayload {
  username: string
  password: string
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('admin_token') || '',
    user: JSON.parse(localStorage.getItem('admin_user') || 'null') as AdminUser | null,
  }),
  actions: {
    async login(payload: LoginPayload) {
      const res = await apiPost<{ token: string; user: AdminUser }>('/auth/login', payload)
      this.token = res.data.token
      this.user = res.data.user
      localStorage.setItem('admin_token', this.token)
      localStorage.setItem('admin_user', JSON.stringify(this.user))
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('admin_token')
      localStorage.removeItem('admin_user')
      window.location.href = '/login'
    },
  },
})
