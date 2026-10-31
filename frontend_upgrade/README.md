# FrameBurn 前端升级包（可直接复制）

> 目录定位：`Scrape_gen_AI_video/frontend_upgrade`

这个目录是为 `FrameBurn` 产出的“可复制前端结果包”，目标是：

- 页面结构与 `FrameBurn` 当前核心功能一致；
- 保留“竞品洞察 + 模板一键填充”能力；
- 提升交互防呆（视频模式文件必填、空提示词拦截、轮询稳定性）；
- 可用临时网站本地预览（无需连接真实生成引擎）。

## 包含文件

- `index.html`：升级后的页面结构（含 insights 洞察区）
- `app.js`：升级后的交互脚本（任务轮询、历史画廊、模板注入、模式校验）
- `preview_server.py`：本地临时预览服务（内置 Mock API）
- `preview.png`：预览截图（如存在）

## 如何本地预览（临时网站）

在当前仓库环境中运行：

1. 进入目录：`Scrape_gen_AI_video/frontend_upgrade`
2. 启动预览服务：`python preview_server.py`
3. 浏览器打开：`http://127.0.0.1:8787/`

预览服务会提供以下模拟接口，保证页面交互可演示：

- `/health`
- `/api/v1/versions`
- `/api/v1/functions`
- `/api/v1/insights/short-video-sites`
- `/api/v1/tasks`（创建/查询/删除/下载）

> 说明：预览模式用于看页面结构与流程，不产出真实视频文件。

## 如何接入真实 FrameBurn 项目

如果你要把这套页面接到真实后端：

1. 将 `index.html` 和 `app.js` 复制到：
   - `FrameBurn/frameburn_platform/app/static/`
2. 启动真实 FrameBurn 服务（FastAPI）
3. 访问根路径 `/`（由真实后端返回页面）

真实接口契约已对齐 FrameBurn 当前实现（`/api/v1/tasks`、`/api/v1/insights/short-video-sites` 等）。

## 本次修复重点

- 修复：Scrape 产物与 FrameBurn 主站功能分叉（缺失 insights 洞察区）
- 修复：`视频生成` 模式缺少前端必填提示与校验
- 修复：任务轮询在多入口触发时可能出现并发轮询
- 修复：画廊在“仅剩已删除任务”时显示逻辑不准确
- 强化：模板一键填充后自动同步质量/时长/模式状态

## 建议下一步

- 接入真实 `final.mp4` 回放与缩略图（目前预览服务为 Mock）
- 增加“失败任务重试”快捷按钮（携带原参数）
- 增加“回收站恢复”页面（已对齐后端软删除语义）
