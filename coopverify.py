#!/usr/bin/env python
# coding=utf8
#
# coopverify.py - verifiera coop-transaktioner
#

import sys
import urllib
import urllib2
import cookielib
import json
import time
import re
from datetime import datetime, date
import calendar
from itertools import groupby
from collections import OrderedDict
import getpass

def dategroup(struct):
    grp = OrderedDict()
    for k,g in groupby(sorted(struct, key=lambda x: x['date']), lambda x: x['date']):
        grp[k] = list(g)
    return grp

def monthrange(start, end):
    months = (end.year - start.year) * 12 + end.month + 1 
    for i in xrange(start.month, months):
        year  = (i - 1) / 12 + start.year
        month = (i - 1) % 12 + 1
        yield date(year, month, 1)

shortmonths = ['jan', 'feb', 'mar', 'apr', 'maj', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec']
longmonths = ['januari', 'februari', 'mars', 'april', 'maj', 'juni', 'juli', 'augusti', 'september', 'oktober', 'november', 'december']

date_regex = re.compile('^(\d+) (\w+) (\d+)$')

def parse_date(datestr):
    m = date_regex.match(datestr)
    if not m:
        print "Misslyckades med att tolka datum '{0}'".format(datestr)
        sys.exit(1)

    try:
        idx = shortmonths.index(m.group(2))
    except ValueError:
        try:
            idx = longmonths.index(m.group(2))
        except ValueError:
            print "Hittade inte månad '{0}'".format(m.group(2))
            sys.exit(1)

    return date(int(m.group(3)), idx+1, int(m.group(1)))

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print "Usage: coopverify.py <mail> <starmånad> <slutmånad>"
        print "  Ex:  coopverify.py kalle@example.com 2015-06 2015-08"
        sys.exit(1)

    username = sys.argv[1]
    start = datetime.strptime(sys.argv[2], "%Y-%m").date()
    end = datetime.strptime(sys.argv[3], "%Y-%m").date()

    password = getpass.getpass(prompt='Lösenord för {0}: '.format(username))
    # Logga in
    print "Loggar in..."
    cj = cookielib.CookieJar()
    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
    urllib2.install_opener(opener)
    req = urllib2.Request("https://www.coop.se/Personliga-Baren/Logga-in/?method=Login",
                          json.dumps({'isBar': 'true',
                                      'username': username,
                                      'password': password,
                                      }))
    req.add_header('X-Requested-With', 'XMLHttpRequest')
    resp = urllib2.urlopen(req)
    if resp.code != 200:
        print "Misslyckades med inloggning"
        print resp.read()
        sys.exit(1)


    points = []
    xact = []
    for monthstart in monthrange(start, end):
        print "Laddar {0}-{1}".format(monthstart.year, monthstart.month)
        monthend = date(monthstart.year, monthstart.month, calendar.monthrange(monthstart.year, monthstart.month)[1])

        # Poängtransaktioner, blir alltid siduppdelat
        pagenum = 1
        while True:
            url = "https://www.coop.se/Services/PlainService.svc/JsonExecuteGet?method=GetTransactionHistory&data={0}&_={1}".format(urllib.quote_plus(json.dumps({
                'page':pagenum,
                'pageSize': 250,
                'from': monthstart.strftime("%Y-%m-%d"),
                'to': monthend.strftime("%Y-%m-%d"),
            })), int(time.time())*1000)
            req = urllib2.Request(url)
            req.add_header('X-Requested-With', 'XMLHttpRequest')
            req.add_header('Referer', 'https://www.coop.se/Mina-sidor/Oversikt/Mina-poang/')
            resp = urllib2.urlopen(req)
            if resp.code != 200:
                print "Misslyckades att hämta poänghistorik"
                sys.exit(1)
            d = resp.read().decode('utf8')
            d = d[1:]

            jpoints = json.loads(d)
            points.extend([{'date': parse_date(r['date']), 'sum': r['sum'], 'outside': r['location'].startswith('Betalning utanf')} for r in jpoints['d']['model']['results']])
            if pagenum < int(jpoints['d']['model']['pageCount']):
                pagenum += 1
                print "... sida {0}".format(pagenum)
            else:
                break


        # Korttransaktioner
        url = "https://www.coop.se/Services/PlainService.svc/JsonExecuteGet?method=GetTransactions&data={0}&_={1}".format(urllib.quote_plus(json.dumps({
            'page':1,
            'pageSize': 25,
            'from': monthstart.strftime("%Y-%m-%d"),
            'to': monthend.strftime("%Y-%m-%d"),
            })), int(time.time())*1000)
        req = urllib2.Request(url)
        req.add_header('X-Requested-With', 'XMLHttpRequest')
        req.add_header('Referer', 'https://www.coop.se/Mina-sidor/Oversikt/Kontoutdrag-MedMera-Mer/')
        resp = urllib2.urlopen(req)
        if resp.code != 200:
            print "Misslyckades att hämta transaktionshistorik"
            print resp.code
            print resp.read()
            sys.exit(1)
        d = resp.read().decode('utf8')
        d = d[1:]

        jxact = json.loads(d)
        xact.extend([{'sum':r['sum'], 'loc': r['location'], 'date': parse_date(r['date'])} for r in jxact['d']['model']['results'] if int(r['sum']) < 0 and not r['title'].startswith('Uttag ')])

    print "Jämför..."
    g_points = dategroup(points)
    g_xact = dategroup(xact)

    for k,v in g_xact.items():
        if not g_points.has_key(k):
            print "{0}: Köp finns, men inga poängtransaktioner!".format(k)
            continue
        pts = g_points[k]
        for trans in v:
            matches = [m for m in pts if int(m['sum']) == -int(trans['sum'])]
            if len(matches):
                pts.remove(matches[0])
            else:
                # Double points on coop purchases
                matches = [m for m in pts if int(m['sum'])/2 == -int(trans['sum']) and not m['outside']]
                if len(matches):
                    pts.remove(matches[0])
                else:
                    print "{0}: Köp för {1} saknar motsvarande poäng!".format(k, -int(trans['sum']))
        if len(pts):
            for p in pts:
                if int(p['sum']) < 0:
                    print "{0}: Poänguttag av {1} poäng.".format(k, -int(p['sum']))
                else:
                    print "{0}: Transaktion med {1} poäng saknar motsvarande köp!".format(k, int(p['sum']))

    print ""
    print "** Statistik **"
    print "Antal korttransaktioner:  {0}".format(len(xact))
    print "Antal poängtransaktioner: {0}".format(len(points))
    print "Total kortvolym:          {0}".format(sum([-int(x['sum']) for x in xact]))
    print "Total poängvolym:         {0}".format(sum([int(x['sum']) for x in points]))
