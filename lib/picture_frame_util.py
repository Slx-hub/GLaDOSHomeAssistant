import os
import random
from lib import kvv_response_parser
from PIL import Image, ImageDraw, ImageFont

import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

##############################
## GLDS FILES
##############################

def load_random_glds_image():
    folder = "./lib/pic_frame_images/"
    files = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    if not files:
        logger.info("No images found in %s" % folder)
        return

    chosen_file = random.choice(files)
    file_path = os.path.join(folder, chosen_file)

    with open(file_path, "rb") as f:
        return f.read()

def load_specific_glds_image():
    file_path = "./lib/pic_frame_images/glotz.glds"
    if not os.path.isfile(file_path):
        logger.info("No specific image found at %s" % file_path)
        return

    with open(file_path, "rb") as f:
        return f.read()

##############################
## IMAGE RENDERING
##############################

#                  0 Black    1 White    2 Green    3 Blue     4 Red      5 Yellow   6 Orange
palette_colors = ["#282828", "#E5E5E5", "#527743", "#545CCE", "#A04E4E", "#FFFF47", "#A8663A"]

def draw_info_screen(data):
    # Create blank image
    img = Image.new("RGB", (800, 480), palette_colors[1])
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"

    current_time = datetime.now().strftime("%d.%m.%y %H:%M")
    draw.text((580, 10), current_time, font_size=30, fill=palette_colors[0])

    y_cursor = draw_header(draw, "KVV", 10)

    try:
        y_cursor = draw_kvv_content(draw, data, y_cursor)
    except Exception as e:
        logger.info("Failed to render KVV view: %s" % e)
        draw.text((20, y_cursor), f"<!> Failed to render KVV view", font_size=20, fill=palette_colors[4])
        y_cursor += 25
    
    y_cursor = draw_header(draw, "Weather", y_cursor)

    try:
        y_cursor = draw_weather_content(draw, data, y_cursor)
    except Exception as e:
        logger.info("Failed to render Weather view: %s" % e)
        draw.text((20, y_cursor), f"<!> Failed to render Weather view", font_size=20, fill=palette_colors[4])
        y_cursor += 25

    return image_to_glds_bytes(img)

def draw_header(draw, text, y_cursor):
    draw.text((20, y_cursor), text, font_size=30, fill=palette_colors[4])
    y_cursor += 35
    draw.line([(10, y_cursor),(790,y_cursor)], width=4, fill=palette_colors[0])
    return y_cursor + 10

def draw_kvv_content(draw, data, y_cursor):
    if not kvv_response_parser.validate_kvv_response(data, draw):
        return y_cursor + 25

    root_element = data["kvv"]["trias:Trias"]["trias:ServiceDelivery"]["trias:DeliveryPayload"]
    warnings = root_element["trias:TripResponse"]["trias:TripResponseContext"]["trias:Situations"]
    trips = root_element["trias:TripResponse"]["trias:TripResult"]

    if warnings != None and warnings.get("trias:PtSituation") != None:
        pt_situation = warnings["trias:PtSituation"]
        warnings_list = pt_situation if isinstance(pt_situation, list) else [pt_situation]
        
        for warning in warnings_list:
            draw.text((20, y_cursor), "<! {0}> {1}".format(warning["siri:Description"],warning["siri:Summary"]), font_size=20, fill=palette_colors[4])
            y_cursor += 25

    for trip in trips:
        text_parts = kvv_response_parser.format_trip_for_display(trip)
        draw_colored_text(draw, (20,y_cursor), text_parts, 18)
        y_cursor += 25

    return y_cursor + 10

def draw_weather_content(draw, data, y_cursor):
    if "weather" not in data or not data["weather"]:
        draw.text((20, y_cursor), "No weather data received.", font_size=20, fill=palette_colors[5])
        return y_cursor + 25
    elif isinstance(data["weather"], str) and data["weather"].startswith("error:"):
        draw.text((20, y_cursor), f"<!> {data['weather']}", font_size=20, fill=palette_colors[4])
        return y_cursor + 25

    try:
        def draw_hour_block(draw, hour_data, x_pos, y_pos):
            # Convert Unix timestamp to hour:minute
            dt = datetime.fromtimestamp(hour_data["dt"])
            time_str = dt.strftime("%H:%M")
            
            # Draw time
            draw.text((x_pos, y_pos), time_str, font_size=20, fill=palette_colors[0])
            
            # Draw weather icon
            weather_icon = hour_data["weather"][0]["icon"][:2]
            icon = Image.open(f'./lib/weather_icons/{weather_icon}.png').convert('RGBA')
            # Get base image from draw object and paste icon
            draw._image.paste(icon, (x_pos + 2, y_pos + 25), icon)

            draw.text((x_pos, y_pos + 70), f" {round(hour_data['temp'])}°C", font_size=20, fill=palette_colors[0])
            
            # Draw precipitation if exists
            if "snow" in hour_data and "1h" in hour_data["snow"]:
                precip = f" {round(hour_data['snow']['1h'])}mm"
            elif "rain" in hour_data and "1h" in hour_data["rain"]:
                precip = f" {round(hour_data['rain']['1h'])}mm"
            else:
                precip = "     --"
            draw.text((x_pos, y_pos + 95), precip, font_size=20, fill=palette_colors[3])

        # Draw first 8 hourly entries
        hourly_data = data["weather"]["hourly"][0:15:2]
        block_width = 95  # Width for each hour block
        start_x = 40
        
        for i, hour_data in enumerate(hourly_data):
            x_pos = start_x + (i * block_width)
            draw_hour_block(draw, hour_data, x_pos, y_cursor)
            
        y_cursor += 90  # Total height of each block 

    except Exception as e:
        logger.info("Failed to render weather view: %s" % e)
        draw.text((20, y_cursor), f"<!> Failed to render weather view", font_size=20, fill=palette_colors[4])
        y_cursor += 25

    return y_cursor + 10

def draw_colored_text(draw, origin, parts, fontsize = 20):
    x = origin[0]
    y = origin[1]
    for text, color in parts:
        draw.text((x, y), text, font_size=fontsize, fill=palette_colors[color])
        # Measure width of this piece to offset the next
        x += draw.textlength(text, font_size=fontsize)

##############################
## RAW IMAGE TO GLDS FORMAT
##############################

def file_to_glds_bytes(file_path):
    return image_to_glds_bytes(Image.open(file_path).convert('RGB'))

def image_to_glds_bytes(image):
    buffer = bytearray()
    img_size = image.size
    img_pixels = image.load()
    
    for y in range(img_size[1]):
        for x in range(0, img_size[0], 2):
            try:
                byte = bytes.fromhex('{}{}'.format(get_color_index(img_pixels[x, y]), get_color_index(img_pixels[x + 1, y])))
                buffer.extend(byte)
            except Exception as e:
                raise Exception('Exception on pixel <{}, {}> with color {}'.format(x, y, img_pixels[x, y]), e)
    return buffer

def get_color_index(color):
    return str(palette_colors.index(to_hex_string(color)))

def to_hex_string(color):
    return '#%0.2X%0.2X%0.2X' % (color[0], color[1], color[2])