#!/usr/bin/env python3
"""
测试新的飞书机器人能否正常发送消息
"""
import sys
import json
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def test_send():
    config_file = Path(__file__).parent / "feishu_config.json"
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    app_id = config['app_id']
    app_secret = config['app_secret']
    chat_id = config.get("chat_id", "")
    
    print(f"测试机器人: {app_id}")
    
    # 获取 token
    resp = requests.post(
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': app_id, 'app_secret': app_secret},
        timeout=10
    )
    token_data = resp.json()
    if token_data.get('code') != 0:
        print(f"❌ 获取 token 失败: {token_data}")
        return
    
    token = token_data['tenant_access_token']
    print(f"✅ 获取 token 成功")
    
    # 发送测试消息
    body = {
        'zh_cn': {
            'title': '策略监控机器人',
            'content': [[{'tag': 'md', 'text': f'🤖 新机器人已上线！\n\n可用命令：\n- **报告** → 生成策略报告\n- **状态** → 查看策略状态\n- **排名** → 查看收益排名\n- **持仓** → 查看持仓详情\n- **帮助** → 显示帮助信息'}]]
        }
    }
    
    resp = requests.post(
        'https://open.feishu.cn/open-apis/im/v1/messages',
        params={'receive_id_type': 'chat_id'},
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        },
        json={
            'receive_id': chat_id,
            'msg_type': 'post',
            'content': json.dumps(body, ensure_ascii=False)
        },
        timeout=15
    )
    
    result = resp.json()
    if result.get('code') == 0:
        print("✅ 消息发送成功！请检查飞书群")
    else:
        print(f"❌ 消息发送失败: {result}")

if __name__ == "__main__":
    test_send()
