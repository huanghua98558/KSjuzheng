<template>
  <el-card class="permission-section" shadow="never">
    <template #header>{{ title }}</template>
    <el-row :gutter="12">
      <el-col v-for="item in items" :key="item.key" :span="6">
        <el-checkbox :model-value="checked(type, item.key)" @change="(value: any) => emit('change', type, item.key, Boolean(value))">
          {{ permissionLabel(item) }}
        </el-checkbox>
      </el-col>
    </el-row>
  </el-card>
</template>

<script setup lang="ts">
import { permissionLabel } from '@/utils/permissions'

const props = defineProps<{
  title: string
  type: string
  items: Array<{ key: string; perm_key?: string; name?: string; label?: string }>
  state: Record<string, number>
}>()

const emit = defineEmits<{
  change: [type: string, key: string, allowed: boolean]
}>()

function checked(type: string, key: string) {
  return props.state[`${type}:${key}`] === 1
}
</script>
