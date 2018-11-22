#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2015 SUSE Linux GmbH
# Copyright (c) 2016 SUSE LLC
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

class AdiTool(ToolBase.ToolBase):

    def __init__(self, project):
        ToolBase.ToolBase.__init__(self)
        self.project = project

    def add_revesedeps(self, adinr, packagenames):
        adicontent = set(self.meta_get_packagelist("%s:Staging:adi:%s"%(self.project, adinr)))

        if not packagenames:
            packagenames = adicontent

        query = ['view=revpkgnames'] + [ 'package=%s'%p for p in packagenames ]
        url = makeurl(self.apiurl, ['build', self.project, 'standard', 'x86_64', '_builddepinfo'], query)
        xml = ET.fromstring(self.cached_GET(url))

        needed_links = set()
        for pnode in xml.findall('package'):
            name = pnode.get('name')
            for rdep in pnode.findall('pkgdep'):
                p = rdep.text
                if not p in adicontent:
                    logger.info("%s triggers %s which is missing from adi:%s", name, p, adinr)
                    needed_links.add(p)

        for i in needed_links:
            print "osc linkpac {0} {1} {0}:Staging:adi:{2}".format(self.project, i, adinr)

    def rebuild_revesedeps(self, packagenames):
        adicontent = set(self.meta_get_packagelist(self.project))

        if not packagenames:
            packagenames = adicontent

        query = ['view=revpkgnames'] + [ 'package=%s'%p for p in packagenames ]
        url = makeurl(self.apiurl, ['build', self.project, 'standard', 'x86_64', '_builddepinfo'], query)
        xml = ET.fromstring(self.cached_GET(url))

        rdeps = set()
        for pnode in xml.findall('package'):
            name = pnode.get('name')
            for rdep in pnode.findall('pkgdep'):
                p = rdep.text
                rdeps.add(p)

        for i in rdeps:
            print "osc rebuild {0} {1}".format(self.project, i)


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
        tool = AdiTool(self.options.project)
        return tool

    def do_add_revdeps(self, subcmd, opts, adi, *packages):
        """${cmd_name}: enable build for packages in Ring 0 or 1 or with
        baselibs.conf

        ${cmd_usage}
        ${cmd_option_list}
        """

        self.tool.add_revesedeps(adi, packages)

    def do_rebuild_revdeps(self, subcmd, opts, *packages):
        """${cmd_name}: rebuild reverse deps

        ${cmd_usage}
        ${cmd_option_list}
        """

        self.tool.rebuild_revesedeps(packages)

if __name__ == "__main__":
    app = CommandLineInterface()
    sys.exit( app.main() )

# vim: sw=4 et
