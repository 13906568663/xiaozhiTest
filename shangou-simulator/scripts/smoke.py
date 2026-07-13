"""端到端冒烟测试:REST 生成演示场景 → MCP 客户端跑完整个骑手动作流。

用法:先启动服务(uv run python main.py),再执行 uv run python scripts/smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

BASE = os.getenv("SIM_BASE", "http://127.0.0.1:18100")


def check(name: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name} {detail}")
    if not condition:
        sys.exit(1)


async def call(session: ClientSession, tool: str, args: dict) -> str:
    result = await session.call_tool(tool, args)
    text = "".join(c.text for c in result.content if getattr(c, "text", None))
    return text


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE) as http:
        r = await http.post("/api/reset")
        check("REST 重置数据", r.status_code == 200)
        # 时间冻结,让断言稳定(充电宝 ready=0 不受影响,麻辣烫保持"未备好")
        r = await http.post("/api/clock", json={"scale": 0})
        check("REST 冻结时钟", r.status_code == 200)
        r = await http.post("/api/orders/preset")
        created = r.json()["created"]
        check("REST 生成三单演示场景", r.status_code == 200 and len(created) == 3, str(created))
        cross_id, pb_id, meal_id = created

        r = await http.get("/")
        check("管理后台页面可访问", r.status_code == 200 and "外卖派单中心" in r.text)

    async with streamablehttp_client(f"{BASE}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            check("MCP 工具清单", names == sorted([
                "list_orders", "get_order_detail", "get_rider_stats",
                "accept_order", "reject_order", "update_order_status",
            ]), str(names))

            text = await call(session, "list_orders", {})
            data = json.loads(text)
            check("list_orders 返回 3 张在途单", data["order_count"] == 3)
            cross = next(o for o in data["orders"] if o["id"] == cross_id)
            check("跨店单包含 2 个取货点", len(cross["pickups"]) == 2)

            text = await call(session, "get_order_detail", {"order_id": cross_id})
            detail = json.loads(text)
            check("订单详情带两两路程矩阵", len(detail["travel_matrix"]) == 6, f"{len(detail['travel_matrix'])} 条")

            # 充电宝单:接单 → 直接取货(ready=0) → 送达
            text = await call(session, "accept_order", {"order_id": pb_id})
            check("接充电宝单", "已接单" in text, text[:50])
            text = await call(session, "update_order_status", {"order_id": pb_id, "action": "pick_up"})
            check("充电宝即到即取", "全部取齐" in text, text[:80])
            text = await call(session, "update_order_status", {"order_id": pb_id, "action": "deliver"})
            check("充电宝单送达", "已准时送达" in text, text[:60])

            # 出餐单:接单 → 到店(应提示等待) → 取货(应提示未备好)
            await call(session, "accept_order", {"order_id": meal_id})
            text = await call(session, "update_order_status", {"order_id": meal_id, "action": "arrive_shop"})
            check("麻辣烫早到提示等待", "等待" in text and "分钟" in text, text[:80])
            text = await call(session, "update_order_status", {"order_id": meal_id, "action": "pick_up"})
            check("未备好时取货被拦截", "还没备好" in text, text[:80])

            # 跨店单:不带 shop_id 应要求指定;逐店取齐后送达
            await call(session, "accept_order", {"order_id": cross_id})
            text = await call(session, "update_order_status", {"order_id": cross_id, "action": "pick_up"})
            check("跨店单要求指定店铺", "请指定" in text, text[:80])
            text = await call(session, "update_order_status", {"order_id": cross_id, "action": "pick_up", "shop_id": "每日鲜果店"})
            check("鲜果店未备好被拦截(时间冻结中)", "还没备好" in text, text[:80])

            # 恢复时间流动,让备货完成后取齐
            async with httpx.AsyncClient(base_url=BASE) as http:
                await http.post("/api/clock", json={"scale": 60})
            await asyncio.sleep(5)  # 60x:现实 5 秒 = 模拟 5 分钟,鲜果(4分)/便利店(2分)均已备好
            async with httpx.AsyncClient(base_url=BASE) as http:
                await http.post("/api/clock", json={"scale": 1})

            text = await call(session, "update_order_status", {"order_id": cross_id, "action": "pick_up", "shop_id": "每日鲜果店"})
            check("鲜果店取货", "已取到" in text, text[:80])
            text = await call(session, "update_order_status", {"order_id": cross_id, "action": "pick_up", "shop_id": "7号便利店"})
            check("便利店取货后全部取齐", "全部取齐" in text, text[:100])
            text = await call(session, "update_order_status", {"order_id": cross_id, "action": "deliver"})
            check("跨店单送达", "送达" in text, text[:60])

            text = await call(session, "get_rider_stats", {})
            stats = json.loads(text)
            check("统计:已送达 2 单", stats["delivered_count"] == 2, text)

    print("\nSMOKE OK - 全部通过")


if __name__ == "__main__":
    asyncio.run(main())
