#!/usr/bin/env python

import re
import os
from subprocess import check_call

from setuptools import setup, find_packages, Command
from setuptools.command.sdist import sdist


cmdclass = {}


try:
    from pyqt_distutils.build_ui import build_ui
    has_build_ui = True
except ImportError:
    has_build_ui = False


with open('app/__init__.py') as f:
    _version = re.search(r'__version__\s+=\s+\'(.*)\'', f.read()).group(1)


if has_build_ui:
    class build_res(build_ui):
        """Build UI and resources."""

        def run(self):
            # build UI & resources
            build_ui.run(self)

    cmdclass['build_res'] = build_res


class custom_sdist(sdist):
    """Custom sdist command."""

    def run(self):
        self.run_command('build_res')
        sdist.run(self)


cmdclass['sdist'] = custom_sdist


class bdist_app(Command):
    """Custom command to build the application. """

    description = 'Build the application'
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        self.run_command('build_res')
        check_call(['pyinstaller', '-y', 'app.spec'])


cmdclass['bdist_app'] = bdist_app


setup(name='app',
      version=_version,
      packages=find_packages(),
      description='Automated Drone Image Analysis Tool',
      author='Charlie Grove',
      author_email='charlie.grove@texsar.org',
      license=' AGPL-3.0',
      url='https://www.texsar.org',
      entry_points={
          'gui_scripts': ['app=app.__main__:main'],
      },
      cmdclass=cmdclass)
