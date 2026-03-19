import urllib.request, urllib.error, json

def login():
    req = urllib.request.Request(
        'http://localhost:8000/api/v1/auth/login',
        data=b'{"username":"admin","password":"admin123456"}',
        headers={'Content-Type': 'application/json'}, method='POST'
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)['access_token']

token = login()
BASE = 'http://localhost:8000/api/v1'

def api(method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body else None
    req = urllib.request.Request(BASE+path, data=data, method=method,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as r: return json.load(r)
    except urllib.error.HTTPError as e:
        try: return json.load(e)
        except: return {'_err': e.code, '_raw': e.read().decode()[:300]}

print("=== departments full response ===")
r = api('GET', '/admin/departments')
print(type(r), list(r.keys()) if isinstance(r, dict) else f'list len={len(r)}')
if isinstance(r, dict): print('items count:', len(r.get('items', [])))

print("\n=== qc-rules full response ===")
r = api('GET', '/admin/qc-rules')
print(type(r), list(r.keys()) if isinstance(r, dict) else f'list len={len(r)}')
if isinstance(r, dict): print('items count:', len(r.get('items', [])))

print("\n=== prompts full response ===")
r = api('GET', '/admin/prompts')
print(type(r), list(r.keys()) if isinstance(r, dict) else f'list len={len(r)}')
if isinstance(r, dict): print('items count:', len(r.get('items', [])))

print("\n=== save inquiry response ===")
ENC_ID = 'a7e7b0b2-685c-463e-88b3-54a833feb63a'
r = api('PUT', f'/encounters/{ENC_ID}/inquiry', {'chief_complaint': '测试主诉'})
print(r)

print("\n=== admin/stats/token-usage ===")
r = api('GET', '/admin/stats/token-usage')
print(r)
