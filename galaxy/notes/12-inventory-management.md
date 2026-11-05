# Inventory Management

Real-time tracking via **Cin7** (cloud ERP) integrated with Shopify + ReCharge.

**Green Coffee** (warehouse)
- Lot-level tracking: origin, process, harvest year, arrival date, bag count
- FIFO allocation to [[Roasting Process]] schedule
- Reorder points: 10 bags (standard), 15 bags (high-demand origins)
- Cycle counts: monthly full, weekly spot-checks on active lots

**Roasted Coffee** (production floor)
- Batch tracking: roast date, profile ID, yield %, QC status
- Shelf life: 21 days peak, 60 days max (nitrogen flushed)
- Allocation priority: [[Subscription Program]] → Wholesale → Cafe → Online
- Aging report daily at 6 AM — triggers discount/donation at day 18

**Packaging Materials**
- Bag stock: 3-month buffer (supply chain 8-week lead)
- Labels: printed on-demand (thermal transfer)
- Boxes: flat-packed, 2-week buffer

**Retail Merch** (cafe)
- Mugs, brewers, filters — Square POS sync

Integrations: Cin7 ↔ Shopify (orders), Cin7 ↔ ReCharge (subscriptions), Cin7 ↔ QuickBooks (accounting).

See: [[Roasting Process]], [[Subscription Program]], [[Packaging Team]], [[Financials]]
