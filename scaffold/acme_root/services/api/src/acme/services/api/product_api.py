"""What this product adds to the platform's API, declared once: each
namespace's routers and its service factory (`products.ProductApi`), the
namespace itself declared beside the product's kinds
(`acme.om.product_namespaces`). HOSTED, the services root, and the API's
container read `PRODUCT_API`, so no wiring file names a product's
namespace. The platform's own adds nothing."""

from acme.services.api.products import ProductApi

PRODUCT_API = ProductApi()
