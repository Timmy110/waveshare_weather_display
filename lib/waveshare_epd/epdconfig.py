# *****************************************************************************
# * | File        :   epdconfig.py
# * | Author      :   Waveshare electronics (modified for libgpiod)
# * | Function    :   Hardware underlying interfaces
# * | Info        :
# *                Used to drive the e-paper display via SPI on Raspberry Pi.
# *                Adapted from Waveshare official library.
# *                Modified: Replaced RPi.GPIO with gpiod for Debian 12+/13+
# *****************************************************************************
import time
import os
import ctypes


# Pin configuration for Waveshare 7.5" E-Paper HAT (B) V2
RST_PIN = 17
DC_PIN = 25
BUSY_PIN = 24
CS_PIN = 8

# GPIOD handles (set during module_init)
_gpio_chip = None
_line_rst = None
_line_dc = None
_line_busy = None
_line_cs = None


def _open_gpiochip():
    global _gpio_chip
    try:
        import gpiod
    except ImportError:
        # On older systems the lib may be named pigpiod/gpiod differently
        raise ImportError(
            "gpiod library not found. Install with: pip install gpiod "
            "or sudo apt install python3-gpiod"
        )
    # For most Raspberry Pi boards, gpiochip0 is the correct chip.
    _gpio_chip = gpiod.chip('gpiochip0')


def _get_output_line(pin):
    """Configure and return a GPIOD output line handle."""
    line = _gpio_chip.get_line(pin)
    line.request(consumer='waveshare_epd', type=gpiod.LINE_REQ_DIR_OUT)
    return line


def _get_input_line(pin):
    """Configure and return a GPIOD input line handle."""
    line = _gpio_chip.get_line(pin)
    line.request(consumer='waveshare_epd', type=gpiod.LINE_REQ_DIR_IN)
    return line


def module_init():
    """Initialize SPI and GPIO. Returns 0 on success."""
    global _gpio_chip, _line_rst, _line_dc, _line_busy, _line_cs

    # Initialize GPIO via gpiod
    _open_gpiochip()
    _line_rst = _get_output_line(RST_PIN)
    _line_dc = _get_output_line(DC_PIN)
    _line_busy = _get_input_line(BUSY_PIN)
    _line_cs = _get_output_line(CS_PIN)

    # Initialize SPI
    import spidev
    global SPI
    SPI = spidev.SpiDev()
    SPI.open(0, 0)
    SPI.max_speed_hz = 4000000
    SPI.mode = 0b00

    return 0


def module_exit(cleanup=False):
    """Clean up GPIO and SPI."""
    global _gpio_chip, _line_rst, _line_dc, _line_busy, _line_cs
    for line in (_line_rst, _line_dc, _line_busy, _line_cs):
        try:
            if line is not None:
                line.release()
        except Exception:
            pass
    _line_rst = _line_dc = _line_busy = _line_cs = None
    _gpio_chip = None

    try:
        global SPI
        SPI.close()
    except Exception:
        pass


def digital_write(pin, value):
    """Write a value (0 or 1) to the specified GPIO pin."""
    line_map = {RST_PIN: _line_rst, DC_PIN: _line_dc, CS_PIN: _line_cs}
    line = line_map.get(pin)
    if line is None:
        raise ValueError(f"Pin {pin} is not configured as output")
    line.set_value(bool(value))


def digital_read(pin):
    """Read the value (0 or 1) from the specified GPIO pin."""
    # BUS_PIN is the only input pin we use
    if pin == BUSY_PIN and _line_busy is not None:
        return _line_busy.get_value()
    raise ValueError(f"Pin {pin} is not configured as input")


def delay_ms(delay):
    time.sleep(delay / 1000.0)


def spi_writebyte(data):
    global SPI
    SPI.writebytes(data)


def spi_writebyte2(data):
    global SPI
    SPI.writebytes2(data if hasattr(SPI, 'writebytes2') else bytes(data))
