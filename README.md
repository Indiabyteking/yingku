# 影库（YingKu）— 本机影视资源管理网站

一个运行在本机的流媒体风格全栈影视资源管理网站：从本机 **AList** 挂载的夸克网盘与百度网盘读取电影与剧集片源，自动完成防和谐文件名清洗与还原，借助 **TMDB** 刮削海报、横版背景图、透明片名 Logo、分季分集剧照及演职员信息，聚合 **MDBList** 多平台评分（IMDb、烂番茄、Metacritic、Trakt 等），支持 **DeepSeek** 大模型辅助推断改写片名，并一键拉起本机 **MPC-HC** 流式播放与跟踪观看进度。

---

## 一、环境要求与快速启动

### 1. 前置准备
- Python `>= 3.11` 与包管理工具 [`uv`](https://docs.astral.sh/uv/)
- 本机已安装并启动 **AList**（默认地址 `http://127.0.0.1:5244`）
- 本机播放器 **MPC-HC**（如 `C:\Program Files\MPC-HC\mpc-hc64.exe`，可在网页引导或设置页自定义路径）

### 2. 安装依赖
在项目根目录下执行：
```powershell
uv sync
```

### 3. 一条命令启动网站
```powershell
uv run yingku
```
（等价命令：`uv run python run.py`，支持 `--host 127.0.0.1 --port 5000` 参数）

启动后在浏览器访问 **`http://127.0.0.1:5000`**：
- **首次打开**：自动进入 **5 步首次使用引导（`/setup`）**，逐步说明各项密钥用途与获取地址，支持逐项点击“检测”实时验证连通性。
- **平滑降级**：**AList** 与 **TMDB** 为必需项；**MDBList** 与 **DeepSeek** 为选填项（若密钥为空或为 `to_do` 等占位值，点击“检测”会给出清晰原因，点击“跳过此步”即可降级为仅显示 TMDB 评分 / 仅用本地规则与声韵引擎识别，不影响正常入库与播放）。

---

## 二、配置文件说明（`.env`）

项目根目录下的 `.env` 文件保存本机凭据（已加入 `.gitignore`，不会提交到 Git）。可参考 `.env.example` 创建，也可直接在网页“首次引导”或“设置”页填写保存（原子写回 `.env` 并立即在内存生效，无需重启服务）：

| 变量名 | 是否必需 | 说明 |
|---|---|---|
| `ALIST_URL` | 必需 | AList 服务地址，默认 `http://127.0.0.1:5244` |
| `ALIST_USERNAME` | 必需 | AList 登录用户名，如 `admin` |
| `ALIST_PASSWORD` | 必需 | AList 登录密码 |
| `TMDB_TOKEN` | 必需 | TMDB API 只读访问令牌（Bearer Read Access Token） |
| `MDBLIST_APIKEY` | 选填 | MDBList API Key，用于补充 IMDb、烂番茄、Metacritic 等评分 |
| `LLM_BASE_URL` | 选填 | DeepSeek 或 OpenAI 兼容接口地址，默认 `https://api.deepseek.com` |
| `LLM_API_KEY` | 选填 | 大模型 API Key；为空或占位符（如 `to_do`）时自动降级为纯规则识别 |
| `LLM_MODEL` | 选填 | 模型名称，如 `deepseek-chat` 或 `deepseek-flash` |
| `LLM_API` | 选填 | 调用协议，取 `chat_completions` 或 `responses` |
| `PLAYER_PATH` | 播放使用 | 本机播放器可执行文件路径，如 `C:\Program Files\MPC-HC\mpc-hc64.exe` |

---

## 三、架构分层与数据存储

项目采用清晰的 **MVC + 外部客户端独立封装** 分层结构：

```text
app/
├── models/          # Model 层：仅负责 SQLite 读写（零外部请求、零视图逻辑）
│   ├── database.py      # SQLite 连接管理（WAL + 外键约束）
│   ├── media_model.py   # 媒体资料库 (data/media.db)：作品、季、集、文件映射、观看进度
│   └── state_model.py   # 本机状态与缓存库 (data/local_state.db)：引导状态、识别缓存、图片缓存索引、后台任务进度
├── clients/         # 外部服务封装层：每个外部依赖独立封装，统一限速与 429/5xx 指数退避重试
│   ├── http_client.py   # 最小请求间隔限速 + Retry-After / 指数退避重试
│   ├── alist_client.py  # AList 登录、目录递归扫描、本地代理签名流地址生成
│   ├── tmdb_client.py   # TMDB 搜索、详情/季集/候选图拉取、本地磁盘图片缓存
│   ├── mdblist_client.py# MDBList 多平台评分解析与无感降级
│   ├── deepseek_client.py# 兼容 responses 与 chat_completions 双协议的大模型名称推断
│   └── player_client.py # 跨平台本地播放器检测、MPC-HC 断点续播拉起与会话时长回写
├── services/        # 业务编排层：规则清洗、防和谐还原、TMDB 二次校验、异步入库刮削、续播决策
├── controllers/     # Controller 路由层：只负责“取数据 → 整理 → 渲染”，不写 SQL，不直接调外部接口
├── templates/       # View 视图层：服务端渲染 Jinja2 模板，仅负责展示，不做业务计算
└── static/          # 静态资源：统一设计变量的 Tailwind CSS 编译产物与原生 JavaScript 交互脚本
```

### 双数据库与离线图片缓存
- **`data/media.db`**：存放已入库的电影、剧集、季、单集、关联文件与观看进度。
- **`data/local_state.db`**：存放首次引导状态、服务连通性快照、文件名识别结果缓存与图片缓存索引，与媒体资料物理分离。
- **`data/cache/images/`**：所有海报、背景图、透明片名 Logo、单集剧照、演职员头像与后台候选预览图均下载至本地并由 `/media-cache/<path>` 提供，页面不直接引用任何 TMDB 外链，离线时已入库内容仍可完整浏览。

---

## 四、运行自动化测试

测试套件位于 `tests/` 目录，全部基于本地假数据与模拟客户端运行，**不依赖外部网络**，覆盖：
- 网盘文件名广告/画质噪声清洗、季集提取、防和谐分隔符/繁简/谐音字/夹杂拼音/首字母缩写还原；
- HTTP 429 限流自动退避重试、AList / TMDB / MDBList / DeepSeek（`responses` 与 `chat_completions` 双协议）/ MPC-HC 参数解析；
- AI 推测结果强制经 TMDB 二次检索校验（拒绝采信编造 ID）及 SQLite 识别缓存命中（同一文件不重复请求 AI）；
- 首次使用引导拦截、入库刮削、多版本电影与剧集续播、后台更换 Logo / 标题 / 重新匹配等端到端路由验证。

运行测试命令：
```powershell
uv run pytest -v
```
