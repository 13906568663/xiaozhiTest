from __future__ import annotations

import pytest

from app.capabilities.services.capabilities import CapabilityService
from app.domain.enums import CapabilityType
from app.domain.permissions import (
    DEFAULT_PERMISSION_DEFINITIONS,
    DEFAULT_ROLE_PERMISSION_CODES,
    PermissionCode,
    RoleCode,
)


def test_virtual_mcp_config_accepts_mounted_tools_and_headers() -> None:
    config = {
        "mounted_tools": [{"name": "inventory_lookup"}],
        "headers": {"X-Tenant": "demo"},
    }

    normalized = CapabilityService()._normalize_config(
        CapabilityType.VIRTUAL_MCP, config
    )

    assert normalized == config
    assert normalized is not config


@pytest.mark.parametrize(
    "config,error",
    [
        ({"mounted_tools": "inventory_lookup"}, "mounted_tools"),
        ({"headers": ["X-Tenant", "demo"]}, "headers"),
    ],
)
def test_virtual_mcp_config_rejects_invalid_shapes(
    config: dict[str, object], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        CapabilityService()._normalize_config(CapabilityType.VIRTUAL_MCP, config)


def test_toolset_permissions_are_bootstrap_ready_for_default_roles() -> None:
    permission_codes = {
        definition.code for definition in DEFAULT_PERMISSION_DEFINITIONS
    }
    assert PermissionCode.TOOLSETS_READ in permission_codes
    assert PermissionCode.TOOLSETS_WRITE in permission_codes
    assert PermissionCode.TOOLSETS_READ in DEFAULT_ROLE_PERMISSION_CODES[
        RoleCode.PLATFORM_ADMIN
    ]
    assert PermissionCode.TOOLSETS_WRITE in DEFAULT_ROLE_PERMISSION_CODES[
        RoleCode.PLATFORM_ADMIN
    ]
    assert PermissionCode.TOOLSETS_READ in DEFAULT_ROLE_PERMISSION_CODES[
        RoleCode.OPERATOR
    ]
    assert PermissionCode.TOOLSETS_WRITE in DEFAULT_ROLE_PERMISSION_CODES[
        RoleCode.OPERATOR
    ]
    assert PermissionCode.TOOLSETS_READ in DEFAULT_ROLE_PERMISSION_CODES[RoleCode.VIEWER]
    assert PermissionCode.TOOLSETS_WRITE not in DEFAULT_ROLE_PERMISSION_CODES[
        RoleCode.VIEWER
    ]
