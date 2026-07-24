from __future__ import annotations

from dataclasses import dataclass

TXT_RECORDS = {"api": "v1", "protocol": "1", "pairing": "required"}


@dataclass(frozen=True)
class MdnsConfig:
    service_name: str
    service_type: str
    port: int
    advertise_ip: str | None = None

    @property
    def zeroconf_service_type(self) -> str:
        return zeroconf_service_type(self.service_type)

    @property
    def service_instance_name(self) -> str:
        return f"{self.service_name}.{self.zeroconf_service_type}"

    @property
    def txt_records(self) -> dict[str, str]:
        return dict(TXT_RECORDS)


def zeroconf_service_type(service_type: str) -> str:
    base = service_type.strip()
    if base.endswith(".local."):
        return base
    if not base.endswith("."):
        base = f"{base}."
    return f"{base}local."
