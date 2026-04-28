<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>成员数据查询</span>
        <el-tag>同时查询星火计划和萤光计划数据</el-tag>
      </div>
    </template>

    <el-row :gutter="18">
      <el-col :span="8">
        <el-input
          v-model="uidText"
          type="textarea"
          :rows="14"
          placeholder="每行输入一个UID，支持批量查询"
        />
        <div class="member-query-actions">
          <el-button type="primary" :loading="loading" @click="query">🔍 开始查询</el-button>
          <el-button @click="reset">重置</el-button>
        </div>
      </el-col>
      <el-col :span="16">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="萤光计划" name="firefly">
            <el-table :data="fireflyRows" border stripe height="430">
              <el-table-column prop="member_id" label="成员ID" width="140" />
              <el-table-column prop="member_name" label="成员昵称" />
              <el-table-column prop="fans_count" label="粉丝数" width="120" />
              <el-table-column prop="org_task_num" label="机构任务数" width="120" />
              <el-table-column prop="total_amount" label="总金额" width="120" />
              <el-table-column prop="org_name" label="所属机构" width="160" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="星火计划" name="spark">
            <el-table :data="sparkRows" border stripe height="430">
              <el-table-column prop="member_id" label="成员ID" width="140" />
              <el-table-column prop="member_name" label="成员名称" />
              <el-table-column prop="fans_count" label="粉丝数" width="120" />
              <el-table-column prop="org_task_num" label="任务数" width="120" />
              <el-table-column prop="total_amount" label="累计收入" width="120" />
              <el-table-column prop="org_name" label="所属机构" width="160" />
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </el-col>
    </el-row>
  </el-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet } from '@/api/http'

const uidText = ref('')
const activeTab = ref('firefly')
const loading = ref(false)
const fireflyRows = ref<any[]>([])
const sparkRows = ref<any[]>([])

function uids() {
  return uidText.value.split(/\s+/).map((item) => item.trim()).filter(Boolean)
}

async function query() {
  const targets = uids()
  if (!targets.length) {
    ElMessage.warning('请输入至少一个UID')
    return
  }
  loading.value = true
  try {
    const firefly: any[] = []
    const spark: any[] = []
    for (const uid of targets) {
      const [fireflyRes, sparkRes] = await Promise.all([
        apiGet<any[]>('/firefly/members', { search: uid, page_size: 20 }),
        apiGet<any[]>('/spark/members', { search: uid, page_size: 20 }),
      ])
      firefly.push(...(Array.isArray(fireflyRes.data) ? fireflyRes.data : []))
      spark.push(...(Array.isArray(sparkRes.data) ? sparkRes.data : []))
    }
    fireflyRows.value = firefly
    sparkRows.value = spark
  } finally {
    loading.value = false
  }
}

function reset() {
  uidText.value = ''
  fireflyRows.value = []
  sparkRows.value = []
}
</script>
