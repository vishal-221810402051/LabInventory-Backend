from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class SystemInfoResponse(BaseModel):
    application: Literal["LabInventory"]
    api_version: Literal["v1"]
    protocol_version: Literal[1]
    service_type: Literal["_labinventory._tcp."]
    service_name: Literal["LabInventory Backend"]
    instance_id: UUID
    pairing_required: Literal[True]
    capabilities: list[str]
