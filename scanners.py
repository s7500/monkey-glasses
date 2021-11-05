from loguru import logger
import threading
from decimal import Decimal

from dds.accounts.models import AdvUser
from dds.activity.models import BidsHistory, TokenHistory
from dds.store.models import Collection, Status, Token, Ownership, Bid
from dds.store.services.ipfs import get_ipfs
from dds.networks.models import Network
from django.db.models import F

from scanners.utils import get_scanner, never_fall
from scanners.base import HandlerABC


class ScannerAbsolute(threading.Thread):
    """
    ScannerAbsolute launches a scanner of the appropriate type
    depending on the network and calls the resulting handler.
    """

    def __init__(
        self,
        network: Network,
        handler: object,
        contract_type: str = None,
        contract: object = None,
    ) -> None:
        super().__init__()
        self.network = network
        self.handler = handler
        self.contract_type = contract_type  # ERC721/ ERC1155
        self.contract = contract

    def run(self):
        self.start_polling()

    @property
    def block_name(self) -> str:
        name = f"{self.handler.TYPE}_{self.network.name}"
        name += f"_{self.contract.address}" if self.contract else ""
        name += f"_{self.contract_type}" if self.contract_type else ""
        return name

    @logger.catch
    @never_fall
    def start_polling(self) -> None:
        logger.add(
            f"logs/scanner_{self.handler.TYPE}.log",
            format="{time:DD.MM.YYYY HH:mm:ss} | {level} | {message}",
            enqueue=True,
            level="DEBUG",
        )
        while True:

            scanner = get_scanner(self.network, self.contract_type, self.contract)
            last_checked_block = scanner.get_last_block(self.block_name)
            last_network_block = scanner.get_last_network_block()

            if last_network_block - last_checked_block < 2:
                scanner.sleep()
                continue

            # filter cannot support more than 5000 blocks at one query
            if last_network_block - last_checked_block > 5000:
                last_network_block = last_checked_block + 4990

            handler = self.handler(self.network, scanner, self.contract)
            event_list = getattr(scanner, f"get_events_{handler.TYPE}")(
                last_checked_block,
                last_network_block,
            )
            if event_list:
                list(map(handler.save_event, event_list))
            scanner.save_last_block(self.block_name, last_network_block)
            scanner.sleep()


class HandlerDeploy(HandlerABC):
    TYPE = "deploy"

    def save_event(self, event_data):
        data = self.scanner.parse_data_deploy(event_data)
        logger.debug(f"New event: {data}")

        collection = Collection.objects.filter(
            name__iexact=data.collection_name,
            network=self.network,
        )
        if collection.exists():
            collection.update(
                status=Status.COMMITTED,
                deploy_block=data.deploy_block,
                address=data.address,
            )


class HandlerMintTransferBurn(HandlerABC):
    TYPE = "mint"

    def save_event(self, event_data):
        data = self.scanner.parse_data_mint(event_data)

        try:
            collection = Collection.objects.get(
                network=self.network,
                address=self.contract.address,
            )
        except Collection.DoesNotExist:
            logger.warning(
                f"Collection not found. Network: {self.network}, address: {self.contract.address}"
            )
            return
        token_id = data.token_id
        new_owner = self.get_owner(data.new_owner)
        old_owner = self.get_owner(data.old_owner)

        token = self.get_buyable_token(
            token_id=token_id,
            collection=collection,
            smart_contract=self.contract,
            is_mint=bool(old_owner.address == self.scanner.EMPTY_ADDRESS),
        )
        if token is None:
            logger.warning(f"Token not found")
            return

        if old_owner.address == self.scanner.EMPTY_ADDRESS:
            logger.debug(f"New mint event: {data}")
            self.mint_event(
                token=token,
                token_id=token_id,
                tx_hash=data.tx_hash,
                new_owner=new_owner,
            )
        elif new_owner.address == self.scanner.EMPTY_ADDRESS:
            logger.debug(f"New burn event: {data}")
            self.burn_event(
                token=token,
                tx_hash=data.tx_hash,
                amount=data.amount,
                old_owner=old_owner,
            )
            self.ownership_quantity_update(
                token=token,
                old_owner=old_owner,
                new_owner=None,
                amount=data.amount,
            )
        else:
            logger.debug(f"New transfer event: {data}")
            self.transfer_event(
                token=token,
                tx_hash=data.tx_hash,
                token_id=token_id,
                new_owner=new_owner,
                old_owner=old_owner,
                amount=data.amount,
            )
            self.ownership_quantity_update(
                token=token,
                old_owner=old_owner,
                new_owner=new_owner,
                amount=data.amount,
            )

    def get_buyable_token(
        self,
        token_id: int,
        collection: Collection,
        smart_contract,
        is_mint: bool,
    ) -> Token:
        if is_mint:
            ipfs = get_ipfs(token_id, smart_contract)
            return Token.objects.filter(
                ipfs=ipfs,
                collection=collection,
            ).first()
        return Token.objects.filter(
            internal_id=token_id,
            collection=collection,
        ).first()

    def mint_event(
        self,
        token: Token,
        token_id: int,
        tx_hash: str,
        new_owner: AdvUser,
    ) -> None:
        token.status = Status.COMMITTED
        token.internal_id = token_id
        token.tx_hash = tx_hash
        token.save()

        TokenHistory.objects.get_or_create(
            token=token,
            tx_hash=tx_hash,
            method="Mint",
            new_owner=new_owner,
            old_owner=None,
            price=None,
        )

    def burn_event(
        self,
        token: Token,
        tx_hash: str,
        amount: int,
        old_owner: AdvUser,
    ) -> None:
        if token.standart == "ERC721":
            token.status = Status.BURNED
            token.first().bid_set.all().delete()
        else:
            token.total_supply = max(token.total_supply - amount, 0)
            if token.total_supply == 0:
                token.status = Status.BURNED
                token.first().bid_set.all().delete()
        token.save()
        TokenHistory.objects.get_or_create(
            token=token,
            tx_hash=tx_hash,
            method="Burn",
            new_owner=None,
            old_owner=old_owner,
            price=None,
            amount=amount,
        )

    def transfer_event(
        self,
        token: Token,
        tx_hash: str,
        token_id: int,
        new_owner: AdvUser,
        old_owner: AdvUser,
        amount: int,
    ) -> None:
        token.tx_hash = tx_hash
        token.internal_id = token_id

        if token.standart == "ERC721":
            token.owner = new_owner
            token.selling = False
            token.currency_price = None

        token.save()

        if TokenHistory.objects.filter(tx_hash=tx_hash, method="Buy").exists():
            return

        TokenHistory.objects.update_or_create(
            tx_hash=tx_hash,
            defaults={
                "method": "Transfer",
                "token": token,
                "price": None,
                "amount": amount,
                "new_owner": new_owner,
                "old_owner": old_owner,
            },
        )

    def ownership_quantity_update(
        self,
        token: Token,
        old_owner: AdvUser,
        new_owner: AdvUser,
        amount: int,
    ) -> None:
        if old_owner is not None:
            try:
                ownership = Ownership.objects.get(owner=old_owner, token=token)
            except Ownership.DoesNotExist:
                logger.warning(
                    f"Ownership is not found: owner {old_owner}, token {token}"
                )
                return
            ownership.quantity = max(ownership.quantity - amount, 0)
            ownership.save()
            if ownership.quantity <= 0:
                ownership.delete()

        if new_owner is not None:
            ownership, created = Ownership.objects.update_or_create(
                owner=new_owner,
                token=token,
                defaults={
                    "currency_price": None,
                    "selling": False,
                },
            )
            ownership.quantity = F("quantity") + amount
            ownership.save()
            if created:
                token.owners.add(ownership)

class HandlerBuy(HandlerABC):
    TYPE = "buy"

    def save_event(self, event_data):
        data = self.scanner.parse_data_buy(event_data)
        logger.debug(f"New event: {data}")

        token = Token.objects.get(
            collection_address=data.collection_address,
            internal_id=data.token_id,
        )

        getattr(self, f"buy_{token.standart}")(token, data)

        self.refresh_token_history(token, data)

    def buy_ERC721(self, token: Token, data):
        new_owner = self.get_owner(data.buyer)
        token.owner = new_owner
        token.selling = False
        token.currency_price = None
        token.save()
        Bid.objects.filter(token=token).delete()

    def buy_ERC1155(self, token: Token, data):
        new_owner = self.get_owner(data.buyer)
        old_owner = self.get_owner(data.seller)
        owner = Ownership.objects.filter(
            owner=new_owner,
            token=token,
        ).first()

        token_history = TokenHistory.objects.filter(
            tx_hash=data.tx_hash,
            method="Transfer",
        )

        # TODO: discuss logic of token history
        if owner and not token_history.exists():
            owner.quantity = owner.quantity + data.amount
            owner.save()
        elif not owner:
            owner = Ownership.objects.create(
                owner=new_owner,
                token=token,
                quantity=data.amount,
            )
            token.owners.add(owner)

        if not token_history.exists():
            try:
                owner = Ownership.objects.get(owner=old_owner, token=token)
            except Ownership.DoesNotExist:
                logger.warning(f"Ownership not found owner {old_owner}, token {token}")
                return
            owner.quantity = max(owner.quantity - data.amount, 0)
            if owner.quantity:
                owner.save()
            if not owner.quantity:
                owner.delete()

        bet = Bid.objects.filter(token=token).order_by("-amount")
        sell_amount = data.amount
        if bet.exists():
            if sell_amount == bet.first().quantity:
                bet.delete()
            else:
                bet = bet.first()
                bet.quantity -= sell_amount
                bet.save()

    def refresh_token_history(self, token, data):
        new_owner = self.get_owner(data.buyer)
        old_owner = self.get_owner(data.seller)

        decimals = token.currency.get_decimals
        price = Decimal(data.price / decimals)

        TokenHistory.objects.update_or_create(
            tx_hash=data.tx_hash,
            defaults={
                "method": "Buy",
                "amount": data.amount,
                "price": price,
                "token": token,
                "new_owner": new_owner,
                "old_owner": old_owner,
            },
        )


class HandlerApproveBet(HandlerABC):
    TYPE = "approve"

    def save_event(self, event_data):
        data = self.scanner.parse_data_approve(event_data)
        logger.debug(f"New event: {data}")

        if data.exchange != self.network.exchange_address:
            return

        bet = Bid.objects.filter(user__username=data.user)
        if not bet.exists():
            return

        for item in bet:
            if data.wad > item.quantity * item.amount:
                item.state = Status.COMMITTED
                item.save()
                BidsHistory.objects.create(
                    token=item.token,
                    user=item.user,
                    price=item.amount,
                    date=item.created_at,
                )
