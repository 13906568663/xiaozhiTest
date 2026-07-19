"""MCP 工具层:把派单系统的订单信息与尾程情报暴露给 AI 助手(streamable-http)。

只读服务:接单/到店/取货/送达等操作在骑手 App 上完成,不经语音助手。
所有工具返回 ensure_ascii=False 的 JSON 文本或中文说明,方便大模型直接口播。
"""

from __future__ import annotations

import json
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from .store import OpError, Store

INSTRUCTIONS = (
    "闪购外卖派单系统(骑手端,只读)。当前只有一名骑手:所有订单都是这名骑手的,"
    "用户提到的任何称呼或人名(我/骑手/Jack/小郑等)都指他,查询订单一律直接查,"
    "不需要也无法按人名筛选,严禁反问'谁的订单'。"
    "订单可能包含多个取货点(跨店单),每个取货点有备货就绪倒计时 ready_in_minutes:"
    "0 表示商户已出货、到店即取,大于 0 表示商家还在备货、骑手早到会干等。"
    "订单带平台标签(platform,如'淘宝闪购1')、收货人(receiver,含电话尾号)和"
    "顾客备注(note,如'放D305门口'),用户问收货人/备注/商家出货情况都能答。"
    "店铺和顾客都是杭州余杭仓前(梦想小镇/杭师大一带)的真实地点(订单里带真实地址)。"
    "本服务不提供接单/拒单/状态上报操作:那些在骑手 App 上完成,"
    "用户说'帮我接单/我取到了'时,告知在配送 App 上操作即可,不要试图代办。"
    "本平台的核心价值是'最后100米':汇聚骑手社交网络的实时尾程情报"
    "(哪个电梯快、走哪个门、商家出货快慢)。订单数据里已自动附带"
    " rider_circle_intel 字段(该取餐点/送餐点的骑手圈情报),"
    "报订单状态时必须把这个字段的内容顺口播报给骑手,严禁漏掉;"
    "订单数据没覆盖的地点,骑手问落地细节(怎么进楼/哪个门/电梯/要不要等)时"
    "再调 get_last_mile_intel 查。"
    "助手不做任何规划:路线怎么走、先送哪单,都由平台规划好了。"
    "严禁主动提出'帮你规划/怎么跑最顺';即使骑手明确要求帮忙规划,"
    "也绝不给'先去A再去B最后C'式的顺序,只回答'平台已经规划好了,按平台的路线和顺序走',"
    "再补上相关取送点的尾程情报。"
)


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


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
        ("蜜雪", "冰城", "仓兴", "柠檬水", "奶茶"),
        "骑手圈最新反馈:蜜雪冰城这家店今天订单好像很多,"
        "有骑手反馈半个小时都还没取到货。",
    ),
]


def _match_intel(*texts: str) -> str | None:
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    for keys, text in _LAST_MILE_INTEL:
        if any(k in blob for k in keys):
            return text
    return None


def _attach_intel(view: dict) -> dict:
    """给订单视图挂骑手圈尾程情报:取货点按店名/地址匹配,送达点按收货人/地址匹配。

    情报直接随订单数据返回,模型一次调用就能拿到,不依赖它记得再调
    get_last_mile_intel;没有情报的点位不加字段(避免模型念'暂无反馈')。
    """
    for p in view.get("pickups", []):
        tip = _match_intel(p.get("shop_name", ""), p.get("address", ""))
        if tip:
            p["rider_circle_intel"] = tip
    buyer = view.get("buyer") or {}
    tip = _match_intel(buyer.get("name", ""), buyer.get("address", ""))
    if tip:
        view["rider_circle_intel"] = tip + "(送达点情报)"
    return view


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
        views = [_attach_intel(store.order_view(o)) for o in sorted(orders, key=lambda o: o.id)]
        return _json(
            {
                "sim_time": store.now().strftime("%H:%M:%S"),
                "rider_location": store.rider["location"],
                "order_count": len(views),
                "orders": views,
                "hint": (
                    "ready_in_minutes=0 表示商品已备好可直接取;早到未备好会干等。"
                    "rider_circle_intel 是骑手社交平台的众包尾程情报,回答时必须顺口播报给骑手,不要漏。"
                ),
            }
        )

    @mcp.tool(
        name="get_order_detail",
        description=(
            "查看单个订单的完整信息:取货点备货状态、收货人/备注、送达时限,"
            "并自动附带取送点的骑手圈尾程情报(rider_circle_intel,必须播报)。"
            "道路怎么走不用管(平台地图已规划)。"
        ),
    )
    def get_order_detail(
        order_id: Annotated[str, Field(description="订单号,如 SG1001")],
    ) -> str:
        try:
            order = store._order(order_id)
        except OpError as e:
            return f"操作失败:{e}"
        view = _attach_intel(store.order_view(order))
        view["hint"] = "rider_circle_intel 是骑手圈众包尾程情报,回答时必须顺口播报给骑手。"
        # 不附带点位间骑行时间矩阵:跑单顺序与路线由平台规划,不诱导模型自行规划
        return _json(view)

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

    # 订单操作(接单/到店/取货/送达)不暴露给语音助手:骑手在配送 App 上
    # 自行操作,导演可用 18100 管理台推进状态;语音侧只读 + 尾程情报。

    return mcp
