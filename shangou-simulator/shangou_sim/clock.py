"""可加速的模拟时钟。

演示时真实等 12 分钟出餐不现实,所以全系统统一使用模拟时间:
scale=5 表示现实 1 秒 = 模拟 5 秒;scale=0 表示时间冻结(讲解时用)。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta


class SimClock:
    def __init__(self, scale: float = 5.0) -> None:
        self.scale = scale
        self._base_real = time.time()
        self._base_sim = datetime.now().astimezone()

    def now(self) -> datetime:
        elapsed = time.time() - self._base_real
        return self._base_sim + timedelta(seconds=elapsed * self.scale)

    def set_scale(self, scale: float) -> None:
        # 先把当前模拟时刻固化为新基准,再切倍速,避免时间跳变
        self._base_sim = self.now()
        self._base_real = time.time()
        self.scale = max(0.0, float(scale))

    def minutes_until(self, moment: datetime) -> float:
        """距离某模拟时刻还有几分钟(过期为负数)。"""
        return (moment - self.now()).total_seconds() / 60.0
