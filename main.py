import asyncio
import sys
from binascii import hexlify
from dataclasses import asdict, dataclass, field
from datetime import datetime
from json import dumps
from time import sleep, time_ns
from typing import Optional

from bleak import BleakScanner

# Configure update duration (update after n seconds)
UPDATE_DURATION = 1
MIN_RSSI = -60
AIRPODS_MANUFACTURER = 76
AIRPODS_DATA_LENGTH = 54
RECENT_BEACONS_MAX_T_NS = 10000000000  # 10 Seconds
AIRPODS_MODEL_MAP = {
    "e": "AirPodsPro",
    "3": "AirPods3",
    "f": "AirPods2",
    "2": "AirPods1",
    "a": "AirPodsMax",
}


@dataclass
class AirPodsData:
    date: str
    status: int = 0
    charge: dict[str, int] = field(
        default_factory=lambda: {"left": -1, "right": -1, "case": -1}
    )
    charging_left: bool = False
    charging_right: bool = False
    charging_case: bool = False
    model: str = "AirPods not found"
    raw: Optional[str] = None


recent_beacons = []


def get_best_result(device):
    now = time_ns()

    recent_beacons.append({"time": now, "device": device})

    filtered = []
    strongest_beacon = None

    for beacon in recent_beacons:
        if now - beacon["time"] > RECENT_BEACONS_MAX_T_NS:
            continue

        filtered.append(beacon)

        current_device = beacon["device"]
        if strongest_beacon is None or strongest_beacon.rssi < current_device.rssi:
            strongest_beacon = current_device

    recent_beacons[:] = filtered

    if strongest_beacon is not None and strongest_beacon.address == device.address:
        strongest_beacon = device

    return strongest_beacon


# Getting data with hex format
async def get_device():
    # Scanning for devices
    devices = await BleakScanner.discover()
    for d in devices:
        # Checking for AirPods
        d = get_best_result(d)
        if (
            d.rssi >= MIN_RSSI
            and AIRPODS_MANUFACTURER in d.metadata["manufacturer_data"]
        ):
            data_hex = hexlify(
                bytearray(d.metadata["manufacturer_data"][AIRPODS_MANUFACTURER])
            )
            if len(data_hex) == AIRPODS_DATA_LENGTH:
                return data_hex
    return False


# Same as get_device() but it's standalone method instead of async
def get_data_hex():
    a = asyncio.run(get_device())
    return a


# Getting data from hex string and converting it to dict(json)
def get_data():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result_data = AirPodsData(date=timestamp)

    raw = get_data_hex()

    # Return blank data if airpods not found
    if not raw:
        return result_data

    result_data.status = 1  # Found AirPods

    # Decoding raw data to prevent JSON sterilization issues
    result_data.raw = raw.decode()

    flip: bool = is_flipped(raw)

    # On 7th position we can get AirPods model, gen1, gen2, Pro or Max
    result_data.model = AIRPODS_MODEL_MAP.get(chr(raw[7]), "unknown")

    # Checking left AirPod for availability and storing charge in variable
    status_tmp = int("" + chr(raw[12 if flip else 13]), 16)
    left_status = (
        100 if status_tmp == 10 else (status_tmp * 10 + 5 if status_tmp <= 10 else -1)
    )

    # Checking right AirPod for availability and storing charge in variable
    status_tmp = int("" + chr(raw[13 if flip else 12]), 16)
    right_status = (
        100 if status_tmp == 10 else (status_tmp * 10 + 5 if status_tmp <= 10 else -1)
    )

    # Checking AirPods case for availability and storing charge in variable
    status_tmp = int("" + chr(raw[15]), 16)
    case_status = (
        100 if status_tmp == 10 else (status_tmp * 10 + 5 if status_tmp <= 10 else -1)
    )

    result_data.charge = dict(left=left_status, right=right_status, case=case_status)

    # On 14th position we can get charge status of AirPods
    charging_status = int("" + chr(raw[14]), 16)
    result_data.charging_left = (
        charging_status & (0b00000010 if flip else 0b00000001)
    ) != 0
    result_data.charging_right = (
        charging_status & (0b00000001 if flip else 0b00000010)
    ) != 0
    result_data.charging_case = (charging_status & 0b00000100) != 0

    return result_data


# Return if left and right is flipped in the data
def is_flipped(raw):
    return (int("" + chr(raw[10]), 16) & 0x02) == 0


def run():
    output_file = sys.argv[-1]

    try:
        while True:
            data = get_data()

            if data.status == 1:
                json_data = dumps(asdict(data))
                if len(sys.argv) > 1:
                    with open(output_file, "a") as f:
                        f.write(json_data + "\n")
                else:
                    print(json_data)

            sleep(UPDATE_DURATION)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
