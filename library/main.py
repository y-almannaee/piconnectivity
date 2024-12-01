import asyncpio, asyncio
import numpy as np
from typing import Literal, Callable
from random import randint
from .utils import (
    State,
    DTYPES,
    add_metadata,
    to_bytes,
    from_bytes,
    ENDIANNESS,
    Writable_Store,
    Callable_Store,
    send_to,
    receive_from,
)
from .protocols import start_UART


def available_as(variable_name: str, datatype: DTYPES) -> "None":
    """Exposes the result of some function under a variable name"""

    def inner_decorator(user_function: Callable):
        store = Callable_Store(variable_name, datatype, user_function)
        State().store.append(store)
        return user_function

    return inner_decorator


def define_store(variable_name: str, datatype: DTYPES):
    store = Writable_Store(variable_name, datatype)
    State().store.append(store)
    return store


def schedule(coro: Callable):
    asyncio.get_event_loop().create_task(coro())


async def get(
    other_device_id: int,
    name: str,
    datatype: DTYPES,
    timeout: float = 2.0,
) -> any:
    """
    Gets a variable with a specific name, datatype from another MCU.

    Args:

    Raises:
    """

    if not State().running():
        raise Exception(
            "Network is not running. Start the network before getting data."
        )

    command = f"7{datatype.convert()}{name}".encode()
    frame = add_metadata(command)
    await send_to(other_device_id, frame)

    try:
        response_frame = await receive_from(other_device_id, timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError("No response received within timeout")

    payload = response_frame[5:-4]
    result = from_bytes(payload, datatype)

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
    if not State().running():
        raise Exception(
            "Network is not running. Start the network before sending data."
        )

    # Ensure the datatype matches the value
    try:
        value_bytes = to_bytes(value)
    except Exception as e:
        raise TypeError(f"Failed to convert value to bytes: {e}")

    if len(value_bytes) != datatype.size:
        raise ValueError(
            f"The value does not match the expected size for datatype {datatype.typename}."
        )

    # Construct the message
    command = "put"
    name_bytes = name.encode("utf-8")  # Encode the variable name
    name_len = len(name_bytes).to_bytes(1, ENDIANNESS)  # 1-byte length of the name
    datatype_code = datatype.code.to_bytes(1, ENDIANNESS)  # 1-byte datatype code
    target_device_id = other_device_id.to_bytes(1, ENDIANNESS)  # 1-byte device ID

    # Assemble the message: [target ID, command, name_len, name, datatype_code, value]
    payload = (
        target_device_id
        + command.encode("utf-8")
        + name_len
        + name_bytes
        + datatype_code
        + value_bytes
    )

    # Add metadata and send the frame
    frame = add_metadata(payload, sequence=True, chk=True, ack=True)

    # Send the frame through the appropriate protocol handler
    if hasattr(State(), "protocol"):
        transport = State().protocol.transport
        transport.write(frame)
    else:
        raise Exception("No protocol handler available for sending data.")


def start_network(device_id: int = None) -> "None":
    """
    Begin searching for connections.

    Args:
            device_id (int): Value in the range of [8, 119] assigned to the current device
    """
    # IDs 0 is reserved for a broadcast
    # ID 248-255 is reserved for higher addressing modes
    if (device_id > 0x77) or (device_id < 8):
        raise Exception(
            f"Device ID {device_id} is reserved.\nEnsure address is between 8 and 119 (inclusive of endpoints)"
        )
    if State().running() is True:
        raise Exception(
            "Network already running\nCan't run two networks from the same device"
        )
    if device_id is None:
        device_id = randint(8, 119)
    State().device_id = device_id
    loop = asyncio.get_event_loop()
    loop.run_until_complete(_main())


def stop_network() -> "None":
    pass


async def _main() -> "None":
    await State().start_pi()
    hardware_rev = await State().pi.get_hardware_revision()
    print(f"Running on RPi hdw. rev. {format(hardware_rev,'#0x')}")

    # Register the handlers for various protocols
    # Serial UART
    serial_pins = "/dev/serial0"
    # serial_usb = '/dev/ttyUSB0'
    await start_UART(serial_pins)
    await State().shutdown.wait()
    # TODO: Serial when RX is high


if __name__ == "__main__":
    start_network()
