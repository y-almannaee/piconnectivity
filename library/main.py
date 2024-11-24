import asyncpio, asyncio
import serial_asyncio_fast as serial_asyncio
import numpy as np
from serial import EIGHTBITS, PARITY_EVEN, STOPBITS_TWO
from typing import Literal, Callable, Dict
from enum import Enum
from secrets import token_bytes
from time import time
from random import randint
from functools import wraps

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

class UART_Handler_Protocol(asyncio.Protocol):
	def connection_made(self, transport):
		self.transport = transport

	def data_received(self, data):
		print('data received', repr(data))

class DTYPES(Enum):
	# Floating-point types
	half = ("half", 2, False, 10)
	float = float32 = ("float", 4, False, 12)
	float64 = double = ("double", 8, False, 13)

	# Signed integers
	int8 = ("int8", 1, True, 20)
	int16 = short = ("int16", 2, True, 21)
	int = int32 = ("int32", 4, True, 22)
	long = int64 = ("int64", 8, True, 23)

	# Unsigned integers
	uint8 = ("uint8", 1, False, 25)
	uint16 = ushort = ("uint16", 2, False, 26)
	uint = uint32 = ("uint32", 4, False, 27)
	ulong = uint64 = ("uint64", 8, False, 28)

	# Char and Bool
	char = ("char", 1, False, 30)
	bool = ("bool", 1, False, 31)

	def __init__(self, typename, size, signed, conversion):
		self.typename = typename				# Human-readable name
		self.size = size						# Byte size of the type
		self.signed = signed					# Whether the type is signed
		self.conversion = conversion	# The integer that is sent in the frame

	@classmethod
	def from_typename(cls, typename: str):
		"""Retrieve a datatype from its name."""
		for item in cls:
			if item.typename == typename:
				return item
		raise ValueError(f"Unknown datatype: {typename}")

	def convert(self) -> 'int':
		"""Convert datatype to a single byte for protocol commands."""
		return self.conversion

	def to_dict(self):
		"""Get a dictionary representation of the datatype."""
		return {"typename": self.typename, "size": self.size, "signed": self.signed}

class State():
	running: bool						# whether the network is running
	device_id: int						# the current device ID
	variables: Dict[str, Callable]		# a KV pair of variable names and a callable that returns the variable's value
	cache: Dict[str, any]				# cache for received variable values

	def __init__(self):
		self.running = False
		self.variables = {}
		self.cache = {}

module_state = [State()]

def to_bytes(data: any) -> bytes:
	'''Returns the correctly ordered bytes for data types'''
	if isinstance(data, np.ndarray) or isinstance(data, np.generic):
		if ENDIANNESS == 'little':
			return data.byteswap().tobytes()
		else:
			return data.tobytes()
	if isinstance(data, int):
		return data.to_bytes((data.bit_length() + 7) // 8, byteorder=ENDIANNESS)
	raise TypeError("Unsupported type for to_bytes")

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
	msg_len = len(message).to_bytes(1, byteorder=ENDIANNESS)
	# Nonce calculation does not have to be the same across implementations, just needs to ensure that it is reasonably
	# random. Below code takes the current Unix time down to 2 decimal places, then hashes it down to 1 byte using Blake2b
	msg_nonce = token_bytes(1) if nonce else (0).to_bytes(1, byteorder=ENDIANNESS)
	msg_ack = (255).to_bytes(1, byteorder=ENDIANNESS) if ack else (0).to_bytes(1, byteorder=ENDIANNESS)
	msg_start = (255).to_bytes(1, byteorder=ENDIANNESS)
	frame+=msg_len+msg_nonce+msg_ack+msg_start+message
	# Calculates the checksum then appends the modulo and remainder of it to the message, as well as the 255 stop byte
	if chk:
		msg_checksum = sum(frame)
		frame.extend((msg_checksum//256, msg_checksum%256, 255))
	else:
		frame.extend((0,0,255))
	return frame

def available_as(variable_name: str) -> 'None':
	'''Exposes the result of some function under a variable name'''
	def inner_decorator(user_function: Callable):
		for key in module_state[0].variables:
			if key.startswith(variable_name):
				raise Exception("Can't create a variable with a name that matches another variable's, or the beginning of another variable's\ne.g. neither variable T nor variable Temp can be added when another variable Temperature is already registered")
		module_state[0].variables[variable_name] = user_function
		return user_function
	return inner_decorator

async def get(other_device_id: int,
	name: str,
	datatype: Literal[DTYPES.bool, DTYPES.char],
	protocol_send: Callable,
	protocol_receive: Callable,
	timeout: float = 2.0,) -> any:
	"""
	Gets a variable with a specific name, datatype from another MCU.

	Args:

	Raises:
	"""
	state = module_state[0]
	
	if not state.running:
		raise Exception("Network is not running. Start the network before getting data.")
	
	if name in state.cache:
		# Return cached value if available
		return state.cache[name]

	command = f"7{datatype.convert()}{name}".encode()
	frame = add_metadata(command)
	await protocol_send(frame)

	try:
		response_frame = await asyncio.wait_for(protocol_receive(), timeout=timeout)
	except asyncio.TimeoutError:
		raise TimeoutError("No response received within timeout")

	payload = response_frame[5:-4]
	if datatype in (DTYPES.int8, DTYPES.int16, DTYPES.int32, DTYPES.int64):
		result = int.from_bytes(payload, byteorder=ENDIANNESS)
	elif datatype == DTYPES.bool:
		result = bool(int.from_bytes(payload, byteorder=ENDIANNESS))
	elif datatype == DTYPES.char:
		result = payload.decode()
	else:
		raise ValueError("Unsupported datatype")
	
	# Cache the result
	state.cache[name] = result
	return result

async def put(other_device_id: int, name: str, datatype: DTYPES, value: any):
	"""
	Sends a variable with a specific name, datatype, and value to another MCU.

	Args:
		other_device_id (int): The device ID of the target MCU.
		name (str): The name of the variable to send.
		datatype (DTYPES): The datatype of the variable to send.
		value (any): The value of the variable to send.

	Raises:
		ValueError: If the datatype does not match the value.
		TypeError: If value cannot be converted to bytes.
		Exception: If the network is not running.
	"""
	if not module_state[0].running:
		raise Exception("Network is not running. Start the network before sending data.")

	# Ensure the datatype matches the value
	try:
		value_bytes = to_bytes(value)
	except Exception as e:
		raise TypeError(f"Failed to convert value to bytes: {e}")

	if len(value_bytes) != datatype.size:
		raise ValueError(f"The value does not match the expected size for datatype {datatype.typename}.")

	# Construct the message
	command = "put"
	name_bytes = name.encode("utf-8")  # Encode the variable name
	name_len = len(name_bytes).to_bytes(1, ENDIANNESS)  # 1-byte length of the name
	datatype_code = datatype.code.to_bytes(1, ENDIANNESS)  # 1-byte datatype code
	target_device_id = other_device_id.to_bytes(1, ENDIANNESS)  # 1-byte device ID

	# Assemble the message: [target ID, command, name_len, name, datatype_code, value]
	payload = (
		target_device_id +
		command.encode("utf-8") +
		name_len +
		name_bytes +
		datatype_code +
		value_bytes
	)

	# Add metadata and send the frame
	frame = add_metadata(payload, nonce=True, chk=True, ack=True)

	# Send the frame through the appropriate protocol handler
	if hasattr(module_state[0], "protocol"):
		transport = module_state[0].protocol.transport
		transport.write(frame)
	else:
		raise Exception("No protocol handler available for sending data.")

def start_network(device_id: int = None) -> 'None':
	'''
	Begin searching for connections.

	Args:
		device_id (int): Value between 1 and 247 assigned to the current device
	'''
	# IDs 0 is reserved for a broadcast
	# ID 248-255 is reserved for higher addressing modes
	if module_state[0].running is True:
		raise Exception("Network already running\nCan't run two networks from the same device")
	if device_id is None:
		device_id = randint(1,247)
	pi = asyncpio.pi()
	module_state[0].device_id = device_id
	loop = asyncio.get_event_loop()
	loop.run_until_complete(main(pi,module_state[0]))

async def main(pi: asyncpio.pi, state: State) -> 'None':
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
	uart_pin_coro = serial_asyncio.create_serial_connection(
		loop, 
		UART_Handler_Protocol, 
		serial_pins, 
		baudrate=SERIAL_BAUDRATE, 
		bytesize=SERIAL_BYTESIZE, 
		parity=SERIAL_PARITY, 
		stopbits=SERIAL_STOPBITS, 
		timeout=SERIAL_TIMEOUT
	)
	loop.create_task(uart_pin_coro)
	while(True):
		await asyncio.sleep(3)
	# TODO: Serial when RX is high

if __name__ == "__main__":
	start_network()