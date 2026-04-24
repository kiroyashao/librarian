# Librarian

> [Forge](https://github.com/kiroyashao/forge.git) 项目的子项目

Librarian 是一个基于 LangGraph/LangChain 构建的 AI Skills 管理系统。它自动化地组织、去重、评估和维护 AI skills，支持人工审核工作流、定时任务和 REST API。

---

## 为什么需要 Librarian？

在 Forge 项目中，skills 采用文件夹分类的方式进行组织。虽然这种方式结构清晰，但存在以下显著问题：

- **冗余严重**：不同文件夹中的 skills 经常包含重叠或重复的内容，导致维护困难且行为不一致。
- **结构僵化**：扁平的文件夹层级无法表达 skills 之间的复杂关系，难以导航和发现相关能力。
- **管理低效**：随着 skill 数量的增长，手动组织变得不可持续。修剪过时的 skills、检测重复项和维护交叉引用需要持续的人工干预。
- **缺乏动态适应能力**：静态的文件夹结构无法随着 skill 生态系统的发展而演进。新 skills 的添加缺乏智能路由，过时的 skills 无法自动清理。

**Librarian 的目标就是解决这些问题**。它通过引入多智能体系统，将扁平的 skill 集合转化为**嵌套的、层次化的 skills 树形结构**。这棵树由专门的智能体动态管理，负责：

- 智能 skill 路由和分类
- 自动去重和质量评估
- 维护相关 skill 之间的交叉链接
- 修剪过时或低质量的 skills
- 工具合成和安全监管

最终实现一个自组织、自维护的 skills 生态系统，能够优雅地扩展，并消除原始文件夹方式带来的冗余和低效问题。

---

## 架构设计

Librarian 采用多智能体架构，包含以下专业化工人节点：

| 工人节点 | 职责 |
|---------|------|
| `SkillRouter` | 将输入的 skills 路由到合适的分类 |
| `SkillEvaluator` | 评估 skill 质量，支持可配置的阈值 |
| `SkillDeduplicator` | 检测并去除重复的 skills |
| `SkillSplitter` | 将大型 skills 拆分为可管理的块 |
| `SkillPruner` | 移除过时或低质量的 skills |
| `SkillLinkMaintainer` | 维护 skills 之间的交叉引用 |
| `ToolSynthesizer` | 从 skill 能力中合成工具 |
| `ToolGuardian` | 确保工具安全性，支持人工审核 |

---

## 安装

```bash
# 克隆仓库
git clone https://github.com/kiroyashao/librarian.git
cd librarian

# 安装依赖
uv pip install -e .

```

---

## 配置

Librarian 使用 YAML 配置文件（`librarian.yaml`）进行系统设置，使用环境变量存储敏感凭证。

### 主要配置选项

```yaml
llms:
  - name: llm-1
    model: <MODEL>
    apiKey: <API_KEY>
    apiBase: <API_BASE>
  ...
workers:
  SkillEvaluator:
    llm: llm-1
    qualityThreshold: 0.7
    requireHumanReview: false
    categories:
      - data_analysis
      - web_scraping
      - file_management
  ...
skillTriggerThreshold: 10  # 触发工作流所需的 skill 数量
maxRejectionCount: 3       # 被拒绝多少次后丢弃

api:
  port: 9112
  host: "0.0.0.0"
```

完整配置模板请参考 [librarian.yaml](librarian.yaml)。

---

## 使用方法

### 启动服务器

```bash
python main.py
```

API 服务器默认启动在 `http://localhost:9112`。

---

## API 参考

### Skills 管理

#### 获取单个 Skill

```http
GET /skills/{skill_name}
```

**响应：**
```json
{
  "record": { ... },
  "frontmatter": { ... },
  "content": "# Skill 内容..."
}
```

#### 获取 Skill 链接关系

```http
GET /skills/{skill_name}/links
```

---

### 人工审核

#### 获取待审核列表

```http
GET /reviews
```

#### 提交审核结果

```http
POST /reviews/{review_id}
Content-Type: application/json

{
  "approved": true,
  "comment": "审核通过！"
}
```

---

## 定时任务

Librarian 内置了定时任务调度器，用于周期性维护：

```yaml
cronjobs:
  enabled: true
  jobs:
    cleaner:
      schedule: "0 0 */3 * *"  # 每 3 天午夜执行
    merger:
      schedule: "0 0 */3 * *"
```

Cron 表达式遵循标准 Unix cron 格式。

---

## 项目结构

```
librarian/
├── src/
│   ├── api/              # FastAPI 服务器
│   ├── config/           # 配置管理
│   ├── db/               # 数据库管理器
│   ├── git_manager/      # Git 版本控制
│   ├── models/           # 数据模型
│   ├── tools/            # 内置工具
│   ├── workers/          # 多智能体工人节点
│   └── workflows/        # 工作流定义
├── tests/                # 单元测试和集成测试
├── data/                 # SQLite 数据库
├── librarian.yaml        # 配置文件
└── main.py               # 入口文件
```

---

## 许可证

本项目是 Forge 生态系统的一部分。
