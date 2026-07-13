"""管理后台 REST API(供网页 UI 使用,与 MCP 工具共用同一套 Store 逻辑)。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .store import OpError, Store

ACTOR = "管理后台"


class ActionBody(BaseModel):
    type: str = Field(description="accept / reject / arrive_shop / pick_up / deliver")
    shop_id: str = ""
    reason: str = ""


class AutogenBody(BaseModel):
    enabled: bool
    interval_seconds: float = Field(default=40.0, ge=5, le=600)


class ClockBody(BaseModel):
    scale: float = Field(ge=0, le=60)


def build_router(store: Store) -> APIRouter:
    router = APIRouter()

    @router.get("/state")
    def get_state():
        return store.state()

    @router.post("/orders/preset")
    def create_preset():
        orders = store.create_preset_scenario()
        return {"created": [o.id for o in orders]}

    @router.post("/orders/random")
    def create_random():
        order = store.create_random_order(actor=ACTOR)
        return {"created": order.id}

    @router.post("/orders/{order_id}/action")
    def order_action(order_id: str, body: ActionBody):
        try:
            act = body.type.strip().lower()
            if act == "accept":
                message = store.accept(order_id, actor=ACTOR)
            elif act == "reject":
                message = store.reject(order_id, body.reason, actor=ACTOR)
            elif act == "arrive_shop":
                message = store.arrive_shop(order_id, body.shop_id, actor=ACTOR)
            elif act == "pick_up":
                message = store.pick_up(order_id, body.shop_id, actor=ACTOR)
            elif act == "deliver":
                message = store.deliver(order_id, actor=ACTOR)
            else:
                raise HTTPException(400, f"未知动作:{body.type}")
        except OpError as e:
            raise HTTPException(400, str(e))
        return {"message": message}

    @router.post("/autogen")
    def set_autogen(body: AutogenBody):
        store.autogen_enabled = body.enabled
        store.autogen_interval = body.interval_seconds
        store.log(ACTOR, f"自动派单已{'开启' if body.enabled else '关闭'}(每 {body.interval_seconds:.0f} 秒一单)")
        return {"enabled": store.autogen_enabled, "interval_seconds": store.autogen_interval}

    @router.post("/clock")
    def set_clock(body: ClockBody):
        store.clock.set_scale(body.scale)
        store.log(ACTOR, "时间已冻结(讲解模式)" if body.scale == 0 else f"时间倍速调整为 {body.scale:g}x")
        return {"scale": store.clock.scale}

    @router.post("/reset")
    def reset():
        store.reset()
        return {"ok": True}

    return router
