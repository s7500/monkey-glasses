import requests
from scanners.base import DeployData, BuyData, ApproveData, MintData
from tronapi import Tron

class DeployMixin:
    def get_events_deploy(self, last_checked_block, last_network_block):
        type_match = {
            'ERC721': ['fabric721_address', 'ERC721Made'],
            'ERC1155': ['fabric1155_address', 'ERC115Made'],
        }
        collection_data = type_match[self.contract_type]
        collection_address = getattr(self.network, collection_data[0])
        event_name = collection_data[1]
        url = self.build_tronapi_url(last_checked_block, last_network_block, collection_address, event_name)
        events = requests.get(url).json()['data']
        return events

    def parse_data_deploy(self, event) -> DeployData:
        tron = Tron()
        return DeployData(
            collection_name=event["result"]["name"],
            address=tron.address.from_hex(event["result"]["newToken"].replace('0x', '41')).decode(),
            deploy_block=event["block_number"],
        )


class BuyMixin:
    def get_events_buy(self, last_checked_block, last_network_block):
        type_match = {
            'ERC721': ['exchange_address', 'ExchangeMadeErc721'],
            'ERC1155': ['exchange_address', 'ExchangeMadeErc1155'],
        }
        collection_data = type_match[self.contract_type]
        collection_address = getattr(self.network, collection_data[0])
        event_name = collection_data[1]
        url = self.build_tronapi_url(last_checked_block, last_network_block, collection_address, event_name)
        events = requests.get(url).json()['data']
        return events

    def parse_data_buy(self, event) -> BuyData:
        return BuyData(
            buyer=event["result"]["buyer"].lower(),
            seller=event["result"]["seller"],
            price=event["result"]["buyAmount"],
            amount=event["result"]["sellAmount"],
            tx_hash=event["transaction_id"].hex(),
            token_id=event["result"]["sellId"],
            collection_address=event["result"]["sellTokenAddress"],
        )


class ApproveMixin:
    def get_events_approve(self, last_checked_block, last_network_block):
        collection_address = self.contract.address
        event_name = 'Approval'
        url = self.build_tronapi_url(last_checked_block, last_network_block, collection_address, event_name)
        events = requests.get(url).json()['data']

        return events

    def parse_data_approve(self, event) -> ApproveData:
        return ApproveData(
            exchange=event["result"]["guy"],
            user=event["result"]["src"].lower(),
            wad=event["result"]["wad"],
        )


class MintMixin:
    def get_events_mint(self, last_checked_block, last_network_block):
        collection_address = self.contract.address

        event_name = 'Transfer'
        url = self.build_tronapi_url(last_checked_block, last_network_block, collection_address, event_name)
        events = requests.get(url).json()['data']
        return events

    def parse_data_mint(self, event) -> MintData:
        token_id = event["result"].get("tokenId")
        if token_id is None:
            token_id = event["result"].get("id")
        return MintData(
            token_id=token_id,
            new_owner=event["result"]["to"].lower(),
            old_owner=event["result"]["from"].lower(),
            tx_hash=event["transaction_id"].hex(),
            amount=event["result"]["value"],
        )
