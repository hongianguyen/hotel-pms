# -*- coding: utf-8 -*-
"""Fill the booking page's room content (text + photos) in Odoo.

Run inside `odoo-bin shell`, with PHOTO_DIR pointing at the folder
fetch_photos.py wrote and CONTENT at room_content.json:

    PHOTO_DIR=/root/room_photos CONTENT=/root/room_content.json \
        odoo-bin shell -c <conf> -d <db> --no-http < load_room_content.py

Re-runnable: each run replaces the photos and text of the room types it
names and leaves every other room type alone. Room types are matched by
their exact English name.
"""
import base64
import glob
import json
import os

photo_dir = os.environ['PHOTO_DIR']
content = json.load(open(os.environ['CONTENT'], encoding='utf-8'))
RoomType = env['hotel.room.type'].with_context(lang='en_US')

for type_name, spec in content.items():
    if type_name.startswith('_'):
        continue
    room_type = RoomType.search([('name', '=', type_name)], limit=1)
    if not room_type:
        print('SKIP: no room type named %r' % type_name)
        continue
    room_type.write({
        'web_summary': spec['summary'],
        'web_description': spec['description'],
        'web_facilities': spec['facilities'],
        'web_beds': spec['beds'],
        'web_size': spec['size'],
        'web_view': spec['view'],
    })
    room_type.web_image_ids.unlink()
    images = []
    for seq, ref in enumerate(spec['photos'], 1):
        matches = glob.glob(os.path.join(photo_dir, ref + '.*'))
        if not matches:
            print('  missing photo %s' % ref)
            continue
        with open(matches[0], 'rb') as f:
            images.append({
                'room_type_id': room_type.id,
                'sequence': seq * 10,
                'image_1920': base64.b64encode(f.read()),
            })
    env['lak.room.type.image'].create(images)
    print('%s: text + %d photos' % (type_name, len(images)))

env.cr.commit()
