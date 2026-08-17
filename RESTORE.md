# 中美出口管制时间线 · 项目恢复指南

本仓库是"中美出口管制博弈时间线"项目的**单一真相源**，包含全部关键文件。在新电脑上恢复项目的步骤如下。

## 一、项目概览

- **产物**：`index.html`（交互式时间线，横/竖屏双模式+反制弧线+A3打印）
- **固定链接**：https://w53418791-glitch.github.io/us-china-timeline/
- **自动化**：3 条 WorkBuddy 定时任务（00:00 / 08:50 / 18:00），自动检索→更新→推送
- **数据截至**：2026-08-17，39 节点 / 59 动作

## 二、仓库文件结构

```
us-china-timeline/
├── index.html                          ← 时间线产物（GitHub Pages 自动渲染）
├── 中美出口管制时间线.html              ← 原始文件名副本
├── 检索逻辑与方法论.md                  ← 自动化大脑（检索维度/核实规则/频率）
├── RESTORE.md                          ← 本文件
├── .workbuddy/
│   ├── state.json                      ← 状态（last_date/节点数/动作数）
│   ├── upload_to_github.py             ← 推送脚本（GitHub Contents API PUT）
│   ├── upload_to_cos.py                ← 旧COS脚本（转发到upload_to_github.py）
│   └── memory/
│       ├── MEMORY.md                   ← 项目长期记忆
│       └── 2026-08-10.md ~ 2026-08-17.md  ← 每日工作日志
```

## 三、新电脑恢复步骤

### 第 1 步：登录 WorkBuddy，开新对话

在 WorkBuddy 中开一个新的工作区（或复用现有工作区），开新对话。

### 第 2 步：跟 WorkBuddy 说

> "从 GitHub 拉取 us-china-timeline 项目恢复"

WorkBuddy 会：
1. 用 `git clone https://github.com/w53418791-glitch/us-china-timeline.git` 克隆仓库到工作区
2. 把仓库里的文件恢复到对应位置：
   - `检索逻辑与方法论.md` → 工作区根目录
   - `index.html` → `outputs/中美出口管制时间线.html`
   - `.workbuddy/state.json` → `.workbuddy/state.json`
   - `.workbuddy/upload_to_github.py` → `.workbuddy/upload_to_github.py`
   - `.workbuddy/memory/*` → `.workbuddy/memory/`
3. 读取 `MEMORY.md` 和 `检索逻辑与方法论.md` 获取完整上下文

### 第 3 步：重建 3 条定时自动化

跟 WorkBuddy 说：

> "重建时间线的 3 条定时自动化（00:00 / 08:50 / 18:00）"

WorkBuddy 会用 `automation_update` 工具创建 3 条 recurring 自动化，prompt 内容从 `检索逻辑与方法论.md` 的流程章节生成，cwds 指向新工作区路径。

### 第 4 步：验证

- 打开 https://w53418791-glitch.github.io/us-china-timeline/ 确认时间线可访问
- 跟 WorkBuddy 说"手动检索一次"验证流程正常

## 四、关键配置

| 项 | 值 |
|---|---|
| GitHub 仓库 | `w53418791-glitch/us-china-timeline`（public） |
| GitHub Token | `<GITHUB_TOKEN_PLACEHOLDER>` |
| GitHub Pages URL | `https://w53418791-glitch.github.io/us-china-timeline/` |
| 推送方式 | GitHub Contents API PUT（不用 git CLI，避免 safe-delete 冲突） |
| 自动化频率 | 每日 3 次：00:00 / 08:50 / 18:00（北京时间） |
| Python 路径 | `C:\Users\31044\.workbuddy\binaries\python\versions\3.13.12\python.exe`（新电脑可能不同，需调整） |

## 五、注意事项

1. **VPN/代理**：推送 GitHub API 时需关闭 VPN 或将 `api.github.com` 加入直连规则，否则 SSL 握手失败
2. **电脑需开机**：WorkBuddy 自动化是桌面级调度，电脑关机/休眠时不跑
3. **年份核实**：检索时必须三重验证（URL年份/正文日期/事件上下文），防 2025 年旧闻混入（见方法论 E 节）
4. **放风消息不收**：草案/拟议/独家消息一律不收录，只收官网已正式发布的动作
5. **Token 安全**：GitHub Token 存在 `upload_to_github.py` 中，泄露风险——长期建议改用环境变量或 GitHub Secrets
