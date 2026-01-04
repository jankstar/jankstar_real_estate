#!/usr/bin/env python3
# rebuild: 'python setup.py sdist bdist_wheel'
import io
import os
import re
from configparser import ConfigParser

from setuptools import find_packages, setup # type: ignore

MODULE2PREFIX = {}


def read(fname):
    content = io.open(
        os.path.join(os.path.dirname(__file__), fname),
        'r', encoding='utf-8').read()
    content = re.sub(
        r'(?m)^\.\. toctree::\r?\n((^$|^\s.*$)\r?\n)*', '', content)
    return content


def get_require_version(name):
    require = '%s >= %s.%s, < %s.%s'
    require %= (name, major_version, minor_version,
        major_version, minor_version + 1)
    return require


config = ConfigParser()
config.read_file(open(os.path.join(os.path.dirname(__file__), 'tryton.cfg')))
info = dict(config.items('tryton'))
for key in ('depends', 'extras_depend', 'xml'):
    if key in info:
        info[key] = info[key].strip().splitlines()
version = info.get('version', '0.0.1')
major_version, minor_version, _ = version.split('.', 2)
major_version = int(major_version)
minor_version = int(minor_version)
name = 'jankstar_real_estate'

requires = []
for dep in info.get('depends', []):
    if not re.match(r'(ir|res)(\W|$)', dep):
        prefix = MODULE2PREFIX.get(dep, 'trytond')
        requires.append(get_require_version('%s_%s' % (prefix, dep)))
requires.append(get_require_version('trytond'))

tests_require = []

setup(name=name,
    version=version,
    description='Real Estate Management',
    long_description=read('README.rst'),
    author='jankstar',
    author_email='jankstar.berlin@gmail.com',
    url='www.jankstar.de',
    keywords='Tryton',
    package_dir={'trytond.modules.real_estate': '.'},
    packages=(
        ['trytond.modules.real_estate']
        + ['trytond.modules.real_estate.%s' % p
            for p in find_packages()]
        ),
    package_data={
        'trytond.modules.real_estate': (info.get('xml', [])
            + ['tryton.cfg', 'view/*.xml', 'locale/*.po', '*.fodt',
                'icons/*.svg', 'tests/*.rst', 'tests/*.json']),
        },
    classifiers=[
        'Development Status :: 3 - Alpha', #5 - Production/Stable',
        'Environment :: Plugins',
        'Framework :: Tryton',
        'Intended Audience :: Developers',
        'Intended Audience :: Financial and Insurance Industry',
        'Intended Audience :: Legal Industry',
        'License :: OSI Approved :: '
        'GNU General Public License v3 or later (GPLv3+)',
        #'Natural Language :: Bulgarian',
        #'Natural Language :: Catalan',
        #'Natural Language :: Chinese (Simplified)',
        #'Natural Language :: Czech',
        #'Natural Language :: Dutch',
        'Natural Language :: English',
        #'Natural Language :: Finnish',
        #'Natural Language :: French',
        'Natural Language :: German',
        #'Natural Language :: Hungarian',
        #'Natural Language :: Indonesian',
        #'Natural Language :: Italian',
        #'Natural Language :: Persian',
        #'Natural Language :: Polish',
        #'Natural Language :: Portuguese (Brazilian)',
        #'Natural Language :: Romanian',
        #'Natural Language :: Russian',
        #'Natural Language :: Slovenian',
        #'Natural Language :: Spanish',
        #'Natural Language :: Turkish',
        #'Natural Language :: Ukrainian',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: Implementation :: CPython',
        'Topic :: Office/Business',
        ],
    license='GPL-3',
    python_requires='>=3.9',
    install_requires=requires,
    extras_require={
        'test': tests_require,
        },
    zip_safe=False,
    entry_points="""
    [trytond.modules]
    real_estate = trytond.modules.real_estate
    """,  # noqa: E501
    )
