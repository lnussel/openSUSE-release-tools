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
from collections import namedtuple
import sys
import cmdln
import logging
import urllib2
import osc.core

import ToolBase

logger = logging.getLogger()

FACTORY = "openSUSE:Factory"

SourceInfo = namedtuple('SourceInfo', ('package', 'vrev', 'srcmd5', 'verifymd5', 'linked'))
LinkedInfo = namedtuple('LinkedInfo', ('project', 'package'))

class Freezer(ToolBase.ToolBase):

    def __init__(self, project):
        ToolBase.ToolBase.__init__(self)
        self.project = project
        self.packages = dict()

    def _init(self):
        self._init_links()
        self._init_sourceinfo()

    def _init_links(self):
        url = self.makeurl(['source', self.project, '_meta'])
        root = ET.fromstring(self.cached_GET(url))
        links = root.findall('link')
        links.reverse()
        self.projectlinks = [link.get('project') for link in links]
        logger.debug("links %s", self.projectlinks)

    def _init_sourceinfo(self):
        for prj in [ self.project ] + self.projectlinks:
            url = self.makeurl(['source', prj], {'view': 'info', 'nofilename': '1'})
            root = ET.fromstring(self.cached_GET(url))

            for node in root.findall('sourceinfo'):
                attrs = [node.get(i, None) for i in SourceInfo._fields]
                for linked in node.findall('linked'):
                    if attrs[-1] is None:
                        attrs[-1] = []
                    attrs[-1].append(LinkedInfo(*[linked.get(i, None) for i in LinkedInfo._fields]))
                si = SourceInfo(*attrs)
                self.packages.setdefault(prj, dict())[si.package] = si

#    def freeze_prjlinks(self):
#        sources = {}
#        flink = ET.Element('frozenlinks')
#
#        for lprj in self.projectlinks:
#            fl = ET.SubElement(flink, 'frozenlink', {'project': lprj})
#            sources = self.receive_sources(lprj, sources, fl)
#
#        url = self.makeurl(['source', self.prj, '_project', '_frozenlinks'], {'meta': '1'})
#        self.api.retried_PUT(url, ET.tostring(flink))
#
#    def receive_sources(self, prj, sources, flink):
#        url = self.makeurl(['source', prj], {'view': 'info', 'nofilename': '1'})
#        f = self.api.cached_GET(url)
#        root = ET.parse(f).getroot()
#
#        for si in root.findall('sourceinfo'):
#            package = self.check_one_source(flink, si)
#            sources[package] = 1
#        return sources
#
#    def check_one_source(self, flink, si):
#        package = si.get('package')
#
#        # If the package is an internal one (e.g _product)
#        if package.startswith('_'):
#            return None
#
#        # Ignore packages with an origing (i.e. with an origin
#        # different from the current project)
#        if si.find('originproject') != None:
#            return None
#
#        # we have to check if its a link within the staging project
#        # in this case we need to keep the link as is, and not freezing
#        # the target. Otherwise putting kernel-source into staging prj
#        # won't get updated kernel-default (and many other cases)
#        for linked in si.findall('linked'):
#            if linked.get('project') in self.projectlinks:
#                # take the unexpanded md5 from Factory / 13.2 link
#                url = self.makeurl(['source', self.api.project, package],
#                                       {'view': 'info', 'nofilename': '1'})
#                # print(package, linked.get('package'), linked.get('project'))
#                f = self.api.cached_GET(url)
#                proot = ET.parse(f).getroot()
#                lsrcmd5 = proot.get('lsrcmd5')
#                if lsrcmd5 is None:
#                    raise Exception("{}/{} is not a link but we expected one".format(self.api.project, package))
#                ET.SubElement(flink, 'package', {'name': package, 'srcmd5': lsrcmd5, 'vrev': si.get('vrev')})
#                return package
#        if package in ['rpmlint-mini-AGGR']:
#            return package  # we should not freeze aggregates
#        ET.SubElement(flink, 'package', {'name': package, 'srcmd5': si.get('srcmd5'), 'vrev': si.get('vrev')})
#        return package
#

    def add(self, *packages):
        True

    def check(self, *packages):
        self._init()
        packages = packages[0]
        if not packages:
            packages = self.packages[self.project].keys()

        for p in packages:
            s = set()
            for prj in self.packages.keys():
                if p in self.packages[prj]:
                    s.add(self.packages[prj][p].srcmd5)
            if len(s) > 1:
                print p, s
 
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
