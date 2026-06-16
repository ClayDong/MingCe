#!/usr/bin/env python3
"""检查飞书配置状态"""

import os
import json
import subprocess
import shutil
from pathlib import Path

print("=" * 60)
print("飞书配置状态检查")
print("=" * 60)

# 1. 检查配置文件
config_path = str(Path(__file__).parent / "feishu_config.json")
print(f"\n1. 配置文件检查:")
print(f"   路径: {config_path}")
print(f"   存在: {os.path.exists(config_path)}")

if os.path.exists(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    print(f"   chat_id: {config.get('chat_id', '未配置')}")
    print(f"   app_id: {config.get('app_id', '未配置')}")
    print(f"   app_secret: {config.get('app_secret', '未配置')}")

# 2. 检查 lark-cli
print(f"\n2. lark-cli 检查:")
lark_cli = shutil.which("lark-cli")
print(f"   系统PATH: {lark_cli or '未找到'}")

# 检查常见路径
common_paths = [
    "/Users/dong/.nvm/versions/node/v24.14.0/bin/lark-cli",
    "/Users/dong/.nvm/versions/node/v22.22.3/bin/lark-cli",
    "/usr/local/bin/lark-cli",
    "/usr/bin/lark-cli",
]

for p in common_paths:
    exists = os.path.isfile(p) and os.access(p, os.X_OK)
    print(f"   {p}: {exists}")

# 3. 检查 Node.js
print(f"\n3. Node.js 检查:")
node = shutil.which("node")
print(f"   node: {node or '未找到'}")
npm = shutil.which("npm")
print(f"   npm: {npm or '未找到'}")

# 4. 检查 nvm
print(f"\n4. NVM 检查:")
nvm_dir = "/Users/dong/.nvm"
print(f"   NVM目录: {os.path.exists(nvm_dir)}")
if os.path.exists(nvm_dir):
    versions_dir = os.path.join(nvm_dir, "versions", "node")
    if os.path.exists(versions_dir):
        versions = os.listdir(versions_dir)
        print(f"   已安装版本: {versions}")

print("\n" + "=" * 60)
print("检查完成")
print("=" * 60)