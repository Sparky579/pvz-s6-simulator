"""The original Chinese S6 package requires the GBK Win32 ANSI environment."""
from __future__ import annotations
import os

WINE_LOCALE='zh_CN.UTF-8'
EXPECTED_ACP=936


def wine_environment(prefix,display=None,**overrides):
    env={**os.environ,'WINEPREFIX':str(prefix),'WINEDEBUG':'-all',
         'LANG':WINE_LOCALE,'LC_ALL':WINE_LOCALE,'LANGUAGE':'zh_CN:en'}
    if display is not None:env['DISPLAY']=display
    env.update(overrides)
    return env
