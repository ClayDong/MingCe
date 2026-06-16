#!/usr/bin/env python3
"""
测试飞书通知发送
"""

import sys
import os
import json
from datetime import datetime
from pathlib import Path
from loguru import logger

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))

from qlib_vnpy_platform.config import load_config


def test_send_feishu_notification():
    """测试飞书通知发送"""
    logger.info("=" * 60)
    logger.info("测试飞书通知发送")
    logger.info("=" * 60)
    
    # 1. 检查配置文件
    config_path = Path(__file__).parent / "feishu_config.json"
    if not config_path.exists():
        logger.error(f"配置文件不存在: {config_path}")
        return False
    
    logger.info(f"✅ 找到配置文件: {config_path}")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            feishu_config = json.load(f)
        
        chat_id = feishu_config.get("chat_id")
        app_id = feishu_config.get("app_id")
        app_secret = feishu_config.get("app_secret")
        
        logger.info(f"配置信息:")
        logger.info(f"  chat_id: {chat_id}")
        logger.info(f"  app_id: {'已配置' if app_id else '未配置'}")
        logger.info(f"  app_secret: {'已配置' if app_secret else '未配置'}")
        
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        return False
    
    # 2. 检查 lark-cli
    import shutil
    import subprocess
    
    lark_cli_path = shutil.which("lark-cli")
    if not lark_cli_path:
        for p in [
            "/Users/dong/.nvm/versions/node/v24.14.0/bin/lark-cli",
            "/Users/dong/.nvm/versions/node/v22.22.3/bin/lark-cli",
            "/usr/local/bin/lark-cli",
        ]:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                lark_cli_path = p
                break
    
    if lark_cli_path:
        logger.info(f"✅ 找到 lark-cli: {lark_cli_path}")
        logger.info("尝试用 lark-cli 发送...")
        
        test_message = (
            f"🔔 **测试通知**\n"
            f"🕐 **{datetime.now().strftime('%Y-%m-%d %H:%M')}**\n"
            f"\n"
            f"来自: MakingMoney 系统测试\n"
            f"时间: {datetime.now().isoformat()}"
        )
        
        try:
            node_bin = os.path.dirname(lark_cli_path)
            node_env = os.environ.copy()
            node_env['PATH'] = node_bin + ':' + node_env.get('PATH', '')
            
            cmd = [lark_cli_path, "im", "+messages-send", "--chat-id", chat_id, "--markdown", test_message]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=node_env)
            
            if result.returncode == 0:
                logger.info("✅ lark-cli 发送成功!")
                logger.info(f"输出: {result.stdout[:200]}")
                return True
            else:
                logger.error(f"❌ lark-cli 发送失败:")
                logger.error(f"  退出码: {result.returncode}")
                logger.error(f"  标准输出: {result.stdout}")
                logger.error(f"  错误输出: {result.stderr}")
        except Exception as e:
            logger.error(f"❌ lark-cli 调用异常: {e}")
    else:
        logger.warning("⚠️ 未找到 lark-cli")
    
    # 3. 尝试飞书 API
    if app_id and app_secret:
        logger.info("尝试用飞书 API 发送...")
        
        try:
            import requests
            
            # 获取 token
            resp = requests.post(
                'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
                json={'app_id': app_id, 'app_secret': app_secret},
                timeout=10
            )
            data = resp.json()
            
            if data.get('code') != 0:
                logger.error(f"❌ 获取 token 失败: {data.get('msg')}")
            else:
                token = data['tenant_access_token']
                logger.info("✅ 获取 token 成功")
                
                # 发送消息
                body = {
                    'zh_cn': {
                        'title': '测试通知', 
                        'content': [[{
                            'tag': 'md', 
                            'text': (
                                f"🔔 **测试通知**\n"
                                f"🕐 **{datetime.now().strftime('%Y-%m-%d %H:%M')}**\n"
                                f"\n"
                                f"来自: MakingMoney 系统测试"
                            )
                        }]]
                    }
                }
                
                resp2 = requests.post(
                    'https://open.feishu.cn/open-apis/im/v1/messages',
                    params={'receive_id_type': 'chat_id'},
                    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                    json={'receive_id': chat_id, 'msg_type': 'post', 'content': json.dumps(body, ensure_ascii=False)},
                    timeout=15
                )
                
                if resp2.json().get('code') == 0:
                    logger.info("✅ 飞书 API 发送成功!")
                    return True
                else:
                    logger.error(f"❌ 飞书 API 发送失败: {resp2.json()}")
        except Exception as e:
            logger.error(f"❌ 飞书 API 调用异常: {e}")
    else:
        logger.warning("⚠️ app_id/app_secret 未配置，无法使用 API 方式")
    
    logger.warning("=" * 60)
    logger.warning("所有发送方式均失败")
    logger.warning("=" * 60)
    
    logger.info("\n💡 建议:")
    logger.info("1. 确认 lark-cli 是否已正确安装和配置")
    logger.info("2. 确认飞书机器人权限和 chat_id 是否正确")
    logger.info("3. 如果需要使用 API 方式，请正确配置 app_id 和 app_secret")
    return False


if __name__ == "__main__":
    success = test_send_feishu_notification()
    sys.exit(0 if success else 1)
