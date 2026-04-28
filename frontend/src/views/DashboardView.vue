<template>
  <div class="page-stack">
    <div class="page-heading">
      <h2>概览仪表盘</h2>
      <p>实时汇总账号、成员、执行与收益核心数据</p>
    </div>

    <el-row :gutter="16">
      <el-col v-for="card in cards" :key="card.label" :span="6">
        <el-card class="metric-card">
          <div class="metric-inline">
            <div class="metric-icon" :style="{ background: card.color }">{{ card.icon }}</div>
            <div>
              <strong>{{ card.value }}</strong>
              <span>{{ card.label }}</span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :span="16">
        <el-card class="section-card dashboard-panel">
          <template #header>
            <div class="card-header">
              <span>最近趋势</span>
              <el-tag size="small" type="info">来自 MySQL huoshijie</el-tag>
            </div>
          </template>
          <div v-if="trendLabels.length" class="trend-list">
            <div v-for="(label, index) in trendLabels" :key="label">
              <span>{{ label }}</span>
              <el-progress :percentage="trendPercent(index)" />
            </div>
          </div>
          <el-empty v-else description="暂无趋势数据" />
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card class="section-card dashboard-panel">
          <template #header>
            <div class="card-header">
              <span>系统公告</span>
              <el-button link type="primary" @click="$router.push('/settings')">去设置</el-button>
            </div>
          </template>
          <div class="notice-card">
            <strong>2月份星火计划收益结算通知</strong>
            <p>公告、权限、机构、日志均从后台接口读取；这里保留和当前后台一致的公告入口。</p>
            <div>
              <el-button type="primary" size="small">我知道了</el-button>
              <el-button size="small">今日不再显示</el-button>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiGet } from '@/api/http'

const overview = ref<any>(null)

const cards = computed(() => [
  { label: '账号总数', value: overview.value?.accounts?.total ?? '-', icon: '账', color: '#6a5adf' },
  { label: 'MCN 成员', value: overview.value?.accounts?.mcn_members ?? '-', icon: '员', color: '#24b6f0' },
  { label: '执行总数', value: overview.value?.executions?.total ?? '-', icon: '执', color: '#31b56a' },
  { label: '成功次数', value: overview.value?.executions?.success ?? '-', icon: '成', color: '#ff9f28' },
])

const trendLabels = computed<string[]>(() => overview.value?.trend?.labels || [])

function trendPercent(index: number) {
  const values = overview.value?.trend?.values || []
  const max = Math.max(...values, 1)
  return Math.round((values[index] / max) * 100)
}

onMounted(async () => {
  const res = await apiGet<any>('/statistics/overview')
  overview.value = res.data
})
</script>
