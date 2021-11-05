import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from dds.utilities import RedisClient
from typing import Optional
from dds.accounts.models import AdvUser


class HandlerABC(ABC):
    def __init__(self, network, scanner, contract=None) -> None:
        self.network = network
        self.scanner = scanner
        self.contract = contract

    def get_owner(self, owner_address: str) -> Optional[AdvUser]:
        return AdvUser.objects.filter(username=owner_address).first()

    @abstractmethod
    def save_event(self) -> None:
        ...


class ScannerABC(ABC):
    def __init__(self, network, contract_type=None, contract=None):
        self.network = network
        self.contract_type = contract_type
        self.contract = contract

    def sleep(self) -> None:
        # TODO: from config
        time.sleep(1)

    def save_last_block(self, name, block) -> None:
        redis_ = RedisClient()
        redis_.connection.set(name, block)

    def get_last_block(self, name) -> int:
        redis_ = RedisClient()
        last_block_number = redis_.connection.get(name)
        if last_block_number is None:
            last_block_number = self.get_last_network_block()
            self.save_last_block(name, last_block_number)
        return int(last_block_number)


    @abstractmethod
    def get_last_network_block(self) -> int:
        ...


@dataclass
class DeployData:
    collection_name: str
    address: str
    deploy_block: int


@dataclass
class BuyData:
    buyer: str
    seller: str
    price: float
    amount: int
    token_id: int
    tx_hash: str
    collection_address: str


@dataclass
class ApproveData:
    exchange: str
    user: str
    wad: int


@dataclass
class MintData:
    token_id: int
    new_owner: str
    old_owner: str
    tx_hash: str
    amount: int
