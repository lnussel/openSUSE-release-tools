#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2017 SUSE LLC
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from xml.etree import cElementTree as ET
import sys
import cmdln
import logging
import urllib2
import osc.core

import ToolBase

makeurl = osc.core.makeurl

logger = logging.getLogger()

FACTORY = "openSUSE:Factory"

class Freezer(ToolBase.ToolBase):

    def __init__(self, project):
        ToolBase.ToolBase.__init__(self)
        self.project = project
        self.packages = []

        self.set_links()

    def set_links(self):
        url = self.makeurl(['source', self.project, '_meta'])
        f = self.retried_GET(url)
        root = ET.parse(f).getroot()
        links = root.findall('link')
        links.reverse()
        self.projectlinks = [link.get('project') for link in links]
        logger.debug("links %s", self.projectlinks)

    def freeze_prjlinks(self):
        sources = {}
        flink = ET.Element('frozenlinks')

        for lprj in self.projectlinks:
            fl = ET.SubElement(flink, 'frozenlink', {'project': lprj})
            sources = self.receive_sources(lprj, sources, fl)

        url = self.api.makeurl(['source', self.prj, '_project', '_frozenlinks'], {'meta': '1'})
        self.api.retried_PUT(url, ET.tostring(flink))

    def receive_sources(self, prj, sources, flink):
        url = self.api.makeurl(['source', prj], {'view': 'info', 'nofilename': '1'})
        f = self.api.retried_GET(url)
        root = ET.parse(f).getroot()

        for si in root.findall('sourceinfo'):
            package = self.check_one_source(flink, si)
            sources[package] = 1
        return sources

    def check_one_source(self, flink, si):
        package = si.get('package')

        # If the package is an internal one (e.g _product)
        if package.startswith('_'):
            return None

        # Ignore packages with an origing (i.e. with an origin
        # different from the current project)
        if si.find('originproject') != None:
            return None

        # we have to check if its a link within the staging project
        # in this case we need to keep the link as is, and not freezing
        # the target. Otherwise putting kernel-source into staging prj
        # won't get updated kernel-default (and many other cases)
        for linked in si.findall('linked'):
            if linked.get('project') in self.projectlinks:
                # take the unexpanded md5 from Factory / 13.2 link
                url = self.api.makeurl(['source', self.api.project, package],
                                       {'view': 'info', 'nofilename': '1'})
                # print(package, linked.get('package'), linked.get('project'))
                f = self.api.retried_GET(url)
                proot = ET.parse(f).getroot()
                lsrcmd5 = proot.get('lsrcmd5')
                if lsrcmd5 is None:
                    raise Exception("{}/{} is not a link but we expected one".format(self.api.project, package))
                ET.SubElement(flink, 'package', {'name': package, 'srcmd5': lsrcmd5, 'vrev': si.get('vrev')})
                return package
        if package in ['rpmlint-mini-AGGR']:
            return package  # we should not freeze aggregates
        ET.SubElement(flink, 'package', {'name': package, 'srcmd5': si.get('srcmd5'), 'vrev': si.get('vrev')})
        return package


    def add(self, *packages):
        True

 
class CommandLineInterface(ToolBase.CommandLineInterface):

    def __init__(self, *args, **kwargs):
        ToolBase.CommandLineInterface.__init__(self, args, kwargs)

    def get_optparser(self):
        parser = ToolBase.CommandLineInterface.get_optparser(self)
        parser.add_option('-p', '--project', dest='project', metavar='PROJECT',
                        help='project to process (default: %s)' % FACTORY,
                        default = FACTORY)
        return parser

    def setup_tool(self):
        tool = Freezer(self.options.project)
        return tool

    def do_add(self, subcmd, opts, *packages):
        """${cmd_name}: add packages to freezer

        ${cmd_usage}
        ${cmd_option_list}
        """

        self.tool.add(packages)

    def do_remove(self, subcmd, opts, *packages):
        """${cmd_name}: remove packages from freezer

        ${cmd_usage}
        ${cmd_option_list}
        """

        self.tool.remove(packages)

    def do_info(self, subcmd, opts, *packages):
        """${cmd_name}: show information about packages

        ${cmd_usage}
        ${cmd_option_list}
        """

        self.tool.info(packages)

    def do_check(self, subcmd, opts, *packages):
        """${cmd_name}: check whether packages are up to date

        ${cmd_usage}
        ${cmd_option_list}
        """

        self.tool.check(packages)

if __name__ == "__main__":
    app = CommandLineInterface()
    sys.exit( app.main() )

# vim: sw=4 et
