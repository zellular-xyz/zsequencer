import json
import logging
import time
import threading

from ecdsa import SigningKey, VerifyingKey, SECP256k1, BadSignatureError
from eigensdk.crypto.bls import attestation

from local_zellular import Zellular

logging.basicConfig(level=logging.INFO)

APP_NAME: str = "simple_app"
OPERATORS_FILE: str = "/tmp/zellular_dev_net/operators.json"
RANDOM_NODE_SOCKET: str = "http://localhost:6002"


def parse_operators_file():
    with open(OPERATORS_FILE) as operators_file:
        operators_data = json.load(operators_file)

        for operator_id in operators_data:
            public_key_g2 = attestation.new_zero_g2_point()
            public_key_g2.setStr(operators_data[operator_id]['public_key_g2'].encode("utf-8"))
            operators_data[operator_id]['public_key_g2'] = public_key_g2

        return operators_data


class Wallet:
    BATCH_THRESHOLD = 2

    def __init__(self, verifier, logger, last_block_index=0):
        self.balances = {}
        self.transactions_batch = []
        self.verifier = verifier
        self.logger = logger
        self.last_block_index = last_block_index

    def register_user(self, public_key_hex, initial_balance):
        if public_key_hex in self.balances:
            raise ValueError("User already registered")
        self.balances[public_key_hex] = initial_balance

    def get_balance(self, public_key_hex):
        if public_key_hex not in self.balances:
            raise ValueError("User not registered")
        return self.balances.get(public_key_hex)

    def transfer(self, pub_sender, pub_recipient, amount, timestamp, msg_signature):
        if self.get_balance(pub_sender) < amount:
            raise ValueError("Insufficient balance")
        if amount <= 0:
            raise ValueError("Transfer amount must be positive")

        transaction_data = {
            "sender": pub_sender,
            "recipient": pub_recipient,
            "amount": amount,
            "timestamp": timestamp
        }
        transaction_bytes = json.dumps(transaction_data, sort_keys=True).encode("utf-8")

        try:
            pub_key = VerifyingKey.from_string(bytes.fromhex(pub_sender), curve=SECP256k1)
            pub_key.verify(bytes.fromhex(msg_signature), transaction_bytes)  # Signature verification
        except (BadSignatureError, ValueError) as e:
            raise ValueError("Signature verification failed") from e

        msg = {
            "transaction": transaction_data,
            "signature": msg_signature,
            "pub_key": transaction_data.get('sender')
        }
        self.transactions_batch.append(msg)
        if len(self.transactions_batch) == self.BATCH_THRESHOLD:
            self.verifier.send(batch=self.transactions_batch)
            self.transactions_batch = []

    def receive_transactions(self):
        for (received_batch, index) in self.verifier.iterate_batches(after=self.last_block_index):
            self.logger.info(f'Received batch idx:{index} with length of:{len(received_batch)}')

            self.last_block_index = index
            for transaction_msg in received_batch:
                transaction, signature, pub_key = (transaction_msg.get('transaction'),
                                                   transaction_msg.get('signature'),
                                                   transaction_msg.get('pub_key'))
                '''
                verify each transaction signature based on transaction content and pub_key
                to prevent node malicious activity
                '''
                transaction_bytes = json.dumps(transaction, sort_keys=True).encode("utf-8")

                try:
                    pub_key = VerifyingKey.from_string(bytes.fromhex(pub_key), curve=SECP256k1)
                    pub_key.verify(bytes.fromhex(signature), transaction_bytes)  # Signature verification
                except (BadSignatureError, ValueError) as e:
                    raise ValueError("Signature verification failed") from e

                self.balances[transaction.get('sender')] -= transaction.get('amount')
                self.balances[transaction.get('recipient')] += transaction.get('amount')


def generate_key_pair():
    private_key = SigningKey.generate(curve=SECP256k1)  # Generate private key
    public_key = private_key.get_verifying_key()  # Derive public key
    return private_key.to_string().hex(), public_key.to_string().hex()


def create_user_key_mapping(usernames):
    user_keys = {}
    for username in usernames:
        private_key, public_key = generate_key_pair()
        user_keys[username] = {"private_key": private_key, "public_key": public_key}
    return user_keys


def simulate_sdk():
    verifier = Zellular(app_name=APP_NAME,
                        base_url=RANDOM_NODE_SOCKET,
                        operators=parse_operators_file(),
                        threshold_percent=20)
    logger = logging.getLogger(__name__)

    usernames = ["Alice", "Bob", "Charlie"]
    user_key_mapping = create_user_key_mapping(usernames)
    wallet = Wallet(verifier=verifier, logger=logger)

    # Start the receive_transactions method in a new thread
    receive_thread = threading.Thread(target=wallet.receive_transactions)
    receive_thread.daemon = True  # Daemonize thread to stop it when the main program exits
    receive_thread.start()

    sample_transactions = {
        usernames[0]: [
            {
                "sender": user_key_mapping.get(usernames[0]).get('public_key'),
                "recipient": user_key_mapping.get(usernames[1]).get('public_key'),
                "amount": 11,
                "timestamp": time.time()
            },
            {
                "sender": user_key_mapping.get(usernames[0]).get('public_key'),
                "recipient": user_key_mapping.get(usernames[2]).get('public_key'),
                "amount": 20,
                "timestamp": time.time()
            },
            {
                "sender": user_key_mapping.get(usernames[0]).get('public_key'),
                "recipient": user_key_mapping.get(usernames[1]).get('public_key'),
                "amount": 15,
                "timestamp": time.time()
            },
            {
                "sender": user_key_mapping.get(usernames[0]).get('public_key'),
                "recipient": user_key_mapping.get(usernames[2]).get('public_key'),
                "amount": 35,
                "timestamp": time.time()
            }
        ]
    }

    for username in usernames:
        wallet.register_user(public_key_hex=user_key_mapping.get(username).get('public_key'),
                             initial_balance=1000)

    for username, transactions in sample_transactions.items():
        for transaction in transactions:
            transaction_bytes = json.dumps(transaction, sort_keys=True).encode("utf-8")
            sender_private_key = user_key_mapping.get(username).get('private_key')
            transaction_signature = (SigningKey.from_string(bytes.fromhex(sender_private_key), curve=SECP256k1)
                                     .sign(transaction_bytes).hex())

            sender_public_key = transaction.get('sender')
            recipient_public_key = transaction.get('recipient')
            amount = transaction.get('amount')
            timestamp = transaction.get('timestamp')

            wallet.transfer(
                pub_sender=sender_public_key,
                pub_recipient=recipient_public_key,
                amount=amount,
                timestamp=timestamp,
                msg_signature=transaction_signature)


def main():
    simulate_sdk()
    # send_transaction()


if __name__ == '__main__':
    main()
