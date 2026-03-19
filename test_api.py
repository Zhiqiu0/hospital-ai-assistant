import json, subprocess

import urllib.request
req = urllib.request.Request(
    'http://localhost:8000/api/v1/auth/login',
    data=b'{"username":"admin","password":"admin123456"}',
    headers={'Content-Type': 'application/json'},
    method='POST'
)
with urllib.request.urlopen(req) as resp:
    token = json.load(resp)['access_token']

BASE = 'http://localhost:8000/api/v1'
ENC_ID = 'a7e7b0b2-685c-463e-88b3-54a833feb63a'
auth = f'Authorization: Bearer {token}'

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

results = []

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
results.append(('科室列表', f'✅ {len(r)} depts' if isinstance(r, list) else '❌ ' + str(r)[:100]))

# 5. QC rules
r = curl_get('/admin/qc-rules')
results.append(('质控规则', f'✅ {len(r)} rules' if isinstance(r, list) else '❌ ' + str(r)[:100]))

# 6. Prompts
r = curl_get('/admin/prompts')
results.append(('Prompt模板', f'✅ {len(r)} prompts' if isinstance(r, list) else '❌ ' + str(r)[:100]))

# 7. Stats overview
r = curl_get('/admin/stats/overview')
results.append(('统计概览', '✅ keys=' + str(list(r.keys())) if isinstance(r, dict) and '_raw' not in r else '❌ ' + str(r)[:100]))

# 8. Admin records
r = curl_get('/admin/records?page=1&page_size=5')
results.append(('管理员-病历管理', f'✅ total={r.get("total")}' if 'total' in r else '❌ ' + str(r)[:100]))

# 9. Token usage
r = curl_get('/admin/stats/token-usage')
results.append(('Token用量', '✅ keys=' + str(list(r.keys())[:4]) if isinstance(r, dict) and '_raw' not in r else '❌ ' + str(r)[:100]))

# 10. check-username (no auth needed)
r = api('GET', '/auth/check-username?username=admin')
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

print('\n' + '='*50)
print('  API 测试结果')
print('='*50)
for name, res in results:
    print(f'  {name}: {res}')
print('='*50)
