# OpsPilot Phase 0 初学者完整开发教程

> 适合读者：掌握 Python 基础语法，知道函数、类、字典、列表和异常，但没有独立开发过前后端、数据库、Docker、测试和 CI 组成的完整项目。

## 0. 这份教程要解决什么问题

如果只逐行阅读代码，很容易出现一种情况：每一行似乎都认识，但不知道这些文件为什么要分开、程序从哪里开始、数据如何流动，以及新增功能时应该改哪里。

因此本文不按“文件名顺序”讲解，而按以下学习路线展开：

1. 先理解系统整体要完成什么。
2. 再跟踪一条请求如何穿过全部模块。
3. 然后拆解每层的职责和实现。
4. 最后学习测试、容器、迁移和 CI 如何保证项目可交付。

读完后，你应该能够回答：

- 为什么不能把全部代码写在一个 `main.py` 中？
- React、Nginx、FastAPI、Agent、SQLAlchemy 和 PostgreSQL 分别做什么？
- 一个 HTTP 请求如何变成数据库里的事件和轨迹？
- 为什么有 Pydantic 校验后还需要 Tool Gateway？
- 为什么数据库有 ORM 以后还需要 Alembic？
- 单元测试、集成测试和容器测试有什么区别？
- 为什么 Phase 0 使用 Mock，而不直接调用真实大模型？

---

## 1. 先建立几个大型项目必备概念

### 1.1 程序、进程与服务

Python 文件是程序代码。执行它以后，操作系统会创建一个进程。一个持续运行、等待其他程序请求的进程通常称为服务。

OpsPilot Phase 0 中有四个主要服务：

| 服务 | 技术 | 主要职责 |
|---|---|---|
| Web | React + Nginx | 展示页面、接收用户操作 |
| API | FastAPI + Uvicorn | 接收 HTTP 请求、运行业务逻辑 |
| Database | PostgreSQL | 持久保存事件和执行轨迹 |
| Cache | Redis | 为后续异步任务提供基础设施 |

这些服务不是互相复制功能，而是各自负责一种问题。

### 1.2 API 是什么

API 可以理解成两个程序之间约定好的“函数调用协议”。浏览器无法直接调用服务器里的 Python 函数，所以双方通过 HTTP 通信。

例如：

```text
POST /api/v1/incidents
```

表示“创建一个故障事件”。请求体是 JSON，响应也是 JSON。

这与在 Python 中调用函数很像：

```python
incident = create_incident(payload)
```

不同点是调用者和函数运行在不同进程，甚至可以运行在不同机器上，所以必须明确约定 URL、HTTP 方法、请求字段、响应字段和错误格式。

### 1.3 数据库为什么不是一个 JSON 文件

JSON 文件适合保存少量静态配置，但数据库能处理：

- 多个请求同时读写；
- 事务：一组操作要么全部成功，要么全部失败；
- 索引：快速查找数据；
- 关联：一个事件对应多条轨迹；
- 约束：主键不能重复、外键必须有效；
- 持久化：容器重启后数据仍存在。

### 1.4 容器是什么

容器可以理解为“带有运行环境的应用包”。API 容器里不仅有我们的 Python 代码，还有 Python 3.11、依赖包和启动命令。

这样可以避免：

```text
在我的电脑上能运行，在你的电脑上不能运行。
```

Docker Compose 则负责一次启动多个相互依赖的容器。

---

## 2. Phase 0 的目标与边界

OpsPilot 最终目标是构建一个企业 IT 故障处置 Agent。它需要读取监控、日志、服务信息、Runbook 和历史事件，给出有证据支持的诊断，并把有风险的变更放在人工审批之后。

但如果第一天就接入真实大模型、Prometheus、Loki、CMDB、Kubernetes 和权限系统，出现错误时会很难判断问题来自哪里。

因此 Phase 0 先建立一个最小纵向切片：

```text
用户填写事件
    ↓
前端发送 HTTP 请求
    ↓
后端校验请求
    ↓
创建数据库事件
    ↓
运行确定性 Agent 状态机
    ↓
调用五个 Mock 只读工具
    ↓
生成带证据 ID 的结论
    ↓
持久化完整轨迹
    ↓
前端显示结果
```

“纵向切片”意味着一次打通界面、接口、业务逻辑和数据库，而不是先完成某一层的全部功能。

Phase 0 故意不实现：

- 真实大模型调用；
- 真实生产监控和日志；
- 用户登录和 RBAC；
- 审批中心；
- 真实重启或回滚；
- Celery 异步任务；
- SSE 实时推送；
- 训练和模型评测。

这不是“少做了”，而是在控制复杂度。Phase 0 首先证明架构可以跑通，Phase 1 再在稳定主干上增加安全和审批。

---

## 3. 总体架构设计

### 3.1 组件关系

```text
┌──────────────────────────────────────────────┐
│ 浏览器                                       │
│ React 表单、事件列表、诊断时间线             │
└───────────────────┬──────────────────────────┘
                    │ HTTP / JSON
                    ▼
┌──────────────────────────────────────────────┐
│ Nginx                                        │
│ 提供前端静态文件，将 /api/ 转发给 API         │
└───────────────────┬──────────────────────────┘
                    │ http://api:8000
                    ▼
┌──────────────────────────────────────────────┐
│ FastAPI                                      │
│ 路由、Pydantic 校验、依赖注入、错误响应      │
└──────────────┬──────────────────┬────────────┘
               │                  │
               ▼                  ▼
┌──────────────────────┐  ┌────────────────────┐
│ Agent Orchestrator   │  │ SQLAlchemy         │
│ 状态机、工具调用顺序 │  │ 会话、模型、事务   │
└──────────┬───────────┘  └─────────┬──────────┘
           │                         │
           ▼                         ▼
┌──────────────────────┐  ┌────────────────────┐
│ Tool Gateway         │  │ PostgreSQL         │
│ 白名单、参数校验     │  │ Incident/Trace     │
└──────────┬───────────┘  └────────────────────┘
           │
           ▼
┌──────────────────────┐
│ Mock Scenarios       │
│ 指标、日志、Runbook  │
└──────────────────────┘
```

### 3.2 为什么要分层

大型项目最容易出现的问题是“一个修改影响所有地方”。分层的目标是限制影响范围。

例如未来把 Mock 指标替换为 Prometheus：

- 前端不需要修改；
- Incident 数据表不需要修改；
- API URL 不需要修改；
- Agent 调用的工具名不需要修改；
- 只需要替换 Tool Gateway 后面的数据适配器。

一个模块理想上只应该有一个主要变化原因：

- UI 变化时改 `apps/web`；
- HTTP 契约变化时改 `apps/api`；
- Agent 流程变化时改 `opspilot/agent`；
- 工具安全规则变化时改 `opspilot/tools`；
- 数据结构变化时改 `models` 和 `migrations`。

### 3.3 依赖方向

项目大致遵循下面的依赖方向：

```text
外层界面和接口 → 核心业务模块 → 数据与工具抽象
```

核心业务模块不应该反过来依赖 React。否则换一个界面就要重写 Agent。

---

## 4. 项目目录逐项说明

```text
toolcalling-model/
├── apps/
│   ├── api/                     # HTTP 接口层
│   │   ├── main.py              # FastAPI 应用入口
│   │   ├── schemas.py           # API 请求/响应模型
│   │   └── routes/incidents.py  # 事件相关接口
│   └── web/                     # React 前端
│       ├── src/App.tsx          # 主页面
│       ├── src/api.ts           # 前端 API 客户端
│       ├── Dockerfile           # 前端镜像构建
│       └── nginx.conf           # 静态服务和反向代理
├── opspilot/
│   ├── agent/                   # Agent 状态与编排
│   ├── db/                      # 数据库引擎与会话
│   ├── models/                  # ORM 数据模型
│   ├── tools/                   # 工具定义、校验和执行入口
│   └── config.py                # 环境配置
├── simulator/scenarios/         # 确定性模拟故障数据
├── migrations/                  # 数据库版本迁移
├── tests/                       # 单元和集成测试
├── docs/adr/                    # 架构决策记录
├── docker-compose.yml           # 多容器编排
├── Dockerfile.api               # API 镜像
├── pyproject.toml               # Python 项目和工具配置
└── .github/workflows/ci.yml     # 自动化质量检查
```

`__init__.py` 表示目录是 Python 包。这样才能使用：

```python
from opspilot.agent.state import AgentState
```

而不是依赖当前工作目录进行脆弱的相对文件查找。

---

## 5. 从程序启动开始理解

执行：

```powershell
docker compose up --build
```

大致发生以下事情：

1. Compose 读取 `docker-compose.yml`。
2. 创建一个仅供本项目使用的 Docker 网络。
3. 启动 PostgreSQL 和 Redis。
4. 等待二者的健康检查通过。
5. 构建并启动 API 容器。
6. API 先运行 `alembic upgrade head`。
7. 迁移成功后运行 Uvicorn，监听容器内 8000 端口。
8. 构建 React，复制静态文件到 Nginx。
9. Nginx 监听容器内 80 端口，映射到电脑的 5173 端口。

### 5.1 端口映射

Compose 中：

```yaml
ports:
  - "8000:8000"
```

左边是电脑端口，右边是容器端口。因此浏览器访问电脑的 `localhost:8000`，Docker 会把请求送到 API 容器的 8000。

Web 的映射是：

```yaml
ports:
  - "5173:80"
```

所以浏览器访问 `localhost:5173`，实际到达 Nginx 的 80 端口。

### 5.2 服务名就是容器网络中的主机名

环境变量中的数据库地址是：

```text
postgresql+asyncpg://opspilot:opspilot@postgres:5432/opspilot
```

其中：

- 第一个 `opspilot` 是用户名；
- 第二个 `opspilot` 是密码；
- `postgres` 是 Compose 服务名；
- `5432` 是 PostgreSQL 容器端口；
- 最后一个 `opspilot` 是数据库名。

API 容器不能用 `localhost` 连接 PostgreSQL，因为 API 容器中的 `localhost` 指 API 容器自己。它必须使用服务名 `postgres`。

---

## 6. 配置模块：为什么不把地址写死

文件：`opspilot/config.py`

核心代码：

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPSPILOT_",
        env_file=".env",
        extra="ignore",
    )

    env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./opspilot.db"
    redis_url: str = "redis://localhost:6379/0"
    model_provider: str = "mock"
```

`BaseSettings` 会把 Python 字段名映射到环境变量。例如：

```python
database_url
```

对应：

```text
OPSPILOT_DATABASE_URL
```

开发环境可以使用 SQLite，Docker 环境通过 `.env` 改成 PostgreSQL，而代码无需修改。

这是配置与代码分离原则。以下内容通常都不应硬编码：

- 数据库地址；
- Redis 地址；
- API Key；
- 模型地址；
- 超时和调用预算。

### 6.1 `lru_cache` 的作用

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

装饰器 `@lru_cache` 会缓存函数返回结果。第一次调用时读取环境变量并创建对象，后续调用返回同一个 Settings 对象。

这样不会在每个请求里重复解析 `.env`。

---

## 7. 数据库会话：连接、会话和事务的区别

文件：`opspilot/db/session.py`

```python
engine = create_async_engine(
    get_settings().database_url,
    pool_pre_ping=True,
)
```

`engine` 可以理解为数据库连接设施。它知道数据库地址、驱动和连接池，但它不是一次具体业务操作。

```python
SessionFactory = async_sessionmaker(
    engine,
    expire_on_commit=False,
)
```

`SessionFactory` 是“会话工厂”，调用它会创建一个 `AsyncSession`。

Session 可以理解为一次业务工作单元。创建事件、创建轨迹、更新状态应该在同一会话和事务里完成。

```python
async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
```

这里需要理解三个语法点：

1. `async def` 表示异步函数。
2. `async with` 确保异步资源最终被释放。
3. `yield` 暂时把 session 交给 FastAPI，等请求完成后再继续执行清理。

如果路由执行出错，会话退出，未提交事务不会变成正式数据。

`pool_pre_ping=True` 会在复用连接前检查连接是否仍有效，减少数据库重启后拿到失效连接的问题。

---

## 8. ORM 模型：把 Python 对象映射到数据库表

文件：`opspilot/models/incident.py`

ORM 是 Object-Relational Mapping，中文常译为对象关系映射。它让我们用 Python 类描述数据库表。

### 8.1 Incident

```python
class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
```

含义是：

- Python 类叫 `Incident`；
- 数据库表叫 `incidents`；
- `id` 是字符串列；
- 最大长度 36；
- 它是主键；
- 默认生成 UUID。

主键用于唯一识别一行数据。即使两个事件标题相同，ID 也不同。

### 8.2 TraceEvent

TraceEvent 保存一次执行过程中的单个步骤：

```text
状态转换、工具调用、最终结论
```

关键字段：

```python
incident_id: Mapped[str] = mapped_column(
    ForeignKey("incidents.id"),
    index=True,
)
```

`ForeignKey` 表示这条轨迹必须属于一个存在的 Incident。

`index=True` 表示为 `incident_id` 建索引，因为系统经常执行“查询某事件的全部轨迹”。没有索引时，数据量大后数据库可能逐行扫描整个表。

### 8.3 一对多关系

```python
trace: Mapped[list["TraceEvent"]] = relationship(
    back_populates="incident",
    cascade="all, delete-orphan",
    order_by="TraceEvent.sequence",
)
```

含义：

- 一个 Incident 有多条 TraceEvent；
- TraceEvent 可以反向找到所属 Incident；
- 删除 Incident 时删除其孤立轨迹；
- 查询轨迹时按 sequence 排序。

### 8.4 为什么 payload 使用 JSON

不同轨迹的详细内容不完全相同：

- 状态转换需要保存 `state`；
- 工具调用需要保存工具名、参数和结果；
- 最终答案需要保存根因、置信度和证据 ID。

因此共同字段放在普通列，变化较大的详情放进 JSON `payload`。这叫“稳定结构与灵活结构结合”。

不能把所有内容都塞进 JSON，否则数据库很难约束和高效查询；也不应该为每种轨迹创建完全不同的数据表，否则 Phase 0 会过度复杂。

---

## 9. Alembic：数据库结构也需要版本管理

Python 代码可以用 Git 记录版本，但数据库里的表结构不会因为切换 Git 分支自动变化。

例如以后给 Incident 增加：

```text
assigned_to
```

仅修改 ORM 类不会自动安全地修改生产数据库。因此需要 Alembic 保存数据库结构的演进步骤。

### 9.1 迁移文件是什么

文件：`migrations/versions/20260924_0001_create_incidents.py`

每个迁移都有一个版本号：

```python
revision = "20260924_0001"
down_revision = None
```

`revision` 是当前版本，`down_revision` 指向上一个版本。多个迁移连接起来就形成版本链。

### 9.2 upgrade 与 downgrade

```python
def upgrade() -> None:
    ...
```

描述从旧版本升级到新版本需要做什么。本项目初始迁移会创建：

- `incidents`
- `trace_events`
- `ix_trace_events_incident_id` 索引

```python
def downgrade() -> None:
    ...
```

描述如何回退。删除顺序必须与依赖关系相反：先删索引和子表，再删父表。

### 9.3 Alembic 如何知道数据库地址

`migrations/env.py` 读取统一的 Settings：

```python
config.set_main_option(
    "sqlalchemy.url",
    get_settings().database_url,
)
```

因此本地 SQLite 和 Docker PostgreSQL 使用相同迁移代码，只是环境变量不同。

### 9.4 为什么容器启动时先迁移

API Dockerfile 的启动命令是：

```dockerfile
CMD [
  "sh",
  "-c",
  "alembic upgrade head && exec uvicorn ..."
]
```

`&&` 表示只有迁移成功才启动 API。如果数据库结构不正确，服务应该明确启动失败，而不是运行到某个请求时才报“列不存在”。

`exec` 让 Uvicorn 成为容器的主进程，使 Docker 发出的停止信号能正确传递给 Uvicorn。

### 9.5 ORM 与 Alembic 的分工

| 工具 | 负责什么 |
|---|---|
| SQLAlchemy ORM | 当前代码认为数据结构应该是什么样 |
| Alembic | 数据库如何从旧结构演进到新结构 |

ORM 是“现在的设计图”，迁移是“施工步骤”。两者不能互相替代。

---

## 10. Pydantic：在业务逻辑前建立数据边界

项目中有两组 Pydantic 模型：

1. `apps/api/schemas.py`：校验外部 HTTP 请求和响应。
2. `opspilot/tools/schemas.py`：校验 Agent 调用工具时的参数。

两组模型虽然都用 Pydantic，但处于不同安全边界，不能混为一谈。

### 10.1 API 请求模型

```python
class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=5000)
    severity: Literal["P1", "P2", "P3", "P4"]
    service_name: Literal[
        "gateway",
        "order",
        "payment",
        "inventory",
        "notification",
    ]
```

`Literal` 表示值只能来自指定集合。用户如果传入：

```json
{"severity": "VERY_BAD"}
```

FastAPI 会在路由执行之前返回 422。

`Field` 定义长度范围，避免空字符串和无限大的请求体进入后续逻辑。

### 10.2 响应模型

```python
class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
```

`from_attributes=True` 允许 Pydantic 从 SQLAlchemy 对象属性读取数据。否则它主要期待普通字典。

响应模型的意义不仅是生成文档，还能限制对外返回字段。即使 ORM 以后增加内部字段，只要没有写入响应模型，就不会自动泄露给客户端。

### 10.3 为什么列表默认值用 default_factory

```python
trace: list[TraceEventRead] = Field(default_factory=list)
```

不推荐：

```python
trace = []
```

因为可变默认值可能被多个实例共享。`default_factory=list` 保证每个对象创建独立列表。

### 10.4 工具参数模型

例如日志工具：

```python
class LogsQuery(TimeRangeQuery):
    keywords: list[str] = Field(default_factory=list, max_length=10)
    level: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
```

这里不仅检查类型，还限制最多 10 个关键词、最多返回 200 条日志。即使未来模型生成了极大查询，Schema 也能在访问真实日志系统之前拒绝它。

---

## 11. FastAPI 应用入口

文件：`apps/api/main.py`

### 11.1 创建应用

```python
app = FastAPI(
    title="OpsPilot API",
    version="0.1.0",
    lifespan=lifespan,
)
```

`app` 是整个 Web 应用对象。Uvicorn 启动参数：

```text
apps.api.main:app
```

冒号左边是 Python 模块，右边是模块中的对象。

### 11.2 路由装饰器

```python
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

装饰器把普通 Python 函数注册为 HTTP 路由。收到 `GET /health` 时，FastAPI 调用 `health()`，并把字典序列化为 JSON。

### 11.3 lifespan

```python
@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()
```

`yield` 之前是启动阶段，`yield` 之后是关闭阶段。服务停止时释放数据库连接池。

数据库建表没有放在这里，因为结构演进已经交给 Alembic。

### 11.4 统一异常响应

未处理异常会转换为结构化 JSON，并生成 `request_id`。这样前端不会收到一段不可解析的 HTML 错误页，开发者也可以根据 request ID 查日志。

异常响应只暴露异常类型，不直接把完整堆栈返回给用户，因为堆栈可能包含文件路径、SQL 或其他内部信息。

---

## 12. FastAPI 依赖注入

事件路由中定义：

```python
SessionDependency = Annotated[
    AsyncSession,
    Depends(get_session),
]
```

初学时可以把它理解成：

> 这个参数的类型是 AsyncSession，但它的值由 FastAPI 调用 get_session 自动提供。

路由写成：

```python
async def list_incidents(
    session: SessionDependency,
) -> list[Incident]:
    ...
```

路由不负责：

- 读取数据库 URL；
- 创建 engine；
- 打开连接；
- 请求完成后关闭会话。

这些都由 `get_session` 管理。

这种设计让测试可以替换依赖。例如生产使用 PostgreSQL，测试使用 SQLite，但路由本身不需要两个版本。

---

## 13. 创建事件接口逐步拆解

文件：`apps/api/routes/incidents.py`

### 13.1 接收经过校验的数据

```python
async def create_incident(
    payload: IncidentCreate,
    session: SessionDependency,
) -> Incident:
```

进入函数时，`payload` 已经不是原始 JSON，而是经过 Pydantic 校验的 `IncidentCreate` 对象。

### 13.2 创建 ORM 对象

```python
incident = Incident(
    **payload.model_dump(),
    status="NEW",
)
```

`model_dump()` 把 Pydantic 对象转换为字典。

`**` 是字典解包。例如：

```python
{"title": "告警", "severity": "P1"}
```

解包后相当于：

```python
Incident(title="告警", severity="P1")
```

### 13.3 add、flush 与 commit

```python
session.add(incident)
await session.flush()
```

`add()` 把对象放入会话，但不一定立即写数据库。

`flush()` 把当前变更发送给数据库，使默认生成的 `incident.id` 可用，但事务还没有最终提交。

```python
await session.commit()
```

`commit()` 才正式提交事务。

区分它们非常重要：

| 操作 | 含义 |
|---|---|
| add | 告诉会话要保存对象 |
| flush | 把 SQL 发给数据库，但事务仍可回滚 |
| commit | 正式提交事务 |

### 13.4 运行业务编排

```python
events = MockOrchestrator().run(
    payload.service_name,
    payload.description,
)
```

路由只负责协调，不在路由里实现状态机和工具细节。这使 HTTP 层保持较薄。

### 13.5 保存轨迹

```python
for sequence, event in enumerate(events, start=1):
    session.add(
        TraceEvent(
            incident_id=incident.id,
            sequence=sequence,
            **event,
        )
    )
```

`enumerate(..., start=1)` 同时得到顺序号和事件内容。

显式使用 `session.add()`，而不是访问尚未加载的关系集合，可以避免异步 ORM 隐式查询导致的 `MissingGreenlet`。

### 13.6 为什么提交后重新查询

```python
return await _get_incident(session, incident.id)
```

重新查询时使用：

```python
selectinload(Incident.trace)
```

这会显式加载轨迹，保证返回对象包含数据库中的完整结果，而不是依赖内存中碰巧存在的数据。

---

## 14. Agent 状态机

文件：`opspilot/agent/state.py`

### 14.1 状态定义

```python
class AgentState(StrEnum):
    NEW = "NEW"
    TRIAGE = "TRIAGE"
    COLLECTING_EVIDENCE = "COLLECTING_EVIDENCE"
    DIAGNOSING = "DIAGNOSING"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
```

`StrEnum` 的成员既是枚举，也是字符串。它比到处手写字符串更安全：

```python
AgentState.DIAGNOSING
```

不容易误写成：

```text
DIAGONOSING
```

### 14.2 合法转换表

```python
ALLOWED_TRANSITIONS = {
    AgentState.NEW: {AgentState.TRIAGE},
    AgentState.TRIAGE: {
        AgentState.COLLECTING_EVIDENCE,
        AgentState.NEEDS_HUMAN,
    },
    ...
}
```

字典的 key 是当前状态，set 是允许到达的下一状态。

### 14.3 为什么状态机是安全控制

没有状态机时，代码可能从 NEW 直接进入 RESOLVED，或者未经审批进入执行状态。

状态机把流程约束变成代码：

```python
def assert_transition(current, target):
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(...)
```

对于普通表单应用，非法状态可能只造成显示错误；对于运维 Agent，非法状态可能意味着未审批就执行生产变更。因此状态机不只是代码组织方式，也是安全边界。

---

## 15. MockOrchestrator：把流程组织起来

文件：`opspilot/agent/orchestrator.py`

Orchestrator 可以翻译为编排器。它不负责查询日志的具体实现，而是决定：

- 什么时候改变状态；
- 以什么顺序调用工具；
- 如何记录证据；
- 何时生成最终答案。

### 15.1 内部 transition 函数

```python
def transition(target: AgentState) -> None:
    nonlocal state
    assert_transition(state, target)
    state = target
    events.append({
        "event_type": "state_transition",
        "payload": {"state": state},
    })
```

`nonlocal state` 表示修改外层 `run()` 函数中的局部变量 `state`。

每次转换同时做两件事：

1. 验证是否合法；
2. 记录一条可审计事件。

如果只修改状态而不记录，事后只能看到最终状态，无法知道中间发生了什么。

### 15.2 工具调用计划

Phase 0 固定调用五个工具：

```text
query_metrics
query_logs
get_service_info
search_runbook
search_incidents
```

它们分别从指标、日志、配置、操作手册和历史案例提供不同角度的证据。

当前调用顺序是确定性的。这样测试每次都得到同样结果。Phase 1/3 接入模型后，模型可以参与选择工具，但仍必须受到工具白名单、调用预算和状态机限制。

### 15.3 证据 ID

```python
evidence_id = f"ev-{index}"
```

每次工具调用获得一个证据 ID，最终答案保存这些 ID：

```json
{
  "root_causes": ["payment 到 Redis 的连接发生持续超时"],
  "confidence": 0.86,
  "evidence_ids": ["ev-1", "ev-2", "ev-3", "ev-4", "ev-5"]
}
```

这样最终答案不是一段无法验证的文本，而是可以追溯到具体工具调用。

### 15.4 为什么产生 10 条轨迹

| 序号 | 轨迹 |
|---:|---|
| 1 | 进入 TRIAGE |
| 2 | 进入 COLLECTING_EVIDENCE |
| 3 | query_metrics |
| 4 | query_logs |
| 5 | get_service_info |
| 6 | search_runbook |
| 7 | search_incidents |
| 8 | 进入 DIAGNOSING |
| 9 | final_answer |
| 10 | 进入 RESOLVED |

这就是端到端测试中 `TraceEvents = 10` 的来源。

---

## 16. Tool Gateway：Agent 与外部世界之间的门卫

文件：`opspilot/tools/gateway.py`

### 16.1 工具白名单

```python
_schemas = {
    "query_metrics": MetricsQuery,
    "query_logs": LogsQuery,
    "get_service_info": ServiceInfoQuery,
    "search_runbook": SearchQuery,
    "search_incidents": SearchQuery,
}
```

这个字典同时说明：

- 哪些工具可以调用；
- 每个工具使用哪个参数 Schema。

未知工具会立即被拒绝：

```python
if schema is None:
    raise ToolValidationError(
        f"Unknown or disallowed tool: {tool_name}"
    )
```

即使未来大模型产生 `run_shell`，系统也不会因为模型“说了”就执行。

### 16.2 参数二次校验

```python
validated = schema.model_validate(arguments)
```

为什么 HTTP 入口已经验证过，这里还要验证？

因为工具参数不是用户原始请求，而是 Agent 根据请求重新构造的数据。未来这些参数可能由大模型生成。模型输出同样是不可信输入，必须重新校验。

系统里可能存在多层边界：

```text
用户输入边界 → Agent 输出边界 → 工具访问边界
```

每穿过一层，都要重新验证。

### 16.3 工具返回来源信息

每种结果都包含类似：

```json
{"source_uri": "mock://prometheus"}
```

数据来源是证据的一部分。未来真实系统中，它可能变为某个指标查询、日志查询或文档地址。

### 16.4 为什么 Runbook 标记 untrusted

```json
{"untrusted": true}
```

Runbook 是外部文本，未来可能被错误修改，甚至包含诱导模型执行危险操作的内容。系统可以参考它，但不能把其中的自然语言当作系统级指令。

这为后面的 Prompt Injection 防御预留了语义。

---

## 17. Mock 场景：模拟数据不等于绕过系统

文件：`simulator/scenarios/scenarios.json`

目前包含三个场景：

1. Gateway CPU 饱和；
2. Payment 到 Redis 超时；
3. Order 新版本发布回归。

每个场景包含：

- 服务名；
- 关键词；
- 根因；
- 指标；
- 日志；
- Runbook；
- 历史事件。

重要区别：

```text
前端假数据：React 直接显示一段写死 JSON，后端没有参与。

本项目 Mock：请求仍经过 API、Agent、Gateway、数据库和前端，
只是 Gateway 最终读取模拟数据源。
```

Mock 的目标是替换不稳定或暂时不存在的外部依赖，而不是跳过系统架构。

这使未来替换真实适配器时，可以继续复用接口和测试契约。

---

## 18. React 前端：状态驱动界面

文件：

- `apps/web/src/App.tsx`
- `apps/web/src/api.ts`
- `apps/web/src/styles.css`

如果你只熟悉 Python，可以先把 React 组件理解为：

> 一个根据当前数据生成页面结构的函数。

```tsx
export default function App() {
  ...
  return (...页面结构...);
}
```

### 18.1 TypeScript 类型对应 Python 类型提示

```typescript
export type Incident = {
  id: string;
  title: string;
  status: string;
  trace: TraceEvent[];
};
```

它与 Python 的 Pydantic/类型提示作用相似：帮助编辑器和构建工具发现字段拼写错误和类型不匹配。

但 TypeScript 类型只在开发和构建时存在，浏览器运行 JavaScript 时不会自动校验服务器响应。因此真正的外部边界仍需后端 Pydantic 保证。

### 18.2 useState

```typescript
const [incidents, setIncidents] = useState<Incident[]>([]);
```

可以理解为：

- `incidents` 是当前值；
- `setIncidents` 用于更新值；
- 初始值是空数组；
- 值变化后 React 重新计算页面。

其他状态包括：

- `selected`：当前选中的事件；
- `loading`：是否正在等待请求；
- `error`：错误提示。

### 18.3 useEffect

页面第一次加载时需要请求事件列表：

```typescript
useEffect(() => {
  ...
}, []);
```

空依赖数组 `[]` 表示组件首次挂载时运行一次。

代码中的 `active` 标志用于防止组件已经卸载后，较晚返回的异步请求继续调用 `setState`：

```typescript
let active = true;

return () => {
  active = false;
};
```

这是一种处理异步生命周期的基础方法。

### 18.4 useMemo

```typescript
const evidenceCount = useMemo(
  () => selected?.trace.filter(
    (event) => event.event_type === "tool_call"
  ).length ?? 0,
  [selected],
);
```

它根据当前选中事件计算工具证据数量。只有 `selected` 改变时才重新计算。

当前计算很轻，使用 `useMemo` 不是性能必需，但它清楚表达了“这是派生数据，而不是独立状态”。

如果把 evidenceCount 也存进 `useState`，就可能出现 selected 更新了但 count 忘记同步的问题。

### 18.5 表单提交

```typescript
const submit = async (values) => {
  setLoading(true);
  setError(undefined);
  try {
    const incident = await createIncident(...);
    setIncidents((current) => [incident, ...current]);
    setSelected(incident);
  } catch (reason) {
    ...
  } finally {
    setLoading(false);
  }
};
```

这里与 Python 的 `try/except/finally` 思路相同：

- try 执行请求；
- catch 处理异常；
- finally 无论成功失败都关闭 loading。

更新 incidents 时使用函数形式：

```typescript
setIncidents((current) => [incident, ...current]);
```

这样 React 会把最新状态传入 `current`，避免异步情况下基于旧值更新。

### 18.6 前端 API 客户端

`api.ts` 把 HTTP 细节集中起来：

```typescript
const response = await fetch("/api/v1/incidents");
if (!response.ok) throw new Error("无法加载事件");
return response.json();
```

页面组件只需要调用 `listIncidents()`，不用重复写 URL、HTTP 方法和请求头。

随着项目变大，这一层还可以加入：

- 统一错误格式；
- request ID；
- 身份认证 token；
- 超时；
- 重试策略。

---

## 19. Nginx：静态服务器与反向代理

文件：`apps/web/nginx.conf`

React 构建后得到 HTML、CSS 和 JavaScript 静态文件。Nginx 负责把这些文件发送给浏览器。

### 19.1 静态文件

```nginx
root /usr/share/nginx/html;
index index.html;
```

浏览器访问 `/` 时返回 `index.html`。

### 19.2 API 反向代理

```nginx
location /api/ {
    proxy_pass http://api:8000/api/;
}
```

浏览器认为自己请求：

```text
http://localhost:5173/api/v1/incidents
```

Nginx 在 Docker 网络里把它转发给：

```text
http://api:8000/api/v1/incidents
```

好处：

- 前端不需要写死 API 容器地址；
- 浏览器看到的页面和 API 属于同一来源；
- 部署环境变化时主要改 Nginx，而不是重新编译业务代码。

### 19.3 单页应用回退

```nginx
location / {
    try_files $uri /index.html;
}
```

如果将来 React 增加 `/incidents/123` 之类的前端路由，服务器找不到同名物理文件时会返回 `index.html`，再由 React 决定显示哪个页面。

---

## 20. Dockerfile：如何制作交付物

### 20.1 API 镜像

文件：`Dockerfile.api`

```dockerfile
FROM python:3.11-slim
```

选择一个带 Python 3.11 的精简 Linux 基础镜像。

```dockerfile
WORKDIR /app
```

后续命令默认在 `/app` 中执行。

```dockerfile
COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY apps ./apps
COPY opspilot ./opspilot
COPY simulator ./simulator
```

显式复制运行所需内容。如果忘记复制 `simulator`，本地运行可能成功，但容器会出现 `FileNotFoundError`。Phase 0 测试确实发现过这个问题。

```dockerfile
RUN pip install --no-cache-dir .
```

根据 `pyproject.toml` 安装项目和依赖。`--no-cache-dir` 避免把 pip 下载缓存保留在最终镜像层。

### 20.2 Web 多阶段构建

第一阶段使用 Node：

```dockerfile
FROM node:22-alpine AS build
RUN npm ci
RUN npm run build
```

第二阶段使用 Nginx：

```dockerfile
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
```

Node、TypeScript 编译器和源码不需要进入最终运行镜像。最终只保留 Nginx 和构建产物。

### 20.3 npm ci 与 npm install

本地添加依赖时通常使用 `npm install`，它会更新 lock 文件。

CI 和 Docker 构建使用 `npm ci`：

- 严格按照 `package-lock.json` 安装；
- lock 文件与 package.json 不一致时直接失败；
- 更适合可复现构建。

---

## 21. Docker Compose：把多个服务组装起来

文件：`docker-compose.yml`

### 21.1 healthcheck

PostgreSQL：

```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U opspilot"]
  interval: 5s
  timeout: 3s
  retries: 10
```

“进程已经启动”不等于“数据库已经能接受请求”。healthcheck 通过后，Compose 才认为数据库健康。

API 依赖：

```yaml
depends_on:
  postgres:
    condition: service_healthy
  redis:
    condition: service_healthy
```

这样 API 不会在数据库初始化期间立即连接并失败。

但要注意：`depends_on` 只处理启动顺序，不是完整的运行时故障恢复机制。运行过程中数据库断开，仍需要应用层超时、重连和降级。

### 21.2 volume

```yaml
volumes:
  - postgres_data:/var/lib/postgresql/data
```

容器文件系统通常是临时的。命名卷把数据库数据保存到独立存储，重建容器后数据仍然存在。

因此 `docker compose down` 和 `docker compose down --volumes` 含义不同：后者会删除数据卷，是破坏性操作，不能随意执行。

### 21.3 `.dockerignore`

Docker 构建会先把构建上下文发送给 Docker Engine。如果没有 `.dockerignore`，可能把以下内容都发送进去：

- `.git`
- `node_modules`
- 测试缓存
- 本地数据库
- 构建产物

Phase 0 初次构建上下文曾达到约 143 MB。增加 `.dockerignore` 后降到 KB 级。

这不仅提高速度，还能降低把无关文件或秘密复制进镜像的风险。

---

## 22. 测试为什么要分层

测试不是越接近真实环境就一定越好。不同测试解决不同问题。

### 22.1 单元测试

单元测试只验证一个小规则。

状态机测试：

```python
def test_legal_transition() -> None:
    assert_transition(AgentState.NEW, AgentState.TRIAGE)
```

非法转换测试：

```python
with pytest.raises(ValueError):
    assert_transition(AgentState.NEW, AgentState.RESOLVED)
```

工具安全测试确保 `run_shell` 不在白名单中。

单元测试特点：

- 快；
- 容易定位问题；
- 不验证完整系统装配。

### 22.2 API 集成测试

集成测试通过 TestClient 真正调用 FastAPI 路由，验证：

- Pydantic 请求校验；
- 路由与 Agent 连接；
- 五个工具调用；
- SQLAlchemy 保存数据；
- 响应序列化；
- 非法服务返回 422。

测试环境把数据库 URL 设置为独立的 SQLite 文件：

```python
TEST_DATABASE_PATH = Path(...) / "test-opspilot.db"
os.environ["OPSPILOT_DATABASE_URL"] = (
    f"sqlite+aiosqlite:///{TEST_DATABASE_PATH.as_posix()}"
)
```

session 级自动 fixture 会在测试前删除旧表并重新建表，在测试结束后删除表和测试数据库文件。这样测试不依赖上一次运行留下的数据，也能模拟 CI 的干净环境。

这样测试速度快，不要求开发者每次都启动 PostgreSQL；同时不会因为本地残留数据库而产生“本机通过、CI 失败”的假象。

### 22.3 数据库迁移测试

迁移分别在 SQLite 和隔离 PostgreSQL 数据库验证。

SQLite 测试：

```text
upgrade → downgrade → upgrade
```

PostgreSQL 测试验证初次升级后存在：

```text
alembic_version
incidents
trace_events
```

### 22.4 容器端到端测试

容器测试验证最终交付物，而不是源码目录：

```text
浏览器入口
→ Nginx
→ API 容器
→ Agent
→ PostgreSQL 容器
```

这类测试发现了“镜像没有复制 simulator”问题。该问题在本地 pytest 中不会出现，因为本地源码目录里文件存在。

### 22.5 覆盖率

覆盖率表示测试执行过多少代码行。当前为 92.12%。

但覆盖率高不代表测试一定好：

```python
function()
```

虽然执行了代码，但如果没有断言结果，测试价值有限。

覆盖率应该作为“是否遗漏大量代码”的警报，而不是质量的唯一证明。

---

## 23. 静态检查与格式质量

### 23.1 Ruff

Ruff 检查：

- 未使用变量；
- 导入顺序；
- 常见 Python 错误；
- 可疑默认参数；
- 行长度和现代语法规则。

### 23.2 mypy

mypy 在运行代码前检查类型关系。

例如如果工具执行函数要求：

```python
dict[str, Any]
```

但调用处可能传入普通 `object`，mypy 会报告问题。Phase 0 通过给 calls 添加明确类型解决了这一问题：

```python
calls: list[tuple[str, dict[str, Any]]]
```

Python 类型提示不会自动阻止运行，但它能在大型项目中提前发现模块之间的契约错误。

### 23.3 ESLint 与 TypeScript

ESLint 检查 React 使用方式和 JavaScript/TypeScript 问题。

Phase 0 中它发现 Effect 里间接同步触发状态更新的写法不理想，我们改成 Promise 回调并增加组件卸载保护。

TypeScript 编译器检查字段、函数参数和返回值。Vite build 则进一步确认代码能生成浏览器可运行的生产包。

---

## 24. CI：在干净机器上重复验证

文件：`.github/workflows/ci.yml`

GitHub Actions 在 push 和 pull request 时执行两个任务。

后端任务：

```text
Python 3.11
→ 安装依赖
→ Ruff
→ mypy
→ pytest
→ 覆盖率至少 80%
```

前端任务：

```text
Node.js 22
→ npm ci
→ ESLint
→ Vite build
```

为什么本地已经测试，还需要 CI？

- 本地可能残留旧依赖；
- 开发者可能忘记运行某个命令；
- Windows 能运行的代码不一定能在 Linux 容器运行；
- CI 提供公开、可重复的质量记录。

CI 是团队共同遵守的自动化门禁，而不是某个人的口头保证。

---

## 25. Phase 0 中真实遇到的错误与经验

### 25.1 `MissingGreenlet`

原因：异步 SQLAlchemy 关系属性可能触发隐式数据库 I/O。

原思路：

```python
incident.trace.append(TraceEvent(...))
```

修复：

```python
session.add(
    TraceEvent(incident_id=incident.id, ...)
)
```

经验：异步程序中要让 I/O 显式出现，避免普通属性访问偷偷查询数据库。

### 25.2 容器缺少场景文件

原因：Dockerfile 没有复制 `simulator`。

经验：测试源码不等于测试交付物，必须运行最终镜像。

### 25.3 Python wheel 达到约 43 MB

原因：Hatch 把整个 `apps` 包打包，其中包含前端 `node_modules`。

修复：wheel 只打包核心 `opspilot`，API 源码由 Docker 显式复制。

经验：包边界要主动定义，不能依赖工具自动猜测。

### 25.4 Docker 构建上下文达到约 143 MB

原因：缺少 `.dockerignore`。

经验：构建上下文既是性能边界，也是安全边界。

### 25.5 Docker Hub DNS/网络问题

官方镜像授权服务在当前网络不可达。测试时从可访问的镜像代理拉取相同基础镜像，并标记为标准本地镜像名，没有把临时代理写入项目交付配置。

经验：基础设施错误和业务代码错误必须分开诊断。看到 Docker build 失败，不能立刻修改 Python 代码。

---

## 26. 推荐的代码阅读顺序

不要一开始从 React 大组件逐行读。建议按以下顺序，每一步都回答一个明确问题。

### 第一步：理解数据长什么样

1. `apps/api/schemas.py`
2. `opspilot/models/incident.py`

问题：请求字段、响应字段、数据库字段有什么区别？

### 第二步：理解流程规则

1. `opspilot/agent/state.py`
2. `opspilot/agent/orchestrator.py`

问题：Agent 当前有哪些状态？为什么不能任意跳转？

### 第三步：理解工具边界

1. `opspilot/tools/schemas.py`
2. `opspilot/tools/gateway.py`
3. `simulator/scenarios/scenarios.json`

问题：一个未知工具和一个参数非法的已知工具分别在哪里被拒绝？

### 第四步：理解 HTTP 与事务

1. `opspilot/db/session.py`
2. `apps/api/routes/incidents.py`
3. `apps/api/main.py`

问题：session 何时创建、何时提交、何时释放？

### 第五步：理解浏览器交互

1. `apps/web/src/api.ts`
2. `apps/web/src/App.tsx`
3. `apps/web/nginx.conf`

问题：浏览器为什么只请求 `/api/...`，却能找到 API 容器？

### 第六步：理解交付

1. `Dockerfile.api`
2. `apps/web/Dockerfile`
3. `docker-compose.yml`
4. `.github/workflows/ci.yml`

问题：源码如何变成可重复启动的四个服务？

---

## 27. 亲手验证项目的练习路线

### 练习 1：通过 API 创建事件

在 PowerShell 执行：

```powershell
$body = @{
  title = "Gateway 延迟告警"
  description = "gateway cpu and latency are increasing"
  severity = "P2"
  service_name = "gateway"
  source = "manual"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://localhost:8000/api/v1/incidents" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

观察返回的 `trace`，尝试数出 10 条轨迹。

### 练习 2：故意制造参数错误

把 severity 改成：

```text
P0
```

观察 FastAPI 返回 422。思考：为什么 Agent 没有运行？

### 练习 3：测试未知工具

阅读 `tests/unit/test_tools.py`，运行：

```powershell
E:\OpsPilotRuntime\.venv\Scripts\python.exe -m pytest tests/unit/test_tools.py -v
```

然后尝试把 `run_shell` 临时加入白名单，观察测试为何需要相应变化。学习时可以实验，但不要提交这个危险改动。

### 练习 4：增加一个 Mock 场景

为 `inventory` 增加：

- 一个根因；
- 一组指标；
- 两条日志；
- 一个 Runbook；
- 一个历史事件。

然后从页面创建 inventory 事件，确认最终答案发生变化。

### 练习 5：增加一个只读工具

例如 `get_recent_deployments`：

1. 在 tools schemas 中定义参数模型；
2. 加入 Gateway 白名单；
3. 在场景数据加入发布记录；
4. 在 Orchestrator 中调用；
5. 更新测试，确认轨迹从 10 条变为 11 条。

这个练习能帮助你理解一个功能如何跨越多个模块，但仍保持每层职责清晰。

### 练习 6：观察事务失败

在测试分支中故意让某个 TraceEvent 包含无法序列化的数据，观察 commit 失败后事件是否完整写入。借此理解事务“全部成功或全部失败”的意义。

---

## 28. 常用命令与每条命令的意义

### 后端安装

```powershell
E:\OpsPilotRuntime\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

`-e` 是 editable install，源码修改后通常无需重新安装项目本身。

### 后端检查

```powershell
E:\OpsPilotRuntime\.venv\Scripts\python.exe -m ruff check .
E:\OpsPilotRuntime\.venv\Scripts\python.exe -m mypy opspilot apps/api
E:\OpsPilotRuntime\.venv\Scripts\python.exe -m pytest
```

建议按 Ruff、mypy、pytest 的顺序运行：先解决速度快、定位明确的问题，再运行行为测试。

### 前端检查

```powershell
Set-Location apps/web
npm ci
npm run lint
npm run build
```

### 数据库迁移

```powershell
E:\OpsPilotRuntime\.venv\Scripts\python.exe -m alembic upgrade head
```

`head` 表示迁移到最新版本。

### Docker

```powershell
docker compose up --build -d
docker compose ps
docker compose logs api
docker compose down
```

- `up`：创建并启动；
- `--build`：启动前重新构建镜像；
- `-d`：后台运行；
- `ps`：查看容器状态；
- `logs`：查看日志；
- `down`：停止并删除容器网络，但默认不删除命名数据卷。

---

## 29. 初学者常见误区

### 误区 1：能运行就说明架构正确

一个 2000 行 `main.py` 也可能运行，但后续无法安全修改。架构的价值体现在变化发生时，影响能否被限制在合理范围。

### 误区 2：类型提示等于运行时校验

Python 类型提示主要给 mypy 和开发者看。外部 JSON 必须用 Pydantic做运行时校验。

### 误区 3：用了 ORM 就不用懂 SQL 和事务

ORM 最终仍生成 SQL。你仍需理解主键、外键、索引、事务、提交和回滚。

### 误区 4：大模型输出是可信的

模型输出本质上是外部输入。它可能格式错误、参数越界或尝试调用不存在的工具，必须经过 Schema、白名单和状态机。

### 误区 5：Mock 没有价值

好的 Mock 用来隔离外部不确定性，并保持真实调用路径。坏的 Mock 才是直接在页面写死结果、绕过系统。

### 误区 6：覆盖率越高越好

覆盖率是辅助指标。测试是否覆盖关键风险、是否有有效断言，比单纯追求 100% 更重要。

### 误区 7：容器启动等于服务可用

数据库进程启动后仍需初始化。必须通过 healthcheck 或应用级健康接口判断是否真正可用。

---

## 30. 术语表

| 术语 | 初学者解释 |
|---|---|
| Monorepo | 前端、后端和相关模块放在同一个 Git 仓库 |
| API | 程序之间通信的约定 |
| Schema | 数据应该包含哪些字段、字段是什么类型 |
| ORM | 用 Python 类操作关系数据库 |
| Migration | 可追踪、可升级和回退的数据库结构变更 |
| Dependency Injection | 由框架提供依赖，而不是函数自己创建依赖 |
| Async/Await | 等待 I/O 时让出执行权的异步编程方式 |
| Transaction | 一组数据库操作要么全部成功，要么全部失败 |
| State Machine | 明确定义状态及合法转换的流程模型 |
| Orchestrator | 负责组织步骤和调用顺序的编排模块 |
| Tool Gateway | Agent 访问工具前的统一验证和控制入口 |
| Mock | 用可控实现替代暂时不可用或不稳定的外部系统 |
| Reverse Proxy | 接收请求并转发给内部服务的代理 |
| Container | 包含程序和运行环境的隔离进程 |
| CI | 每次代码变化时自动执行质量检查 |
| Trace | 可持久化、可审计的执行过程记录 |
| Evidence-first | 结论必须能够追溯到证据 |

---

## 31. Phase 0 最重要的设计原则

请优先记住下面八条，而不是死记框架 API：

1. **输入必须验证**：用户输入和模型输出都不能直接信任。
2. **状态必须合法**：流程不能靠散落的 if/else 随意推进。
3. **工具必须白名单**：Agent 只能调用系统明确允许的能力。
4. **I/O 应该显式**：特别是在异步数据库代码中。
5. **结论必须引用证据**：不能只输出看似合理的自然语言。
6. **数据库结构必须版本化**：ORM 模型不能替代迁移。
7. **测试必须覆盖最终交付物**：源码测试通过不等于容器可运行。
8. **配置与代码分离**：环境差异通过配置表达，不复制业务代码。

这八条构成后续 Phase 1 的基础。下一阶段增加审批、RBAC、SSE 和受控变更时，仍然会沿用这些原则。

---

## 32. 学完后的自测问题

如果你能用自己的话回答以下问题，就说明已经真正理解 Phase 0：

1. 浏览器访问 `localhost:5173/api/v1/incidents` 后，请求实际经过哪些组件？
2. 为什么 API 容器连接数据库要使用 `postgres`，不能使用 `localhost`？
3. Pydantic API Schema 和 Tool Schema 分别保护哪一层边界？
4. `session.add()`、`flush()` 和 `commit()` 有什么区别？
5. 为什么异步 SQLAlchemy 中直接访问关系属性可能出错？
6. 为什么 Agent 使用状态机，而不是在一个函数里连续写 if/else？
7. Tool Gateway 如何阻止模型调用 `run_shell`？
8. 为什么最终答案要保存 evidence IDs？
9. Mock 场景和在前端写死结果有什么本质区别？
10. SQLAlchemy 模型和 Alembic 迁移分别解决什么问题？
11. 为什么本地 pytest 通过后仍然要测试 Docker 镜像？
12. `.dockerignore` 为什么既关系性能，也关系安全？
13. 单元测试、集成测试和 E2E 测试各自最适合发现什么问题？
14. 为什么 CI 要在干净环境重新运行本地已经通过的测试？
15. Phase 0 为什么不直接连接真实大模型和生产 Kubernetes？

建议不要只在心里回答。把答案写下来，并尝试指出对应代码文件。能够从设计原则定位到代码，是从“会语法”走向“会做项目”的关键一步。

---

## 33. 自测问题参考答案

建议先自己回答第 32 章的问题，再阅读本章。判断自己是否掌握的标准不是能否背出答案，而是能否沿着答案找到对应代码，并向别人解释为什么这样设计。

### 33.1 浏览器访问 `localhost:5173/api/v1/incidents` 后，请求实际经过哪些组件？

完整路径是：

```text
浏览器
  → 电脑的 5173 端口
  → Docker 端口映射
  → Web 容器中的 Nginx 80 端口
  → Nginx 匹配 location /api/
  → Docker 内部网络中的 api:8000
  → Uvicorn
  → FastAPI
  → incidents 路由
  → SQLAlchemy / Agent
  → PostgreSQL
```

返回路径按相反方向回到浏览器。

前端代码只写：

```typescript
fetch("/api/v1/incidents")
```

浏览器会把相对路径补全为当前页面来源，也就是 `http://localhost:5173/api/v1/incidents`。Nginx 根据 `apps/web/nginx.conf` 将 `/api/` 请求转发到 API 服务。

对应文件：

- `apps/web/src/api.ts`
- `apps/web/nginx.conf`
- `docker-compose.yml`
- `apps/api/routes/incidents.py`

### 33.2 为什么 API 容器连接数据库要使用 `postgres`，不能使用 `localhost`？

每个容器都有自己的网络空间。站在 API 容器内部看：

```text
localhost = API 容器自己
```

PostgreSQL 运行在另一个容器，所以访问 `localhost:5432` 会尝试连接 API 容器自己的 5432 端口，那里没有 PostgreSQL。

Docker Compose 会为服务提供内部 DNS。服务名 `postgres` 会解析到 PostgreSQL 容器的内部地址，因此正确连接地址使用：

```text
postgres:5432
```

只有从宿主机访问映射端口时，才通常使用 `localhost`。

对应文件：

- `.env.example`
- `docker-compose.yml`

### 33.3 Pydantic API Schema 和 Tool Schema 分别保护哪一层边界？

API Schema 保护外部客户端到 API 的边界：

```text
浏览器/调用者 → FastAPI
```

它检查事件标题、描述、严重级别和服务名等用户输入。

Tool Schema 保护 Agent 到工具的边界：

```text
Agent/未来的大模型 → Tool Gateway → 外部系统
```

它检查指标查询、日志查询和搜索参数，包括时间范围、关键词数量、返回数量等。

两层都需要校验，因为通过 API 校验的用户请求，不代表 Agent 后续构造的工具参数一定正确。未来大模型可能生成错误字段、越界值或者不存在的工具调用。

对应文件：

- `apps/api/schemas.py`
- `opspilot/tools/schemas.py`
- `opspilot/tools/gateway.py`

### 33.4 `session.add()`、`flush()` 和 `commit()` 有什么区别？

`session.add(object)`：

- 把 Python ORM 对象登记到当前 Session；
- 告诉 SQLAlchemy 这个对象需要保存；
- 不保证此时已经执行 SQL。

`await session.flush()`：

- 把待处理变更发送给数据库；
- 数据库会执行 INSERT/UPDATE；
- 可以获得数据库生成的值；
- 事务还没有最终提交，仍然可以回滚。

`await session.commit()`：

- 正式提交事务；
- 其他事务可以按照数据库隔离级别看到结果；
- 提交后的修改不再能通过普通 rollback 撤回。

本项目先 flush Incident，是为了在创建 TraceEvent 前获得 `incident.id`。Incident 和全部 TraceEvent 完成后再统一 commit，使它们属于同一事务。

可以用“填写转账单”类比：

```text
add    = 把转账单放入待处理队列
flush  = 银行系统开始处理，但交易尚未最终确认
commit = 正式确认整笔交易
```

对应文件：`apps/api/routes/incidents.py`。

### 33.5 为什么异步 SQLAlchemy 中直接访问关系属性可能出错？

ORM 关系属性可能还没有从数据库加载。访问：

```python
incident.trace
```

时，SQLAlchemy 可能想自动发送一条 SELECT，这叫懒加载。

问题在于普通属性访问不是 `await` 表达式，但异步数据库 I/O 必须在正确的异步上下文中显式等待。于是可能出现 `MissingGreenlet`。

Phase 0 最初使用：

```python
incident.trace.append(TraceEvent(...))
```

访问 `trace` 时触发了隐式加载。修复后直接创建带外键的对象：

```python
session.add(
    TraceEvent(
        incident_id=incident.id,
        ...,
    )
)
```

查询数据时则明确使用：

```python
selectinload(Incident.trace)
```

核心原则是：异步代码中的数据库 I/O 应该显式、可观察，不要隐藏在普通属性访问里。

对应文件：

- `apps/api/routes/incidents.py`
- `opspilot/models/incident.py`

### 33.6 为什么 Agent 使用状态机，而不是在一个函数里连续写 `if/else`？

简单流程可以用 if/else，但运维 Agent 后续会出现大量状态：

- 收集证据；
- 等待人工审批；
- 审批通过或拒绝；
- 执行变更；
- 执行失败；
- 回滚；
- 超时；
- 请求人工接管。

如果只用分散的 if/else，很难回答“从当前状态到底允许去哪里”，也容易产生未审批直接执行等危险路径。

状态机把规则集中表示为：

```python
当前状态 -> 允许的下一状态集合
```

每次转换统一调用 `assert_transition()`。非法转换立即失败，合法转换同时记录轨迹。

因此状态机的价值有三层：

1. 让流程容易理解；
2. 让非法路径可以测试；
3. 把安全规则变成不可绕过的代码约束。

对应文件：

- `opspilot/agent/state.py`
- `opspilot/agent/orchestrator.py`

### 33.7 Tool Gateway 如何阻止模型调用 `run_shell`？

Tool Gateway 维护显式白名单 `_schemas`：

```python
_schemas = {
    "query_metrics": MetricsQuery,
    "query_logs": LogsQuery,
    "get_service_info": ServiceInfoQuery,
    "search_runbook": SearchQuery,
    "search_incidents": SearchQuery,
}
```

执行工具时先查找：

```python
schema = self._schemas.get(tool_name)
```

如果模型请求 `run_shell`，字典里找不到，`schema` 就是 `None`，Gateway 抛出 `ToolValidationError`，不会进入任何执行逻辑。

这里采用“默认拒绝”策略：

```text
没有明确允许 = 禁止
```

它比“维护危险工具黑名单”安全，因为不可能列举所有潜在危险名称。

即使工具名合法，参数还必须通过对应 Pydantic Schema。白名单解决“能不能调用”，Schema 解决“能用什么参数调用”。

对应文件：

- `opspilot/tools/gateway.py`
- `tests/unit/test_tools.py`

### 33.8 为什么最终答案要保存 evidence IDs？

如果最终答案只有：

```text
Redis 网络异常是根因。
```

用户无法判断它是根据指标、日志还是模型猜测得出的。

保存 evidence IDs 后，可以把结论追溯到五次具体工具调用，包括：

- 调用了什么工具；
- 传入什么参数；
- 数据来自哪里；
- 返回了什么结果；
- 数据是在什么时间观察到的。

这带来以下能力：

- 解释诊断依据；
- 审计模型行为；
- 调查错误结论；
- 导出事件报告；
- 评测证据引用是否准确。

证据优先并不意味着模型一定正确，而是让模型结论可以被检查。

对应文件：`opspilot/agent/orchestrator.py`。

### 33.9 Mock 场景和在前端写死结果有什么本质区别？

前端写死结果会绕过：

- HTTP API；
- 请求校验；
- Agent 状态机；
- Tool Gateway；
- 数据库事务；
- 持久化；
- 容器网络。

它只能证明页面能显示一段数据。

OpsPilot 的 Mock 只替换最末端的数据来源，真实执行路径仍然是：

```text
React → Nginx → FastAPI → Agent → Gateway
→ Mock Scenario → SQLAlchemy → PostgreSQL → React
```

因此它能验证系统各层的真实契约。未来接入 Prometheus 时，只需要替换工具后端适配器，上层流程仍可复用。

对应文件：

- `simulator/scenarios/scenarios.json`
- `opspilot/tools/gateway.py`

### 33.10 SQLAlchemy 模型和 Alembic 迁移分别解决什么问题？

SQLAlchemy 模型描述应用当前期望的数据结构，并让 Python 代码以对象形式查询和修改数据。

Alembic 迁移描述真实数据库如何从旧版本一步一步变成当前结构。

类比：

```text
ORM 模型 = 建筑最终设计图
Alembic 迁移 = 从旧建筑改造成新建筑的施工步骤
```

只改 ORM 模型不会可靠地更新已经存在的数据库。例如删除一列、改列类型或迁移旧数据，都必须有明确迁移步骤。

对应文件：

- `opspilot/models/incident.py`
- `migrations/versions/20260924_0001_create_incidents.py`

### 33.11 为什么本地 pytest 通过后仍然要测试 Docker 镜像？

pytest 运行时直接访问工作区源码，因此所有本地文件都存在。但 Docker 镜像只包含 Dockerfile 中明确复制的内容。

Phase 0 曾出现：

- 本地测试通过；
- API 健康检查通过；
- 容器创建事件失败；
- 错误为 `FileNotFoundError`。

原因是 Dockerfile 忘记复制 `simulator/scenarios`。

所以不同测试层验证不同对象：

```text
pytest       验证源码环境中的模块协作
Docker build 验证能否正确打包
容器 E2E     验证最终交付物能否协同运行
```

对应文件：

- `Dockerfile.api`
- `.dockerignore`
- `docker-compose.yml`

### 33.12 `.dockerignore` 为什么既关系性能，也关系安全？

Docker 构建前会把构建上下文发送给 Docker Engine。没有 `.dockerignore` 时，可能发送：

- `node_modules`；
- `.git` 历史；
- 本地数据库；
- 测试报告；
- 缓存；
- `.env` 或其他秘密文件。

性能方面，文件越多，发送、校验和缓存计算越慢。Phase 0 曾发送约 143 MB，修复后降至 KB 级。

安全方面，即使 Dockerfile 当前没有 COPY 某个秘密，秘密仍可能进入构建上下文或被未来误复制。排除无关文件可以缩小泄露面。

`.dockerignore` 不能替代密钥管理，但它是重要的第二道防线。

对应文件：

- `.dockerignore`
- `apps/web/.dockerignore`

### 33.13 单元测试、集成测试和 E2E 测试各自最适合发现什么问题？

单元测试最适合发现局部规则错误：

- 非法状态转换没有被拒绝；
- 未知工具被错误放行；
- 某个纯函数结果错误。

它运行快、定位准确，但不能证明模块装配正确。

集成测试最适合发现模块接口问题：

- FastAPI 没有正确注入 Session；
- Pydantic 模型与路由不匹配；
- Agent 返回结构不能被 ORM 保存；
- 响应无法序列化。

E2E 测试最适合发现部署和完整链路问题：

- 镜像缺文件；
- Nginx 代理路径错误；
- 容器服务名错误；
- PostgreSQL 迁移未执行；
- 端口映射错误。

它们不是互相替代，而是形成测试金字塔：大量快速单元测试、适量集成测试、少量关键 E2E 测试。

### 33.14 为什么 CI 要在干净环境重新运行本地已经通过的测试？

本地环境可能存在隐藏条件：

- 上一次测试留下的数据库；
- 手工安装但未写入依赖文件的包；
- 未提交的配置文件；
- 本地缓存；
- 特定操作系统行为。

事实上，编写本教程时就发现测试曾可能依赖残留 SQLite 表。修复后，测试 fixture 会主动创建并清理数据库。

CI 每次从新的虚拟机和检出的仓库开始，可以验证：

```text
只依赖仓库中已经声明和提交的内容，项目是否仍能通过检查。
```

CI 还提供团队可见的统一结果，避免“我本地是好的”成为无法复核的结论。

对应文件：

- `.github/workflows/ci.yml`
- `tests/conftest.py`

### 33.15 Phase 0 为什么不直接连接真实大模型和生产 Kubernetes？

真实大模型具有随机性，还会引入：

- API 鉴权；
- 网络失败；
- 超时和限流；
- 模型输出格式错误；
- token 成本；
- 模型版本差异。

生产 Kubernetes 则涉及真实权限和业务风险。一个尚未验证安全边界的 Agent 不应该直接获得生产变更能力。

如果同时接入所有真实系统，出现错误时很难判断是：

- 页面问题；
- API 问题；
- 状态机问题；
- 模型问题；
- 工具问题；
- 网络问题；
- 权限问题；
- Kubernetes 问题。

Phase 0 使用确定性 Mock，可以先稳定验证架构、数据契约、状态机、轨迹和容器交付。后续阶段再逐步替换真实依赖，每次只增加有限变量。

安全上还遵循最小权限原则：

```text
先只读诊断
→ 再实现审批
→ 再实现预定义沙箱动作
→ 最后才讨论受控的真实系统集成
```

这不是为了回避真实场景，而是为了让真实集成建立在可测试、可审计和不可绕过的控制之上。

---

## 34. 如何使用这些答案继续学习

建议按以下方式复习每一道题：

1. 先遮住答案，用自己的话回答。
2. 找到答案列出的对应文件。
3. 在代码中指出真正实现该结论的语句。
4. 修改一个安全的小参数并运行测试。
5. 恢复修改，重新解释为什么测试结果发生变化。

当你能从“问题”走到“设计原则”，再从“设计原则”走到“具体代码和测试”，就不再只是记忆框架用法，而是在形成工程思维。
