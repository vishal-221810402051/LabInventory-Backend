from __future__ import annotations

import pytest

from app.discovery.config import TXT_RECORDS, MdnsConfig
from app.discovery.interface_selector import validate_advertise_ip


def test_mdns_txt_records_are_correct() -> None:
    assert TXT_RECORDS == {"api": "v1", "protocol": "1", "pairing": "required"}


def test_zeroconf_service_type_and_instance_name_are_correct() -> None:
    config = MdnsConfig(
        service_name="LabInventory Backend",
        service_type="_labinventory._tcp.",
        port=8000,
    )

    assert config.zeroconf_service_type == "_labinventory._tcp.local."
    assert config.service_instance_name == "LabInventory Backend._labinventory._tcp.local."
    assert config.txt_records == {"api": "v1", "protocol": "1", "pairing": "required"}


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "0.0.0.0", "169.254.1.10", "224.0.0.1", "8.8.8.8", "::1"],
)
def test_invalid_advertise_addresses_are_rejected(address: str) -> None:
    with pytest.raises(ValueError):
        validate_advertise_ip(address)


def test_private_lan_advertise_address_is_accepted() -> None:
    assert validate_advertise_ip("192.168.1.20") == "192.168.1.20"
