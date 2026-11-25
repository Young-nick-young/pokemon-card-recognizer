import csv
import tempfile
import unittest
from pathlib import Path
from catalogue_discovery import discover, compare
from tcgdex_discovery import retrieve
from reconcile_catalogues import reconcile
from prepare_discovered_set import prepare
from discover_set import run

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

    def test_full_onboarding_input(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"cards.csv"
            p.write_text("record_type,set,definition,name,collector_number,rarity,category,finish,patterns\ncard,Example,treatment,Pikachu,001/001,Common,Pokemon,normal,\n")
            report=run("Example",1,1,csv_path=p)["reports"][0]
            template={"name":"Example","set_id":"example","series":"Example","display_code":"EX","official_code":"EX","dataset_id":"ex","expected_cards":1,"denominator":1,"spreadsheet_id":"test-only","script_url":"https://example.invalid/test"}
            approvals={"1":{"reviewed":True,"reference_image":"https://example.invalid/1.png","evidence":"synthetic fixture","card_type":"Pokemon","inventory_variants":["normal"]}}
            candidate=prepare(report,template,approvals)
            self.assertEqual(candidate["cards"][0]["variants"],["normal"])
            self.assertEqual(candidate["cards"][0]["inventory_variants"],["normal"])
            approvals["1"]["reviewed"]=False
            with self.assertRaises(ValueError):
                prepare(report,template,approvals)
            approvals["1"]["reviewed"]=True
            report["cards"][0]["name"]="Pikachu ex"
            with self.assertRaises(ValueError):
                prepare(report,template,approvals)

if __name__=="__main__":
    unittest.main()
