"""Feeds the analyser the SPI frames of known transactions and checks what it makes of them.

Run from the repository root: `python3 -m unittest discover tests`.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from saleae.analyzers import AnalyzerFrame  # noqa: E402 (the stub in tests/saleae)
from Nrf70Analyzer import Nrf70Analyzer  # noqa: E402


def le(*values):
    return [b for v in values for b in v.to_bytes(4, "little")]


class Bus:
    """Plays transactions into an analyser, as Logic 2's SPI analyser would frame them."""

    def __init__(self):
        self.hla = Nrf70Analyzer()
        self.time = 0.0

    def transaction(self, mosi, miso=None):
        miso = miso or [0] * len(mosi)
        out = [self.hla.decode(AnalyzerFrame("enable", self.time, self.time))]
        for m, s in zip(mosi, miso):
            data = {"mosi": bytes([m]), "miso": bytes([s])}
            out.append(self.hla.decode(AnalyzerFrame("result", self.time, self.time, data)))
        out.append(self.hla.decode(AnalyzerFrame("disable", self.time, self.time + 1e-6)))
        self.time += 1e-5
        frames = [f for f in out if f is not None]
        assert len(frames) == 1, frames
        return frames[0]

    def read(self, address, data):
        """FAST_READ: opcode, 24-bit address, one dummy byte, then the data on MISO."""
        header = [0x0B, address >> 16, (address >> 8) & 0xFF, address & 0xFF, 0]
        return self.transaction(header + [0] * len(data), [0] * 5 + data)

    def write(self, address, data):
        """PP: opcode, 24-bit address with bit 23 set, then the data on MOSI."""
        address |= 0x800000
        return self.transaction([0x02, address >> 16, (address >> 8) & 0xFF, address & 0xFF] + data)


class Decode(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()

    def test_status_registers(self):
        frame = self.bus.transaction([0x1F, 0], [0, 0x06])
        self.assertEqual(frame.type, "RDSR1")
        self.assertEqual(frame.data["summary"], "SR1 = 0x06 AWAKE|READY")
        self.assertEqual(self.bus.transaction([0x3F, 0x01]).data["summary"], "SR2 := 0x01 WAKEUP_REQ")
        self.assertEqual(self.bus.transaction([0x05, 0], [0, 0]).data["summary"], "SR0 = 0x00")

    def test_register_read_skips_the_latency_word(self):
        # INT_FROM_RPU_CTRL is in SYSBUS: a single read returns one word of latency first.
        frame = self.bus.read(0x000400, le(0xDEADBEEF, 0x00020000))
        self.assertEqual(frame.data["summary"], "read INT_FROM_RPU_CTRL = 0x00020000")
        self.assertEqual(frame.data["region"], "SYSBUS")
        # GRAM has two.
        frame = self.bus.read(0x080D54, le(1, 2, 0x01010700))
        self.assertEqual(frame.data["summary"], "read LMAC_VER = 0x01010700")

    def test_packet_ram_has_no_latency(self):
        frame = self.bus.read(0x0C0004, le(0x01020E09))
        self.assertEqual(frame.data["summary"], "read UMAC_VER = 0x01020E09")

    def test_burst_read(self):
        frame = self.bus.read(0x8C5000, le(1, 2, 3, 4, 5))
        self.assertEqual(frame.data["summary"], "read 20 B burst from PKT+0x00000: 00000001 00000002 00000003 00000004 ...")
        self.assertEqual(frame.data["bytes"], 20)

    def test_writes(self):
        frame = self.bus.write(0x000494, le(0x80000000))
        self.assertEqual(frame.type, "PP")
        self.assertEqual(frame.data["summary"], "write INT_FROM_MCU_CTRL = 0x80000000")
        frame = self.bus.write(0x0C5100, list(range(8)))
        self.assertEqual(frame.data["summary"], "write 8 B to PKT+0x00100: 03020100 07060504")

    def test_queues_are_named_once_the_queue_table_is_read(self):
        # The RPU publishes an enqueue and a dequeue address per queue at HPQ_INFO.
        queues = [0xA4000D00 + 4 * i for i in range(14)]
        self.assertEqual(self.bus.read(0x0C0004, le(0)).data["summary"], "read UMAC_VER = 0x00000000")
        self.bus.read(0x8C0024, le(*queues))
        # event_busy.dequeue is the second word; cmd_busy.enqueue the fifth.
        frame = self.bus.read(0x000D04, le(0, 0xB0006000))
        self.assertEqual(frame.data["summary"], "read HPQ event_busy.dequeue = 0xB0006000")
        frame = self.bus.write(0x000D10, le(0xB0007000))
        self.assertEqual(frame.data["summary"], "write HPQ cmd_busy.enqueue = 0xB0007000")

    def test_queue_table_read_word_by_word(self):
        queues = [0xA4000D00 + 4 * i for i in range(14)]
        for i, q in enumerate(queues):
            self.bus.read(0x0C0024 + 4 * i, le(q))
        frame = self.bus.read(0x000D00, le(0, 7))
        self.assertEqual(frame.data["summary"], "read HPQ event_busy.enqueue = 0x00000007")

    def test_write_enable_from_a_qspi_host(self):
        frame = self.bus.transaction([0x06])
        self.assertEqual(frame.type, "WREN")
        self.assertEqual(frame.data["summary"], "WREN (QSPI host)")

    def test_quad_and_unknown_commands(self):
        frame = self.bus.transaction([0xEB] + [0] * 20)
        self.assertEqual(frame.type, "READ4IO")
        frame = self.bus.transaction([0x99, 1, 2])
        self.assertEqual(frame.type, "unknown")
        self.assertEqual(frame.data["summary"], "0x99, 3 bytes")


if __name__ == "__main__":
    unittest.main()
