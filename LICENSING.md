# Source and SDK licensing

RunTeams is free to use and its local product source is available under the
RunTeams Source Available License 1.0 in LICENSE. This license permits commercial
work using the product and restricts commercial redistribution of the product.
It is not an OSI-approved open-source license.

允许：个人或企业内部使用、修改源码用于内部工作、用产品为客户交付付费服务和成果，
以及开发和销售独立员工、流水线、技能或集成。

需要另行书面授权：将 RunTeams 或其修改版打包、换标、嵌入后作为商业产品分发，
或将其功能作为商业托管产品提供给他人。免费档不豁免商业产品的再分发限制。

The English LICENSE is the governing text. This explanation does not alter it.

## SDK and authored assets

SDK sources live in this same repository:

| Location | Purpose | License |
| --- | --- | --- |
| sdk/runtime, sdk/view, sdk/ui | Libraries for independent authored programs | Apache-2.0, as recorded in each package |
| sdk/shared, sdk/mcp-host | Shared contracts and product host source | Root LICENSE, except explicitly identified third-party components |
| runteams_creator_dev | Scaffolding and developer commands | Root LICENSE |
| runteams_core/devtools/export_creator_devkit.py | Developer-kit exporter | Root LICENSE |

The exported kit retains the tool licenses. Its source/ directory is your
editable author project: the template permission in TEMPLATE_LICENSE.txt permits
using, modifying and distributing that template as part of your own assets,
including paid assets. It does not relicense the accompanying _runteams tools.
Using the SDK imposes no requirement to assign ownership of your authored assets.

## Third-party and earlier copies

Third-party licenses remain effective; they are not replaced by the root
license. Retain notices in source and binary distributions. In particular,
unmodified MPL-2.0 dependencies retain their source-availability obligations.
See THIRD_PARTY_DOCUMENTS.md and THIRD_PARTY_INVENTORY.json.

This first public source snapshot excludes unpublished preparation history.
The new license does not retroactively revoke valid licenses for earlier copies.
Any separately published earlier material must be evaluated under its actual
license. Public availability alone does not establish copyright ownership.
