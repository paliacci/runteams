"""Open3D's server-side representative color, using the same libvips pipeline."""
import math
from collections import Counter


def _resize(vips, data, kind, limit, kernel):
    image = vips.Image.new_from_buffer(data, '', access='sequential', fail_on='warning')
    shrink = max(image.width, image.height) / limit
    if kind == 'jpeg':
        factor = next((value for value in (8, 4, 2) if shrink >= value), 1)
        if factor > 1 and int(shrink) == factor:
            factor //= 2
        if factor > 1:
            image = vips.Image.jpegload_buffer(data, shrink=factor, access='sequential', fail_on='warning')
    elif kind == 'webp' and shrink > 1:
        image = vips.Image.webpload_buffer(data, scale=1 / shrink, access='sequential', fail_on='warning')

    interpretation = image.interpretation
    profile = 'p3' if interpretation == 'rgb16' else 'srgb'
    if image.get_typeof('icc-profile-data') and interpretation not in ('labs', 'grey16'):
        try:
            image = image.icc_transform(profile, embedded=True, depth=16 if interpretation == 'rgb16' else 8,
                                        intent='perceptual')
        except vips.Error:
            pass  # Sharp retains the original pixels when an embedded profile is invalid.
    elif interpretation == 'cmyk':
        image = image.icc_transform(profile, input_profile='cmyk', intent='perceptual')

    shrink = max(image.width, image.height) / limit
    if shrink > 1:
        alpha, pixel_format = image.hasalpha(), image.format
        if alpha:
            image = image.premultiply().cast(pixel_format)
        image = image.resize(1 / shrink, kernel=kernel)
        if alpha:
            image = image.unpremultiply().cast(pixel_format)
    return image.colourspace('srgb')


def _distance(a, b):
    red, green, blue = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return red * red + green * green + blue * blue


def _nearest(pixel, centroids):
    best, distance = 0, _distance(pixel, centroids[0])
    for index in range(1, len(centroids)):
        candidate = _distance(pixel, centroids[index])
        if candidate < distance:
            best, distance = index, candidate
    return best


def _clusters(pixels):
    step = max(1, len(pixels) // 4)
    centroids = [pixels[min(index * step, len(pixels) - 1)] for index in range(4)]
    for _ in range(50):
        totals = [[0, 0, 0, 0] for _ in centroids]
        for pixel in pixels:
            entry = totals[_nearest(pixel, centroids)]
            entry[0] += pixel[0]
            entry[1] += pixel[1]
            entry[2] += pixel[2]
            entry[3] += 1
        updated = [tuple(math.floor(channel / count + 0.5) for channel in (red, green, blue)) if count else centroid
                   for centroid, (red, green, blue, count) in zip(centroids, totals)]
        if updated == centroids:
            break
        centroids = updated
    return centroids


def _hsl(red, green, blue):
    high, low = max(red, green, blue), min(red, green, blue)
    light = (high + low) / 2
    if high == low:
        return 0, 0, light
    delta = high - low
    saturation = delta / (high + low) if light < 0.5 else delta / (2 - high - low)
    if high == red:
        hue = (green - blue) / delta + (6 if green < blue else 0)
    elif high == green:
        hue = (blue - red) / delta + 2
    else:
        hue = (red - green) / delta + 4
    return hue / 6, saturation, light


def _rgb(hue, saturation, light):
    if saturation == 0:
        return (math.floor(light * 255 + 0.5),) * 3
    high = light * (1 + saturation) if light < 0.5 else light + saturation - light * saturation
    low = 2 * light - high

    def channel(value):
        if value < 0:
            value += 1
        if value > 1:
            value -= 1
        if value < 1 / 6:
            return low + (high - low) * 6 * value
        if value < 1 / 2:
            return high
        if value < 2 / 3:
            return low + (high - low) * (2 / 3 - value) * 6
        return low

    return tuple(math.floor(channel(value) * 255 + 0.5) for value in (hue + 1 / 3, hue, hue - 1 / 3))


def _adjust(color):
    hue, saturation, light = _hsl(*(channel / 255 for channel in color))
    if light > 0.6:
        light = max(0.4, light - max(0.05, 0.2 - saturation * 0.3))
    elif light < 0.4:
        light = 0.4
    saturation = min(0.62, saturation * 1.5)
    result = _rgb(hue, saturation, light)
    adjusted_light = _hsl(*(channel / 255 for channel in result))[2]
    while light > 0.35 and 1.05 / (adjusted_light + 0.05) < 2.2:
        light -= 0.02
        result = _rgb(hue, saturation, light)
        adjusted_light = _hsl(*(channel / 255 for channel in result))[2]
    return result


def representative_color(data, kind):
    """Take validated static image bytes and return Open3D's RGB triple."""
    try:
        import pyvips as vips
    except (ImportError, OSError):
        return None
    try:
        image = _resize(vips, data, kind, 300, 'lanczos3')
        jpeg = image.jpegsave_buffer(Q=75, interlace=False, subsample_mode='on', optimize_coding=True, keep='none')
        raw = bytes(vips.Image.new_from_buffer(jpeg, '', access='sequential').colourspace('srgb').write_to_memory())
        sampled = bytes(_resize(vips, jpeg, 'jpeg', 256, 'nearest').write_to_memory())
    except vips.Error:
        return None
    if not sampled:
        return None

    centroids = _clusters(list(zip(sampled[::30], sampled[1::30], sampled[2::30])))
    counts = Counter(centroids[_nearest(pixel, centroids)] for pixel in zip(raw[::3], raw[1::3], raw[2::3]))
    candidates = {color: count for color, count in counts.items() if count >= 100}
    if not candidates:
        return None
    total = sum(candidates.values())

    def score(color):
        _, saturation, light = _hsl(*(channel * 257 / 65535 for channel in color))
        return candidates[color] / total * 100 * 0.1 + saturation * 100 * 0.4 + (1 - abs(light - 0.5)) * 100 * 0.4 + 10

    return _adjust(max(candidates, key=score))
