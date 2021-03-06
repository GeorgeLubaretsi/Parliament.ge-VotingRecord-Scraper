#!/usr/bin/python
# vim: set fileencoding=utf-8
"""Voting Records scraper.

Scrape the voting records of the Georgian Parliament.

"""
__docformat__ = "epytext en"
import sys, os, getopt, urllib2, re, json, time
from BeautifulSoup import BeautifulSoup


HOST = 'http://www.parliament.ge/'
DOC = 'index.php'
PARAMS = '?sec_id=1530&lang_id=GEO&kan_name=&kan_num=&kan_mp=&Search=ძიება'
ROOT = HOST + DOC + PARAMS
NEXT_PAGE = ROOT + '&limit='
#HOST = 'file:///home/shensche/votingrecord/Parliament.ge-VotingRecord-Scraper/'
#ROOT = HOST + 'first.html'
SLEEP = 1 #: how long to wait between request
JSON_INDENT = 2 #: indentation for JSON output
OUTDIR = os.getcwd() + os.sep #: default output directory



class ScrapeError (Exception):
    """Generic scrape exception."""
    def __init__(self, value):
        super(ScrapeError, self).__init__()
        self.value = value
    def __str__(self):
        return repr(self.value)


class VotingRecordsScraper (object):
    """Class to scrape the voting records."""

    def __init__ (self, outdir):
        """Constructor

        @param outdir: output directory
        @type outdir: string
        """
        if outdir[-1] != os.sep:
            self.outdir = outdir + os.sep
        else:
            self.outdir = outdir


    def _find_not_in_hidethis (self, tags):
        """
        Filter tags which are not inside a parent tag with class 'hidethis'.

        @param tags: tags to filter
        @type tags: [ BeautifulSoup.Tag ]
        @return: filtered tags
        @rtype: [ BeautifulSoup.Tag ]
        """
        data = []
        for tag in tags:
            hidethis = False
            for attr in tag.parent.parent.parent.parent.attrs:
                if attr[0] == 'class' and attr[1] == 'hidethis':
                    hidethis = True
            for attr in tag.parent.parent.parent.attrs:
                if attr[0] == 'class' and attr[1] == 'hidethis':
                    hidethis = True
            if not hidethis:
                data.append(tag)
        return data


    def _get_kan_id (self, tag):
        """
        Get kan_id in given 'a'-tag.

        kan_id seems to be the only identifier for the voting records data.

        @param tag: tag representing an HTML <a>
        @type tag: BeautifulSoup.Tag
        @return: the kan_id
        @rtype: string
        """
        return tag.attrs[0][1].split('=')[-1]


    def _get_next_page (self, soup, is_root=False):
        """
        Determine the URL of the next page to scrape.

        @param soup: soup to look for next page indicator
        @type soup: BeautifulSoup.BeautifulSoup
        @param is_root: if current page is the root page
        @type is_root: bool
        @return: URL of next page to scrape
        @rtype: string
        """
        regex = re.compile('limit=')
        tags = soup.findAll('a', attrs={'href':regex})
        if len(tags) < 5 and not is_root: # last page
            return None

        limit = ''
        for attr in tags[-2].attrs: # -2 is next page
            if attr[0] == 'href':
                limit = attr[1].split('=')[-1]
        return NEXT_PAGE + limit.encode('utf-8')


    def _write (self, details, numbers, dates, results, amendments):
        """
        Write voting records to (JSON) files.

        @param details: scraped bill details
        @type details: [ {'uri': string, 'name': string, 'kan_id': string} ]
        @param numbers: scraped bill numbers
        @type numbers: [ int ]
        @param dates: scraped bill dates
        @type dates: [ int ]
        @param results: scraped bill voting results
        @type results: [ [ {'name' : string, 'vote': string} ] ]
        @param amendments: scraped amendment bill numbers
        @type amendments: [ [ string ] ]
        """
        for i in xrange(len(details)):
            record = {
                'kan_id': details[i]['kan_id'],
                'url': HOST + details[i]['uri'],
                'name': details[i]['name'],
                'number': numbers[i],
                'date': dates[i],
                'result': results[i],
                'amendments': amendments[i]
            }

            fmt = 'Voting record for bill %s, kan_id %s'
            print fmt % (record['number'], record['kan_id'])

            fname = self.outdir + record['kan_id'] + '.json'
            handle = open(fname, 'w')
            json.dump(record, handle, indent=JSON_INDENT)
            handle.close()


    def _scrape_details (self, soup):
        """
        Find all bill details in given soup.

        A detail contains info about uri to the actual bill, name and kan_id.

        @param soup: soup to scrape
        @type soup: BeautifulSoup.BeautifulSoup
        @return: scraped bill details: relative uri, name, kan_id or None
        @rtype: [ {'uri': string, 'name': string, 'kan_id': string} ]
        """
        regex = re.compile('kan_det=det')
        tags = soup.findAll('a', attrs={'href':regex})
        tags = self._find_not_in_hidethis(tags)

        data = []
        for anchor in tags:
            data.append({
                'uri': anchor.attrs[0][1],
                'name': anchor.contents[0].string.strip(),
                'kan_id': self._get_kan_id(anchor)
            })

        if len(data) == 0:
            print 'WARNING: No bills found. Is this the right document?'
            return None

        return data


    def _scrape_numbers (self, soup, num_details):
        """
        Find all bill numbers in given soup.

        @param soup: soup to scrape
        @type soup: BeautifulSoup.BeautifulSoup
        @param num_details: number of bill details
        @type num_details: int
        @return: scraped bill numbers
        @rtype: [ int ]
        """
        regex = re.compile('^\s?\d\S*') # can't mach [-–], so using \S ??
        tags = soup.findAll('td', attrs={'width':'50', 'align':'center'})
        tags = self._find_not_in_hidethis(tags)
        data = []

        for tag in tags:
            if len(tag.contents) == 0: # no bill number
                data.append(None)
            else:
                if re.match(regex, tag.contents[0].string):
                    data.append(tag.contents[0].string.strip())

        num = len(data)
        if num != num_details:
            fmt = 'Number mismatch: bill numbers %d != bill details %d'
            raise ScrapeError(fmt % (num, num_details))

        return data


    def _scrape_dates (self, soup, num_details):
        """
        Find all bill dates in given soup.

        @param soup: soup to scrape
        @type soup: BeautifulSoup.BeautifulSoup
        @param num_details: number of bill details
        @type num_details: int
        @return: scraped bill dates
        @rtype: [ int ]
        """
        regex = re.compile('^\d{4}-\d{2}-\d{2}$')
        tags = soup.findAll('td', attrs={'width':80, 'align':'center'})
        tags = self._find_not_in_hidethis(tags)
        data = []

        for tag in tags:
            if re.match(regex, tag.contents[0].string):
                data.append(tag.contents[0].string)

        num = len(data)
        if num != num_details:
            fmt = 'Number mismatch: bill dates %d != bill details %d'
            raise ScrapeError(fmt % (num, num_details))

        return data


    def _scrape_results (self, soup, num_details):
        """
        Find all bill voting results in given soup.

        @param soup: soup to scrape
        @type soup: BeautifulSoup.BeautifulSoup
        @param num_details: number of bill details
        @type num_details: int
        @return: scraped bill voting results (vote + name)
        @rtype: [ [ {'name' : string, 'vote': string} ] ]
        """
        regex = re.compile('kan_det=res')
        tags = soup.findAll('a', attrs={'href':regex})
        data = []
        for anchor in tags:
            handle = urllib2.urlopen(HOST + anchor.attrs[0][1])
            #handle = urllib2.urlopen(HOST + 'res.html')
            result = BeautifulSoup(
                handle, convertEntities=BeautifulSoup.HTML_ENTITIES)
            table = result.find('table', attrs={
                'width': '500',
                'border':'0',
                'align':'left',
                'cellpadding':'3',
                'cellspacing':'2',
                'bgcolor':'#EEEEEE'
            })
            votes = []
            for tag in table.findAll('tr', attrs={'bgcolor':'#FFFFFF'}):
                children = tag.findChildren()
                votes.append({
                    'name': children[0].contents[0].string,
                    'vote': children[1].contents[0].string
                })
            handle.close()
            data.append(votes)
            time.sleep(SLEEP) # give the server some time to breathe

        num = len(data)
        if num != num_details:
            for _ in xrange(abs(num_details - num)): # fill with empty values
                data.append(None)

        return data


    def _scrape_amendments (self, soup, details):
        """
        Find all amendment bill numbers in given soup.

        @param soup: soup to scrape
        @type soup: BeautifulSoup.BeautifulSoup
        @param details: scraped bill details
        @type details: [ {'uri': string, 'name': string, 'kan_id': string} ]
        @return scraped amendment bill numbers
        @rtype: [ [ string ] ]
        """
        # prepopulate data to be returned
        data = [[] for _ in xrange(len(details))]

        # each div contains a list of amendments
        tags = soup.findAll('div', attrs={'class':'hidethis'})
        for div in tags:
            # find parent bill's index for this div's kan_id
            bill = div.parent.parent.findPreviousSibling()
            kan_id = self._get_kan_id(bill.find('td').find('a'))
            for det in details:
                if det['kan_id'] == kan_id:
                    idx = details.index(det)
                    break

            # find amendment numbers
            nums = []
            for row in div.findAll('tr'):
                cols = row.findAll('td')
                if len(cols[1].contents) == 0:
                    nums.append(None)
                else: # use bill number
                    nums.append(cols[1].contents[0])
            data[idx] = nums

        return data


    def scrape (self, url, is_root=False):
        """
        Scrape one page and return the next page's URL.

        @param url: URL of the page to scrape
        @type url: string
        @param is_root: if given url is root page (used for getting next page)
        @type is_root: bool
        @return: URL of the next page to scrape
        @rtype: string
        """
        time_start = time.time()
        print 'Scraping: %s' % url

        handle = urllib2.urlopen(url)
        soup = BeautifulSoup(
            handle, convertEntities=BeautifulSoup.HTML_ENTITIES)

        details = self._scrape_details(soup)
        if details:
            num_details = len(details)
            numbers = self._scrape_numbers(soup, num_details)
            dates = self._scrape_dates(soup, num_details)
            results = self._scrape_results(soup, num_details)
            amendments = self._scrape_amendments(soup, details)
            self._write(details, numbers, dates, results, amendments)

        handle.close()

        nxt = self._get_next_page(soup, is_root)
        print 'Time: Page %d seconds.' % (time.time() - time_start)

        return nxt


    def run (self):
        """Run the complete scraping process."""
        print 'Output directory: %s' % self.outdir
        time_start = time.time()

        nxt = self.scrape(ROOT, is_root=True)
        while nxt:
            nxt = self.scrape(nxt, is_root=False)
            time.sleep(SLEEP) # give the server some time to breathe

        print 'Time: Overall %d seconds.' % (time.time() - time_start)


def main():
    """Main function in case the class isn't used directly."""
    # parse command line options
    try:
        opts, _ = getopt.getopt(sys.argv[1:], 'ho:', ['help', 'output='])
    except getopt.error, msg:
        print msg
        print 'For help use --help'
        sys.exit(2)

    # process options
    outdir = None
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            print __doc__
            sys.exit(0)
        elif opt in ("-o", "--output"):
            outdir = arg

    if not outdir:
        outdir = OUTDIR
    if not os.path.exists(outdir):
        os.mkdir(outdir)

    VotingRecordsScraper(outdir).run()


if __name__ == "__main__":
    main()
