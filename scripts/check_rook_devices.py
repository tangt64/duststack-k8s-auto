"""Read-only validation of explicitly selected fresh Ceph disks (Python 3.9+)."""
import json
import os
import re
import stat
import subprocess
import sys


def validate_device(name, run=subprocess.run, inspect=os.stat):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('Only a block-device basename is accepted')
    path = '/dev/' + name
    info = inspect(path)
    if not stat.S_ISBLK(info.st_mode):
        raise ValueError(path + ' is not a block device')
    output = run(['lsblk', '--json', '--bytes', '--output', 'NAME,PATH,TYPE,FSTYPE,MOUNTPOINTS,SIZE', path], check=True, capture_output=True, text=True)
    nodes = json.loads(output.stdout)['blockdevices']
    if len(nodes) != 1:
        raise ValueError(path + ' did not resolve to exactly one disk')
    disk = nodes[0]
    if disk['type'] != 'disk' or disk.get('children') or disk.get('fstype') or any(disk.get('mountpoints') or []):
        raise ValueError(path + ' is mounted, partitioned or contains a filesystem')
    if int(disk['size']) < 20 * 1024 ** 3:
        raise ValueError(path + ' is smaller than 20 GiB')
    output = run(['wipefs', '--no-act', '--json', path], check=True, capture_output=True, text=True)
    if json.loads(output.stdout).get('signatures'):
        raise ValueError(path + ' contains existing storage signatures')
    return {'device': name, 'bytes': int(disk['size']), 'device_id': info.st_rdev}


def main():
    if not sys.argv[1:]:
        raise SystemExit('Explicit device names required')
    checked = [validate_device(name) for name in sys.argv[1:]]
    if len({item['device_id'] for item in checked}) != len(checked):
        raise SystemExit('Duplicate physical devices')
    print(json.dumps({'verified_empty_disks': checked}))


if __name__ == '__main__':
    main()
