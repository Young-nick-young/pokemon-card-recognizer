import csv
import tempfile
import unittest
from pathlib import Path
from catalogue_discovery import discover, compare
from tcgdex_discovery import retrieve
from reconcile_catalogues import reconcile

class DiscoveryTests(unittest.TestCase):
    def test_csv_and_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"cards.csv"
            header="record_type,set,definition,name,collector_number,rarity,category,finish,patterns\n"
            row="card,Example,treatment,Pikachu,001/001,Common,Pokemon,normal,\n"
            p.write_text(header+row)
            cards=discover(p,"Example",1,1)
            self.assertEqual(cards[0]["standard_variants"],["normal"])
            self.assertEqual(compare(cards,{"cards":[{"number":{"sortKey":1},"name":"Pikachu","cardId":"ex-001","variants":["normal","other"]}]} )[0]["unconfirmed_existing"],["other"])
            p.write_text(header+row+row)
            with self.assertRaises(ValueError):
                discover(p,"Example",1,1)
    def test_api_and_reconciliation(self):
        brief={"id":"ex-1","localId":"001","name":"Pikachu"}
        full={**brief,"set":{"id":"ex"},"rarity":"Common","category":"Pokemon","variants":{"normal":True,"reverse":False}}
        def get(url):
            return {"id":"ex","name":"Example","cards":[brief]} if "/sets/" in url else full
        report=retrieve("en","ex",1,get=get,pause=lambda _:None)
        self.assertEqual(report["cards"][0]["standard_variants"],["normal"])
        other={"status":"REVIEW_REQUIRED","set":"Example","source":"fixture","card_count":1,"cards":[{"number":1,"name":"Pikachu","rarity":"Common","category":"Pokemon","standard_variants":["normal"]}]}
        self.assertEqual(reconcile(report,other)["agreement_count"],1)
        other["cards"][0]["standard_variants"]=["holo"]
        self.assertEqual(reconcile(report,other)["conflict_count"],1)
        with self.assertRaises(ValueError):
            retrieve("en","ex",2,get=get,pause=lambda _:None)

if __name__=="__main__":
    unittest.main()
