# *****************************************************************************
# * | File        :	  epdconfig.py
# * | Author      :   Waveshare team
# * | Function    :   EPDBUS config module for Raspberry Pi
# * | Info        :
# -----------------------------------------------------------------------------

import os
import sys
import time
import subprocess

# Global constants
RST_PIN = 17
DC_PIN = 25
BUSY_PIN = 17
CS_PIN = 8

def module_init():
    """Initialize SPI and GPIO. Returns 0 on success."""
    global BUSY_PIN, RST_PIN, DC_PIN, CS_PIN
    
    try:
        import spidev
        global SPI
        SPI = spidev.SpiDev()
        SPI.open(0, 0)
        SPI.max_speed_hz = 4000000
        SPI.mode = 0b00
    except Exception as e:
        print("SPI init failed:", e)
        return -1

    try:
        import gpiozero
        global gpiozero_module
        gpiozero_module = gpiozero
    except ImportError:
        print("gpiozero not available, using fallback GPIO")
        return 0
    
    return 0

def module_exit():
    """Clean up SPI and GPIO."""
    try:
        SPI.close()
    except Exception:
        pass

def digital_write(pin, value):
    if 'gpiozero_module' in globals():
        from gpiozero import OutputDevice
        pin_obj = OutputDevice(pin)
        pin_obj.on() if value else pin_obj.off()
    else:
        print("[WARN] No GPIO available (running on non-Pi host)")

def digital_read(pin):
    if 'gpiozero_module' in globals():
        from gpiozero import InputDevice
        pin_obj = InputDevice(pin)
        return not pin_obj.is_active
    return 1  # Busy = not busy when emulated

def delay_ms(delay):
    time.sleep(delay / 1000.0)

def spi_writebyte(data):
    SPI.writebytes(data)

def spi_writebyte2(data):
    SPI.writebytes2(data if hasattr(SPI, 'writebytes2') else list(data))
