import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import MainLayout from '@/layouts/MainLayout.vue'
import LoginView from '@/views/LoginView.vue'
import DashboardView from '@/views/DashboardView.vue'
import GenericTableView from '@/views/GenericTableView.vue'
import MemberQueryView from '@/views/MemberQueryView.vue'
import SettingsView from '@/views/settings/SettingsView.vue'

export interface MenuItem {
  path: string
  title: string
  icon?: string
  endpoint?: string
  children?: MenuItem[]
}

export const menuItems: MenuItem[] = [
  {
    path: '/dashboard',
    title: '数据概览',
    children: [
      { path: '/member-query', title: '成员数据查询' },
      { path: '/dashboard', title: '概览仪表盘', endpoint: '/statistics/overview' },
      { path: '/statistics', title: '执行统计', endpoint: '/statistics/drama' },
    ],
  },
  {
    path: '/accounts',
    title: '账号管理',
    children: [
      { path: '/accounts', title: '软件账号管理', endpoint: '/accounts' },
      { path: '/ks-accounts', title: 'KS账号管理', endpoint: '/ks-accounts' },
      { path: '/org-members', title: '机构成员管理', endpoint: '/org-members' },
      { path: '/account-violation', title: '账号违规信息', endpoint: '/spark/violation-photos' },
      { path: '/users', title: '用户管理', endpoint: '/auth/users' },
    ],
  },
  {
    path: '/income',
    title: '收益管理',
    children: [
      { path: '/wallet-info', title: '钱包信息', endpoint: '/wallet-info' },
      { path: '/firefly-members', title: '萤光本月收益', endpoint: '/firefly/members' },
      { path: '/firefly-income', title: '历史收益', endpoint: '/firefly/income' },
      { path: '/fluorescent-income', title: '收益明细', endpoint: '/fluorescent/income' },
    ],
  },
  {
    path: '/spark',
    title: '星火计划',
    children: [
      { path: '/spark-members', title: '星火成员', endpoint: '/spark/members' },
      { path: '/spark-archive', title: '星火归档', endpoint: '/spark/archive' },
      { path: '/spark-income', title: '星火收益', endpoint: '/spark/income' },
      { path: '/spark-photos', title: '星火作品', endpoint: '/spark/photos' },
    ],
  },
  {
    path: '/drama',
    title: '短剧管理',
    children: [
      { path: '/collect-pool', title: '短剧收藏池', endpoint: '/collect-pool' },
      { path: '/high-income-dramas', title: '高转化短剧管理', endpoint: '/high-income-dramas' },
      { path: '/drama-statistics', title: '短剧链接统计', endpoint: '/statistics/drama-links' },
      { path: '/drama-collections', title: '短剧收藏记录', endpoint: '/collections/accounts' },
    ],
  },
  {
    path: '/external',
    title: '外部项目',
    children: [
      { path: '/external-url-stats', title: '外部项目统计', endpoint: '/statistics/external-urls' },
      { path: '/cxt-user', title: '橙星推用户', endpoint: '/cxt-user' },
      { path: '/cxt-videos', title: '橙星推剧集', endpoint: '/cxt-videos' },
    ],
  },
  {
    path: '/system',
    title: '系统管理',
    children: [
      { path: '/settings', title: '系统配置' },
      { path: '/cloud-cookies', title: '云端Cookie管理', endpoint: '/cloud-cookies' },
    ],
  },
]

function flattenMenus(items: MenuItem[]) {
  return items.flatMap((item) => item.children || [item])
}

const routes: RouteRecordRaw[] = [
  { path: '/login', component: LoginView },
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    children: [
      { path: 'member-query', component: MemberQueryView, meta: { title: '成员数据查询' } },
      { path: 'dashboard', component: DashboardView, meta: { title: '概览仪表盘' } },
      { path: 'settings', component: SettingsView, meta: { title: '系统配置' } },
      ...flattenMenus(menuItems)
        .filter((item) => !['/member-query', '/dashboard', '/settings'].includes(item.path))
        .map((item) => ({
          path: item.path.slice(1),
          component: GenericTableView,
          meta: { title: item.title, endpoint: item.endpoint },
        })),
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.path !== '/login' && !auth.token) return '/login'
  if (to.path === '/login' && auth.token) return '/dashboard'
})

export default router
