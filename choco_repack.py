#!/usr/bin/env python3
# coding: utf-8
# Author: Park Lam<lqmonline@gmail.com>

from decouple import config
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import os
import subprocess
import argparse
import re
import tempfile
import zipfile
import wget
import shutil

CHOCO_REPOS_ENDPOINT = 'https://chocolatey.org/api/v2/package/'
CHOCO_REPOS_LOCAL = '\\\\{0}\choco_repos'.format(config('COMPUTERNAME'))

def download_nuget_file(pkg_name, save_to, version=None):
    pkg_endpoint_url = '/'.join(s.strip('/') for s in \
            [ CHOCO_REPOS_ENDPOINT, pkg_name, version or ''])
    print('Download: {}'.format(pkg_endpoint_url))
    filename = wget.download(pkg_endpoint_url, out=os.path.join(save_to, 'origin.nuget'))
    print('\n')
    return os.path.join(save_to, filename)

def unzip_nuget_file(nuget_file, extract_to):
    print('Extract: {}'.format(nuget_file))
    print('To: {}'.format(extract_to))
    with zipfile.ZipFile(nuget_file, 'r') as zip_file:
        zip_file.extractall(extract_to)

def read_nuspec(pkg_dir):
    pkg_name, pkg_version, pkg_dependencies = None, None, []
    for f in os.listdir(pkg_dir):
        if f.endswith('.nuspec'):
            filename = os.path.join(pkg_dir, f)
            tree = ET.parse(filename)
            root = tree.getroot()
            ns = root.tag.split('}').pop(0).strip('{')
            pkg_name = list(root)[0].find('{%s}id' % ns).text
            pkg_version = list(root)[0].find('{%s}version' % ns).text
            pkg_dependencies = [ i.attrib for i in list(list(root)[0].find('{%s}dependencies' % ns) or [ ]) ]
            break
    return pkg_name, pkg_version, pkg_dependencies

def is_pkg_exists(base_dir, pkg_name, pkg_version):
    return os.path.exists(os.path.join(base_dir, '{}.{}.nupkg'.format(pkg_name, pkg_version)))

def prepare_pack(pkg_dir, save_to):
    try:
        shutil.rmtree(os.path.join(pkg_dir, '_rels'))
        shutil.rmtree(os.path.join(pkg_dir, 'package'))
        os.remove(os.path.join(pkg_dir, '[Content_Types].xml'))
    except Exception as e:
        print(e)

    tools_dir = os.path.join(pkg_dir, 'tools')
    download_dir = os.path.join(save_to, 'downloads')
    if not os.path.exists(download_dir):
        os.mkdir(download_dir)

    if os.path.exists(tools_dir):
        for fn in os.listdir(tools_dir):
            if fn.lower().endswith('.ps1'):
                with open(os.path.join(tools_dir, fn), 'r', encoding='utf-8') as in_file, \
                        open(os.path.join(tools_dir, 'tmp.ps1'), 'w', encoding='utf-8') as out_file:
                    for line in in_file.readlines():
                        if 'https://' in line or 'http://' in line:
                            re_pattern = re.compile('[\'\"]http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\), ]|(?:%[0-9a-fA-F][0-9a-fA-F]))+[\'\"]')
                            re_result = re_pattern.search(line)
                            if re_result:
                                url = urlparse(re_result[0].strip("'").strip('"'))
                                filename = os.path.basename(url.path)
                                if os.path.exists(os.path.join(download_dir, filename)):
                                    print('File exists: {}.'.format(filename))
                                else:
                                    try:
                                        print('Download start: {}'.format(url.geturl()))
                                        filename = os.path.basename(wget.download(url.geturl(), out=download_dir))
                                        print('\n')
                                    except Exception as e:
                                        print('Download failed: {}'.format(url.geturl()))
                                        raise e
                                out_file.write(line.replace(re_result[0], \
                                        os.path.join(download_dir, filename)))
                        else:
                            out_file.write(line)
                shutil.move(os.path.join(tools_dir, 'tmp.ps1'), os.path.join(tools_dir, fn))
    else:
        print('WARN: Directory "tools/" is not exists in package.')
        #raise Exception('directory "{}" is not found in package'.format(tools_dir))

def do_pack(pkg_dir, save_to):
    pkg_name, pkg_version, pkg_dependencies = read_nuspec(pkg_dir)
    pack_cmd = 'choco pack {pkg_dir}\\{pkg_name}.nuspec --out {output_dir}'.format(
            pkg_dir=pkg_dir, pkg_name=pkg_name, output_dir=save_to)
    #print('Execute command: {}'.format(pack_cmd))
    exec_result = subprocess.call(pack_cmd)

def repack_pkg(pkg_name, save_to, version=None):
    print('--> Start pack [{}]'.format(pkg_name))
    if version and os.path.exists(os.path.join(save_to, '{}.{}.nupkg'.format(pkg_name, version))):
        print('Pakcage "{}.{}.nupkg" already exists. Exit...'.format(pkg_name, version))
        return

    pkg_dir = tempfile.mkdtemp()
    download_dir = tempfile.mkdtemp()

    download_file = download_nuget_file(pkg_name, save_to=download_dir)

    unzip_nuget_file(download_file, pkg_dir)

    pkg_name, pkg_version, pkg_dependencies = read_nuspec(pkg_dir)
    if is_pkg_exists(save_to, pkg_name, pkg_version):
        print('Package exists: {}.{}.nupkg.'.format(pkg_name, pkg_version))
    elif '.extension' in pkg_name:
        shutil.copyfile(download_file, os.path.join(save_to, '{}.{}.nupkg'.format(pkg_name, pkg_version)))
        print('Package downloaded: {}.{}.nupkg'.format(pkg_name, pkg_version))
    else:
        prepare_pack(pkg_dir, save_to=save_to)
        do_pack(pkg_dir, save_to=save_to)
        print('Package packed: {}.{}.nupkg'.format(pkg_name, pkg_version))

    if pkg_dependencies:
        for pkg in pkg_dependencies:
            repack_pkg(pkg['id'], save_to, version=(None if 'version' not in pkg \
                    else pkg['version'].strip('[').strip(']')))

    print('--> {} is packed.'.format(pkg_name))

if __name__ == '__main__':
    '''
    Usage: choco_repack googlechrome
    '''
    parser = argparse.ArgumentParser(description='Repack chocolatey package for internal use.')
    parser.add_argument('-n', '--name', nargs='+', required=True, \
            dest='pkgs', help='Package(s) to repack. Support syntax "googlechrome"')
    parser.add_argument('-o', '--output', required=False, dest='output_dir', \
            help='Directory to save .nuget files. Default save to current dir')
    args = parser.parse_args()

    if not args.output_dir:
        output_dir = config('CHOCO_REPOS_LOCAL', default=CHOCO_REPOS_LOCAL)
    else:
        output_dir = args.output_dir

    for pkg in args.pkgs:
        if '==' in pkg:
            pkg_name, pkg_version = pkg.split('==')
        else:
            pkg_name = pkg
            pkg_version = None
        repack_pkg(pkg_name, save_to=output_dir, version=pkg_version)
