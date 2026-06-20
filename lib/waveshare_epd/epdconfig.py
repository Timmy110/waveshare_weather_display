# *****************************************************************************
# * | File        :	  epdconfig.py
# * | Author      :   Waveshare team / adapted for weather dashboard
# * | Function    :   Hardware underlying interface (GPIO + SPI)
# * | Info        :
# *----------------
# * | This version:   V4.0
# * | Date        :   2019-06-22
# * | Info        :   python demo
# *****************************************************************************

import os
import sys
import time
import logging

logger = logging.getLogger(__name__)

# Raspberry Pi pin configuration (BCM numbering)
RST_PIN  = 17
DC_PIN   = 25
CS_PIN   = 8
BUSY_PIN = 24

# Global SPI handle
_spi = None


def digital_write(pin, value):
    """Write a digital value to a GPIO pin. Assumes GPIO is already set up."""
    import RPi.GPIO as GPIO
    GPIO.output(pin, value)


def digital_read(pin):
    """Read a digital value from a GPIO pin. Assumes GPIO is already set up."""
    import RPi.GPIO as GPIO
    return GPIO.input(pin)


def delay_ms(delay):
    """Delay for the specified number of milliseconds."""
    time.sleep(delay / 1000.0)


def spi_writebyte(data):
    """Write byte(s) to SPI bus (single-byte mode)."""
    global _spi
    if _spi is None:
        return
    _spi.writebytes(data)


def spi_writebyte2(data):
    """Write byte(s) to SPI bus (bulk mode, faster for large transfers)."""
    global _spi
    if _spi is None:
        return
    _spi.xfer2([0x00] + list(data))


def module_init():
    """
    Initialize GPIO and SPI.
    Returns 0 on success, -1 on failure.
    """
    global _spi
    try:
        import RPi.GPIO as GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(RST_PIN, GPIO.OUT)
        GPIO.setup(DC_PIN, GPIO.OUT)
        GPIO.setup(CS_PIN, GPIO.OUT)
        GPIO.setup(BUSY_PIN, GPIO.IN)

        import spidev
        _spi = spidev.SpiDev()
        _spi.open(0, 0)          # SPI bus 0, device 0 (CE0)
        _spi.max_speed_hz = 4000000  # 4 MHz — safe for e-paper
        logger.info("SPI + GPIO initialized successfully")
        return 0

    except ImportError as e:
        logger.error("Missing dependency for GPIO/SPI: %s", e)
        logger.error("Install with: pip3 install spidev RPi.GPIO")
        return -1

    except Exception as e:
        logger.error("Failed to initialize GPIO/SPI: %s", e)
        return -1


def module_exit(cleanup=False):
    """Clean up GPIO and SPI resources."""
    global _spi
    try:
        if _spi is not None:
            _spi.close()
            _spi = None
    except Exception:
        pass

    if cleanup:
        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup()
        except Exception:
            pass
