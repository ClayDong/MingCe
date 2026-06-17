"""关键任务失败告警 — 关键链路失败时推送到飞书。

双通道发送：
1. 优先使用 ALERT_WEBHOOK_URL（独立 webhook，不依赖 app 凭证）
2. 回退到飞书应用卡片消息（复用 FEISHU_APP_ID/SECRET + CHAT_ID）
"""

import httpx
from loguru import logger


async def send_alert(message: str, level: str = "warning"):
    """发送告警到飞书群。

    Args:
        message: 告警内容
        level: 告警级别 (warning / error / critical)
    """
    try:
        from config.settings import get_settings
        settings = get_settings()
    except Exception as e:
        logger.debug(f"send_alert: failed to import settings: {e}")
        logger.warning(f"ALERT ({level}): {message}")
        return

    webhook_url = getattr(settings, "ALERT_WEBHOOK_URL", "")
    sent = False

    # 通道1：webhook（若配置）
    if webhook_url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(webhook_url, json={
                    "msg_type": "interactive",
                    "card": {
                        "header": {
                            "title": {"tag": "plain_text", "content": f"⚠️ 明策告警 [{level}]"},
                            "template": "red" if level == "critical" else ("yellow" if level == "error" else "blue"),
                        },
                        "elements": [
                            {"tag": "markdown", "content": message},
                            {"tag": "note", "elements": [{"tag": "plain_text", "content": f"明策系统 · {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]},
                        ],
                    },
                })
                if resp.status_code == 200:
                    sent = True
                else:
                    logger.error(f"告警 webhook 返回非200: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            logger.error(f"告警 webhook 发送失败: {e}")

    # 通道2：回退到飞书应用卡片消息（复用已配置的 app 凭证）
    if not sent:
        chat_id = getattr(settings, "FEISHU_CHAT_ID", "")
        if chat_id:
            try:
                from services.feishu_service import send_card_message
                card = {
                    "header": {
                        "title": {"tag": "plain_text", "content": f"⚠️ 明策告警 [{level}]"},
                        "template": "red" if level == "critical" else ("yellow" if level == "error" else "blue"),
                    },
                    "elements": [
                        {"tag": "markdown", "content": message},
                        {"tag": "note", "elements": [{"tag": "plain_text", "content": f"明策系统 · {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]},
                    ],
                }
                ok = await send_card_message(chat_id, card)
                if ok:
                    sent = True
            except Exception as e:
                logger.error(f"告警飞书卡片回退发送失败: {e}")

    if not sent:
        logger.warning(f"ALERT ({level}, all channels failed): {message}")
    else:
        logger.info(f"ALERT ({level}) sent successfully")
