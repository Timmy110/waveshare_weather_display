import sys
import os
import logging

logger = logging.getLogger(__name__)

# Add lib directory to path so waveshare_epd can be imported
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

from PIL import Image


def init_display():
    """Initialize the Waveshare epd7in5b_V2 display. Returns the EPD instance."""
    try:
        from waveshare_epd.epd7in5b_V2 import EPD
        logger.info("Initializing epd7in5b_V2 display...")
        epd = EPD()
        if epd.init() != 0:
            logger.error("Failed to initialize display")
            return None
        # Clear screen on first init
        epd.Clear()
        logger.info("Display initialized successfully (800x480)")
        return epd
    except ImportError as e:
        logger.error("Could not import waveshare_epd library: %s", e)
        return None
    except Exception as e:
        logger.error("Display initialization error: %s", e)
        return None


def render_to_display(epd, black_img, red_img):
    """Send the black and red channel images to the e-paper display."""
    try:
        # Convert PIL 1-bit images to byte arrays for the driver
        buf_black = epd.getbuffer(black_img)
        buf_red = epd.getbuffer(red_img)
        epd.display(buf_black, buf_red)
        logger.info("Frame sent to display")
    except Exception as e:
        logger.error("Failed to render to display: %s", e)


def create_blank_images():
    """Create blank white images for black and red channels."""
    WIDTH, HEIGHT = 800, 480
    img_black = Image.new("1", (WIDTH, HEIGHT), 1)  # 1 = white in 1-bit mode
    img_red = Image.new("1", (WIDTH, HEIGHT), 1)
    return img_black, img_red
