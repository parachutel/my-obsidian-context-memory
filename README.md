# Obsidian Context Memory for Codex

把 Obsidian Vault 作为 Codex 的可审计、跨任务上下文记忆库。项目开始时召回相关历史，任务结束时归档精简结论，同时避免保存完整对话、隐藏推理和凭据。

## 架构

```text
AGENTS.md（全局调度）
        ↓
Skill（受控召回、验证、结构化归档）
        ↓
Hooks（SessionStart / UserPromptSubmit / Stop）
        ↓
Obsidian Vault/Codex（Markdown 持久记忆）
```

- `SessionStart`：注入当前项目的少量候选记忆路径。
- `UserPromptSubmit`：按当前任务检索候选路径，并创建不含原始提示词的 turn 状态。
- `Stop`：若本轮仍是 pending，先用 `decision: block` 请求一次 archive/skip；成功后不写 checkpoint，只有继续后的第二次 Stop 仍未处理才写一个 `partial` 元数据 checkpoint。
- Skill：按需读取有限摘要，验证后归档 Task、Decision 和 Knowledge。

所有从 Vault 召回的内容都被视为不可信历史数据；当前用户指令与当前证据始终优先。

## 要求

- macOS 或 Linux（脚本使用 POSIX 文件锁）
- Python 3.9+
- 支持 Hooks 和 Skills 的 Codex
- 一个已在本机下载的 Obsidian Vault

不依赖 Obsidian 社区插件、REST API、MCP、向量数据库，也不要求 Obsidian 正在运行。

## 一键安装

```bash
git clone git@github.com:parachutel/my-obsidian-context-memory.git \
  "$HOME/.agents/skills/obsidian-context-memory"
python3 "$HOME/.agents/skills/obsidian-context-memory/scripts/install.py" \
  --vault "/absolute/path/to/your/Obsidian/Vault"
```

仓库根目录就是 Skill 根目录；推荐直接 clone 到 Codex 官方 USER Skill 目录。这样安装文件本身就是 Git checkout，不再维护第二份复制品。

安装器会：

1. 使用或安装 Skill 到 `$HOME/.agents/skills/obsidian-context-memory`。
2. 写入 `${CODEX_HOME:-~/.codex}/obsidian-context-memory/config.json`。
3. 合并三个 Hook 到 `hooks.json`，保留其他 Hook。
4. 在全局 `AGENTS.md` 中维护一个带标记的调度块。
5. 将 Vault 的 `Codex/` 命名空间和本地状态目录加入 `sandbox_workspace_write.writable_roots`。
6. 在修改已有配置前备份到 `obsidian-context-memory/backups/<timestamp>/`。
7. 初始化 Vault 中隔离的 `Codex/` 目录。

然后重启 Codex，在聊天输入框执行 `/hooks`，审核并信任：

- `SessionStart`
- `UserPromptSubmit`
- `Stop`

Hook 定义更新后，Codex 可能显示 `modified`，需要重新审核。安装器不会绕过 Hook 信任机制。

### 升级

```bash
cd "$HOME/.agents/skills/obsidian-context-memory"
git pull --ff-only
python3 scripts/install.py --vault "/absolute/path/to/your/Obsidian/Vault"
```

`doctor` 会报告版本清单、当前 Git commit、三个 Hook 是否各自只有一个精确处理器，以及脚本/config 路径是否指向当前 checkout。文件本身无法证明 Hook 已被信任；每次 Hook 定义变化后仍须运行 `/hooks`。

### 安装选项

```bash
python3 scripts/install.py --help
python3 scripts/install.py --vault "/path/to/vault" --dry-run
python3 scripts/install.py --vault "/path/to/vault" --managed-root "Codex"
python3 scripts/install.py --vault "/path/to/vault" --skip-config-toml
```

如果使用自定义 `CODEX_HOME`：

```bash
CODEX_HOME="$HOME/custom-codex" python3 scripts/install.py --vault "/path/to/vault"
```

## 使用

自动 Hooks 生效后，正常使用 Codex 即可。手动命令如下：

```bash
MEMORY="$HOME/.agents/skills/obsidian-context-memory/scripts/obsidian_memory.py"

python3 "$MEMORY" doctor
python3 "$MEMORY" recall --cwd "$PWD" --query "current task"
python3 "$MEMORY" recall --cwd "$PWD" --query "current task" --format json --explain
python3 "$MEMORY" archive --cwd "$PWD" --input /path/to/task-packet.json --validate
python3 "$MEMORY" archive --cwd "$PWD" --input /path/to/task-packet.json
```

Archive packet 的最小字段是非空的 `title`、`status` 和 `summary`。未知字段默认报错；完整字段见 [`references/schema.md`](references/schema.md)。

## Vault 结构

```text
Codex/
├── _System/
├── Projects/<project-key>/
│   ├── Project.md
│   ├── Tasks/YYYY/
│   ├── Decisions/YYYY/
│   └── Checkpoints/By-Turn/
├── Knowledge/<domain>/
├── Inbox/
└── Quarantine/
```

项目身份优先使用规范化 Git remote；没有 remote 时使用 Git root，非 Git 目录使用当前路径的短哈希。不会把 remote 中的凭据写入 Vault。

若多个 Codex 生成目录属于同一个逻辑项目，必须显式绑定，不做静默合并：

```bash
python3 "$MEMORY" project bind stable-project-key --cwd "$PWD" --display "Project name"
```

绑定保存在本地 state 目录，不写入普通 Vault 笔记。

## 安全与隐私

- 默认只读取和写入 Vault 的 `Codex/` 命名空间。
- 普通 Obsidian 笔记只有在配置为 shared root 且含 `codex_share: true` 时才会进入候选集。
- 自动 Hook 只注入候选路径，不注入整篇笔记。
- 正常 archive/skip 后 `Stop` 不生成 checkpoint；未解决的二次 Stop 只保存 turn 生命周期元数据，不保存原文或内容指纹。
- `sensitivity: secret` 强制生成 metadata-only 任务记录。
- 写入会拒绝 symlink 逃逸，并使用本地锁、临时文件和唯一文件名降低并发/iCloud 冲突。
- 内置常见 token、密钥、密码和私钥模式的脱敏。

自动脱敏不能替代良好的秘密管理。不要把 `.env`、凭据、完整 transcript 或无关个人数据交给记忆库。

## 与 Codex local Memories 共存

本 Skill 把 Obsidian Markdown 定义为权威、人工可审计的持久层。Codex local Memories 默认建议关闭；如果启用，只作为自动生成的辅助召回层：

- 避免同时开启自动生成和 Obsidian 归档，除非明确接受重复捕获。
- 可保留既有 Memories 的注入，但必须像其他历史上下文一样复核。
- 必须遵守的规则继续放在 `AGENTS.md`。

`doctor` 会读取公开的 `features.memories`、`memories.generate_memories` 和 `memories.use_memories` 配置并提示双重生成/注入。

## 检索与规模

召回使用 BM25/IDF、标题、项目、类型、置信度、时效和 supersession 组合排序，并限制单项目占用；`--explain` 可查看分数组成。Hook 候选扫描不会构造 excerpt。

默认不引入后台服务、向量库或 MCP。只有 eligible note 超过 2,000，或真实 Vault 的 p95 recall 超过 500 ms 时，才考虑可重建的本地 FTS/mtime cache；Markdown 始终是权威来源。

## iCloud 注意事项

- 保持 Vault 已下载到本机。
- 同一个 Vault 只使用一种双向同步系统。
- iCloud/Obsidian Sync 都不是备份；请维护独立、版本化备份。
- 远程或云端 Codex 无法直接访问本机 iCloud Vault。

## 手动配置

安装器使用的通用模板位于 [`config/`](config/)：

- `hooks.example.json`
- `AGENTS.md.example`
- `memory-config.example.json`
- `config.toml.example`

已有配置必须合并，不能直接用示例文件覆盖。

## 开发与验证

```bash
python3 -m py_compile scripts/obsidian_memory.py scripts/install.py
python3 -m unittest discover -s tests -v
```

CI 在 Python 3.9 和当前稳定版 Python 上运行相同测试。
