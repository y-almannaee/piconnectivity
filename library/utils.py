from typing import Literal, Dict, Callable, List, Union
from secrets import token_bytes
from enum import Enum
import numpy as np
from asyncio.queues import Queue
import asyncio, asyncpio
import struct, sys
from dataclasses import dataclass

ENDIANNESS: Literal["little", "big"] = "little"


@dataclass
class Frame_Header:
    """Represents the header of a frame"""

    sender_id: int
    recipient_id: int
    length: int
    sequence: bytes
    ack: bool

    @classmethod
    def from_bytes(cls, data: bytes):
        """Create header from bytes"""
        if data[5] not in [0, 255]:
            raise ValueError("ack bit not valid")
        return cls(
            sender_id=data[0],
            recipient_id=data[1],
            length=data[2],
            sequence=data[3:5],
            ack=bool(data[5]),
        )

    @classmethod
    def min_for_header(cls):
        return 7

    @classmethod
    def start_byte(cls):
        return 6

    @property
    def total_frame_length(self) -> int:
        """Calculate total frame length including metadata and checksums"""
        return (
            1  # Sender byte
            + 1  # Recipient byte
            + 1  # Length byte
            + 2  # Sequence
            + 1  # Ack byte
            + 1  # Start byte (255)
            + self.length  # Payload
            + 2  # Checksum
            + 1  # Stop byte (255)
        )


class DTYPES(Enum):
    """Enum for datatypes during transfer and their other properties"""

    # Floating-point types
    half = float16 = ("float16", 2, False, 10)
    float = float32 = ("float32", 4, False, 12)
    float64 = double = ("float64", 8, False, 13)

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
        self.typename = typename  # Human-readable name
        self.size = size  # Byte size of the type
        self.signed = signed  # Whether the type is signed
        self.conversion = conversion  # The integer that is sent in the frame

    @classmethod
    def from_typename(cls, typename: str):
        """Retrieve a datatype from its name"""
        for item in cls:
            if item.typename == typename:
                return item
        raise ValueError(f"Unknown datatype: {typename}")

    @classmethod
    def from_protocol_number(cls, number: "int"):
        """Retrieve a datatype from its protocol-defined number"""
        for item in cls:
            if item.conversion == number:
                return item
        raise ValueError(f"Unknown datatype: {number}")

    def to_bytes(self, value) -> bytes:
        interpret_func = self.np()
        interpreted = interpret_func(value)
        return to_bytes(interpreted)

    def convert(self) -> "int":
        """Convert datatype to a single byte for protocol commands."""
        return self.conversion

    def np(self) -> Callable:
        """Returns a function to convert Python datatypes to numpy types"""
        if self.typename != "char":
            return getattr(np, self.typename)
        else:
            return str

    @classmethod
    def revert(cls, data, datatype) -> "float | int | str | bool":
        bo = "<" if ENDIANNESS == "little" else ">"  # byte order
        if datatype in (DTYPES.int8, DTYPES.int16, DTYPES.int32, DTYPES.int64):
            return int.from_bytes(data, byteorder=ENDIANNESS, signed=True)
        elif datatype in (DTYPES.uint8, DTYPES.uint16, DTYPES.uint32, DTYPES.uint64):
            return int.from_bytes(data, byteorder=ENDIANNESS, signed=False)
        elif datatype == DTYPES.bool:
            return bool(int.from_bytes(data, byteorder=ENDIANNESS))
        elif datatype == DTYPES.char:
            return data.decode()
        elif datatype in (DTYPES.half, DTYPES.float16):
            return struct.unpack(f"{bo}e", data)[0]
        elif datatype in (DTYPES.float, DTYPES.float32):
            return struct.unpack(f"{bo}f", data)[0]
        elif datatype in (DTYPES.double, DTYPES.float64):
            return struct.unpack(f"{bo}d", data)[0]
        else:
            raise ValueError(f"Unsupported datatype: {datatype}")


class Writable_Store:
    value: any = None
    _name: str
    _datatype: DTYPES

    def __init__(self, name, datatype, default_value=None):
        self.value = default_value
        self._name = name
        self._datatype = datatype

    async def read(self):
        return self.value

    def write(self, value):
        self.value = value

    def type(self):
        return self._datatype


class Callable_Store:
    _user_func: callable
    _name: str
    _datatype: DTYPES

    def __init__(self, name, datatype, func: callable):
        self._user_func = func
        self._name = name
        self._datatype = datatype

    # def __getattribute__(self, name: str):
    #     if name == "value":
    #         # If we come a-knockin' for the value
    #         # of this store, just call the command
    #         return self._user_func()
    #     super().__getattribute__(name)

    async def read(self):
        value = await self._user_func()
        return value

    def write(self):
        raise Exception(f"Store {self._name} cannot be written to")

    def type(self):
        return self._datatype


class Device:
    id: int
    chain: List[List["Device"]]
    iface: str

    def __init__(self, id: int, chain: List[int], iface: str):
        self.id = id
        self.chain = chain
        self.iface = iface
        if id in State().awaiting_connection:
            State().awaiting_connection[id].set()

    def update(self, new_chain):
        """Updates the chain and interface if distance is shorter"""
        pass

    def distance(self):
        """Finds distance to node"""
        return len(self.chain)


class State:
    """Singleton that manages the state"""

    _instance = None
    shutdown: asyncio.Event  # whether the network is shutting down
    pi: asyncpio.pi
    device_id: int  # the current device ID
    store: Dict[str, Writable_Store | Callable_Store] = {}
    other_devices: Dict[int, Device] = {}  # Dict of other devices
    awaiting_connection: Dict[int, asyncio.Event] = {}
    futures: Dict[str, asyncio.Future] = {}
    scheduled_tasks = []
    tasks: Dict[str, Queue] = {
        "uart": Queue(),
        "iic": Queue(),
        "spi": Queue(),
    }

    def __new__(cls):
        if cls._instance is None:
            print("Initializing the state")
            cls._instance = super(State, cls).__new__(cls)
            # Initialization
            cls._instance.shutdown = asyncio.Event()
            cls._instance.shutdown.set()
        return cls._instance

    def running(self) -> None:
        return not self.shutdown.is_set()

    async def start_pi(self) -> None:
        self.pi = asyncpio.pi()
        try:
            await self.pi.connect()
            self.shutdown.clear()
        except:
            print("Failure to connect")
            exit(1)


def to_bytes(data: any, length=None) -> bytes:
    """Returns the correctly ordered bytes for data types"""
    if isinstance(data, np.ndarray) or isinstance(data, np.generic):
        if ENDIANNESS == sys.byteorder:
            return data.tobytes()
        else:
            return data.byteswap().tobytes()
    if isinstance(data, int):
        if length is None:
            blen = data.bit_length() if data.bit_length() != 0 else 1
            return data.to_bytes((blen + 7) // 8, byteorder=ENDIANNESS)
        else:
            return data.to_bytes(length, byteorder=ENDIANNESS)
    raise TypeError("Unsupported type for to_bytes")


def from_bytes(data: bytes, datatype: DTYPES) -> "any":
    """Convert received bytes to appropriate Python type"""
    return DTYPES.revert(data, datatype)


def add_metadata(
    recipient_id: int,
    message: bytes,
    sequence: bool = True,
    chk: bool = True,
    ack: bool = True,
) -> bytearray:
    """
    Take a message and adds the necessary metadata to it to complete the frame.
    """
    frame: bytearray = bytearray()
    msg_sender = to_bytes(State().device_id)
    msg_recipient = to_bytes(recipient_id)
    if isinstance(message, bytearray):
        message = bytes(message)
    if not isinstance(message, bytes):
        raise TypeError("Message should be a bytes object")
    msg_len = to_bytes(len(message))
    # Nonce calculation does not have to be the same across implementations, just needs to ensure that it is reasonably
    # random. Below code takes the current Unix time down to 2 decimal places, then hashes it down to 1 byte using Blake2b
    msg_sequence = token_bytes(2) if sequence else to_bytes(0, length=2)
    msg_ack = to_bytes(255) if ack else to_bytes(0)
    msg_start = to_bytes(255)
    frame += (
        msg_sender
        + msg_recipient
        + msg_len
        + msg_sequence
        + msg_ack
        + msg_start
        + message
    )
    # Calculates the checksum then appends the modulo and remainder of it to the message, as well as the 255 stop byte
    if chk:
        msg_checksum = sum(frame)
        frame.extend((msg_checksum // 256, msg_checksum % 256, 255))
    else:
        frame.extend((0, 0, 255))
    return frame


def put(payload: bytes) -> None:
    """
    Handle the "put" command.
    Updates a variable with the specified name, datatype, and value.
    """
    if payload[0] != 6:
        raise Exception("Not a put command.")

    if len(payload) < 3:
        raise Exception("Invalid payload for put command.")

    # Extract variable name length and name
    name_length = payload[1]
    name = payload[2 : 2 + name_length].decode()

    print(f"Request to put in store '{name}'")

    # Extract datatype and value
    datatype = payload[2 + name_length + 1]
    datatype = DTYPES.from_protocol_number(datatype)
    value_data = payload[2 + name_length + 2 :]
    value = DTYPES.revert(value_data, datatype)

    # Update the variable in state
    if name not in State().store:
        raise Exception(f"Store '{name}' not found in state")

    if State().store[name].type() != datatype:
        raise Exception(f"Store '{name}' not of type {datatype}")

    State().store[name].write(value)
    print(f"Updated store '{name}' with value {value}")


async def get(payload: bytes) -> tuple[DTYPES, bytes]:
    if payload[0] != 7:
        raise Exception("Not a get command.")

    if len(payload) < 3:
        raise Exception("Invalid payload for get command.")

    # Extract variable name length and name
    name_length = payload[1]
    name = payload[2 : 2 + name_length].decode()

    try:
        value = await State().store[name].read()
    except KeyError:
        value = None
    datatype = State().store[name].type()
    return datatype, value
