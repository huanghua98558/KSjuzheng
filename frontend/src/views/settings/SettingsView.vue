<template>
  <el-card>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="个人信息" name="profile">
        <el-form class="profile-form" label-width="90px">
          <el-form-item label="账号">
            <el-input :model-value="auth.user?.username" disabled />
          </el-form-item>
          <el-form-item label="昵称">
            <el-input v-model="profile.nickname" placeholder="请输入昵称" />
          </el-form-item>
          <el-form-item label="邮箱">
            <el-input v-model="profile.email" placeholder="请输入邮箱" />
          </el-form-item>
          <el-form-item label="手机号">
            <el-input v-model="profile.phone" placeholder="请输入手机号" />
          </el-form-item>
          <el-form-item label="角色">
            <el-tag type="danger" effect="plain">{{ auth.user?.role || '超级管理员' }}</el-tag>
          </el-form-item>
          <el-form-item>
            <el-button type="primary">保存修改</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="操作日志" name="logs">
        <div class="filter-row">
          <el-input v-model="logFilters.action" placeholder="操作类型" class="filter-control" />
          <el-input v-model="logFilters.module" placeholder="模块" class="filter-control" />
          <el-date-picker v-model="logFilters.dateRange" type="daterange" start-placeholder="开始日期" end-placeholder="结束日期" />
          <el-button type="primary" @click="loadLogs">查询</el-button>
          <el-button @click="resetLogs">重置</el-button>
          <el-button type="danger">清空日志</el-button>
        </div>
        <el-table :data="logs" border stripe height="460">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="username" label="操作用户" width="130" />
          <el-table-column prop="action" label="操作类型" width="120" />
          <el-table-column prop="module" label="模块" width="120" />
          <el-table-column prop="target_type" label="目标" width="120" />
          <el-table-column prop="detail" label="详情" min-width="260" show-overflow-tooltip />
          <el-table-column prop="ip" label="IP" width="140" />
          <el-table-column prop="created_at" label="时间" width="180" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="基本设置" name="basic">
        <el-table :data="configRows" border stripe height="460">
          <el-table-column prop="key" label="配置项" width="220" />
          <el-table-column prop="value" label="配置值" min-width="280" show-overflow-tooltip />
          <el-table-column prop="description" label="说明" min-width="260" />
          <el-table-column prop="updated_at" label="更新时间" width="180" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="机构信息管理" name="organizations">
        <div class="toolbar">
          <span>机构信息管理</span>
          <el-button type="primary">添加机构</el-button>
        </div>
        <el-table :data="organizations" border stripe height="460">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="name" label="机构名称" width="180" />
          <el-table-column prop="org_code" label="机构代码" width="150" />
          <el-table-column prop="notes" label="描述" min-width="220" />
          <el-table-column prop="is_active" label="状态" width="100" />
          <el-table-column prop="updated_at" label="更新时间" width="180" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="公告管理" name="announcements">
        <div class="toolbar">
          <span>公告管理</span>
          <el-button type="primary">添加公告</el-button>
        </div>
        <el-table :data="announcements" border stripe height="460">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="title" label="公告标题" width="240" />
          <el-table-column prop="content" label="公告内容" min-width="320" show-overflow-tooltip />
          <el-table-column prop="level" label="级别" width="100" />
          <el-table-column prop="is_enabled" label="状态" width="100" />
          <el-table-column prop="created_at" label="创建时间" width="180" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="默认权限配置" name="permissions">
        <div class="toolbar">
          <span>角色：</span>
          <el-radio-group v-model="role" @change="loadPermissions">
            <el-radio-button label="operator">团长</el-radio-button>
            <el-radio-button label="captain">队长</el-radio-button>
            <el-radio-button label="normal_user">普通用户</el-radio-button>
          </el-radio-group>
          <el-button type="primary" :loading="saving" @click="savePermissions">保存配置</el-button>
        </div>

        <PermissionSection title="软件账号管理按钮权限" type="account_button" :items="meta.account_buttons" :state="state" @change="setPermission" />
        <PermissionSection title="用户管理按钮权限" type="user_mgmt_button" :items="meta.user_mgmt_buttons" :state="state" @change="setPermission" />
        <PermissionSection title="Web页面权限" type="web_page" :items="meta.web_pages" :state="state" @change="setPermission" />
        <PermissionSection title="客户端页面权限" type="client_page" :items="meta.client_pages" :state="state" @change="setPermission" />
      </el-tab-pane>

      <el-tab-pane label="关于系统" name="about">
        <el-descriptions border :column="2">
          <el-descriptions-item label="系统名称">快手短剧影视精灵系统</el-descriptions-item>
          <el-descriptions-item label="前端技术">Vue 3 + Vite + Element Plus</el-descriptions-item>
          <el-descriptions-item label="后端接口">FastAPI / MySQL huoshijie</el-descriptions-item>
          <el-descriptions-item label="源码目录">D:\KS184\ks-admin-vue</el-descriptions-item>
        </el-descriptions>
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, apiPut } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import PermissionSection from './components/PermissionSection.vue'

interface PermissionItem {
  key: string
  perm_key?: string
  name?: string
  label?: string
  is_allowed?: number
}

const auth = useAuthStore()
const activeTab = ref('permissions')
const role = ref('operator')
const saving = ref(false)
const logs = ref<any[]>([])
const configRows = ref<any[]>([])
const organizations = ref<any[]>([])
const announcements = ref<any[]>([])
const logFilters = reactive({ action: '', module: '', dateRange: null as any })
const profile = reactive({
  nickname: '',
  email: '',
  phone: '',
})
const state = reactive<Record<string, number>>({})
const meta = reactive({
  account_buttons: [] as PermissionItem[],
  user_mgmt_buttons: [] as PermissionItem[],
  web_pages: [] as PermissionItem[],
  client_pages: [] as PermissionItem[],
})

function stateKey(type: string, key: string) {
  return `${type}:${key}`
}

function setPermission(type: string, key: string, allowed: boolean) {
  state[stateKey(type, key)] = allowed ? 1 : 0
}

async function loadPermissions() {
  const res = await apiGet<any>(`/auth/role-default-permissions/${role.value}`)
  Object.assign(meta, res.data.meta)
  Object.keys(state).forEach((key) => delete state[key])
  for (const item of res.data.permissions || []) {
    state[stateKey(item.perm_type, item.perm_key)] = item.is_allowed ? 1 : 0
  }
}

async function loadLogs() {
  const res = await apiGet<any>('/auth/logs', {
    action: logFilters.action || undefined,
    module: logFilters.module || undefined,
  })
  logs.value = res.data.logs || []
}

function resetLogs() {
  logFilters.action = ''
  logFilters.module = ''
  logFilters.dateRange = null
  loadLogs()
}

async function loadSettingsData() {
  const [configRes, orgRes, announcementRes] = await Promise.all([
    apiGet<Record<string, any>>('/config'),
    apiGet<any[]>('/organizations'),
    apiGet<any>('/announcements'),
  ])
  configRows.value = Object.entries(configRes.data || {}).map(([key, value]) => ({ key, ...(value as any) }))
  organizations.value = Array.isArray(orgRes.data) ? orgRes.data : []
  announcements.value = announcementRes.data?.announcements || []
}

async function savePermissions() {
  saving.value = true
  try {
    const permissions = Object.entries(state).map(([compound, allowed]) => {
      const index = compound.indexOf(':')
      return {
        perm_type: compound.slice(0, index),
        perm_key: compound.slice(index + 1),
        is_allowed: allowed,
      }
    })
    await apiPut(`/auth/role-default-permissions/${role.value}`, { permissions })
    ElMessage.success('默认权限配置已保存')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  profile.nickname = auth.user?.nickname || ''
  profile.email = (auth.user as any)?.email || ''
  profile.phone = (auth.user as any)?.phone || ''
  loadPermissions()
  loadLogs()
  loadSettingsData()
})
</script>
