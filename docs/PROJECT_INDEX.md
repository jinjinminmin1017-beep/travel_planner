# Project Index

更新日期：2026-07-19

## 技术栈

- 前端：Expo / React Native、React 19、TypeScript。
- 后端：FastAPI、Pydantic v2、Uvicorn、pytest、httpx；根目录 `.env` 由项目内 ENV loader 一次性加载。
- 数据与合同：`backend/app/models/schemas.py` 为后端 Pydantic 合同，`schemas/*.schema.json` 为导出的 JSON Schema，`frontend/src/types/index.ts` 为前端类型。
- CI：GitHub Actions，覆盖 schema export/diff、后端测试、前端 typecheck、Expo export、Provider 配置与公开 smoke。

## 主要目录

- `frontend/`：Expo App 工程。
- `frontend/src/App.tsx`：当前 App 主界面、状态与用户流程聚合入口。
- `frontend/src/api/`：后端 API client。
- `frontend/src/types/`：前端 TypeScript 合同类型。
- `frontend/src/utils/`：展示格式化工具。
- `frontend/src/components/`：规划状态、正常结果、路线详情和约束无匹配页面组件。
- `frontend/src/pages/`：目录存在，当前未发现页面文件或路由文件。
- `frontend/assets/`：地图与目的地静态视觉资源。
- `backend/`：FastAPI 后端工程。
- `browser_worker/`：独立 Node.js/Playwright 常驻浏览器进程；第一阶段只实现东航/上航 handler，通过 loopback 内部接口向后端返回脱敏统一航班结构。
- `backend/app/main.py`：后端应用、middleware、异常处理与全部路由注册入口。
- `backend/app/models/`：Pydantic schema/model。
- `backend/app/services/`：规划、解析、推荐、重算、结果集偏好传播、存储、可观测性等业务服务层；结果集席别传播位于 `result_set_preferences.py`。
- `backend/app/services/rail_connection_matcher.py`：铁路两段完整 offer 的确定性连接匹配、同站身份校验、跨站动态换乘门槛与诊断指标。
- `backend/app/services/constraints/`：V1.16 分类型约束计算、安全门禁、Pareto 筛选和最近备选选择。
- `backend/app/data_sources/`：地图、地理编码、铁路、航班、天气、LLM、跳转和数据源配置适配器。
  - `config_loader.py`：从 `TRAVEL_DATA_SOURCE_IDS` 与 `TRAVEL_SOURCE_<ID>_*` 构造不可变、类型化的 ENV-only 配置快照。
  - `provider_registry.py`：统一的 adapter settings model 与 Provider factory 注册表；启用源在启动期完成构造校验。
  - `rate_limiter.py`：按 source_id 共享的线程安全 HTTP 请求门控，使外部 Provider 的 `QPS_LIMIT` 在真实请求边界生效。
  - `flight_providers.py`：航班请求构造、响应解析和快照脱敏；已实现春秋航空 `airline_9c_public_query`、海航 `airline_hu_public_query` 与青岛航空 `airline_qw_public_query` 匿名公开票价查询，其他航司仍需独立实现与验证，环境变量不能声明技术就绪。
  - `browser_worker_client.py`、`browser_flight_providers.py`：loopback worker 客户端和浏览器航班 Provider；东航源保持禁用，需完成 URL 模板确认、许可与真实 benchmark 才能启用。
- `backend/app/core/`：请求上下文、安全策略、日志配置。
- `backend/app/data/`：本地数据目录，如交通节点和目的地资产。
- `backend/app/llm/`：Prompt、LLM 调用日志和版本相关文件。
- `backend/app/tests/`：后端 pytest 测试。
- `schemas/`：导出的 API/schema JSON Schema。
- `scripts/`：启动、schema 导出、Provider 配置检查、live smoke、数据导入、质量评估脚本。
- `docs/`：产品任务拆分、架构索引、API 合同和历史文档归档。
- `mock_data/`：路线 mock 数据目录。
- `.github/workflows/`：CI 工作流。

## 入口文件

- 前端入口：`frontend/index.ts`，注册 `frontend/src/App.tsx`。
- 后端入口：`backend/app/main.py`，FastAPI app 对象为 `app`。
- 后端启动命令：`python -m uvicorn app.main:app --reload --app-dir backend`。
- 浏览器 worker 启动命令：`cd browser_worker; npm install; npx playwright install chromium; npm run build; npm run start`。

## API Client

- 位置：`frontend/src/api/client.ts`。
- Base URL：优先读取 `EXPO_PUBLIC_API_BASE_URL`，否则按 Expo dev server 或本地地址推断。
- 已封装接口：规划、异步轮询、重试、取消、数据源状态、重算、跳转、反馈、事件。

## 类型定义

- 后端模型：`backend/app/models/schemas.py`。
- 前端类型：`frontend/src/types/index.ts`。
- JSON Schema：`schemas/*.schema.json`。
- Schema 导出脚本：`scripts/export_schemas.py`。

## 状态管理

- 当前未发现 Redux、Zustand、React Navigation 等独立状态/路由库。
- App 运行时状态集中在 `frontend/src/App.tsx` 的 React state/effects。
- 本地留存、收藏、提醒、偏好与分享能力在 `frontend/src/nativeCapabilities.ts`。

## 数据库与缓存

- 本地持久化服务：`backend/app/services/persistence.py`。
- TTL 缓存服务：`backend/app/services/cache_store.py`。
- 运行时 store：`backend/app/services/store.py`。
- 默认 SQLite 路径配置：`.env.example` 中的 `TRAVEL_SQLITE_PATH=logs/travel_planner.sqlite3`。
- 春秋航空、海航与青岛航空匿名公开查询已分别登记为 `airline_9c_public_query`、`airline_hu_public_query`、`airline_qw_public_query`；报价使用 60 秒进程内缓存，脱敏原始快照与规范化 offer 写入本地 SQLite `logs/flight_harvest.sqlite3`。
- Redis/PostgreSQL 尚未实现，当前不提供对应运行配置。

## 配置文件

- 后端环境模板：`.env.example`。
- 前端环境模板：`frontend/.env.example`。
- 数据源配置：进程环境变量；本地由根目录 `.env` 注入，`.env.example` 是唯一非敏感变量清单。运行时不读取 JSON 配置源。
- Expo 配置：`frontend/app.json`。
- TypeScript 配置：`frontend/tsconfig.json`。

## 常用命令

- 安装后端依赖：`.\.venv\Scripts\python -m pip install -r backend\requirements.txt`
- 启动后端：`.\.venv\Scripts\python -m uvicorn app.main:app --reload --app-dir backend`
- 启动前端：`cd frontend; npm run start`
- 启动脚本：`.\scripts\dev.ps1 -Target backend` / `frontend` / `test`
- 浏览器 worker：`.\scripts\dev.ps1 -Target browser-worker`
- 真机调试：`.\scripts\device-debug.ps1 -OpenQr`
- 后端测试：`.\.venv\Scripts\python -m pytest backend\app\tests`
- 前端 typecheck：`cd frontend; npm run typecheck`
- 前端构建导出：`cd frontend; npm run build`
- Schema 导出：`.\.venv\Scripts\python scripts\export_schemas.py`
- Provider 配置检查：`.\.venv\Scripts\python scripts\check_real_api_config.py --tier public`
- 公开 live smoke：`.\.venv\Scripts\python scripts\live_smoke_real_apis.py --tier public`
- 春秋航班 live smoke：`.\.venv\Scripts\python scripts\live_smoke_real_apis.py --tier public --provider flight`
- 航司连续门禁 smoke：`.\.venv\Scripts\python scripts\continuous_flight_smoke.py --mode gate --iterations 3 --interval-seconds 0`
- 春秋航空匿名查询验证：`docs/flight_provider_evidence/2026-07-18/spring_airlines_anonymous_query.md`
