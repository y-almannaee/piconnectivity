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
)
from .protocols import start_UART


def available_as(variable_name: str, datatype: DTYPES) -> "None":
    """Exposes the result of some function under a variable name"""

    def inner_decorator(user_function: Callable):
        store = Callable_Store(variable_name, datatype, user_function)
        State().store[variable_name] = store
        return user_function

    return inner_decorator


def define_store(variable_name: str, datatype: DTYPES):
    store = Writable_Store(variable_name, datatype)
    State().store[variable_name] = store
    return store


def schedule(coro: Callable):
    State().scheduled_tasks.append(coro())


async def get(
    device_id: int,
    name: str,
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

    try:
        device = State().other_devices[device_id]
    except KeyError:
        raise Exception(f"Device with ID {device_id} doesn't exist")
    protocol = device.iface
    payload = bytearray()
    payload.extend((7, len(name)))
    payload.extend(name.encode())
    frame = add_metadata(device.id, payload)
    sequence = bytes(frame[3:4])
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    State().futures[sequence] = future
    State().tasks[protocol].put_nowait(frame)
    return future


async def put(device_id: int, name: str, datatype: DTYPES, value: any):
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

    try:
        device = State().other_devices[device_id]
    except KeyError:
        raise Exception(f"Device with ID {device_id} doesn't exist")
    protocol = device.iface
    payload = bytearray()
    payload.extend((6, len(name)))
    payload.extend(name.encode())
    payload.extend((datatype.convert()))
    interp_func = datatype.np()
    converted_value = interp_func(value)
    payload.extend(to_bytes(converted_value))
    frame = add_metadata(device.id, payload)
    State().tasks[protocol].put_nowait(frame)


async def wait_for_connect(device_id: int):
    State().awaiting_connection[device_id] = asyncio.Event()
    await State().awaiting_connection[device_id].wait()


def start_network(device_id: int = None) -> "None":
    """
    Begin searching for connections.

    Args:
            device_id (int): Value in the range of [8, 119] assigned to the current device
    """
    # IDs 0 is reserved for a broadcast
    # ID 248-255 is reserved for higher addressing modes
    if device_id is None:
        device_id = randint(8, 119)
    if (device_id > 0x77) or (device_id < 8):
        raise Exception(
            f"Device ID {device_id} is reserved.\nEnsure address is between 8 and 119 (inclusive of endpoints)"
        )
    if State().running() is True:
        raise Exception(
            "Network already running\nCan't run two networks from the same device"
        )
    State().device_id = device_id
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_main())
    except KeyboardInterrupt:
        print("Stopping...")


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
    for task in State().scheduled_tasks:
        asyncio.get_running_loop().create_task(task)
    await State().shutdown.wait()
    # TODO: Serial when RX is high


if __name__ == "__main__":
    start_network()
