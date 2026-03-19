import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UserInfo {
  id: string
  username: string
  real_name: string
  role: string
  department_id?: string
  department_name?: string
}

interface AuthState {
  token: string | null
  user: UserInfo | null
  systemType: 'outpatient' | 'inpatient'
  setAuth: (token: string, user: UserInfo) => void
  clearAuth: () => void
  setSystemType: (type: 'outpatient' | 'inpatient') => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      systemType: 'outpatient',
      setAuth: (token, user) => set({ token, user }),
      clearAuth: () => set({ token: null, user: null, systemType: 'outpatient' }),
      setSystemType: (type) => set({ systemType: type }),
    }),
    { name: 'mediscribe-auth' }
  )
)
