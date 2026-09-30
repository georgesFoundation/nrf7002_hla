"""Saleae Logic 2 HLA for the host bus of the nRF7002 (SPI, or QSPI in single-line mode).

The commands are those of the nRF7002 Product Specification v1.2, section 7.1, table 3. The memory
regions, registers and host port queue table come from the `nrf70` driver
(https://github.com/embassy-rs/nrf70): `src/lib.rs` (`regions`, `HostRpuHPQMInfo`) and
`fw/bindings.rs`, generated from the nRF Connect SDK 3.4.0 headers. Keep them in step.

It takes the frames of Logic 2's SPI analyser (MOSI on DIO0, MISO on DIO1, enable on CS) and turns
each transaction into one frame. Quad transfers (READ4IO, PP4IO) cannot be decoded from two lines:
they are shown by opcode and length only.
"""

from saleae.analyzers import AnalyzerFrame, HighLevelAnalyzer

# Host address space: name, first and last address, latency (words a single read returns before
# the one asked for), and the RPU address of the region's start.
REGIONS = [
    ("SYSBUS", 0x000000, 0x008FFF, 1, 0xA4000000),
    ("EXT_SYS_BUS", 0x009000, 0x03FFFF, 2, None),
    ("PBUS", 0x040000, 0x07FFFF, 1, 0xA5000000),
    ("GRAM", 0x080000, 0x092000, 2, 0xB7000000),
    ("PKTRAM", 0x0C0000, 0x0F0FFF, 0, 0xB0000000),
    ("LMAC_ROM", 0x100000, 0x134000, 1, 0x80000000),
    ("LMAC_RET_RAM", 0x140000, 0x14C000, 1, 0x80040000),
    ("LMAC_SRC_RAM", 0x180000, 0x190000, 1, 0x80080000),
    ("UMAC_ROM", 0x200000, 0x261800, 1, 0x80000000),
    ("UMAC_RET_RAM", 0x280000, 0x2A4000, 1, 0x80080000),
    ("UMAC_SRC_RAM", 0x300000, 0x338000, 1, 0x80100000),
]

# RPU addresses the driver uses (`fw/bindings.rs`).
NAMES = {
    0xA4000000: "MIPS_MCU_CONTROL",
    0xA4000004: "MIPS_MCU_UCCP_INT_STATUS",
    0xA400000C: "MIPS_MCU_UCCP_INT_CLEAR",
    0xA4000030: "MIPS_MCU_SYS_CORE_MEM_CTRL",
    0xA4000034: "MIPS_MCU_SYS_CORE_MEM_WDATA",
    0xA4000050: "MIPS_MCU_BOOT_EXCP_INSTR_0",
    0xA4000054: "MIPS_MCU_BOOT_EXCP_INSTR_1",
    0xA4000058: "MIPS_MCU_BOOT_EXCP_INSTR_2",
    0xA400005C: "MIPS_MCU_BOOT_EXCP_INSTR_3",
    0xA4000100: "MIPS_MCU2_CONTROL",
    0xA4000130: "MIPS_MCU2_SYS_CORE_MEM_CTRL",
    0xA4000134: "MIPS_MCU2_SYS_CORE_MEM_WDATA",
    0xA4000150: "MIPS_MCU2_BOOT_EXCP_INSTR_0",
    0xA4000154: "MIPS_MCU2_BOOT_EXCP_INSTR_1",
    0xA4000158: "MIPS_MCU2_BOOT_EXCP_INSTR_2",
    0xA400015C: "MIPS_MCU2_BOOT_EXCP_INSTR_3",
    0xA4000400: "INT_FROM_RPU_CTRL",
    0xA4000480: "INT_TO_MCU_CTRL",
    0xA4000488: "INT_FROM_MCU_ACK",
    0xA4000494: "INT_FROM_MCU_CTRL",
    0xA4002C2C: "UCC_SLEEP_CTRL_DATA_0",
    0xA4002C30: "UCC_SLEEP_CTRL_DATA_1",
    0xB0000000: "UMAC_BOOT_SIG",
    0xB0000004: "UMAC_VER",
    0xB00000B8: "TX_CMD_BASE",
    0xB0004FD4: "OTP_PACKAGE_TYPE",
    0xB0004FD8: "OTP_FT_PROG_VERSION",
    0xB0004FDC: "OTP_INFO_FLAGS",
    0xB7000D50: "LMAC_BOOT_SIG",
    0xB7000D54: "LMAC_VER",
    0xB7000D58: "RX_CMD_BASE",
}

# `HostRpuHPQMInfo`: one enqueue and one dequeue address per queue, as the RPU publishes them.
HPQ_INFO = 0xB0000024
HPQ_QUEUES = ["event_busy", "event_avl", "cmd_busy", "cmd_avl", "rx_buf_busy0", "rx_buf_busy1", "rx_buf_busy2"]
HPQ_INFO_WORDS = 2 * len(HPQ_QUEUES)

# Packet buffers start here (`RPU_MEM_PKT_BASE`).
PKT_BASE = 0xB0005000

# Address bit 23: the address increments through a burst (NCS `addrmask`).
ADDR_INCREMENT = 0x800000

RDSR0, RDSR1, RDSR2, WRSR2 = 0x05, 0x1F, 0x2F, 0x3F
CIPHER_INIT, FAST_READ, READ4IO, PP, PP4IO = 0x4F, 0x0B, 0xEB, 0x02, 0x38

# Not an nRF7002 command: the nRF52 and nRF53 QSPI peripherals send a flash write enable before
# each page program, and poll RDSR0 after it.
WREN = 0x06

# Status register bits, as the driver reads them.
STATUS_BITS = {
    RDSR0: [(0x01, "WIP")],
    RDSR1: [(0x02, "AWAKE"), (0x04, "READY")],
    RDSR2: [(0x01, "WAKEUP_REQ")],
}
STATUS_NAMES = {RDSR0: "SR0", RDSR1: "SR1", RDSR2: "SR2"}

# Frame types: the command of each transaction (the PS calls RDSR0 just RDSR).
COMMANDS = {
    RDSR0: "RDSR0",
    RDSR1: "RDSR1",
    RDSR2: "RDSR2",
    WRSR2: "WRSR2",
    CIPHER_INIT: "CIPHER_INIT",
    FAST_READ: "FAST_READ",
    READ4IO: "READ4IO",
    PP: "PP",
    PP4IO: "PP4IO",
    WREN: "WREN",
}
UNKNOWN = "unknown"

# Longest list of words printed in full; longer transfers show their length and first words.
MAX_WORDS = 4


def _byte(value):
    if isinstance(value, (bytes, bytearray, list, tuple)):
        return int(value[0]) if len(value) else 0
    return int(value)


def words(data):
    return [int.from_bytes(bytes(data[i : i + 4]), "little") for i in range(0, len(data) - 3, 4)]


def region_of(address):
    for region in REGIONS:
        if region[1] <= address <= region[2]:
            return region
    return None


def status_text(op, value):
    bits = [name for bit, name in STATUS_BITS[op] if value & bit]
    return "0x%02X%s" % (value, " " + "|".join(bits) if bits else "")


class Nrf70Analyzer(HighLevelAnalyzer):
    result_types = {name: {"format": "{{data.summary}}"} for name in list(COMMANDS.values()) + [UNKNOWN]}

    def __init__(self):
        self._start = None
        self._mosi = []
        self._miso = []
        self._hpq_words = {}
        self._queue_names = {}

    def decode(self, frame):
        if frame.type == "enable":
            self._start = frame.start_time
            self._mosi = []
            self._miso = []
            return None
        if frame.type == "result":
            if self._start is None:
                self._start = frame.start_time
            self._mosi.append(_byte(frame.data.get("mosi", 0)))
            self._miso.append(_byte(frame.data.get("miso", 0)))
            return None
        if frame.type == "disable":
            if self._start is None or not self._mosi:
                self._start = None
                return None
            result = self._transaction(self._start, frame.end_time)
            self._start = None
            return result
        return None

    # --- naming

    def _name(self, rpu):
        if rpu in self._queue_names:
            return self._queue_names[rpu]
        if rpu in NAMES:
            return NAMES[rpu]
        if HPQ_INFO <= rpu < HPQ_INFO + 4 * HPQ_INFO_WORDS:
            return "HPQ_INFO+0x%02X" % (rpu - HPQ_INFO)
        if rpu >= PKT_BASE and rpu < 0xB1000000:
            return "PKT+0x%05X" % (rpu - PKT_BASE)
        return None

    def _describe(self, address):
        region = region_of(address)
        if region is None:
            return "0x%06X" % address, None, "?"
        name, start, _, _, base = region
        rpu = base + (address - start) if base is not None else None
        label = self._name(rpu) if rpu is not None else None
        text = label or "%s+0x%05X" % (name, address - start)
        return text, rpu, name

    def _learn_hpq(self, rpu, values):
        for i, value in enumerate(values):
            offset = rpu + 4 * i - HPQ_INFO
            if 0 <= offset < 4 * HPQ_INFO_WORDS:
                self._hpq_words[offset // 4] = value
        if len(self._hpq_words) == HPQ_INFO_WORDS:
            for q, queue in enumerate(HPQ_QUEUES):
                self._queue_names[self._hpq_words[2 * q]] = "HPQ %s.enqueue" % queue
                self._queue_names[self._hpq_words[2 * q + 1]] = "HPQ %s.dequeue" % queue

    # --- transactions

    def _transaction(self, start, end):
        op = self._mosi[0]
        n = len(self._mosi)

        if op in STATUS_BITS:
            if n < 2:
                return self._frame(COMMANDS[op], start, end, "%s (no data)" % STATUS_NAMES[op])
            value = self._miso[1]
            summary = "%s = %s" % (STATUS_NAMES[op], status_text(op, value))
            return self._frame(COMMANDS[op], start, end, summary, bytes=1)

        if op == WRSR2:
            if n < 2:
                return self._frame("WRSR2", start, end, "WRSR2 (no data)")
            value = self._mosi[1]
            summary = "SR2 := %s" % status_text(RDSR2, value)
            return self._frame("WRSR2", start, end, summary, bytes=1)

        if op in (FAST_READ, PP):
            if n < 4:
                return self._frame(COMMANDS[op], start, end, "%s, %d bytes (no address)" % (COMMANDS[op], n))
            raw = (self._mosi[1] << 16) | (self._mosi[2] << 8) | self._mosi[3]
            address = raw & ~ADDR_INCREMENT
            burst = bool(raw & ADDR_INCREMENT)
            text, rpu, region = self._describe(address)
            if op == FAST_READ:
                return self._read(start, end, address, burst, text, rpu, region, self._miso[5:])
            return self._write(start, end, burst, text, rpu, region, self._mosi[4:])

        if op in (READ4IO, PP4IO):
            summary = "%s, %d clocks (quad: decode with the host on one line)" % (COMMANDS[op], 8 * n)
            return self._frame(COMMANDS[op], start, end, summary)

        if op == WREN and n == 1:
            return self._frame("WREN", start, end, "WREN (QSPI host)")

        if op == CIPHER_INIT:
            return self._frame("CIPHER_INIT", start, end, "CIPHER_INIT " + " ".join("%02X" % b for b in self._mosi[1:]))

        return self._frame(UNKNOWN, start, end, "0x%02X, %d bytes" % (op, n))

    def _read(self, start, end, address, burst, text, rpu, region, data):
        region_info = region_of(address)
        latency = region_info[3] if region_info else 0
        values = words(data)
        if not burst and latency and len(values) == latency + 1:
            # A single word: the first `latency` words are not the register's.
            values = values[latency:]
        if rpu is not None:
            self._learn_hpq(rpu, values)
        if len(values) == 1:
            summary = "read %s = 0x%08X" % (text, values[0])
        else:
            shown = " ".join("%08X" % v for v in values[:MAX_WORDS])
            more = " ..." if len(values) > MAX_WORDS else ""
            summary = "read %d B%s from %s: %s%s" % (len(data), " burst" if burst else "", text, shown, more)
        return self._frame("FAST_READ", start, end, summary, region=region, name=text, bytes=len(data))

    def _write(self, start, end, burst, text, rpu, region, data):
        values = words(data)
        if len(values) == 1:
            summary = "write %s = 0x%08X" % (text, values[0])
        else:
            shown = " ".join("%08X" % v for v in values[:MAX_WORDS])
            more = " ..." if len(values) > MAX_WORDS else ""
            summary = "write %d B to %s: %s%s" % (len(data), text, shown, more)
        return self._frame("PP", start, end, summary, region=region, name=text, bytes=len(data))

    def _frame(self, command, start, end, summary, **fields):
        data = {"summary": summary, "bytes": 0}
        data.update(fields)
        return AnalyzerFrame(command, start, end, data)
