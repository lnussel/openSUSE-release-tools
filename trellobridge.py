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
from datetime import datetime
import ToolBase
import requests
import logging
import sys
import osc.core
import urllib2

logger = logging.getLogger()

class TrelloBridge(ToolBase.ToolBase):

    def __init__(self, key, token):
        ToolBase.ToolBase.__init__(self)
        self._apikey = key
        self._token = token

    def _get(self, path, **kwargs):
        r = requests.get("https://trello.com/1" + path, **kwargs)
        r.raise_for_status()
        return r

    def get_board(self, boardid):
        board = self._get("/boards/%s" % (boardid), params=dict(
            key=self._apikey, token=self._token,
            fields="id,name,idOrganization",
            lists="open", list_fields="id,name",
            cards="visible", cards_fields="id,desc,labels,idList",
            labels="all", labels_fields="id,name"))
        return board.json()

    def results2trello(self, boardid, project):

        cards = {}
        board = self.get_board(boardid)
        for card in board['cards']:
            cards[card['name']] = card

        labels = {}
        for l in board['labels']:
            if len(l['name']):
                labels[l['name']] = l['id']

        lists = {}
        for l in board['lists']:
            if len(l['name']):
                lists[l['name']] = l['id']

        projects = [ project + suffix for suffix in (':Rings:0-Bootstrap', ':Rings:1-MinimalX', '')]

        projects += [ project + ":Staging:" + p for p in ('A', 'B', 'C', 'D', 'E') ]

        results = {}
        for prj in projects:
            root = ET.fromstring(self.cached_GET(self.makeurl(['build', prj, '_result'])))
            for result in root.findall('result'):
                arch = result.get('arch')
                repo = result.get('repository')
                repostate = result.get('state')
                for node in result.findall('status'):
                    status = node.get('code')
                    package = node.get('package')
                    tocheck = [ 'failed' ]
                    if 'published' in repostate:
                        tocheck += ['unresolvable']
                    if status in tocheck:
                        results.setdefault('/'.join((prj, package)), set()).add((repo, arch, status))
                        logger.debug("%s/%s %s %s %s", prj, package, repo, arch, status)

        old = set(cards.keys())
        new = set(results.keys())

        def results2desc(p, r):
            desc = "https://build.opensuse.org/package/show/{}\n\n".format(p)
            for t in results[i]:
                repo, arch, status = t
                if status != 'unresolvable':
                    desc += "* [{}](https://build.opensuse.org/package/live_build_log/{}/{}/{})\n".format(status, p, repo, arch)

            return desc

        # update existing cards
        for i in old & new:
            card = cards[i]
            oldlabels = set(str(l['name']) for l in card['labels'])
            newlabels = set()

            for t in results[i]:
                repo, arch, status = t
                newlabels.add(arch)
                newlabels.add(status)

            for l in newlabels - oldlabels:
                if not l in labels:
                    logger.error('missing label %s', l)
                    continue

                logger.debug("adding label '%s' to %s", l, i)
                r = requests.post("https://trello.com/1/cards/{}/idLabels".format(card['id']),
                        params = dict(key=self._apikey, token=self._token),
                        data = { 'value': labels[l] })
                r.raise_for_status()

            for l in oldlabels - newlabels:
                logger.debug("removing label '%s' from %s", l, i)
                r = requests.delete("https://trello.com/1/cards/{}/idLabels/{}".format(card['id'], labels[l]),
                        params = dict(key=self._apikey, token=self._token))
                r.raise_for_status()

            desc = results2desc(i, results[i])
            if desc != card['desc']:
                r = requests.put("https://trello.com/1/cards/{}".format(card['id']),
                        params = dict(key=self._apikey, token=self._token),
                        data = { 'desc': desc })
                r.raise_for_status()

        for i in new - old:
            logger.debug("adding card '%s'", i)
            idLabels = set()
            for t in results[i]:
                repo, arch, status = t
                idLabels.add(labels[arch])
                idLabels.add(labels[status])
            r = requests.post("https://trello.com/1/cards",
                    params = dict(key=self._apikey, token=self._token),
                    data = dict(
                        name=i,
                        desc="https://build.opensuse.org/package/show/{}".format(i),
                        idLabels=','.join(idLabels),
                        idList=lists['Incoming'],
                        due=datetime.utcnow().strftime('%Y-%m-%d'),
                        ))
            r.raise_for_status()

        for i in old - new:
            logger.debug("removing card '%s'", i)
#            r = requests.delete("https://trello.com/1/cards/{}".format(cards[i]['id']),
#                    params = dict(key=self._apikey, token=self._token))
            r = requests.put("https://trello.com/1/cards/{}".format(card['id']),
                    params = dict(key=self._apikey, token=self._token),
                    data = { 'closed': 'true' })
            r.raise_for_status()


        # trigger rebuild
        for card in board['cards']:
            if card['idList'] != lists['Rebuild']:
                continue
            prj, pkg = str(card['name']).split('/')
            if not prj in projects:
                logger.error("invalid project %s for %s", prj, pkg)
                continue

            logger.debug("rebuild %s/%s", prj, pkg)
            try:
                self.http_POST(self.makeurl(['build', prj], query=dict(code='failed', cmd='rebuild', package=pkg)))
                logger.debug("removing card '%s'", card['name'])
#                r = requests.delete("https://trello.com/1/cards/{}".format(card['id']),
#                        params = dict(key=self._apikey, token=self._token))
                r = requests.put("https://trello.com/1/cards/{}".format(card['id']),
                        params = dict(key=self._apikey, token=self._token),
                        data = { 'closed': 'true' })

                r.raise_for_status()
            except urllib2.HTTPError as e:
                logger.error(e)

class CommandLineInterface(ToolBase.CommandLineInterface):

    def __init__(self, *args, **kwargs):
        ToolBase.CommandLineInterface.__init__(self, args, kwargs)

    def get_optparser(self):
        parser = ToolBase.CommandLineInterface.get_optparser(self)
        parser.add_option('--key', dest='key', metavar='KEY',
                        help='api key')
        parser.add_option('--token', dest='token', metavar='TOKEN',
                        help='API token')
        return parser

    def setup_tool(self):
        if not self.options.key or not self.options.token:
            raise Exception("missing key and token options. generate them at https://trello.com/app-key")
        tool = TrelloBridge(self.options.key, self.options.token)
        return tool

    def do_run(self, subcmd, opts, boardid):
        """${cmd_name}: print lists of a board

        ${cmd_usage}
        ${cmd_option_list}
        """

        self.tool.results2trello(boardid, 'openSUSE:Leap:15.1')

    def do_lists(self, subcmd, opts, boardid):
        """${cmd_name}: print lists of a board

        ${cmd_usage}
        ${cmd_option_list}
        """

        board = self.tool.get_board(boardid)
        print("{}  {}".format(board['id'], board['name']))
        for l in board['lists']:
            print("  {}  {}".format(l['id'], l['name']))

    def do_cards(self, subcmd, opts, boardid):
        """${cmd_name}: list cards of a board

        ${cmd_usage}
        ${cmd_option_list}
        """

        board = self.tool.get_board(boardid)
        print("{}  {}".format(board['id'], board['name']))
        for l in board['cards']:
            print("  {}  {} {}".format(l['id'], l['name'], ','.join(i['name'] for i in l['labels'])))

    def do_labels(self, subcmd, opts, boardid):
        """${cmd_name}: list cards of a board

        ${cmd_usage}
        ${cmd_option_list}
        """

        board = self.tool.get_board(boardid)
        print("{}  {}".format(board['id'], board['name']))
        for l in board['labels']:
            print("  {}  {}".format(l['id'], l['name']))


if __name__ == "__main__":
    app = CommandLineInterface()
    sys.exit(app.main())

# vim:sw=4 et
