<template>
  <el-container class="shell">
    <el-aside width="176px" class="sidebar">
      <div class="brand">
        <div class="brand-mark">剧</div>
        <strong>快手短剧精灵系统</strong>
      </div>

      <el-scrollbar class="sidebar-scroll">
        <el-menu
          router
          :default-active="$route.path"
          :default-openeds="openMenus"
          background-color="#061b2e"
          text-color="#d7e5f5"
          active-text-color="#2f8dfb"
        >
          <el-sub-menu v-for="group in menuItems" :key="group.path" :index="group.path">
            <template #title>
              <span class="menu-title">{{ group.title }}</span>
            </template>
            <el-menu-item v-for="item in group.children" :key="item.path" :index="item.path">
              {{ item.title }}
            </el-menu-item>
          </el-sub-menu>
        </el-menu>
      </el-scrollbar>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div class="topbar-title">{{ $route.meta.title || '后台管理' }}</div>
        <div class="topbar-right">
          <el-tag effect="plain" type="success" size="small">服务正常</el-tag>
          <span class="clock">{{ clockText }}</span>
          <span class="admin-avatar">{{ userInitial }}</span>
          <span class="admin-name">{{ auth.user?.nickname || auth.user?.username || '系统管理员' }}</span>
          <el-tag effect="plain" type="danger" size="small">超级管理员</el-tag>
          <el-dropdown trigger="click">
            <span class="dropdown-trigger">⌄</span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="auth.logout()">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>

    <el-dialog v-model="noticeVisible" width="520px" class="notice-dialog" :show-close="false">
      <template #header>
        <div class="notice-title">{{ activeNotice.title }}</div>
        <div class="notice-time">{{ activeNotice.created_at || clockText }}</div>
      </template>
      <div class="notice-content">
        {{ activeNotice.content || '暂无公告内容' }}
      </div>
      <div class="notice-pager">{{ noticeIndex + 1 }} / {{ notices.length || 1 }}</div>
      <template #footer>
        <el-button @click="hideToday">今日不再显示</el-button>
        <el-button type="primary" @click="nextNotice">我知道了</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { menuItems } from '@/router'
import { apiGet } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

interface Notice {
  id?: number
  title: string
  content?: string
  created_at?: string
}

const auth = useAuthStore()
const openMenus = menuItems.map((item) => item.path)
const clockText = ref('')
const notices = ref<Notice[]>([])
const noticeIndex = ref(0)
const noticeVisible = ref(false)
let timer: number | undefined

const userInitial = computed(() => {
  const name = auth.user?.nickname || auth.user?.username || '系'
  return name.slice(0, 1)
})

const activeNotice = computed<Notice>(() => {
  return notices.value[noticeIndex.value] || {
    title: '2月份星火计划收益结算通知',
    content: '@所有人，星火计划收益结算通知请以系统公告为准。',
  }
})

function todayKey() {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  return `notice_hidden_${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`
}

function refreshClock() {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  clockText.value = `${now.getFullYear()}/${pad(now.getMonth() + 1)}/${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
}

async function loadNotices() {
  if (localStorage.getItem(todayKey()) === '1') return
  try {
    const res = await apiGet<any>('/announcements')
    const list = Array.isArray(res.data?.announcements) ? res.data.announcements : Array.isArray(res.data) ? res.data : []
    notices.value = list.filter((item: any) => item.is_enabled !== 0).map((item: any) => ({
      id: item.id,
      title: item.title || '系统公告',
      content: item.content || item.message || '',
      created_at: item.created_at,
    }))
  } catch {
    notices.value = []
  }
  noticeVisible.value = notices.value.length > 0
}

function nextNotice() {
  if (noticeIndex.value < notices.value.length - 1) {
    noticeIndex.value += 1
    return
  }
  noticeVisible.value = false
}

function hideToday() {
  localStorage.setItem(todayKey(), '1')
  noticeVisible.value = false
}

onMounted(() => {
  refreshClock()
  timer = window.setInterval(refreshClock, 1000)
  loadNotices()
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>
