/**
 * 用户管理页共享类型与常量（pages/admin/users/types.ts）
 *
 * 2026-06-11 Round 5.5 拆分：从 UsersPage.tsx 抽出，供页面主文件、
 * 表单弹窗、重置密码弹窗、表格列定义共用。纯类型/常量，无运行时逻辑。
 */

/** 角色枚举 → 中文标签 + Tag 颜色映射 */
export const ROLE_MAP: Record<string, { label: string; color: string }> = {
  super_admin: { label: '超级管理员', color: 'red' },
  hospital_admin: { label: '医院管理员', color: 'orange' },
  dept_admin: { label: '科室管理员', color: 'gold' },
  doctor: { label: '医生', color: 'blue' },
  nurse: { label: '护士', color: 'cyan' },
}

/** 用户列表行类型（后端 UserResponse 子集，仅含本页用到的字段） */
export interface UserRow {
  id: string
  username: string
  real_name: string
  role: string
  is_active: boolean
  department_id?: string | null
  department_name?: string | null
}

/** 科室下拉项（仅取 id + name 用于 Select options） */
export interface DeptOption {
  id: string
  name: string
}

/** 新建/编辑用户表单字段——与后端 UserCreate/UserUpdate 对齐 */
export interface UserFormValues {
  username?: string
  password?: string
  real_name: string
  role: string
  department_id?: string | null
  employee_no?: string
  phone?: string
  email?: string
}
