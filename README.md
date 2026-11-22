# 榆弦谱库·曲谱目录页索引

实现 B+ 树叶页和内部页分裂，沿叶页链查编号区间。面向演示数据和本地复现，场景、操作剧本和业务边界见 [BUSINESS.md](BUSINESS.md)。

## 业务模块

- 曲目索引批
- 页容量设置
- 索引巡检
- 业务证据
- 范围借阅单

## 本地运行

```sh
cp -n .env.example .env
docker compose up -d --build --wait
```

- 工作台 `http://127.0.0.1:18293`
- FastAPI 文档 `http://127.0.0.1:19293/docs`
- MySQL 8.0 端口 `127.0.0.1:17793`，账号 `app`，演示库 `workflow`
- `docker compose exec -T backend python -m scripts.seed_demo` 手动重跑演示数据
- `docker compose logs -f backend worker` 查看运行情况
- `docker compose down` 停容器并保留演示卷

### 演示账号

统一密码 `Demo-Walkthrough-2026`。

| 账号 | 角色 | 能执行的操作 |
|---|---|---|
| `operator` | 经办员 | 读取档案、创建实验输入、提交执行、导出结果 |
| `reviewer` | 复核员 | 读取、导出和签署结果 |
| `viewer` | 观察员 | 读取、导出已有结果 |

`SEED_DEMO=true` 启动时生成账号与一个业务样例。工作台新建档案会预填样例。可编辑表单中的数值、文本和结构化 JSON 后提交。业务说明中的原始文件是上游示例，演示数据通过表单录入。角色枚举位于后端 `src/constants/workflow.py` 与前端 `src/constants/workflow.js`。执行状态枚举也位于这两个文件，使用于队列、列表和执行详情。证据校验码是报告 JSON 按 UTF-8、键排序且省略多余空格序列化后的 SHA-256。

## 工程结构

| 服务 | 实现 |
|---|---|
| frontend | Nginx 与原生 HTML、CSS、JavaScript |
| backend | Python 3.11、FastAPI、SQLAlchemy |
| worker | Python 持久队列执行与 Redis 唤醒信号 |
| db | MySQL 8.0，持久卷保存档案、执行、证据及审计 |
| redis | Redis 7，追加日志卷保存队列唤醒信号 |

编辑 `backend/src/services/domain.py` 可修改试算方法与业务表单说明。留谱判定规则位于 `backend/src/services/lending_rules.py`，借阅单与库存的事务、行锁与幂等位于 `backend/src/services/lending.py`。API 路由、数据定义和页面位于 `backend/src/routes/`、`backend/src/models/` 与 `frontend/src/pages/`。开发时更新源文件后重新构建对应服务。

### 留谱借阅单 API

留谱数据（`inventory_scores` 库存、`lending_orders` 借阅单、`lending_order_items` 明细则）随 API 启动建表；`SEED_DEMO` 启动时按已有档案回填库存。

- `GET /lending/inventory/{case_id}`：该批次每种曲谱的在库、已留和可留份数。
- `GET /lending/orders`、`GET /lending/orders/{id}`：借阅单列表与单张明细（含已留编号、缺货编号与结论）。
- `POST /lending/orders`：提交范围借阅单，字段为 `case_id`、`start_number`、`end_number` 与可选 `request_key`。缺货整单不留，空段退回；同一请求键与同一批次、同一编号段重复提交返回首次结果，请求键被不同编号段复用则返回冲突。
- `POST /lending/orders/{id}/cancel`：撤销并只归还本单留过的份数，重复撤销无副作用。

重叠编号段的并发提交在同一事务内以条件更新判断可留份数，不会超留；不相交编号段互不阻塞。再次运行范围查询时，`范围借阅单` 明细会按 `已留份数` 扣减可借份数。

`.env.example` 提供 `FRONTEND_PORT`、`BACKEND_PORT`、`DB_PORT`、`DB_PASSWORD`、`AUTH_KEY` 、`SEED_DEMO` 与 `NETWORK_SUBNET`。修改 `NETWORK_SUBNET` 可避开本机现有容器网段。所有发布的端口绑定本机回环地址。接入独立部署前需配置自己的凭据并按业务范围做独立验收。

[MIT License](LICENSE)
