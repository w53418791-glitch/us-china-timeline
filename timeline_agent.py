#!/usr/bin/env python3
"""
中美出口管制时间线自动更新 - GitHub Actions 云端版
完全在 GitHub 服务器上运行，不需要电脑开机
- 搜索：Google News RSS（免费）+ Federal Register API（免费）
- LLM：DeepSeek V3 API（搜索结果核实+结构化+分析）
- 推送：GitHub Contents API PUT
"""

import os, json, re, base64, urllib.request, urllib.parse, time
from datetime import datetime, date

# ========== 配置 ==========
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
REPO = 'w53418791-glitch/us-china-timeline'
TODAY = datetime.now().strftime('%Y-%m-%d')
TODAY_CN = datetime.now().strftime('%Y年%-m月%-d日')

# ========== 1. 读 state.json ==========
def read_state():
    url = f'https://raw.githubusercontent.com/{REPO}/main/.workbuddy/state.json'
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

# ========== 2. 搜索 ==========
def google_news_search(query, lang='en'):
    """Google News RSS 免费"""
    base = 'https://news.google.com/rss/search'
    params = {'q': query, 'hl': f'{lang}-US' if lang=='en' else 'zh-CN', 'gl': 'US' if lang=='en' else 'CN', 'ceid': 'US:en' if lang=='en' else 'CN:zh-Hans'}
    url = base + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read().decode('utf-8', errors='ignore')
        # 解析 RSS（简单正则，避免依赖 xml 库）
        items = re.findall(r'<item>(.*?)</item>', data, re.DOTALL)
        results = []
        for item in items[:10]:
            title = re.search(r'<title>(.*?)</title>', item, re.DOTALL)
            link = re.search(r'<link>(.*?)</link>', item, re.DOTALL)
            pub = re.search(r'<pubDate>(.*?)</pubDate>', item, re.DOTALL)
            desc = re.search(r'<description><!\[CDATA\[(.*?)\]\]></description>', item, re.DOTALL)
            results.append({
                'title': title.group(1) if title else '',
                'url': link.group(1) if link else '',
                'date': pub.group(1) if pub else '',
                'snippet': (desc.group(1)[:200] if desc else '')
            })
        return results
    except Exception as e:
        print(f'  Google News 搜索失败: {e}')
        return []

def federal_register_search(last_date):
    """Federal Register API 免费 - 搜美方对华动作"""
    url = f'https://www.federalregister.gov/api/v1/documents.json'
    params = {
        'conditions[term]': 'China',
        'conditions[publication_date][gte]': last_date,
        'conditions[agencies][]': ['commerce-department', 'international-trade-commission', 'defense-department', 'office-of-the-foreign-assets-control', 'united-states-trade-representative'],
        'per_page': 20,
        'order': 'newest'
    }
    url = url + '?' + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'timeline-agent/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        results = []
        for doc in data.get('results', [])[:15]:
            results.append({
                'title': doc.get('title', ''),
                'url': doc.get('html_url', ''),
                'date': doc.get('publication_date', ''),
                'snippet': doc.get('abstract', '')[:300],
                'agency': doc.get('agencies', [{}])[0].get('name', '') if doc.get('agencies') else ''
            })
        return results
    except Exception as e:
        print(f'  Federal Register 搜索失败: {e}')
        return []

# ========== 3. DeepSeek 核实+结构化 ==========
def deepseek_verify(search_results, last_date, methodology):
    """用 DeepSeek V3 核实搜索结果并输出结构化事件"""
    
    # 构建 prompt
    results_text = '\n'.join([
        f"[{i+1}] {r.get('title','')}\n    URL: {r.get('url','')}\n    日期: {r.get('date','')}\n    摘要: {r.get('snippet','')}\n    来源: {r.get('agency','')}"
        for i, r in enumerate(search_results)
    ])
    
    system_prompt = f"""你是中美出口管制博弈时间线的自动更新助手。严格按以下规则工作：

{methodology[:4000]}

## 输出格式
返回 JSON 对象，格式如下：
{{
  "new_events": [
    {{
      "date": "YYYY-MM-DD",
      "type": "us" 或 "cn" 或 "dialog",
      "cat": "bis/fcc/ofac/dod/dhs/ustr/mofcom/other-cn/trade/337/贸易救济",
      "agency": "机构名",
      "badge": "us" 或 "cn",
      "brief": "时间线一行简述(30字内)",
      "依据": "基于xx规章/清单/调查",
      "行动": "采取xx行动(详细描述)",
      "分析": "逐条AI分析(为何用/逻辑/意义)——必须引用合规观澜/贸易夜航/合规视点至少一个",
      "原文": "原文引用",
      "来源": "来源",
      "url": "来源URL"
    }}
  ],
  "summary": "本轮检索总结",
  "new_count": 0
}}

## 核实规则（硬性）
1. 只收录 last_date({last_date}) 之后发布的新正式动作
2. 放风/草案/独家消息一律不收\n2. **主体识别**：必须查清主体是谁做了什么——第三方报告/评论不收，只收政府机构正式动作\n3. **吹风/拟议不收**：彭博/路透援引知情人士的拟议/考虑消息不收\n4. **公众号权重**：合规观澜/贸易夜航/合规视点/聆听美讯为权威源
3. 年份三重验证：URL年份/正文日期/事件上下文，剔除2025年及更早旧闻
4. ITC仅收终裁/初裁/排除令/禁止令；不收立案/投诉受理/日落复审/程序启动
5. 不补录前序遗漏，只收 last_date 之后的新动作
6. 分析部分必须引用合规观澜、贸易夜航、合规视点至少一个公众号（若暂无专题则标注"公众号暂无专题，分析综合其他权威源"）
"""

    user_prompt = f"""今天是{TODAY}。last_date={last_date}。

以下是搜索到的候选新闻（{len(search_results)}条），请核实并输出结构化事件：

{results_text}

请严格按规则筛选，只输出确认有效的 2026 年新正式动作。如果全部不符合，返回空数组。"""

    # 调用 DeepSeek API
    url = 'https://api.deepseek.com/chat/completions'
    payload = json.dumps({
        'model': 'deepseek-chat',
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ],
        'temperature': 0.1,
        'max_tokens': 4000
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    })
    
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
        content = data['choices'][0]['message']['content']
        # 提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            return json.loads(json_match.group())
        print('  DeepSeek 返回非JSON格式')
        return {'new_events': [], 'summary': content[:200], 'new_count': 0}
    except Exception as e:
        print(f'  DeepSeek API 调用失败: {e}')
        return {'new_events': [], 'summary': f'API错误: {e}', 'new_count': 0}

# ========== 4. HTML 追加 ==========
def get_github_file(path):
    encoded = urllib.parse.quote(path, safe='/')
    url = f'https://api.github.com/repos/{REPO}/contents/{encoded}'
    req = urllib.request.Request(url, headers={
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'timeline-agent'
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    return data

def put_github_file(path, content, sha, message):
    encoded = urllib.parse.quote(path, safe='/')
    url = f'https://api.github.com/repos/{REPO}/contents/{encoded}'
    b64 = base64.b64encode(content.encode('utf-8')).decode()
    payload = json.dumps({
        'message': message,
        'content': b64,
        'sha': sha
    }).encode()
    req = urllib.request.Request(url, method='PUT', data=payload, headers={
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'timeline-agent'
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status

def append_events(html_content, new_events):
    """在 EVENTS 数组末尾追加新事件"""
    # 构建 JS 对象字符串
    events_js = ''
    for e in new_events:
        events_js += ',\n\n' + json.dumps(e, ensure_ascii=False)
    
    # 在 ];\n\nconst MONTH= 前追加
    # 用正则匹配 ]; 后面跟 const MONTH（兼容 \r\n 和 \n 换行）
    import re as _re
    _anchor_match = _re.search(r'\];\s*const MONTH=', html_content)
    if _anchor_match:
        anchor = _anchor_match.group()
    else:
        anchor = None
    if anchor not in html_content:
        # 尝试其他锚点
        # 找 EVENTS 数组后的第一个 ];
        events_start = html_content.find('const EVENTS=')
        if events_start == -1:
            print('  ERROR: const EVENTS= not found')
            return html_content
        anchor = '];'
        last_semicolon = html_content.find('];', events_start)
        if last_semicolon == -1:
            print('  ERROR: 找不到 EVENTS 数组结尾锚点 ];')
            return html_content
        events_js += '\n];'
        return html_content[:last_semicolon] + events_js + html_content[last_semicolon+2:]
    
    events_js += '\n];\n\nconst MONTH='
    html_content = html_content.replace(anchor, events_js, 1)  # 只替换第一个
    return html_content

def update_scrollbar(html_content, nodes, actions):
    """更新 scrollbar-hint 计数"""
    # 匹配 <b>数字</b> 个日期节点
    html_content = re.sub(
        r'共 <b>\d+</b> 个日期节点.*?<b>\d+</b> 项动作[^<]*',
        f'共 <b>{nodes}</b> 个日期节点 · <b>3</b> 场一轨对话 · <b>{actions}</b> 项动作（ITC仅收337终裁/排除令+双反终裁；不收立案/初裁/日落复审）· 数据截至 {TODAY}',
        html_content
    )
    # 更新 header range
    html_content = re.sub(
        r'时间范围：<b>[^<]+</b>.*?数据截至[^<]*',
        f'时间范围：<b>2026年5月13日 — {TODAY_CN}</b>　·　数据截至 {TODAY_CN}',
        html_content
    )
    return html_content

# ========== 5. 主流程 ==========
def main():
    print(f'=== 中美出口管制时间线自动更新 ({TODAY}) ===')
    
    # 1. 读 state
    state = read_state()
    last_date = state.get('last_date', '2026-08-19')
    date_nodes = state.get('date_nodes', 32)
    action_count = state.get('action_count', 56)
    print(f'last_date={last_date}, nodes={date_nodes}, actions={action_count}')
    
    # 2. 读方法论
    methodology_file = get_github_file('检索逻辑与方法论.md')
    methodology = base64.b64decode(methodology_file['content']).decode('utf-8')
    print(f'方法论长度: {len(methodology)} chars')
    
    # 3. 搜索（双语并行）
    all_results = []
    
    # 美方英文搜索
    us_queries = [
        f'BIS Entity List China export control {last_date}',
        f'OFAC SDN China sanctions {last_date}',
        f'FCC China covered list {last_date}',
        f'USTR 301 tariff China {last_date}',
        f'ITC 337 China exclusion order final {last_date}',
        f'DHS UFLPA China entity list {last_date}',
        f'Trump executive order China power grid electric {last_date}',
        f'White House executive order bulk power system China {last_date}',
        f'whitehouse.gov China sanctions {last_date}',
        f'State Department China sanctions {last_date}',
        f'OFAC SDN China Hong Kong {last_date}',
        f'Treasury sanctions China entity {last_date}',
        f'White House executive order bulk power system China {last_date}',
    ]
    for q in us_queries:
        results = google_news_search(q, 'en')
        all_results.extend(results)
        print(f'  搜索: {q[:50]}... → {len(results)} 条')
    
    # Federal Register API
    fr_results = federal_register_search(last_date)
    all_results.extend(fr_results)
    print(f'  Federal Register → {len(fr_results)} 条')
    
    # 中方中文搜索
    cn_queries = [
        f'商务部 反制 出口管制 {last_date}',
        f'外交部 反制 美国 {last_date}',
        f'网信办 网络安全审查 {last_date}',
        f'反倾销 反补贴 美国 {last_date}',
        f'不可靠实体清单 {last_date}',
        f'合规观澜 制裁 中国 {last_date}',
        f'贸易夜航 制裁 出口管制 {last_date}',
        f'合规视点 OFAC BIS {last_date}',
        f'聆听美讯 制裁 关税 {last_date}',
    ]
    for q in cn_queries:
        results = google_news_search(q, 'zh')
        all_results.extend(results)
        print(f'  搜索: {q[:50]}... → {len(results)} 条')
    
    # 去重
    seen_urls = set()
    unique_results = []
    for r in all_results:
        url = r.get('url', '')
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_results.append(r)
    print(f'总计: {len(all_results)} 条搜索结果, 去重后 {len(unique_results)} 条')
    
    # 4. DeepSeek 核实+结构化
    print('调用 DeepSeek API 核实...')
    result = deepseek_verify(unique_results[:30], last_date, methodology)
    new_events = result.get('new_events', [])
    summary = result.get('summary', '')
    new_count = result.get('new_count', len(new_events))
    print(f'DeepSeek 返回: {len(new_events)} 条新事件')
    print(f'总结: {summary}')
    
    # 5. 更新 HTML
    if new_events:
        # 读 index.html
        index_file = get_github_file('index.html')
        html = base64.b64decode(index_file['content']).decode('utf-8')
        
        # 追加新事件
        html = append_events(html, new_events)
        
        # 更新计数
        new_nodes = date_nodes  # 需要根据新事件计算
        new_actions = action_count + len(new_events)
        for e in new_events:
            if e.get('date') and e['date'] not in html[:html.rfind('];')]:  # 粗略检查新日期
                new_nodes += 1
        
        html = update_scrollbar(html, new_nodes, new_actions)
        
        # 推送 index.html
        status = put_github_file('index.html', html, index_file['sha'], f'auto-update: {len(new_events)} new events ({TODAY})')
        print(f'推送 index.html: {status}')
        
        # 更新 state.json
        state['last_date'] = TODAY
        state['date_nodes'] = new_nodes
        state['action_count'] = new_actions
        state['note'] = f'{TODAY} GitHub Actions自动更新: 新增{len(new_events)}条事件'
        
        state_file = get_github_file('.workbuddy/state.json')
        put_github_file('.workbuddy/state.json', json.dumps(state, ensure_ascii=False, indent=2), state_file['sha'], f'update state ({TODAY})')
        print('state.json 已更新')
    else:
        # 无新事件，仍更新 last_date
        state['last_date'] = TODAY
        state['note'] = f'{TODAY} GitHub Actions: 本轮无新正式动作'
        state_file = get_github_file('.workbuddy/state.json')
        put_github_file('.workbuddy/state.json', json.dumps(state, ensure_ascii=False, indent=2), state_file['sha'], f'update state - no new events ({TODAY})')
        print('本轮无新正式动作，state.json last_date 已更新')
    
    print(f'=== 完成 ({TODAY}) ===')

if __name__ == '__main__':
    main()
