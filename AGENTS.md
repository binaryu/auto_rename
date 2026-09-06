# AGENTS.md

## 构建/测试/格式化

- **运行全部可用测试（推荐）:** `pytest tests/unit tests/test_emya_models.py tests/test_organizer.py`
  （当前 150 passed / 1 failed）
- **裸跑 `pytest` 会失败:** `tests/integration/test_integration.py` 在收集阶段就 ImportError
  （见「已知问题」），必须先 `--ignore` 或按上面的方式指定路径
- **运行单个测试文件:** `pytest tests/unit/test_core/test_renamer.py`
- **运行单个测试:** `pytest tests/unit/test_core/test_manual_rule_engine.py::TestManualRuleEngine::test_locked_fields_union`
- **格式化:** `black .`（⚠️ 当前 53/76 文件不符合 black，全量格式化会产生巨大 diff，
  只对改动文件执行 `black <file>`）
- **类型检查:** `mypy src/`（⚠️ 基线约 408 errors / 40 files，未纳入 CI 门禁；
  只需保证自己改动的文件不新增错误）
- **Lint:** `flake8 src/`（⚠️ 基线约 3079 处告警，主要是 `W293` 空白行含空格、`E501` 超长；
  同样只关注改动行）
- `pyproject.toml` 已配置 `pythonpath = ["src"]`、`testpaths = ["tests"]`、`addopts = "-v"`
- 依赖安装: `pip install -r requirements.txt`（开发工具在 `requirements-dev.txt`）
- 本地 Python 3.14，但 `requirements.txt` 按 3.9 兼容版本锁定，勿随意升级依赖

## 项目结构要点

所有代码都在 `src/video_organizer/` 包内（不存在顶层 `web/`、`upload/`、`database/` 目录）。

- **入口:**
  - 主入口: `src/video_organizer/main.py` — `main()`
  - 包运行: `python -m src.video_organizer.main [--web/--web-only/--process]`
    或（`pip install -e .` 之后）`python -m video_organizer`（`__main__.py`）
  - CLI 启动器: `run_organizer.py` — 无参数时自动追加 `--web`（监控 + Web 同时启动）
  - 参数定义在 `utils/cli_parser.py`: `--config/--monitor-dir/--show-config/--process/
    --organize-p123/--organize-yun139/--organize-dry-run/--web/--web-only/--web-host/
    --web-port/--web-reload/-v`
- **核心模块** (`src/video_organizer/core/`)：单文件与子包混存，导入前先确认路径
  - `renamer/` — 包，对外只导出 `VideoRenamer`（`from .core.renamer import VideoRenamer`）；
    内含 `renamer.py`、`ai_parser.py`（LLM 识别）、`category_detector.py`、
    `chinese_utils.py`、`path_builder.py`
  - `file_handler/handler.py` — `VideoFileHandler` 文件处理主循环（原 `core/video_file_handler.py` 已迁移）
  - `monitor/monitor.py` — `FileSystemMonitor` 目录监控
  - `downloader/` — `base.py` + `qbittorrent_monitor.py` + `aria2_monitor.py` + `factory.py`
  - `guessit_parser/parser.py` — `GuessItParser`，GuessIt 集成 + 中文文件名预处理
  - `emya/` — emya 媒体库入库（`api.py` / `models.py` / `service.py`）
  - `config_loader.py` — 配置加载/保存/验证（支持 frozen 打包环境路径）
  - `tmdb_client.py` — TMDB API 客户端
  - `manual_rule_engine.py` — 手动规则 DSL 引擎
  - `media_type_resolver.py` — media_type 置信度仲裁（电影/剧集误判修正）
  - `recycle_cleaner/` — 网盘回收站定时清理（`base.py` Provider 抽象 + `providers.py` 各网盘实现
    + `cleaner.py` 每日时间点调度线程）；123云盘删除的文件仍占容量，需 `trash_delete_all` 才释放
    （`fs_trash` 仅移入回收站）；新增网盘只需实现 `BaseRecycleProvider.stats()/clear()` 并
    `@register_provider`
  - `media_tracker_client.py`、`subtitle_handler.py`、`file_mover.py`、`db_manager.py`
- **工具模块** (`src/video_organizer/utils/`):
  - `llm_translator.py` — 多 Provider LLM 翻译/识别，负载均衡（round_robin/random/failover/weighted）；
    自动检测 `finish_reason=length` 截断并把 `max_tokens` 翻倍到 `max_tokens_cap` 重试；
    识别 JSON 支持 `tmdb_corrected_title` 纠正片名
  - `cli_parser.py`、`cli_output.py`、`config_loader.py`、`logging_setup.py`、
    `logging_utils.py`、`path_manager.py`
- **Web 后端** (`src/video_organizer/web/`):
  - `app.py` — FastAPI 应用创建 `create_app()`，统一挂 `/api/*` 前缀
  - `auth.py` — HMAC-SHA256 令牌（非标准 JWT，默认 7 天过期，服务重启全部失效）
    + PBKDF2 密码哈希 + `X-API-Key` 认证（sha256 哈希存库）
  - `routers/` — `auth.py`, `apikeys.py`, `config.py`, `tasks.py`, `logs.py`,
    `manual.py`, `downloaders.py`, `strm.py`, `organize.py`, `recycle.py`；
    `strm.py` 的 123 秒传代理会先建临时文件再取直链，**所有提前返回路径**都必须走
    `_p123_trash_temp()` 清理（已重试一次并校 code），否则文件残留在网盘目录里
  - `services/state.py` — `StateManager` 单例
  - `static/` — 原生 JS 前端（`index.html`, `app.js`, `ui.js`, `api.js`, `app.css`）
- **上传/整理模块** (`src/video_organizer/upload/`):
  - `base.py` — 上传基类（进度追踪、断点续传、Telegram 通知）
  - `emos_uploader.py` — emos 上传 + 重复资源识别
  - `cloud189_uploader.py` / `cloud189_client.py` — 天翼云盘
  - `p123_uploader.py` / `p123_client.py` / `pan123_client.py` — 123 云盘（`pan123_client.py` 是
    原生驱动，除 `fs_trash` 外另有 `recycle_list/iter_recycle/recycle_stats/recycle_delete/recycle_clear`）；
    ⚠️ `Pan123Client.request()` 接口报错时只记日志**不抛异常**（仅返回带非 0 code 的 body），
    所以删除/移动类调用必须自己检查 `resp["code"]`，否则会静默失败
  - `yun139_uploader.py` / `yun139_client.py` — 139 移动云盘
  - `media_tracker_uploader.py` — Media Tracker
  - `base_organizer.py` + `p123_organizer.py` + `yun139_organizer.py` — 网盘整理（`--organize-*`）
- **数据库** (`src/video_organizer/database/`): SQLAlchemy（`models.py`, `operations.py`,
  `config_operations.py`, `session.py`），用于 emya 入库、API Key、配置持久化
- **运行时目录:** `data/`（缓存、139_rapid）、`logs/`、`strm/`、`cas/`（均被 gitignore）

## 配置

- `config.ini`（实际，gitignore）/ `config_template.ini`（模板，首次运行自动生成），
  两者 section 结构保持一致
- 查找顺序（`core/config_loader.py: get_default_config_path()`）:
  frozen 环境用 exe 同级目录；否则 **cwd 下 `config.ini` → 项目根 `config.ini` → 包内 `config.ini`**。
  注意「配置文件为空」不等于「不可用」，真实密钥常在项目根 `config.ini`
- 主要 section: `[monitoring]` `[naming]` `[tmdb]` `[llm_fallback]` `[llm_provider_1..3]`
  `[guessit]` `[emos]` `[emos_recognition]` `[processing]` `[logging]` `[telegram]`
  `[emya_db]` `[yun139]` `[media_tracker]` `[p123]` `[recycle_clean]`；`[downloader.aria2]` / `[downloader.qbittorrent]` 模板中注释示例
- **回收站清理配置** (`[recycle_clean]`，默认 `enabled = False`):
  - `providers` — 逗号分隔（当前仅 `p123`）、`daily_at` — `HH:MM`，可配多个如 `04:00,16:00`
  - `catch_up_on_start` — 启动时补跑错过的时间点、`run_on_start` — 启动后立即跑一次（调试）
  - `notify_telegram` — 结果推 `[telegram]`、`max_items` — 统计时最多遍历的条目数
  - 策略固定为「清空回收站」（不可恢复），未做按天数/个数删除；调度器在 `main.py:
    initialize_recycle_cleaner()` 创建并 `set_cleaner()` 注册为全局单例，未启用时也注册（供 Web 手动触发）
- **LLM Provider 配置** (`[llm_provider_N]`):
  - `api_url`, `api_key`, `model`, `name` — 基本连接参数
  - `max_tokens` — 最大输出 token（默认 4096，推理模型需更大预算）
  - `max_tokens_cap` — 截断时自动翻倍上限（默认 16384）
  - `timeout`, `max_retries`, `weight`, `enabled` — 控制参数
  - 策略默认 `round_robin`，由代码传入 `llm_config["strategy"]`，config.ini 暂无该键

## 代码约定

- 使用 `pathlib.Path`，禁用字符串路径
- 使用 `from typing import Dict, List, Optional, Union`
- 绝对导入: `from src.video_organizer.core.renamer import VideoRenamer`
- 异常用 `try/except` + 日志 `logger = logging.getLogger(__name__)`
- 文档和注释使用中文
- ⚠️ 控制台输出中文在 Windows 下易乱码，脚本内读文件显式 `encoding="utf-8"`

## Docker

- 正式镜像: `Dockerfile` — 无 ENTRYPOINT，`CMD ["python","run_organizer.py","--web",
  "--web-host","0.0.0.0","--web-port","8080"]`（监控 + Web），带 `/api/health` healthcheck，
  非 root `appuser` 运行，`config_template.ini` 拷为 `/app/config.ini`
- 轻量镜像: `Dockerfile.run` — 默认 `python run_organizer.py`，无 healthcheck
- 遗留镜像: `Dockerfile.legacy`
- `docker-compose.yml` 三个 service: `video-organizer`、`video-organizer-web-only`
  （需 `--profile web-only`，命令覆盖为 `--web-only`）、`video-organizer-dev`（热重载）
- 配置挂载在 `./data/config.ini:/app/config.ini`

## 已知问题

1. **`pytest` 收集失败（阻塞全量测试）**
   `tests/integration/test_integration.py:14` 仍 `from src.video_organizer.core.video_file_handler
   import VideoFileHandler`，该模块已迁移到 `core/file_handler/handler.py` → ImportError，
   整个测试会话被中断。临时绕过：`--ignore=tests/integration/test_integration.py`。
2. **`tests/` 根目录下的旧测试与当前 API 不匹配（12 failed）**
   - `tests/test_tmdb_client.py`（8 个）— `TMDBClient.__init__()` 已无 `language` 参数
   - `tests/test_config_loader.py`（2 个）— `config_to_dict` 不再输出 `monitored_dir` 键
   - `tests/test_renamer.py::test_extract_movie_pattern` — `original_filename` 现在返回完整路径
   - 与 `tests/unit/test_core/` 下的同名新测试重复，需要决定删除还是修
3. **`tests/unit/test_core/test_manual_rule_engine.py::TestManualRuleEngine::test_locked_fields_union` 失败**
   原因：`get_locked_fields()` 依赖 `apply()` 被调用后累积结果，而测试直接构造引擎后查询，
   从未调用 `apply()`，导致返回空集合。这是测试与实现语义分歧，需要决定改实现
   （静态推导 lock_fields）还是改测试。
4. `black` / `mypy` / `flake8` 均无干净基线（见上），仓库无 CI 门禁；
   `.github/workflows/build.yml` 只做打包构建。

## 调试

### 启动测试服务器（避免卡住）
```powershell
$p = Start-Process -WindowStyle Hidden -PassThru -FilePath "python" -ArgumentList "-m", "src.video_organizer.main", "--web-only", "--web-port", "8095"; Write-Output $p.Id
```

### 停止测试服务器
```powershell
Get-Process -Id (Get-NetTCPConnection -LocalPort 8095 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force
```

### 查看日志
```powershell
python -c "import sys; sys.path.insert(0,'src'); from pathlib import Path; p=Path('logs'); [print(f.read_text(encoding='utf-8')[:2000]) for f in sorted(p.glob('*.log'))[-3:]]"
```

## Web API 快速参考

- Web 服务默认 `0.0.0.0:8080`（`--web-port` / `--web-host` 可改）
- 认证两种方式：
  - `POST /api/auth/login` → `access_token`，后续 `Authorization: Bearer <token>`
    （Bearer 校验失败时还会回退尝试把它当 API Key）
  - `X-API-Key: <key>`（`/api/apikeys` 增删改查，哈希存库）
- 免认证路径前缀（`web/auth.py: PUBLIC_PATHS`）: `/api/auth/`、`/static/`、
  `/api/health`、`/api/tasks/ws/`、`/api/logs/ws/`
- `POST /api/manual/validate` — 文件名识别验证（传 `{"file_path": "..."}`），
  详见 `docs/api-manual-validate.md`
- `GET /api/auth/first-run-credentials` — 首次运行随机密码
- 其他路由前缀: `/api/config`、`/api/tasks`、`/api/logs`、`/api/manual`、
  `/api/downloaders`、`/api/organize/{provider}/status|files|count|run|cancel|progress`；
  STRM 代理路由无 `/api` 前缀
- 回收站清理: `GET /api/recycle/status`、`GET /api/recycle/{provider}/stats`、
  `POST /api/recycle/{provider}/run`（body `{"dry_run": bool}`）；前端入口在「网盘整理」页底部卡片，
  配置项在「配置管理 → 回收站清理」
- WebSocket: `/api/tasks/ws/progress`, `/api/tasks/ws/dashboard`, `/api/logs/ws/{filename}`

## 其他文档

- `docs/API.md`、`docs/developer_guide.md`、`docs/usage_guide.md`
- `README.md`（功能说明）、`DOCKER.md` / `DOCKER_QUICKSTART.md`、`BUILD.md`
- ⚠️ `CLAUDE.md` / `IFLOW.md` / `QWEN.md` 是同类 agent 说明书的历史副本，内容已过时；
  改架构说明时以本文件为准并同步它们，或先确认是否可删
