"""Django 5.1 template-context copy is incompatible with Python 3.14."""
import sys
from copy import copy


def apply():
    if sys.version_info < (3, 14):
        return
    from django.template.context import BaseContext

    def __copy__(self):
        duplicate = self.__class__.__new__(self.__class__)
        duplicate.__dict__ = copy(self.__dict__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    BaseContext.__copy__ = __copy__


apply()
