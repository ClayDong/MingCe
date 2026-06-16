"""关键任务失败告警 — 关键链路失败时推送到飞书。"""

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
    if not webhook_url:
        logger.debug(f"ALERT ({level}, no webhook): {message}")
        return

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
            if resp.status_code != 200:
                logger.error(f"告警发送返回非200: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"告警发送失败: {e}")
