from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import ImageDraw, ImageFont
import time
import subprocess

# Initialize I2C bus (port 1) and SSD1306 device with 64x32 resolution
serial = i2c(port=1, address=0x3C)
device = ssd1306(serial, width=64, height=32)

# --- fonts ---
try:
    font_small = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10
    )
except IOError:
    font_small = ImageFont.load_default()

try:
    font_large = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20
    )
except IOError:
    font_large = ImageFont.load_default()

# --- sensors: (label, table name) ---
SENSORS = [
    ("DNEV", "temp_dnevna"),
    ("DVOR", "temp_dvoriste"),
    ("SJEVR", "temp_sjever"),
]

# --- how long each sensor is shown, and how often to refetch ---
ROTATE_SECONDS = 10      # switch sensor every 10 s
POLL_SECONDS   = 30      # refresh DB every 30 s (per sensor fetch interval)

# --- build one mysql command per sensor ---
def make_cmd(table):
    return [
        "mysql",
        "-h", "192.168.0.42",
        "-u", "root",
        "--ssl-verify-server-cert=false",
        "-N", "-s",
        "-e", f"use brdovec; select timestamp, value from {table} order by timestamp desc limit 1;"
    ]

CMDS = {name: make_cmd(table) for name, table in SENSORS}

def fetch(name):
    """Return (ts_str, val_str) for a sensor, or defaults on failure."""
    try:
        result = subprocess.run(CMDS[name], capture_output=True, text=True, timeout=10)
        zone = result.stdout.strip()
        if not zone:
            return "--:--:--", "--"

        parts = zone.split('\t')
        if len(parts) != 2:
            return "--:--:--", "--"

        raw_ts, raw_value = parts

        # MySQL TIMESTAMP "YYYY-MM-DD HH:MM:SS" -> "HH:MM:SS"
        ts_str = raw_ts.split(" ")[1] if " " in raw_ts else raw_ts[-8:]

        # trim to 4 chars to fit nicely at font_large=20
        val_str = f"{raw_value}°"
        return ts_str, val_str

    except Exception:
        return "--:--:--", "--"

def draw_screen(label, ts_str, val_str):
    with canvas(device) as draw:
        # top row: label (left) + timestamp (right, small font)
        draw.text((0, 0), label, font=font_small, fill="white")

        # timestamp right-aligned in the small font
        ts_w = draw.textlength(ts_str, font=font_small)
        draw.text((device.width - ts_w, 0), ts_str, font=font_small, fill="white")

        # bottom row: big value, centered
        display = f"{val_str}C"
        v_w = draw.textlength(display, font=font_large)
        x = max(0, (device.width - v_w) // 2)
        draw.text((x, 11), display, font=font_large, fill="white")

print("OLED Temperature Monitor started (3 sensors).")

# cache last reading per sensor so we can rotate quickly without re-querying
cache = {name: ("--:--:--", "--") for name, _ in SENSORS}
last_fetch = 0.0
sensor_index = 0

try:
    while True:
        now = time.time()

        # refetch all sensors on the poll interval
        if now - last_fetch >= POLL_SECONDS:
            for name, _ in SENSORS:
                cache[name] = fetch(name)
            last_fetch = now

        # pick which sensor to show
        label, _ = SENSORS[sensor_index]
        ts_str, val_str = cache[label]

        draw_screen(label, ts_str, val_str)

        # advance rotation, sleep briefly so we can react to time changes
        time.sleep(ROTATE_SECONDS)
        sensor_index = (sensor_index + 1) % len(SENSORS)

except KeyboardInterrupt:
    print("\nStopping monitor. Clearing display...")
    with canvas(device) as draw:
        pass