# AstrBot 贵金属高频监控与多因子分析系统 (Yuffie)

> **Yuffie (尤菲)** - 金银趋势量化罗盘

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/streamlit-1.28+-FF4B4B?logo=streamlit)](https://streamlit.io)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 📖 系统简介

Yuffie 是一个**高可用贵金属高频监控与多因子分析系统**，采用"底层基建与业务逻辑严格解耦"的架构设计。系统具备：

- ✅ **主备源熔断降级** - WebSocket 断线自动重连，指数退避，系统级熔断
- ✅ **动态 ATR 阈值** - 基于真实波动率的精准异常检测，非固定百分比
- ✅ **状态机保护** - 防网络抖动的冷却期机制，死信队列防丢消息
- ✅ **交易日历感知** - CME 日历、节假日过滤、开盘静默期
- ✅ **Web 监控仪表盘** - Streamlit + Plotly 交互式可视化
- ✅ **AstrBot 插件** - IM 机器人预警与深度研报

---

## 🏗️ 系统架构

```
astrbot_plugin_yuffie/
├── config.yaml              # 全局配置（WS 地址、ATR 系数、冷却时间）
├── main.py                  # AstrBot 插件入口
├── web_app.py               # Web 监控仪表盘 (Streamlit)
├── requirements.txt         # Python 依赖
├── readme.md                # 项目文档
├── test_sprint1.py          # Sprint 1 测试
├── test_sprint2.py          # Sprint 2 测试
├── test_real_stream.py      # 真实网络测试
│
├── core/                    # 基础设施层
│   ├── __init__.py
│   ├── data_stream.py       # 高频数据流 (WebSocket + 滑窗 + 熔断)
│   ├── indicators.py        # 量化计算引擎 (ATR、RSI、布林带)
│   ├── market_cal.py        # 交易日历 (CME、静默期)
│   └── state_manager.py     # 状态持久化 + 死信队列
│
└── plugins/                 # 业务插件层 (AstrBot)
    ├── __init__.py
    ├── alert_monitor.py     # 极速预警插件 (后台常驻)
    └── analysis_report.py   # 深度分析插件 (指令响应)
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置系统

编辑 `config.yaml`：

```yaml
monitor:
  symbol: "GC=F"              # 纽约期金
  cooldown_minutes: 30        # 预警冷却时间

atr_strategy:
  k_multiplier: 2.5           # ATR 触发倍数
  fallback_threshold: 10.0    # 降级绝对值阈值

data_sources:
  primary_ws: "wss://..."     # WebSocket 地址

calendar:
  exchange: "CME"
  open_mute_minutes: 30       # 开盘静默期
```

### 3. 启动 Web 监控仪表盘

```bash
# 启动 Web 服务
streamlit run web_app.py --server.port 8501

# 访问 http://localhost:8501
```

**实时数据模式**：

在 Web 界面侧边栏勾选"**使用实时数据 (Binance PAXG/USDT)**"，系统会：
1. 连接 Binance WebSocket: `wss://stream.binance.com:9443/ws/paxgusdt@trade`
2. 实时获取 PAXG/USDT 交易数据（PAXG 是锚定黄金的加密货币）
3. 自动计算 ATR、RSI、布林带等指标
4. 在图表上显示实时价格、阻力轨和支撑轨

默认使用模拟数据（演示模式），勾选后切换到实时数据模式。

将项目放置于 AstrBot 插件目录，在 AstrBot 配置中启用：

```yaml
plugins:
  astrbot_plugin_yuffie:
    enabled: true
    use_mock: false
    cooldown_minutes: 30
```

---

## 📊 Web 监控仪表盘功能

### 顶栏核心指标
- **最新金价** - 实时价格
- **ATR 波动率** - 动态波动率基准
- **灵敏度 (k)** - ATR 触发倍数
- **触发阈值** - k×ATR 计算结果

### 主图表 (Plotly)
- 金价走势折线图
- **阻力轨** (+k×ATR) - 红色虚线
- **支撑轨** (-k×ATR) - 绿色虚线
- 当前价格水平线
- 成交量柱状图

### 多因子分析面板
- **RSI 仪表盘** - 超买/超卖/中性可视化
- **移动平均** - MA20、MA50 位置关系
- **布林带** - 上轨/中轨/下轨
- **综合研判** - 多因子打分结论

### 系统健康状态
- **冷却期状态** - 上涨/下跌警报可用性
- **死信队列** - 待处理消息统计

---

## 🧪 测试验证

### Sprint 1: 状态机与日历
```bash
python test_sprint1.py
```

### Sprint 2: 数据流与指标
```bash
python test_sprint2.py
```

### 真实网络测试
```bash
python test_real_stream.py
```

**测试结果：**
- ✅ 指数退避重连 (1s → 2s → 4s → 8s)
- ✅ 熔断机制 (重连 4 次后抛出 CircuitBreakerException)
- ✅ 真实 WebSocket 连接 (wss://echo.websocket.org)
- ✅ 非 JSON 消息处理 (纯文本返回 None，不崩溃)

---

## 📈 核心技术特性

### 1. 高频数据流 (data_stream.py)
- WebSocket 长连接 + 内存滑窗 (deque)
- **指数退避重连**: `backoff = min(base × 2^(attempt-1), max_backoff)`
- **系统级熔断**: 重连 > 3 次抛出 `CircuitBreakerException`
- **消息解析容错**: 非 JSON 消息返回 None，不崩溃

### 2. 量化计算 (indicators.py)
- **动态 ATR**: 真实波动幅度，非固定百分比
- **异常检测**: `|ΔPrice| > k × ATR` 触发
- **降级保护**: ATR 无效时使用 `fallback_threshold`
- **多因子**: RSI、MA、布林带、动量

### 3. 状态管理 (state_manager.py)
- **先写状态，后发消息**: 防漏报设计
- **死信队列 (DLQ)**: 发送失败自动重试
- **SQLite 持久化**: 系统重启可恢复

### 4. 交易日历 (market_cal.py)
- CME 日历接入 (pandas_market_calendars)
- **休市判断**: 周末、节假日
- **静默期**: 开盘前后 30 分钟过滤假信号

---

## 🤖 AstrBot 指令

| 指令 | 说明 |
|------|------|
| `/黄金分析` | 获取深度分析报告 |
| `/监控状态` | 查看监控器运行状态 |
| `/测试警报` | 发送测试警报验证系统 |

---

## 📝 配置说明

### config.yaml 完整示例

```yaml
# 核心监控参数
monitor:
  symbol: "GC=F"
  poll_interval: 60
  cooldown_minutes: 30

# 量化预警阈值
atr_strategy:
  enabled: true
  period: 14
  k_multiplier: 2.5
  fallback_threshold: 10.0
  volume_surge_ratio: 1.5

# 数据源
data_sources:
  primary_ws: "wss://api.exchange.com/ws"
  fallback_api: "yfinance"

# 交易日历
calendar:
  exchange: "CME"
  open_mute_minutes: 30
```

---

## 🛠️ 开发记录

### Sprint 1: 核心基建
- ✅ `state_manager.py` - SQLite 持久化、冷却期、死信队列
- ✅ `market_cal.py` - CME 日历、休市/静默期判断

### Sprint 2: 数据流与指标
- ✅ `data_stream.py` - WebSocket、滑窗、熔断、指数退避
- ✅ `indicators.py` - ATR、RSI、布林带、异常检测
- ✅ 真实网络测试验证

### Sprint 3: 业务插件
- ✅ `alert_monitor.py` - 后台预警监控
- ✅ `analysis_report.py` - 深度研报生成
- ✅ `main.py` - AstrBot 入口

### Sprint 4: Web 监控
- ✅ `web_app.py` - Streamlit + Plotly 仪表盘

---

## ⚠️ 风险提示

> 本系统仅供参考，**不构成投资建议**。市场有风险，投资需谨慎。

---

## 📄 License

MIT License

---

*Yuffie 贵金属高频监控系统 | 数据驱动决策*
