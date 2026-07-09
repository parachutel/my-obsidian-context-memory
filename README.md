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
- `Stop`：写入元数据 checkpoint，只保存状态和单向指纹，不保存 prompt、回答或 transcript。
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
git clone git@github.com:parachutel/my-obsidian-context-memory.git
cd my-obsidian-context-memory
python3 scripts/install.py --vault "/absolute/path/to/your/Obsidian/Vault"
```

安装器会：

1. 安装 Skill 到 `${CODEX_HOME:-~/.codex}/skills/obsidian-context-memory`。
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
MEMORY="${CODEX_HOME:-$HOME/.codex}/skills/obsidian-context-memory/scripts/obsidian_memory.py"

python3 "$MEMORY" doctor
python3 "$MEMORY" recall --cwd "$PWD" --query "current task"
python3 "$MEMORY" archive --cwd "$PWD" --input /path/to/task-packet.json
```

Archive packet 的完整字段见 [`skill/obsidian-context-memory/references/schema.md`](skill/obsidian-context-memory/references/schema.md)。

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

## 安全与隐私

- 默认只读取和写入 Vault 的 `Codex/` 命名空间。
- 普通 Obsidian 笔记只有在配置为 shared root 且含 `codex_share: true` 时才会进入候选集。
- 自动 Hook 只注入候选路径，不注入整篇笔记。
- `Stop` checkpoint 不保存原文，只保存 SHA-256 指纹和生命周期状态。
- `sensitivity: secret` 强制生成 metadata-only 任务记录。
- 写入会拒绝 symlink 逃逸，并使用本地锁、临时文件和唯一文件名降低并发/iCloud 冲突。
- 内置常见 token、密钥、密码和私钥模式的脱敏。

自动脱敏不能替代良好的秘密管理。不要把 `.env`、凭据、完整 transcript 或无关个人数据交给记忆库。

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
python3 -m py_compile skill/obsidian-context-memory/scripts/obsidian_memory.py scripts/install.py
python3 -m unittest discover -s tests -v
```

CI 在 Python 3.9 和当前稳定版 Python 上运行相同测试。
