# Define the Schema-Profile Support Policy

**Type:** Grilling  
**Status:** Closed  
**Blocks:** Define the Python-to-Core-Data writer contract; define release gates

## Question

Which recognized schema profiles does MoneyWiz Tools support for reading and
for live writes, and how does each interface fail when it encounters an
unrecognized profile?

## Resolution

Every recognized schema profile is supported for reading. Live writes are
allowed only for a verified write profile, initially the observed MoneyWiz 2026
model `48` profile. An unrecognized profile permits diagnostic reading only and
never live persistence.
