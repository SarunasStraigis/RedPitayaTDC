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
ADDR_PINS = 0x28

CTRL_ENABLE = 1 << 0
CTRL_SOFT_RESET = 1 << 1

STATUS_VALID = 1 << 0
STATUS_ARMED = 1 << 1
STATUS_MMCM_LOCKED = 1 << 2

PINS_CAP_SHIFT = 16
PINS_CAP_VALUE = 0x0001
PIN_SEL_MASK = 0xF
DEFAULT_START_SEL = 8  # DIO7_P / E1 pin 17
DEFAULT_STOP_SEL = 9   # DIO7_N / E1 pin 18

# Index matches tdc_axi.v dio_i[*]. Labels are the UI source of truth.
PIN_TABLE = (
    {"index": 0, "name": "DIO0_P", "e1": 3, "fpga": "G17"},
    {"index": 1, "name": "DIO0_N", "e1": 4, "fpga": "G18"},
    {"index": 2, "name": "DIO1_P", "e1": 5, "fpga": "H16"},
    {"index": 3, "name": "DIO1_N", "e1": 6, "fpga": "H17"},
    {"index": 4, "name": "DIO2_P", "e1": 7, "fpga": "J18"},
    {"index": 5, "name": "DIO2_N", "e1": 8, "fpga": "H18"},
    {"index": 6, "name": "DIO3_P", "e1": 9, "fpga": "K17"},
    {"index": 7, "name": "DIO3_N", "e1": 10, "fpga": "K18"},
    {"index": 8, "name": "DIO7_P", "e1": 17, "fpga": "M14"},
    {"index": 9, "name": "DIO7_N", "e1": 18, "fpga": "M15"},
)

FLAG_TIMEOUT = 1 << 0
FLAG_OVERFLOW = 1 << 1
FLAG_UNMATCHED_STOP = 1 << 2

FLAG_NAMES = (
    (FLAG_TIMEOUT, "timeout"),
    (FLAG_OVERFLOW, "overflow"),
    (FLAG_UNMATCHED_STOP, "unmatched_stop"),
)

BAD_FLAG_MASK = FLAG_TIMEOUT | FLAG_OVERFLOW | FLAG_UNMATCHED_STOP


def flags_to_names(flags: int) -> list:
    return [name for bit, name in FLAG_NAMES if flags & bit]


def is_good_pair(valid: bool, flags: int) -> bool:
    """True for a START→STOP delay (not unmatched STOP / timeout / overflow)."""
    return bool(valid) and (int(flags) & BAD_FLAG_MASK) == 0


def same_bin_pair(valid: bool, flags: int, t_start: int, t_stop: int) -> bool:
    """True when a good pair has identical start/stop timestamps (0 ns / same 4 ns bin)."""
    if not is_good_pair(valid, flags):
        return False
    return (int(t_start) & 0xFFFFFFFF) == (int(t_stop) & 0xFFFFFFFF)


def pin_label(entry: dict) -> str:
    return "%s (E1 pin %d)" % (entry["name"], entry["e1"])


def pin_info(index: int) -> dict:
    entry = PIN_TABLE[int(index)]
    out = dict(entry)
    out["label"] = pin_label(entry)
    return out


def pins_list() -> list:
    return [pin_info(p["index"]) for p in PIN_TABLE]


def pins_selectable(word: int) -> bool:
    return ((int(word) >> PINS_CAP_SHIFT) & 0xFFFF) == PINS_CAP_VALUE


def decode_pins_word(word: int) -> tuple:
    start = int(word) & PIN_SEL_MASK
    stop = (int(word) >> 4) & PIN_SEL_MASK
    return start, stop


def encode_pins_word(start: int, stop: int) -> int:
    return (PINS_CAP_VALUE << PINS_CAP_SHIFT) | ((int(stop) & PIN_SEL_MASK) << 4) | (int(start) & PIN_SEL_MASK)


def parse_pin_sel(value) -> int:
    if isinstance(value, bool):
        raise ValueError("invalid pin")
    if isinstance(value, int):
        idx = value
    else:
        text = str(value).strip()
        try:
            idx = int(text, 0)
        except ValueError:
            idx = None
            key = text.upper().replace(" ", "")
            for p in PIN_TABLE:
                if key == p["name"].upper():
                    idx = p["index"]
                    break
                if key in ("E1-%d" % p["e1"], "E1PIN%d" % p["e1"], "PIN%d" % p["e1"]):
                    idx = p["index"]
                    break
            if idx is None:
                raise ValueError("unknown pin %r" % value)
    if idx < 0 or idx >= len(PIN_TABLE):
        raise ValueError("pin index out of range: %r" % value)
    return idx
