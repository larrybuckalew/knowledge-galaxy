# Cropster

**Cropster RoastLogId** — roast logging & analytics platform. Core of [[Roasting Process]] data pipeline.

**Usage:**
- Every roast logged automatically via Loring API (BT, ET, RoR, fan, drum, gas)
- Profile templates: 12 base profiles (per origin/process/roast level)
- Batch ID format: YYMMDD-ROASTER-SEQ (e.g., 251104-LOR-03)
- Cupping scores linked to batch → [[Quality Control]] release gate

**Integrations:**
- Loring S35: native API (real-time curve)
- Probat P12: Phidget bridge (manual start/stop, auto curve)
- IKAWA Pro: USB + Cropster app
- Cin7 ([[Inventory Management]]): batch → lot allocation webhook
- Shopify: roast date → product freshness badge

**Reporting:** Weekly roast consistency report (Marcus Chen). Monthly origin performance (Lena Kowalski). [[Quality Control]] trend dashboard.

**Cost:** $299/mo (Professional, 5 users). Marcus, Priya, Diego, Lena, Keiko.

**Backup:** Local CSV export daily 2 AM. Google Drive sync.

See: [[Roasting Process]], [[Quality Control]], [[Inventory Management]], [[Green Coffee Inventory]], [[Marcus Chen]], [[Lena Kowalski]]
