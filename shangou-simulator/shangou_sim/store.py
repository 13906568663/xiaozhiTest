"""内存数据层:店铺/买家/骑手种子数据、订单状态机、事件流、随机与预设订单生成。

设计要点(对应客户场景):
- 订单 = N 个取货任务 + 1 个送达点。跨店单就是 2 个取货任务;
- 每个取货任务有 ready_at(备货就绪时刻)。prep=0 表示商户已出货、到店即取,
  prep>0 表示商家还在备货,骑手早到会"干等",等待时长会被记录并计入统计;
- 店铺/买家均为杭州余杭仓前·梦想小镇一带的真实地点(百度 BD09 经纬度),
  内部平面坐标由经纬度局部投影得到(米),行程时间 = 距离 / 骑行速度;
  道路怎么走交给平台地图规划,本系统只负责"最后100米"尾程决策。
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
    address: str = ""
    lng: float = 0.0  # 百度 BD09
    lat: float = 0.0


@dataclass
class Buyer:
    id: str
    name: str
    address: str
    x: float
    y: float
    lng: float = 0.0  # 百度 BD09
    lat: float = 0.0
    phone_tail: str = ""  # 收货人电话尾号(脱敏展示)


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
    window_minutes: float = 30.0  # 送达时限总长;待接单时不走表,接单后才开始倒计时
    status: str = PENDING
    accepted_at: datetime | None = None
    delivered_at: datetime | None = None
    rejected_at: datetime | None = None
    reject_reason: str = ""
    late: bool = False
    platform: str = ""  # 平台单号标签,如 "淘宝闪购1"
    note: str = ""      # 顾客备注,如 "放D305门口 / 依据餐量提供餐具"
    demo_loop: bool = False  # 演示循环单:时限快耗尽时自动回满,永不超时


# 局部平面投影原点(区域西南角,BD09):所有真实点位投影到 0~5000m 平面,
# 前端画布与距离计算沿用米制坐标,无需感知经纬度。
_ORIGIN_LNG, _ORIGIN_LAT = 119.9900, 30.2760


def _bd09_to_xy(lng: float, lat: float) -> tuple[float, float]:
    x = (lng - _ORIGIN_LNG) * 111320.0 * math.cos(math.radians(lat))
    y = (lat - _ORIGIN_LAT) * 110540.0
    return round(x, 1), round(y, 1)


def _mk_shop(id_: str, name: str, category: str, lng: float, lat: float,
             address: str, prep_min: int, prep_max: int) -> Shop:
    x, y = _bd09_to_xy(lng, lat)
    return Shop(id_, name, category, x, y, prep_min, prep_max,
                address=address, lng=lng, lat=lat)


def _mk_buyer(id_: str, name: str, address: str, lng: float, lat: float,
              phone_tail: str = "") -> Buyer:
    x, y = _bd09_to_xy(lng, lat)
    return Buyer(id_, name, address, x, y, lng=lng, lat=lat, phone_tail=phone_tail)


# 真实店铺(杭州余杭仓前·梦想小镇一带,照淘宝闪购真实订单还原,
# 坐标来自百度地点检索)
SHOPS: list[Shop] = [
    _mk_shop("shop_clc", "敕勒川·砂锅牛腩牛杂煲(梦想小镇店)", "餐饮",
             120.011687, 30.297968, "仓前街道良睦路1399号梦想小镇互联网村1号楼1楼", 0, 8),
    _mk_shop("shop_jgb", "重庆鸡公煲(杭师大店)", "餐饮",
             120.006234, 30.290800, "仓前街道时尚万通城1幢1-2室", 0, 10),
    _mk_shop("shop_mx", "蜜雪冰城(仓兴店)", "餐饮",
             120.007022, 30.296827, "仓前街道仓兴街101号", 10, 15),
]

# 真实楼宇的固定顾客(照真实订单脱敏信息)
BUYERS: list[Buyer] = [
    _mk_buyer("buyer_shao", "邵*(先生)", "正元智慧A栋(A幢13层)", 120.000244, 30.283826, phone_tail="6147"),
    _mk_buyer("buyer_zhang", "张*丽", "杭州师范大学科技园D幢(D-305)", 119.994381, 30.281774, phone_tail="9985"),
    _mk_buyer("buyer_wang", "王*(女士)", "梦想小镇天使村10栋(前台代收)", 120.009744, 30.296685, phone_tail="3302"),
]

# 配送站:梦想小镇互联网村门口(对应真实订单里"离敕勒川 28 米")
RIDER_HOME = _bd09_to_xy(120.0115, 30.2978)

SHOP_ITEMS: dict[str, list[str]] = {
    "shop_clc": ["砂锅牛腩煲", "砂锅牛杂煲", "秘制小菜", "米饭x2"],
    "shop_jgb": ["重庆鸡公煲(中份)", "干锅花菜", "米饭x2", "王老吉"],
    "shop_mx": ["冰鲜柠檬水", "珍珠奶茶", "摩天脆脆冰淇淋"],
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
        # 骑手名保持中性:上游语音端对骑手的称呼不固定(我/Jack/任意人名),
        # 显示名不绑定具体人名,由 AI 跟随用户的称呼
        self.rider = {"id": "rider_1", "name": "骑手", "x": RIDER_HOME[0], "y": RIDER_HOME[1], "location": "配送站"}
        self.autogen_enabled = False
        self.autogen_interval = 40.0  # 现实秒
        self._autogen_last = time.time()
        self.clock.set_scale(self.clock.scale)
        self.log("系统", "数据已重置,骑手在配送站待命")

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
        self._demo_refresh(order)
        return order

    def _demo_refresh(self, order: Order) -> None:
        """演示循环单:剩余时限低于窗口 30% 时自动回满,倒计时循环、永不超时。

        只作用于 demo_loop 标记的在途单;倒计时仍真实下走,观众能看到
        "剩 25 分 → 剩 24 分…",烧到低位悄悄续满,演示中不会出现超时单。
        """
        if not order.demo_loop or order.status not in (PENDING, ACCEPTED, DELIVERING):
            return
        left = self.clock.minutes_until(order.deadline)
        if left < order.window_minutes * 0.3:
            order.deadline = self.now() + timedelta(minutes=order.window_minutes)
        # 未出餐取货点(如蜜雪冰城):骑手到店前备货倒计时烧到低位也自动回满,
        # 稳定保持"商家备货中"的演示状态;到店(ARRIVED)后正常走完,等一等能取到。
        for p in order.pickups:
            if p.status == P_PENDING and p.prep_minutes > 0:
                ready_left = self.clock.minutes_until(p.ready_at)
                if ready_left < p.prep_minutes * 0.25:
                    p.ready_at = self.now() + timedelta(minutes=p.prep_minutes)

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
        platform: str = "",
        note: str = "",
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
            window_minutes=float(deadline_minutes),
            platform=platform,
            note=note,
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
        shop = random.choice(list(self.shops.values()))
        specs = [(shop.id, random.sample(SHOP_ITEMS[shop.id], k=min(2, len(SHOP_ITEMS[shop.id]))), None)]
        return self.create_order(specs, buyer.id, 35.0, actor=actor)

    def create_preset_scenario(self, actor: str = "管理后台") -> list[Order]:
        """演示场景:照淘宝闪购真实订单还原的三张单,生成后立即置为已接单。

        1. 淘宝闪购1:敕勒川砂锅(商户已出货) → 邵先生@正元智慧A栋,26 分钟时限;
        2. 淘宝闪购7:重庆鸡公煲(商户已出货) → 张*丽@杭师大科技园D幢,37 分钟时限;
        3. 淘宝闪购3:蜜雪冰城·仓兴店(商家备货中,未出餐) → 王女士@天使村10栋,32 分钟时限。
        prep=0 即"商户已出货",到店即取;蜜雪冰城 prep=12 且骑手未到店时倒计时
        循环回满,稳定演示"店里单多、还没出餐"的取餐场景。
        """
        self.log(actor, "生成演示场景:三张淘宝闪购订单(蜜雪冰城未出餐),自动接单")
        orders = [
            self.create_order(
                [("shop_clc", ["砂锅牛腩煲", "米饭x2"], 0.0)],
                "buyer_shao", 26.0, actor=actor,
                platform="淘宝闪购1", note="依据餐量提供餐具",
            ),
            self.create_order(
                [("shop_jgb", ["重庆鸡公煲(中份)", "米饭x2"], 0.0)],
                "buyer_zhang", 37.0, actor=actor,
                platform="淘宝闪购7", note="放D305门口 / 依据餐量提供餐具",
            ),
            self.create_order(
                [("shop_mx", ["冰鲜柠檬水", "珍珠奶茶"], 12.0)],
                "buyer_wang", 32.0, actor=actor,
                platform="淘宝闪购3", note="少冰 / 放前台代收",
            ),
        ]
        for o in orders:
            o.demo_loop = True  # 演示单永不超时:时限烧到低位自动回满循环
            self.accept(o.id, actor="系统(演示预接单)")
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
        now = self.now()
        order.accepted_at = now
        # 时限从接单时刻起算:待接单期间订单不会变旧,接单后重置备货与送达倒计时
        order.created_at = now
        order.deadline = now + timedelta(minutes=order.window_minutes)
        for pickup in order.pickups:
            pickup.ready_at = now + timedelta(minutes=pickup.prep_minutes)
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
        # 支持传店铺 id 或店名(精确优先)
        for p in order.pickups:
            shop = self.shops[p.shop_id]
            if shop_id in (shop.id, shop.name):
                return p, shop
        # 模糊兜底:大模型转述店名常有错字/丢括号(如"畔山"写成"畈山"),
        # 按去括号前缀 + 首段包含匹配,唯一命中才接受
        def _core(name: str) -> str:
            return name.split("(")[0].split("(")[0].strip()

        want = _core(shop_id)
        hits = [
            (p, self.shops[p.shop_id])
            for p in order.pickups
            if want and (want in _core(self.shops[p.shop_id].name) or _core(self.shops[p.shop_id].name) in want)
        ]
        if len(hits) == 1:
            return hits[0]
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
        self._demo_refresh(order)
        buyer = self.buyers[order.buyer_id]
        pending = order.status == PENDING
        # 待接单的订单永远保持"刚派单"状态:倒计时不走表,接单后才开始计时
        deadline_left = round(order.window_minutes if pending else self.clock.minutes_until(order.deadline), 1)
        pickups = []
        for p in order.pickups:
            shop = self.shops[p.shop_id]
            ready_in = p.prep_minutes if pending else round(self.clock.minutes_until(p.ready_at), 1)
            pickups.append(
                {
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "category": shop.category,
                    "address": shop.address,
                    "items": p.items,
                    "status": p.status,
                    "status_label": PICKUP_STATUS_LABEL[p.status],
                    "ready_in_minutes": max(0.0, ready_in) if p.status != P_PICKED else 0.0,
                    "is_ready": ready_in <= 0,
                    "merchant_status": "商户已出货" if ready_in <= 0 else f"商家备货中(还需{max(0.0, ready_in):.0f}分钟)",
                    "prep_minutes": p.prep_minutes,
                    "wait_minutes": p.wait_minutes,
                    "travel_from_rider_minutes": self.rider_travel_minutes_to(shop.x, shop.y),
                    "x": shop.x,
                    "y": shop.y,
                }
            )
        receiver = buyer.name + (f" 尾号{buyer.phone_tail}" if buyer.phone_tail else "")
        return {
            "id": order.id,
            "kind": order.kind,
            "platform": order.platform,
            "status": order.status,
            "status_label": ORDER_STATUS_LABEL[order.status],
            "buyer": {"id": buyer.id, "name": buyer.name, "address": buyer.address,
                      "phone_tail": buyer.phone_tail, "x": buyer.x, "y": buyer.y},
            "receiver": receiver,
            "buyer_hint": f"送达:{receiver},{buyer.address}",
            "note": order.note,
            "delivery_fee": order.delivery_fee,
            "created_at": order.created_at.strftime("%H:%M:%S"),
            "deadline": "接单后计时" if pending else order.deadline.strftime("%H:%M:%S"),
            "deadline_left_minutes": deadline_left,
            "overdue": order.status in (ACCEPTED, DELIVERING) and deadline_left < 0,
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
