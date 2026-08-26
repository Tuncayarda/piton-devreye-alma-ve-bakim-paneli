#!/usr/bin/env python3
"""The XML bodies sent to a camera or an NVR.

Every body here is taken VERBATIM from the field scripts that have been used
on trains (cctv hikvision.py / nvr.py). They are not reconstructed from the
ISAPI documentation on purpose: the devices accept a narrow shape, silently
ignore fields they do not know, and the working shape is the one that has
already been proven on the hardware.

The second and third streams are DERIVED from the first by replacement — the
same way the field script does it — so the three profiles cannot drift apart
when one of them is edited.

  101  main    1920x1080  CBR 4096  600 fps-milli  GOP 6
  102  sub      320x240   CBR 1024  1000           GOP 25
  103  third   project    CBR 2048  2500           GOP 25
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

# Multicast group the trains' video wall listens on. One group for every
# camera, separated by the port numbers below (8960/8964/8968).
MULTICAST_GROUP = "239.255.255.35"

# Resolutions offered for the third stream. YATAKLI uses the first; the
# second exists because other projects run their wall at 1024x768.
STREAM3_SIZES = ("1280x1024", "1024x768")
DEFAULT_STREAM3 = STREAM3_SIZES[0]

_XML = '<?xml version="1.0" encoding="UTF-8"?>'


def size(text: str) -> tuple[int, int]:
    """"1280x1024" -> (1280, 1024). Falls back to the default."""
    try:
        width, height = str(text).lower().split("x", 1)
        return int(width), int(height)
    except (AttributeError, TypeError, ValueError):
        return size(DEFAULT_STREAM3)


def time_body(timezone: str) -> str:
    return (f'{_XML}<Time><timeMode>NTP</timeMode>'
            f'<timeZone>{timezone}</timeZone></Time>')


def ntp_body(server: str) -> str:
    return (f'{_XML}<NTPServer><id>1</id>'
            f'<addressingFormatType>ipaddress</addressingFormatType>'
            f'<ipAddress>{server}</ipAddress><portNo>123</portNo>'
            f'<synchronizeInterval>1</synchronizeInterval></NTPServer>')


def ir_body(mode: str) -> str:
    return (f'{_XML}<HardwareService '
            f'xmlns="http://www.isapi.org/ver20/XMLSchema" version="2.0">'
            f'<IrLightSwitch><mode>{mode}</mode></IrLightSwitch>'
            f'</HardwareService>')


def third_stream_body(enabled: bool) -> str:
    return ('<SoftwareService><ThirdStream><enabled>'
            f'{"true" if enabled else "false"}'
            '</enabled></ThirdStream></SoftwareService>')


def stream_bodies(name: str, audio: bool,
                  stream3: str = DEFAULT_STREAM3) -> dict[str, str]:
    """The three streaming profiles for one camera, keyed by channel id."""
    width, height = size(stream3)
    main = (
        f'{_XML}<StreamingChannel '
        'xmlns="http://www.isapi.org/ver20/XMLSchema" version="2.0">'
        f'<id>101</id><channelName>{name}</channelName>'
        '<enabled>true</enabled><encrypt>off</encrypt>'
        '<Transport><videoSourcePortNo>554</videoSourcePortNo>'
        '<maxPacketSize>1000</maxPacketSize>'
        '<ControlProtocolList><ControlProtocol>'
        '<streamingTransport>RTSP</streamingTransport>'
        '</ControlProtocol></ControlProtocolList>'
        f'<Multicast><enabled>true</enabled>'
        f'<destIPAddress>{MULTICAST_GROUP}</destIPAddress>'
        '<videoDestPortNo>8960</videoDestPortNo>'
        '<audioDestPortNo>8962</audioDestPortNo></Multicast>'
        '<Security><enabled>true</enabled>'
        '<certificateType>digest</certificateType></Security></Transport>'
        f'<Audio><enabled>{"true" if audio else "false"}</enabled>'
        '<audioInputChannelID>1</audioInputChannelID>'
        '<audioCompressionType>AAC</audioCompressionType></Audio>'
        '<Video xmlns=""><enabled>true</enabled>'
        '<videoInputChannelID>1</videoInputChannelID>'
        '<videoCodecType>H.264</videoCodecType>'
        '<videoResolutionWidth>1920</videoResolutionWidth>'
        '<videoScanType>progressive</videoScanType>'
        '<videoResolutionHeight>1080</videoResolutionHeight>'
        '<videoQualityControlType>cbr</videoQualityControlType>'
        '<constantBitRate>4096</constantBitRate>'
        '<maxFrameRate>600</maxFrameRate><GovLength>6</GovLength>'
        '<H264Profile>Main</H264Profile><SVC><enabled>false</enabled></SVC>'
        '<smoothing>50</smoothing>'
        '<SmartCodec><enabled>false</enabled></SmartCodec>'
        '</Video></StreamingChannel>')
    sub = (main.replace(">101<", ">102<").replace(">8960<", ">8964<")
           .replace(">8962<", ">8966<").replace(">1920<", ">320<")
           .replace(">1080<", ">240<").replace(">4096<", ">1024<")
           .replace(">600<", ">1000<").replace(">6<", ">25<"))
    third = (main.replace(">101<", ">103<").replace(">8960<", ">8968<")
             .replace(">8962<", ">8970<").replace(">1920<", f">{width}<")
             .replace(">1080<", f">{height}<").replace(">4096<", ">2048<")
             .replace(">600<", ">2500<").replace(">6<", ">25<"))
    return {"101": main, "102": sub, "103": third}


def proxy_channel_body(channel_id, name: str, ip: str,
                       username: str, password: str, *,
                       include_name: bool = True) -> str:
    """One camera as an NVR input channel.

    Carries the CAMERA's credential: the NVR logs in to the camera itself.
    The value comes from the in-memory credential store and is never written
    to a file or a log line (see panel.credentials).
    """
    root = ET.Element("InputProxyChannel")

    def add(parent, tag: str, value) -> None:
        ET.SubElement(parent, tag).text = str(value)

    add(root, "id", channel_id)
    # The old recorder's own web page includes the name when it POSTs a new
    # channel, but omits it when it PUTs an existing channel.  That firmware
    # rejects the extra PUT field with HTTP 400, so callers choose the shape
    # to match the operation.
    if include_name:
        add(root, "name", name)
    source = ET.SubElement(root, "sourceInputPortDescriptor")
    add(source, "proxyProtocol", "HIKVISION")
    add(source, "addressingFormatType", "ipaddress")
    add(source, "ipAddress", ip)
    add(source, "managePortNo", 8000)
    add(source, "srcInputPort", 1)
    add(source, "userName", username)
    add(source, "password", password)
    add(source, "streamType", "auto")
    # ElementTree escapes text values, including credentials containing '&'
    # or '<'.  Hand-built XML would turn those otherwise valid passwords into
    # malformed input and the recorder would answer HTTP 400.
    return f"{_XML}{ET.tostring(root, encoding='unicode')}"
