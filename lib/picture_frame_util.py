import os
import random
from PIL import Image, ImageDraw, ImageFont

##############################
## GLDS FILES
##############################

def load_random_glds_image():
    folder = "./lib/pic_frame_images/"
    files = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    if not files:
        print("No images found in", folder)
        return

    chosen_file = random.choice(files)
    file_path = os.path.join(folder, chosen_file)

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

    root_element = data["trias:Trias"]["trias:ServiceDelivery"]["trias:DeliveryPayload"]
    warnings = root_element["trias:TripResponse"]["trias:TripResponseContext"]["trias:Situations"]
    trip = root_element["trias:TripResponse"]["trias:TripResult"]["trias:Trip"]

    parts = [("hello", 0),(" -> ", 4),("world", 0)]
    draw_colored_text(draw, (10,10), parts)
    draw_colored_text(draw, (10,30), parts, 20)
    draw_colored_text(draw, (10,60), parts, 30)

    return image_to_glds_bytes(img)

def draw_colored_text(draw, origin, parts, fontsize = 10):
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