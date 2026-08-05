"""Devreye Alma Paneli — çekirdek modüller.

Alt modüller birbirini `from . import ...` ile çağırır; hiçbiri kendi
başına bir HTTP sunucusu ya da pencere açmaz. Arayüz tarafı yalnızca
panel_api.py üzerinden bu modüllere erişir.
"""
