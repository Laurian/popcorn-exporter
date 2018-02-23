import sys
import json
import time
import re
import subprocess
import os
import os.path
import moviepy.editor as mpy
import requests
import shutil
import hashlib
from hashids import Hashids
from goldfinch import validFileName as vfn


'''
IMPORT NOTES
1) there are some bugs in moviepy that you need to fix before this works
change line 894 in moviepy/video/VideoClip.py to:
    if isinstance(img, str) or isinstance(img, unicode):

change line 32 in moviepy/video/fx/resize.py to:
    arr = np.fromstring(resized_pil.tobytes(), dtype='uint8')

2) Install imagemagick and make the fonts in the 'fonts' directory
available to it. You should see them by running convert -list font
'''

# all video output is 720p
WIDTH = 1280
HEIGHT = 720


def filename_from_url(url):
    ''' Converts a url into a friendlier file name'''

    # return 'cache/' + re.sub(r'://|/', '_', url)
    # convert to hash (md5) to avoid looooongcat urls causing FS failures if filename is 'too long' (255 chars is not uncommon)
    return 'cache/' + hashlib.md5(vfn(url)).hexdigest()


def download_video(url):
    '''Downloads videos using youtube-dl'''

    filename = filename_from_url(url)
    if filename.endswith('.mp4') is False:
        filename += '.mp4'

    if os.path.exists(filename):
        return filename

    args = ['youtube-dl', '--recode-video', 'mp4', '-o', filename, '-q', url]

    try:
        subprocess.check_output(args)
        if os.path.exists(filename):
            return filename
        else:
            filename += '.mp4'
            return filename
    except Exception as e:
        return None


def download_file(url):
    '''Downloads any file type using requests'''

    filename = filename_from_url(url)
    if os.path.exists(filename):
        return filename

    try:
        r = requests.get(url, stream=True)
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
        return filename
    except:
        return None


def download_asset(url):
    '''Attempts to download either a video or image asset'''

    print 'URL', url

    ext = url.split('.')[-1].lower()
    if ext in ['jpeg', 'jpg', 'gif', 'png', 'svg']:
        filename = download_file(url)
    else:
        filename = download_video(url)

    return filename


def get_dimensions(options):
    '''
    Returns dimensions from a popcorn options dict.
    Note that popcorn calculates dimensions in percentage rather than pixels.
    '''

    width = int(float(options['width'])/100 * WIDTH)
    height = int(float(options['height'])/100 * HEIGHT)
    x = int(float(options['left'])/100 * WIDTH)
    y = int(float(options['top'])/100 * HEIGHT)

    return (width, height, x, y)


def create_clip(cliptype, options):
    '''
    Creates a moviepy clip.
    Output will either by a VideoFileClip, TextClip, or ImageClip
    '''

    if cliptype == 'sequencer':
        source_url = options['source']
        if isinstance(source_url, list):
            source_url = source_url[0]

        source = download_asset(source_url)
        clip = mpy.VideoFileClip(source)

        global_start = float(options['start'])
        global_end = float(options['end'])
        duration = global_end - global_start
        clip_length = float(options['duration'])
        subclip_start = float(options['from'])
        subclip_end = subclip_start + duration

        # hack to prevent moviepy error when trying to make a subclip that's too long
        if subclip_end >= clip_length:
            subclip_end = duration - .01

        clip = clip.subclip(subclip_start, subclip_end).set_start(global_start)

        width, height, x, y = get_dimensions(options)
        clip = clip.resize((width, height)).set_pos((x, y))

        print subclip_start, subclip_end, global_start, global_end
        print width, height, x, y
        print ''

        return clip

    elif cliptype == 'image':
        source = download_file(options["src"])
        global_start = float(options['start'])
        global_end = float(options['end'])
        duration = global_end - global_start

        width, height, x, y = get_dimensions(options)
        if width == 0:
            width = 1
        if height == 0:
            height = 1

        ext = source.split('.')[-1].lower()
        if ext in ['svg']:
            source = "http://www.msss.com/moc_gallery/broken_icon.jpg"

        clip = mpy.ImageClip(source).set_duration(duration).set_start(global_start)
        clip = clip.resize((width, height)).set_pos((x, y))

        return clip

    elif cliptype == 'text':
        global_start = float(options['start'])
        global_end = float(options['end'])
        duration = global_end - global_start
        font = options['fontFamily']
        alignment = {'left': 'NorthWest', 'center': 'center', 'right': 'NorthEast'}[options['alignment']]

        text = options['text'].encode('utf-8')
        options['height'] = int(options['fontSize'])
        width, height, x, y = get_dimensions(options)
        if not alignment == 'center':
            height = HEIGHT - y

        clip = mpy.TextClip(
            txt=text,
            size=(width, height),
            method='caption',
            color=options['fontColor'],
            align=alignment,
            font=font,
            fontsize= HEIGHT * int(options['fontSize']) / 100
        )

        clip = clip.set_duration(duration).set_start(global_start).set_pos((x, y))

        return clip

    return None


def convert(data, outfile='composition.mp4'):
    '''Converts popcorn track list into an mp4'''

    clips = []

    # generate background color clip
    # convert hex color from popcorn to an RGB tuple
    bg_color = data.get('backgroundColor', '#000000').lstrip('#')
    bg_color = tuple(int(bg_color[i:i+2], 16) for i in (0, 2, 4))
    total_duration = float(data['duration'])
    background_clip = mpy.ColorClip(size=(WIDTH, HEIGHT), col=bg_color).set_duration(total_duration)
    clips.append(background_clip)

    # generate moviepy clips from popcorn options
    tracks = sorted(data['tracks'], key=lambda k: k['order'], reverse=True)
    for track in tracks:
        for event in track['trackEvents']:
            clip = create_clip(event['type'], event['popcornOptions'])
            clips.append(clip)

    # ignore track events that create_clip can't handle
    clips = [c for c in clips if c is not None]

    # composite the video
    video = mpy.CompositeVideoClip(clips, size=(1280, 720))

    tmpoutfile = outfile + '.temp.mp4'

    video.write_videofile(
        tmpoutfile,
        fps=24,
        codec='libx264',
        audio_codec='aac',
        temp_audiofile='temp-audio.m4a',
        remove_temp=True
    )

    shutil.move(tmpoutfile, outfile)

    return outfile


if __name__ == '__main__':
    with open(sys.argv[1], 'rb') as infile:
        data = json.load(infile)

        if 'media' in data:
            if 'background' in data:
                data['media'][0]['backgroundColor'] = data['background']

            data = data['media'][0]

        lastEnd = 0
        for t in data['tracks']:
            for e in t['trackEvents']:
                lastEnd = max(lastEnd, e['popcornOptions']['end'])

        if lastEnd == 0:
            lastEnd = data['duration']

        data['duration'] = lastEnd

        convert(data, outfile=sys.argv[2])
