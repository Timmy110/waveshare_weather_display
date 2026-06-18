# *****************************************************************************
# * | File        :   epdconfig.py
# * | Author      :   Waveshare electronics (modified for gpiozero)
# * | Function    :   Hardware underlying interfaces
# * | Info        :
# *                Used to drive the e-paper display via SPI on Raspberry Pi.
# *                Adapted from Waveshare official library.
# *                Modified: Replaced RPi.GPIO with gpiozero for compatibility
# *                with Debian 12+ (Bookworm/Trixie) where sysfs GPIO is gone.
# *****************************************************************************
import time
import os


# Pin configuration for Waveshare 7.5" E-Paper HAT (B) V2
RST_PIN = 17
DC_PIN = 25
BUSY_PIN = 24
CS_PIN = 8

# GPIO handles (set during module_init)
_gpio_rst = None
_gpio_dc = None
_gpio_busy = None
SPI = None


def module_init():
    """Initialize SPI and GPIO. Returns 0 on success."""
    global _gpio_rst, _gpio_dc, _gpio_busy, SPI

    from gpiozero import OutputDevice, InputDevice

    _gpio_rst = OutputDevice(RST_PIN)
    _gpio_dc = OutputDevice(DC_PIN)
    _gpio_busy = InputDevice(BUSY_PIN)
    # NOTE: CS is handled by the hardware SPI driver (spidev), so we do not
    # manually claim GPIO 8 here. gpiozero cannot share a pin already owned by
    # the kernel SPI driver, which would raise "GPIO busy".

    # Initialize SPI
    import spidev
    SPI = spidev.SpiDev()
    SPI.open(0, 0)
    SPI.max_speed_hz = 4000000
    SPI.mode = 0b00

    return 0


def module_exit(cleanup=False):
    """Clean up GPIO and SPI."""
    global _gpio_rst, _gpio_dc, _gpio_busy, SPI

    for gpio in (_gpio_rst, _gpio_dc, _gpio_busy):
        try:
            if gpio is not None:
                gpio.close()
        except Exception:
            pass
    _gpio_rst = _gpio_dc = _gpio_busy = None

    try:
        if SPI is not None:
            SPI.close()
    except Exception:
        pass


def digital_write(pin, value):
    """Write a value (0 or 1) to the specified GPIO pin."""
    # CS_PIN is handled by hardware SPI; no manual control needed.
    if pin == CS_PIN:
        return
    line_map = {RST_PIN: _gpio_rst, DC_PIN: _gpio_dc}
    gpio = line_map.get(pin)
    if gpio is None:
        raise ValueError(f"Pin {pin} is not configured as output")
    gpio.value = bool(value)


def digital_read(pin):
    """Read the value (0 or 1) from the specified GPIO pin."""
    if pin == BUSY_PIN and _gpio_busy is not None:
        return _gpio_busy.value
    raise ValueError(f"Pin {pin} is not configured as input")


def delay_ms(delay):
    time.sleep(delay / 1000.0)


def spi_writebyte(data):
    global SPI
    SPI.writebytes(data)


def spi_writebyte2(data):
    global SPI
    SPI.writebytes2(data if hasattr(SPI, 'writebytes2') else bytes(data))