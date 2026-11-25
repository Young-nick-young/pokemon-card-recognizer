import csv
import tempfile
import unittest
from pathlib import Path
from catalogue_discovery import discover, compare
from tcgdex_discovery import retrieve
from reconcile_catalogues import reconcile
from prepare_discovered_set import prepare
from discover_set import run
from tcgcsv_marketplace_evidence import reconcile_marketplace
import json
import shutil
import subprocess
import sys

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

    def test_marketplace_evidence(self):
        card={"number":{"sortKey":1,"display":"001/001"},"cardId":"ex-001","name":"Pikachu"}
        product={"productId":10,"categoryId":3,"groupId":20,"name":"Pikachu","extendedData":[{"name":"Number","value":"001/001"}]}
        def wrap(x): return {"success":True,"errors":[],"results":x}
        results=reconcile_marketplace(wrap([product,{**product,"productId":11,"name":"Pikachu Jumbo"},{**product,"productId":12,"name":"Pikachu (Stamped)"}]),wrap([{"productId":10,"subTypeName":"Normal"},{"productId":10,"subTypeName":"Reverse Holofoil"}]),{"cards":[card]},20)
        self.assertEqual(results["excluded_jumbo"],1)
        self.assertEqual(results["matches"][0]["standard_variant_evidence"],["normal","reverse-holo"])
        self.assertEqual(len(results["review"]),1)
        self.assertFalse(results["exclusive_printings_verified"])

    def test_actual_scaffold_in_temporary_repository(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            work=Path(d)/"repo"
            shutil.copytree(root,work,ignore=shutil.ignore_patterns(".git","__pycache__","*.pkl"))
            report={"status":"REVIEW_REQUIRED","source":"synthetic fixture","set":"Discovery Example","card_count":1,"cards":[{"number":1,"name":"Pikachu","rarity":"Common","category":"Pokemon","standard_variants":["normal"]}]}
            template={"name":"Discovery Example","set_id":"discovery-example","series":"Example","display_code":"DX","official_code":"DX","dataset_id":"discovery-example","expected_cards":1,"denominator":1,"spreadsheet_id":"test-only","script_url":"https://example.invalid/test"}
            approvals={"1":{"reviewed":True,"reference_image":"https://example.invalid/1.png","evidence":"synthetic fixture","card_type":"Pokemon","inventory_variants":["normal"]}}
            candidate=prepare(report,template,approvals)
            definition=Path(d)/"definition.json"
            definition.write_text(json.dumps(candidate))
            p=subprocess.run([sys.executable,str(work/"tools/onboard_set.py"),"--definition",str(definition),"--recognizer-root",str(work)],capture_output=True,text=True)
            self.assertEqual(p.returncode,3,p.stdout+p.stderr)
            self.assertIn("PROMOTION GATE: BLOCKED",p.stdout)
            cards=json.loads((work/"sets/discovery_example/cards.json").read_text())
            self.assertEqual(cards["cards"][0]["variants"],["normal"])

if __name__=="__main__":
    unittest.main()
