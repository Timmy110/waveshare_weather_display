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
_chip = None
_line_rst = None
_line_dc = None
_line_busy = None
_line_cs = None


def _open_gpiochip():
    """Open the GPIO chip, trying multiple library APIs."""
    global _chip, _gpiod_api

    # Try gpiodev first (newer Debian packages like Trixie)
    try:
        import gpiodev
        _chip = gpiodev.Chip('gpiochip0')
        _gpiod_api = 'gpiodev'
        return
    except ImportError:
        pass

    # Try gpiod v2 API (class-based, capital C)
    try:
        import gpiod
        _chip = gpiod.Chip('gpiochip0')
        _gpiod_api = 'gpiod-v2'
        return
    except (ImportError, AttributeError):
        pass

    # Try gpiod v1 API (function-based, lowercase)
    try:
        import gpiod
        _chip = gpiod.chip('gpiochip0')
        _gpiod_api = 'gpiod-v1'
        return
    except (ImportError, AttributeError):
        pass

    raise ImportError(
        "No supported GPIOD library found. Install one of:\n"
        "  sudo apt install python3-gpiodev\n"
        "  pip install gpiod\n"
        "  pip install libgpiod"
    )


def _get_output_line(pin):
    """Configure and return a GPIOD output line handle."""
    if _gpiod_api == 'gpiodev':
        line = _chip.get_line(pin)
        line.set_direction_output(0)
        return line
    else:
        # gpiod v1/v2 class-based
        line = _chip.get_line(pin)
        req = {'shared': False, 'direction': 'out', 'consumer': 'waveshare_epd'}
        line.request(**req)
        return line


def _get_input_line(pin):
    """Configure and return a GPIOD input line handle."""
    if _gpiod_api == 'gpiodev':
        line = _chip.get_line(pin)
        line.set_direction_input()
        return line
    else:
        line = _chip.get_line(pin)
        req = {'shared': False, 'direction': 'in', 'consumer': 'waveshare_epd'}
        line.request(**req)
        return line


_gpiod_api = None


def module_init():
    """Initialize SPI and GPIO. Returns 0 on success."""
    global _chip, _line_rst, _line_dc, _line_busy, _line_cs

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
    global _chip, _line_rst, _line_dc, _line_busy, _line_cs
    for line in (_line_rst, _line_dc, _line_busy, _line_cs):
        try:
            if line is not None:
                line.release()
        except Exception:
            pass
    _line_rst = _line_dc = _line_busy = _line_cs = None
    _chip = None

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
    if _gpiod_api == 'gpiodev':
        line.set_value(bool(value))
    else:
        line.set_value(bool(value))


def digital_read(pin):
    """Read the value (0 or 1) from the specified GPIO pin."""
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
