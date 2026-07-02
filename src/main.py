import asyncio
from viam.module.module import Module
from models.labjack_t7 import LabJackT7  # noqa: F401

if __name__ == "__main__":
    asyncio.run(Module.run_from_registry())
