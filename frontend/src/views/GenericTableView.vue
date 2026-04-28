<template>
  <div class="page-stack">
    <div class="page-heading">
      <h2>{{ config.title }}</h2>
      <p>{{ config.subtitle || `${config.title}数据列表` }}</p>
    </div>

    <el-row v-if="config.statCards?.length" :gutter="16">
      <el-col v-for="card in config.statCards" :key="card.key" :span="6">
        <el-card class="metric-card">
          <div class="metric-inline">
            <div class="metric-icon" :style="{ background: card.color || '#2f8dfb' }">{{ card.icon || '数' }}</div>
            <div>
              <strong>{{ card.money ? `¥${numberValue(statValue(card.key))}` : displayValue(statValue(card.key)) }}</strong>
              <span>{{ card.label }}</span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="filter-card">
      <div class="filter-row">
        <template v-for="filter in config.filters" :key="filter.key">
          <el-date-picker
            v-if="filter.type === 'date'"
            v-model="filters[filter.key]"
            type="date"
            value-format="YYYY-MM-DD"
            :placeholder="filter.placeholder"
            class="filter-control"
          />
          <el-select
            v-else-if="filter.type === 'select'"
            v-model="filters[filter.key]"
            clearable
            filterable
            :placeholder="filter.placeholder"
            class="filter-control"
          >
            <el-option
              v-for="option in optionsFor(filter.source)"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-input
            v-else
            v-model="filters[filter.key]"
            clearable
            :placeholder="filter.placeholder"
            class="filter-control"
            @keyup.enter="loadData"
          />
        </template>
        <el-button
          v-for="action in config.actions"
          :key="action.label"
          :type="action.type"
          :loading="loading && action.label === '搜索'"
          @click="handleAction(action.label)"
        >
          {{ action.label }}
        </el-button>
      </div>
    </el-card>

    <el-card>
    <template #header>
      <div class="card-header">
        <span>{{ config.title }}</span>
        <div class="action-row">
          <el-tag type="info">共 {{ total }} 条</el-tag>
        </div>
      </div>
    </template>

    <el-table
      v-loading="loading"
      :data="rows"
      stripe
      height="calc(100vh - 320px)"
      class="data-table"
      @selection-change="selection = $event"
      @sort-change="handleSort"
    >
      <el-table-column type="selection" width="42" />
      <el-table-column
        v-for="column in columns"
        :key="column.key"
        :prop="column.key"
        :label="column.label"
        :width="column.width"
        :fixed="column.fixed"
        :sortable="column.sortable ? 'custom' : false"
        min-width="140"
        show-overflow-tooltip
      >
        <template #default="{ row, $index }">
          <span v-if="column.key === 'index'">{{ $index + 1 + (page - 1) * pageSize }}</span>
          <el-avatar v-else-if="column.image" :src="valueOf(row, column.key)" :size="34">{{ valueOf(row, column.key) ? '' : '-' }}</el-avatar>
          <el-link v-else-if="column.link && valueOf(row, column.key)" type="primary" :href="valueOf(row, column.key)" target="_blank">{{ valueOf(row, column.key) }}</el-link>
          <span v-else-if="column.money" class="money">¥{{ numberValue(valueOf(row, column.key)) }}</span>
          <el-tag v-else-if="column.tag" size="small" :type="tagType(valueOf(row, column.key))">{{ displayValue(valueOf(row, column.key)) }}</el-tag>
          <span v-else>{{ displayValue(valueOf(row, column.key)) }}</span>
        </template>
      </el-table-column>
      <el-table-column fixed="right" label="操作" :width="operationWidth">
        <template #default="{ row }">
          <el-button
            v-for="action in primaryRowActions"
            :key="action.label"
            link
            :type="action.type || 'primary'"
            size="small"
            @click="handleAction(action.label, row)"
          >
            {{ action.label }}
          </el-button>
          <el-dropdown v-if="moreRowActions.length" trigger="click" @command="(label: string) => handleAction(label, row)">
            <el-button link type="primary" size="small">更多</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="action in moreRowActions" :key="action.label" :command="action.label">
                  {{ action.label }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        background
        layout="total, sizes, prev, pager, next, jumper"
        :total="total"
        @current-change="loadData"
        @size-change="loadData"
      />
    </div>
  </el-card>

    <el-dialog v-model="dialog.visible" :title="dialog.title" :width="dialogWidth" destroy-on-close>
      <template v-if="dialog.mode === 'detail'">
        <el-descriptions border :column="2" class="detail-descriptions">
          <el-descriptions-item v-for="column in columns" :key="column.key" :label="column.label">
            <template v-if="column.image">
              <el-avatar :src="valueOf(dialog.row, column.key)" :size="42">{{ valueOf(dialog.row, column.key) ? '' : '-' }}</el-avatar>
            </template>
            <template v-else-if="column.link && valueOf(dialog.row, column.key)">
              <el-link type="primary" :href="valueOf(dialog.row, column.key)" target="_blank">{{ valueOf(dialog.row, column.key) }}</el-link>
            </template>
            <template v-else>{{ displayValue(valueOf(dialog.row, column.key)) }}</template>
          </el-descriptions-item>
        </el-descriptions>
      </template>

      <template v-else-if="dialog.mode === 'batch'">
        <el-alert :closable="false" type="info" show-icon>
          <template #title>
            当前已选择 {{ selection.length }} 条数据；该操作会按当前后台规则提交到真实接口。
          </template>
        </el-alert>
        <el-form class="dialog-form" label-width="120px">
          <el-form-item label="操作名称">
            <el-input v-model="dialog.title" disabled />
          </el-form-item>
          <el-form-item v-if="dialog.label.includes('分成')" label="分成比例">
            <el-input-number v-model="dialog.form.commission_rate" :min="0" :max="100" :precision="2" />
          </el-form-item>
          <el-form-item v-if="dialog.label.includes('机构')" label="选择机构">
            <el-select v-model="dialog.form.organization_id" filterable clearable placeholder="选择机构">
              <el-option v-for="option in selectOptions.organizations" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="dialog.label.includes('分配用户')" label="选择用户">
            <el-select v-model="dialog.form.owner_id" filterable clearable placeholder="选择用户">
              <el-option v-for="option in selectOptions.users" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="dialog.form.remark" type="textarea" :rows="3" placeholder="请输入备注" />
          </el-form-item>
        </el-form>
      </template>

      <template v-else>
        <el-form class="dialog-form" label-width="120px">
          <el-form-item v-for="field in dialogFields" :key="field.key" :label="field.label">
            <el-select
              v-if="field.type === 'select'"
              v-model="dialog.form[field.key]"
              filterable
              clearable
              :placeholder="field.placeholder"
            >
              <el-option v-for="option in optionsFor(field.source)" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
            <el-input-number
              v-else-if="field.type === 'number'"
              v-model="dialog.form[field.key]"
              :min="0"
              :max="field.max"
              :precision="field.precision || 0"
            />
            <el-input
              v-else-if="field.type === 'textarea'"
              v-model="dialog.form[field.key]"
              type="textarea"
              :rows="4"
              :placeholder="field.placeholder"
            />
            <el-input v-else v-model="dialog.form[field.key]" :placeholder="field.placeholder" />
          </el-form-item>
        </el-form>
      </template>

      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button v-if="dialog.mode !== 'detail'" type="primary" :loading="submitting" @click="submitDialog">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiDelete, apiGet, apiPost, apiPut } from '@/api/http'
import { getPageConfig } from '@/config/pageConfigs'

interface DialogField {
  key: string
  label: string
  type?: 'input' | 'select' | 'number' | 'textarea'
  source?: 'users' | 'organizations'
  placeholder?: string
  max?: number
  precision?: number
}

interface ActionPlan {
  method: 'post' | 'put' | 'delete'
  url: string
}

const route = useRoute()
const loading = ref(false)
const submitting = ref(false)
const rows = ref<Record<string, any>[]>([])
const selection = ref<Record<string, any>[]>([])
const stats = ref<Record<string, any>>({})
const SOURCE_OPTIONS: Array<{ label: string; value: string | number }> = [
  { label: '全部', value: 'all' },
  { label: '仅我的', value: 'self' },
  { label: '仅 MCN', value: 'mcn' },
]
const selectOptions = reactive<Record<string, Array<{ label: string; value: string | number }>>>({
  users: [],
  organizations: [],
  sources: SOURCE_OPTIONS,
})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filters = reactive<Record<string, any>>({})
const sorter = reactive({ prop: '', order: '' })
const dialog = reactive({
  visible: false,
  title: '',
  label: '',
  mode: 'form' as 'form' | 'detail' | 'batch',
  row: {} as Record<string, any>,
  form: {} as Record<string, any>,
})

const config = computed(() => getPageConfig(route.path, String(route.meta.title || ''), String(route.meta.endpoint || '')))
const endpoint = computed(() => config.value.endpoint)
const columns = computed(() => config.value.columns)
const rowActions = computed(() => config.value.rowActions || [{ label: '查看详情', type: 'primary' as const }, { label: '编辑' }])
const moreIndex = computed(() => rowActions.value.findIndex((action) => action.label === '更多'))
const primaryRowActions = computed(() => {
  if (moreIndex.value >= 0) return rowActions.value.slice(0, moreIndex.value)
  return rowActions.value
})
const moreRowActions = computed(() => {
  if (moreIndex.value >= 0) return rowActions.value.slice(moreIndex.value + 1)
  return []
})
const operationWidth = computed(() => {
  const visibleCount = primaryRowActions.value.length + (moreRowActions.value.length ? 1 : 0)
  return Math.max(130, visibleCount * 64)
})
const dialogWidth = computed(() => (dialog.mode === 'detail' ? '780px' : '560px'))
const dialogFields = computed<DialogField[]>(() => fieldsForAction(dialog.label))

function normalizeRows(data: any): Record<string, any>[] {
  if (config.value.responseListKey && Array.isArray(data?.[config.value.responseListKey])) return data[config.value.responseListKey]
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.list)) return data.list
  if (Array.isArray(data?.accounts)) return data.accounts
  if (Array.isArray(data?.items)) return data.items
  if (Array.isArray(data?.records)) return data.records
  if (Array.isArray(data?.details)) return data.details
  if (Array.isArray(data?.announcements)) return data.announcements
  return []
}

function normalizeTotal(data: any, fallback: number) {
  return data?.total || data?.pagination?.total || fallback
}

function optionsFor(source?: string) {
  if (!source) return []
  return selectOptions[source] || []
}

function statValue(key: string) {
  return stats.value[key] ?? stats.value.summary?.[key] ?? 0
}

function valueOf(row: Record<string, any>, key: string) {
  const aliases: Record<string, string[]> = {
    avatar: ['avatar', 'avatar_url', 'member_head', 'cover_url', 'thumbnail', 'thumb_url'],
    thumbnail: ['thumbnail', 'thumb_url', 'cover_url'],
    organization_name: ['organization_name', 'org_name'],
    owner_name: ['owner_name', 'assigned_user_name', 'user_name'],
    account_name: ['account_name', 'kuaishou_name', 'nickname'],
    real_uid: ['real_uid', 'uid_real'],
    sign_status: ['sign_status', 'contract_status'],
    member_name: ['member_name', 'nickname', 'username'],
    drama_url: ['drama_url', 'url'],
    total_amount: ['total_amount', 'amount', 'income', 'income_amount'],
  }
  for (const alias of aliases[key] || [key]) {
    if (row[alias] !== undefined && row[alias] !== null && row[alias] !== '') return row[alias]
  }
  return row[key]
}

function displayValue(value: any) {
  if (value === undefined || value === null || value === '') return '-'
  if (value === true) return '是'
  if (value === false) return '否'
  return String(value)
}

function numberValue(value: any) {
  const num = Number(value || 0)
  return Number.isFinite(num) ? num.toFixed(2) : '0.00'
}

function tagType(value: any) {
  const text = String(value)
  // 数据来源标签 (_src)
  if (text === '我的') return 'success'
  if (text === 'MCN') return 'primary'
  if (['正常', '启用', 'active', 'success', '1', '是'].includes(text)) return 'success'
  if (['禁用', '失败', 'failed', '0', '否'].includes(text)) return 'danger'
  return 'info'
}

function requestParams() {
  const params: Record<string, any> = {
    page: page.value,
    page_size: pageSize.value,
  }
  if (sorter.prop) {
    params.sort_by = sorter.prop
    params.sort_order = sorter.order === 'descending' ? 'desc' : 'asc'
  }
  for (const filter of config.value.filters) {
    if (filters[filter.key]) params[filter.key] = filters[filter.key]
  }
  return params
}

function handleSort(payload: { prop: string; order: string | null }) {
  sorter.prop = payload.prop || ''
  sorter.order = payload.order || ''
  loadData()
}

async function loadData() {
  if (!endpoint.value) return
  loading.value = true
  try {
    const res = await apiGet<any>(endpoint.value, requestParams())
    rows.value = normalizeRows(res.data)
    total.value = res.total || res.pagination?.total || normalizeTotal(res.data, rows.value.length)
    if (!config.value.statsEndpoint && res.data?.summary) stats.value = res.data.summary
    if (!config.value.statsEndpoint && res.data?.stats) stats.value = res.data.stats
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  stats.value = {}
  if (!config.value.statsEndpoint) return
  try {
    const res = await apiGet<any>(config.value.statsEndpoint)
    stats.value = res.data || {}
    if (res.data?.summary) stats.value = { ...res.data.summary, summary: res.data.summary }
  } catch {
    stats.value = {}
  }
}

async function loadFilterOptions() {
  const sources = new Set(config.value.filters.map((filter) => filter.source).filter(Boolean))
  if (sources.has('users') && !selectOptions.users.length) {
    const res = await apiGet<any>('/auth/users', { page: 1, page_size: 1000 })
    const list = Array.isArray(res.data?.users) ? res.data.users : Array.isArray(res.data) ? res.data : []
    selectOptions.users = list.map((item: any) => ({
      label: item.nickname || item.real_name || item.username || String(item.id),
      value: item.id,
    }))
  }
  if (sources.has('organizations') && !selectOptions.organizations.length) {
    const res = await apiGet<any>('/organizations')
    const list = Array.isArray(res.data) ? res.data : res.data?.organizations || []
    selectOptions.organizations = list.map((item: any) => ({
      label: item.name || item.org_name || String(item.id),
      value: item.id,
    }))
  }
}

function reset() {
  for (const key of Object.keys(filters)) delete filters[key]
  page.value = 1
  loadData()
}

function selectedIds() {
  return selection.value.map((item) => item.id ?? item.uid ?? item.member_id).filter(Boolean)
}

function cleanLabel(label: string) {
  return label.replace(/\s*\(\d+\)/g, '').replace(/^[^\u4e00-\u9fa5A-Za-z0-9]+/u, '').trim()
}

function rowId(row?: Record<string, any>) {
  return row?.id ?? row?.member_id ?? row?.uid
}

function actionPlan(label: string, row?: Record<string, any>): ActionPlan | null {
  const action = cleanLabel(label)
  const id = rowId(row)

  if (route.path === '/accounts') {
    if (action.includes('删除')) return row?.id ? { method: 'delete', url: `/accounts/${row.id}` } : { method: 'post', url: '/accounts/batch-delete' }
    if (action.includes('批量授权')) return { method: 'post', url: '/accounts/batch-authorize' }
    if (action.includes('更新授权') || action.includes('刷新签约状态')) return { method: 'post', url: '/accounts/sync-mcn-authorization' }
    if (action.includes('更新收益')) return { method: 'post', url: '/accounts/batch-update-income' }
    if (action.includes('批量修改分成')) return { method: 'post', url: '/accounts/batch-commission-rate' }
    if (action.includes('批量修改机构')) return { method: 'post', url: '/accounts/batch-assign-organization' }
    if (action.includes('分配用户')) return { method: 'post', url: '/accounts/assign' }
    if (action.includes('邀请账号')) return { method: 'post', url: '/accounts/batch-direct-invite' }
    if (action.includes('开通星火')) return { method: 'post', url: '/accounts/batch-open-spark' }
    if (action.includes('文件批量') || action.includes('批量导入')) return { method: 'post', url: '/accounts/batch-import' }
    if (action.includes('编辑') && row?.id) return { method: 'put', url: `/accounts/${row.id}` }
    if (action.includes('添加账号')) return { method: 'post', url: '/accounts' }
  }

  if (route.path === '/users') {
    if (action.includes('删除')) return row?.id ? { method: 'delete', url: `/auth/users/${row.id}` } : { method: 'post', url: '/auth/users/batch-delete' }
    if (action.includes('重置密码')) return row?.id ? { method: 'post', url: `/auth/users/${row.id}/reset-password` } : { method: 'post', url: '/auth/users/batch-reset-password' }
    if (action.includes('禁用') || action.includes('启用')) return row?.id ? { method: 'put', url: `/auth/users/${row.id}/status` } : { method: 'post', url: '/auth/users/batch-toggle-status' }
    if (action.includes('编辑分成')) return row?.id ? { method: 'put', url: `/auth/users/${row.id}/commission-rate` } : { method: 'post', url: '/auth/users/batch-update-commission-rate' }
    if (action.includes('修改角色')) return row?.id ? { method: 'post', url: `/auth/users/${row.id}/change-role` } : { method: 'post', url: '/auth/users/batch-change-role' }
    if (action.includes('设置机构')) return row?.id ? { method: 'put', url: `/auth/users/${row.id}/organizations` } : { method: 'post', url: '/auth/users/batch/organizations' }
    if (action.includes('分配给团长')) return row?.id ? { method: 'post', url: `/auth/users/${row.id}/assign-to-operator` } : { method: 'post', url: '/auth/users/batch-assign-to-operator' }
    if (action.includes('合作类型')) return row?.id ? { method: 'put', url: `/auth/users/${row.id}/cooperation-type` } : { method: 'post', url: '/auth/users/batch-change-cooperation-type' }
    if (action.includes('分成可见')) return row?.id ? { method: 'put', url: `/auth/users/${row.id}/commission-visibility` } : { method: 'post', url: '/auth/users/batch-commission-visibility' }
    if (action.includes('编辑') && row?.id) return { method: 'put', url: `/auth/users/${row.id}` }
    if (action.includes('创建用户')) return { method: 'post', url: '/auth/users' }
  }

  if (route.path === '/org-members') {
    if (action.includes('删除') && row?.id) return { method: 'delete', url: `/org-members/${row.id}` }
    if (action.includes('编辑') && row?.id) return { method: 'put', url: `/org-members/${row.id}` }
    if (action.includes('添加')) return { method: 'post', url: '/org-members' }
  }

  if (route.path === '/collect-pool') {
    if (action.includes('删除')) return row?.id ? { method: 'delete', url: `/collect-pool/${row.id}` } : { method: 'post', url: '/collect-pool/batch-delete' }
    if (action.includes('添加')) return { method: 'post', url: '/collect-pool' }
  }

  if (route.path === '/high-income-dramas') {
    if (action.includes('删除') && row?.id) return { method: 'delete', url: `/high-income-dramas/${row.id}` }
    if (action.includes('添加')) return { method: 'post', url: '/high-income-dramas' }
  }

  if (route.path === '/drama-statistics') {
    if (action.includes('删除') || action.includes('清空')) return { method: 'delete', url: '/statistics/drama-links' }
  }

  if (route.path === '/external-url-stats') {
    if (action.includes('删除') || action.includes('清空')) return { method: 'delete', url: '/statistics/external-urls' }
  }

  if (route.path === '/cxt-user') {
    if (action.includes('删除')) return { method: 'delete', url: '/cxt-user/batch' }
    if (action.includes('批量上传')) return { method: 'post', url: '/cxt-user/batch' }
    if (action.includes('批量UID修改') || action.includes('修改')) return { method: 'put', url: '/cxt-user/batch-status-by-uid' }
  }

  if (route.path === '/cxt-videos') {
    if (action.includes('删除')) return { method: 'delete', url: '/cxt-videos/batch' }
    if (action.includes('批量导入')) return { method: 'post', url: '/cxt-videos/batch-import' }
    if (action.includes('详情') && id) return null
  }

  if (route.path === '/firefly-members') {
    if (action.includes('同步')) return { method: 'post', url: '/firefly/members/sync' }
    if (action.includes('上传')) return { method: 'post', url: '/firefly/members/upload' }
    if (action.includes('删除') && id) return { method: 'delete', url: `/firefly/members/${id}` }
    if (action.includes('编辑') && id) return { method: 'put', url: `/firefly/members/${id}` }
  }

  if (route.path === '/firefly-income' || route.path === '/fluorescent-income') {
    if (action.includes('删除') && row?.id) return { method: 'delete', url: `/firefly/income/${row.id}` }
    if (action.includes('编辑') && row?.id) return { method: 'put', url: `/firefly/income/${row.id}` }
    if (action.includes('未结清') && row?.id) return { method: 'put', url: `/firefly/income/${row.id}/settlement` }
    if (action.includes('加入高转化')) return { method: 'post', url: '/fluorescent/add-to-high-income' }
  }

  if (route.path === '/spark-members') {
    if (action.includes('删除') && id) return { method: 'delete', url: `/spark/members/${id}` }
    if (action.includes('编辑') && id) return { method: 'put', url: `/spark/members/${id}` }
    if (action.includes('添加')) return { method: 'post', url: '/spark/members' }
  }

  if (route.path === '/spark-income') {
    if (action.includes('删除') && row?.id) return { method: 'delete', url: `/spark/income/${row.id}` }
    if (action.includes('编辑') && row?.id) return { method: 'put', url: `/spark/income/${row.id}` }
    if (action.includes('加入高转化')) return { method: 'post', url: '/fluorescent/add-to-high-income' }
  }

  if (route.path === '/spark-archive') {
    if (action.includes('分成') && row?.id) return { method: 'put', url: `/spark/archive/${row.id}/commission` }
    if (action.includes('未结清') && row?.id) return { method: 'put', url: `/spark/archive/${row.id}/settlement` }
    if (action.includes('批量') && action.includes('分成')) return { method: 'post', url: '/spark/archive/batch-commission' }
    if (action.includes('批量') || action.includes('未结清')) return { method: 'post', url: '/spark/archive/batch-settlement' }
  }

  if (route.path === '/spark-photos') {
    if (action.includes('删除') && row?.id) return { method: 'delete', url: `/spark/photos/${row.id}` }
    if (action.includes('编辑') && row?.id) return { method: 'put', url: `/spark/photos/${row.id}` }
    if (action.includes('添加')) return { method: 'post', url: '/spark/photos' }
  }

  if (route.path === '/account-violation') {
    if (action.includes('删除') && row?.id) return { method: 'delete', url: `/spark/violation-photos/${row.id}` }
    if (action.includes('编辑') && row?.id) return { method: 'put', url: `/spark/violation-photos/${row.id}` }
  }

  return null
}

function requestByPlan(plan: ActionPlan, payload?: unknown) {
  if (plan.method === 'put') return apiPut(plan.url, payload)
  if (plan.method === 'delete') return apiDelete(plan.url, payload)
  return apiPost(plan.url, payload)
}

function fieldsForAction(label: string): DialogField[] {
  const action = cleanLabel(label)
  if (action.includes('账号') || route.path.includes('accounts')) {
    return [
      { key: 'uid', label: '快手号/UID', placeholder: '请输入快手号或UID' },
      { key: 'nickname', label: '昵称', placeholder: '请输入昵称' },
      { key: 'real_uid', label: '真实UID', placeholder: '请输入真实UID' },
      { key: 'organization_id', label: '所属机构', type: 'select', source: 'organizations' },
      { key: 'owner_id', label: '所属用户', type: 'select', source: 'users' },
      { key: 'remark', label: '备注', type: 'textarea', placeholder: '请输入备注' },
    ]
  }
  if (action.includes('用户') || route.path === '/users') {
    return [
      { key: 'username', label: '用户名', placeholder: '请输入用户名' },
      { key: 'nickname', label: '昵称', placeholder: '请输入昵称' },
      { key: 'password', label: '密码', placeholder: '留空则不修改' },
      { key: 'commission_rate', label: '分成比例', type: 'number', max: 100, precision: 2 },
      { key: 'organization_id', label: '所属机构', type: 'select', source: 'organizations' },
      { key: 'parent_id', label: '上级用户', type: 'select', source: 'users' },
    ]
  }
  if (action.includes('短剧') || route.path.includes('drama') || route.path.includes('collect') || route.path.includes('income')) {
    return [
      { key: 'drama_name', label: '短剧名称', placeholder: '请输入短剧名称' },
      { key: 'drama_url', label: '短剧链接', placeholder: '请输入短剧链接' },
      { key: 'auth_code', label: '授权码', placeholder: '请输入授权码' },
      { key: 'remark', label: '备注', type: 'textarea', placeholder: '请输入备注' },
    ]
  }
  return columns.value.slice(0, 8).map((column) => ({
    key: column.key,
    label: column.label,
    placeholder: `请输入${column.label}`,
  }))
}

function openDialog(label: string, row?: Record<string, any>) {
  dialog.label = label
  dialog.title = label
  dialog.row = row || {}
  dialog.form = { ...(row || {}) }
  dialog.mode = label.includes('查看') || label.includes('详情') || label.includes('点击查看') ? 'detail' : label.includes('批量') || label.includes('(0)') ? 'batch' : 'form'
  dialog.visible = true
  loadFilterOptions()
}

async function submitDialog() {
  const plan = actionPlan(dialog.label, dialog.row)
  if (!plan) {
    ElMessage.warning(`“${dialog.label}”后端暂无可用接口，已保持为弹窗展示，不提交无效请求`)
    return
  }
  submitting.value = true
  try {
    const payload = dialog.mode === 'batch' ? { ids: selectedIds(), ...dialog.form } : dialog.form
    await requestByPlan(plan, payload)
    ElMessage.success('操作成功')
    dialog.visible = false
    loadData()
    loadStats()
  } finally {
    submitting.value = false
  }
}

async function runDelete(label: string, row?: Record<string, any>) {
  const ids = row ? [row.id ?? row.uid ?? row.member_id].filter(Boolean) : selectedIds()
  const plan = actionPlan(label, row)
  if (!plan) {
    ElMessage.warning(`“${label}”后端暂无可用接口，未提交无效请求`)
    return
  }
  await ElMessageBox.confirm(`确定执行“${label}”？${ids.length ? `本次影响 ${ids.length} 条数据。` : ''}`, '操作确认', {
    type: 'warning',
    confirmButtonText: '确定',
    cancelButtonText: '取消',
  })
  await requestByPlan(plan, { ids })
  ElMessage.success('操作成功')
  loadData()
  loadStats()
}

async function handleAction(label: string, row?: Record<string, any>) {
  if (label === '搜索' || label === '刷新' || label === '查询') {
    loadData()
    loadStats()
    return
  }
  if (label === '重置') {
    reset()
    return
  }
  if (label.includes('删除') || label.includes('清空')) {
    await runDelete(label, row)
    return
  }
  if (label.includes('导出')) {
    if (route.path === '/drama-statistics') window.open('/api/statistics/drama-links', '_blank')
    else if (route.path === '/external-url-stats') window.open('/api/statistics/external-urls', '_blank')
    else ElMessage.warning(`“${label}”后端暂无导出接口`)
    return
  }
  openDialog(label, row)
}

watch(() => route.fullPath, () => {
  page.value = 1
  rows.value = []
  for (const key of Object.keys(filters)) delete filters[key]
  loadData()
  loadStats()
  loadFilterOptions()
})

onMounted(() => {
  loadData()
  loadStats()
  loadFilterOptions()
})
</script>
