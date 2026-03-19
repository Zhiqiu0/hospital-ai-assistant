import json
import os
import urllib.request
from urllib.parse import urlencode
req = urllib.request.Request(
    'http://localhost:8000/api/v1/auth/login',
    data=b'{"username":"admin","password":"admin123456"}',
    headers={'Content-Type': 'application/json'},
    method='POST'
)
with urllib.request.urlopen(req) as resp:
    token = json.load(resp)['access_token']

BASE = os.getenv('MEDASSIST_API_BASE', 'http://localhost:8010/api/v1')

import urllib.error

def api(method, path, body=None):
    url = BASE + path
    data = json.dumps(body, ensure_ascii=False).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    })
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try: return json.load(e)
        except: return {'_err': e.code, '_raw': e.read().decode()[:200]}
    except Exception as e:
        return {'_exc': str(e)[:200]}

def curl_get(path): return api('GET', path)
def curl_put(path, body): return api('PUT', path, body)
def curl_post(path, body): return api('POST', path, body)


encounter = curl_post('/encounters/quick-start', {
    'patient_name': 'API Test Patient',
    'gender': 'male',
    'age': 35,
    'phone': '13900007777',
    'visit_type': 'outpatient',
})
ENC_ID = encounter.get('encounter_id')

results = []

results.append(('快速建档', '✅ ' + ENC_ID if ENC_ID else '❌ ' + str(encounter)[:100]))

# 1. Save inquiry
r = curl_put(f'/encounters/{ENC_ID}/inquiry', {
    'chief_complaint': 'Test chief complaint',
    'history_present_illness': 'Test history',
    'past_history': 'HTN 5 years',
    'allergy_history': 'No known allergies',
    'physical_exam': 'T:36.8 BP:130/80',
    'initial_impression': 'Gastritis'
})
results.append(('保存问诊信息', '✅' if r.get('chief_complaint') else '❌ ' + str(r)[:100]))

# 2. Medical records list
r = curl_get('/medical-records/my')
results.append(('历史病历列表', f'✅ total={r.get("total")}' if 'total' in r else '❌ ' + str(r)[:100]))

# 3. Admin users
r = curl_get('/admin/users?page=1&page_size=5')
results.append(('管理员-用户列表', f'✅ total={r.get("total")}' if 'total' in r else '❌ ' + str(r)[:100]))

# 4. Departments
r = curl_get('/admin/departments')
dept_items = r.get('items', r) if isinstance(r, dict) else r
results.append(('科室列表', f'✅ {len(dept_items)} depts' if isinstance(dept_items, list) else '❌ ' + str(r)[:100]))

# 5. QC rules
r = curl_get('/admin/qc-rules')
rule_items = r.get('items', r) if isinstance(r, dict) else r
results.append(('质控规则', f'✅ {len(rule_items)} rules' if isinstance(rule_items, list) else '❌ ' + str(r)[:100]))

# 6. Prompts
r = curl_get('/admin/prompts')
prompt_items = r.get('items', r) if isinstance(r, dict) else r
results.append(('Prompt模板', f'✅ {len(prompt_items)} prompts' if isinstance(prompt_items, list) else '❌ ' + str(r)[:100]))

# 6.1 Model configs
r = curl_get('/admin/model-configs')
results.append(('模型配置', f'✅ {len(r)} scenes' if isinstance(r, list) else '❌ ' + str(r)[:100]))

# 7. Stats overview
r = curl_get('/admin/stats/overview')
results.append(('统计概览', '✅ keys=' + str(list(r.keys())) if isinstance(r, dict) and '_raw' not in r else '❌ ' + str(r)[:100]))

# 8. Admin records
r = curl_get('/admin/records?page=1&page_size=5')
results.append(('管理员-病历管理', f'✅ total={r.get("total")}' if 'total' in r else '❌ ' + str(r)[:100]))

# 9. Token usage
r = curl_get('/admin/stats/token-usage')
results.append(('Token用量', '✅ keys=' + str(list(r.keys())[:4]) if isinstance(r, dict) and '_raw' not in r else '❌ ' + str(r)[:100]))

# 10. check-username
r = curl_get('/auth/check-username?' + urlencode({'username': 'admin'}))
results.append(('check-username', '✅ exists=' + str(r.get('exists')) if 'exists' in r else '❌ ' + str(r)[:100]))

# 11. AI quick-qc
r = curl_post('/ai/quick-qc', {'content': 'Test record content', 'record_type': 'outpatient'})
results.append(('AI质控(quick-qc)', '✅ has issues field' if 'issues' in r else '❌ ' + str(r)[:100]))

# 12. Exam suggestions
r = curl_post('/ai/exam-suggestions', {'chief_complaint': '头痛', 'history_present_illness': '3天头痛', 'initial_impression': '偏头痛'})
results.append(('检查建议', '✅ ' + str(len(r.get('suggestions', []))) + ' suggestions' if 'suggestions' in r else '❌ ' + str(r)[:100]))

# 13. Diagnosis suggestion
r = curl_post('/ai/diagnosis-suggestion', {'chief_complaint': '头痛', 'history_present_illness': '3天头痛'})
results.append(('诊断建议', '✅ ' + str(len(r.get('diagnoses', []))) + ' diagnoses' if 'diagnoses' in r else '❌ ' + str(r)[:100]))

# 14. Voice structuring
r = curl_post('/ai/voice-structure', {
    'transcript': '医生问，哪里不舒服。患者说反复发热三天，伴咳嗽咳痰，无胸痛，无药物过敏史，既往否认高血压糖尿病。',
    'visit_type': 'outpatient',
    'patient_name': 'API Test Patient',
    'patient_gender': 'male',
    'patient_age': '35',
})
results.append(('语音整理', '✅ has inquiry+draft' if isinstance(r, dict) and 'inquiry' in r and 'draft_record' in r else '❌ ' + str(r)[:100]))

print('\n' + '='*50)
print('  API 测试结果')
print('='*50)
for name, res in results:
    print(f'  {name}: {res}')
print('='*50)
