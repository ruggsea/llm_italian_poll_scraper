# TEMPORARY debug helper for .github/workflows/debug_egress.yaml — delete together.
# Extracts WebForms fields from a saved ListaSondaggi page and builds the
# PaginaSuccessiva postback body; also records the first poll date on the page.
import re, urllib.parse, sys

html = open(sys.argv[1]).read()

def val(n):
    m = re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(n), html)
    return m.group(1) if m else ''

data = {
    '__VIEWSTATE': val('__VIEWSTATE'),
    '__VIEWSTATEGENERATOR': val('__VIEWSTATEGENERATOR'),
    '__EVENTVALIDATION': val('__EVENTVALIDATION'),
    'ctl00$Contenuto$dgSondaggi_PaginaSuccessiva': ' > ',
}
open('/tmp/post_data.txt', 'w').write(urllib.parse.urlencode(data))
m = re.search(r'title="(\d{2}/\d{2}/\d{4})"', html)
open('/tmp/page1_date.txt', 'w').write(m.group(1) if m else '?')
