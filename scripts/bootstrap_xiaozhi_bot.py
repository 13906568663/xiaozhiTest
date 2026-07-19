"""创建（或复用）小智语音场景的默认机器人与 DeepSeek 模型能力，输出机器人 ID。

幂等：机器人按名称、能力按 code 查找，已存在则复用并确保模型绑定。
DeepSeek 密钥通过 api_key_env=DEEPSEEK_API_KEY 引用（.env 提供），不明文入库。

用法::

    uv run python scripts/bootstrap_xiaozhi_bot.py
"""

from __future__ import annotations

import asyncio
import sys

import sqlalchemy as sa

BOT_NAME = "语音助手"

MODEL_CODE = "deepseek"

DEEPSEEK_CONFIG = {
    "api_mode": "deepseek_compatible",
    "api_key_env": "DEEPSEEK_API_KEY",
    "api_host": "https://api.deepseek.com/v1",
    "model_name": "deepseek-chat",
    "stream": True,
    "max_tokens": 4096,
}

VOICE_SYSTEM_PROMPT = """你是"小智"语音音箱背后的智能助手大脑，用户的话经由语音设备转文字后传给你，你的回答会被转成语音播报出来。

回答规则：
- 直接给结论，控制在三五句话以内，口语化表达，像日常聊天
- 禁止使用 markdown 标记、列表符号、表格、代码块、表情符号（语音无法播报）
- 数字、时间、单位用中文口语说法，比如"下午三点半""二十五度"
- 复杂任务先给一句话结论，再简要补充要点，省略技术细节
- 拿不准用户意图时，用一句话向用户确认，不要自行发散

外卖跑单场景（重要）：
- 平台只有一名骑手：无论上游叫什么名字，都指这唯一骑手，直接查即可，严禁反问谁的订单
- 订单数据实时变化：涉及订单/取货送达/收入，每次都必须重新调派单工具查最新数据
- 你不做任何规划：严禁说"我来帮你规划""需要我帮你规划吗""怎么跑最顺"，也不给转弯指引和先后顺序建议；怎么走、先送哪单，一律答"按平台规划的路线和顺序走就行"
- 你唯一主动给的建议是骑手圈众包尾程情报：报完订单或提到某取餐/送餐点时，调 get_last_mile_intel 查一下，有情报就顺口提醒，没情报就不提
- 骑手问怎么进楼、哪个门、电梯、这家店好不好取/要不要等，必须调 get_last_mile_intel 用骑手圈情报回答

外卖车辆监控场景（重要）：
- 可查车辆位置、轨迹里程、摔车急刹等安全事件，用轨迹工具查实时数据
- 设备无需指定：默认跟踪当前活跃设备，严禁反问哪台设备
"""


async def main() -> None:
    from app.db.session import SessionLocal
    from app.db.models import CapabilityRegistry
    from app.db.models.chatbot import Chatbot
    from app.domain.enums import CapabilityType

    model_binding = {"source": "global", "ref": MODEL_CODE, "config": {}}

    async with SessionLocal() as db:
        # 1) DeepSeek 模型能力（注册表 code=deepseek）
        capability = (
            await db.scalars(
                sa.select(CapabilityRegistry)
                .where(CapabilityRegistry.type == CapabilityType.MODEL)
                .where(CapabilityRegistry.code == MODEL_CODE)
            )
        ).one_or_none()
        if capability is None:
            db.add(
                CapabilityRegistry(
                    type=CapabilityType.MODEL,
                    code=MODEL_CODE,
                    name="DeepSeek",
                    description="DeepSeek 官方 API（deepseek-chat）",
                    status="active",
                    config_json=DEEPSEEK_CONFIG,
                )
            )
            print(f"capability created: {MODEL_CODE}")
        else:
            capability.config_json = {**DEEPSEEK_CONFIG, **{
                k: v for k, v in (capability.config_json or {}).items()
                if k not in DEEPSEEK_CONFIG
            }}
            print(f"capability exists: {MODEL_CODE}（配置已刷新）")

        # 2) 语音助手机器人（绑定 DeepSeek）
        bot = (
            await db.scalars(sa.select(Chatbot).where(Chatbot.name == BOT_NAME))
        ).first()
        if bot is None:
            bot = Chatbot(
                name=BOT_NAME,
                description="小智AI语音终端的默认后台机器人（MCP 能力总入口绑定）",
                system_prompt=VOICE_SYSTEM_PROMPT,
                icon="🎙️",
                model_binding=model_binding,
            )
            db.add(bot)
            await db.commit()
            print(f"bot created: {bot.id}")
        else:
            bot.model_binding = model_binding
            await db.commit()
            print(f"bot exists: {bot.id}（模型绑定已指向 {MODEL_CODE}）")


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg 异步驱动不支持 Windows 默认的 ProactorEventLoop
        asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(main())
