import asyncpio, asyncio
import serial_asyncio_fast as serial_asyncio
from serial import EIGHTBITS, PARITY_EVEN, STOPBITS_TWO
from typing import Literal
from enum import Enum
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

def get_metadata(message: any, nonce: bool = True, chk: bool = True, ack: bool = True, start: bool = True):
	'''Before the body of the message is sent, the following are communicated using this metadata:
		- the message length
		- the nonce of this message (used to ensure that this message is new and not rebroadcasted on the receiver end)
		- the chk for this message
		- a request for acknowledgement
		- a message start sequence'''
	pass

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