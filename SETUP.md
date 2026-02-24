# StyleNest Fashion Website — Chatbot Setup Guide

## Files in this folder
- index.html      → Homepage (hero, categories, best sellers, testimonials)
- women.html      → Women's collection (dresses, tops, sarees, kurtis)
- men.html        → Men's collection (shirts, t-shirts, ethnic, jackets)
- accessories.html → Bags, jewellery, watches
- sale.html        → Sale page with countdown timer, top deals, under ₹999
- about.html       → Company info, shipping policy, return policy, FAQ, contact

## Products in the catalog (for chatbot RAG testing)

### Women's
- Silk Wrap Midi Dress — ₹2,999 (was ₹4,999) — StyleNest Originals — Sizes XS–XL
- Boho Floral Maxi Dress — ₹3,499 — ONLY — Sizes XS–XL
- Ribbed Bodycon Midi Dress — ₹1,724 (was ₹2,299) — StyleNest Originals
- Chiffon Ruffled Sleeve Top — ₹899 — Libas — Sizes XS–XXL
- Cotton Crop Top — ₹599 — StyleNest Originals — 12 colors
- Satin Formal Office Blouse — ₹1,299 — Aurelia
- Banarasi Pure Silk Saree — ₹6,299 (was ₹8,999) — Rang Manch
- Printed Georgette Party Saree — ₹2,499 — Libas
- Handloom Cotton Daily Wear Saree — ₹1,199 — Rang Manch
- Printed Floral A-Line Kurti — ₹799 (was ₹1,299) — Rang Manch — Sizes S–3XL
- Embroidered Anarkali Kurti — ₹2,199 — Aurelia — Sizes S–XXL
- Linen Straight Kurta Set — ₹1,699 — Libas — Sizes S–3XL

### Men's
- Premium Linen Casual Shirt — ₹1,799 — Urban Thread — Sizes S–XXL
- Slim Fit Formal Dress Shirt — ₹2,499 — Arrow — Sizes 38–44
- Tropical Print Vacation Shirt — ₹1,049 (was ₹1,499) — Roadster
- Classic Cotton Round Neck Tee — ₹499 — StyleNest Men — 20 colors, Sizes S–3XL
- Premium Pique Polo T-Shirt — ₹1,299 — Urban Thread — Sizes S–XXL
- Oversized Graphic Print Tee — ₹799 — Roadster — Sizes S–XXL
- Embroidered Silk Kurta Set — ₹4,499 (was ₹5,999) — Manyavar — Sizes S–XXL
- Brocade Nehru Jacket — ₹3,299 — Manyavar — Sizes S–XXL
- Classic Bomber Jacket — ₹2,599 (was ₹3,999) — StyleNest Men — Sizes S–XXL
- Washed Denim Trucker Jacket — ₹2,299 — Roadster — Sizes S–XXL
- Lightweight Puffer Jacket — ₹3,999 — Urban Thread — Sizes S–3XL

### Accessories
- Genuine Leather Tote Bag — ₹3,299 (was ₹5,499) — LuxeCarry
- Mini Croc-texture Sling Bag — ₹1,299 — StyleNest Originals
- Vegan Leather Laptop Backpack — ₹2,799 — LuxeCarry
- Embellished Evening Clutch — ₹1,899 — StyleNest Originals
- Layered Delicate Gold Necklace — ₹2,499 — GoldBloom
- Oxidised Silver Jhumka Earrings — ₹799 — Rang Manch
- Freshwater Pearl Bracelet — ₹3,299 — GoldBloom
- Kundan Bridal Jewellery Set — ₹3,999 (was ₹4,999) — Rang Manch
- Rose Gold Minimalist Ladies Watch — ₹4,499 — Timex
- Chronograph Sports Watch — ₹3,299 — Fastrack
- Health & Fitness Smartwatch — ₹6,799 (was ₹7,999) — StyleNest Tech
- Couple Watch Gift Set — ₹7,499 — Timex

## Key policies (for chatbot to answer)
- Free delivery above ₹999 (standard 4-7 days)
- Express delivery: ₹199 (1-3 days)
- Same-day delivery in Mumbai, Delhi, Bangalore, Hyderabad: ₹299
- COD available, ₹50 handling charge
- 30-day returns, 30-day free size exchange
- Refunds in 5-7 business days
- Gold Membership: ₹299/year — free express delivery + 10% extra off
- Phone: 1800-103-7799 | Email: hello@stylenest.in | WhatsApp: +91 98100-77991

## Setup Steps

### Step 1: Register StyleNest as a client in your backend
Run this (replace base URL if different):
```bash
curl -X POST http://localhost:8000/clients \
  -H "Content-Type: application/json" \
  -d '{
    "name": "StyleNest",
    "website_url": "http://localhost:3001",
    "bot_name": "StyleBot",
    "business_name": "StyleNest"
  }'
```
Save the returned `client_id` and `api_key`.

### Step 2: Replace credentials in all HTML files
Find: data-client-id="STYLENEST_CLIENT_ID"
Find: data-api-key="STYLENEST_API_KEY"
Replace both with actual values from Step 1.

### Step 3: Serve the fashion website
```bash
cd fashion_website
python3 -m http.server 3001
```
Then open: http://localhost:3001

### Step 4: Trigger the crawler
```bash
curl -X POST http://localhost:8000/crawl \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{"client_id": "YOUR_CLIENT_ID"}'
```

### Step 5: Test the chatbot!
Open http://localhost:3001 and test these queries:

**RAG Search Agent:**
- "Show me women's dresses"
- "What bags do you have?"
- "Do you have silk sarees?"

**Sales Agent:**
- "I need a gift for my girlfriend under ₹3000"
- "What's best for a wedding function?"
- "Recommend something formal for office"

**Comparison Agent:**
- "Compare Silk Wrap Dress vs Floral Maxi Dress"
- "What's better for everyday wear — cotton tee or polo?"
- "Leather tote vs backpack — which is more practical?"

**Customer Support Agent:**
- "What is your return policy?"
- "How long does delivery take?"
- "Do you have COD?"
- "What sizes are available?"
