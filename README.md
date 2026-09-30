# nRF70 SPI analyser for Saleae Logic 2

A Logic 2 High Level Analyzer (HLA) for the host bus of Nordic's nRF7002 Wi-Fi companion IC. It
takes the frames of Logic 2's SPI analyser and turns each chip-select period into one frame: a status
register access, or a read or write with the memory region, the register or queue name, and the data.

Logic 2 extensions can only be written in Python.

## Use

1. In Logic 2, open the **Extensions** panel, then **⋮ → Load Existing Extension**, and pick this
   folder's `extension.json`.
2. Add an **SPI** analyser: MOSI on DIO0, MISO on DIO1, clock on SCK, enable on CS (active low),
   8 bits, MSB first, CPOL 0, CPHA 0.
3. Add **nRF70 SPI** with that SPI analyser as its input.

The host must drive the nRF7002 over one data line: SPI, or QSPI with FAST_READ and PP. Quad
transfers (READ4IO, PP4IO) cannot be decoded from the two lines the SPI analyser samples; they show
up by opcode and length only.

## What it decodes

- The nRF7002 commands (nRF7002 PS v1.2, section 7.1, table 3): RDSR0, RDSR1 and RDSR2 with their
  bits (`WIP`, `AWAKE`, `READY`, `WAKEUP_REQ`), WRSR2, FAST_READ, PP, CIPHER_INIT; READ4IO and PP4IO
  by opcode only. Any other opcode is shown as raw bytes, except WREN (`0x06`): not an nRF7002
  command, but the nRF52 and nRF53 QSPI peripherals send it before every page program, and poll
  RDSR0 after it, as they would for a flash.
- The host address space: the region (`SYSBUS`, `PBUS`, `GRAM`, `PKTRAM`, the LMAC and UMAC memories)
  and the offset in it. Address bit 23 marks a burst (the address increments).
- Reads of a single word skip the region's latency words (one in `SYSBUS` and `PBUS`, two in `GRAM`),
  so the value shown is the register's.
- The registers and memory locations the driver uses by name (`INT_FROM_RPU_CTRL`, `UMAC_VER`,
  `RX_CMD_BASE`...), packet buffers as `PKT+offset`.
- The host port queues: when the capture includes the host reading the queue table (`HPQ_INFO`,
  at start-up), later accesses to the queues are named, for example `HPQ event_busy.dequeue`.

A frame's type is its command (`RDSR0`, `RDSR1`, `RDSR2`, `WRSR2`, `FAST_READ`, `PP`, `READ4IO`,
`PP4IO`, `CIPHER_INIT`, `WREN`, or `unknown`). Reads and writes also carry `region`, `name` and
`bytes` fields, which Logic 2 shows and exports with the data table.

## Sources

- nRF7002 Product Specification v1.2, section 7 (commands).
- The `nrf70` driver, <https://github.com/embassy-rs/nrf70>: `src/lib.rs` (`regions`,
  `HostRpuHPQMInfo`, `SpiBus`) and `fw/bindings.rs`, generated from the nRF Connect SDK 3.4.0
  headers (register and memory addresses).

## Tests

```sh
python3 -m unittest discover tests
```

`tests/saleae/` stands in for Logic 2's `saleae.analyzers` module, so the tests run with a plain
Python 3.
