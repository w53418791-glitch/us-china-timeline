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
def deepseek_verify(search_results, last_date, methodology, existing_events=None):
    """用 DeepSeek V3 核实搜索结果并输出结构化事件"""
    
    # 构建 prompt
    results_text = '\n'.join([
        f"[{i+1}] {r.get('title','')}\n    URL: {r.get('url','')}\n    日期: {r.get('date','')}\n    摘要: {r.get('snippet','')}\n    来源: {r.get('agency','')}"
        for i, r in enumerate(search_results)
    ])
    
    # 已收录事件摘要（用于跨轮次语义查重）
    existing_text = ''
    if existing_events:
        existing_text = '\n'.join([
            f"- [{e.get('date','')}] ({e.get('type','')}) {e.get('agency','')}: {e.get('brief','')[:90]}"
            for e in existing_events[-25:]  # 只给最近25条，省token
        ])
    
    system_prompt = f"""你是中美出口管制博弈时间线的自动更新助手。严格按以下规则工作：

{methodology[:3500]}

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
      "分析": "逐条AI分析(为何用/逻辑/意义)——必须引用合规观澜/贸易夜航/合规视点/聆听美讯/USA yesterday至少一个",
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
2. 放风/草案/独家消息一律不收
3. 年份三重验证：URL年份/正文日期/事件上下文，剔除2025年及更早旧闻
4. ITC仅收终裁/初裁/排除令/禁止令；不收立案/投诉受理/日落复审/程序启动
5. 不补录前序遗漏，只收 last_date 之后的新动作
6. 分析部分必须引用合规观澜、贸易夜航、合规视点、聆听美讯、USA yesterday 至少一个公众号（若暂无专题则标注"公众号暂无专题，分析综合其他权威源"）
7. **主体识别**：必须明确涉及中国政府/企业/实体，或美方明确针对中国；泛指"外国"的总统公告（如232/电力行政令）虽未点名中国但影响中国也收录，需在分析中说明影响路径
8. **公众号 crosscheck**：每条事件应在合规观澜/贸易夜航/合规视点/聆听美讯/USA yesterday 中至少 crosscheck 1 个，确认该公众号有同步报道或分析；若5个公众号均无任何提及，标注"公众号暂无专题"并在分析中说明信息源局限
9. **跨轮次语义查重（硬性·最高优先级）★★★**：以下"已收录事件清单"是时间线中已有的事件。候选新闻若与清单中任何一条属同一事件——同一诉讼/同一公告/同一制裁行动，仅因不同媒体转载或报道日期差1-2天——**一律判定为重复，不收**。判定标准：主体机构+行动对象+事件类型相同，且brief/标题语义近似（如"长鑫起诉国防部"各媒体转载、同一232公告的不同报道、同一英伟达白名单事件）。重复是时间线最严重缺陷，宁可漏收不可重收。
10. **吹风词硬性拦截（硬性）★★★**：候选标题/内容若含以下"未落地"信号词——weighs/mulls/considers/reportedly/said to be preparing/计划/考虑/酝酿/拟/网传/知情人士/正在研究/可能征收/或对——且**无官方正式公告**（白宫 proclamation/FR Doc/行政令/正式新闻稿）确认已签署生效，**一律不收**。白宫官员回应"除非正式宣布否则视为猜测"的消息尤其不收。判据：必须已发生（signed/filed/issued/finalized/listed），而非"正在考虑"。
11. **来源可信度分级（硬性）**：仅由非权威站点（tech-insider.org/economy.ac/LawStreet Journal/自媒体/SEO站等）报道、无任何官方源或权威媒体（白宫/FR/财政部/Reuters/Bloomberg/新华社等）背书的"新动作"——多为二手转译或AI聚合，**不收**。正式动作必须有官方链接（.gov/.mil/官网）或权威媒体交叉确认。
12. **解读/评论类文章不得作为事件源（硬性·9/2事故新增）★★★**：来源为**律所分析（如globaltradeandsanctionslaw.com等）、行业研究机构（如Benchmark Mineral Intelligence等）、咨询公司博客**的文章，若其正文是在解读/回顾已发生动作（提到"8月24日行动""第14420号行政令""Operation Economic Outcast"等旧日期/旧编号作为背景），**即使文章新发布也不收**——这类文章是二手评论，不是官方新动作。判据：正文中引用的动作日期/编号对应的时间线已有事件，无任何新的FR Doc/制裁名单/公告/命令。9/2 事故：律所文章把8/24 OFAC经济驱逐重述为"启动Operation Economic Outcast扩大次级制裁"、行业机构把8/26行政令重述为"限制BESS进口"，均判重复剔除。
13. **"回顾旧动作"识别（硬性）★★**：候选文章若正文明确引用 last_date 之前的动作日期（如"8月13日公告""8月24日制裁""8月26日行政令"）或既有命令编号（第14420号/FR Doc 2026-xxx），且其"新意"仅是解读、预测后续影响——**不收为新事件**，判为旧事件解读。只有官方正式发布的新动作（新FR Doc/新名单/新命令/新公告）才收。
"""

    user_prompt = f"""今天是{TODAY}。last_date={last_date}。

以下是搜索到的候选新闻（{len(search_results)}条），请核实并输出结构化事件：

{results_text}

请严格按规则筛选，只输出确认有效的 2026 年新正式动作。如果全部不符合，返回空数组。"""

    if existing_events:
        user_prompt += f"""

## 时间线已收录事件（近25条，用于跨轮次查重，严禁重复收录）
{existing_text}

请逐条比对：若上面的候选新闻与这些已收录事件属同一事件（同诉讼/同公告/同制裁，仅媒体或日期不同），必须判为重复剔除。"""

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
    anchor = '];\n\nconst MONTH='
    if anchor not in html_content:
        # 尝试其他锚点
        anchor = '];'
        # 找最后一个 ];
        last_semicolon = html_content.rfind('];')
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
    
    # 美方英文搜索 (12维，覆盖全工具箱)
    us_queries = [
        # BIS 出口管制
        f'BIS Entity List China export control {last_date}',
        f'BIS EAR China dual-use {last_date}',
        # OFAC 制裁（含涉伊朗次级制裁）
        f'OFAC SDN China sanctions {last_date}',
        f'OFAC Iran China secondary sanctions {last_date}',
        # 白宫 proclamation（232关税/行政令）
        f'White House proclamation China tariff {last_date}',
        f'White House executive order China {last_date}',
        # 国务院制裁
        f'State Department sanctions China {last_date}',
        # FCC
        f'FCC China covered list {last_date}',
        # USTR 301
        f'USTR 301 tariff China {last_date}',
        # ITC 337（含普遍排除令 GEO）
        f'ITC 337 China exclusion order final {last_date}',
        f'ITC general exclusion order China {last_date}',
        # DHS UFLPA
        f'DHS UFLPA China entity list {last_date}',
        # DPA/DPAS 关键矿产出口限制
        f'Defense Production Act China critical minerals {last_date}',
        # DOC 贸易救济（反倾销/反规避/日落复审）
        f'DOC antidumping China review final {last_date}',
        f'DOC circumvention inquiry China {last_date}',
        f'DOC sunset review China continuation {last_date}',
    ]
    for q in us_queries:
        results = google_news_search(q, 'en')
        all_results.extend(results)
        print(f'  搜索: {q[:50]}... → {len(results)} 条')

    # Federal Register API
    fr_results = federal_register_search(last_date)
    all_results.extend(fr_results)
    print(f'  Federal Register → {len(fr_results)} 条')

    # 中方中文搜索 (10维，覆盖反制法律体系)
    cn_queries = [
        # 外交部/商务部 反制清单
        f'商务部 反制 出口管制 {last_date}',
        f'外交部 反制 美国 {last_date}',
        # 不可靠实体清单
        f'不可靠实体清单 {last_date}',
        # 网信办 网络安全审查
        f'网信办 网络安全审查 {last_date}',
        # 中方贸易救济（反倾销初裁）
        f'商务部 反倾销 初裁 美国 {last_date}',
        # 阻断办法
        f'商务部 阻断 不当域外管辖 {last_date}',
        # 反歧视/反规避调查
        f'商务部 反歧视 调查 美国 {last_date}',
        # 海关暂停进口
        f'海关总署 暂停进口 美国 {last_date}',
        # 两用物项/管控名单
        f'两用物项 出口管制 清单 {last_date}',
        # 稀土出口限制
        f'稀土 出口限制 美国 {last_date}',
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
    # 读现有 index.html 提取已收录事件（供跨轮次查重）
    existing_events = []
    try:
        index_file = get_github_file('index.html')
        index_html = base64.b64decode(index_file['content']).decode('utf-8')
        # 提取近25条事件摘要
        m = re.search(r'const EVENTS=\[([\s\S]*?)\];\s*\n\s*const MONTH', index_html)
        if m:
            import json as _json
            events_str = '[' + m.group(1) + ']'
            # 优先用 Node 解析（兼容 JSON 与手写无引号key两种格式）
            node_ok = False
            try:
                import subprocess, tempfile, os as _os
                node_path = _os.environ.get('NODE_PATH_BIN', r'C:\Users\31044\.workbuddy\binaries\node\versions\22.22.2-2\node.exe')
                if not _os.path.exists(node_path):
                    # GitHub Actions 环境用系统 node
                    node_path = 'node'
                # 把 events_str 写临时 js 文件由 node 解析
                tmp_js = tempfile.mktemp(suffix='.js')
                with open(tmp_js, 'w', encoding='utf-8') as f:
                    f.write('const evs = ' + events_str + '; console.log(JSON.stringify(evs.slice(-30)));')
                r = subprocess.run([node_path, tmp_js], capture_output=True, text=True, encoding='utf-8', timeout=20)
                _os.remove(tmp_js)
                if r.returncode == 0 and r.stdout.strip():
                    parsed = _json.loads(r.stdout.strip())
                    existing_events = parsed
                    node_ok = True
            except Exception:
                pass
            if not node_ok:
                # fallback: json.loads（标准JSON格式）
                try:
                    parsed = _json.loads(events_str)
                    existing_events = parsed[-25:]
                except Exception:
                    # 非标准JSON（手写无引号key），用正则粗提取 date+brief
                    ev_dates = re.findall(r'date\s*:\s*["\']?(\d{4}-\d{2}-\d{2})', m.group(1))
                    ev_briefs = re.findall(r'brief\s*:\s*["\']([^"\']{0,90})', m.group(1))
                    for d, b in zip(ev_dates[-25:], ev_briefs[-25:]):
                        existing_events.append({'date': d, 'brief': b})
    except Exception as e:
        print(f'  读取已有事件失败(不影响本轮): {e}')
    print(f'已收录事件(供查重): {len(existing_events)} 条')
    result = deepseek_verify(unique_results[:30], last_date, methodology, existing_events)
    new_events = result.get('new_events', [])
    summary = result.get('summary', '')
    new_count = result.get('new_count', len(new_events))
    print(f'DeepSeek 返回: {len(new_events)} 条新事件')
    print(f'总结: {summary}')
    
    # 4b. 二次硬过滤：吹风词 + 与已收录事件语义重复的硬拦截（Python侧兜底）
    WIND_WORDS = ['考虑', '酝酿', '拟', '网传', '知情人士', '正在研究', '可能征收', '或对', 'weighs', 'mulls', 'considers', 'reportedly', 'preparing']
    # 语义重复关键词表：事件主体/行动对象特征词（覆盖历史所有事故品类）
    DUP_KEYS = ['长鑫', 'CXMT', '英伟达', 'Nvidia', '白名单', '无人机', '芯片关税', 'laptop', 'server', '1260H', '实体清单',
                'SDN', 'Kameng', '电力设备', 'BESS', '储能', '电网', '行政令', 'Executive Order', '14420',
                '反倾销', '337', '日落', 'UFLPA', '涉疆', '多晶硅', '无人机', '232', '301',
                '经济驱逐', '次级制裁', '伊朗', 'Iran', 'OFAC', '制裁', 'sanction',
                '反制清单', '不可靠实体', '稀土', '镓', '锗', '网络安全审查', '半导体', 'chip']
    if new_events:
        filtered = []
        for e in new_events:
            text = (e.get('brief','') + e.get('行动','') + e.get('原文','')).lower()
            # 吹风词拦截
            wind_hit = [w for w in WIND_WORDS if w.lower() in text]
            if wind_hit:
                print(f'  拦截吹风词 {wind_hit}: {e.get("brief","")[:50]}')
                continue
            # 与已收录事件语义重复拦截：日期窗口±10天 + 共享特征词（brief+行动双字段比对）
            dup = False
            new_date = e.get('date','')
            eb = (e.get('brief','') or '') + ' ' + (e.get('行动','') or '')
            for oe in existing_events:
                ob = (oe.get('brief','') or '') + ' ' + (oe.get('行动','') or '')
                od = oe.get('date','')
                if len(ob) < 8:
                    continue
                # 日期窗口：±10天内（解读文章/转载日期可能滞后数天至一周）
                in_window = False
                try:
                    from datetime import datetime as _dt
                    nd = _dt.strptime(new_date, '%Y-%m-%d') if new_date else None
                    odt = _dt.strptime(od, '%Y-%m-%d') if od else None
                    if nd and odt:
                        in_window = abs((nd - odt).days) <= 10
                except Exception:
                    pass
                shared = [k for k in DUP_KEYS if k.lower() in eb.lower() and k.lower() in ob.lower()]
                # 共享≥1个高区分度特征词且窗口内 → 判重复
                if shared and in_window:
                    print(f'  拦截语义重复(共享{shared}, {od}±10天内): [{new_date}]{(e.get("brief","") or "")[:45]} vs [{od}]{(oe.get("brief","") or "")[:45]}')
                    dup = True
                    break
                # 即使日期超窗，若共享词≥2且同月也拦（防滞后更久的解读）
                if len(shared) >= 2 and new_date and od and new_date[:7] == od[:7]:
                    print(f'  拦截语义重复(共享{shared}, 同月): [{new_date}]{(e.get("brief","") or "")[:45]} vs [{od}]{(oe.get("brief","") or "")[:45]}')
                    dup = True
                    break
            if not dup:
                filtered.append(e)
        if len(filtered) < len(new_events):
            print(f'二次过滤: {len(new_events)} → {len(filtered)} 条')
        new_events = filtered
    
    # 5. 更新 HTML
    if new_events:
        # 读 index.html
        index_file = get_github_file('index.html')
        html = base64.b64decode(index_file['content']).decode('utf-8')
        
        # 追加新事件
        html = append_events(html, new_events)
        
        # JS 语法自检（防坏数据上线，历史教训：SyntaxError导致白屏）
        try:
            m_ev = re.search(r'const EVENTS=\[([\s\S]*?)\];\s*\n\s*const MONTH', html)
            if m_ev:
                import subprocess, tempfile, os as _os
                node_path = r'C:\Users\31044\.workbuddy\binaries\node\versions\22.22.2-2\node.exe'
                if _os.path.exists(node_path):
                    tmp_html = tempfile.mktemp(suffix='.html')
                    with open(tmp_html, 'w', encoding='utf-8') as f:
                        f.write(html)
                    env = dict(_os.environ)
                    env['TMP_HTML'] = tmp_html
                    js_check = r"const fs=require('fs');const h=fs.readFileSync(process.env.TMP_HTML,'utf-8');const m=h.match(/const EVENTS=\[([\s\S]*?)\];\s*\n\s*const MONTH/);if(!m)process.exit(1);new Function('return ['+m[1]+']')();"
                    r = subprocess.run([node_path, '-e', js_check], capture_output=True, text=True, encoding='utf-8', env=env, timeout=30)
                    _os.remove(tmp_html)
                    if r.returncode != 0:
                        print(f'❌ JS 语法自检失败，跳过推送: {r.stderr[:200]}')
                        return
                    print('✅ JS 语法自检通过')
        except Exception as e:
            print(f'  JS 自检异常(继续): {e}')
        
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
