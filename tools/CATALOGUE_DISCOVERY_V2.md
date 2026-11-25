# Catalogue Discovery v2 (candidate only)

Use this tooling before the existing onboarding pipeline, not during phone scanning.
No paid subscriptions or automatic production writes.

## 1. Discover
```sh
python tools/tcgdex_discovery.py --language en --set-id me03 --expected 124 --output perfect-order-tcgdex.json
python tools/discover_set.py --set-name "Perfect Order" --expected 124 --denominator 88 --tcgdex-report perfect-order-tcgdex.json --csv YOUR_TREATMENT_EXPORT.csv --catalogue sets/perfect_order/cards.json --output perfect-order-review.json
```
Omit --csv if unavailable. Use --tcgdex-id me03 instead of --tcgdex-report for a fresh retrieval.
TCGdex is community-maintained; reuse cached reports, respect provider guidelines, and do not assume agreement is independent evidence. TCGOdds treatment CSV is supported. SixByFive's TCGPlayer exporter is powered by TCGCSV; its export format is not yet directly supported. For permitted local TCGCSV JSON downloads, use:
```sh
python tools/tcgcsv_marketplace_evidence.py --products products.json --prices prices.json --group-id YOUR_GROUP_ID --catalogue sets/perfect_order/cards.json --output marketplace-review.json
```
Marketplace printing labels are evidence, not proof of a complete physical printing list. Jumbo and oversized products are excluded. Unknown or stamped listings require explicit review. Do not commit downloaded marketplace data or copyrighted artwork to the public repo.

## 2. Prepare a new-set candidate
Use one reviewed discovery report (an individual report from the combined output), a normal set definition template, and explicit per-card approvals keyed by collector number. Each approval requires reviewed: true, a reference_image from an approved source, evidence, card_type and inventory_variants. The current scaffold is English/numeric only. Nonstandard numbering needs its own adapter. No images are downloaded by discovery.
```sh
python tools/prepare_discovered_set.py --report reviewed-source.json --template definition-template.json --approvals approvals.json --output definition.json
python tools/onboard_set.py --definition definition.json
```
Only run the second command in an isolated development checkout. Existing scaffold and promotion gates remain in force. No auto-deployment. Existing production cards or quantities are not modified.

## 3. Tests and speed
```sh
python -m unittest discover -s tools -p test_catalogue_discovery.py -v
python tools/validate_tcgdex_live.py
python tools/benchmark_sift_threads.py
```
Run the last two only when needed. The synthetic recognition benchmark is not a substitute for labelled real phone photographs or Render timing measurements.
