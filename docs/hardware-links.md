# Hardware Links

These links are the parts used for the Chapter Player build. Quantities are for one player.

Links may change over time; equivalent parts should also work if they match the specs in the install guide and wiring tables.

## Electronics

| Part | Qty | Link | Notes |
| --- | ---: | --- | --- |
| Raspberry Pi Zero 2 W/WH | 1 | [Adafruit product 6008](https://www.adafruit.com/product/6008) | Use a WH board or add a soldered 40-pin header. |
| 2.08 inch SH1122 SPI OLED | 1 | [Amazon ASIN B0D1V5YBXC](https://www.amazon.com/dp/B0D1V5YBXC) | 256x64 SPI OLED. |
| KY-040 rotary encoder module | 2 | [Amazon ASIN B07T3672VK](https://www.amazon.com/dp/B07T3672VK) | One for navigation and one for volume. |
| MAX98357A I2S mono amplifier breakout | 1 | [Amazon ASIN B0GF67KXC3](https://www.amazon.com/dp/B0GF67KXC3?th=1) | Drives the internal speaker. |
| Adafruit 5993 vertical USB-C breakout | 1 | [Adafruit product 5993](https://www.adafruit.com/product/5993) | Rear USB-C service/power port. |
| Inline fuse for USB-C 5 V positive lead | 1 | [Amazon ASIN B0813Q4S6P](https://www.amazon.com/dp/B0813Q4S6P) | Install in series on the positive leg from the USB-C board before the Raspberry Pi 5 V input. |
| Visaton FRWS 5 - 4 Ohm full-range speaker | 1 | [Parts Express 292-7820](https://www.parts-express.com/Visaton-FRWS5-4-2-Full-Range-Speaker-4-Ohm-292-7820?quantity=1) | Internal speaker. |
| Cross-connect wiring | 1 set | [Amazon ASIN B01EV70C78](https://www.amazon.com/dp/B01EV70C78?th=1) | Used for wiring between the Raspberry Pi and the display, encoders, amp, USB-C board, and fuse. |

## Case Hardware

| Part | Qty | Link | Notes |
| --- | ---: | --- | --- |
| Polyurethane adhesive feet | 4 | [Amazon ASIN B074PXV3D8](https://www.amazon.com/dp/B074PXV3D8?th=1) | Install in the bottom foot indents shown in the case diagram. |
| M2.5 heat press threaded inserts | As needed | Source from your preferred hardware supplier | Install in the highlighted component mounting holes. |
| M2.5x5 mm screws | As needed | Source from your preferred hardware supplier | Used for mounting components into the heat press inserts. |
| Printed case front, back, and knobs | 1 set | [Case STL files](../hardware/case/) | Print the v5 case files from the repository. |

## Common Build Supplies

- 16 GB or larger microSD card.
- 5 V power supply, ideally 2.5 A.
- Cross-connect wires or soldered hookup wire.
- Soldering tools if using a Raspberry Pi Zero 2 W without a pre-soldered header.

See the [Raspberry Pi Zero 2 W install guide](raspberry-pi-zero-2w-install.md) for wiring tables and setup steps.
