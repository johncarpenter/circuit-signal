# Data Notes

## Description
This data is from the POS of a bakery chain in California. The bakery is Portos Bakery. https://www.portosbakery.com/

This data lake contains 1 dataset(s) (portos_items_2024_2025) with ~36,485,867 total rows.

<!-- Add context about the data source, business domain, and any relevant background. -->

## Datasets

### portos_items_2024_2025
- **Rows**: 36,485,867
- **Signature**: T3-D4-V3
- **Time column**: `created` (hourly)
- **Discriminators**: store_id, description, seatnumber, store_name
- **Value columns**: sku, amount, quantity

## Normalizations

<!-- Review and edit these rules. The pipeline applies them during analysis. -->

- `sku` in **portos_items_2024_2025**: mean=830,571.40, range=[231.00, 2,222,222.00]. <!-- Are these cents? If so: convert to dollars (divide by 100). -->
- `amount` in **portos_items_2024_2025**: mean=525.02, range=[-66,045.00, 12,600.00]. <!-- Are these cents? If so: convert to dollars (divide by 100). -->
- `created` (hourly, 2024-02-26 07:14:29.834944 to 2025-12-03 19:10:49.879295): <!-- What timezone? e.g. 'Times are UTC, convert to PDT' -->
- `updated` (hourly, 2024-02-26 07:14:29.834944 to 2025-12-03 19:10:49.879295): <!-- What timezone? e.g. 'Times are UTC, convert to PDT' -->
- `_fivetran_synced` (hourly, 2025-11-20 21:23:03.678000 to 2025-12-03 19:17:33.233000): <!-- What timezone? e.g. 'Times are UTC, convert to PDT' -->


- All amounts in the tables are recorded as cents. They should be converted to dollars when used in the analysis.
- Currency is USD.
- Times in the tables are UTC, convert those to PDT when used in the analysis.
