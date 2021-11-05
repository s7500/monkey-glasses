from scanners.base import ScannerABC
from scanners.eth.mixins import DeployMixin, ApproveMixin, BuyMixin, MintMixin


class Scanner(
    ScannerABC,
    DeployMixin,
    ApproveMixin,
    BuyMixin,
    MintMixin,
):
    EMPTY_ADDRESS = "0x0000000000000000000000000000000000000000"

    def get_last_network_block(self) -> int:
        return self.network.get_web3_connection().eth.blockNumber

