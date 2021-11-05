import time
import os
import sys
import traceback
from dds.networks.models import Network, Types
from scanners.eth.scanner import Scanner as EthereumScanner
from scanners.tron.scanner import Scanner as TronScanner

base_dir = "blocks"


def get_last_block(name, network_name) -> int:
    try:
        with open(os.path.join(base_dir, name), "r") as file:
            last_block_number = file.read()
    except FileNotFoundError:
        network = Network.objects.get(name=network_name)
        w3 = network.get_web3_connection()
        last_block_number = w3.eth.block_number
        save_last_block(last_block_number, name)

    return int(last_block_number)


def save_last_block(last_block_number, network_name):
    with open(os.path.join(base_dir, network_name), "w") as file:
        file.write(str(last_block_number))


def get_scanner(network, contract_type=None, contract=None):
    # TODO: refactor
    if network.network_type == Types.ethereum:
        return EthereumScanner(network, contract_type, contract=contract)
    if network.network_type == Types.tron:
        return TronScanner(network, contract_type, contract=contract)


def never_fall(func):
    def wrapper(*args, **kwargs):
        while True:
            try:
                func(*args, **kwargs)
            except Exception as e:
                print(
                    "\n".join(traceback.format_exception(*sys.exc_info())),
                    flush=True,
                )
                time.sleep(60)

    return wrapper
