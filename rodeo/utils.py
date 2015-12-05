# -*- coding: utf-8 -*-
import re
import unicodedata
import os


def slugify(string):
    """
    Slugify a unicode string.

    Example:
    >>> slugify(u"Hello World")
    u"hello-world"
    """

    return re.sub(r'[-\s]+', '-',
            (re.sub(r'[^\w\s-]', '',string).strip().lower()))

def tail(f, n):
  stdin,stdout = os.popen2("tail -n " + str(n) + " " + f)
  stdin.close()
  lines = stdout.readlines(); stdout.close()
  return lines