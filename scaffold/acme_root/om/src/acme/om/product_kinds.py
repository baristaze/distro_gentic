"""What this product adds to the platform's kinds, declared once: its agent
kinds, its tools and the classes they declare, its work and claimant kinds,
its secret owners, its stream kinds, and its executors (`root.ProductKinds`).
Every process's entry point reads `PRODUCT_KINDS`: the API's container, the
session runner's, and the maintenance worker's, so a kind one process knows
every other knows. The platform's own adds nothing."""

from acme.om.root import ProductKinds

PRODUCT_KINDS = ProductKinds()
