# API 接口定义文档（当前实现版）

> 基础路径：`/api/v1` | 更新日期：2026-03-19

本文档以当前代码实现为准，用于本地开发联调。

---

## 一、通用说明

- 鉴权方式：`Authorization: Bearer <JWT_TOKEN>`
- 数据格式：JSON
- SSE 接口返回：`Content-Type: text/event-stream`
- 当前大部分接口直接返回业务 JSON，**未统一包装**为 `{ code, message, data }`

常见错误：

- `401`：未登录、Token 无效或登录失败
- `403`：权限不足
- `404`：资源不存在
- `422`：参数校验失败

---

## 二、认证模块 `/auth`

### 2.1 登录

`POST /auth/login`

请求：

```json
{
  "username": "doctor01",
  "password": "doctor123"
}
```

成功响应：

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "uuid",
    "username": "doctor01",
    "real_name": "张医生",
    "role": "doctor",
    "department_id": "uuid",
    "department_name": "内科"
  }
}
```

失败响应示例：

```json
{ "detail": "账号不存在" }
```

```json
{ "detail": "密码不正确" }
```

```json
{ "detail": "账号已被禁用" }
```

### 2.2 登出

`POST /auth/logout`

响应：

```json
{ "message": "已登出" }
```

### 2.3 检查用户名是否存在

`GET /auth/check-username?username=doctor01`

响应：

```json
{ "exists": true, "message": "账号存在" }
```

---

## 三、患者模块 `/patients`

### 3.1 搜索患者

`GET /patients?keyword=张&page=1&page_size=20`

### 3.2 创建患者

`POST /patients`

请求：

```json
{
  "name": "张三",
  "gender": "male",
  "birth_date": "1980-01-01",
  "phone": "13800138000"
}
```

### 3.3 获取患者详情

`GET /patients/{patient_id}`

---

## 四、接诊模块 `/encounters`

### 4.1 快速开始接诊

`POST /encounters/quick-start`

用于当前前端主流程：自动创建患者并创建接诊。

请求：

```json
{
  "patient_name": "张三",
  "gender": "male",
  "age": 35,
  "phone": "13800138000",
  "visit_type": "outpatient"
}
```

响应：

```json
{
  "encounter_id": "uuid",
  "patient": {
    "id": "uuid",
    "name": "张三"
  },
  "visit_type": "outpatient"
}
```

### 4.2 创建接诊

`POST /encounters`

### 4.3 获取接诊详情

`GET /encounters/{encounter_id}`

### 4.4 保存问诊输入

`PUT /encounters/{encounter_id}/inquiry`

请求字段：

```json
{
  "chief_complaint": "发热3天",
  "history_present_illness": "3天前无明显诱因出现发热",
  "past_history": "否认高血压、糖尿病史",
  "allergy_history": "青霉素过敏",
  "personal_history": "无吸烟饮酒史",
  "physical_exam": "T 38.8℃",
  "initial_impression": "急性上呼吸道感染？"
}
```

### 4.5 基于接诊记录获取追问建议

`POST /encounters/{encounter_id}/inquiry-suggestions`

SSE 返回，当前前端主流程暂未使用。

### 4.6 基于接诊记录获取检查建议

`POST /encounters/{encounter_id}/exam-suggestions`

### 4.7 获取工作台恢复快照

`GET /encounters/{encounter_id}/workspace`

用于前端“续接诊/恢复接诊”功能，一次性返回：

- 患者基础信息
- 最近保存的问诊内容
- 当前接诊下最近一份病历内容（按最近更新时间）

响应示例：

```json
{
  "encounter_id": "uuid",
  "visit_type": "outpatient",
  "status": "in_progress",
  "patient": {
    "id": "uuid",
    "name": "张三",
    "gender": "male",
    "age": 35
  },
  "inquiry": {
    "chief_complaint": "发热3天",
    "history_present_illness": "3天前无明显诱因出现发热"
  },
  "active_record": {
    "record_id": "uuid",
    "record_type": "outpatient",
    "status": "submitted",
    "current_version": 1,
    "content": "完整病历文本"
  },
  "records": []
}
```

---

## 五、病历模块 `/medical-records`

### 5.1 快速签发保存病历

`POST /medical-records/quick-save`

当前前端“出具最终病历”按钮使用该接口。

请求：

```json
{
  "encounter_id": "uuid",
  "record_type": "outpatient",
  "content": "完整病历文本"
}
```

响应：

```json
{
  "record_id": "uuid",
  "message": "病历已保存"
}
```

### 5.2 我的历史病历

`GET /medical-records/my?page=1&page_size=20`

### 5.3 创建病历

`POST /medical-records`

### 5.4 获取病历详情

`GET /medical-records/{record_id}`

### 5.5 生成病历（record 模式）

`POST /medical-records/{record_id}/generate`

SSE 返回，属于较完整的 record-centric 流程，当前前端主流程暂未使用。

### 5.6 续写病历（record 模式）

`POST /medical-records/{record_id}/continue`

### 5.7 润色病历（record 模式）

`POST /medical-records/{record_id}/polish`

### 5.8 保存结构化病历内容

`PUT /medical-records/{record_id}/content`

### 5.9 获取病历版本历史

`GET /medical-records/{record_id}/versions`

### 5.10 触发病历质控扫描

`POST /medical-records/{record_id}/qc/scan`

---

## 六、AI 快捷接口 `/ai`

这一组接口是当前前端工作台主要使用的接口。

### 6.1 一键生成病历

`POST /ai/quick-generate`

请求字段：

```json
{
  "chief_complaint": "发热3天",
  "history_present_illness": "3天前无明显诱因发热",
  "past_history": "否认高血压、糖尿病史",
  "allergy_history": "青霉素过敏",
  "personal_history": "无吸烟饮酒史",
  "physical_exam": "T 38.8℃",
  "initial_impression": "急性上呼吸道感染？",
  "record_type": "outpatient"
}
```

SSE 事件格式：

```text
data: {"type":"start"}

data: {"type":"chunk","text":"..."}

data: {"type":"done"}
```

### 6.2 续写病历

`POST /ai/quick-continue`

### 6.3 补全缺失项

`POST /ai/quick-supplement`

请求中 `qc_issues` 为数组。

### 6.4 润色病历

`POST /ai/quick-polish`

请求：

```json
{ "content": "原始病历文本" }
```

### 6.5 追问建议

`POST /ai/inquiry-suggestions`

请求：

```json
{
  "chief_complaint": "发热3天",
  "history_present_illness": "3天前无明显诱因发热"
}
```

响应：

```json
{
  "suggestions": [
    {
      "text": "是否有咳嗽、咳痰？",
      "priority": "high",
      "is_red_flag": false,
      "category": "伴随症状",
      "options": ["有", "无", "不确定"]
    }
  ]
}
```

### 6.6 检查建议

`POST /ai/exam-suggestions`

请求字段：`chief_complaint`、`history_present_illness`、`initial_impression`、`department`

### 6.7 诊断建议

`POST /ai/diagnosis-suggestion`

请求：

```json
{
  "chief_complaint": "发热3天",
  "history_present_illness": "3天前无明显诱因发热",
  "initial_impression": "急性上呼吸道感染？",
  "inquiry_answers": [
    { "question": "是否咳嗽", "answer": "有，伴少量白痰" }
  ]
}
```

响应：

```json
{
  "diagnoses": [
    {
      "name": "急性上呼吸道感染",
      "confidence": "high",
      "reasoning": "主诉和病程符合",
      "next_steps": "建议完善血常规等检查"
    }
  ]
}
```

### 6.8 生成质控修复文本

`POST /ai/qc-fix`

响应：

```json
{ "fix_text": "建议直接写入病历的修复文本" }
```

### 6.9 快速质控

`POST /ai/quick-qc`

请求：

```json
{
  "content": "完整病历文本",
  "record_type": "outpatient"
}
```

响应：

```json
{
  "issues": [
    {
      "risk_level": "high",
      "field_name": "allergy_history",
      "issue_description": "过敏史未填写",
      "suggestion": "请补充过敏史"
    }
  ],
  "summary": "发现 1 个高风险问题",
  "pass": false
}
```

---

## 七、质控问题模块 `/qc-issues`

### 7.1 更新质控问题状态

`PATCH /qc-issues/{issue_id}`

请求：

```json
{ "status": "resolved" }
```

---

## 八、后台管理模块 `/admin`

以下接口均要求管理员角色：`super_admin`、`hospital_admin`、`dept_admin`

### 8.1 用户管理

- `GET /admin/users`
- `POST /admin/users`
- `PUT /admin/users/{user_id}`
- `DELETE /admin/users/{user_id}`

### 8.2 科室管理

- `GET /admin/departments`
- `POST /admin/departments`
- `DELETE /admin/departments/{dept_id}`

### 8.3 质控规则管理

- `GET /admin/qc-rules`
- `POST /admin/qc-rules`
- `PUT /admin/qc-rules/{rule_id}`
- `PUT /admin/qc-rules/{rule_id}/toggle`
- `DELETE /admin/qc-rules/{rule_id}`

### 8.4 Prompt 模板管理

- `GET /admin/prompts`
- `POST /admin/prompts`
- `PUT /admin/prompts/{prompt_id}`
- `DELETE /admin/prompts/{prompt_id}`

### 8.5 统计接口

- `GET /admin/stats/overview`
- `GET /admin/stats/usage`
- `GET /admin/stats/qc-issues`
- `GET /admin/stats/token-usage`

说明：`usage` 和 `qc-issues` 当前为占位实现，返回内容较少。

### 8.6 管理员查看病历

`GET /admin/records?page=1&page_size=20&doctor_id=<optional>`

---

## 九、当前默认测试账号

- 管理员：`admin / admin123456`
- 医生：`doctor01 / doctor123`

---

## 十、说明

- 当前系统同时存在两套病历流程：
  - `quick` 快捷接口流程：已接入前端工作台
  - `record-centric` 完整病历流程：后端已实现一部分，但前端主流程暂未全面接入
- 如果后续决定收敛为单一接口体系，应以本文件为基础继续整理，而不是继续沿用旧版目标文档。
