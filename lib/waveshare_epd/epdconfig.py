# *****************************************************************************
# * | File        :	  epdconfig.py
# * | Author      :   Waveshare electronics
# * | Function    :   Hardware underlying interfaces
# * | Info        :
# *                Used to drive the e-paper display via SPI on Raspberry Pi.
# *                Adapted from Waveshare official library.
# *****************************************************************************
import time
import os
import ctypes


# Pin configuration for Waveshare 7.5" E-Paper HAT (B) V2
RST_PIN = 17
DC_PIN = 25
BUSY_PIN = 24
CS_PIN = 8


def module_init():
    """Initialize SPI and GPIO. Returns 0 on success."""
    global GPIO, SPI

    # Initialize GPIO using RPi.GPIO
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    
    GPIO.setup(RST_PIN, GPIO.OUT)
    GPIO.setup(DC_PIN, GPIO.OUT)
    GPIO.setup(BUSY_PIN, GPIO.IN)
    GPIO.setup(CS_PIN, GPIO.OUT)

    # Initialize SPI
    import spidev
    SPI = spidev.SpiDev()
    SPI.open(0, 0)
    SPI.max_speed_hz = 4000000
    SPI.mode = 0b00
    
    return 0


def module_exit(cleanup=False):
    """Clean up GPIO and SPI."""
    try:
        import RPi.GPIO as GPIO
        if cleanup:
            GPIO.cleanup()
    except Exception:
        pass
    try:
        SPI.close()
    except Exception:
        pass


def digital_write(pin, value):
    import RPi.GPIO as GPIO
    GPIO.output(pin, value)


def digital_read(pin):
    import RPi.GPIO as GPIO
    return GPIO.input(pin)


def delay_ms(delay):
    time.sleep(delay / 1000.0)


def spi_writebyte(data):
    SPI.writebytes(data)


def spi_writebyte2(data):
    SPI.writebytes2(data if hasattr(SPI, 'writebytes2') else bytes(data))
