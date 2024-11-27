from config import zconfig
import zellular
import json
from pprint import pprint

# import zellular
# import json
# import requests
# from uuid import uuid4
# import time
#
# #
# operators = zellular.get_operators()
#
# pprint(operators)

APP_NAME: str = "simple_app"


def main():
    verifier = zellular.Zellular(app_name=APP_NAME,
                                 base_url='http://176.9.7.122:8241')
    for batch, index in verifier.batches():
        txs = json.loads(batch)
        for i, tx in enumerate(txs):
            print(index, i, tx)


if __name__ == '__main__':
    main()
