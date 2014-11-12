#!/usr/bin/python
# Copyright (c) 2014 SUSE Linux Products GmbH
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

class Checker(object):

    def __init__(self, apiurl = None, factory = None, dryrun = False, logger = None, user = None):
        self.apiurl = apiurl
        self.factory = factory if factory else "openSUSE:Factory"
        self.dryrun = dryrun
        self.logger = logger
        self.review_user = user
        self.requests = []
        self.review_messages = { 'accepted' : 'ok', 'declined': 'the package needs to be accepted in Factory first' }

    def set_request_ids(self, ids):
        for rqid in ids:
            u = osc.core.makeurl(self.apiurl, [ 'request', rqid ])
            r = osc.core.http_GET(u)
            root = ET.parse(r).getroot()
            req = osc.core.Request()
            req.read(root)
            self.requests.append(req)

    def check_requests(self):
        for req in self.requests:
            good = self.check_one_request(req)

            if good is None:
                self.logger.info("ignoring")
            elif good:
                self.logger.info("%s is good"%req.reqid)
                self._set_review(req, 'accepted')
            else:
                self.logger.info("%s is not acceptable"%req.reqid)
                self._set_review(req, 'declined')

    def _set_review(self, req, state):
        if not self.review_user:
            return

        review_state = self.get_review_state(req.reqid, self.review_user)
        if review_state == 'new':
            self.logger.debug("setting %s to %s"%(req.reqid, state))
            if not self.dryrun:
                msg = self.review_messages[state] if state in self.review_messages else state
                osc.core.change_review_state(apiurl = self.apiurl,
                        reqid = req.reqid, newstate = state,
                        by_user=self.review_user, message=msg)
        elif review_state == '':
            self.logger.info("can't change state, %s does not have '%s' as reviewer"%(req.reqid, self.review_user))
        else:
            self.logger.debug("%s review in state '%s' not changed"%(req.reqid, review_state))

    def check_one_request(self, req):
        overall = None
        for a in req.actions:
            if a.type == 'maintenance_incident':
                rev = self._get_verifymd5(a.src_project, a.src_package, a.src_rev)
                ret = self._check_package(a.src_project, a.src_package, rev, a.tgt_releaseproject, a.src_package)
            elif a.type == 'maintenance_release':
                pkgname = a.src_package
                if pkgname == 'patchinfo':
                    continue
                linkpkg = self._get_linktarget_self(a.src_project, pkgname)
                if linkpkg is not None:
                    pkgname = linkpkg
                # packages in maintenance have links to the target. Use that
                # to find the real package name
                (linkprj, linkpkg) = self._get_linktarget(a.src_project, pkgname)
                if linkpkg is None or linkprj is None or linkprj != a.tgt_project:
                    self.logger.error("%s/%s is not a link to %s"%(a.src_project, pkgname, a.tgt_project))
                    overall = False
                    break
                else:
                    pkgname = linkpkg
                src_rev = self._get_verifymd5(a.src_project, a.src_package)
                ret = self._check_package(a.src_project, a.src_package, src_rev, a.tgt_project, pkgname)
            elif a.type == 'submit':
                rev = self._get_verifymd5(a.src_project, a.src_package, a.src_rev)
                ret = self._check_package(a.src_project, a.src_package, rev, a.tgt_package, a.tgt_package)
            else:
                self.logger.error("unhandled request type %s"%a.type)
                ret = None
            if ret == False or overall is None and ret is not None:
                overall = ret
        return overall

    def _check_package(self, src_project, src_package, src_rev, target_project, target_package):
        self.logger.info("%s/%s@%s -> %s/%s"%(src_project, src_package, src_rev, target_project, target_package))
        good = self._check_factory(src_rev, target_package)

        if good:
            self.logger.info("%s is in Factory"%target_package)
            return good

        good = self._check_requests(src_rev, target_package)
        if good:
            self.logger.info("%s already reviewed for Factory"%target_package)

        return good


    def _check_factory(self, rev, package):
        """check if factory sources contain the package and revision. check head and history"""
        self.logger.debug("checking %s in %s"%(package, self.factory))
        srcmd5 = self._get_verifymd5(self.factory, package)
        if srcmd5 is None:
            self.logger.debug("new package")
            return None
        elif rev == srcmd5:
            self.logger.debug("srcmd5 matches")
            return True

        self.logger.debug("%s not the latest version, checking history", rev)
        u = osc.core.makeurl(self.apiurl, [ 'source', self.factory, package, '_history' ], { 'limit': '5' })
        try:
            r = osc.core.http_GET(u)
        except urllib2.HTTPError, e:
            self.logger.debug("package has no history!?")
            return None

        root = ET.parse(r).getroot()
        for revision in root.findall('revision'):
            node = revision.find('srcmd5')
            if node is None:
                continue
            self.logger.debug("checking %s"%node.text)
            if node.text == rev:
                self.logger.debug("got it, rev %s"%revision.get('rev'))
                return True

        self.logger.debug("srcmd5 not found in history either")
        return False

    def _check_requests(self, rev, package):
        self.logger.debug("checking requests")
        requests = osc.core.get_request_list(self.apiurl, self.factory, package, None, ['new', 'review'], 'submit')
        for req in requests:
            for a in req.actions:
                rqrev = self._get_verifymd5(a.src_project, a.src_package, a.src_rev)
                self.logger.debug("rq %s: %s/%s@%s"%(req.reqid, a.src_project, a.src_package, rqrev))
                if rqrev == rev:
                    if req.state.name == 'new':
                        self.logger.debug("request ok")
                        return True
                    elif req.state.name == 'review':
                        self.logger.debug("request still in review")
                        return None
                    else:
                        self.logger.error("request in state %s not expected"%req.state.name)
                        return None
        return False

    # XXX used in other modules
    def _get_verifymd5(self, src_project, src_package, rev=None):
        query = { 'view': 'info' }
        if rev:
            query['rev'] = rev
        url = osc.core.makeurl(self.apiurl, ('source', src_project, src_package), query=query)
        try:
            root = ET.parse(osc.core.http_GET(url)).getroot()
        except urllib2.HTTPError:
            return None

        if root is not None:
            srcmd5 = root.get('verifymd5')
            return srcmd5

    # TODO: what if there is more than _link?
    def _get_linktarget_self(self, src_project, src_package):
        """ if it's a link to a package in the same project return the name of the package"""
        prj, pkg = self._get_linktarget(src_project, src_package)
        if prj is None or prj == src_project:
            return pkg

    def _get_linktarget(self, src_project, src_package):

        query = {}
        url = osc.core.makeurl(self.apiurl, ('source', src_project, src_package), query=query)
        try:
            root = ET.parse(osc.core.http_GET(url)).getroot()
        except urllib2.HTTPError:
            return (None, None)

        if root is not None:
            linkinfo = root.find("linkinfo")
            if linkinfo is not None:
                return (linkinfo.get('project'), linkinfo.get('package'))

    # XXX used in other modules
    def get_review_state(self, request_id, user):
        """Return the current review state of the request."""
        states = []
        url = osc.core.makeurl(self.apiurl, ('request', str(request_id)))
        try:
            root = ET.parse(osc.core.http_GET(url)).getroot()
            states = [review.get('state') for review in root.findall('review') if review.get('by_user') == user]
        except urllib2.HTTPError, e:
            print('ERROR in URL %s [%s]' % (url, e))
        return states[0] if states else ''

class CommandLineInterface(cmdln.Cmdln):
    def __init__(self, *args, **kwargs):
        cmdln.Cmdln.__init__(self, args, kwargs)

    def get_optparser(self):
        parser = cmdln.CmdlnOptionParser(self)
        parser.add_option("--factory", metavar="project", help="the openSUSE Factory project")
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

        self.checker = Checker(apiurl = apiurl, \
                factory = self.options.factory, \
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

        review = "@by_user='%s'+and+@state='new'"%self.checker.review_user
        url = osc.core.makeurl(self.checker.apiurl, ('search', 'request'), "match=state/@name='review'+and+review[%s]"%review)
        root = ET.parse(osc.core.http_GET(url)).getroot()

        for request in root.findall('request'):
            req = osc.core.Request()
            req.read(request)
            self.checker.requests.append(req)

        self.checker.check_requests()


if __name__ == "__main__":
    app = CommandLineInterface()
    sys.exit( app.main() )

# vim: sw=4 et
