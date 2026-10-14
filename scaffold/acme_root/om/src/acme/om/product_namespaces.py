"""What this product adds to the platform's namespaces, declared once: each
namespace's name, how its managers are built over the storage and the
platform's managers, and the purges the maintenance worker runs of it, each
before the purge it names (`platform_root.ProductNamespaces`). Its routes
and its service are declared beside its API
(`acme.services.api.product_api`). The maintenance worker and the API read
`PRODUCT_NAMESPACES`, so no wiring file names a product's namespace. The
platform's own adds nothing."""

from acme.om.platform_root import ProductNamespaces

PRODUCT_NAMESPACES = ProductNamespaces()
