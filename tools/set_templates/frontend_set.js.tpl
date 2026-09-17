const {js_constant} = Object.freeze({{
  id: {set_id_json},
  name: {display_name_json},
  setCode: {display_code_json},
  series: {series_json},
  officialCode: {official_code_json},
  datasetId: {dataset_id_json},
  denominator: {denominator},
  maxCard: {expected_cards},
  imageSet: null,
  scriptUrl: {script_url_json},
  inventorySetIdParam: {inventory_set_id_param},
  variants: {variant_labels_json},
  dynamicVariants: false,
  schemaPackageUrl:
    RECOGNIZER_URL +
    {package_route_json}
}});

SetRegistry.register(
  {js_constant}
);
