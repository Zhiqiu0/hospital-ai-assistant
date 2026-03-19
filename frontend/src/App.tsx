import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from '@/pages/LoginPage'
import WorkbenchPage from '@/pages/WorkbenchPage'
import InpatientWorkbenchPage from '@/pages/InpatientWorkbenchPage'
import AdminLayout from '@/pages/admin/AdminLayout'
import { useAuthStore } from '@/store/authStore'

const ADMIN_ROLES = ['super_admin', 'hospital_admin', 'dept_admin']

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { token } = useAuthStore()
  return token ? <>{children}</> : <Navigate to="/login" replace />
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { token, user } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  if (!user || !ADMIN_ROLES.includes(user.role)) return <Navigate to="/workbench" replace />
  return <>{children}</>
}

function RootRedirect() {
  const { token, user, systemType } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  if (user && ADMIN_ROLES.includes(user.role)) return <Navigate to="/admin" replace />
  return <Navigate to={systemType === 'inpatient' ? '/inpatient' : '/workbench'} replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/workbench" element={<PrivateRoute><WorkbenchPage /></PrivateRoute>} />
        <Route path="/inpatient" element={<PrivateRoute><InpatientWorkbenchPage /></PrivateRoute>} />
        <Route path="/admin/*" element={<AdminRoute><AdminLayout /></AdminRoute>} />
        <Route path="/" element={<RootRedirect />} />
      </Routes>
    </BrowserRouter>
  )
}
