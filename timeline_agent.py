#!/usr/bin/env python3
"""
中美出口管制时间线自动更新 - GitHub Actions 云端版
完全在 GitHub 服务器上运行，不需要电脑开机
- 检索：官方源直抓（白宫/OFAC/ITC/商务部/外交部 官网）+ Federal Register API
- 公众号素材：合规观澜/贸易夜航/合规视点/聆听美讯/USA yesterday（仅分析引用）
- LLM：DeepSeek V3 API（官方动作核实+结构化+分析）
- 推送：GitHub Contents API PUT
"""

import os, json, re, base64, urllib.request, urllib.parse, time
from datetime import datetime, date

# ========== 配置 ==========
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
REPO = 'w53418791-glitch/us-china-timeline'
TODAY = datetime.now().strftime('%Y-%m-%d')
# 兼容 Windows(%-m不支持)与Linux：手动去前导零
_now = datetime.now()
TODAY_CN = f'{_now.year}年{_now.month}月{_now.day}日'

# ========== 1. 读 state.json ==========
def read_state():
    url = f'https://raw.githubusercontent.com/{REPO}/main/.workbuddy/state.json'
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

# ========== 2. 信息源直抓（信源即检索对象） ==========

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'}

def fetch_url(url, timeout=20):
    """带 UA 抓取网页文本"""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f'  抓取失败 [{url[:60]}]: {str(e)[:80]}')
        return ''

def whitehouse_search(last_date):
    """白宫 presidential-actions 页直抓（proclamation/行政令/备忘录一手源）"""
    html = fetch_url('https://www.whitehouse.gov/presidential-actions/')
    if not html:
        return []
    results = []
    seen = set()
    months = {'January':1,'February':2,'March':3,'April':4,'May':5,'June':6,'July':7,'August':8,'September':9,'October':10,'November':11,'December':12}
    # 白宫列表: 每条 <li>…<time>August 26, 2026</time>…<h2><a href>标题</a></h2>
    # 按 li 分块解析
    for li in re.findall(r'<li[^>]*data-wp-key[^>]*>(.*?)</li>', html, re.DOTALL):
        tm = re.search(r'<time[^>]*>([^<]+)</time>', li)
        am = re.search(r'<h[234][^>]*>\s*<a href="(https://www\.whitehouse\.gov/presidential-actions/[^"]+)"[^>]*>(.*?)</a>', li, re.DOTALL)
        if not am:
            continue
        url = am.group(1)
        title = re.sub(r'<[^>]+>', '', am.group(2)).strip()
        title = title.replace('&#8217;', "'").replace('&#8211;', '-').replace('&#038;', '&')
        if not title or url in seen or len(title) < 10:
            continue
        seen.add(url)
        date_fmt = ''
        if tm:
            dt = tm.group(1).strip()
            dm = re.search(r'(\w+) (\d{1,2}), (\d{4})', dt)
            if dm:
                date_fmt = f'{dm.group(3)}-{months.get(dm.group(1),0):02d}-{int(dm.group(2)):02d}'
        results.append({'title': title, 'url': url, 'date': date_fmt, 'snippet': '', 'agency': '白宫(White House)', 'source': 'whitehouse.gov(直抓)'})
    # 仅保留 last_date 之后（白宫列表含历史），并预筛涉华/涉贸易技术管制关键词
    wh_keys = ['china', 'tariff', 'sanction', 'export', 'semiconductor', 'chip', 'entity', '232',
               '301', 'trade', 'drone', 'uav', 'critical', 'mineral', 'bulk-power', 'electric',
               'energy', 'grid', 'battery', 'national emergency', 'import', 'foreign', 'supply chain',
               'rare earth', 'military', 'entity list', 'export control', 'investment']
    filtered = []
    for r in results:
        if not r['date'] or r['date'] >= last_date:
            tl = (r['title'] + ' ' + r['url']).lower()
            if any(k in tl for k in wh_keys):
                filtered.append(r)
    print(f'  白宫 actions: {len(filtered)}/{len(results)} 条涉华/涉管制候选 (last_date={last_date} 后)')
    return filtered[:15]

def ofac_search(last_date):
    """OFAC recent-actions 页直抓（SDN/制裁公告一手源）"""
    html = fetch_url('https://ofac.treasury.gov/recent-actions')
    if not html:
        return []
    results = []
    seen = set()
    # 条目形如 <a href="/recent-actions/20260828">Iran-related and Counter Terrorism Designations</a>
    for m in re.finditer(r'<a href="(/recent-actions/\d{8})"[^>]*>(.*?)</a>', html, re.DOTALL):
        url = 'https://ofac.treasury.gov' + m.group(1)
        title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        title = title.replace('&#039;', "'")
        if not title or url in seen:
            continue
        seen.add(url)
        datestr = m.group(1)[-8:]
        date_fmt = f'{datestr[:4]}-{datestr[4:6]}-{datestr[6:]}'
        # 仅取 last_date 之后的（OFAC 列表含历史）
        if date_fmt >= last_date:
            results.append({'title': title, 'url': url, 'date': date_fmt, 'snippet': '', 'agency': '美国财政部OFAC', 'source': 'ofac.treasury.gov(直抓)'})
    print(f'  OFAC recent-actions: {len(results)} 条 (last_date={last_date} 后)')
    return results

def itc_search(last_date):
    """ITC 新闻发布页直抓（337终裁/排除令/双反终裁一手源）
    注: usitc.gov 有 Akamai 反爬(403)，此处失败时由 Federal Register API
    的 international-trade-commission 机构覆盖（ITC裁定均发布于FR）"""
    html = fetch_url('https://www.usitc.gov/press_room/news_release')
    if not html:
        print('  ITC news: 站点反爬(403)，由 FR API international-trade-commission 覆盖')
        return []
    results = []
    seen = set()
    # ITC 新闻标题列表，含日期
    for m in re.finditer(r'<a href="(https://www\.usitc\.gov/press_room/news_release/[^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL):
        url = m.group(1)
        title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if not title or url in seen or len(title) < 10:
            continue
        seen.add(url)
        # 从URL提取日期 (usitc.gov/press_room/news_release/2026/xxxx)
        dm = re.search(r'/(20\d{2})/(\d{2})/', url)
        date_fmt = f'{dm.group(1)}-{dm.group(2)}-01' if dm else ''
        results.append({'title': title, 'url': url, 'date': date_fmt, 'snippet': '', 'agency': '美国国际贸易委员会ITC', 'source': 'usitc.gov(直抓)'})
    print(f'  ITC news: {len(results)} 条候选')
    return results

def federal_register_search(last_date):
    """Federal Register API 免费 - 搜美方对华动作（官方源 API 保留）"""
    url = f'https://www.federalregister.gov/api/v1/documents.json'
    params = {
        'conditions[term]': 'China',
        'conditions[publication_date][gte]': last_date,
        'conditions[agencies][]': ['commerce-department', 'international-trade-commission', 'international-trade-administration', 'defense-department', 'foreign-assets-control-office', 'trade-representative-office-of-united-states', 'treasury-department', 'homeland-security-department'],
        'per_page': 30,
        'order': 'newest'
    }
    url = url + '?' + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'timeline-agent/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        results = []
        for doc in data.get('results', [])[:20]:
            ags = doc.get('agencies') or []
            results.append({
                'title': doc.get('title', ''),
                'url': doc.get('html_url', ''),
                'date': doc.get('publication_date', ''),
                'snippet': (doc.get('abstract') or '')[:300],
                'agency': ags[0].get('name', '') if ags else '',
                'source': 'federalregister.gov(API)'
            })
        return results
    except Exception as e:
        print(f'  Federal Register 搜索失败: {e}')
        return []

def gzh_crosscheck_search(last_date):
    """公众号 crosscheck 检索（合规观澜/贸易夜航/合规视点/聆听美讯/USA yesterday）
    用公众号名+关键词在 Google News 检索，命中结果仅作分析引用素材，不作事件收录源"""
    gzh_names = ['合规观澜', '贸易夜航', '合规视点', '聆听美讯', 'USA yesterday']
    results = []
    for name in gzh_names:
        for kw in ['出口管制', '制裁', '关税', '反制', '实体清单']:
            q = f'"{name}" {kw}'
            try:
                base = 'https://news.google.com/rss/search'
                params = {'q': q, 'hl': 'zh-CN', 'gl': 'CN', 'ceid': 'CN:zh-Hans'}
                url = base + '?' + urllib.parse.urlencode(params)
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=12) as r:
                    data = r.read().decode('utf-8', errors='ignore')
                items = re.findall(r'<item>(.*?)</item>', data, re.DOTALL)
                for item in items[:3]:
                    t = re.search(r'<title>(.*?)</title>', item, re.DOTALL)
                    link = re.search(r'<link>(.*?)</link>', item, re.DOTALL)
                    title = t.group(1).strip() if t else ''
                    results.append({
                        'title': title,
                        'url': link.group(1) if link else '',
                        'date': '',
                        'snippet': '',
                        'agency': f'公众号:{name}',
                        'source': f'gzh-crosscheck({name})'
                    })
            except Exception:
                pass
    print(f'  公众号crosscheck: {len(results)} 条')
    return results

def _fetch_auto_encode(url, timeout=20):
    """抓取并自动处理 GBK/UTF-8 编码（中方官网多为 GBK），SSL 失败降级不验证"""
    contexts = []
    try:
        import ssl
        contexts.append(ssl.create_default_context())
        contexts.append(ssl._create_unverified_context())  # 部分官网证书链问题
    except Exception:
        pass
    for ctx in contexts:
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read()
            charset = (r.headers.get_content_charset() or '').lower()
            for enc in ([charset] if charset else []) + ['utf-8', 'gb18030']:
                try:
                    return raw.decode(enc)
                except Exception:
                    continue
            return raw.decode('utf-8', errors='ignore')
        except Exception as e:
            last_err = str(e)[:80]
            if 'certificate' not in last_err.lower() and 'ssl' not in last_err.lower():
                # 非SSL错误直接放弃（404/超时等）
                print(f'  抓取失败 [{url[:60]}]: {last_err}')
                return ''
    print(f'  抓取失败 [{url[:60]}]: {last_err}')
    return ''

def mofcom_search(last_date):
    """商务部新闻发布+政策发布页直抓（反制公告/不可靠实体清单/反倾销等一手源）"""
    # 新闻发布栏目（含例行发布会答问/公告）
    html = _fetch_auto_encode('http://www.mofcom.gov.cn/xwfb/index.html')
    # 政策发布栏目（公告/令/办法）
    html2 = _fetch_auto_encode('http://www.mofcom.gov.cn/zwgk/zcfb/index.html')
    full = (html or '') + '\n' + (html2 or '')
    if not full.strip():
        print('  商务部: 抓取失败(跳过)')
        return []
    results = []
    seen = set()
    # 匹配新闻链接与标题（商务部页面常见 /article/ 路径或绝对URL）
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{10,120})</a>', full):
        url = m.group(1)
        title = m.group(2).strip()
        title = re.sub(r'\s+', ' ', title)
        if not title or url in seen or len(title) < 10:
            continue
        # 只取文章类链接
        if 'article' not in url and 'index' in url:
            continue
        if not url.startswith('http'):
            url = 'http://www.mofcom.gov.cn' + (url if url.startswith('/') else '/' + url)
        seen.add(url)
        # 关键词过滤：仅保留涉美/反制类
        if any(k in title for k in ['美国', '反制', '出口管制', '不可靠实体', '反倾销', '反补贴', '清单', '制裁', '关税', '两用物项', '稀土', '贸易救济']):
            results.append({'title': title, 'url': url,
                           'date': '', 'snippet': '', 'agency': '商务部', 'source': 'mofcom.gov.cn(直抓)'})
    print(f'  商务部新闻/政策: {len(results)} 条候选')
    return results[:20]

def mfa_search(last_date):
    """外交部发言人答记者问/例行记者会页直抓（反制回应/涉美表态一手源）"""
    html = _fetch_auto_encode('https://www.mfa.gov.cn/web/wjdt_674879/fyrbt_674889/')
    if not html:
        print('  外交部: 抓取失败(跳过)')
        return []
    results = []
    seen = set()
    # 正文条目: <li><a href="./202608/t2026xxxx.shtml" target="_blank">2026年8月X日外交部发言人...答记者问（2026-08-XX）</a>
    for m in re.finditer(r'<a href="\./(20260?\d/t\d+_\d+\.shtml)"[^>]*>(2026年[^<]{5,100})</a>', html):
        url = 'https://www.mfa.gov.cn/web/wjdt_674879/fyrbt_674889/' + m.group(1)
        title = m.group(2).strip()
        title = re.sub(r'\s+', ' ', title)
        # 从标题提取日期 2026年8月17日
        dm = re.search(r'2026年(\d+)月(\d+)日', title)
        date_fmt = ''
        if dm:
            date_fmt = f'2026-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}'
        if not date_fmt or date_fmt < last_date:
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append({'title': title, 'url': url, 'date': date_fmt,
                       'snippet': '', 'agency': '外交部', 'source': 'mfa.gov.cn(直抓)'})
    print(f'  外交部发言人: {len(results)} 条候选 (last_date={last_date} 后)')
    return results[:20]

# ========== 2b. 公众号反查（reverse check） ==========
def reverse_check_leads(reverse_leads, last_date):
    """依据公众号 reverse_leads 的 keywords 反向在官方源核实
    命中官方条目才返回（作为补录候选）；公众号本身不能作为收录依据"""
    if not reverse_leads:
        return []
    found = []
    print(f'--- 公众号反查: {len(reverse_leads)} 条线索 ---')
    for lead in reverse_leads[:5]:
        keywords = lead.get('keywords') or []
        title_hint = lead.get('动作摘要', '')[:40]
        if not keywords:
            continue
        hit = None
        # 1) FR API 关键词搜索（美方动作主通道）
        for kw in keywords[:3]:
            try:
                url = 'https://www.federalregister.gov/api/v1/documents.json?' + urllib.parse.urlencode({
                    'conditions[term]': kw,
                    'conditions[publication_date][gte]': last_date,
                    'per_page': 5,
                    'order': 'newest'
                })
                req = urllib.request.Request(url, headers={'User-Agent': 'timeline-agent/1.0'})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read().decode())
                for doc in data.get('results', [])[:3]:
                    title = doc.get('title', '')
                    if any(k.lower() in title.lower() for k in keywords if len(k) > 3):
                        hit = {
                            'title': title,
                            'url': doc.get('html_url', ''),
                            'date': doc.get('publication_date', ''),
                            'snippet': (doc.get('abstract') or '')[:200],
                            'agency': 'Federal Register(反查命中)',
                            'source': 'federalregister.gov(公众号反查)',
                            'reverse_hint': title_hint
                        }
                        break
                if hit:
                    break
            except Exception as e:
                print(f'    反查FR失败({kw}): {str(e)[:60]}')
        # 2) 白宫 actions 关键词匹配
        if not hit and any(k in title_hint for k in ['公告', '关税', 'proclamation', 'tariff', '行政令', 'executive']):
            try:
                wh_html = fetch_url('https://www.whitehouse.gov/presidential-actions/')
                if wh_html:
                    for li in re.findall(r'<li[^>]*data-wp-key[^>]*>(.*?)</li>', wh_html, re.DOTALL):
                        am = re.search(r'<h[234][^>]*>\s*<a href="(https://www\.whitehouse\.gov/presidential-actions/[^"]+)"[^>]*>(.*?)</a>', li, re.DOTALL)
                        if not am:
                            continue
                        t = re.sub(r'<[^>]+>', '', am.group(2)).strip()
                        tl = t.lower()
                        if any(k.lower() in tl for k in keywords if len(k) > 3):
                            hit = {'title': t, 'url': am.group(1), 'date': '',
                                   'snippet': '', 'agency': '白宫(反查命中)',
                                   'source': 'whitehouse.gov(公众号反查)', 'reverse_hint': title_hint}
                            break
            except Exception:
                pass
        if hit:
            print(f'  ✅ 反查命中: {hit["title"][:60]} (线索: {title_hint})')
            found.append(hit)
        else:
            print(f'  ⏭ 反查无官方命中, 不收录: {title_hint}')
    return found

# ========== 3. DeepSeek 核实+结构化 ==========
def deepseek_verify(search_results, last_date, methodology, existing_events=None, gzh_material=None):
    """用 DeepSeek V3 核实搜索结果并输出结构化事件
    gzh_material: 公众号(合规观澜等5个)检索素材，仅作"分析"字段引用参考，不决定是否收录"""
    
    # 构建 prompt
    results_text = '\n'.join([
        f"[{i+1}] {r.get('title','')}\n    URL: {r.get('url','')}\n    日期: {r.get('date','')}\n    摘要: {r.get('snippet','')}\n    来源: {r.get('agency','')}\n    信源类型: {r.get('source','')}"
        for i, r in enumerate(search_results)
    ])
    
    # 已收录事件摘要（用于跨轮次语义查重）
    existing_text = ''
    if existing_events:
        existing_text = '\n'.join([
            f"- [{e.get('date','')}] ({e.get('type','')}) {e.get('agency','')}: {e.get('brief','')[:90]}"
            for e in existing_events[-25:]  # 只给最近25条，省token
        ])

    # 公众号素材（分析引用用）
    gzh_text = ''
    if gzh_material:
        gzh_text = '\n'.join([
            f"- {r.get('agency','')}: {r.get('title','')[:80]}"
            for r in gzh_material[:20]
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
  "reverse_leads": [
    {{
      "title": "公众号报道标题",
      "动作摘要": "公众号描述的已落地动作(制裁/反制/关税等)",
      "gzh": "报道公众号名",
      "推测机构": "如 OFAC/BIS/白宫/商务部/外交部",
      "推测日期": "YYYY-MM-DD(如可判断)",
      "keywords": ["英文检索词", "中文检索词"]  
    }}
  ],
  "summary": "本轮检索总结",
  "new_count": 0
}}

reverse_leads 规则：从"公众号检索素材"中识别**公众号明确报道已落地(非吹风)、但本轮候选官方动作中未见对应条目**的新动作线索（最多5条）。每条给2-4个检索词用于反向在官方源核实。若全部对应已有候选/已收录，返回空数组。

## 核实规则（硬性）
0. **候选来源说明**：候选已改为**官方源直抓**（白宫 presidential-actions / OFAC recent-actions / Federal Register / ITC / 商务部 / 外交部官网），信源类型标注在每条"信源类型"字段，默认可信度高。你的任务是**核实该官方动作是否确为对华相关新动作 + 提取结构化字段**，而非再判断来源网站可信度。
1. 只收录 last_date({last_date}) 之后发布的新正式动作
2. 放风/草案/独家消息一律不收
3. 年份三重验证：URL年份/正文日期/事件上下文，剔除2025年及更早旧闻
4. ITC仅收终裁/初裁/排除令/禁止令；不收立案/投诉受理/日落复审/程序启动
5. 不补录前序遗漏，只收 last_date 之后的新动作
6. 分析部分必须引用合规观澜、贸易夜航、合规视点、聆听美讯、USA yesterday 至少一个公众号（若暂无专题则标注"公众号暂无专题，分析综合其他权威源"）
7. **主体识别**：必须明确涉及中国政府/企业/实体，或美方明确针对中国；泛指"外国"的总统公告（如232/电力行政令）虽未点名中国但影响中国也收录，需在分析中说明影响路径
8. **公众号 crosscheck**：每条事件应在合规观澜/贸易夜航/合规视点/聆听美讯/USA yesterday 中至少 crosscheck 1 个，确认该公众号有同步报道或分析；若5个公众号均无任何提及，标注"公众号暂无专题"并在分析中说明信息源局限
9. **跨轮次语义查重（硬性·最高优先级）★★★**：以下"已收录事件清单"是时间线中已有的事件。候选若与清单中任何一条属同一事件——同一诉讼/同一公告/同一制裁行动，仅因不同媒体转载或报道日期差1-2天——**一律判定为重复，不收**。判定标准：主体机构+行动对象+事件类型相同，且brief/标题语义近似（如"长鑫起诉国防部"各媒体转载、同一232公告的不同报道、同一英伟达白名单事件）。重复是时间线最严重缺陷，宁可漏收不可重收。
10. **吹风词硬性拦截（硬性）★★★**：候选标题/内容若含以下"未落地"信号词——weighs/mulls/considers/reportedly/said to be preparing/计划/考虑/酝酿/拟/网传/知情人士/正在研究/可能征收/或对——且**无官方正式公告**（白宫 proclamation/FR Doc/行政令/正式新闻稿）确认已签署生效，**一律不收**。白宫官员回应"除非正式宣布否则视为猜测"的消息尤其不收。判据：必须已发生（signed/filed/issued/finalized/listed），而非"正在考虑"。
11. **解读/评论类文章不得作为事件源（硬性）★★★**：来源为**律所分析、行业研究机构、咨询公司博客**的文章，若其正文是在解读/回顾已发生动作（引用旧日期/旧命令编号作为背景），**即使文章新发布也不收**——这类文章是二手评论，不是官方新动作。9/2 事故：律所文章把8/24 OFAC经济驱逐重述为"启动Operation Economic Outcast扩大次级制裁"、行业机构把8/26行政令重述为"限制BESS进口"，均判重复剔除。
12. **"回顾旧动作"识别（硬性）★★**：候选若正文明确引用 last_date 之前的动作日期（如"8月13日公告""8月24日制裁""8月26日行政令"）或既有命令编号（第14420号/FR Doc 2026-xxx），且其"新意"仅是解读、预测后续影响——**不收为新事件**，判为旧事件解读。只有官方正式发布的新动作（新FR Doc/新名单/新命令/新公告）才收。
13. **白宫/OFAC直抓条目筛选**：白宫 presidential-actions 列表含大量无关条目（纪念日、太空学院等），**仅收录涉华/涉贸易/涉技术管制的条目**（proclamation/行政令/备忘录中涉及 China/tariff/sanction/export/semiconductor/entity/232/301/紧急状态限制等），无关条目剔除。OFAC recent-actions 同理仅收涉中国主体或伊朗次级制裁牵连中企的条目。
"""

    user_prompt = f"""今天是{TODAY}。last_date={last_date}。

以下是候选官方动作（{len(search_results)}条），请核实并输出结构化事件：

{results_text}

请严格按规则筛选，只输出确认有效的 2026 年新正式动作。如果全部不符合，返回空数组。"""

    if existing_events:
        user_prompt += f"""

## 时间线已收录事件（近25条，用于跨轮次查重，严禁重复收录）
{existing_text}

请逐条比对：若上面的候选与这些已收录事件属同一事件（同诉讼/同公告/同制裁，仅媒体或日期不同），必须判为重复剔除。"""

    if gzh_text:
        user_prompt += f"""

## 公众号检索素材（合规观澜/贸易夜航/合规视点/聆听美讯/USA yesterday）
以下为本轮公众号名检索命中。公众号素材有**双重作用**：
1. **分析引用**：判断某公众号是否有相关专题，供"分析"字段引用（不影响收录）
2. **反查线索（重要）**：若某公众号**明确报道了一个已落地的制裁/反制裁动作**（已签署/已列入/已生效，非吹风非评论），但上面的候选官方动作里**看不到对应条目**——说明该动作可能被官方源直抓遗漏，请填入 reverse_leads，给出检索词供反向核实。

{gzh_text}"""

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
    
    # 3. 检索（信息源直抓：官方源为收录依据，公众号为分析素材）
    all_results = []

    # 3a. 美方官方源直抓（信源即检索对象，源头权威无需过滤）
    print('--- 美方官方源直抓 ---')
    wh = whitehouse_search(last_date)
    all_results.extend(wh)
    of = ofac_search(last_date)
    all_results.extend(of)
    it = itc_search(last_date)
    all_results.extend(it)

    # 3b. Federal Register API（官方源 API 保留）
    print('--- Federal Register API ---')
    fr_results = federal_register_search(last_date)
    all_results.extend(fr_results)
    print(f'  Federal Register → {len(fr_results)} 条')

    # 3c. 中方官方源检索：商务部/外交部官网公告页直抓（可访问时）
    print('--- 中方官方源直抓 ---')
    cn_official_results = mofcom_search(last_date) + mfa_search(last_date)
    all_results.extend(cn_official_results)

    # 3d. 公众号 crosscheck 检索（5个公众号：合规观澜/贸易夜航/合规视点/聆听美讯/USA yesterday）
    #     结果标记 source=gzh-*，只作分析引用素材，不作事件收录源
    print('--- 公众号 crosscheck 检索 ---')
    gzh_results = gzh_crosscheck_search(last_date)
    all_results.extend(gzh_results)
    
    # 去重
    seen_urls = set()
    unique_results = []
    for r in all_results:
        url = r.get('url', '')
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_results.append(r)
    # 公众号素材单列（不占 DeepSeek 主核实额度，仅作分析素材库）
    gzh_material = [r for r in unique_results if 'gzh-crosscheck' in r.get('source','')]
    official_results = [r for r in unique_results if 'gzh-crosscheck' not in r.get('source','')]
    print(f'总计: {len(all_results)} 条候选, 去重后 {len(unique_results)} 条 (官方源 {len(official_results)} + 公众号素材 {len(gzh_material)})')
    
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
    # 官方源结果送主核实（公众号素材另传作分析参考）
    verify_input = official_results[:35] if official_results else unique_results[:30]
    result = deepseek_verify(verify_input, last_date, methodology, existing_events, gzh_material)
    new_events = result.get('new_events', [])
    summary = result.get('summary', '')
    new_count = result.get('new_count', len(new_events))
    reverse_leads = result.get('reverse_leads') or []
    print(f'DeepSeek 返回: {len(new_events)} 条新事件, {len(reverse_leads)} 条反查线索')
    print(f'总结: {summary}')

    # 4a. 公众号反查: reverse_leads 反向在官方源核实命中后补入候选，二次确认
    if reverse_leads:
        reverse_hits = reverse_check_leads(reverse_leads, last_date)
        if reverse_hits:
            # 反查命中项与已有候选/已收录去重后送 DeepSeek 二次确认
            print(f'反查命中 {len(reverse_hits)} 条, 送 DeepSeek 二次确认...')
            result2 = deepseek_verify(reverse_hits, last_date, methodology, existing_events, gzh_material)
            new_from_reverse = result2.get('new_events', [])
            if new_from_reverse:
                print(f'  反查确认收录: {len(new_from_reverse)} 条')
                # 标注来源含公众号反查
                for e in new_from_reverse:
                    src = e.get('来源', '')
                    if '反查' not in src:
                        e['来源'] = (src + ' / 公众号反查确认' if src else '公众号反查确认')
                new_events.extend(new_from_reverse)
            else:
                print('  反查命中项经 DeepSeek 核实不符收录规则, 不收录')
    
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
