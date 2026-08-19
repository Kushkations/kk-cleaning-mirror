# Mozart Properties — Rent Book

A single-file web app (`index.html`) for tracking rent across all Mozart
properties: 6th Ave, Colorado, Duplex Loan, Granby Condo, Home Mortgage,
Martin Luther King Duplex, Mozart Place, Mozart Properties (units, garages,
parking), Sheridan Apts, and the truck loan. Seeded from the Aug 2026 paper
sheet — 43 rent rows totaling $37,643.00/month, matching the sheet's Totals
line.

## What it does

**Landlord side** (PIN-locked, starting PIN `1234`):
- Month view: mark each unit paid (Venmo / Cash App / Zelle / Direct Deposit /
  Cash / Check), see collected vs. still-owed totals, partial payments,
  a not-paid filter, and a per-method breakdown.
- Year view: a 12-month grid per unit (✓ paid / ◐ partial / ✕ not paid).
- Tenants tab: edit tenants, rents, vacancies; add units or new properties.
- Settings: payment handles, PIN change, JSON backup/restore, monthly CSV
  export, print view.

**Tenant side**: each unit gets a personal payment link (📲 button) showing
their rent and the landlord's Venmo/Cash App/Zelle. After paying, the tenant
taps "I paid" which opens a pre-filled text to the landlord; the link inside
that text records the payment in the landlord's book automatically when tapped
(de-duplicated, tagged "sent by tenant").

## Storage

All data lives in the landlord's browser (`localStorage`) — no server, no
third-party storage. Backups via Settings → "Save a backup file".

## Deploying

Static site — deploy this folder as its own Vercel project (e.g.
`mozart-properties`) with no build step. Turn OFF Deployment Protection
(Vercel Authentication) for the project so tenants can open their links.
