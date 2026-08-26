"""Memory-mapped register map for the TDC AXI slave (base 0x40000000)."""

ID_VALUE = 0x54444331  # "TDC1"
DEFAULT_CLOCK_HZ = 250_000_000
DEFAULT_TIMEOUT_TICKS = 500_000_000  # 2 s @ 250 MHz
DEFAULT_BASE = 0x40000000
MAP_SIZE = 4096

ADDR_ID = 0x00
ADDR_CONTROL = 0x04
ADDR_STATUS = 0x08
ADDR_SEQ = 0x0C
ADDR_DT_TICKS = 0x10
ADDR_T_START = 0x14
ADDR_T_STOP = 0x18
ADDR_FLAGS = 0x1C
ADDR_TIMEOUT = 0x20
ADDR_CLOCK_HZ = 0x24

CTRL_ENABLE = 1 << 0
CTRL_SOFT_RESET = 1 << 1

STATUS_VALID = 1 << 0
STATUS_ARMED = 1 << 1
STATUS_MMCM_LOCKED = 1 << 2

FLAG_TIMEOUT = 1 << 0
FLAG_OVERFLOW = 1 << 1
FLAG_UNMATCHED_STOP = 1 << 2

FLAG_NAMES = (
    (FLAG_TIMEOUT, "timeout"),
    (FLAG_OVERFLOW, "overflow"),
    (FLAG_UNMATCHED_STOP, "unmatched_stop"),
)


def flags_to_names(flags: int) -> list:
    return [name for bit, name in FLAG_NAMES if flags & bit]
