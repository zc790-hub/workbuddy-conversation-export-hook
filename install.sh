#!/bin/bash
# 安装 agent 对话导出 Skill
# 将 hooks 目录复制到 ~/.agent/hooks/conversation-export/ 并创建命令包装器

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 安装目标目录（可通过 AGENT_HOME 环境变量自定义）
AGENT_HOME="${AGENT_HOME:-$HOME/.agent}"
TARGET_DIR="$AGENT_HOME/hooks/conversation-export"
WRAPPER="$AGENT_HOME/hooks/run-conversation-export.sh"

# 查找可用的 Python 3
if command -v python3 &>/dev/null; then
    PYTHON="$(command -v python3)"
elif [ -x "$AGENT_HOME/binaries/python/versions/3.13.12/bin/python3" ]; then
    PYTHON="$AGENT_HOME/binaries/python/versions/3.13.12/bin/python3"
else
    echo "❌ 未找到 python3，请先安装 Python 3.8+"
    exit 1
fi

echo "🛠  安装 agent 对话导出 Skill..."
echo "   Python: $PYTHON"
echo "   安装到: $AGENT_HOME"

# 创建目标目录
mkdir -p "$TARGET_DIR"

# 复制 hooks 目录内容（保留已有配置）
cp -R "$SCRIPT_DIR/hooks/" "$TARGET_DIR/"
# 如果已有配置文件，不覆盖
if [ -f "$TARGET_DIR/hook-config.local.json" ]; then
    echo "   检测到本地配置: hook-config.local.json（优先使用）"
else
    cp "$SCRIPT_DIR/hooks/hook-config.json" "$TARGET_DIR/hook-config.local.json" 2>/dev/null || true
fi

# 创建命令包装器
cat > "$WRAPPER" <<EOF
#!/bin/bash
# agent 对话导出 Skill 包装器
# 用法: $WRAPPER [--conversation-id <id>] [--format json|markdown|text] [--output <path>] [--init]

exec "$PYTHON" "$TARGET_DIR/run_hook.py" "\$@"
EOF

chmod +x "$WRAPPER"

echo "✅ 安装完成"
echo "   脚本目录: $TARGET_DIR"
echo "   启动命令: $WRAPPER"
echo ""
echo "下一步:"
echo "  1. 运行初始化配置: $WRAPPER --init"
echo "  2. 测试导出: $WRAPPER --dry-run"
echo "  3. 加入 ~/.zshrc 的 EXIT trap 或定时任务中调用"
