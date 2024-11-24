from typing import Literal, Dict, Callable, List
from secrets import token_bytes
from enum import Enum
import numpy as np
from asyncio.queues import Queue
import struct

ENDIANNESS: Literal['little','big'] = 'little'

class DTYPES(Enum):
	'''Enum for datatypes during transfer and their other properties'''
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

class writable_store():
	_value: any = None
	_name: str
	_datatype: DTYPES

	def __init__(self, name, datatype, default_value=None):
		self._value = default_value
		self._name = name
		self._datatype = datatype

class device():
	id: int
	chain: List[int]
	last_link: str
	iface: str

	def __init__(self, id: int, chain: List[int], last_link: str, iface: str):
		self.id = id
		self.chain = chain
		self.last_link = last_link
		self.iface = iface

class State():
	'''Singleton that manages the state'''
	_instance = None
	running: bool						# whether the network is running
	device_id: int						# the current device ID
	readables: Dict[str, Callable]		# a KV pair of variable names and a callable that returns the variable's value
	writables: List[writable_store]		# KV pair of variable name and data with type any
	other_devices: List[device]			# List of other devices
	tasks: Dict[str, Queue] = {
		"uart": Queue(),
		"iic": Queue(),
		"spi": Queue(),
	}

	def __new__(cls):
		if cls._instance is None:
			print('Initializing the state')
			cls._instance = super(State, cls).__new__(cls)
			# Initialization
			cls._instance.running = False
			cls._instance.readables = {}
			cls._instance.writables = []
			cls._instance.other_devices = []
		return cls._instance
	
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

def from_bytes(data: bytes, datatype: DTYPES) -> 'any':
	"""Convert received bytes to appropriate Python type"""
	bo = '<' if ENDIANNESS == 'little' else '>' # byte order
	if datatype in (DTYPES.int8, DTYPES.int16, DTYPES.int32, DTYPES.int64):
		return int.from_bytes(data, byteorder=ENDIANNESS, signed=True)
	elif datatype in (DTYPES.uint8, DTYPES.uint16, DTYPES.uint32, DTYPES.uint64):
		return int.from_bytes(data, byteorder=ENDIANNESS, signed=False)
	elif datatype == DTYPES.bool:
		return bool(int.from_bytes(data, byteorder=ENDIANNESS))
	elif datatype == DTYPES.char:
		return data.decode()
	elif datatype in (DTYPES.float, DTYPES.float32):
		return struct.unpack(f"{bo}f", data)[0]
	elif datatype in (DTYPES.double, DTYPES.float64):
		return struct.unpack(f"{bo}d", data)[0]
	else:
		raise ValueError(f"Unsupported datatype: {datatype}")

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

async def send_to(id, frame, timeout=2.0) -> None | bool:
	pass

async def receive_from(id, timeout=2.0) -> None | bool:
	pass