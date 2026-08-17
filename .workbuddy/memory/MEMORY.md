# 项目长期记忆 · 中美出口管制时间线

## 项目目标
追踪特朗普5月访华后至今，美方对华出口管制/制裁/关税/贸易救济 + 中方对应反制，呈现为交互式时间线HTML（横/竖屏双模式+反制弧线+A3打印）。

## 方法论权威文件
**`检索逻辑与方法论.md`**（工作区根目录）是自动化检索的权威依据，更新逻辑先改该文件。

## 关键约定（用户确认 v2）
- **双语检索**：美方优先英文、中方优先中文
- **中方反制法律体系**（用户总结，见方法论C2）：主工具=反制清单/恶意实体清单/阻断办法/不可靠实体清单/禁止限制出口目录/两用物项清单/管控名单/关注名单；辅助=反垄断/暂停进口/网安审查/数据出境评估/反歧视/反规避/贸易救济
- **分析必引公众号**：合规观澜、贸易夜航、合规视点（至少引一个），叠加研报/行业分析
- **频率**：每日3次 00:00/08:50/18:00 + 手动触发
- **核实硬性**：只收官网已发布；放风/草案/旧闻不收；OFAC同质归并；**每条必须核实年份是2026（防跨年旧闻）**
- **美方监测维度新增**：ITC 337调查（有限排除令/禁止令/初裁终裁）——已纳入方法论C1"贸易救济/ITC"行，检索词含`ITC 337 investigation China 2026`
- **防溢出**：state.json记last_date，锚点追加不整读HTML，日志30天轮转
- **部署**：WorkBuddy自动化(大脑)+CloudStudio(公网URL)

## 产物
- `outputs/中美出口管制时间线.html`（EVENTS内嵌，39节点/59动作，截至2026-08-17；含8/17 ITC 337 DRAM投诉受理(DN 3930,联想被告)+8/17 DOC铝型材AD复审终裁+8/6补录玻璃钢门板AD/CVD双反税令(FR Doc 2026-16033)+8/6网信办对Palo Alto Networks网络安全审查+8/3无缝钢管第三次日落复审立案+8/11二氟甲烷反倾销令继续+8/6补录7项贸易救济(钢制货架/钢绞线日落复审+防腐剂令继续+铝容器/面巾纸反规避立案)+8/13白宫《大转运骗局》报告+8/14 DOC乘用车轮胎AD复审终裁+8/14 ITC咔唑紫颜料23号日落复审终止+8/13特朗普无人机关税232公告+8/13 ITC 337墨盒普遍排除令+8/6 ITC 337 LCD玻璃基板终裁+8/6 BIS黑粉/钨废料DPA+8/6多晶硅232+8/11 ITC日落复审+8/12木质卧室家具反倾销复审+8/4 DOC钢瓶/集装箱底盘日落复审+8/5中方五项反制+7/30 OFAC马汉航空+8/4 INKSNA+8/7 OFAC伊影子银行）
- 事件数据结构：date/type/cat/agency/brief/依据/行动/分析/原文/来源/url

## GitHub Pages 部署（已替代COS）
- GitHub仓库：`w53418791-glitch/us-china-timeline`（public）
- 固定URL：`https://w53418791-glitch.github.io/us-china-timeline/`
- 上传脚本：`.workbuddy/upload_to_github.py`（**改用GitHub Contents API PUT**，不再用git CLI——后者因Windows sandbox safe-delete冲突反复Permission denied，导致"本地有远程没"问题）
- 旧脚本 `.workbuddy/upload_to_cos.py` 已改为转发到GitHub脚本（自动化prompt不用改）
- Token: <GITHUB_TOKEN_PLACEHOLDER>（存在脚本中）
- COS已弃用（myqcloud.com域名被浏览器当文件存储强制下载）

## 教训
- 监测不能只搜"出口管制/制裁"，必须覆盖贸易救济(反倾销)、海关、认证、网安审查等全工具箱（曾漏碧根果反倾销）
- 放风消息不入（曾误入FCC光模块拟议，后删除）
- 旧闻核实日期（中芯国际拜登时期稿/2020实体清单旧事）
- **编辑陷阱**：系统的 `<omitted>` 标记会**真的写入文件**（不是仅显示省略）；写入 JS 后会让 SyntaxError 导致全部 JS 不执行。**推送前必须用 Node `new Function(lastScript)` 验证语法**；Edit 的 old_string/new_string 须用具体行包住关键锚点，避免被省略标记替换覆盖
- COS 直链(`myqcloud.com`)被国内浏览器/下载器识别为文件存储，强制下载 HTML；改用 GitHub Pages(`github.io`)直接渲染
- **scrollbar与state.json必须同步**：早班删除旧闻后仅更新state.json未更新scrollbar，导致计数不一致(29/34 vs 27/33)；每次操作后两处都要改
- **OFAC涉伊朗次级制裁需专门检索**：曾漏3条(7/30马汉航空GSA+8/4 INKSNA防扩散+8/7伊影子银行)，因检索词偏重"China export control"而未覆盖"OFAC Iran China SDN"等伊朗次级制裁维度；已加强OFAC检索覆盖
- **DPA/DPAS关键矿产出口限制需专门检索**：曾漏8/6 BIS黑粉/钨废料规则(FR Doc 2026-16078)，因检索词偏重"BIS Entity List/EAR"而未覆盖"Defense Production Act critical minerals export restriction"维度；今后C1需增加DPA/DPAS检索词
- **反倾销行政复审终裁易遗漏**：曾漏8/12木质卧室家具反倾销复审终裁(FR Doc 2026-16446)，因FR发布日与中文媒体报道日有1天时差(8/12发布→8/13报道)，且检索词未覆盖"antidumping administrative review final results China"；今后需增加美DOC ITA反倾销复审检索维度
- **232条款无人机关税需关注白宫proclamation**：8/13特朗普签公告对进口无人机及零部件征10%-100%关税，依据232条款，非FR规则而是总统公告；检索时需覆盖"White House proclamation drone tariff China 2026"维度，不能只搜"Section 232 China federal register"
- **ITC 337普遍排除令(GEO)需专门检索**：曾漏8/13 ITC墨盒337终裁(337-TA-1452，普遍排除令)，因检索词偏重"ITC 337 investigation China exclusion order"而未覆盖"general exclusion order ink cartridge China"；GEO是337条款最强救济，比有限排除令影响更大，今后需增加"ITC general exclusion order China"检索维度
- **DOC双反日落复审终裁易遗漏**：曾漏8/4 DOC对华钢瓶+集装箱底盘双反日落复审终裁(FR Doc 2026-15747/15748)，因这些是快速复审(无中方应诉)且中文媒体报到较少；今后需定期检索"DOC sunset review final results China antidumping"覆盖此类案件
- **FR页面404需跨班重试**：8/14 DOC乘用车轮胎AD复审终裁(FR Doc 2026-16662)晚班抓取时FR页面404，夜班重试成功；FR新发布文档可能延迟可访问，遇404应在下一班次重试
- **ITC日落复审终止(撤销令)也需收录**：8/14 ITC咔唑紫颜料23号日落复审终止(FR Doc 2026-16581)是少见的美方主动撤销对华贸易救济案例，虽为解除限制而非新增限制，仍是贸易救济生命周期事件，应收录以呈现完整图景
- **白宫政策报告/执法公告需检索"White House report"维度**：曾漏8/13白宫OTMP《大转运骗局》报告(24页，指控中国经40国转运规避关税750亿美元/年，推Detective Border AI执法)，因检索词偏重"出口管制/制裁"而未覆盖"White House transshipment report China"维度；该报告与8/13无人机关税公告同日发布但属独立动作，今后需增加"White House report China tariff enforcement"检索维度
- **GitHub上传可能因网络代理SSL拦截失败**：8/15早班+晚班+夜班(3班连续)上传均失败，DNS解析到代理IP 198.18.1.227(198.18.x.x基准测试段)，Python/curl/Node.js/git均SSL握手失败；属网络基础设施问题，待恢复后重试 `.workbuddy/upload_to_github.py`
- **反规避调查(circumvention inquiry)需专门检索**：曾漏8/6铝容器+面巾纸反规避立案(FR Doc 2026-16053/16056)，因检索词偏重"antidumping/countervailing sunset review China"而未覆盖"circumvention inquiry China"维度；反规避调查是贸易救济执法的重要延伸，与白宫反转运报告形成呼应；今后需定期检索"DOC circumvention inquiry China"覆盖此类案件
- **日落复审令继续(continuation notice)也需收录**：曾漏8/6防腐剂(腐蚀抑制剂)第一次日落复审令继续(FR Doc 2026-16052)，这是商务部+ITC联合认定令继续的通知，与日落复审终裁性质相同；今后需定期检索"DOC continuation antidumping countervailing order China"覆盖此类案件
- **日落复审立案(initiation)易遗漏**：曾漏8/3 DOC/ITC对华无缝碳钢和合金钢标准管第三次双反日落复审立案(FR Doc 2026-15663/15646)，因立案(initiation)是程序启动不如终裁受媒体关注，且中文媒体报道滞后(8/3发布→8/11报道)；今后需定期检索"DOC initiation sunset review China"覆盖此类案件
- **二氟甲烷(R-32)等化工产品反倾销令继续需覆盖**：曾漏8/11 DOC对华二氟甲烷反倾销令第一次日落复审令继续(FR Doc 2026-16297)，因检索词偏重"steel/aluminum"等金属产品而未覆盖化工产品；今后需扩大检索范围至"DOC continuation antidumping order China chemical"
- **AD/CVD新税令发布(order issuance)不同于日落复审/复审终裁，需专门检索**：曾漏8/6 DOC对华玻璃钢门板AD/CVD双反税令(FR Doc 2026-16033)，这是基于ITC最终损害裁定后正式发布的新税令(order issuance)，与日落复审终裁/行政复审终裁属不同程序阶段；检索时需覆盖"DOC antidumping countervailing duty order China issuance"维度，不能只搜"sunset review/administrative review"
- **网信办网络安全审查需专门检索**：曾漏8/6网信办对美企派拓公司(Palo Alto Networks)在华产品网络安全审查，因检索词偏重"商务部/外交部反制"而未覆盖"网信办 网络安全审查 外国企业"维度；网安审查是中方反制工具箱的重要辅助工具，今后C2需增加"网信办 cybersecurity review foreign company"检索维度
- **ITC 337投诉受理通知(Notice of Receipt of Complaint)也需收录**：曾漏8/17 ITC收到Netlist对DRAM器件337调查投诉(DN 3930, FR Doc 2026-16763)，联想集团(中国)被列为被告之一；投诉受理通知是337调查生命周期的第一步(先于正式立案)，虽ITC尚未决定是否立案，但已在联邦公报正式发布且涉及中国企业；今后需定期检索"ITC 337 complaint receipt China"覆盖此类案件；同一FR发布日可能有多条对华相关文件(8/17同时发布铝型材AD复审+DRAM 337投诉)，需逐条核查FR搜索结果不可只取第一条
