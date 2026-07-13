"""内存数据层:店铺/买家/骑手种子数据、订单状态机、事件流、随机与预设订单生成。

设计要点(对应客户场景):
- 订单 = N 个取货任务 + 1 个送达点。跨店单就是 2 个取货任务;
- 每个取货任务有 ready_at(备货就绪时刻)。充电宝柜 prep=0 到店即取,
  餐饮单 prep 8~15 分钟,骑手早到会"干等",等待时长会被记录并计入统计;
- 所有店铺/买家有平面坐标(5km x 5km 虚拟地图),行程时间 = 距离 / 骑行速度,
  供 AI 做路线规划。
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .clock import SimClock

SPEED_M_PER_MIN = 250.0  # 骑行速度:15km/h

# 订单状态
PENDING = "PENDING"        # 待接单
ACCEPTED = "ACCEPTED"      # 已接单(取货中)
DELIVERING = "DELIVERING"  # 全部取齐,配送中
DELIVERED = "DELIVERED"    # 已送达
REJECTED = "REJECTED"      # 已拒单

# 取货任务状态
P_PENDING = "PENDING"      # 未取
P_ARRIVED = "ARRIVED"      # 已到店(可能在等出餐)
P_PICKED = "PICKED"        # 已取货

ORDER_STATUS_LABEL = {
    PENDING: "待接单",
    ACCEPTED: "取货中",
    DELIVERING: "配送中",
    DELIVERED: "已送达",
    REJECTED: "已拒单",
}
PICKUP_STATUS_LABEL = {P_PENDING: "未取", P_ARRIVED: "已到店", P_PICKED: "已取货"}


class OpError(Exception):
    """业务规则不允许的操作(带面向骑手的中文提示)。"""


@dataclass
class Shop:
    id: str
    name: str
    category: str
    x: float
    y: float
    prep_min: int  # 备货时长下限(分钟)
    prep_max: int


@dataclass
class Buyer:
    id: str
    name: str
    address: str
    x: float
    y: float


@dataclass
class Pickup:
    shop_id: str
    items: list[str]
    prep_minutes: float
    ready_at: datetime
    status: str = P_PENDING
    arrived_at: datetime | None = None
    picked_at: datetime | None = None
    wait_minutes: float = 0.0  # 实际干等时长


@dataclass
class Order:
    id: str
    kind: str
    pickups: list[Pickup]
    buyer_id: str
    delivery_fee: float
    created_at: datetime
    deadline: datetime
    status: str = PENDING
    accepted_at: datetime | None = None
    delivered_at: datetime | None = None
    rejected_at: datetime | None = None
    reject_reason: str = ""
    late: bool = False


SHOPS: list[Shop] = [
    Shop("shop_mlt", "蜀香麻辣烫", "餐饮", 1200, 1500, 8, 15),
    Shop("shop_slf", "金牌烧腊饭店", "餐饮", 3800, 1200, 8, 14),
    Shop("shop_fruit", "每日鲜果店", "生鲜", 1800, 3600, 3, 6),
    Shop("shop_cvs", "7号便利店", "便利店", 2400, 3900, 2, 4),
    Shop("shop_pb", "极速充电宝·3号柜", "充电宝", 3200, 2800, 0, 0),
]

BUYERS: list[Buyer] = [
    Buyer("buyer_zhang", "张女士", "阳光花园2栋1单元", 900, 2600),
    Buyer("buyer_li", "李先生", "科技园B座前台", 4300, 3400),
    Buyer("buyer_wang", "王同学", "大学城3号宿舍楼", 3000, 4600),
]

RIDER_HOME = (2500.0, 2500.0)  # 配送站

SHOP_ITEMS: dict[str, list[str]] = {
    "shop_mlt": ["微辣麻辣烫套餐", "全辣麻辣烫大份", "冰豆浆", "卤蛋x2"],
    "shop_slf": ["叉烧双拼饭", "烧鸭例牌", "白切鸡饭", "老火例汤"],
    "shop_fruit": ["果切拼盘", "进口香蕉2斤", "蓝莓1盒", "西瓜半个"],
    "shop_cvs": ["冰镇可乐x2", "抽纸3包", "5号电池1板", "关东煮套餐"],
    "shop_pb": ["共享充电宝x1(柜机自取)"],
}


def _dist_m(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x1 - x2, y1 - y2)


def travel_minutes_between(x1: float, y1: float, x2: float, y2: float) -> float:
    return round(_dist_m(x1, y1, x2, y2) / SPEED_M_PER_MIN, 1)


class Store:
    def __init__(self, clock: SimClock) -> None:
        self.clock = clock
        self.shops: dict[str, Shop] = {s.id: s for s in SHOPS}
        self.buyers: dict[str, Buyer] = {b.id: b for b in BUYERS}
        self.reset()

    # ── 基础 ────────────────────────────────────────────

    def reset(self) -> None:
        self.orders: dict[str, Order] = {}
        self.events: list[dict[str, Any]] = []
        self._seq = 1000
        self.rider = {"id": "rider_1", "name": "小郑", "x": RIDER_HOME[0], "y": RIDER_HOME[1], "location": "配送站"}
        self.autogen_enabled = False
        self.autogen_interval = 40.0  # 现实秒
        self._autogen_last = time.time()
        self.clock.set_scale(self.clock.scale)
        self.log("系统", "数据已重置,骑手小郑在配送站待命")

    def now(self) -> datetime:
        return self.clock.now()

    def log(self, actor: str, text: str) -> None:
        self.events.append({"time": self.now().strftime("%H:%M:%S"), "actor": actor, "text": text})
        if len(self.events) > 200:
            del self.events[: len(self.events) - 200]

    def _order(self, order_id: str) -> Order:
        order = self.orders.get(order_id.strip())
        if order is None:
            raise OpError(f"找不到订单 {order_id},请先查询在途订单列表确认单号")
        return order

    def rider_travel_minutes_to(self, x: float, y: float) -> float:
        return travel_minutes_between(self.rider["x"], self.rider["y"], x, y)

    # ── 订单创建 ────────────────────────────────────────

    def _next_id(self) -> str:
        self._seq += 1
        return f"SG{self._seq}"

    def create_order(
        self,
        pickup_specs: list[tuple[str, list[str], float | None]],
        buyer_id: str,
        deadline_minutes: float,
        actor: str = "系统",
    ) -> Order:
        now = self.now()
        pickups: list[Pickup] = []
        for shop_id, items, prep in pickup_specs:
            shop = self.shops[shop_id]
            prep_minutes = float(prep) if prep is not None else float(random.randint(shop.prep_min, max(shop.prep_min, shop.prep_max)))
            pickups.append(
                Pickup(
                    shop_id=shop_id,
                    items=items,
                    prep_minutes=prep_minutes,
                    ready_at=now + timedelta(minutes=prep_minutes),
                )
            )

        buyer = self.buyers[buyer_id]
        legs_km = self._route_km(pickups, buyer)
        cross = len(pickups) > 1
        fee = round(4 + 1.2 * legs_km + (3 if cross else 0) + random.uniform(0, 1.5), 1)

        order = Order(
            id=self._next_id(),
            kind=self._kind_of(pickups),
            pickups=pickups,
            buyer_id=buyer_id,
            delivery_fee=fee,
            created_at=now,
            deadline=now + timedelta(minutes=deadline_minutes),
        )
        self.orders[order.id] = order
        shop_names = "、".join(self.shops[p.shop_id].name for p in pickups)
        self.log(actor, f"新订单 {order.id}({order.kind}):{shop_names} → {buyer.name},配送费 {fee} 元")
        return order

    def _route_km(self, pickups: list[Pickup], buyer: Buyer) -> float:
        points = [(self.shops[p.shop_id].x, self.shops[p.shop_id].y) for p in pickups] + [(buyer.x, buyer.y)]
        total = _dist_m(self.rider["x"], self.rider["y"], *points[0])
        for a, b in zip(points, points[1:]):
            total += _dist_m(*a, *b)
        return total / 1000.0

    def _kind_of(self, pickups: list[Pickup]) -> str:
        if len(pickups) > 1:
            return "跨店多取"
        category = self.shops[pickups[0].shop_id].category
        if category == "充电宝":
            return "即取(充电宝)"
        if category == "餐饮":
            return "餐饮出餐"
        return category

    def create_random_order(self, actor: str = "系统") -> Order:
        buyer = random.choice(list(self.buyers.values()))
        roll = random.random()
        if roll < 0.2:
            specs = [("shop_pb", SHOP_ITEMS["shop_pb"], 0.0)]
            deadline = 25.0
        elif roll < 0.4:
            pair = random.sample([s.id for s in SHOPS if s.category != "充电宝"], 2)
            specs = [(sid, random.sample(SHOP_ITEMS[sid], k=min(2, len(SHOP_ITEMS[sid]))), None) for sid in pair]
            deadline = 45.0
        else:
            shop = random.choice([s for s in SHOPS if s.category != "充电宝"])
            specs = [(shop.id, random.sample(SHOP_ITEMS[shop.id], k=min(2, len(SHOP_ITEMS[shop.id]))), None)]
            deadline = 35.0
        return self.create_order(specs, buyer.id, deadline, actor=actor)

    def create_preset_scenario(self, actor: str = "管理后台") -> list[Order]:
        """客户电话里的验收场景:同一时刻三张单。

        1. 跨店单:鲜果店 + 便利店 两处取货 → 王同学;
        2. 充电宝单:柜机即取不等待 → 李先生;
        3. 出餐单:麻辣烫 12 分钟出餐(早到要干等) → 张女士。
        """
        self.log(actor, "生成演示场景:跨店单 + 充电宝单 + 出餐等待单,同时派发")
        orders = [
            self.create_order(
                [("shop_fruit", ["果切拼盘", "蓝莓1盒"], 4.0), ("shop_cvs", ["冰镇可乐x2", "抽纸3包"], 2.0)],
                "buyer_wang", 45.0, actor=actor,
            ),
            self.create_order([("shop_pb", SHOP_ITEMS["shop_pb"], 0.0)], "buyer_li", 25.0, actor=actor),
            self.create_order([("shop_mlt", ["微辣麻辣烫套餐", "冰豆浆"], 12.0)], "buyer_zhang", 40.0, actor=actor),
        ]
        return orders

    def autogen_tick(self) -> None:
        if not self.autogen_enabled:
            self._autogen_last = time.time()
            return
        if time.time() - self._autogen_last >= self.autogen_interval:
            self._autogen_last = time.time()
            self.create_random_order(actor="自动派单")

    # ── 骑手动作(MCP 与管理后台共用) ────────────────────

    def accept(self, order_id: str, actor: str) -> str:
        order = self._order(order_id)
        if order.status != PENDING:
            raise OpError(f"订单 {order.id} 当前是「{ORDER_STATUS_LABEL[order.status]}」,不能重复接单")
        order.status = ACCEPTED
        order.accepted_at = self.now()
        self.log(actor, f"接单 {order.id}")
        return f"已接单 {order.id},开始取货。" + self._pickup_brief(order)

    def reject(self, order_id: str, reason: str, actor: str) -> str:
        order = self._order(order_id)
        if order.status != PENDING:
            raise OpError(f"订单 {order.id} 当前是「{ORDER_STATUS_LABEL[order.status]}」,只有待接单状态可以拒单")
        order.status = REJECTED
        order.rejected_at = self.now()
        order.reject_reason = reason or "骑手拒单"
        self.log(actor, f"拒单 {order.id}({order.reject_reason})")
        return f"已拒绝订单 {order.id}"

    def arrive_shop(self, order_id: str, shop_id: str, actor: str) -> str:
        order = self._order(order_id)
        pickup, shop = self._pickup_of(order, shop_id)
        if order.status not in (ACCEPTED, DELIVERING):
            raise OpError(f"订单 {order.id} 是「{ORDER_STATUS_LABEL[order.status]}」,要先接单才能到店")
        if pickup.status == P_PICKED:
            raise OpError(f"{shop.name} 的商品已经取过了")

        travel = self.rider_travel_minutes_to(shop.x, shop.y)
        self._move_rider(shop.x, shop.y, shop.name)
        pickup.status = P_ARRIVED
        pickup.arrived_at = self.now()
        wait = max(0.0, self.clock.minutes_until(pickup.ready_at))
        if wait > 0:
            self.log(actor, f"到店 {shop.name}(订单 {order.id}),商家还需 {wait:.1f} 分钟备货,等待中")
            return f"已到 {shop.name}(路上约 {travel} 分钟)。商家还没备好,还需等待约 {wait:.1f} 分钟才能取货。"
        self.log(actor, f"到店 {shop.name}(订单 {order.id}),商品已备好")
        return f"已到 {shop.name}(路上约 {travel} 分钟),商品已备好,可以直接取货。"

    def pick_up(self, order_id: str, shop_id: str, actor: str) -> str:
        order = self._order(order_id)
        pickup, shop = self._pickup_of(order, shop_id)
        if order.status not in (ACCEPTED, DELIVERING):
            raise OpError(f"订单 {order.id} 是「{ORDER_STATUS_LABEL[order.status]}」,不能取货")
        if pickup.status == P_PICKED:
            raise OpError(f"{shop.name} 的商品已经取过了")
        if pickup.status == P_PENDING:
            # 允许直接说"取到了":隐含先到店
            self._move_rider(shop.x, shop.y, shop.name)
            pickup.status = P_ARRIVED
            pickup.arrived_at = self.now()

        remain = self.clock.minutes_until(pickup.ready_at)
        if remain > 0:
            self.log(actor, f"在 {shop.name} 等待出餐(订单 {order.id}),还需 {remain:.1f} 分钟")
            return f"{shop.name} 的商品还没备好,还需约 {remain:.1f} 分钟,骑手在店内等待。备好后再确认取货。"

        assert pickup.arrived_at is not None
        pickup.wait_minutes = round(max(0.0, (pickup.ready_at - pickup.arrived_at).total_seconds() / 60.0), 1)
        pickup.status = P_PICKED
        pickup.picked_at = self.now()
        wait_note = f"(到店干等了 {pickup.wait_minutes} 分钟)" if pickup.wait_minutes > 0 else ""
        self.log(actor, f"取货完成 {shop.name}(订单 {order.id}){wait_note}")

        if all(p.status == P_PICKED for p in order.pickups):
            order.status = DELIVERING
            buyer = self.buyers[order.buyer_id]
            eta = self.rider_travel_minutes_to(buyer.x, buyer.y)
            deadline_left = self.clock.minutes_until(order.deadline)
            self.log(actor, f"订单 {order.id} 全部取齐,开始配送 → {buyer.name}")
            return (
                f"已取到 {shop.name} 的商品{wait_note}。订单 {order.id} 全部取齐,"
                f"送往 {buyer.name}({buyer.address}),路程约 {eta} 分钟,距送达时限还剩 {deadline_left:.1f} 分钟。"
            )
        remaining = "、".join(self.shops[p.shop_id].name for p in order.pickups if p.status != P_PICKED)
        return f"已取到 {shop.name} 的商品{wait_note}。订单 {order.id} 还差:{remaining}。"

    def deliver(self, order_id: str, actor: str) -> str:
        order = self._order(order_id)
        if order.status == DELIVERED:
            raise OpError(f"订单 {order.id} 已经送达过了")
        if order.status != DELIVERING:
            missing = "、".join(self.shops[p.shop_id].name for p in order.pickups if p.status != P_PICKED)
            raise OpError(f"订单 {order.id} 还没取齐,不能送达。未取:{missing or '未接单'}")
        buyer = self.buyers[order.buyer_id]
        self._move_rider(buyer.x, buyer.y, f"{buyer.name}({buyer.address})")
        order.status = DELIVERED
        order.delivered_at = self.now()
        order.late = order.delivered_at > order.deadline
        if order.late:
            overtime = (order.delivered_at - order.deadline).total_seconds() / 60.0
            self.log(actor, f"订单 {order.id} 送达 {buyer.name},超时 {overtime:.1f} 分钟")
            return f"订单 {order.id} 已送达 {buyer.name},但超时了 {overtime:.1f} 分钟,收入 {order.delivery_fee} 元。"
        self.log(actor, f"订单 {order.id} 准时送达 {buyer.name},收入 {order.delivery_fee} 元")
        return f"订单 {order.id} 已准时送达 {buyer.name},收入 {order.delivery_fee} 元。"

    def _move_rider(self, x: float, y: float, location: str) -> None:
        self.rider["x"], self.rider["y"], self.rider["location"] = x, y, location

    def _pickup_of(self, order: Order, shop_id: str) -> tuple[Pickup, Shop]:
        shop_id = (shop_id or "").strip()
        if not shop_id:
            unpicked = [p for p in order.pickups if p.status != P_PICKED]
            if len(unpicked) == 1:
                pickup = unpicked[0]
                return pickup, self.shops[pickup.shop_id]
            raise OpError(
                f"订单 {order.id} 有多个取货点,请指定 shop_id:"
                + "、".join(f"{self.shops[p.shop_id].name}({p.shop_id})" for p in order.pickups)
            )
        # 支持传店铺 id 或店名
        for p in order.pickups:
            shop = self.shops[p.shop_id]
            if shop_id in (shop.id, shop.name):
                return p, shop
        raise OpError(f"订单 {order.id} 不包含店铺「{shop_id}」的取货任务")

    def _pickup_brief(self, order: Order) -> str:
        parts = []
        for p in order.pickups:
            shop = self.shops[p.shop_id]
            ready_in = self.clock.minutes_until(p.ready_at)
            state = "已备好" if ready_in <= 0 else f"还需 {ready_in:.1f} 分钟备货"
            parts.append(f"{shop.name}:{state},骑过去约 {self.rider_travel_minutes_to(shop.x, shop.y)} 分钟")
        return "取货点:" + ";".join(parts)

    # ── 视图 ────────────────────────────────────────────

    def order_view(self, order: Order) -> dict[str, Any]:
        buyer = self.buyers[order.buyer_id]
        deadline_left = round(self.clock.minutes_until(order.deadline), 1)
        pickups = []
        for p in order.pickups:
            shop = self.shops[p.shop_id]
            ready_in = round(self.clock.minutes_until(p.ready_at), 1)
            pickups.append(
                {
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "category": shop.category,
                    "items": p.items,
                    "status": p.status,
                    "status_label": PICKUP_STATUS_LABEL[p.status],
                    "ready_in_minutes": max(0.0, ready_in) if p.status != P_PICKED else 0.0,
                    "is_ready": ready_in <= 0,
                    "prep_minutes": p.prep_minutes,
                    "wait_minutes": p.wait_minutes,
                    "travel_from_rider_minutes": self.rider_travel_minutes_to(shop.x, shop.y),
                    "x": shop.x,
                    "y": shop.y,
                }
            )
        return {
            "id": order.id,
            "kind": order.kind,
            "status": order.status,
            "status_label": ORDER_STATUS_LABEL[order.status],
            "buyer": {"id": buyer.id, "name": buyer.name, "address": buyer.address, "x": buyer.x, "y": buyer.y},
            "delivery_fee": order.delivery_fee,
            "created_at": order.created_at.strftime("%H:%M:%S"),
            "deadline": order.deadline.strftime("%H:%M:%S"),
            "deadline_left_minutes": deadline_left,
            "overdue": order.status not in (DELIVERED, REJECTED) and deadline_left < 0,
            "late": order.late,
            "travel_to_buyer_from_rider_minutes": self.rider_travel_minutes_to(buyer.x, buyer.y),
            "pickups": pickups,
            "reject_reason": order.reject_reason,
        }

    def active_orders(self) -> list[Order]:
        return [o for o in self.orders.values() if o.status in (PENDING, ACCEPTED, DELIVERING)]

    def stats(self) -> dict[str, Any]:
        delivered = [o for o in self.orders.values() if o.status == DELIVERED]
        waits = [p.wait_minutes for o in self.orders.values() for p in o.pickups]
        return {
            "delivered_count": len(delivered),
            "income": round(sum(o.delivery_fee for o in delivered), 1),
            "late_count": sum(1 for o in delivered if o.late),
            "rejected_count": sum(1 for o in self.orders.values() if o.status == REJECTED),
            "active_count": len(self.active_orders()),
            "pending_count": sum(1 for o in self.orders.values() if o.status == PENDING),
            "total_wait_minutes": round(sum(waits), 1),
        }

    def state(self) -> dict[str, Any]:
        orders = sorted(self.orders.values(), key=lambda o: o.id, reverse=True)
        return {
            "sim_time": self.now().strftime("%H:%M:%S"),
            "time_scale": self.clock.scale,
            "rider": dict(self.rider),
            "shops": [vars(s) for s in self.shops.values()],
            "buyers": [vars(b) for b in self.buyers.values()],
            "orders": [self.order_view(o) for o in orders],
            "events": self.events[::-1][:80],
            "stats": self.stats(),
            "autogen": {"enabled": self.autogen_enabled, "interval_seconds": self.autogen_interval},
        }
