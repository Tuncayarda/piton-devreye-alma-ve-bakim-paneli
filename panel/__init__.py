"""Commissioning panel application package.

Sub-packages talk to each other through plain imports; none of them opens a
socket or a window. The UI reaches this code only through `panel.api`.
"""
