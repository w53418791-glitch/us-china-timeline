#!/usr/bin/env python3
"""推送中美出口管制时间线HTML到GitHub Pages（用Contents API PUT，绕过git CLI的safe-delete冲突）"""
import os, base64, json, urllib.request

OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'outputs')
HTML_FILE = os.path.join(OUTPUTS_DIR, '中美出口管制时间线.html')
GITHUB_URL = 'https://w53418791-glitch.github.io/us-china-timeline/'
TOKEN = '<GITHUB_TOKEN_PLACEHOLDER>'
REPO = 'w53418791-glitch/us-china-timeline'
API_URL = f'https://api.github.com/repos/{REPO}/contents/index.html'

# 1. 读取本地HTML
with open(HTML_FILE, 'rb') as f:
    content_b64 = base64.b64encode(f.read()).decode()
print(f'✅ 已读取本地HTML ({os.path.getsize(HTML_FILE)} bytes)')

# 2. 查远程文件 SHA（PUT 必须带 sha 才能覆盖已有文件）
req_get = urllib.request.Request(API_URL, headers={
    'Authorization': f'token {TOKEN}',
    'Accept': 'application/vnd.github+json'
})
try:
    with urllib.request.urlopen(req_get) as r:
        sha = json.loads(r.read().decode()).get('sha', '')
    print(f'远程当前 sha: {sha[:10]}...')
except urllib.error.HTTPError as e:
    if e.code == 404:
        sha = ''  # 文件不存在，首次创建
        print('远程尚无 index.html，首次创建')
    else:
        raise

# 3. PUT 上传
req_put = urllib.request.Request(API_URL, method='PUT', headers={
    'Authorization': f'token {TOKEN}',
    'Accept': 'application/vnd.github+json',
    'Content-Type': 'application/json'
}, data=json.dumps({
    'message': 'auto-update timeline',
    'content': content_b64,
    'sha': sha
}).encode())
try:
    with urllib.request.urlopen(req_put) as r:
        body = json.loads(r.read().decode())
        print(f'✅ 推送成功！commit: {body.get("commit",{}).get("sha","")[:10]}...')
except urllib.error.HTTPError as e:
    err = e.read().decode()
    print(f'❌ 推送失败 {e.code}: {err[:300]}')
    exit(1)

print(f'固定链接: {GITHUB_URL}')
print('注：GitHub Pages 约 30-60 秒后自动重建')
