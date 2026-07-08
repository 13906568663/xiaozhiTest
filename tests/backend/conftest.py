"""backend 测试共享配置。

必须在任何 ``app.*`` 模块导入之前把 BASE_PATH 置空：``app/main.py`` 在模块
导入期就读取 settings 并把全部路由挂到 ``{BASE_PATH}/api/v1`` 下（默认
``/agent-flow``，服务 B 系统 nginx 反代），而测试统一直接请求 ``/api/v1``。
pytest 保证 conftest 先于测试模块导入，这里强制覆盖即可，不影响生产配置。
"""

from __future__ import annotations

import os

os.environ["BASE_PATH"] = ""
