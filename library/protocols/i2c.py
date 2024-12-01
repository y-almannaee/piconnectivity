import asyncio, asyncpio
import numpy as np
from typing import Optional
from ..utils import DTYPES, ENDIANNESS, Frame_Header, Device, add_metadata
from serial import EIGHTBITS, PARITY_ODD, STOPBITS_TWO
import serial_asyncio_fast as serial_asyncio
from ..utils import State

async def start_i2c(pi: asyncpio.pi):
    loop = asyncio.get_event_loop()
    pi.bsc_i2c()