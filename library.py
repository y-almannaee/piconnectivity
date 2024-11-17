import asyncpio, asyncio
import serial_asyncio_fast as serial_asyncio
from serial import EIGHTBITS, PARITY_EVEN, STOPBITS_TWO
from typing import Literal
from enum import Enum
from hashlib import blake2b
from time import time
import numpy as np

# Raspberry Pi 4B reference pinout from https://pinout.xyz/

# disable the Serial Console in raspi-config before using UART
PI_SERIAL_TX: int = 14 # UART Serial TX on BCM pin 14
PI_SERIAL_RX: int = 15 # UART Serial RX on BCM pin 15

# https://pyserial.readthedocs.io/en/latest/pyserial_api.html#serial.Serial
SERIAL_BAUDRATE: int = 9600
SERIAL_BYTESIZE = EIGHTBITS
SERIAL_PARITY = PARITY_EVEN
SERIAL_STOPBITS = STOPBITS_TWO
SERIAL_TIMEOUT: int = 15 # in seconds

ENDIANNESS: Literal['little','big'] = 'little'

class PROTOCOL_DATATYPES(Enum):
	# FP
	half = float16 = 10
	float = float32 = 12
	float64 = double = 13
	# Ints
	int8 = 20
	int16 = short = 21
	int = int32 = 22
	long = int64 = 23
	# Uints
	uint8 = 25
	uint16 = ushort = 26
	uint = uint32 = 27
	ulong = uint64 = 28
	# Char
	char = 30
	# Bool
	bool = 31

def to_bytes(data: any) -> bytes:
	'''Returns the correctly ordered bits for data types'''
	if isinstance(data, np.ndarray) or isinstance(data, np.generic):
		data.dtype.newbyteorder(ENDIANNESS)
		return data.tobytes()

def add_metadata(message: bytes, nonce: bool = True, chk: bool = True, ack: bool = True) -> bytearray:
	'''
	Take a message and adds the necessary metadata to it to complete the frame.

	Args:
		message (bytes): The message to send, converted to bytes
		nonce (bool): Whether to include the time-based nonce or leave it empty
		chk (bool): Whether to calculate the two-byte checksum or leave it empty
		ack (bool): Whether to request an acknowledgement

	Returns:
		bytearray: The complete frame ready to send
	'''
	frame: bytearray = bytearray()
	if not isinstance(message,bytes):
		raise TypeError("Message should be a bytes object")
	msg_len = len(message).to_bytes()
	# Nonce calculation does not have to be the same across implementations, just needs to ensure that it is reasonably
	# random. Below code takes the current Unix time down to 2 decimal places, then hashes it down to 1 byte using Blake2b
	msg_nonce = blake2b("{:.2f}".format(time.time()).encode(),digest_size=1).digest() if nonce else (0).to_bytes()
	msg_ack = (255).to_bytes() if ack else (0).to_bytes()
	msg_start = (255).to_bytes()
	frame+=msg_len+msg_nonce+msg_ack+msg_start+message
	# Calculates the checksum then appends the modulo and remainder of it to the message, as well as the 255 stop byte
	if chk:
		msg_checksum = sum(frame)
		frame.extend((msg_checksum//256, msg_checksum%256, 255))
	else:
		frame.extend((0,0,255))
	return frame

class InputChunkProtocol(asyncio.Protocol):
	def connection_made(self, transport):
		self.transport = transport

	def data_received(self, data):
		print('data received', repr(data))

async def available_as(user_function: function, variable_name: str) -> 'None':
	'''Exposes the result of some function under a variable name'''
	pass

def start_network() -> 'None':
	pi = asyncpio.pi()
	loop = asyncio.get_event_loop()
	loop.run_until_complete(main(pi))

async def main(pi: asyncpio.pi) -> 'None':
	try:
		await pi.connect()
	except:
		print("Failure to connect")
		exit(1)
	hardware_rev = await pi.get_hardware_revision()
	print(f"Running on RPi hdw. rev. {format(hardware_rev,'#0x')}")
	
	# Register the handlers for various protocols
	# Serial UART
	loop = asyncio.get_running_loop()
	serial_pins = '/dev/serial0'
	# serial_usb = '/dev/ttyUSB0'
	uart_pin_coro = serial_asyncio.create_serial_connection(loop, InputChunkProtocol, serial_pins, 
			                       baudrate=SERIAL_BAUDRATE, bytesize=SERIAL_BYTESIZE, parity=SERIAL_PARITY, 
								   stopbits=SERIAL_STOPBITS, timeout=SERIAL_TIMEOUT)
	loop.create_task(uart_pin_coro)
	while(True):
		await asyncio.sleep(3)
	# TODO: Serial when RX is high

if __name__ == "__main__":
	start_network()