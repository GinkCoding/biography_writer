# Apple Silicon (arm64) 环境配置指南

## 问题背景

你的 Mac 是 Apple Silicon (M1/M2/M3) 芯片，但当前终端可能在 Rosetta (x86_64) 模式下运行。
这导致 Python 包架构不匹配，无法正常运行。

## 快速开始

### 方法一：使用提供的脚本（推荐）

1. **安装依赖（arm64 模式）**:
```bash
/usr/bin/arch -arm64 /usr/local/bin/python3 setup_arm64.py
```

2. **运行项目**:
```bash
./run_arm64.sh
```

### 方法二：手动配置

1. **确保使用 arm64 模式的 Python**:
```bash
# 检查当前架构
/usr/bin/arch -arm64 /usr/local/bin/python3 -c "import platform; print(platform.machine())"
# 应该输出: arm64
```

2. **安装依赖**:
```bash
/usr/bin/arch -arm64 /usr/local/bin/python3 -m pip install -r requirements.txt
```

3. **运行程序**:
```bash
/usr/bin/arch -arm64 /usr/local/bin/python3 run_biography.py
```

## 永久解决方案（关闭 Rosetta）

如果你想让终端默认使用 arm64 模式：

1. 退出当前终端
2. 打开 **Finder** → **应用程序** → **实用工具**
3. 右键点击 **终端.app** → **显示简介** (Get Info)
4. **取消勾选** "使用 Rosetta 打开"
5. 重新打开终端

之后就可以正常使用:
```bash
python3 run_biography.py
```

## 验证环境

运行以下命令检查环境是否正确：

```bash
/usr/bin/arch -arm64 /usr/local/bin/python3 -c "
import platform
print(f'架构: {platform.machine()}')

try:
    import torch
    print(f'PyTorch: {torch.__version__}')
    print(f'MPS (Apple GPU) 可用: {torch.backends.mps.is_available()}')
except Exception as e:
    print(f'PyTorch: 错误 - {e}')

try:
    import sentence_transformers
    print(f'SentenceTransformers: 已安装')
except Exception as e:
    print(f'SentenceTransformers: 错误 - {e}')
"
```

## 架构对比

| 特性 | x86_64 (Rosetta) | arm64 (原生) |
|------|------------------|--------------|
| 性能 | 较慢（转译） | 最快（原生） |
| PyTorch GPU | 不支持 MPS | 支持 MPS |
| 内存使用 | 较高 | 较低 |
| 兼容性 | 通用 | 原生最优 |

**推荐**: 使用 arm64 原生模式以获得最佳性能。
