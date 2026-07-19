"""MCP 工具层:把派单系统的骑手动作暴露给 AI 助手(streamable-http)。

所有工具返回 ensure_ascii=False 的 JSON 文本或中文说明,方便大模型直接口播。
"""

from __future__ import annotations

import json
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from .store import OpError, Store

ACTOR = "AI骑手助手"

INSTRUCTIONS = (
    "闪购外卖派单系统(骑手端)。当前只有一名骑手:所有订单都是这名骑手的,"
    "用户提到的任何称呼或人名(我/骑手/Jack/小郑等)都指他,查询订单一律直接查,"
    "不需要也无法按人名筛选,严禁反问'谁的订单'。"
    "订单可能包含多个取货点(跨店单),每个取货点有备货就绪倒计时 ready_in_minutes:"
    "0 表示商户已出货、到店即取,大于 0 表示商家还在备货、骑手早到会干等。"
    "订单带平台标签(platform,如'淘宝闪购1')、收货人(receiver,含电话尾号)和"
    "顾客备注(note,如'放D305门口'),用户问收货人/备注/商家出货情况都能答。"
    "店铺和顾客都是杭州余杭仓前(梦想小镇/杭师大一带)的真实地点(订单里带真实地址);"
    "演示订单生成时即为已接单(取货中)状态,直接引导取货送达即可。"
    "本平台的核心价值是'最后100米':汇聚骑手社交网络的实时尾程情报"
    "(哪个电梯快、走哪个门、商家出货快慢)。骑手问取餐/送餐的落地细节"
    "(怎么进楼/哪个门/电梯/到店要不要等)时,必须调 get_last_mile_intel 查骑手圈情报;"
    "问'怎么走/路线'时不给转弯级导航(平台地图已自动规划),直接说按平台规划路线走,"
    "再主动补上目的地的尾程情报。"
)


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


def build_mcp(store: Store) -> FastMCP:
    mcp = FastMCP(
        name="shangou-dispatch-sim",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        # 内网演示服务,允许通过容器名/内网 IP 访问(否则非 localhost 的 Host 会被 421 拒绝)
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
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
                "hint": "ready_in_minutes=0 表示商品已备好可直接取;早到未备好会干等。待接单订单的倒计时从接单时刻才开始算,不会超时。",
            }
        )

    @mcp.tool(
        name="get_order_detail",
        description=(
            "查看单个订单的完整信息:取货点备货状态、收货人/备注、送达时限等。"
            "道路怎么走不用管(平台地图已规划);落地细节(电梯/门禁/出货快慢)请另调 get_last_mile_intel。"
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

    # ── 最后100米:骑手社交平台众包尾程情报(演示写死) ──

    _LAST_MILE_INTEL: list[tuple[tuple[str, ...], str]] = [
        (
            ("正元", "智慧", "A栋", "A幢", "邵"),
            "骑手圈最新反馈:正元智慧A栋这个时间段主电梯会等比较久喔,"
            "可以绕到大门左边的货梯上去,可能会更快一点喔。",
        ),
        (
            ("科技园", "杭师大", "D幢", "D栋", "D305", "张"),
            "骑手圈最新反馈:杭师大科技园东门是员工通道,电动车不让进;"
            "北门是货运入口,你可以从那边进来。",
        ),
        (
            ("敕勒川", "砂锅", "牛腩", "牛杂"),
            "骑手圈最新反馈:敕勒川这家店今天订单好像很多,"
            "有骑手反馈半个小时都还没取到货。",
        ),
    ]

    @mcp.tool(
        name="get_last_mile_intel",
        description=(
            "查询取餐点/送餐点的'最后100米'尾程情报——来自骑手社交平台的实时众包信息:"
            "进哪个门、坐哪部电梯、门禁限制、商家出货快慢、到店要不要等。"
            "骑手问'到了怎么上楼/从哪个门进/电梯好不好等/这家店取餐快吗/要等多久'"
            "这类落地细节时必须用这个;去取餐或送餐前也应主动查一次给骑手提个醒。"
            "place 填店名、楼宇名或收货地址关键词。"
        ),
    )
    def get_last_mile_intel(
        place: Annotated[str, Field(description="地点关键词,如 正元智慧A栋、科技园D幢、敕勒川")],
    ) -> str:
        place = (place or "").strip()
        if not place:
            return "请告诉我要查哪个取餐点或送餐点。"
        for keys, text in _LAST_MILE_INTEL:
            if any(k in place for k in keys):
                return text
        return f"骑手圈暂时没有关于「{place}」的最新尾程反馈,按现场实际情况处理即可。"

    # ── 动作类 ──────────────────────────────────────────

    @mcp.tool(
        name="accept_order",
        description="接下一张待接单的订单。接单后返回各取货点的备货情况;落地细节请再调 get_last_mile_intel。",
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
