# Hardware Links

These links are the parts used for the Chapter Player build. Quantities are for one player.

Links may change over time; equivalent parts should also work if they match the specs in the install guide and wiring tables.

## Electronics

| Part | Qty | Link | Notes |
| --- | ---: | --- | --- |
| Raspberry Pi Zero 2 W/WH | 1 | [Adafruit product 6008](https://www.adafruit.com/product/6008) | Use a WH board or add a soldered 40-pin header. |
| 2.08 inch SH1122 SPI OLED | 1 | [Amazon ASIN B0D1V5YBXC](https://www.amazon.com/dp/B0D1V5YBXC) | 256x64 SPI OLED. |
| KY-040 rotary encoder module | 2 | [Amazon ASIN B07T3672VK](https://www.amazon.com/dp/B07T3672VK) | One for the Select knob and one for the Volume knob. |
| MAX98357A I2S mono amplifier breakout | 1 | [Amazon ASIN B0GF67KXC3](https://www.amazon.com/dp/B0GF67KXC3?th=1) | Drives the internal speaker. |
| Adafruit 5993 vertical USB-C breakout | 1 | [Adafruit product 5993](https://www.adafruit.com/product/5993) | Rear USB-C power port. Solder positive power to `VBUS` and negative power to `GND`; either duplicate pad row may be used. Leave all data pads disconnected. Adafruit specifies up to 1.5 A for this breakout arrangement. |
| Inline fuse holder and fuse | 1 | [Amazon ASIN B0813Q4S6P](https://www.amazon.com/dp/B0813Q4S6P) | Install the included **1.5 A fast-blow 5x20 mm fuse** in series on the positive lead. The linked assortment also contains unsuitable higher-current fuses, so verify the marking before installation. |
| 3 mm warm-white power indicator LED | 1 | [Dioramo 13240](https://dioramo.com/products/13240) | Fits the lower-right front-cover hole. This 5-6 V version includes its current-limiting resistor and connects directly across Chapter's fused 5 V and ground leads. |
| Visaton FRWS 5 - 4 Ohm full-range speaker | 1 | [Parts Express 292-7820](https://www.parts-express.com/Visaton-FRWS5-4-2-Full-Range-Speaker-4-Ohm-292-7820?quantity=1) | Internal speaker. |
| Cross-connect wiring | 1 set | [Amazon ASIN B01EV70C78](https://www.amazon.com/dp/B01EV70C78?th=1) | Used for wiring between the Raspberry Pi and the display, encoders, amp, USB-C board, and fuse. |

## Case Hardware

| Part | Qty | Link | Notes |
| --- | ---: | --- | --- |
| Polyurethane adhesive feet | 4 | [Amazon ASIN B074PXV3D8](https://www.amazon.com/dp/B074PXV3D8?th=1) | Install in the bottom foot indents shown in the case diagram. |
| M2.5 heat press threaded inserts | 18 | Source from your preferred hardware supplier | Install in the highlighted component mounting holes. |
| M2.5x5 mm screws | 18 | Source from your preferred hardware supplier | Used for mounting components into the heat press inserts. |
| Printed case front, back, and knobs | 1 set | [Case STL files](../hardware/case/) | Print the v5 case files from the repository. |

## Common Build Supplies

- 16 GB or larger microSD card.
- Regulated 5 V power supply rated for at least 2 A; 2.5 A is also suitable. The specified Adafruit 5993 remains limited to the 1.5 A arrangement described in the install guide.
- Cross-connect wires or soldered hookup wire.
- Soldering tools if using a Raspberry Pi Zero 2 W without a pre-soldered header.

See the [Raspberry Pi Zero 2 W install guide](raspberry-pi-zero-2w-install.md) for wiring tables and setup steps.
