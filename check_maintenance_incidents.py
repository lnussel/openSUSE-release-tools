#!/usr/bin/python
# Copyright (c) 2014 SUSE Linux GmbH
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

from pprint import pprint
import os, sys, re
import logging
from optparse import OptionParser
import cmdln

try:
    from xml.etree import cElementTree as ET
except ImportError:
    import cElementTree as ET

import osc.conf
import osc.core
import urllib2

from check_source_in_factory import Checker

class MaintenanceChecker(Checker):
    """ simple bot that adds other reviewers depending on target project
    """

    def __init__(self, *args, **kwargs):
        Checker.__init__(self, *args, **kwargs)
        self.review_messages = {}

    # XXX: share with checkrepo
    def _maintainers(self, package):
        """Get the maintainer of the package involved in the package."""
        query = {
            'binary': package,
        }
        url = osc.core.makeurl(self.apiurl, ('search', 'owner'), query=query)
        root = ET.parse(osc.core.http_GET(url)).getroot()
        return [p.get('name') for p in root.findall('.//person') if p.get('role') == 'maintainer']

    def add_devel_project_review(self, req, package):
        """ add devel project/package as reviewer """
        query = {
            'binary': package,
        }
        url = osc.core.makeurl(self.apiurl, ('search', 'owner'), query=query)
        root = ET.parse(osc.core.http_GET(url)).getroot()
        for p in root.findall('./owner'):
            prj = p.get("project")
            pkg = p.get("package")
            self.add_review(req, by_project = prj, by_package = pkg,
                    msg = "Submission by someone who is not maintainer in the devel project. Please review")

    def check_one_request(self, req):
        overall = None
        add_factory_source = False
        needs_maintainer_review = set()
        for a in req.actions:
            if a.type == 'maintenance_incident':
                foundone = False
                author = req.get_creator()
                # check if there is a link and use that or the real package
                # name as src_packge may end with something like
                # .openSUSE_XX.Y_Update
                pkgname = a.src_package
                (linkprj, linkpkg) = self._get_linktarget(a.src_project, pkgname)
                if linkpkg is not None:
                    pkgname = linkpkg
                maintainers = set(self._maintainers(pkgname))
                if maintainers:
                    for m in maintainers:
                        if author == m:
                            self.logger.debug("%s is maintainer"%author)
                            foundone = True
                    if not foundone:
                        for r in req.reviews:
                            if r.by_user in maintainers:
                                self.logger.debug("found %s as reviewer"%r.by_user)
                                foundone = True
                    self.logger.info("author: %s, maintainers: %s => need review"%(author, ','.join(maintainers)))
                    if not foundone:
                        needs_maintainer_review.add(pkgname)
                else:
                    self.logger.warning("%s doesn't have maintainers"%pkgname)

                if a.tgt_releaseproject == "openSUSE:CPE:SLE-12":
                    add_factory_source = True

                ret = True
            else:
                self.logger.error("unhandled request type %s"%a.type)
                ret = None
            if ret == False or overall is None and ret is not None:
                overall = ret

        if add_factory_source:
            self.logger.debug("%s needs review by factory-source"%req.reqid)
            if self.add_review(req, by_user =  "factory-source") != True:
                overall = None

        if needs_maintainer_review:
            for p in needs_maintainer_review:
                self.add_devel_project_review(req, p)

        return overall

class CommandLineInterface(cmdln.Cmdln):
    def __init__(self, *args, **kwargs):
        cmdln.Cmdln.__init__(self, *args, **kwargs)

    def get_optparser(self):
        parser = cmdln.CmdlnOptionParser(self)
        parser.add_option("--apiurl", '-A', metavar="URL", help="api url")
        parser.add_option("--user",  metavar="USER", help="reviewer user name")
        parser.add_option("--dry", action="store_true", help="dry run")
        parser.add_option("--debug", action="store_true", help="debug output")
        parser.add_option("--osc-debug", action="store_true", help="osc debug output")
        parser.add_option("--verbose", action="store_true", help="verbose")

        return parser

    def postoptparse(self):
        logging.basicConfig()
        self.logger = logging.getLogger(self.optparser.prog)
        if (self.options.debug):
            self.logger.setLevel(logging.DEBUG)
        elif (self.options.verbose):
            self.logger.setLevel(logging.INFO)

        osc.conf.get_config(override_apiurl = self.options.apiurl)

        if (self.options.osc_debug):
            osc.conf.config['debug'] = 1

        apiurl = osc.conf.config['apiurl']
        if apiurl is None:
            raise osc.oscerr.ConfigError("missing apiurl")
        user = self.options.user
        if user is None:
            user = osc.conf.get_apiurl_usr(apiurl)

        self.checker = MaintenanceChecker(apiurl = apiurl, \
                dryrun = self.options.dry, \
                user = user, \
                logger = self.logger)

    def do_id(self, subcmd, opts, *args):
        """${cmd_name}: print the status of working copy files and directories

        ${cmd_usage}
        ${cmd_option_list}
        """
        self.checker.set_request_ids(args)
        self.checker.check_requests()

    def do_review(self, subcmd, opts, *args):
        """${cmd_name}: print the status of working copy files and directories

        ${cmd_usage}
        ${cmd_option_list}
        """
        if self.checker.review_user is None:
            raise osc.oscerr.WrongArgs("missing user")

        self.checker.set_request_ids_search_review()
        self.checker.check_requests()


if __name__ == "__main__":
    app = CommandLineInterface()
    sys.exit( app.main() )

# vim: sw=4 et
