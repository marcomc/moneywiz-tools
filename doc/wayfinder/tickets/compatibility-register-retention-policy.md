# Define the Compatibility Register and Retention Policy

**Type:** Grilling  
**Status:** Closed  
**Blocks:** Release support promise and future capability rollout

## Question

Which schema profiles and profile-by-operation capabilities must each MoneyWiz
Tools release retain, how are they deprecated, and how does a new product
feature become available on an older supported profile?

## Resolution

Every release supports all entries in its version-controlled compatibility
register. Each retained profile runs the release regression corpus. A profile
or capability is removed only through explicit deprecation; a new feature is
enabled on an older retained profile when its adapter and capability evidence
pass.
