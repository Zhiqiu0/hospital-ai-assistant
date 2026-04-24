/**
 * 应用路由根组件（App.tsx）
 *
 * 路由结构：
 *   /login           → LoginPage（无需认证）
 *   /workbench       → WorkbenchPage（门诊工作台，需登录）
 *   /emergency       → EmergencyWorkbenchPage（急诊工作台，需登录）
 *   /inpatient       → InpatientWorkbenchPage（住院工作台，需登录）
 *   /pacs            → PacsWorkbenchPage（影像阅片工作台，需登录）
 *   /admin/*         → AdminLayout（管理后台，需 admin 角色）
 *   /                → RootRedirect（根据角色/系统类型自动跳转）
 *
 * 路由守卫：
 *   PrivateRoute: 检查 token 是否存在，未登录重定向到 /login
 *   AdminRoute:   同时检查 token + 角色，非管理员重定向到 /workbench
 *
 * 根路由重定向逻辑（RootRedirect）：
 *   未登录 → /login
 *   admin/super_admin → /admin
 *   radiologist → /pacs
 *   systemType='inpatient' → /inpatient
 *   其他 → /workbench（门诊，默认）
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from '@/pages/LoginPage'
import WorkbenchPage from '@/pages/WorkbenchPage'
import EmergencyWorkbenchPage from '@/pages/EmergencyWorkbenchPage'
import InpatientWorkbenchPage from '@/pages/InpatientWorkbenchPage'
import PacsWorkbenchPage from '@/pages/PacsWorkbenchPage'
import AdminLayout from '@/pages/admin/AdminLayout'
import { useAuthStore, isTokenExpired } from '@/store/authStore'

const ADMIN_ROLES = ['super_admin', 'hospital_admin', 'dept_admin']

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { token } = useAuthStore()
  const valid = token && !isTokenExpired(token)
  return valid ? <>{children}</> : <Navigate to="/login" replace />
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { token, user } = useAuthStore()
  if (!token || isTokenExpired(token)) return <Navigate to="/login" replace />
  if (!user || !ADMIN_ROLES.includes(user.role)) return <Navigate to="/workbench" replace />
  return <>{children}</>
}

function RootRedirect() {
  const { token, user, systemType } = useAuthStore()
  if (!token || isTokenExpired(token)) return <Navigate to="/login" replace />
  if (user && ADMIN_ROLES.includes(user.role)) return <Navigate to="/admin" replace />
  if (user?.role === 'radiologist') return <Navigate to="/pacs" replace />
  if (systemType === 'inpatient') return <Navigate to="/inpatient" replace />
  return <Navigate to="/workbench" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/workbench"
          element={
            <PrivateRoute>
              <WorkbenchPage />
            </PrivateRoute>
          }
        />
        <Route
          path="/emergency"
          element={
            <PrivateRoute>
              <EmergencyWorkbenchPage />
            </PrivateRoute>
          }
        />
        <Route
          path="/inpatient"
          element={
            <PrivateRoute>
              <InpatientWorkbenchPage />
            </PrivateRoute>
          }
        />
        <Route
          path="/pacs"
          element={
            <PrivateRoute>
              <PacsWorkbenchPage />
            </PrivateRoute>
          }
        />
        <Route
          path="/admin/*"
          element={
            <AdminRoute>
              <AdminLayout />
            </AdminRoute>
          }
        />
        <Route path="/" element={<RootRedirect />} />
      </Routes>
    </BrowserRouter>
  )
}
