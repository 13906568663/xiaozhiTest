"""MCP 工具层:把派单系统的骑手动作暴露给 AI 助手(streamable-http)。

所有工具返回 ensure_ascii=False 的 JSON 文本或中文说明,方便大模型直接口播。
"""

from __future__ import annotations

import json
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .store import OpError, Store

ACTOR = "AI骑手助手"

INSTRUCTIONS = (
    "闪购外卖派单系统(骑手端)。当前只有一名骑手。"
    "订单可能包含多个取货点(跨店单),每个取货点有备货就绪倒计时 ready_in_minutes:"
    "0 表示已备好(如充电宝柜机即到即取),大于 0 表示商家还在备货、骑手早到会干等。"
    "所有 travel_*_minutes 字段是骑行时间(分钟)。"
    "规划路线时应结合:各取货点的备货倒计时、点位之间的骑行时间、各订单的送达时限,"
    "尽量避免到店干等,并保证不超时。"
)


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


def build_mcp(store: Store) -> FastMCP:
    mcp = FastMCP(
        name="shangou-dispatch-sim",
        instructions=INSTRUCTIONS,
        stateless_http=True,
    )

    # ── 查询类 ──────────────────────────────────────────

    @mcp.tool(
        name="list_orders",
        description=(
            "查询骑手当前的订单列表(默认只看在途单:待接单/取货中/配送中)。"
            "返回每个订单的类型、买家、配送费、送达时限剩余分钟数,以及每个取货点的"
            "备货倒计时和从骑手当前位置骑过去的分钟数。骑手问“有没有新单/手上有几单”用这个。"
        ),
    )
    def list_orders(
        include_finished: Annotated[bool, Field(description="是否连已送达/已拒单的历史单一起返回,默认否")] = False,
    ) -> str:
        orders = list(store.orders.values()) if include_finished else store.active_orders()
        views = [store.order_view(o) for o in sorted(orders, key=lambda o: o.id)]
        return _json(
            {
                "sim_time": store.now().strftime("%H:%M:%S"),
                "rider_location": store.rider["location"],
                "order_count": len(views),
                "orders": views,
                "hint": "ready_in_minutes=0 表示商品已备好可直接取;早到未备好会干等。",
            }
        )

    @mcp.tool(
        name="get_order_detail",
        description=(
            "查看单个订单的完整信息,包含各取货点之间、取货点到买家之间的两两骑行时间矩阵,"
            "用于规划先取哪家、后取哪家的路线顺序。"
        ),
    )
    def get_order_detail(
        order_id: Annotated[str, Field(description="订单号,如 SG1001")],
    ) -> str:
        try:
            order = store._order(order_id)
        except OpError as e:
            return f"操作失败:{e}"
        view = store.order_view(order)
        points = [("骑手当前位置", store.rider["x"], store.rider["y"])]
        points += [(p["shop_name"], p["x"], p["y"]) for p in view["pickups"]]
        points.append((f"买家:{view['buyer']['name']}", view["buyer"]["x"], view["buyer"]["y"]))
        matrix = []
        for i, (name_a, xa, ya) in enumerate(points):
            for name_b, xb, yb in points[i + 1 :]:
                from .store import travel_minutes_between

                matrix.append({"from": name_a, "to": name_b, "travel_minutes": travel_minutes_between(xa, ya, xb, yb)})
        view["travel_matrix"] = matrix
        return _json(view)

    @mcp.tool(
        name="get_rider_stats",
        description="查询骑手今日跑单统计:已送达单量、收入、超时单数、累计干等分钟数、在途单数。骑手问“今天跑了多少/赚了多少”用这个。",
    )
    def get_rider_stats() -> str:
        stats = store.stats()
        stats["rider_name"] = store.rider["name"]
        stats["rider_location"] = store.rider["location"]
        stats["sim_time"] = store.now().strftime("%H:%M:%S")
        return _json(stats)

    # ── 动作类 ──────────────────────────────────────────

    @mcp.tool(
        name="accept_order",
        description="接下一张待接单的订单。接单后返回各取货点的备货情况和骑行时间,便于立刻规划路线。",
    )
    def accept_order(
        order_id: Annotated[str, Field(description="订单号,如 SG1001")],
    ) -> str:
        try:
            return store.accept(order_id, actor=ACTOR)
        except OpError as e:
            return f"操作失败:{e}"

    @mcp.tool(
        name="reject_order",
        description="拒绝一张待接单的订单(骑手明确说不接的时候才用)。",
    )
    def reject_order(
        order_id: Annotated[str, Field(description="订单号,如 SG1001")],
        reason: Annotated[str, Field(description="拒单原因,口语原话即可,可为空")] = "",
    ) -> str:
        try:
            return store.reject(order_id, reason, actor=ACTOR)
        except OpError as e:
            return f"操作失败:{e}"

    @mcp.tool(
        name="update_order_status",
        description=(
            "上报骑手动作,推进订单状态。action 取值:"
            "arrive_shop=到店(早到会提示还要等几分钟);"
            "pick_up=取货(商家没备好时不会取成功,会返回还需等待的分钟数);"
            "deliver=送达买家(必须所有取货点都取完)。"
            "跨店单做 arrive_shop/pick_up 时必须带 shop_id(店铺 id 或店名)。"
        ),
    )
    def update_order_status(
        order_id: Annotated[str, Field(description="订单号,如 SG1001")],
        action: Annotated[str, Field(description="动作:arrive_shop / pick_up / deliver")],
        shop_id: Annotated[str, Field(description="取货店铺的 id 或店名;订单只剩一个未取点时可省略")] = "",
    ) -> str:
        try:
            act = action.strip().lower()
            if act == "arrive_shop":
                return store.arrive_shop(order_id, shop_id, actor=ACTOR)
            if act == "pick_up":
                return store.pick_up(order_id, shop_id, actor=ACTOR)
            if act == "deliver":
                return store.deliver(order_id, actor=ACTOR)
            return f"操作失败:未知动作「{action}」,只支持 arrive_shop / pick_up / deliver"
        except OpError as e:
            return f"操作失败:{e}"

    return mcp
